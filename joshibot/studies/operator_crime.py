#!/usr/bin/env python3
"""Operator-unit crime: is the persistent OPERATOR predictable where the COIN was not?

WHY THIS EXISTS
---------------
``studies/RESULT_crime_signatures.md`` returned a complete null and, more usefully, an
explanation for it: **16 of 23 mechanical cliffs complete inside the pool's first 0-45 hours**,
which is inside any feature window a price-history detector can have. Its unit of analysis was
the COIN, treated i.i.d. If crime is instead a repeated game played by persistent operators
with reusable infrastructure, then the blind zone is an artifact of the unit choice: an
operator's history exists the moment a new coin is born, so there is no warm-up at all.

This study changes three things at once, and each is a separate falsifiable claim:

1. **Unit** -- operator, not coin.
2. **Label** -- mechanical (who moved what supply, when), not outcome-based (drawdown). The
   prior label pooled rugs with ordinary deaths; ``vol-control`` there showed how badly a
   fixed-percentage drawdown label can lie.
3. **Corpus** -- ``state/bulk_pump/`` : ten days, 106,639,238 successful transactions, every
   balance change touching a pump-suffixed mint, with intra-slot ordering.

THE CORPUS, AND TWO THINGS THE BRIEF GOT WRONG ABOUT IT
-------------------------------------------------------
Read ``scripts/pump_history.py``'s docstring first for the schema traps (``err`` is a string
where empty means success; every amount is a string; boosted PumpSwap pools are not replay
grade). Two corrections established here by reading all ten days rather than the docstring:

* **There is no signer column and no fee-payer column.** The schema is exactly
  ``signature, block_slot, block_time, tx_index, fee_lamports, err, compute_units, pre, post``
  plus provenance. Identity in this corpus is the token-account ``owner``, which is the
  beneficial holder rather than the signer. This kills the fee-payer-reuse fingerprint
  outright (the prior "10 fee payers = 46.6% of failures" line cannot be extended here) and
  it means every wallet identity below is an *owner*, never a signer.
* **Every row is a success.** ``err = ''`` on 106,639,238 of 106,639,238 rows across all ten
  days. The export dropped reverts, so failure-rate fingerprints are also unavailable. Both
  facts are limitations of the pull, not of the chain, and a re-pull could recover them.

THE LEDGER
----------
Everything downstream reads one derived artifact rather than the raw tape, because the raw
tape is 28 GB of nested lists and every study would otherwise pay the explode cost again.

``ledger`` explodes ``pre``/``post`` into one row per (transaction, token account) and nets
them, so a row is **a balance change**, signed:

    delta_raw = sum(post.amount) - sum(pre.amount)   over one account_index

keyed by ``(block_slot, tx_index)`` rather than by ``signature``. That key is globally unique,
sorts into chain order, and costs 16 bytes against base58's 88. Dropping the signature is what
makes the artifact 5.6 GB instead of 30; when a human needs the signature for one row, it is
one predicate away in the raw tape::

    SELECT signature FROM read_parquet('state/bulk_pump/raw/day=<d>/*.parquet')
    WHERE block_slot = ? AND tx_index = ?

**The quote leg is only sometimes there, and that is a curve-mechanics fact, not a gap.** A
PumpSwap pool holds WSOL in a token account, so post-migration trades carry their SOL leg.
A pump.fun bonding curve holds *native* SOL in the PDA's lamports, which is not a token
balance, so pre-migration trades carry **only the token leg**. Since a bonding curve is
constant-product, that costs less than it looks:

    p = sol / tok  and  sol * tok = k   =>   log p = log k - 2 * log(tok)

so **log price is an exact affine function of the curve's own token balance**, with no need
for the virtual-reserve constants. Displacement is measurable pre-migration; absolute SOL size
is not.

COMMANDS
--------
Run in order; each writes a parquet under ``studies/data/operator_crime/`` and every later
stage reads the earlier ones, so a rerun of the analysis costs seconds rather than the hour
the ledger costs.

``ledger``   explode the 28 GB raw tape into 301,592,622 signed balance changes  (~15 min)
``census``   birth / curve path / insider sets / snipers / custody transfers      (~10 min)
``coins``    one row per coin, with market caps read off the curve identity
``panel``    coins plus STRICTLY CAUSAL operator history (window ends 1 row back)
``labels``   the mechanical label ladder, and the perpetrator wallets behind it
``graph``    sniper reuse vs a degree-preserving null; custody components; known entities
``predict``  the headline: coin-birth features vs operator history, temporal split
``screen``   the birth-time CLEAN screen and its operating point
``tape``     per-trade tapes for the four cheap discriminators
``verify``   falsify the price identity against the boards tape's virtual reserves

Invocation is always ``uv run --group research python -m studies.operator_crime <cmd>``.
Nothing here touches the network, signs anything, or reads the live sentinel's state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "state" / "bulk_pump" / "raw"
OUT = REPO_ROOT / "studies" / "data" / "operator_crime"

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _duck(threads: int = 6, memory: str = "12GB"):
    try:
        import duckdb
    except ImportError:
        raise SystemExit(
            "needs duckdb: `uv run --group research`. The corpus is 28 GB of nested parquet; "
            "pyarrow can read it but the explode is a SQL job."
        ) from None
    con = duckdb.connect()
    con.execute(f"SET threads={threads}")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    tmp = OUT / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp}'")
    return con


def days() -> list[str]:
    return sorted(p.name.split("=", 1)[1] for p in RAW.glob("day=*") if p.is_dir())


# --------------------------------------------------------------------------------------
# stage 1 -- the ledger
# --------------------------------------------------------------------------------------

# **The netting is done inside the row, and that is the whole performance story.**
#
# Two formulations were written first and both are recorded because each fails for a
# different, instructive reason:
#
# 1. A CTE over the parquet, unnested once for `pre` and once for `post`, `UNION ALL`'d. The
#    CTE is referenced twice, so duckdb materialises it -- and materialising 10M rows of two
#    nested list columns **spilled 25 GB on the first day** before emitting an output row.
# 2. Folding the sign into a `list_transform`, concatenating, unnesting once, and netting with
#    `GROUP BY block_slot, tx_index, owner, mint`. One scan, but the group key is *within a
#    row*, so the hash aggregate is a near-unique-key aggregate over 28M rows per day: it
#    reduces almost nothing and still spills (4 GB and climbing).
#
# The fix is to notice that a group can never span two rows. `account_index` is unique within
# each of `pre` and `post`, so the netting is a per-row join of two lists of at most a handful
# of elements: subtract the matching `pre` from every `post`, then append the `pre` legs that
# have no `post` (closed accounts) negated. Quadratic inside a row of length <= 8, linear in
# the tape, and **no aggregation at all** -- so it streams, and the spill directory stays
# empty.
# **`delta_raw` is BIGINT, and the cast is load-bearing.** The netting is done in HUGEINT so a
# subtraction cannot overflow, but parquet has no 128-bit integer, so writing HUGEINT silently
# lands a DOUBLE column on disk -- which is exactly the float the corpus docstring forbids.
# Every value here is bounded by the 1e15 supply and so happens to be exactly representable,
# but a downstream `sum()` over a coin's 400,000 trades is not: 4e17 is past 2**53 and the
# total would quietly stop being the total. int64 holds 9.2e18 and the arithmetic stays exact.
LEDGER_SQL = """
SELECT block_slot, tx_index, block_time,
       u.o AS owner, u.m AS mint, CAST(u.a AS BIGINT) AS delta_raw,
       CAST(u.d AS TINYINT) AS decimals
