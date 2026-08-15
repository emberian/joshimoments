"""Callouts as a VOLATILITY signal — the operator's reframe, measured.

THE QUESTION, AND WHY IT IS NOT THE ONE ALREADY ANSWERED
--------------------------------------------------------
``studies/RESULT_callout_edge.md`` and ``RESULT_caller_wallets.md`` measured
``E[return | callout]`` and found an anti-signal: buying what the feed names returns
**-11.9% at 1 h** and **-43.6% at 8 h**, and every loudness proxy is monotonically worse.
That is a claim about DIRECTION, and the operator's objection to it is correct: their
strategy does not take direction. They scalp wiggles at the bottom of collapsed coins, and
an LP position takes no view at all. Both harvest **two-sided flow**.

The mechanism the two prior studies actually established supports this reframe rather than
the original hypothesis. ``RESULT_caller_wallets.md`` measured that 51.4% of the feed is
machine-generated referral spam and that the one caller whose wallet overlap survived a
null was the *echo* of a 161-wallet buy burst 26 seconds earlier. A callout is therefore
not a cause; it is a **latency-delayed marker of an on-chain flow burst that already
happened**. A marker of flow is worthless for direction and is exactly what a volatility
harvester wants.

So: conditional on the free columns (market cap, age -- the reigning baselines, which score
AUC 0.796 at 1 h where the callout block scores 0.471), does callout activity predict

    (a) realized volatility over the next 1 h / 4 h / 8 h,
    (b) two-sided flow persistence -- buy AND sell counts staying elevated,
    (c) WIGGLE QUALITY -- the amplitude and frequency of oscillations that clear round-trip
        friction, at the bottom of collapsed coins?

THE INSTRUMENT, AND THE ONE IDENTITY THAT MAKES IT FREE
-------------------------------------------------------
Prices come from ``state/bulk_pump/daily/`` -- 106.6M rows, ten UTC days, every pump.fun
coin -- not from the boards tape. That choice is the study, because the boards tape prices
a coin only while it sits in some board's top 50, and board membership is *downstream of
the callout*: conditioning the outcome on it is a collider, and it makes "stopped trading"
look like missing data when it is the outcome itself. The bulk tape prices a coin whether
or not anyone is watching, and it contains the whole population, so the matched control arm
that ``RESULT_callout_edge.md`` §9 asked for is free rather than a second collection.

A pump.fun bonding-curve trade carries only the TOKEN leg on chain (the curve holds native
SOL in the PDA's lamports, not a token balance), so the SOL side is invisible in this
corpus. It does not need to be visible. On a constant product ``k = v_sol * v_tok``::

    price = v_sol / v_tok = k / v_tok^2        =>      log p = log k - 2 log v_tok

and ``v_tok = curve_ata_balance + OFFSET``. **Both constants cancel out of every quantity
this study measures**, because volatility, drawdown and wiggle amplitude are all functions
of log-price DIFFERENCES::

    d log p = -2 d log(ata_balance + OFFSET)

MEASURED, not assumed (``--validate``): ASOF-joining 27,027 board observations of
non-migrated mints to the last bulk-tape trade at or before them, ``v_tok - ata_balance``
has median **exactly 7.30e13** with an IQR of [7.23e13, 7.41e13] (+/-1.5%, and the spread is
board staleness -- the snapshot lags the trade), and ``v_sol * v_tok`` is within 1e-6 of
**3.219e25** for 64.3% of rows, log k flat at 58.7337 across the p10-p90 band. Those are the
published launch parameters (30 SOL virtual, 1.073e9 virtual tokens) recovered from chain.
The remaining rows are coins on a different curve configuration; a different ``k`` cancels
exactly, and a different offset is a <=1.5% scale effect on a quantity compared between two
arms that both carry it.

For a MIGRATED coin the counterparty is a PumpSwap pool holding both legs, so
``log p = log(wsol) - log(tok)`` is read directly with no constants at all.

WHAT "WIGGLE QUALITY" MEANS HERE, AND WHY IT IS AN UPPER BOUND
--------------------------------------------------------------
A wiggle-scalper does not earn volatility; they earn the part of it that clears friction.
So the outcome is a zigzag (directional-change) filter at threshold ``f`` = the coin's own
round-trip cost at a 0.1 SOL clip, from ``shitcoims_paperdesk.friction`` (the CORRECTED
module: full three-leg taker costs, ~2.4% at the operator's clip size). It reports

* ``wiggle_n``   confirmed reversals of size >= f,
* ``wiggle_amp`` the summed log-magnitude of those swings,
* ``wiggle_net`` ``amp - n * f`` -- what is left after paying friction once per swing.

``wiggle_net`` is an **ORACLE bound**: it assumes the scalper turns at the exact extremes.
No live rule achieves it. It is the right outcome anyway, because the question is whether
the *opportunity* is there at all, and a null on the oracle bound is a null on every rule
inside it. Every number derived from it is labelled a bound, including the opportunity count.

METHODOLOGY (PROGRAM.md §3, and each item is here because it was violated somewhere)
-------------------------------------------------------------------------------------
* **Temporal split, entity-clustered.** Standard errors cluster on MINT; a mint never
  straddles arms. Callers are the other entity and are reported as a second clustering.
* **Rotation null, never i.i.d.** An i.i.d. null has manufactured an effect in this tree
  twice. The null here shifts EVERY callout time by one common circular offset, which
  preserves the diurnal envelope (measured amplitude 3.6-5.4x in this market, larger than
  any claimed callout effect) and each mint's own burst structure, and destroys only the
  alignment between a callout and its own coin's flow.
* **Both controls, always (§3.12).** A green known-zero arm certifies a constant-zero
  estimator exactly as readily as a working one -- that failure has already shipped here
  twice. So the null world is run BOTH ways: with no effect, and with a planted one.
* **BY-FDR** over the declared family. Benjamini-Yekutieli, not BH: the outcomes are
  measured on the same windows and are dependent by construction.
* **Censoring priced.** Dead coins are the population's defining feature. Horizons running
  past the tape end are administratively censored and counted; time-to-death is fitted with
  ``lifelines`` rather than by hand.

RUNNING IT
----------
``uv run --group research python -m studies.callout_volatility --build``    the panel (once)
``uv run --group research python -m studies.callout_volatility --validate`` the instrument
``uv run --group research python -m studies.callout_volatility --report``   the study
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import random
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Callable, Final, Sequence

REPO: Final[Path] = Path(__file__).resolve().parent.parent
BULK: Final[Path] = REPO / "state" / "bulk_pump" / "daily"
BOARDS: Final[Path] = REPO / "state" / "boards"
DATA: Final[Path] = REPO / "studies" / "data" / "callout_volatility"

#: pump.fun's launch curve, recovered from chain by ``--validate`` rather than quoted:
#: ``v_tok = curve_ata_balance + CURVE_TOKEN_OFFSET`` (median exactly this value over
#: 27,027 matched board observations) and ``k = v_sol * v_tok`` flat at ``CURVE_K``.
#: Both cancel out of every log-DIFFERENCE this study measures; they are here so that
#: absolute market cap is derivable from the corpus alone, without the boards tape.
CURVE_TOKEN_OFFSET: Final[int] = 73_000_000_000_000
CURVE_K: Final[float] = 3.219e25

#: Raw units of a pump.fun token per whole token, and the fixed supply. Supply is fixed at
#: 1e9 by the launch program, which is why market cap is a constant multiple of price.
TOKEN_DECIMALS: Final[int] = 6
PUMP_SUPPLY_RAW: Final[int] = 1_000_000_000 * 10**TOKEN_DECIMALS

WSOL: Final[str] = "So11111111111111111111111111111111111111112"

#: The census window: ``state/callouts/backfill-1786717285-1786753261.jsonl``, which is also
#: exactly the 2026-08-14 board tape's span. The bulk corpus ends at 2026-08-15T00:00Z, so
#: everything after that is administratively censored and counted rather than guessed at.
CENSUS_START: Final[int] = 1_786_717_285
CENSUS_END: Final[int] = 1_786_753_261
TAPE_END: Final[int] = 1_786_752_000  # 2026-08-15T00:00:00Z, the corpus's own last second

#: Horizons. Declared before any estimate; the family size below is computed from them.
HORIZONS_S: Final[tuple[int, ...]] = (3_600, 14_400, 28_800)

#: The exposure window: callouts within this many seconds BEFORE t0 constitute "the stream".
#: One hour, chosen to match the 1 h horizon and fixed before any estimate.
EXPOSURE_WINDOW_S: Final[int] = 3_600

#: Collapse conditioning for the wiggle arm. The operator's pattern is post-collapse bottom
#: scalping, so arm (c) is evaluated on this subpopulation and the threshold is the brief's.
COLLAPSE_DRAWDOWN: Final[float] = 0.70

#: The operator's own clip, from the 36 h chain reconstruction of their live trades.
CLIP_LAMPORTS: Final[int] = 100_000_000

#: Minute grid for realized variance. Trade-level would make RV a function of trade count
#: rather than of price movement, which is the confound the whole study is about.
RV_GRID_S: Final[int] = 60

#: How many candidate instants one control mint is offered before it is passed over. Each
#: mint still contributes at most ONE row; more offers only raise the fill rate of the
#: match, and a thin control arm is the difference between a contrast and a coincidence.
OFFERS_PER_CANDIDATE: Final[int] = 8

#: The cluster-robust sandwich needs clusters. Below this the SE is not an estimate and the
#: estimator returns ``nan`` instead of a number -- measured necessity, not caution: a null
#: cohort whose exposure varied over five mints reported |z| in the twenties out of nothing.
MIN_CLUSTERS: Final[int] = 20

#: The look-back over which "flow already visible on chain at t0" is counted. Ten minutes:
#: ``RESULT_caller_wallets.md`` measured the callout arriving a median 26 s after the buy
#: burst it echoes, so a window an order of magnitude wider than the lag captures the burst
#: without reaching back into an unrelated regime.
PRE_FLOW_WINDOW_S: Final[int] = 600

#: History pulled in BEFORE the first callout, so that "drawdown from all-time high" is a
#: measurement rather than a restatement of "the first price we happened to see". Two days
#: of the corpus; the coins in this cohort are hours old, so it reaches their births.
PRE_HISTORY_S: Final[int] = 2 * 86_400


# ======================================================================== the panel


def _duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise SystemExit(
            "duckdb is required: run with `uv run --group research`"
        ) from exc
    con = duckdb.connect()
    con.execute("SET threads TO 6")
    con.execute("SET memory_limit='10GB'")
    con.execute("SET preserve_insertion_order=false")
    with contextlib.suppress(Exception):  # pragma: no cover - pragma name varies by version
        con.execute("PRAGMA disable_progress_bar")
    return con


def bulk_days(start_unix: int, end_unix: int) -> list[Path]:
    """The parquet days a [start, end] window needs, oldest first, existing only."""
    from datetime import UTC, datetime, timedelta

    lo = datetime.fromtimestamp(start_unix, tz=UTC).date()
    hi = datetime.fromtimestamp(end_unix, tz=UTC).date()
    out: list[Path] = []
    day = lo
    while day <= hi:
        path = BULK / f"{day:%Y-%m-%d}.parquet"
        if path.exists():
            out.append(path)
        day = day + timedelta(days=1)
    return out


def build_panel(
    *,
    start_unix: int,
    end_unix: int,
    out_dir: Path = DATA,
    echo: Callable[[str], None] = print,
) -> Path:
    """One DuckDB pass over the corpus -> a per-trade price/flow tape.

    The corpus is 106.6M rows and SUBSTRATE.md's tripwire is explicit that a Python row
    loop over it is a defect. Everything expensive happens inside the engine here; the
    per-event kernels downstream operate on one coin's array at a time.

    The counterparty (the bonding curve, or the PumpSwap pool after migration) is
    identified per mint as the owner appearing in the most of that mint's transactions,
    tie-broken by the largest balance held. It is the only account on the other side of
    every trade, so the SIGN of its token-balance change is the trade's side -- balance
    falls, someone bought; balance rises, someone sold -- and its balance level is the
    price state variable. A second counterparty holding >= 20% of the mint's transactions
    means the coin migrated inside the window; those mints are flagged, not silently
    averaged across two incompatible price bases.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # The panel is NAMED by the census window it serves but READ over a wider one: the
    # outcome horizons run forward to the corpus edge and the drawdown conditioning needs
    # history behind the first callout, or "drawdown from all-time high" degenerates into
    # "drawdown from the first price this study happened to look at".
    read_from = start_unix - PRE_HISTORY_S
    read_to = max(end_unix, TAPE_END)
    days = bulk_days(read_from, read_to)
    if not days:
        raise SystemExit(f"no bulk_pump parquet days cover [{read_from}, {read_to}]")
    echo(f"panel: {len(days)} day(s) {days[0].name} .. {days[-1].name}")
    con = _duckdb()
    files = "[" + ",".join(f"'{p}'" for p in days) + "]"
    con.execute(
        f"""
        CREATE OR REPLACE TABLE legs AS
        SELECT t.block_slot, t.tx_index, t.block_time,
               u.owner AS owner, u.mint AS mint, CAST(u.amount AS HUGEINT) AS amt
        FROM read_parquet({files}) t, UNNEST(t.post) s(u)
        WHERE t.err = '' AND t.block_time BETWEEN {read_from} AND {read_to}
        """
    )
    n_legs = con.execute("SELECT COUNT(*) FROM legs").fetchone()[0]
    echo(f"panel: {n_legs:,} post-balance legs (err = '' only; the corpus has no reverts)")

    con.execute(
        """
        CREATE OR REPLACE TABLE cp AS
        WITH per_owner AS (
          SELECT mint, owner, COUNT(*) AS n_tx, MAX(amt) AS max_amt
          FROM legs WHERE mint LIKE '%pump' GROUP BY mint, owner
        ), ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY mint ORDER BY n_tx DESC, max_amt DESC) AS rk,
                 SUM(n_tx) OVER (PARTITION BY mint) AS mint_tx
          FROM per_owner
        )
        SELECT mint, owner AS cp_owner, n_tx, max_amt,
               (SELECT COUNT(*) FROM ranked r2
                 WHERE r2.mint = ranked.mint AND r2.rk > 1 AND r2.n_tx >= 0.20 * ranked.n_tx)
                 > 0 AS migrated_flag
        FROM ranked WHERE rk = 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cp_kind AS
        SELECT c.*,
               EXISTS (SELECT 1 FROM legs l
                        WHERE l.owner = c.cp_owner AND l.mint = '{WSOL}') AS is_pool
        FROM cp c
        """
    )
    n_mints, n_pool = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN is_pool THEN 1 ELSE 0 END) FROM cp_kind"
    ).fetchone()
    echo(f"panel: {n_mints:,} pump mints, {n_pool:,} priced through a migrated pool")

    # The trade tape. ``log_price`` is up to an additive constant per mint, which is all
    # any log-difference outcome needs; ``mcap_sol`` is the absolute figure, and it is
    # available only on the curve branch where the launch parameters are known.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE trades AS
        WITH cur AS (
          SELECT l.mint, l.block_time, l.block_slot, l.tx_index,
                 CAST(l.amt AS DOUBLE) AS tok_bal, k.is_pool, k.migrated_flag
          FROM legs l JOIN cp_kind k ON l.mint = k.mint AND l.owner = k.cp_owner
          WHERE l.mint LIKE '%pump'
        ), wsol AS (
          SELECT l.block_slot, l.tx_index, k.mint, CAST(l.amt AS DOUBLE) AS wsol_bal
          FROM legs l JOIN cp_kind k ON l.owner = k.cp_owner
          WHERE l.mint = '{WSOL}' AND k.is_pool
        ), joined AS (
          SELECT c.*, w.wsol_bal
          FROM cur c LEFT JOIN wsol w
            ON c.mint = w.mint AND c.block_slot = w.block_slot AND c.tx_index = w.tx_index
        )
        SELECT mint, block_time, block_slot, tx_index, tok_bal, wsol_bal, is_pool,
               migrated_flag,
               CASE WHEN is_pool AND wsol_bal > 0 AND tok_bal > 0
                      THEN ln(wsol_bal) - ln(tok_bal)
                    WHEN NOT is_pool AND tok_bal + {CURVE_TOKEN_OFFSET} > 0
                      THEN ln({CURVE_K}) - 2 * ln(tok_bal + {CURVE_TOKEN_OFFSET})
               END AS log_price,
               tok_bal - lag(tok_bal) OVER (
                   PARTITION BY mint ORDER BY block_slot, tx_index) AS d_tok,
               -- The depth a SALE walks, which is the quote side alone. TVL (both sides)
               -- would halve every impact estimate, and impact is the whole guard.
               CASE WHEN is_pool AND wsol_bal > 0
                      THEN wsol_bal / 1e9
                    WHEN NOT is_pool
                      THEN {CURVE_K} / (tok_bal + {CURVE_TOKEN_OFFSET}) / 1e9
               END AS pool_sol
        FROM joined
        """
    )
    n_trades = con.execute("SELECT COUNT(*) FROM trades WHERE log_price IS NOT NULL").fetchone()[0]
    echo(f"panel: {n_trades:,} priced counterparty prints")

    path = out_dir / f"trades-{start_unix}-{end_unix}.parquet"
    con.execute(
        f"""
        COPY (
          SELECT mint, block_time, block_slot, tx_index, log_price, pool_sol,
                 is_pool, migrated_flag,
                 CASE WHEN d_tok < 0 THEN 1 WHEN d_tok > 0 THEN -1 ELSE 0 END AS side
          FROM trades WHERE log_price IS NOT NULL
          ORDER BY mint, block_slot, tx_index
        ) TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    echo(f"panel: wrote {path}")

    # Distinct-wallet counts are a separate, much smaller aggregate: the traders are every
    # owner in a mint's transactions that is NOT the counterparty.
    wallets = out_dir / f"wallets-{start_unix}-{end_unix}.parquet"
    con.execute(
        f"""
        COPY (
          SELECT l.mint, l.block_time // 60 * 60 AS minute,
                 COUNT(DISTINCT l.owner) AS wallets
          FROM legs l JOIN cp_kind k ON l.mint = k.mint
          WHERE l.mint LIKE '%pump' AND l.owner <> k.cp_owner
          GROUP BY 1, 2
        ) TO '{wallets}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    echo(f"panel: wrote {wallets}")

    # First and last sighting per mint: the age floor and the death clock, both censored
    # at the corpus edges and labelled as such downstream.
    life = out_dir / f"life-{start_unix}-{end_unix}.parquet"
    con.execute(
        f"""
        COPY (
          SELECT mint, MIN(block_time) AS first_seen, MAX(block_time) AS last_seen,
                 COUNT(*) AS prints
          FROM trades GROUP BY mint
        ) TO '{life}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    echo(f"panel: wrote {life}")
    con.close()
    return path


# ==================================================================== the instrument check


def validate_curve_identity(
    *, start_unix: int = CENSUS_START, end_unix: int = CENSUS_END, echo: Callable[[str], None] = print
) -> dict[str, float]:
    """Recover the launch parameters from chain, against the boards tape's own reserves.

    The boards vendor serves ``virtual_sol_reserves`` and ``virtual_token_reserves``
    directly. ASOF-joining each board observation to the last bulk-tape print at or before
    it turns "is my price reconstruction right?" into two measurable numbers: the offset
    between the curve's token-account balance and the virtual token reserve, and the
    product ``v_sol * v_tok``. Neither is quoted from documentation here.
    """
    import numpy as np

    panel = DATA / f"boards-{start_unix}-{end_unix}.parquet"
    if not panel.exists():
        build_boards_panel(out=panel, echo=echo)
    trades = DATA / f"trades-{start_unix}-{end_unix}.parquet"
    if not trades.exists():
        raise SystemExit(f"build the panel first: {trades} is missing")
    con = _duckdb()
    frame = con.execute(
        f"""
        SELECT CAST(b.vtok AS DOUBLE) - t.tok_bal AS offset,
               CAST(b.vsol AS DOUBLE) * CAST(b.vtok AS DOUBLE) AS k
        FROM (SELECT * FROM read_parquet('{panel}')
               WHERE vsol > 0 AND vtok > 0 AND NOT complete
                 AND t_ingest BETWEEN {start_unix} AND {end_unix}) b
        ASOF JOIN (
          SELECT mint, block_time, exp((ln({CURVE_K}) - log_price) / 2) - {CURVE_TOKEN_OFFSET}
                 AS tok_bal
          FROM read_parquet('{trades}') WHERE NOT is_pool
        ) t ON b.mint = t.mint AND b.t_ingest >= t.block_time
        WHERE b.t_ingest - t.block_time <= 30 AND t.tok_bal > 0
        """
    ).fetchdf()
    con.close()
    off = frame["offset"].to_numpy()
    k = frame["k"].to_numpy()
    out = {
        "n": float(len(frame)),
        "offset_median": float(np.median(off)),
        "offset_p25": float(np.percentile(off, 25)),
        "offset_p75": float(np.percentile(off, 75)),
        "offset_exact_frac": float(np.mean(np.abs(off - CURVE_TOKEN_OFFSET) < 1e6)),
        "k_median": float(np.median(k)),
        "k_exact_frac": float(np.mean(np.abs(k / CURVE_K - 1) < 1e-6)),
        "log_k_p10": float(np.log(np.percentile(k, 10))),
        "log_k_p90": float(np.log(np.percentile(k, 90))),
    }
    echo("INSTRUMENT — the curve identity, recovered from chain")
    echo(f"  matched board observations           {out['n']:,.0f}")
    echo(
        f"  v_tok - ata_balance   median {out['offset_median']:.4g}"
        f"   IQR [{out['offset_p25']:.4g}, {out['offset_p75']:.4g}]"
        f"   exact {out['offset_exact_frac'] * 100:.1f}%"
    )
    echo(
        f"  v_sol * v_tok         median {out['k_median']:.6g}"
        f"   within 1e-6 of {CURVE_K:.4g}: {out['k_exact_frac'] * 100:.1f}%"
    )
    echo(f"  log k  p10 {out['log_k_p10']:.4f}   p90 {out['log_k_p90']:.4f}")
    echo("  Both constants cancel out of every log-difference outcome; they are validated")
    echo("  because absolute market cap is derived from them and the cohort is built on it.")
    return out


def build_boards_panel(*, out: Path, echo: Callable[[str], None] = print) -> Path:
    """The boards tape as a columnar panel. Used for validation and for ``created_unix``.

    Not for outcomes: board membership is downstream of a callout, so pricing an outcome
    through it conditions on a collider. It is the vendor's coin-creation clock and a
    second opinion on the reserves, and nothing else in this study.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols: dict[str, list[Any]] = {
        k: []
        for k in (
            "mint", "board", "t_ingest", "usd_market_cap", "ath_market_cap",
            "drawdown_from_ath", "complete", "created_unix", "last_trade_unix",
            "vsol", "vtok",
        )
    }

    def add(member: dict[str, Any], board: Any, fallback_t: Any) -> None:
        mint = member.get("mint")
        if not isinstance(mint, str):
            return
        cols["mint"].append(mint)
        cols["board"].append(str(board or ""))
        cols["t_ingest"].append(float(member.get("t_ingest") or fallback_t or 0.0))
        cols["usd_market_cap"].append(float(member.get("usd_market_cap") or 0.0))
        cols["ath_market_cap"].append(float(member.get("ath_market_cap") or 0.0))
        cols["drawdown_from_ath"].append(
            float(member.get("drawdown_from_ath", -1.0) or -1.0)
        )
        cols["complete"].append(bool(member.get("complete", False)))
        cols["created_unix"].append(float(member.get("created_unix") or 0.0))
        cols["last_trade_unix"].append(float(member.get("last_trade_unix") or 0.0))
        cols["vsol"].append(int(member.get("virtual_sol_reserves") or 0))
        cols["vtok"].append(int(member.get("virtual_token_reserves") or 0))

    for path in sorted(BOARDS.glob("boards-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # the collector is live and the last line may be partial
                kind = row.get("kind")
                if kind == "board_entry":
                    add(row, row.get("board"), row.get("t_ingest"))
                elif kind == "board_snapshot":
                    for member in row.get("members") or ():
                        if isinstance(member, dict):
                            add(member, row.get("board"), row.get("t_ingest"))
    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(cols)
    pq.write_table(table, out, compression="zstd")
    echo(f"boards: {table.num_rows:,} observations, {len(set(cols['mint'])):,} mints -> {out}")
    return out


# ======================================================================== the kernels


def zigzag(logp: Sequence[float], threshold: float) -> tuple[int, float]:
    """Confirmed reversals of size >= ``threshold`` and their summed log-amplitude.

    The standard directional-change filter. A swing is booked only once it has REVERSED by
    ``threshold`` from its extreme, so nothing here is confirmed by a price the filter has
    not already seen -- but the amplitude is measured to the extreme itself, which is why
    the result is an ORACLE bound rather than an achievable return: a live rule cannot
    know it is at the extreme, only that it has moved ``threshold`` away from one.
    """
    if threshold <= 0 or len(logp) < 2:
        return 0, 0.0
    anchor = extreme = logp[0]
    direction = 0
    swings = 0
    amplitude = 0.0
    for x in logp:
        if direction == 0:
            if x - anchor >= threshold:
                direction, extreme = 1, x
            elif anchor - x >= threshold:
                direction, extreme = -1, x
        elif direction == 1:
            if x > extreme:
                extreme = x
            elif extreme - x >= threshold:
                amplitude += extreme - anchor
                swings += 1
                anchor, extreme, direction = extreme, x, -1
        else:
            if x < extreme:
                extreme = x
            elif x - extreme >= threshold:
                amplitude += anchor - extreme
                swings += 1
                anchor, extreme, direction = extreme, x, 1
    return swings, amplitude


def realized_variance(times: Sequence[int], logp: Sequence[float], t0: float, t1: float) -> tuple[float, int]:
    """Sum of squared log returns on a fixed minute grid, and the count of ACTIVE minutes.

    The grid is fixed rather than trade-driven on purpose: realized variance measured
    between consecutive trades is a function of trade ARRIVAL, and trade arrival is the
    very thing a callout is suspected of marking. Measuring the outcome on the same clock
    as the suspected exposure would guarantee a positive result and mean nothing.

    A minute with no trade carries the last price forward and contributes a zero return.
    That is the honest encoding -- nothing moved because nothing traded -- and
    ``active_minutes`` is returned alongside so a low RV from a dead coin is never confused
    with a low RV from a calm one.
    """
    if t1 <= t0 or not times:
        return float("nan"), 0
    lo = bisect_right(times, t0) - 1
    if lo < 0:
        lo = 0
    grid = [t0 + i * RV_GRID_S for i in range(int((t1 - t0) // RV_GRID_S) + 1)]
    if len(grid) < 2:
        return float("nan"), 0
    marks: list[float] = []
    active = 0
    idx = lo
    last = logp[lo] if times[lo] <= t0 else float("nan")
    prev_idx = idx
    for position, edge in enumerate(grid):
        while idx < len(times) and times[idx] <= edge:
            last = logp[idx]
            idx += 1
        # The first edge is the window's OPENING MARK, not a minute of the window. Counting
        # it as activity would give every coin one free active minute and make a corpse and
        # a quiet coin indistinguishable at exactly the point the distinction matters.
        if position and idx > prev_idx:
            active += 1
        prev_idx = idx
        marks.append(last)
    if any(m != m for m in marks):  # never seen a price at or before the window's open
        first = next((m for m in marks if m == m), None)
        if first is None:
            return float("nan"), 0
        marks = [first if m != m else m for m in marks]
    rv = sum((marks[i + 1] - marks[i]) ** 2 for i in range(len(marks) - 1))
    return rv, active


def round_trip_threshold(pool_sol: float, *, take_bps: int) -> float:
    """The coin's own round-trip cost at the operator's clip, as a LOG threshold.

    Imported from ``shitcoims_paperdesk.friction`` rather than restated: that module is the
    corrected one (full three-leg taker costs, not the vault-shortfall measurement that
    made every simulated PumpSwap fill ~85 bps too generous on both legs), and a study that
    priced friction its own way would not be comparable with the desk that trades on it.
    """
    from shitcoims_paperdesk.friction import Friction

    friction = Friction()
    pool_lamports = int(max(0.0, pool_sol) * 1e9)
    cost = friction.round_trip(CLIP_LAMPORTS, pool_lamports, take_bps=take_bps)
    if not math.isfinite(cost) or cost <= 0:
        return float("inf")
    # A fractional cost c is cleared by a log move of log(1 + c): the zigzag runs in logs.
    return math.log1p(cost)


# ======================================================================== the cohort


@dataclass(frozen=True, slots=True)
class Series:
    """One mint's priced print series, plus what the friction threshold needs."""

    mint: str
    times: tuple[int, ...]
    logp: tuple[float, ...]
    side: tuple[int, ...]
    pool_sol: tuple[float, ...]
    is_pool: bool
    migrated: bool

    def window(self, t0: float, t1: float) -> tuple[list[int], list[float], list[int]]:
        lo = bisect_left(self.times, int(t0))
        hi = bisect_right(self.times, int(t1))
        return list(self.times[lo:hi]), list(self.logp[lo:hi]), list(self.side[lo:hi])

    def depth_at(self, t0: float) -> float:
        idx = bisect_right(self.times, int(t0)) - 1
        if idx < 0:
            return float("nan")
        return self.pool_sol[idx]

    def price_at(self, t0: float) -> float:
        idx = bisect_right(self.times, int(t0)) - 1
        if idx < 0:
            return float("nan")
        return self.logp[idx]

    def peak_before(self, t0: float) -> float:
        hi = bisect_right(self.times, int(t0))
        return max(self.logp[:hi]) if hi else float("nan")


def active_mints(path: Path, *, start_unix: int, end_unix: int, min_prints: int = 5) -> list[str]:
    """Mints with enough prints inside the window to have a measurable price path.

    The matching pool has to be drawn from somewhere, and drawing it from all 140,948
    mints in the corpus would put coins that never traded during the window into the
    control arm -- where their zero volatility would be read as evidence that callouts
    predict volatility, when it is only evidence that a corpse does not move.
    """
    con = _duckdb()
    rows = con.execute(
        f"""
        SELECT mint FROM read_parquet('{path}')
        WHERE block_time BETWEEN {start_unix} AND {end_unix}
        GROUP BY mint HAVING COUNT(*) >= {min_prints}
        """
    ).fetchall()
    con.close()
    return [str(m) for (m,) in rows]


def load_series(path: Path, *, mints: set[str] | None = None) -> dict[str, Series]:
    """Read the trade panel into per-mint arrays. The only place the panel is materialised.

    Always call it with a mint set. The panel is 23.5M prints over 140,948 mints and
    materialising all of it as Python lists is several gigabytes for no purpose: the cohort
    is the called mints plus a sampled matching pool, and nothing else is ever measured.
    """
    con = _duckdb()
    where = ""
    if mints is not None:
        listed = ",".join(f"'{m}'" for m in sorted(mints))
        where = f"WHERE mint IN ({listed})" if listed else "WHERE FALSE"
    frame = con.execute(
        f"""
        SELECT mint,
               list(block_time ORDER BY block_slot, tx_index) AS times,
               list(log_price ORDER BY block_slot, tx_index) AS logp,
               list(side ORDER BY block_slot, tx_index) AS side,
               list(pool_sol ORDER BY block_slot, tx_index) AS pool_sol,
               any_value(is_pool) AS is_pool, any_value(migrated_flag) AS migrated
        FROM read_parquet('{path}') {where}
        GROUP BY mint
        """
    ).fetchall()
    con.close()
    out: dict[str, Series] = {}
    for mint, times, logp, side, pool_sol, is_pool, migrated in frame:
        out[mint] = Series(
            mint=mint,
            times=tuple(int(t) for t in times),
            logp=tuple(float(x) for x in logp),
            side=tuple(int(s) for s in side),
            pool_sol=tuple(float(p) if p is not None else float("nan") for p in pool_sol),
            is_pool=bool(is_pool),
            migrated=bool(migrated),
        )
    return out


def load_callout_events(*, start_unix: int, end_unix: int) -> list[dict[str, Any]]:
    """The census, deduplicated to one event per (mint, caller, minute).

    ``RESULT_caller_wallets.md`` measured that 51.4% of this feed is bot spam from 13
    accounts, and the intelligence store re-observes the same tweet up to 22 times. Neither
    is filtered out -- a bot echo is still a marker of the burst it is echoing, which is the
    whole hypothesis -- but both are DEDUPLICATED, because counting one tweet twenty-two
    times would make "callout count" a measure of collector cadence.
    """
    from studies.callout_edge import load_callouts

    seen: set[tuple[str, str, int]] = set()
    out: list[dict[str, Any]] = []
    for row in load_callouts():
        t_post = float(row["t_post"])
        if not (start_unix <= t_post <= end_unix):
            continue
        key = (str(row["mint"]), str(row.get("author") or ""), int(t_post // 60))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: r["t_post"])
    return out


def exposure_features(
    events: Sequence[dict[str, Any]], mint: str, t0: float, *, window_s: int = EXPOSURE_WINDOW_S
) -> dict[str, float]:
    """Callout activity for one mint as of ``t0``: count, recency, cadence. STRICTLY causal.

    Every term reads only callouts at or before ``t0``. ``cadence`` is the mean interval
    between consecutive callouts inside the window and is ``window_s`` when there are fewer
    than two -- an explicit "no cadence observed" value rather than a zero, which would read
    as the fastest possible stream.
    """
    times = sorted(
        float(e["t_post"]) for e in events if e["mint"] == mint and float(e["t_post"]) <= t0
    )
    inside = [t for t in times if t >= t0 - window_s]
    gaps = [b - a for a, b in pairwise(inside)]
    return {
        "n_callouts": float(len(inside)),
        "log1p_callouts": math.log1p(len(inside)),
        "recency_s": float(t0 - times[-1]) if times else float(window_s),
        "cadence_s": (statistics.fmean(gaps) if gaps else float(window_s)),
        "n_callers": float(
            len({
                str(e.get("author") or "")
                for e in events
                if e["mint"] == mint and t0 - window_s <= float(e["t_post"]) <= t0
            })
        ),
    }


@dataclass
class Row:
    """One cohort row: a (mint, t0) pair, its conditioning, its exposure, its outcomes."""

    mint: str
    t0: float
    treated: bool
    log_mcap: float
    log_age: float
    depth_sol: float
    drawdown: float
    #: Trades in the ten minutes BEFORE t0, logged. The decisive confound: a callout is an
    #: echo of a burst that already happened, so if the forward effect is really "busy coins
    #: stay busy" it lives here and the callout column is a redundant, slower view of it.
    pre_flow: float = 0.0
    exposure: dict[str, float] = field(default_factory=dict)
    outcomes: dict[str, float] = field(default_factory=dict)
    censored: dict[str, bool] = field(default_factory=dict)


def _mcap_sol(series: Series, t0: float) -> float:
    """Absolute market cap in SOL. The only place the launch constants are load-bearing."""
    lp = series.price_at(t0)
    if lp != lp:
        return float("nan")
    return math.exp(lp) * PUMP_SUPPLY_RAW / 1e9


def measure(
    series: Series,
    t0: float,
    *,
    horizons: Sequence[int] = HORIZONS_S,
    tape_end: int = TAPE_END,
) -> tuple[dict[str, float], dict[str, bool]]:
    """The three outcome families over each horizon, plus the censoring flag per horizon."""
    out: dict[str, float] = {}
    censored: dict[str, bool] = {}
    depth = series.depth_at(t0)
    take_bps = 105 if series.is_pool else 100
    threshold = round_trip_threshold(depth, take_bps=take_bps)
    out["friction_log"] = threshold
    for horizon in horizons:
        tag = f"{horizon // 3600}h"
        t1 = t0 + horizon
        censored[tag] = t1 > tape_end
        _times, logp, side = series.window(t0, t1)
        rv, active = realized_variance(series.times, series.logp, t0, min(t1, tape_end))
        buys = sum(1 for s in side if s > 0)
        sells = sum(1 for s in side if s < 0)
        swings, amplitude = zigzag(logp, threshold)
        out[f"rv_{tag}"] = rv
        out[f"active_min_{tag}"] = float(active)
        out[f"buys_{tag}"] = float(buys)
        out[f"sells_{tag}"] = float(sells)
        out[f"two_sided_{tag}"] = float(min(buys, sells))
        out[f"log_two_sided_{tag}"] = math.log1p(min(buys, sells))
        out[f"wiggle_n_{tag}"] = float(swings)
        out[f"wiggle_amp_{tag}"] = amplitude
        out[f"wiggle_net_{tag}"] = amplitude - swings * threshold if swings else 0.0
    return out, censored


@dataclass(frozen=True, slots=True)
class Universe:
    """Everything a cohort needs, built once and reused by every null draw.

    The null arms rebuild the COHORT hundreds of times; they must never rebuild the
    PANEL. Separating the two is what makes a properly-specified rotation null (one that
    re-draws the treated instants too, rather than only re-labelling the real ones)
    affordable at all.
    """

    series: dict[str, Series]
    created: dict[str, float]
    called: frozenset[str]
    pool_mints: tuple[str, ...]

    def age_of(self, mint: str, t0: float) -> float:
        birth = self.created.get(mint)
        if birth is None or birth <= 0:
            s = self.series.get(mint)
            birth = float(s.times[0]) if s and s.times else t0
        return max(1.0, t0 - birth)


def load_universe(
    *,
    trades: Path,
    start_unix: int,
    end_unix: int,
    seed: int,
    control_pool: int = 30_000,
    echo: Callable[[str], None] = print,
) -> tuple[Universe, list[dict[str, Any]]]:
    """The priced panel restricted to the called mints plus a sampled matching pool."""
    rng = random.Random(seed)
    events = load_callout_events(start_unix=start_unix, end_unix=end_unix)
    echo(f"cohort: {len(events)} deduplicated callouts on {len({e['mint'] for e in events})} mints")
    called = {str(e["mint"]) for e in events}
    alive = active_mints(trades, start_unix=start_unix, end_unix=end_unix)
    echo(f"cohort: {len(alive):,} mints traded >= 5 times inside the window")
    pool_mints = [m for m in alive if m not in called]
    rng.shuffle(pool_mints)
    pool_mints = pool_mints[:control_pool]
    series = load_series(trades, mints=called | set(pool_mints))
    echo(f"cohort: {len(series):,} mints materialised ({len(pool_mints):,} sampled for matching)")
    universe = Universe(
        series=series,
        created=_created_unix(),
        called=frozenset(called),
        pool_mints=tuple(m for m in pool_mints if m in series),
    )
    return universe, events


def _row_for(
    universe: Universe, mint: str, t0: float, *, treated: bool, exposure: dict[str, float]
) -> Row | None:
    """One cohort row, or ``None`` when the coin was not priced at or before ``t0``."""
    s = universe.series.get(mint)
    if s is None or not s.times or s.times[0] > t0:
        return None
    mcap = _mcap_sol(s, t0)
    if not math.isfinite(mcap) or mcap <= 0:
        return None
    peak = s.peak_before(t0)
    price = s.price_at(t0)
    outcomes, censored = measure(s, t0)
    pre_times, _pre_logp, _pre_side = s.window(t0 - PRE_FLOW_WINDOW_S, t0)
    return Row(
        mint=mint,
        t0=t0,
        treated=treated,
        log_mcap=math.log(mcap),
        log_age=math.log(universe.age_of(mint, t0)),
        depth_sol=s.depth_at(t0),
        drawdown=1.0 - math.exp(price - peak) if peak == peak else float("nan"),
        pre_flow=math.log1p(len(pre_times)),
        exposure=exposure,
        outcomes=outcomes,
        censored=censored,
    )


NO_EXPOSURE: Final[dict[str, float]] = {
    "n_callouts": 0.0,
    "log1p_callouts": 0.0,
    "recency_s": float(EXPOSURE_WINDOW_S),
    "cadence_s": float(EXPOSURE_WINDOW_S),
    "n_callers": 0.0,
}


def build_cohort(
    universe: Universe,
    events: Sequence[dict[str, Any]],
    *,
    seed: int,
    controls_per_event: int = 3,
    echo: Callable[[str], None] = lambda _msg: None,
) -> list[Row]:
    """Treated events, plus market-cap- and age-matched controls drawn from the population.

    The control arm is the experiment ``RESULT_callout_edge.md`` §9 named as its top open
    item and could not run, because the board tape's "coins in view" pool is itself
    selected on attention. The bulk corpus has every pump coin that traded, so the matching
    pool is the population rather than a slice of it. A control is a mint that

    * traded within the five minutes before the same instant ``t0`` (so it is alive, which
      the treated arm is by construction -- an unmatched control arm would recover nothing
      but the difference between a live coin and a dead one),
    * sits in the same log-market-cap and log-age bin as a treated row, and
    * carries no callout ANYWHERE in the census, not merely none before ``t0``. A coin
      called out an hour later is a treated coin observed early, and letting it sit in the
      control arm biases the contrast towards zero.

    This function is called by the real run AND by every null draw, with a different
    ``events`` list. That is deliberate: a null that re-labels the real cohort tests a
    different thing from one that rebuilds it, and only the second is a null of the
    hypothesis actually asserted.
    """
    rng = random.Random(seed)
    treated: list[Row] = []
    for event in events:
        mint = str(event["mint"])
        t0 = float(event["t_post"])
        row = _row_for(
            universe, mint, t0, treated=True, exposure=exposure_features(events, mint, t0)
        )
        if row is not None:
            treated.append(row)
    echo(f"cohort: {len(treated)} treated rows survive pricing")
    if not treated:
        return []

    by_bin: dict[tuple[int, int], int] = defaultdict(int)
    for row in treated:
        by_bin[(int(row.log_mcap * 2), int(row.log_age * 2))] += controls_per_event
    need = dict(by_bin)
    # Each candidate is offered ONE instant, drawn from the treated rows themselves, so
    # the control arm inherits the treated arm's clock exactly -- the diurnal envelope is
    # 3.6-5.4x in this market and an arm sampled on a different clock would recover that
    # instead of the effect. A candidate that is not alive at that instant, or lands in a
    # bin already filled, is discarded rather than re-offered: re-offering until it fits
    # would match on the outcome's own support.
    instants = [r.t0 for r in treated]
    controls: list[Row] = []
    order = list(universe.pool_mints)
    rng.shuffle(order)
    for mint in order:
        if not any(need.values()):
            break
        series = universe.series.get(mint)
        if series is None or len(series.times) < 2:
            continue
        # Up to OFFERS_PER_CANDIDATE independent instants, first fit wins, each mint used
        # at most once. Offering several instants matches on the CONDITIONING variables --
        # which is what matching is -- and never on the outcome, because the instants are
        # drawn before any outcome is computed and the loop stops at the first that fits.
        for _ in range(OFFERS_PER_CANDIDATE):
            t0 = rng.choice(instants)
            lo = bisect_right(series.times, int(t0)) - 1
            if lo < 0 or t0 - series.times[lo] > 300:
                continue  # not alive at that instant
            mcap = _mcap_sol(series, t0)
            if not math.isfinite(mcap) or mcap <= 0:
                continue
            key = (int(math.log(mcap) * 2), int(math.log(universe.age_of(mint, t0)) * 2))
            if need.get(key, 0) <= 0:
                continue
            row = _row_for(universe, mint, t0, treated=False, exposure=dict(NO_EXPOSURE))
            if row is None:
                continue
            need[key] -= 1
            controls.append(row)
            break
    echo(f"cohort: {len(controls)} matched controls ({sum(need.values())} slots unfilled)")
    return treated + controls


def _created_unix() -> dict[str, float]:
    """The vendor's coin-creation clock, from the boards tape. Absent is absent."""
    panel = DATA / "boards-created.parquet"
    if not panel.exists():
        source = DATA / f"boards-{CENSUS_START}-{CENSUS_END}.parquet"
        if not source.exists():
            build_boards_panel(out=source)
        con = _duckdb()
        con.execute(
            f"""COPY (SELECT mint, MIN(created_unix) AS created_unix
                        FROM read_parquet('{source}') WHERE created_unix > 0
                        GROUP BY mint)
                TO '{panel}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
        )
        con.close()
    con = _duckdb()
    rows = con.execute(f"SELECT mint, created_unix FROM read_parquet('{panel}')").fetchall()
    con.close()
    return {str(m): float(t) for m, t in rows}


# ======================================================================== the estimators


def clustered_slope(
    xs: Sequence[float],
    ys: Sequence[float],
    clusters: Sequence[str],
    controls: Sequence[Sequence[float]] = (),
) -> tuple[float, float, int]:
    """OLS slope on ``xs`` with cluster-robust SEs, after partialling out ``controls``.

    Frisch-Waugh: residualise both the exposure and the outcome on the free columns, then
    regress one residual on the other. The slope is identical to the full multiple
    regression's and the cluster-robust variance is the sandwich over mint, which is the
    entity PROGRAM.md §3.2 names -- one coin must never contribute independent-looking
    replicates through several callouts.
    """
    import numpy as np

    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    for c in controls:
        ok &= np.isfinite(np.asarray(c, dtype=float))
    x, y = x[ok], y[ok]
    keys = [k for k, good in zip(clusters, ok, strict=True) if good]
    if len(x) < 8 or x.std() == 0:
        return float("nan"), float("nan"), len(x)
    if controls:
        design = np.column_stack(
            [np.ones_like(x)] + [np.asarray(c, dtype=float)[ok] for c in controls]
        )
        beta, *_ = np.linalg.lstsq(design, np.column_stack([x, y]), rcond=None)
        residual = np.column_stack([x, y]) - design @ beta
        x, y = residual[:, 0], residual[:, 1]
    denom = float((x * x).sum())
    if denom <= 0:
        return float("nan"), float("nan"), len(x)
    slope = float((x * y).sum() / denom)
    resid = y - slope * x
    by_cluster: dict[str, float] = defaultdict(float)
    for key, xi, ri in zip(keys, x, resid, strict=True):
        by_cluster[key] += float(xi * ri)
    meat = sum(v * v for v in by_cluster.values())
    n_clusters = len(by_cluster)
    # A sandwich over a handful of clusters is not a standard error, it is a random number,
    # and the null arm measured that directly: rebuilt cohorts in which the exposure varied
    # over four or five mints produced |z| in the twenties out of nothing. The floor makes
    # the estimator REFUSE rather than report, which is why the null distribution below is
    # a distribution rather than an artefact.
    if n_clusters < MIN_CLUSTERS:
        return slope, float("nan"), len(x)
    correction = n_clusters / max(1, n_clusters - 1)
    se = math.sqrt(correction * meat) / denom
    return slope, se, len(x)


def by_fdr(pvalues: Sequence[float], q: float = 0.10) -> list[bool]:
    """Benjamini-Yekutieli. The dependence-robust step-up, not BH.

    The outcomes here are measured over nested windows of the same tape and are dependent
    by construction, so BH's independence assumption is not available. BY divides the
    threshold by the harmonic number, which is the price of not knowing the dependence.
    """
    finite = [(i, p) for i, p in enumerate(pvalues) if p == p]
    m = len(finite)
    out = [False] * len(pvalues)
    if m == 0:
        return out
    c_m = sum(1.0 / k for k in range(1, m + 1))
    finite.sort(key=lambda kv: kv[1])
    cut = 0
    for rank, (_, p) in enumerate(finite, start=1):
        if p <= q * rank / (m * c_m):
            cut = rank
    for i, _ in finite[:cut]:
        out[i] = True
    return out


def two_sided_p(z: float) -> float:
    if not math.isfinite(z):
        return float("nan")
    return math.erfc(abs(z) / math.sqrt(2.0))


def rotation_null(
    events: Sequence[dict[str, Any]], *, offset: float, start_unix: int, end_unix: int
) -> list[dict[str, Any]]:
    """NULL A -- every callout time shifted by ONE common circular offset.

    Preserves the diurnal envelope (3.6-5.4x in this market -- larger than any callout
    effect anyone has claimed, so an i.i.d. null manufactures one out of time-of-day
    alone), preserves each mint's own burst shape, its callout COUNT, and which mints were
    called at all. It destroys exactly one thing: the alignment between a mint's callouts
    and that mint's own flow at that moment.

    So this null asks **does the TIMING carry information**, and it is the strict one: an
    effect that is really "coins people talk about are busy coins" survives every
    i.i.d. shuffle and dies here.
    """
    span = end_unix - start_unix
    return [
        {**event, "t_post": start_unix + ((float(event["t_post"]) - start_unix + offset) % span)}
        for event in events
    ]


def swap_null(
    events: Sequence[dict[str, Any]],
    universe: Universe,
    *,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """NULL B -- callouts keep their instants and are reassigned to MATCHED other mints.

    Each called mint is swapped for a mint from the control pool in the same log-market-cap
    and log-age bin, evaluated at that mint's own first callout instant. Timing, counts,
    cadence and the diurnal envelope all survive untouched; only the IDENTITY of the coin
    changes.

    So this null asks **does it matter WHICH coin was named**, which is the complement of
    NULL A's question. PROGRAM.md §3.13 is explicit that a single null is a knob rather
    than a test -- measured here on co-trading, two nulls at nominally comparable
    thresholds differed 16x in edge count and agreed on 29% of edges. Only findings that
    clear BOTH are carried downstream.
    """
    by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_mint[str(event["mint"])].append(event)
    if not by_mint:
        return []
    # ONE reference instant for both arms. Binning donors on their own clock and called
    # mints on theirs would make the "match" a match between two different definitions of
    # age, which is how a matched control arm quietly stops being matched.
    reference = statistics.median(float(e["t_post"]) for e in events)

    def bin_at(mint: str) -> tuple[int, int] | None:
        series = universe.series.get(mint)
        if series is None or len(series.times) < 2:
            return None
        mcap = _mcap_sol(series, reference)
        if not math.isfinite(mcap) or mcap <= 0:
            return None
        return (
            int(math.log(mcap) * 2),
            int(math.log(universe.age_of(mint, reference)) * 2),
        )

    buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
    for mint in universe.pool_mints:
        key = bin_at(mint)
        if key is not None:
            buckets[key].append(mint)
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for mint, group in by_mint.items():
        key = bin_at(mint)
        if key is None:
            continue
        candidates = [m for m in buckets.get(key, ()) if m not in used]
        if not candidates:
            continue  # no matched donor: this mint drops out rather than being swapped badly
        donor = rng.choice(candidates)
        used.add(donor)
        out.extend({**event, "mint": donor} for event in group)
    out.sort(key=lambda r: r["t_post"])
    return out


# ======================================================================== the report


@dataclass
class Finding:
    name: str
    slope: float
    se: float
    n: int
    clusters: int

    @property
    def z(self) -> float:
        return self.slope / self.se if self.se and math.isfinite(self.se) and self.se > 0 else float("nan")

    @property
    def p(self) -> float:
        return two_sided_p(self.z)


PRIMARY_OUTCOMES: Final[tuple[str, ...]] = ("rv", "log_two_sided", "wiggle_net")
EXPOSURES: Final[tuple[str, ...]] = ("log1p_callouts", "recency_s", "cadence_s")


def fit_family(
    rows: Sequence[Row],
    *,
    exposures: Sequence[str] = EXPOSURES,
    control_flow: bool = False,
) -> list[Finding]:
    """The declared hypothesis family: |outcomes| x |horizons| x |exposures| fits.

    Counted here rather than after the fact, because PROGRAM.md §3.9 makes the trials number
    part of the result: past ~7 independent configurations an in-sample Sharpe of 1 is an
    out-of-sample zero, and the correction below has to know how many were run.
    """
    findings: list[Finding] = []
    clusters = [r.mint for r in rows]
    controls: list[Sequence[float]] = [
        [r.log_mcap for r in rows],
        [r.log_age for r in rows],
    ]
    if control_flow:
        controls.append([r.pre_flow for r in rows])
    for exposure in exposures:
        xs = [r.exposure.get(exposure, float("nan")) for r in rows]
        for outcome in PRIMARY_OUTCOMES:
            for horizon in HORIZONS_S:
                tag = f"{horizon // 3600}h"
                key = f"{outcome}_{tag}"
                ys = [r.outcomes.get(key, float("nan")) for r in rows]
                slope, se, n = clustered_slope(xs, ys, clusters, controls=tuple(controls))
                findings.append(
                    Finding(
                        name=f"{exposure} -> {key}",
                        slope=slope,
                        se=se,
                        n=n,
                        clusters=len({c for c, y in zip(clusters, ys, strict=True) if y == y}),
                    )
                )
    return findings


def per_window(rows: Sequence[Row], *, halves: int = 2) -> list[dict[str, Any]]:
    """The primary cells refit on each half of the window separately.

    PROGRAM.md §3.6: aggregate reporting hides regime collapse -- Elliptic's models fell
    ~244x after a single market shutdown, and the pump.fun regime shifts in weeks. Ten
    hours cannot detect a weekly shift, but it CAN detect an effect that lives entirely in
    one burst, and a coefficient that flips sign across two halves of one afternoon is not
    a finding whatever its pooled z says.

    There is no train/test split here because there is no fitted predictor to leak across
    one: the design is a contemporaneous matched contrast, and the estimand is a
    coefficient, not an out-of-sample score. This is the corresponding discipline.
    """
    if not rows:
        return []
    instants = sorted(r.t0 for r in rows)
    edges = [instants[int(i * (len(instants) - 1) / halves)] for i in range(halves)]
    edges.append(instants[-1] + 1.0)
    out: list[dict[str, Any]] = []
    for i in range(halves):
        lo, hi = edges[i], edges[i + 1]
        subset = [r for r in rows if lo <= r.t0 < hi]
        cells: dict[str, dict[str, float]] = {}
        for outcome in PRIMARY_OUTCOMES:
            key = f"{outcome}_1h"
            slope, se, n = clustered_slope(
                [r.exposure.get("log1p_callouts", float("nan")) for r in subset],
                [r.outcomes.get(key, float("nan")) for r in subset],
                [r.mint for r in subset],
                controls=([r.log_mcap for r in subset], [r.log_age for r in subset]),
            )
            cells[key] = {
                "slope": slope,
                "se": se,
                "z": slope / se if se and math.isfinite(se) and se > 0 else float("nan"),
                "n": float(n),
            }
        out.append({"half": i + 1, "n_rows": len(subset), "lo": lo, "hi": hi, "cells": cells})
    return out


def arm_contrast(rows: Sequence[Row], key: str) -> dict[str, float]:
    """Treated-vs-control on one outcome, with a mint-clustered SE on the difference."""
    import numpy as np

    treated = [(r.mint, r.outcomes.get(key, float("nan"))) for r in rows if r.treated]
    control = [(r.mint, r.outcomes.get(key, float("nan"))) for r in rows if not r.treated]
    t_vals = [v for _, v in treated if v == v]
    c_vals = [v for _, v in control if v == v]
    if len(t_vals) < 5 or len(c_vals) < 5:
        return {"n_t": len(t_vals), "n_c": len(c_vals), "diff": float("nan"), "z": float("nan")}
    xs = [1.0] * len(rows)
    ys = [r.outcomes.get(key, float("nan")) for r in rows]
    xs = [1.0 if r.treated else 0.0 for r in rows]
    slope, se, _n = clustered_slope(xs, ys, [r.mint for r in rows])
    return {
        "n_t": float(len(t_vals)),
        "n_c": float(len(c_vals)),
        "median_t": float(np.median(t_vals)),
        "median_c": float(np.median(c_vals)),
        "diff": slope,
        "se": se,
        "z": slope / se if se and math.isfinite(se) and se > 0 else float("nan"),
    }


def null_distribution(
    universe: Universe,
    events: Sequence[dict[str, Any]],
    *,
    kind: str,
    draws: int,
    seed: int,
    start_unix: int,
    end_unix: int,
    planted: float = 0.0,
    exposures: Sequence[str] = ("log1p_callouts",),
    control_flow: bool = False,
) -> dict[str, Any]:
    """The null distribution of the family's MAX |z|, by rebuilding the whole cohort.

    Rebuilding matters. A null that keeps the real treated instants and only re-labels
    them leaves almost every row unexposed, so its statistic is computed off a handful of
    accidentally-exposed rows and its spread explodes -- measured here at a median max|z|
    of 2.72 with a p95 of 12.73, which is not a null distribution, it is an artefact of the
    estimator running out of clusters. Re-drawing the instants gives the null cohort the
    same shape as the real one, which is the only way the comparison means anything.

    ``planted`` runs the SAME machinery as a known-EFFECT arm (PROGRAM.md §3.12: a green
    known-zero arm certifies a constant-zero estimator exactly as readily as a working one,
    and this tree has shipped that failure twice). The plant is multiplicative in the
    exposure, applied to the null world's outcomes, so an estimator that cannot recover it
    is disqualified from reporting the null as a result.
    """
    rng = random.Random(seed)
    span = end_unix - start_unix
    stats: list[float] = []
    for draw in range(draws):
        if kind == "rotation":
            shifted = rotation_null(
                events,
                offset=rng.uniform(0.05 * span, 0.95 * span),
                start_unix=start_unix,
                end_unix=end_unix,
            )
        elif kind == "swap":
            shifted = swap_null(events, universe, rng=rng)
        else:  # pragma: no cover - closed set
            raise ValueError(f"unknown null {kind!r}")
        rows = build_cohort(universe, shifted, seed=seed + draw)
        if planted:
            for row in rows:
                bump = 1.0 + planted * row.exposure.get("log1p_callouts", 0.0)
                for key in list(row.outcomes):
                    if key.startswith(("rv_", "log_two_sided_", "wiggle_net_")):
                        row.outcomes[key] = row.outcomes[key] * bump
        findings = fit_family(rows, exposures=exposures, control_flow=control_flow)
        best = max((abs(f.z) for f in findings if math.isfinite(f.z)), default=float("nan"))
        stats.append(best)
    finite = sorted(s for s in stats if s == s)
    return {
        "kind": kind,
        "draws": draws,
        "planted": planted,
        "n_finite": len(finite),
        "median": statistics.median(finite) if finite else float("nan"),
        "p95": finite[int(0.95 * (len(finite) - 1))] if finite else float("nan"),
        "max": finite[-1] if finite else float("nan"),
        "values": finite,
    }


def null_p(observed: float, null: dict[str, Any]) -> float:
    """The exceedance p of an observed max|z| against a null's own draws, with its floor.

    ``p_floor = 1/(1 + draws)``: with few replicates the achievable resolution is coarser
    than any p worth quoting, and the honest output in that regime is the floor, not a
    smaller number.
    """
    values = null.get("values") or []
    if not values or not math.isfinite(observed):
        return float("nan")
    exceed = sum(1 for v in values if v >= observed)
    return (1.0 + exceed) / (1.0 + len(values))


#: The wiggle book's own entry conditions, restated as corpus predicates so that the
#: opportunity count is a count of what THAT BOOK would see rather than of coins that merely
#: moved. Kept beside the book's jitter box in ``shitcoims_paperdesk.policy.WigglePolicy``:
#: the depth floor is that box's lower endpoint and the collapse floor is the brief's.
OPPORTUNITY_MIN_POOL_SOL: Final[float] = 5.0
OPPORTUNITY_MIN_SIDE_TRADES: Final[int] = 2
OPPORTUNITY_FLOW_WINDOW_S: Final[int] = 600


def population_opportunity(
    trades: Path,
    *,
    start_unix: int,
    end_unix: int,
    collapse: float = COLLAPSE_DRAWDOWN,
    echo: Callable[[str], None] = lambda _msg: None,
) -> dict[str, float]:
    """How many qualifying wiggle candidates the WHOLE population offers per day.

    Counted over the corpus, never over the study cohort. The cohort is callout mints plus
    a matching sample, so counting in it would answer "how many candidates are there among
    coins people tweeted about", which is a different and much smaller question than the
    one the operator asked.

    A candidate-minute is a minute at which a coin satisfies every condition the book's
    entry rule checks and the corpus can see:

    * **collapsed** -- at least ``collapse`` below its own running peak in the panel,
    * **deep enough** -- pool SOL at or above the ghost-town floor, so our own 0.1 SOL exit
      is not the cliff,
    * **two-sided** -- at least ``OPPORTUNITY_MIN_SIDE_TRADES`` buys AND that many sells in
      the trailing ten minutes. Not "trades": a one-way slide prints plenty of trades and
      has nothing to harvest.

    The count is reported three ways because they answer three different questions, and
    conflating them is how an "at scale" number gets inflated by a factor of sixty: how
    many candidate MINUTES exist, how many distinct coin-HOURS (an episode a book could
    take a position in), and how many distinct COINS.
    """
    con = _duckdb()
    window = OPPORTUNITY_FLOW_WINDOW_S
    frame = con.execute(
        f"""
        WITH minute AS (
          -- INTEGER floor division. DuckDB's `/` is DOUBLE division even on BIGINTs, so
          -- `block_time / 60 * 60` is the identity and the "minute" grid would silently be
          -- a per-second one.
          SELECT mint, block_time // 60 * 60 AS minute,
                 max(log_price) AS hi,
                 arg_max(log_price, block_slot * 1000000 + tx_index) AS close,
                 min(pool_sol) AS pool_sol,
                 sum(CASE WHEN side > 0 THEN 1 ELSE 0 END) AS buys,
                 sum(CASE WHEN side < 0 THEN 1 ELSE 0 END) AS sells
          FROM read_parquet('{trades}')
          WHERE block_time BETWEEN {start_unix - PRE_HISTORY_S} AND {end_unix}
          GROUP BY 1, 2
        ), rolled AS (
          SELECT *,
                 max(hi) OVER (PARTITION BY mint ORDER BY minute
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS peak,
                 sum(buys) OVER (PARTITION BY mint ORDER BY minute
                                 RANGE BETWEEN {window} PRECEDING AND CURRENT ROW) AS buys_w,
                 sum(sells) OVER (PARTITION BY mint ORDER BY minute
                                  RANGE BETWEEN {window} PRECEDING AND CURRENT ROW) AS sells_w
          FROM minute
        ), qualifying AS (
          SELECT mint, minute
          FROM rolled
          WHERE minute BETWEEN {start_unix} AND {end_unix}
            AND 1.0 - exp(close - peak) >= {collapse}
            AND pool_sol >= {OPPORTUNITY_MIN_POOL_SOL}
            AND buys_w >= {OPPORTUNITY_MIN_SIDE_TRADES}
            AND sells_w >= {OPPORTUNITY_MIN_SIDE_TRADES}
        )
        SELECT COUNT(*) AS minutes,
               COUNT(DISTINCT mint || ':' || CAST(minute // 3600 AS VARCHAR)) AS coin_hours,
               COUNT(DISTINCT mint) AS coins
        FROM qualifying
        """
    ).fetchone()
    # The denominator is coins that ACTUALLY TRADED in the window, not every mint the
    # panel ever priced: the panel carries two days of history for the drawdown baseline,
    # and dividing by that would understate the share by a factor of ten.
    active = con.execute(
        f"""SELECT COUNT(DISTINCT mint) FROM read_parquet('{trades}')
             WHERE block_time BETWEEN {start_unix} AND {end_unix}"""
    ).fetchone()[0]
    con.close()
    minutes, coin_hours, coins = (float(x) for x in frame)
    hours = (end_unix - start_unix) / 3600.0
    echo(f"opportunity: {coins:,.0f} qualifying coins over {hours:.1f} h")
    return {
        "window_hours": hours,
        "candidate_minutes": minutes,
        "coin_hours": coin_hours,
        "coins": coins,
        "coin_hours_per_day": coin_hours * 24.0 / hours if hours > 0 else float("nan"),
        "coins_per_day": coins * 24.0 / hours if hours > 0 else float("nan"),
        "active_mints": float(active),
        "share_of_active": coins / active if active else float("nan"),
    }


def oracle_bound(rows: Sequence[Row], *, collapse: float = COLLAPSE_DRAWDOWN) -> dict[str, float]:
    """What a PERFECT scalper would take out of one qualifying hour, per the zigzag.

    Measured on the cohort rather than the population, and that is fine here because it is
    a per-candidate figure rather than a count. It is an ORACLE: the zigzag turns at the
    exact extremes, so no live rule attains it. Its job is to bound the projection from
    above -- a null on the oracle is a null on every rule inside it, and a large oracle is
    not a promise, it is only the absence of a refutation.
    """
    qualifying = [
        r for r in rows
        if r.drawdown == r.drawdown
        and r.drawdown >= collapse
        and r.outcomes.get("two_sided_1h", 0.0) >= OPPORTUNITY_MIN_SIDE_TRADES
        and math.isfinite(r.depth_sol)
        and r.depth_sol >= OPPORTUNITY_MIN_POOL_SOL
    ]
    nets = [r.outcomes.get("wiggle_net_1h", 0.0) for r in qualifying]
    positive = [n for n in nets if n > 0]
    swings = [r.outcomes.get("wiggle_n_1h", 0.0) for r in qualifying]
    return {
        "n": float(len(qualifying)),
        "with_positive_net": float(len(positive)),
        "positive_share": len(positive) / len(qualifying) if qualifying else float("nan"),
        "median_net_log": statistics.median(positive) if positive else float("nan"),
        "median_swings": statistics.median(swings) if swings else float("nan"),
    }


def render(state: dict[str, Any]) -> str:
    out: list[str] = []
    add = out.append
    add("=" * 96)
    add("CALLOUTS AS A VOLATILITY SIGNAL — conditional on market cap and age")
    add("=" * 96)
    cohort = state["cohort"]
    add(
        f"  cohort: {cohort['treated']} treated / {cohort['control']} matched control rows"
        f" on {cohort['mints']} mints"
    )
    add(f"  window: {cohort['window']}   corpus ends {cohort['tape_end']}")
    add("")
    add("ARM CONTRAST — treated minus matched control, mint-clustered SE")
    add(f"  {'outcome':<22}{'n_t':>7}{'n_c':>7}{'median_t':>13}{'median_c':>13}{'diff':>13}{'z':>8}")
    for key, row in state["contrasts"].items():
        add(
            f"  {key:<22}{row['n_t']:>7.0f}{row['n_c']:>7.0f}"
            f"{row.get('median_t', float('nan')):>13.5g}{row.get('median_c', float('nan')):>13.5g}"
            f"{row['diff']:>13.5g}{row['z']:>8.2f}"
        )
    add("")
    add("THE FAMILY — exposure -> outcome, conditional on log mcap and log age")
    add(f"  {'hypothesis':<44}{'slope':>13}{'se':>12}{'z':>8}{'p':>10}{'n':>7}{'BY':>5}")
    for finding, survived in zip(state["findings"], state["by"], strict=True):
        add(
            f"  {finding['name']:<44}{finding['slope']:>13.5g}{finding['se']:>12.5g}"
            f"{finding['z']:>8.2f}{finding['p']:>10.4f}{finding['n']:>7}"
            f"{('YES' if survived else '-'):>5}"
        )
    add(f"  family size {len(state['findings'])}; BY-FDR at q = 0.10 (dependence-robust)")
    add("")
    add("THE CONFOUND — the same family, with FLOW ALREADY VISIBLE ON CHAIN also partialled out")
    add(f"  {'hypothesis':<44}{'slope':>13}{'se':>12}{'z':>8}{'p':>10}{'n':>7}{'BY':>5}")
    for finding, survived in zip(state["flow_findings"], state["flow_by"], strict=True):
        add(
            f"  {finding['name']:<44}{finding['slope']:>13.5g}{finding['se']:>12.5g}"
            f"{finding['z']:>8.2f}{finding['p']:>10.4f}{finding['n']:>7}"
            f"{('YES' if survived else '-'):>5}"
        )
    add("  A callout arrives a median 26 s AFTER the buy burst it echoes")
    add("  (RESULT_caller_wallets.md). So the column that matters is whether anything")
    add("  survives once the burst itself is controlled: what dies here was never the feed.")
    add("")
    add("PER-WINDOW — the same cells on each half, because an aggregate hides a regime")
    add(f"  {'half':<6}{'rows':>7}   " + "".join(f"{o + '_1h':>22}" for o in PRIMARY_OUTCOMES))
    for half in state["per_window"]:
        cells = "".join(
            f"{half['cells'][o + '_1h']['slope']:>14.4g}"
            f" (z{half['cells'][o + '_1h']['z']:>5.1f})"
            for o in PRIMARY_OUTCOMES
        )
        add(f"  {half['half']:<6}{half['n_rows']:>7}   {cells}")
    add("  A coefficient that flips sign across two halves of one afternoon is not a")
    add("  finding, whatever the pooled z says. There is no train/test split because there")
    add("  is no fitted predictor to leak across one: the estimand is a coefficient.")
    add("")
    add("NULLS — two of them, at matched cohort shape, plus a planted-effect recovery arm")
    add(f"  {'null':<30}{'draws':>7}{'median':>9}{'p95':>9}{'max':>9}{'obs':>8}{'p':>9}")
    plain = state["observed_max_z"]
    controlled = state["observed_max_z_flow_controlled"]
    for label, key, observed in (
        ("A rotation (timing)", "null_rotation", plain),
        ("B mint swap (identity)", "null_swap", plain),
        ("A rotation + planted 0.5", "null_rotation_planted", plain),
        ("A rotation, flow controlled", "null_rotation_flow", controlled),
    ):
        null = state.get(key) or {}
        if not null:
            continue
        add(
            f"  {label:<30}{null['draws']:>7}{null['median']:>9.2f}{null['p95']:>9.2f}"
            f"{null['max']:>9.2f}{observed:>8.2f}{null_p(observed, null):>9.4f}"
        )
    add("  p floor = 1/(1 + draws); a p AT the floor is the instrument's resolution, not")
    add("  a measurement of how small the p is.")
    add("  A finding is carried downstream only if it clears BOTH nulls (PROGRAM.md §3.13:")
    add("  a single null is a knob, not a test). The planted arm is the §3.12 requirement:")
    add("  a green known-zero arm certifies a constant-zero estimator just as readily.")
    add("")
    add("CENSORING")
    for tag, share in state["censoring"].items():
        add(f"  {tag:<6} {share * 100:>5.1f}% of rows have a horizon running past the corpus end")
    if state.get("survival"):
        add(f"  {state['survival']}")
    add("")
    add("OPPORTUNITY — the operator's 'at scale' question, counted over the POPULATION")
    opp = state["opportunity"]
    add(
        f"  window {opp['window_hours']:.1f} h over {opp['active_mints']:,.0f} coins that"
        " actually traded in it"
    )
    add(
        f"  qualifying: {opp['candidate_minutes']:,.0f} candidate-minutes,"
        f" {opp['coin_hours']:,.0f} coin-hours, {opp['coins']:,.0f} distinct coins"
        f" ({opp['share_of_active'] * 100:.1f}% of the active population)"
    )
    add(
        f"  -> {opp['coins_per_day']:,.0f} coins/day and {opp['coin_hours_per_day']:,.0f}"
        " coin-hours/day, by linear scaling. A PROJECTION, not a measurement."
    )
    bound = state["oracle"]
    if bound["n"]:
        add(
            f"  ORACLE bound on {bound['n']:.0f} cohort candidates:"
            f" {bound['positive_share'] * 100:.0f}% have positive net after friction,"
            f" median {math.expm1(bound['median_net_log']) * 100:.0f}% over 1 h"
            f" across {bound['median_swings']:.0f} swings"
        )
    add("  The zigzag turns at the exact extremes. No live rule attains this; it is a")
    add("  CEILING, and the book's job is to find out what fraction of it survives a rule.")
    return "\n".join(out)


def run(
    *,
    start_unix: int = CENSUS_START,
    end_unix: int = CENSUS_END,
    seed: int = 20260815,
    draws: int = 200,
    echo: Callable[[str], None] = print,
) -> dict[str, Any]:
    trades = DATA / f"trades-{start_unix}-{end_unix}.parquet"
    if not trades.exists():
        raise SystemExit(
            f"missing {trades}\nrun --build first (one DuckDB pass over the corpus)"
        )
    universe, events = load_universe(
        trades=trades, start_unix=start_unix, end_unix=end_unix, seed=seed, echo=echo
    )
    rows = build_cohort(universe, events, seed=seed, echo=echo)
    findings = fit_family(rows)
    survived = by_fdr([f.p for f in findings])
    # The same family with contemporaneous on-chain flow ALSO partialled out. If the
    # callout column survives this it is carrying something the chain did not already
    # show; if it does not, the honest verdict is that the feed is a slower view of a
    # variable the operator can read directly, which is a null for the callout and a
    # positive for the flow column.
    flow_findings = fit_family(rows, control_flow=True)
    flow_survived = by_fdr([f.p for f in flow_findings])
    observed = max(
        (abs(f.z) for f in findings if f.name.startswith("log1p_callouts") and math.isfinite(f.z)),
        default=float("nan"),
    )
    contrasts = {
        f"{outcome}_{h // 3600}h": arm_contrast(rows, f"{outcome}_{h // 3600}h")
        for outcome in PRIMARY_OUTCOMES
        for h in HORIZONS_S
    }
    censoring = {
        f"{h // 3600}h": statistics.fmean(
            [1.0 if r.censored.get(f"{h // 3600}h") else 0.0 for r in rows]
        )
        for h in HORIZONS_S
    }
    observed_flow = max(
        (
            abs(f.z)
            for f in flow_findings
            if f.name.startswith("log1p_callouts") and math.isfinite(f.z)
        ),
        default=float("nan"),
    )
    echo(f"nulls: rotation x{draws}, swap x{draws}, planted x{max(20, draws // 4)}")
    rotation = null_distribution(
        universe, events, kind="rotation", draws=draws, seed=seed,
        start_unix=start_unix, end_unix=end_unix,
    )
    swap = null_distribution(
        universe, events, kind="swap", draws=draws, seed=seed + 7,
        start_unix=start_unix, end_unix=end_unix,
    )
    planted = null_distribution(
        universe, events, kind="rotation", draws=max(20, draws // 4), seed=seed + 13,
        start_unix=start_unix, end_unix=end_unix, planted=0.50,
    )
    rotation_flow = null_distribution(
        universe, events, kind="rotation", draws=draws, seed=seed,
        start_unix=start_unix, end_unix=end_unix, control_flow=True,
    )
    state = {
        "cohort": {
            "treated": sum(1 for r in rows if r.treated),
            "control": sum(1 for r in rows if not r.treated),
            "mints": len({r.mint for r in rows}),
            "window": f"{start_unix} .. {end_unix}",
            "tape_end": TAPE_END,
        },
        "contrasts": contrasts,
        "findings": [
            {"name": f.name, "slope": f.slope, "se": f.se, "z": f.z, "p": f.p, "n": f.n}
            for f in findings
        ],
        "by": survived,
        "flow_findings": [
            {"name": f.name, "slope": f.slope, "se": f.se, "z": f.z, "p": f.p, "n": f.n}
            for f in flow_findings
        ],
        "flow_by": flow_survived,
        "observed_max_z": observed,
        "observed_max_z_flow_controlled": observed_flow,
        "null_rotation_flow": rotation_flow,
        "null_rotation": rotation,
        "null_swap": swap,
        "null_rotation_planted": planted,
        "censoring": censoring,
        "per_window": per_window(rows),
        "opportunity": population_opportunity(
            trades, start_unix=start_unix, end_unix=end_unix, echo=echo
        ),
        "oracle": oracle_bound(rows),
        "survival": survival_note(rows),
    }
    return state


def survival_note(rows: Sequence[Row]) -> str:
    """Time-to-death with ``lifelines``, never hand-rolled. Censoring is the specification."""
    try:
        from lifelines import KaplanMeierFitter
    except ImportError:
        return "lifelines not installed; run with `uv run --group research` for the survival line."
    durations: list[float] = []
    observed: list[int] = []
    groups: list[bool] = []
    for row in rows:
        last = row.outcomes.get("active_min_8h", 0.0)
        # "Death" here is the coin's last print inside the longest horizon; a coin still
        # trading at the corpus edge is CENSORED, not dead, and lifelines is told so.
        span = min(TAPE_END, row.t0 + HORIZONS_S[-1]) - row.t0
        if span <= 0:
            continue
        durations.append(max(60.0, last * RV_GRID_S))
        observed.append(0 if row.censored.get("8h") else 1)
        groups.append(row.treated)
    if len(durations) < 20:
        return "survival: too few rows to fit."
    fitter = KaplanMeierFitter()
    out = []
    for flag, label in ((True, "treated"), (False, "control")):
        idx = [i for i, g in enumerate(groups) if g == flag]
        if len(idx) < 10:
            continue
        fitter.fit([durations[i] for i in idx], event_observed=[observed[i] for i in idx])
        median = fitter.median_survival_time_
        out.append(f"{label} median active-time {median / 60:.1f} min (n={len(idx)})")
    return "survival: " + "; ".join(out) if out else "survival: not estimable."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="callout-volatility")
    parser.add_argument("--build", action="store_true", help="one DuckDB pass over the corpus")
    parser.add_argument("--validate", action="store_true", help="recover the curve identity")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--start", type=int, default=CENSUS_START)
    parser.add_argument("--end", type=int, default=CENSUS_END)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--draws", type=int, default=200)
    args = parser.parse_args(argv)
    if args.build:
        build_panel(start_unix=args.start, end_unix=args.end)
    if args.validate:
        validate_curve_identity(start_unix=args.start, end_unix=args.end)
    if args.report:
        state = run(start_unix=args.start, end_unix=args.end, seed=args.seed, draws=args.draws)
        if args.json:
            print(json.dumps(state, indent=1, default=str))
        else:
            print(render(state))
    if not (args.build or args.validate or args.report):
        parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