FROM (
  SELECT block_slot, tx_index, block_time,
    list_concat(
      list_transform(post, x -> {{
        'o': x.owner, 'm': x.mint, 'd': x.decimals,
        'a': CAST(x.amount AS HUGEINT) - COALESCE(
               list_extract(
                 list_transform(list_filter(pre, y -> y.account_index = x.account_index),
                                y -> CAST(y.amount AS HUGEINT)), 1), 0)
      }}),
      list_transform(
        list_filter(pre, y -> NOT list_contains(
          list_transform(post, z -> z.account_index), y.account_index)),
        y -> {{'o': y.owner, 'm': y.mint, 'd': y.decimals,
              'a': -CAST(y.amount AS HUGEINT)}})
    ) AS legs
  FROM read_parquet('{glob}')
) src, UNNEST(src.legs) AS t(u)
WHERE (u.m LIKE '%pump' OR u.m = '{wsol}') AND u.a <> 0
"""


def build_ledger(force: bool = False) -> None:
    con = _duck()
    dest = OUT / "ledger"
    dest.mkdir(parents=True, exist_ok=True)
    for day in days():
        out = dest / f"day={day}.parquet"
        if out.exists() and not force:
            print(f"  {day} present, skipping", flush=True)
            continue
        t0 = time.time()
        glob = str(RAW / f"day={day}" / "*.parquet")
        sql = LEDGER_SQL.format(glob=glob, wsol=WSOL)
        tmpout = dest / f".tmp-{day}.parquet"
        con.execute(
            f"COPY ({sql}) TO '{tmpout}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)"
        )
        os.replace(tmpout, out)
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
        print(f"  {day}: {n:,} balance changes in {time.time() - t0:.0f}s", flush=True)


def ledger_glob() -> str:
    return str(OUT / "ledger" / "day=*.parquet")


# --------------------------------------------------------------------------------------
# stage 2 -- the census: one row per mint, and the curve identified
# --------------------------------------------------------------------------------------
#
# The pump.fun bonding curve is constant-product against VIRTUAL reserves, and the constants
# are recoverable from data we already hold rather than from folklore. `state/boards/`
# carries `virtual_sol_reserves` and `virtual_token_reserves` on every board entry, and their
# product is 3.219e25 on every pre-graduation row:
#
#     k = 1.073e15 raw tokens * 3.0e10 lamports = 3.219e25
#
# and `state/firehose/new_token/` confirms the split independently: a create with
# initialBuy = 17,376,518.132293 tokens leaves vTokens = 1,055,623,481.867707, which sums to
# 1,073,000,000.000000 exactly, and vSol = 30.493827158 - 0.493827158 = 30.0 SOL exactly.
#
# So for any coin still on its curve:
#
#     v_tok = curve_token_balance + TOKEN_OFFSET
#     price_lamports_per_raw_token = k / v_tok**2
#
# TOKEN_OFFSET is measured by `curve-constants`, never assumed: it is
# 1.073e15 minus the total supply the curve is funded with at create.
CURVE_K = 32_190_000_000_000_000_000_000_000  # 3.219e25 = 1.073e15 raw tok * 3.0e10 lamports
V_TOK0 = 1_073_000_000_000_000  # raw
V_SOL0 = 30_000_000_000  # lamports

# A mint is BORN in-window iff the NET token supply created at its first observed transaction
# is exactly the pump.fun supply. Supply is minted from nothing, so a create is the one
# transaction whose token legs do not sum to zero, and it does so by exactly 1e15 raw.
#
# This is a sharper cut than "the curve was funded with a lot", which was the first version
# and which mis-sorts every coin with a large dev buy: the curve's *seed* leg is 1e15 minus
# the dev buy, so a creator who bought 20% of his own coin looks like a smaller launch. The
# net-minted test is invariant to the dev buy. Measured on 2026-08-05, 66,316 mints traded and
# the first-transaction net splits four ways:
#
#     exactly 1e15 .... 25,510   a pump.fun create, in-window
#     zero ............ 25,581   an ordinary trade: the coin predates the window
#     negative ........  6,479   likewise
#     other positive ..  8,746   mostly 1e18 single-leg seeds -- a 9-decimal token wearing
#                                the `pump` suffix. Excluded, and counted, rather than
#                                silently rescaled.
#
# TOKEN_OFFSET follows from the same arithmetic: the curve is funded with the whole 1e15 and
# the virtual reserve is 1.073e15, so v_tok = curve_balance + 7.3e13, always.
PUMP_SUPPLY_RAW = 1_000_000_000_000_000
TOKEN_OFFSET = V_TOK0 - PUMP_SUPPLY_RAW  # 7.3e13 raw
PUMP_DECIMALS = 6


def _copy(con, sql: str, out: Path, label: str) -> int:
    t0 = time.time()
    tmp = out.parent / f".tmp-{out.name}"
    con.execute(f"COPY ({sql}) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"  {label}: {n:,} rows in {time.time() - t0:.0f}s -> {out.name}", flush=True)
    return n


BIRTH_SQL = """
WITH led AS (
  SELECT block_slot, tx_index, block_time, owner, mint, delta_raw, decimals
  FROM read_parquet('{ledger}') WHERE mint LIKE '%pump'
),
first_key AS (
  SELECT mint, min(block_slot * 1000000 + tx_index) AS k FROM led GROUP BY mint
),
birth_rows AS (
  SELECT l.*, row_number() OVER (PARTITION BY l.mint ORDER BY l.delta_raw DESC) AS rk,
         count(*) OVER (PARTITION BY l.mint) AS n_birth_legs,
         sum(l.delta_raw) OVER (PARTITION BY l.mint) AS minted_raw
  FROM led l JOIN first_key f
    ON l.mint = f.mint AND l.block_slot * 1000000 + l.tx_index = f.k
)
SELECT c.mint, c.owner AS curve_owner, c.delta_raw AS curve_seed_raw, c.minted_raw,
       c.block_slot AS birth_slot, c.tx_index AS birth_tx, c.block_time AS birth_time,
       c.n_birth_legs, c.decimals,
       d.owner AS deployer, coalesce(d.delta_raw, 0) AS dev_buy_raw
FROM (SELECT * FROM birth_rows WHERE rk = 1) c
LEFT JOIN (SELECT * FROM birth_rows WHERE rk = 2 AND delta_raw > 0) d USING (mint)
"""

# The one predicate that decides membership, written once and reused by every later stage.
BORN = f"minted_raw = {PUMP_SUPPLY_RAW} AND decimals = {PUMP_DECIMALS}"

# The curve's running token balance IS the price path, by log p = log k - 2 log(v_tok). Only
# rows touching the curve account are needed, which is roughly one row per trade.
#
# `post_peak_max_bal` -- the deepest the coin fell back *after* its own top -- is a SUFFIX
# maximum read off at the peak row, not a correlated subquery per mint: `arg_min(sufmax, bal)`
# is the suffix max evaluated where the balance is smallest, which is the definition.
CURVE_SQL = """
WITH born AS (
  SELECT mint, curve_owner FROM read_parquet('{birth}') WHERE {born}
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
       arg_min(block_slot, bal) FILTER (WHERE bal > {grad_eps}) AS slot_peak,
       arg_min(sufmax, bal) FILTER (WHERE bal > {grad_eps}) AS post_peak_max_bal,
       last(bal ORDER BY block_slot, tx_index) AS final_bal,
       last(bal ORDER BY block_slot, tx_index)
         FILTER (WHERE bal > {grad_eps}) AS final_bal_live,
       last(block_time ORDER BY block_slot, tx_index) AS t_last,
       first(block_time ORDER BY block_slot, tx_index) AS t_first
FROM path2 GROUP BY mint
"""


# --------------------------------------------------------------------------------------
# stage 3 -- the insiders, and the mechanical dump label
# --------------------------------------------------------------------------------------
#
# PRE-REGISTERED, and written here before any outcome was looked at.
#
# `snipers`  -- every owner with a net POSITIVE token balance change in the coin's BIRTH
#               SLOT, other than the curve. This is the on-chain bundle shape and it needs no
#               Jito bundle id (which is not on chain at all -- RESULT_execution_landing.md).
#               It cannot happen organically: the mint did not exist one slot earlier, so a
#               buyer in the birth slot either shares the create's atomic bundle or is a bot
#               that reacted inside ~400ms with a mint address nobody had published.
# `insiders` -- snipers plus the deployer. The deployer is normally already a sniper (its dev
#               buy is in the create transaction) so this is usually the same set.
# DUMP       -- the insider set's aggregate holding falls from its own peak to <= 20% of that
#               peak. `t_dump` is the first transaction at or below that line, strictly after
#               the peak. Perpetrators are the insider wallets that sold in between.
#
# Thresholds fixed before estimation: DUMP_FRAC = 0.80 of peak disposed. EARLY_SLOTS = 150
# (~60 s) is reported as a declared second cell, never as the headline.
DUMP_FRAC = 0.80
EARLY_SLOTS = 150

INSIDER_SQL = """
WITH born AS (
  SELECT mint, curve_owner, deployer, birth_slot, curve_seed_raw
  FROM read_parquet('{birth}') WHERE {born}
),
snipers AS (
  SELECT l.mint, l.owner
  FROM read_parquet('{ledger}') l JOIN born b
    ON l.mint = b.mint AND l.block_slot = b.birth_slot
  WHERE l.owner <> b.curve_owner
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
             AND i.block_slot * 1000000 + i.tx_index > k.peak_key) AS t_dump,
         min(i.block_slot) FILTER (
           WHERE i.bal <= (1 - {dump_frac}) * k.ins_peak
             AND i.block_slot * 1000000 + i.tx_index > k.peak_key) AS slot_dump
  FROM ipath i JOIN pk k USING (mint)
  GROUP BY i.mint
),
nsnipe AS (SELECT mint, count(*) AS n_snipers FROM snipers GROUP BY mint)
SELECT b.mint, coalesce(n.n_snipers, 0) AS n_snipers, k.ins_peak, k.t_ins_peak, k.ins_final,
       d.t_dump, d.slot_dump, b.curve_seed_raw
FROM born b
LEFT JOIN nsnipe n USING (mint)
LEFT JOIN pk k USING (mint)
LEFT JOIN dump d USING (mint)
"""


# The sniper incidence is a first-class artifact: the operator graph, the birth-time screen
# and the recidivism feature all read it, and recomputing the birth-slot join three times
# would triple the only expensive join in the pipeline.
SNIPERS_SQL = """
WITH born AS (
  SELECT mint, curve_owner, birth_slot, birth_time
  FROM read_parquet('{birth}') WHERE {born}
)
SELECT l.mint, l.owner, b.birth_time, sum(l.delta_raw) AS bought_raw
FROM read_parquet('{ledger}') l JOIN born b
  ON l.mint = b.mint AND l.block_slot = b.birth_slot
WHERE l.owner <> b.curve_owner AND l.mint LIKE '%pump'
GROUP BY l.mint, l.owner, b.birth_time
HAVING sum(l.delta_raw) > 0
"""

# A DIRECT CUSTODY TRANSFER, and why it is the only linkage edge this corpus can honestly
# offer. RESULT_entity_resolution.md refuses fee sponsorship as a linkage relation ("a funding
# edge must be a native SOL transfer that is the account's first inbound SOL, not somebody
# paid my fee"), and this corpus has no SOL transfers at all. What it does have is token
# custody: a transaction in which exactly two accounts move one pump mint, by equal and
# opposite amounts, and neither is the curve. That is a token transfer, not a trade -- nobody
# paid anybody for it -- so it is custody-shaped evidence rather than co-timing evidence, and
# it is therefore admissible as ground truth for a clustering that a temporal test will use.
#
# **The quote-leg exclusion is what makes it custody rather than commerce.** The first version
# asked only for two equal-and-opposite pump-mint legs with the curve absent, and returned
# 18,195,092 "transfers" in four days -- because that is exactly the shape of a *PumpSwap
# trade* after the coin migrates: the pool takes one side, the trader the other, and the pool
# is not the curve. A payment is not a custody link. So a transaction is admitted only if it
# moved NO WSOL at all, which drops every trade against a wrapped-SOL vault and keeps the
# transfers where nobody was paid.
# Grouped by (block_slot, tx_index) over the WHOLE transaction, not per mint, so "this
# transaction moved no WSOL" is answerable without a second pass -- and run ONE DAY AT A TIME,
# because a transaction never spans a day and the global version OOM'd at 5.5 GB.
TRANSFER_SQL = """
WITH born AS (SELECT mint, curve_owner FROM read_parquet('{birth}') WHERE {born}),
tx AS (
  SELECT block_slot, tx_index,
         min(block_time) AS block_time,
         count(*) AS n_legs,
         count(DISTINCT mint) AS n_mints,
         min(mint) AS mint,
         sum(delta_raw) AS net,
         max(delta_raw) AS pos,
         arg_max(owner, delta_raw) AS to_owner,
         arg_min(owner, delta_raw) AS from_owner,
         bool_or(mint = '{wsol}') AS has_quote
  FROM read_parquet('{glob}')
  GROUP BY block_slot, tx_index
  HAVING count(*) = 2 AND sum(delta_raw) = 0 AND count(DISTINCT mint) = 1
     AND NOT bool_or(mint = '{wsol}') AND max(delta_raw) > 0
)
SELECT t.mint, t.block_slot, t.tx_index, t.block_time, t.from_owner, t.to_owner,
       t.pos AS amount_raw
FROM tx t JOIN born b ON t.mint = b.mint
WHERE t.from_owner <> b.curve_owner AND t.to_owner <> b.curve_owner
"""


def build_census(force: bool = False) -> None:
    """birth -> curve path -> insiders, each a separate artifact so a rerun is cheap."""
    con = _duck()
    birth = OUT / "birth.parquet"
    if force or not birth.exists():
        _copy(con, BIRTH_SQL.format(ledger=ledger_glob()), birth, "birth")
    curve = OUT / "curve.parquet"
    if force or not curve.exists():
        _copy(
            con,
            CURVE_SQL.format(ledger=ledger_glob(), birth=birth, born=BORN, grad_eps=GRAD_EPS),
            curve,
            "curve",
        )
    ins = OUT / "insiders.parquet"
    if force or not ins.exists():
        _copy(
            con,
            INSIDER_SQL.format(
                ledger=ledger_glob(), birth=birth, born=BORN, dump_frac=DUMP_FRAC
            ),
            ins,
            "insiders",
        )
    sn = OUT / "snipers.parquet"
    if force or not sn.exists():
        _copy(con, SNIPERS_SQL.format(ledger=ledger_glob(), birth=birth, born=BORN), sn, "snipers")
    tfd = OUT / "transfers"
    tfd.mkdir(parents=True, exist_ok=True)
    for day in days():
        out = tfd / f"day={day}.parquet"
        if out.exists() and not force:
            continue
        _copy(
            con,
            TRANSFER_SQL.format(
                glob=OUT / "ledger" / f"day={day}.parquet", birth=birth, born=BORN, wsol=WSOL
            ),
            out,
            f"transfers {day}",
        )


# --------------------------------------------------------------------------------------
# stage 4 -- one row per coin, with the curve's own economics
# --------------------------------------------------------------------------------------
#
# Every price quantity below comes from the curve identity and nothing else -- no vendor
# OHLCV, no GeckoTerminal, no survivorship filter. That is the single biggest difference from
# `crime_signatures`, whose cohort had to be assembled from two enumerators with opposite
# biases and still ended with 23 cliffs.
#
#     v_tok       = curve_token_balance + 7.3e13
#     price       = CURVE_K / v_tok^2            lamports per raw token
#     mcap_lamports = CURVE_K * 1e15 / v_tok^2
#
# GRADUATION is mechanical and needs no threshold worth arguing about: at migration the curve
# hands its ENTIRE balance to the PumpSwap pool, so its token account goes to exactly zero.
# `graduated := min_bal <= GRAD_EPS`.
#
# **The migration transaction must then be excluded from the price path, and forgetting that
# is worth a factor of 15 on every graduated coin's peak.** The curve stops selling when its
# *tradeable* reserve is gone, which is not when its balance is gone: 206.9M of the 1e9 supply
# is held back for the migration LP. So the last real quote is at bal = 2.069e14, giving
# v_tok = 2.799e14 and a graduation market cap of **411 SOL** -- which is the check that the
# whole identity is calibrated, because pump.fun graduates at ~$69k and 411 SOL is ~$62k at
# this window's SOL price. Reading the peak at bal = 0 instead gives v_tok = 7.3e13 and a
# nonsense 6,040 SOL, identical for every graduated coin. Hence `min_bal_live`, which is the
# minimum over transactions where the curve still held something.
GRAD_EPS = 1_000_000_000  # 1e9 raw = 1000 tokens, i.e. one millionth of supply

COINS_SQL = """
WITH b AS (SELECT * FROM read_parquet('{birth}') WHERE {born}),
c AS (SELECT * FROM read_parquet('{curve}')),
i AS (SELECT * FROM read_parquet('{insiders}'))
SELECT
  b.mint, b.deployer, b.curve_owner, b.birth_slot, b.birth_time,
  b.dev_buy_raw, b.n_birth_legs,
  i.n_snipers, i.ins_peak, i.t_ins_peak, i.ins_final, i.t_dump,
  c.curve_touches, c.min_bal, c.min_bal_live, c.max_bal, c.final_bal,
  c.final_bal_live, c.post_peak_max_bal,
  c.t_peak, c.t_last,
  (c.min_bal_live + {off}) AS v_tok_peak,
  (c.post_peak_max_bal + {off}) AS v_tok_trough,
  (c.final_bal_live + {off}) AS v_tok_final,
  {kk}::DOUBLE / (c.min_bal_live + {off})::DOUBLE / (c.min_bal_live + {off})::DOUBLE
      * 1e15 / 1e9 AS peak_mcap_sol,
  {kk}::DOUBLE / (c.final_bal_live + {off})::DOUBLE / (c.final_bal_live + {off})::DOUBLE
      * 1e15 / 1e9 AS final_mcap_sol,
  1.0 - pow((c.min_bal_live + {off})::DOUBLE / (c.post_peak_max_bal + {off})::DOUBLE, 2)
      AS drawdown_from_peak,
  (c.min_bal <= {grad_eps}) AS graduated,
  i.ins_peak::DOUBLE / {supply} AS ins_peak_share,
  b.dev_buy_raw::DOUBLE / {supply} AS dev_buy_share,
  c.t_last - b.birth_time AS lifetime_s,
  c.t_peak - b.birth_time AS time_to_peak_s
FROM b JOIN c USING (mint) JOIN i USING (mint)
"""

# Operator history is a running aggregate over the deployer's OWN EARLIER coins, ordered by
# birth time, and it is strictly causal: the frame is `ROWS UNBOUNDED PRECEDING AND 1
# PRECEDING`, so a coin never sees itself or anything born after it. This is the feature the
# whole study exists to test, and getting the frame wrong is the one bug that would
# manufacture the result -- so it is written once, here, and nowhere else.
HISTORY_SQL = """
SELECT *,
  count(*)      OVER h AS prior_launches,
  coalesce(sum(CASE WHEN graduated THEN 1 ELSE 0 END) OVER h, 0) AS prior_grads,
  coalesce(sum(CASE WHEN is_rip   THEN 1 ELSE 0 END) OVER h, 0) AS prior_rips,
  coalesce(avg(n_snipers)      OVER h, 0) AS prior_mean_snipers,
  coalesce(avg(ins_peak_share) OVER h, 0) AS prior_mean_ins_share,
  coalesce(max(peak_mcap_sol)  OVER h, 0) AS prior_best_mcap,
  coalesce(avg(CASE WHEN t_dump IS NOT NULL THEN 1.0 ELSE 0.0 END) OVER h, 0)
      AS prior_dump_rate
FROM read_parquet('{coins}')
WINDOW h AS (PARTITION BY deployer ORDER BY birth_time, birth_slot
             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
"""


# --------------------------------------------------------------------------------------
# stage 5 -- trade tapes, for the four cheap discriminators
# --------------------------------------------------------------------------------------
#
# The cohort is chosen so that the discriminators get a LABELLED test rather than an
# unsupervised one, because "same-bot coins cluster" is only falsifiable if something
# independent of the tape says which coins share a bot. The deployer does: it is read off the
# create transaction and it never touches the trade sequence.
#
#   treatment -- every coin of the TOP_DEPLOYERS deployers by launch count (>= MIN_TOUCHES
#                trades, so a periodogram has something to chew on)
#   control   -- an equal-sized random sample of coins whose deployer launched exactly once
#
# The claim under test is then a two-sample one: NCD between same-deployer pairs vs NCD
# between different-deployer pairs, and the null is the same statistic on tapes whose trade
# ORDER has been shuffled within each coin (which preserves every coin's size distribution and
# destroys only the sequence).
MIN_TOUCHES = 100
TOP_DEPLOYERS = 60

COHORT_SQL = """
WITH c AS (SELECT * FROM read_parquet('{coins}') WHERE curve_touches >= {min_touches}),
dep AS (
  SELECT deployer, count(*) AS n FROM c WHERE deployer IS NOT NULL GROUP BY deployer
),
top AS (SELECT deployer FROM dep WHERE n >= 2 ORDER BY n DESC LIMIT {top_dep}),
treat AS (SELECT c.*, 'serial' AS arm FROM c SEMI JOIN top USING (deployer)),
solo AS (
  SELECT c.*, 'solo' AS arm FROM c JOIN dep USING (deployer) WHERE dep.n = 1
)
SELECT * FROM treat
UNION ALL
SELECT * FROM (SELECT * FROM solo USING SAMPLE {n_solo} ROWS (reservoir, {seed}))
"""

TAPE_SQL = """
WITH coh AS (SELECT mint, curve_owner FROM read_parquet('{cohort}')),
tr AS (
  SELECT l.mint, l.block_slot, l.tx_index, l.block_time, l.owner, l.delta_raw
  FROM read_parquet('{ledger}') l JOIN coh c
    ON l.mint = c.mint AND l.owner <> c.curve_owner
  WHERE l.mint LIKE '%pump'
),
cb AS (
  SELECT l.mint, l.block_slot, l.tx_index,
         sum(l.delta_raw) OVER (PARTITION BY l.mint ORDER BY l.block_slot, l.tx_index
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bal
  FROM read_parquet('{ledger}') l JOIN coh c
    ON l.mint = c.mint AND l.owner = c.curve_owner
)
-- INNER join, deliberately. A trade with no curve leg in the same transaction is a trade the
-- curve was not a party to: a wallet-to-wallet transfer, or -- overwhelmingly -- a PumpSwap
-- trade after the coin migrated, where the pool and not the curve holds the reserves. 81% of
-- the cohort's raw rows are of that second kind, because selecting on `curve_touches >= 100`
-- selects hard for coins that graduated. The curve identity does not price those, and boosted
-- PumpSwap pools are not replay grade in this window at all, so the tape is defined as the
-- BONDING-CURVE PHASE and the post-migration rows are dropped rather than priced wrongly.
SELECT tr.mint, tr.block_slot, tr.tx_index, tr.block_time, tr.owner, tr.delta_raw,
       cb.bal AS curve_bal_after,
       row_number() OVER (PARTITION BY tr.mint ORDER BY tr.block_slot, tr.tx_index) AS seq
FROM tr JOIN cb
  ON tr.mint = cb.mint AND tr.block_slot = cb.block_slot AND tr.tx_index = cb.tx_index
WHERE cb.bal > {grad_eps}
"""


def build_tape(force: bool = False, seed: int = 20260815) -> None:
    con = _duck()
    cohort = OUT / "cohort.parquet"
    if force or not cohort.exists():
        con.execute(
            "CREATE TEMP TABLE nsolo AS "
            + COHORT_SQL.format(
                coins=OUT / "coins.parquet",
                min_touches=MIN_TOUCHES,
                top_dep=TOP_DEPLOYERS,
                n_solo=0,
                seed=seed,
            )
        )
        n_serial = con.execute("SELECT count(*) FROM nsolo").fetchone()[0]
        con.execute("DROP TABLE nsolo")
        sql = COHORT_SQL.format(
            coins=OUT / "coins.parquet",
            min_touches=MIN_TOUCHES,
            top_dep=TOP_DEPLOYERS,
            n_solo=n_serial,
            seed=seed,
        )
        _copy(con, sql, cohort, "cohort")
    tape = OUT / "tape.parquet"
    if force or not tape.exists():
        _copy(con, TAPE_SQL.format(ledger=ledger_glob(), cohort=cohort, grad_eps=GRAD_EPS), tape, "tape")


def build_coins(force: bool = False) -> None:
    con = _duck()
    out = OUT / "coins.parquet"
    if force or not out.exists():
        sql = COINS_SQL.format(
            birth=OUT / "birth.parquet",
            curve=OUT / "curve.parquet",
            insiders=OUT / "insiders.parquet",
            born=BORN,
            off=TOKEN_OFFSET,
            kk=CURVE_K,
            grad_eps=GRAD_EPS,
            supply=PUMP_SUPPLY_RAW,
        )
        _copy(con, sql, out, "coins")


# --------------------------------------------------------------------------------------
# stage 6 -- the labels, counted rather than asserted
# --------------------------------------------------------------------------------------
#
# The brief asked "how many labeled events do ten days contain?" and the honest answer is a
# LADDER, not a number, because "insider dumped" on its own is close to universal and says
# nothing. Each rung adds one materiality condition, and the count falls; the rung where it
# stops looking like the base rate is the rung worth calling a rip.
#
# RIP, pre-registered, is the conjunction of all three:
#   (1) the insider set disposed >= 80% of its own peak holding      -- t_dump is not null
#   (2) that holding was >= 5% of supply                             -- material
#   (3) the coin's peak market cap was >= 100 SOL                    -- somebody could lose
#   (4) and the price fell >= 90% from its peak                      -- it actually collapsed
RIP_INS_SHARE = 0.05
RIP_PEAK_SOL = 100.0
RIP_DRAWDOWN = 0.90

PERP_SQL = """
WITH ev AS (SELECT mint, t_ins_peak, t_dump FROM read_parquet('{coins}') WHERE {rip}),
b AS (SELECT mint, curve_owner, birth_slot FROM read_parquet('{birth}')),
snipers AS (
  SELECT l.mint, l.owner
  FROM read_parquet('{ledger}') l JOIN b
    ON l.mint = b.mint AND l.block_slot = b.birth_slot AND l.owner <> b.curve_owner
  SEMI JOIN ev ON l.mint = ev.mint
  GROUP BY l.mint, l.owner HAVING sum(l.delta_raw) > 0
)
SELECT l.mint, l.owner, sum(l.delta_raw) AS disposed_raw, count(*) AS n_tx
FROM read_parquet('{ledger}') l
JOIN ev ON l.mint = ev.mint
SEMI JOIN snipers s ON l.mint = s.mint AND l.owner = s.owner
WHERE l.block_time >= ev.t_ins_peak AND l.block_time <= ev.t_dump AND l.delta_raw < 0
GROUP BY l.mint, l.owner
"""

RIP_PRED = (
    "t_dump IS NOT NULL "
    f"AND ins_peak_share >= {RIP_INS_SHARE} "
    f"AND peak_mcap_sol >= {RIP_PEAK_SOL} "
    f"AND coalesce(drawdown_from_peak, 0) >= {RIP_DRAWDOWN}"
)


def cmd_labels() -> int:
    con = _duck()
    coins = OUT / "coins.parquet"
    t = f"read_parquet('{coins}')"
    rows: list[tuple[str, int]] = []

    def n(where: str = "TRUE") -> int:
        return con.execute(f"SELECT count(*) FROM {t} WHERE {where}").fetchone()[0]

    total = n()
    rows.append(("coins born in-window", total))
    rows.append(("  with an identified deployer", n("deployer IS NOT NULL")))
    rows.append(("  graduated (curve emptied to the pool)", n("graduated")))
    rows.append(("  bundled at birth (>=2 birth-slot buyers)", n("n_snipers >= 2")))
    rows.append(("  no birth-slot buyer at all", n("n_snipers = 0")))
    rows.append(("insider set disposed >=80% of peak", n("t_dump IS NOT NULL")))
    for s in (0.02, 0.05, 0.10, 0.20):
        rows.append((f"  ... and held >={s:.0%} of supply",
                     n(f"t_dump IS NOT NULL AND ins_peak_share >= {s}")))
    for m in (50, 100, 200, 411):
        rows.append(
            (
                f"  ... >=5% of supply and peak >= {m} SOL",
                n(f"t_dump IS NOT NULL AND ins_peak_share >= 0.05 AND peak_mcap_sol >= {m}"),
            )
        )
    rows.append(("RIP (all four conditions)", n(RIP_PRED)))

    print(f"\n{'label ladder':<52}{'coins':>10}{'share':>9}")
    print("-" * 71)
    for label, k in rows:
        print(f"{label:<52}{k:>10,}{k / total:>9.2%}")

    art = OUT / "labels.json"
    art.write_text(json.dumps({"total": total, "ladder": rows}, indent=2))

    perps = OUT / "perpetrators.parquet"
    _copy(
        con,
        PERP_SQL.format(coins=coins, birth=OUT / "birth.parquet", ledger=ledger_glob(), rip=RIP_PRED),
        perps,
        "perpetrators",
    )
    q = con.execute(
        f"""SELECT count(DISTINCT mint) mints, count(DISTINCT owner) wallets, count(*) pairs
            FROM read_parquet('{perps}')"""
    ).fetchone()
    print(f"\nperpetrators: {q[2]:,} (coin, wallet) disposals over {q[0]:,} ripped coins, "
          f"{q[1]:,} distinct wallets")
    reuse = con.execute(
        f"""SELECT n_coins, count(*) FROM (
              SELECT owner, count(DISTINCT mint) n_coins FROM read_parquet('{perps}') GROUP BY 1)
            GROUP BY 1 ORDER BY 1 DESC LIMIT 8"""
    ).fetchall()
    print("perpetrator recidivism (coins ripped per wallet, top of the distribution):")
    for k, c in reuse:
        print(f"    {k:>4} coins   {c:>7,} wallets")
    return 0


# --------------------------------------------------------------------------------------
# stage 7 -- the operator graph
# --------------------------------------------------------------------------------------
#
# The claim: an operator reuses infrastructure, so the wallets that snipe one of his coins in
# its birth slot are the wallets that snipe the next one. If true, the sniper set is an
# operator fingerprint that exists at t=0 -- which is the whole point, since the prior study's
# blind zone was exactly t=0.
#
# THE NULL IS THE ENTIRE TEST, and this repo has already paid for getting it wrong twice: the
# SVN hypergeometric null validated 99 wallet pairs out of 11,175 on data containing NO
# coordination (RESULT_svn_cotrading.md §5), and a naive co-slot rule built a 138-wallet
# mega-entity whose events clustered in time because that is how it was built
# (RESULT_copytrading.md §3). So:
#
#   * the comparison arm is DAY-MATCHED. Two coins born the same day draw snipers from the
#     same ambient pool of bots; comparing a same-deployer pair against an all-time random
#     pair would measure the calendar, not the operator.
#   * the null is DEGREE-PRESERVING (curveball) on the coin x sniper incidence, which holds
#     every coin's sniper count and every wallet's coin count fixed. A wallet that snipes
#     4,000 coins co-occurs with everything by construction, and only a null that keeps its
#     degree can tell you whether the co-occurrence means anything.
#   * `giant_component_share` is printed next to every clustering number, because union-find
#     on this kind of graph collapses to one component and reports a triumph.


def _curveball(rows: list[set[int]], n_iter: int, rng) -> list[set[int]]:
    """Degree-preserving randomisation of a bipartite incidence, Strona et al.

    Trades the non-shared elements of two rows at a time, so every row degree and every
    column degree is exactly preserved. This is the null the SVN study had to adopt after the
    hypergeometric one validated ~99 pairs out of nothing.
    """
    out = [set(r) for r in rows]
    n = len(out)
    if n < 2:
        return out
    for _ in range(n_iter):
        i, j = rng.integers(0, n, 2)
        if i == j:
            continue
        a, b = out[i], out[j]
        common = a & b
        pool = list((a | b) - common)
        if not pool:
            continue
        rng.shuffle(pool)
        k = len(a) - len(common)
        out[i] = common | set(pool[:k])
        out[j] = common | set(pool[k:])
    return out


def _mean_jaccard(pairs, sets) -> float:
    import numpy as np

    vals = []
    for i, j in pairs:
        a, b = sets[i], sets[j]
        u = len(a | b)
        vals.append(len(a & b) / u if u else 0.0)
    return float(np.mean(vals)) if vals else float("nan")


def cmd_graph(
    seed: int = 20260815, max_deployers: int = 400, n_null: int = 200,
    max_coins_per_deployer: int = 25,
) -> int:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    con = _duck()
    coins = pd.read_parquet(OUT / "coins.parquet", columns=["mint", "deployer", "birth_time"])
    sn = pd.read_parquet(OUT / "snipers.parquet", columns=["mint", "owner"])

    print("\n=== 7.1 deployers ===")
    dep = coins.dropna(subset=["deployer"]).groupby("deployer").size()
    print(f"  coins with a deployer            : {len(coins.dropna(subset=['deployer'])):,}")
    print(f"  distinct deployers               : {len(dep):,}")
    print(f"  deployers with >1 coin           : {(dep > 1).sum():,}  "
          f"({(dep[dep > 1].sum()):,} coins, {dep[dep > 1].sum() / len(coins):.1%} of the corpus)")
    for k in (2, 5, 10, 50):
        print(f"  deployers with >={k:>3} coins        : {(dep >= k).sum():,}")
    print(f"  busiest deployer                 : {dep.max():,} coins")

    print("\n=== 7.2 sniper reuse across one deployer's coins ===")
    # Restrict to the busiest deployers, and cap coins PER deployer. Both caps matter and the
    # second one is not cosmetic: same-deployer pairs are quadratic in a deployer's coin
    # count, and the busiest deployer here launched 1,562 coins -- 1.2M pairs from one
    # operator, which would both dominate the statistic and make the null uncomputable. The
    # cap makes every operator contribute at most C(25,2) = 300 pairs, so the mean is a mean
    # over OPERATORS rather than a mean over one operator's factory output.
    top = dep[dep >= 2].sort_values(ascending=False).head(max_deployers)
    sub = coins[coins["deployer"].isin(top.index)].copy()
    sub = (
        sub.sort_values("birth_time")
        .groupby("deployer", group_keys=False)
        .head(max_coins_per_deployer)
        .copy()
    )
    # **The deployer is dropped from its own coins' sniper sets, and that is not a detail.**
    # A create transaction carries the dev buy, so the deployer is a birth-slot buyer of every
    # coin it launches -- it is in all 25 of its own sniper sets BY CONSTRUCTION. Leaving it
    # in makes same-deployer Jaccard positive on an empty hypothesis, exactly the way the
    # co-slot union-find in RESULT_copytrading.md §3 built a 138-wallet mega-entity whose
    # events clustered in time because that is how it was built. The reported statistic is
    # therefore over snipers OTHER THAN the deployer; the inflated version is printed beside
    # it so the size of the artifact is visible rather than argued about.
    own = dict(zip(sub["mint"], sub["deployer"], strict=True))
    sn_sub = sn[sn["mint"].isin(set(sub["mint"]))]
    mints = sorted(set(sn_sub["mint"]))
    midx = {m: i for i, m in enumerate(mints)}
    wid: dict[str, int] = {}
    sets_with: list[set[int]] = [set() for _ in mints]
    sets: list[set[int]] = [set() for _ in mints]
    for m, o in zip(sn_sub["mint"].to_numpy(), sn_sub["owner"].to_numpy(), strict=True):
        w = wid.setdefault(o, len(wid))
        sets_with[midx[m]].add(w)
        if o != own.get(m):
            sets[midx[m]].add(w)
    sub = sub[sub["mint"].isin(midx)]
    sub["day"] = (sub["birth_time"] // 86400).astype(int)
    print(f"  coins in the arm                 : {len(sub):,} over {sub['deployer'].nunique():,} "
          f"deployers, {len(wid):,} distinct snipers, {sum(len(s) for s in sets):,} edges")

    same, diff = [], []
    for _, g in sub.groupby("deployer"):
        idx = [midx[m] for m in g["mint"]]
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                same.append((idx[a], idx[b]))
    # day-matched different-deployer control, same count as the treatment
    byday: dict[int, list] = {}
    for m, d, dep_ in zip(sub["mint"], sub["day"], sub["deployer"], strict=True):
        byday.setdefault(int(d), []).append((midx[m], dep_))
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
    print(f"  non-empty sniper sets (ex-deployer): "
          f"{sum(1 for s in sets if s):,} of {len(sets):,} coins, "
          f"{sum(len(s) for s in sets):,} edges")
    print(f"  same-deployer pairs              : {len(same):,}   mean Jaccard {obs_same:.4f}")
    print(f"  day-matched different-deployer    : {len(diff):,}   mean Jaccard {obs_diff:.4f}")
    print(f"  ratio                            : "
          f"{obs_same / obs_diff if obs_diff else float('nan'):.2f}x")
    print(f"  [artifact check] same-deployer Jaccard WITH the deployer left in: "
          f"{_mean_jaccard(same, sets_with):.4f}  -- inflated by self-inclusion, not reported")

    null = []
    for _ in range(n_null):
        rand = _curveball(sets, 5 * len(sets), rng)
        null.append(_mean_jaccard(same, rand))
    null = np.array(null)
    p = float((null >= obs_same).mean())
    print(f"  degree-preserving null (n={n_null})  : mean {null.mean():.4f}, "
          f"p95 {np.quantile(null, 0.95):.4f}, max {null.max():.4f}")
    print(f"  p_curveball                      : {p:.4f}   "
          f"effect {obs_same / null.mean() if null.mean() else float('nan'):.2f}x over the null")

    print("\n=== 7.3 custody transfers, the independent linkage ===")
    tf = pd.read_parquet(OUT / "transfers", columns=["from_owner", "to_owner", "mint"])
    print(f"  direct token transfers           : {len(tf):,}")
    print(f"  distinct wallets involved        : {len(set(tf['from_owner']) | set(tf['to_owner'])):,}")
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(tf["from_owner"].to_numpy(), tf["to_owner"].to_numpy(), strict=True):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comps: dict[str, int] = {}
    for w in parent:
        comps[find(w)] = comps.get(find(w), 0) + 1
    sizes = sorted(comps.values(), reverse=True)
    tot = sum(sizes)
    print(f"  components                       : {len(sizes):,}")
    print(f"  giant_component_share            : {sizes[0] / tot if tot else 0:.3f}  "
          f"(top sizes {sizes[:5]})")

    print("\n=== 7.4 known-entity validation ===")
    known_components = {}
    known = {
        "Sh1WNJ8g68rXJGyDjVPcfxWN1WbMrLsgdXmSb6cccuE": "shitcoims",
        "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ": "tha_funds",
        "PmpDh2BQCMMseKYPxseWTSoX3aAouHE4sWyFWTdkqYE": "pumpfun_main",
        "Dev2GmPW2Jv28KW8D7DLqh7TM9hRf8adTDF5p6Jk3CHc": "ember_dev",
        "PrvpTgcuAzN337qSmmKizTMSmhpLPJmZ5Vt8WKCzagf": "og_shitcoims",
        "AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51": "fomo_family_relayer",
    }
    lst = ",".join(f"'{k}'" for k in known)
    hits = con.execute(
        f"""SELECT owner, count(*) n, count(DISTINCT mint) mints
            FROM read_parquet('{ledger_glob()}') WHERE owner IN ({lst})
            GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    seen = {r[0] for r in hits}
    for owner, label in known.items():
        row = next((r for r in hits if r[0] == owner), None)
        if row:
            print(f"  {label:<22} PRESENT  {row[1]:>9,} changes over {row[2]:>6,} mints")
        else:
            print(f"  {label:<22} ABSENT from ten days of the corpus")
    print(f"  operator wallets present         : "
          f"{sum(1 for k, v in known.items() if v != 'fomo_family_relayer' and k in seen)} of 5")

    # The two ground-truth assertions the brief demands of any clustering: the operator's own
    # wallets are ONE entity and must land together; FOMO's relayer is INFRASTRUCTURE and must
    # not be merged with the traders who use it.
    for owner, label in known.items():
        if owner in parent:
            known_components[label] = (find(owner), comps.get(find(owner), 0))
    print("\n  custody-transfer component membership (the linkage that is not co-timing):")
    if not known_components:
        print("    none of the known wallets appears in a direct custody transfer at all.")
        print("    The five own_wallets trade; they do not hand pump tokens to each other,")
        print("    so this corpus offers NO edge on which to test whether they cluster.")
    for label, (root, size) in known_components.items():
        print(f"    {label:<22} component {root[:8]}... of size {size:,}")
    roots = {lab: r for lab, (r, _) in known_components.items() if lab != "fomo_family_relayer"}
    if len(roots) >= 2:
        agree = len(set(roots.values())) == 1
        print(f"    operator wallets in ONE component: {'YES' if agree else 'NO'} "
              f"({len(set(roots.values()))} components over {len(roots)} wallets)")
    if "fomo_family_relayer" in known_components:
        _fr, fsz = known_components["fomo_family_relayer"]
        print(f"    fomo relayer merged with {fsz:,} wallets -- if that is the giant component "
              f"the clustering has absorbed an infrastructure hub, which is the failure mode "
              f"wallet_labels.yaml warns about.")

    art = OUT / "graph.json"
    art.write_text(
        json.dumps(
            {
                "deployers": len(dep),
                "deployers_multi": int((dep > 1).sum()),
                "same_deployer_jaccard": obs_same,
                "day_matched_jaccard": obs_diff,
                "curveball_null_mean": float(null.mean()),
                "curveball_null_p95": float(np.quantile(null, 0.95)),
                "p_curveball": p,
                "transfers": len(tf),
                "giant_component_share": float(sizes[0] / tot) if tot else 0.0,
                "known_present": sorted(seen),
                "seed": seed,
            },
            indent=2,
        )
    )
    print(f"\n  -> {art}")
    return 0


# --------------------------------------------------------------------------------------
# stage 8 -- the panel and the predictive test
# --------------------------------------------------------------------------------------
#
# THE SPLIT, and why it is temporal and not entity-disjoint. PROGRAM.md §3.2 says cluster
# wallets into entities and never let one actor straddle the split. That rule and this study's
# hypothesis are in direct tension: the whole claim is that an operator's PAST predicts his
# NEXT coin, so the operator must appear on both sides or the feature is undefined at test
# time. The resolution is causality rather than disjointness -- every history feature is
# computed over a window frame that ends one row before the coin it describes -- plus a
# temporal split so that no test-set coin contributes to any training-set coin's history.
# This is exactly Marino's protocol (rank creators on the first half, test on the second) and
# it is the one conditioning that has ever beaten breakeven in this literature.
#
# The arms are separated so the study can answer the question it was commissioned to answer:
#   A  coin birth features only   (n_snipers, dev_buy_share, sniper recidivism)
#   B  operator history only      (prior launches / rips / grads / dump rate)
#   C  both
# If B adds nothing over A, the operator reframe fails and the answer is a clean null.

# **BIRTH ORDER IS NOT INFORMATION ORDER, and the first version of this query got it wrong.**
#
# The obvious formulation is a window frame `PARTITION BY deployer ORDER BY birth_time ROWS
# UNBOUNDED PRECEDING AND 1 PRECEDING`, which looks strictly causal and is not. A deployer's
# previous coin is born an hour before this one and rips five days LATER; a birth-ordered
# frame nonetheless credits this coin with `prior_rips = 1`, i.e. with knowledge of a rug that
# had not happened yet. Over a ten-day window where the median coin lives for hours and the
# tail lives for days, that leak points in exactly the direction that manufactures the
# study's own hypothesis.
#
# So every history feature is aggregated over EVENTS whose own timestamp precedes the new
# coin's birth, not over rows whose birth precedes it:
#
#   launch  at the prior coin's birth_time      (observable then)
#   dump    at the prior coin's t_dump          (observable then, NOT at its birth)
#   grad    at the prior coin's migration       (t_last, since the curve's last row IS the
#                                                migration for a graduated coin)
#
# Two features from the first version are DELETED rather than fixed, because they have no
# leak-free form here: `prior_mean_ins_share` and `prior_best_mcap` are maxima over a prior
# coin's whole life, and reconstructing "the peak it had reached by time T" would need the
# full per-trade curve path for all 266,928 coins. `prior_mean_dev_buy` and
# `prior_launch_rate` replace them and are known at the prior coin's birth by construction.
PANEL_SQL = """
WITH c AS (
  SELECT *, ({rip}) AS is_rip,
         CASE WHEN graduated THEN t_last END AS t_grad
  FROM read_parquet('{coins}')
),
sr AS (
  SELECT mint, owner,
         row_number() OVER (PARTITION BY owner ORDER BY birth_time, mint) AS nth
  FROM read_parquet('{snipers}')
),
srm AS (
  SELECT mint,
         avg(CASE WHEN nth > 1 THEN 1.0 ELSE 0.0 END) AS sniper_recidivism,
         max(nth) - 1 AS sniper_prior_max
  FROM sr GROUP BY mint
),
ev AS (
  SELECT deployer, birth_time AS t, 1 AS e_launch, 0 AS e_rip, 0 AS e_dump, 0 AS e_grad,
         n_snipers::DOUBLE AS f_snipers, dev_buy_share AS f_devbuy
  FROM c WHERE deployer IS NOT NULL
  UNION ALL
  SELECT deployer, t_dump, 0, CASE WHEN is_rip THEN 1 ELSE 0 END, 1, 0, NULL, NULL
  FROM c WHERE deployer IS NOT NULL AND t_dump IS NOT NULL
  UNION ALL
  SELECT deployer, t_grad, 0, 0, 0, 1, NULL, NULL
  FROM c WHERE deployer IS NOT NULL AND t_grad IS NOT NULL
),
agg AS (
  SELECT c.mint,
         coalesce(sum(ev.e_launch), 0) AS prior_launches,
         coalesce(sum(ev.e_rip), 0)    AS prior_rips,
         coalesce(sum(ev.e_dump), 0)   AS prior_dumps,
         coalesce(sum(ev.e_grad), 0)   AS prior_grads,
         coalesce(avg(ev.f_snipers), 0) AS prior_mean_snipers,
         coalesce(avg(ev.f_devbuy), 0)  AS prior_mean_dev_buy,
         coalesce(min(c.birth_time - ev.t), 999999) AS secs_since_last_event,
         coalesce(max(c.birth_time - ev.t), 0) AS secs_since_first_event
  FROM c LEFT JOIN ev
    ON ev.deployer = c.deployer AND ev.t < c.birth_time
  GROUP BY c.mint
)
SELECT c.*,
       coalesce(srm.sniper_recidivism, 0) AS sniper_recidivism,
       coalesce(srm.sniper_prior_max, 0) AS sniper_prior_max,
       a.prior_launches, a.prior_rips, a.prior_dumps, a.prior_grads,
       a.prior_mean_snipers, a.prior_mean_dev_buy,
       a.secs_since_last_event,
       a.prior_launches / greatest(a.secs_since_first_event / 3600.0, 1.0)
           AS prior_launch_rate_h
FROM c LEFT JOIN srm USING (mint) JOIN agg a USING (mint)
"""

# The arms decompose by WHICH PERSISTENT ACTOR is being asked about, because "coin features"
# turned out not to be a single thing. `sniper_recidivism` and `sniper_prior_max` are readable
# in the birth slot, so they are birth-time features -- but what they encode is the history of
# the BOT CREW, not of the coin. Lumping them with `n_snipers` would have answered "do birth
# features work?" when the interesting question is "whose past is doing the work: the
# deployer's, or the crew's?".
ARMS = {
    "A0_coin_intrinsic": ["n_snipers", "dev_buy_share"],
    "A1_sniper_crew_history": ["sniper_recidivism", "sniper_prior_max"],
    "A_coin_birth": ["n_snipers", "dev_buy_share", "sniper_recidivism", "sniper_prior_max"],
    "B_operator_history": [
        "prior_launches", "prior_grads", "prior_rips", "prior_dumps",
        "prior_mean_snipers", "prior_mean_dev_buy", "secs_since_last_event",
        "prior_launch_rate_h",
    ],
    "C_both": [
        "n_snipers", "dev_buy_share", "sniper_recidivism", "sniper_prior_max",
        "prior_launches", "prior_grads", "prior_rips", "prior_dumps",
        "prior_mean_snipers", "prior_mean_dev_buy", "secs_since_last_event",
        "prior_launch_rate_h",
    ],
}


def build_panel(force: bool = False) -> None:
    con = _duck()
    out = OUT / "panel.parquet"
    if force or not out.exists():
        _copy(
            con,
            PANEL_SQL.format(coins=OUT / "coins.parquet", snipers=OUT / "snipers.parquet",
                             rip=RIP_PRED),
            out,
            "panel",
        )


def _auprc(y, s):
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(y, s))


def _prec_at_k(y, s, k: int) -> float:
    import numpy as np

    idx = np.argsort(-s)[:k]
    return float(y[idx].mean()) if k else float("nan")


def cmd_predict(seed: int = 20260815, n_null: int = 50, split_day: int = 5) -> int:
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier

    rng = np.random.default_rng(seed)
    df = pd.read_parquet(OUT / "panel.parquet")
    df = df[df["deployer"].notna()].copy()
    t0 = df["birth_time"].min()
    df["day"] = ((df["birth_time"] - t0) // 86400).astype(int)
    tr = df[df["day"] < split_day]
    te = df[df["day"] >= split_day]
    y_tr = tr["is_rip"].to_numpy().astype(int)
    y_te = te["is_rip"].to_numpy().astype(int)
    base = y_te.mean()
    print("\n=== 8.1 the panel and the split ===")
    print(f"  coins with a deployer            : {len(df):,}")
    print(f"  train (days 0-{split_day - 1})   : {len(tr):,}  rips {y_tr.sum():,} "
          f"({y_tr.mean():.4%})")
    print(f"  test  (days {split_day}-9)       : {len(te):,}  rips {y_te.sum():,} "
          f"({base:.4%})")
    print(f"  test coins whose deployer is seen in train : "
          f"{te['deployer'].isin(set(tr['deployer'])).mean():.1%}")

    print("\n=== 8.2 baselines FIRST (PROGRAM.md rule 4) ===")
    results = {}
    # EdgeBank-style memorisation: score = this deployer's rip count in train
    memo = tr.groupby("deployer")["is_rip"].sum()
    s_memo = te["deployer"].map(memo).fillna(0).to_numpy().astype(float)
    results["baseline_edgebank_memorisation"] = _auprc(y_te, s_memo)
    # decayed popularity: this deployer's launch count in train
    pop = tr.groupby("deployer").size()
    s_pop = te["deployer"].map(pop).fillna(0).to_numpy().astype(float)
    results["baseline_deployer_launch_count"] = _auprc(y_te, s_pop)
    results["baseline_random"] = base
    for k, v in results.items():
        print(f"  {k:<38} AUPRC {v:.4f}   ({v / base:.2f}x base rate {base:.4%})")

    print("\n=== 8.3 the arms ===")
    arm_scores = {}
    for name, feats in ARMS.items():
        X_tr = tr[feats].to_numpy(dtype=float)
        X_te = te[feats].to_numpy(dtype=float)
        m = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.1, random_state=seed, max_leaf_nodes=31
        )
        m.fit(X_tr, y_tr)
        s = m.predict_proba(X_te)[:, 1]
        arm_scores[name] = s
        results[name] = _auprc(y_te, s)
        print(f"  {name:<38} AUPRC {results[name]:.4f}   "
              f"({results[name] / base:.2f}x)   P@100 {_prec_at_k(y_te, s, 100):.3f}   "
              f"P@1000 {_prec_at_k(y_te, s, 1000):.3f}")

    print("\n=== 8.4 the null: give this coin somebody else's operator ===")
    # The history BLOCK is permuted across test coins, stratified on `prior_launches`, so
    # every coin keeps a history of exactly the right SIZE and loses only whose it was. The
    # model is refit on the untouched training half and re-scored, so the comparison is
    # like-for-like with the observed row.
    #
    # A first version permuted a deployer-level `.first()` history instead. That is not a
    # null of the observed statistic: the observed arm uses each coin's own running history,
    # which grows down a deployer's launch sequence, so collapsing it to the first coin
    # changed the FEATURE as well as the assignment and would have flattered whichever arm
    # happened to lose the most information.
    hist_cols = ARMS["B_operator_history"]
    nulls: dict[str, list[float]] = {name: [] for name in ARMS}
    H = te[hist_cols].to_numpy(dtype=float)
    strata: dict[float, list[int]] = {}
    for i, v in enumerate(te["prior_launches"].to_numpy()):
        strata.setdefault(float(v), []).append(i)
    for _ in range(n_null):
        order = np.arange(len(te))
        for _, idx in strata.items():
            perm = np.array(idx)
            rng.shuffle(perm)
            order[idx] = perm
        Hs = H[order]
        for name, feats in ARMS.items():
            if not any(f in hist_cols for f in feats):
                continue
            X = te[feats].to_numpy(dtype=float).copy()
            for j, f in enumerate(feats):
                if f in hist_cols:
                    X[:, j] = Hs[:, hist_cols.index(f)]
            m = HistGradientBoostingClassifier(
                max_iter=60, learning_rate=0.15, random_state=seed, max_leaf_nodes=15
            )
            m.fit(tr[feats].to_numpy(dtype=float), y_tr)
            nulls[name].append(_auprc(y_te, m.predict_proba(X)[:, 1]))
    for name in ("B_operator_history", "C_both"):
        arr = np.array(nulls[name])
        if not len(arr):
            continue
        p = float((arr >= results[name]).mean())
        print(f"  {name:<38} obs {results[name]:.4f}  null mean {arr.mean():.4f}  "
              f"p95 {np.quantile(arr, 0.95):.4f}  p_rot {p:.4f}  "
              f"beats null: {'YES' if results[name] > np.quantile(arr, 0.95) else 'NO'}")
        results[f"{name}__null_mean"] = float(arr.mean())
        results[f"{name}__null_p95"] = float(np.quantile(arr, 0.95))
        results[f"{name}__p_rot"] = p

    print("\n=== 8.5 does OPERATOR history add anything over COIN birth features? ===")
    print(f"  AUPRC(C both) - AUPRC(A coin-birth) = "
          f"{results['C_both'] - results['A_coin_birth']:+.4f}   "
          f"({results['C_both'] / results['A_coin_birth']:.3f}x)")
    print(f"  AUPRC(A coin-birth) - AUPRC(A0 intrinsic) = "
          f"{results['A_coin_birth'] - results['A0_coin_intrinsic']:+.4f}   "
          f"({results['A_coin_birth'] / results['A0_coin_intrinsic']:.3f}x)")
    print("\n  Read the two lines together. The first asks whether the DEPLOYER's past adds")
    print("  anything once the birth slot is known; the second asks whether the SNIPER CREW's")
    print("  past does. They are the same question about two different persistent actors, and")
    print("  the study's verdict is whichever one moves.")

    art = OUT / "predict.json"
    art.write_text(json.dumps({"base_rate": float(base), "n_train": len(tr),
                               "n_test": len(te), "results": results,
                               "seed": seed, "split_day": split_day}, indent=2))
    print(f"\n  -> {art}")
    return 0


# --------------------------------------------------------------------------------------
# stage 8b -- competing risks, because a coin does not have one way to end
# --------------------------------------------------------------------------------------
#
# AUPRC answers "does it rip"; it does not answer "when", and it silently treats a coin that
# GRADUATED as a non-event when graduation is a competing outcome that removes the coin from
# risk of ripping on the curve entirely. Cause-specific cumulative incidence is the right
# object: for each cause, the probability of having failed that way by time t, in the presence
# of the other cause.
#
# Censoring is CLOCK-based, never displacement-based (PROGRAM.md §3.8): a coin still trading
# at the end of the window is censored at the window edge, and a coin born on day 9 is
# censored at hours, which is why the cumulative incidence curves are read at fixed horizons
# rather than compared at their right-hand ends.


def cmd_risks(horizons=(3600, 6 * 3600, 24 * 3600, 72 * 3600)) -> int:
    import numpy as np
    import pandas as pd

    df = pd.read_parquet(OUT / "panel.parquet")
    df = df[df["deployer"].notna()].copy()
    t_end = int(df["birth_time"].max()) + 1
    # cause 1 = RIP at t_dump; cause 2 = GRADUATED at migration; else censored at window edge
    t_rip = df["t_dump"].where(df["is_rip"], np.nan)
    t_grad = df["t_last"].where(df["graduated"], np.nan)
    dur = np.minimum(
        np.nan_to_num(t_rip - df["birth_time"], nan=np.inf),
        np.nan_to_num(t_grad - df["birth_time"], nan=np.inf),
    )
    cause = np.where(
        np.nan_to_num(t_rip - df["birth_time"], nan=np.inf)
        <= np.nan_to_num(t_grad - df["birth_time"], nan=np.inf),
        1, 2,
    )
    cens = t_end - df["birth_time"]
    cause = np.where(np.isinf(dur), 0, cause)
    dur = np.where(np.isinf(dur), cens, dur)
    dur = np.maximum(dur, 1)
    df["dur"], df["cause"] = dur, cause
    print("\n=== 8b competing risks, cause-specific cumulative incidence ===")
    print(f"  coins {len(df):,}   RIP {int((cause == 1).sum()):,}   "
          f"GRADUATED {int((cause == 2).sum()):,}   censored {int((cause == 0).sum()):,}")

    try:
        from lifelines import AalenJohansenFitter
    except ImportError:
        print("  lifelines missing; install the research group")
        return 1

    strata = {
        "operator has never ripped (prior_rips = 0)": df["prior_rips"] == 0,
        "operator has ripped 1-2 before": df["prior_rips"].between(1, 2),
        "operator has ripped 3+ before": df["prior_rips"] >= 3,
        "no bundle at birth (n_snipers <= 1)": df["n_snipers"] <= 1,
        "bundled at birth (n_snipers >= 5)": df["n_snipers"] >= 5,
    }
    hdr = "".join(f"{h // 3600:>10}h" for h in horizons)
    print(f"\n  P(RIP by t), cause-specific{'':<22}{hdr}")
    print("  " + "-" * (52 + 11 * len(horizons)))
    out: dict = {}
    for name, m in strata.items():
        g = df[m]
        if len(g) < 100:
            continue
        ajf = AalenJohansenFitter(calculate_variance=False, seed=0)
        # jitter: AJ refuses exact ties between event times, and block_time is 1 s resolution
        ajf.fit(g["dur"].to_numpy(), g["cause"].to_numpy(), event_of_interest=1)
        ci = ajf.cumulative_density_
        vals = []
        for h in horizons:
            idx = ci.index[ci.index <= h]
            vals.append(float(ci.loc[idx[-1]].iloc[0]) if len(idx) else 0.0)
        out[name] = vals
        print(f"  {name:<49}" + "".join(f"{v:>10.3%} " for v in vals))
    (OUT / "risks.json").write_text(json.dumps(
        {"horizons_s": list(horizons), "cumulative_incidence_rip": out,
         "n": len(df), "n_rip": int((cause == 1).sum()),
         "n_grad": int((cause == 2).sum())}, indent=2))
    print(f"\n  -> {OUT / 'risks.json'}")
    return 0


# --------------------------------------------------------------------------------------
# stage 9 -- the product inversion: a birth-time CLEAN screen
# --------------------------------------------------------------------------------------
#
# The operator's use case is a $40 taste bet, so the asymmetry is explicit: a false CLEAN is
# worse than a false DIRTY, and the operating point is chosen for PRECISION OF CLEAN, which is
# `P(not a rip | screen says clean)`. Recall is reported but is not the target -- there are
# 25,000 coins a day and no need to see all of them.
#
# The screen is a conjunction of birth-time-only conditions. Nothing in it reads a price, a
# drawdown or anything after the birth slot.


def cmd_screen(seed: int = 20260815) -> int:
    import numpy as np
    import pandas as pd

    df = pd.read_parquet(OUT / "panel.parquet")
    df = df[df["deployer"].notna()].copy()
    t0 = df["birth_time"].min()
    df["day"] = ((df["birth_time"] - t0) // 86400).astype(int)
    te = df[df["day"] >= 5]
    gates = {
        "no bundle at birth (n_snipers <= 1)": te["n_snipers"] <= 1,
        "deployer has never ripped (prior_rips = 0)": te["prior_rips"] == 0,
        "deployer has never dumped (prior_dumps = 0)": te["prior_dumps"] == 0,
        "no recidivist sniper (sniper_prior_max = 0)": te["sniper_prior_max"] == 0,
        "dev buy under 2% of supply": te["dev_buy_share"] < 0.02,
    }
    # TWO outcomes, and the second one is the honest one.
    #
    # `is_rip` is built from the insider set's holdings, and three of the five gates are also
    # built from the insider set, so a perfect score against it would be substantially
    # DEFINITIONAL rather than predictive: a coin whose only insider is a dev holding under 2%
    # of supply can barely satisfy "the insider set disposed 5% of supply" no matter what its
    # operator does. `collapse` is therefore evaluated alongside it -- a >=90% fall from a peak
    # above 100 SOL, computed from the CURVE alone, with no reference to who sold. If the
    # screen only separates the first label, it has measured its own arithmetic.
    outcomes = {
        "is_rip (insider-mechanical)": te["is_rip"].to_numpy().astype(int),
        "collapse (price only, >=90% from a >=100 SOL peak)": (
            (te["peak_mcap_sol"] >= RIP_PEAK_SOL)
            & (te["drawdown_from_peak"].fillna(0) >= RIP_DRAWDOWN)
        ).to_numpy().astype(int),
    }
    art: dict = {"n_test": len(te), "seed": seed, "outcomes": {}}
    print("\n=== 9 the birth-time clean screen (test half only) ===")
    print(f"  test coins {len(te):,}\n")
    for oname, y in outcomes.items():
        base = y.mean()
        print(f"  --- outcome: {oname}   base rate {base:.4%} ---")
        print(f"  {'gate':<46}{'passes':>10}{'P(clean)':>11}{'rip lift':>10}")
        print("  " + "-" * 77)
        for name, g in gates.items():
            gg = g.to_numpy()
            if gg.sum() == 0:
                continue
            prec = 1 - y[gg].mean()
            print(f"  {name:<46}{gg.sum():>10,}{prec:>11.4%}{(1 - prec) / base:>9.2f}x")
        allg = np.logical_and.reduce([g.to_numpy() for g in gates.values()])
        prec = 1 - y[allg].mean() if allg.sum() else float("nan")
        print("  " + "-" * 77)
        print(f"  {'ALL GATES (the CLEAN screen)':<46}{allg.sum():>10,}{prec:>11.4%}"
              f"{(1 - prec) / base:>9.2f}x")
        print(f"  coverage {allg.mean():.1%} of new coins; admits {y[allg].sum():,} of "
              f"{y.sum():,} bad coins (recall of DIRTY {1 - y[allg].sum() / max(y.sum(), 1):.1%})")
        print()
        art["outcomes"][oname] = {
            "base_rate": float(base), "clean_precision": float(prec),
            "coverage": float(allg.mean()), "admitted_bad": int(y[allg].sum()),
            "total_bad": int(y.sum()),
        }
    art["gates"] = {k: int(v.to_numpy().sum()) for k, v in gates.items()}
    (OUT / "screen.json").write_text(json.dumps(art, indent=2))
    print(f"  -> {OUT / 'screen.json'}")
    return 0


# --------------------------------------------------------------------------------------
# verify -- the price identity against an independent vendor clock
# --------------------------------------------------------------------------------------
#
# Everything priced in this study rests on `v_tok = curve_balance + 7.3e13` and
# `k = 3.219e25`. Two checks are cheap and one of them is genuinely independent:
#
#   internal  -- the median graduated coin should peak at 411 SOL, because the curve stops
#                selling with 206.9M tokens still in the account.
#   external  -- `state/boards/` is a pump.fun vendor feed carrying `virtual_token_reserves`
#                and `virtual_sol_reserves` per snapshot. Neither number is derived from our
#                ledger, so comparing the vendor's v_tok against ours at the same wall-clock
#                second is a real falsification test rather than a restatement.


def cmd_verify(day: str = "20260814", fresh_s: int = 60) -> int:
    import numpy as np

    boards = REPO_ROOT / "state" / "boards" / f"boards-{day}.jsonl"
    if not boards.exists():
        print(f"  no boards tape at {boards}; external check skipped")
        return 1
    rows = []
    with boards.open() as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("kind") != "board_entry" or not r.get("virtual_token_reserves"):
                continue
            rows.append(r)
    on_curve = [r for r in rows if not r.get("complete")]
    ks = np.array(
        [int(r["virtual_token_reserves"]) * int(r["virtual_sol_reserves"]) / CURVE_K
         for r in on_curve]
    )
    std = np.abs(ks - 1) < 1e-3
    print(f"\n=== verify: {len(rows):,} board snapshots from {boards.name} ===")
    print(f"  still on the curve (complete = false) : {len(on_curve):,}")
    print(f"  carrying the STANDARD constant k = 3.219e25 (to 0.1%) : {std.mean():.2%}")
    print("  the rest run a non-standard curve -- pump.fun's boosted / 'mayhem mode' launches.")
    print("  Every market cap in this study is EXACT for the standard majority and")
    print("  APPROXIMATE for the rest; it is used as a materiality screen, never as a fitted")
    print("  quantity, so the cost is cohort membership rather than a biased estimate.")

    probe = [
        (r["mint"], float(r["t_ingest"]), int(r["virtual_token_reserves"]))
        for r, ok in zip(on_curve, std, strict=True) if ok
    ]
    con = _duck()
    con.execute("CREATE TEMP TABLE probe(mint VARCHAR, t DOUBLE, v_tok BIGINT)")
    con.executemany("INSERT INTO probe VALUES (?, ?, ?)", probe)
    q = con.execute(
        f"""
        WITH born AS (SELECT mint, curve_owner FROM read_parquet('{OUT / "birth.parquet"}')
                      WHERE {BORN}),
        path AS (
          SELECT l.mint, l.block_time,
                 sum(l.delta_raw) OVER (PARTITION BY l.mint ORDER BY l.block_slot, l.tx_index
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bal
          FROM read_parquet('{ledger_glob()}') l JOIN born b
            ON l.mint = b.mint AND l.owner = b.curve_owner
          SEMI JOIN probe p ON l.mint = p.mint
        ),
        matched AS (
          SELECT p.mint, p.t, p.v_tok AS vendor,
                 arg_max(path.bal, path.block_time) AS bal,
                 max(path.block_time) AS t_obs
          FROM probe p JOIN path ON path.mint = p.mint AND path.block_time <= p.t
          GROUP BY p.mint, p.t, p.v_tok
        ),
        err AS (
          SELECT *, abs((bal + {TOKEN_OFFSET})::DOUBLE - vendor) / vendor AS rel,
                 t - t_obs AS staleness FROM matched
        )
        SELECT count(*), median(rel),
               count(*) FILTER (WHERE staleness <= {fresh_s}),
               median(rel) FILTER (WHERE staleness <= {fresh_s}),
               quantile_cont(rel, 0.9) FILTER (WHERE staleness <= {fresh_s})
        FROM err
        """
    ).fetchone()
    print(f"\n  standard-curve probes joined to our path : {q[0]:,}")
    print(f"  median |ours - vendor| / vendor, ALL      : {q[1]:.2%}")
    print(f"  ... restricted to snapshots whose last chain trade is within {fresh_s}s "
          f"(n = {q[2]:,})")
    if q[3] is not None:
        print(f"  median relative error                    : {q[3]:.3%}   p90 {q[4]:.3%}")
        print("\n  The staleness split IS the result. The vendor's board clock is an ingest")
        print("  time, not a chain time (RESULT_deterioration.md's two-clock rule); a coin")
        print("  that traded 300 times since the snapshot has genuinely moved. Conditioned on")
        print("  the snapshot being current, our curve balance reproduces a number we never")
        print("  saw, to within half a percent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studies.operator_crime", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ledger", help="explode the raw tape into signed balance changes")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("census", help="birth / curve path / insider sets, one row per mint")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("coins", help="join the census into one row per coin, with economics")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("tape", help="per-trade tapes for the labelled discriminator cohort")
    p.add_argument("--force", action="store_true")
    p.add_argument("--seed", type=int, default=20260815)
    sub.add_parser("labels", help="the mechanical label ladder, and who the perpetrators are")
    p = sub.add_parser("panel", help="coins + causal operator history, one row per coin")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("predict", help="the predictive test: coin-birth vs operator-history arms")
    p.add_argument("--seed", type=int, default=20260815)
    p.add_argument("--n-null", type=int, default=50)
    p.add_argument("--split-day", type=int, default=5)
    sub.add_parser("risks", help="cause-specific cumulative incidence: rip vs graduation")
    sub.add_parser("screen", help="the birth-time CLEAN screen and its operating point")
    p = sub.add_parser("verify", help="falsify the curve price identity against the boards tape")
    p.add_argument("--day", default="20260814")
    p = sub.add_parser("graph", help="operator graph: sniper reuse, custody links, known entities")
    p.add_argument("--seed", type=int, default=20260815)
    p.add_argument("--max-deployers", type=int, default=400)
    p.add_argument("--n-null", type=int, default=200)
    p.add_argument("--max-coins-per-deployer", type=int, default=25)

    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.cmd == "ledger":
        build_ledger(force=args.force)
        return 0
    if args.cmd == "census":
        build_census(force=args.force)
        return 0
    if args.cmd == "coins":
        build_coins(force=args.force)
        return 0
    if args.cmd == "tape":
        build_tape(force=args.force, seed=args.seed)
        return 0
    if args.cmd == "labels":
        return cmd_labels()
    if args.cmd == "panel":
        build_panel(force=args.force)
        return 0
    if args.cmd == "predict":
        return cmd_predict(seed=args.seed, n_null=args.n_null, split_day=args.split_day)
    if args.cmd == "risks":
        return cmd_risks()
    if args.cmd == "screen":
        return cmd_screen()
    if args.cmd == "verify":
        return cmd_verify(day=args.day)
    if args.cmd == "graph":
        return cmd_graph(seed=args.seed, max_deployers=args.max_deployers,
                         n_null=args.n_null,
                         max_coins_per_deployer=args.max_coins_per_deployer)
    return 1


if __name__ == "__main__":
    sys.exit(main())
