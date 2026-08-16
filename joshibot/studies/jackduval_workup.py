"""One caller, worked up: `jackduvalcalls`.

THE OPERATOR'S ASK, AND WHY IT IS NOT THE QUESTION ALREADY ANSWERED
-------------------------------------------------------------------
"we need to be watching his wallet". The operator started following an X caller,
`jackduvalcalls`, after profiting from his `fatdogwithhat` call and `calico` before it.

The population verdict on this feed is already in and it is brutally negative.
``RESULT_callout_edge.md``: buying what the callout feed names returns **-11.9% at 1 h**
and **-43.6% at 8 h**, and LOUDER callouts are monotonically worse -- a caller with over
10k followers returns **-65.8%**, and entity-level Spearman of follower count against the
8 h return is rho = -0.502. A 17,450-follower caller sits in the worst bucket of that
population by construction. So "do his calls go up" is not an open question.

Three things are open, and this module measures each with a structure-preserving null:

(1) **Does he mark WIGGLE-RICH moments better than the ambient callout stream?** The
    operator does not buy and hold; they harvest oscillation. ``RESULT_callout_volatility.md``
    established that the ambient callout DOES mark two-sided flow and harvestable wiggle
    enormously (median called coin: 33 both-sided trades in the next hour against 2 for a
    matched control) -- and that the effect dies once the on-chain burst the callout echoes
    is controlled for. The open question is therefore narrower and sharper: is HE better
    than the ambient stream *at matched moments*? The match is not optional. A called coin
    is by construction ~27 minutes old with a 242-buyer crowd behind it, and an unmatched
    comparison recovers that instead of an effect.

(2) **Is he trading against his followers?** Bought-before-the-call, sold-into-the-call.

(3) **Is his pump.fun profile wallet even his trading wallet?** ``RESULT_caller_wallets.md``
    §1 says almost certainly not: the native pump.fun ``x_username`` link is served null on
    all 317 wallets probed, and the handle->wallet join reaches 3.4% by identity. A clean
    null on ``BAr5csYt...`` is the expected outcome and is a real finding, not a failure.

WHAT IS REUSED RATHER THAN REBUILT
-----------------------------------
* ``studies.callout_volatility`` -- the price instrument (the bonding-curve identity that
  prices every pump coin for free from ``state/bulk_pump/daily/``), ``zigzag``,
  ``realized_variance``, ``round_trip_threshold``, ``Series``, ``load_series``, ``measure``,
  ``build_cohort``, ``clustered_slope``, ``by_fdr``. Nothing about the instrument is
  restated here; a study that priced friction its own way would not be comparable with the
  desk that trades on it.
* ``studies.caller_wallets`` -- ``benjamini_hochberg``, and the SHAPE of ``temporal_join``'s
  null. A hypergeometric test over callouts is WRONG here and was tried first in that study:
  it returned 1,758 false positives where the time-matched substitution returns 1.
* ``studies.callout_backfill`` -- the retro X harness. The pinned actor honours
  ``since_time:`` / ``until_time:``, so one account's history is retrospectively collectable.

THE WALLET TAPE IS FREE HERE, AND THAT IS A CHANGE
---------------------------------------------------
``RESULT_caller_wallets.md`` paid $1.12 of BigQuery for a 27-hour wallet-level swap tape.
It did not have to. ``state/bulk_pump/daily/`` carries the post-token-balance leg of every
transaction with its ``owner``, so per-(mint, owner) balance differences ARE the wallet
tape -- ten days of it, for $0. That is what §3 and §4 run on. The one thing it cannot see
is the SOL leg, so every size statement is in token base units, normalised per mint.

RUNNING IT
----------
    uv run --group research python -m studies.jackduval_workup --collect
    uv run --group research python -m studies.jackduval_workup --calls
    uv run --group research python -m studies.jackduval_workup --wallet-tape
    uv run --group research python -m studies.jackduval_workup --report --draws 200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Final, Sequence

from studies.callout_volatility import (
    CURVE_K,
    CURVE_TOKEN_OFFSET,
    PUMP_SUPPLY_RAW,
    Series,
    by_fdr,
    clustered_slope,
    realized_variance,
    round_trip_threshold,
    two_sided_p,
    zigzag,
)

REPO: Final[Path] = Path(__file__).resolve().parent.parent
CALLOUTS: Final[Path] = REPO / "state" / "callouts"
CACHE: Final[Path] = REPO / ".cache" / "jackduval"

#: The subject. Resolved and on-curve-verified 2026-08-15; see `wallet_labels.yaml`.
HANDLE: Final[str] = "jackduvalcalls"
PROFILE_WALLET: Final[str] = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh"
#: Capital-I homoglyph of the handle, 9 followers. `wallet_labels.yaml` kind: adversary.
IMPOSTER_WALLET: Final[str] = "9T8QKsR28boKJL3x3td39rX8dk1xsd5zwWaF2nFzijvP"

#: The two calls the operator named. If neither appears in what is collected, the handle or
#: the actor's history depth is wrong and everything downstream is built on the wrong
#: account -- so this is a HARD gate, not a sanity print.
NAMED_CALLS: Final[tuple[str, ...]] = ("fatdogwithhat", "calico")

#: The ambient callout census, 2026-08-14T14:21Z -> 2026-08-15T00:21Z.
CENSUS_PATH: Final[Path] = CALLOUTS / "backfill-1786717285-1786753261.jsonl"


# ============================================================== 1. the retro X census


async def _collect(
    *,
    handle: str,
    start_unix: int,
    end_unix: int,
    slice_seconds: int,
    max_items: int,
    out: Path,
    echo: Callable[[str], None] = print,
) -> dict[str, int]:
    """`from:<handle>` walked backwards in bounded slices, verbatim to JSONL.

    Same discipline as ``studies/callout_backfill.py``, which this deliberately mirrors
    rather than imports: one clock per field (``t_post`` is the tweet's own ``created_at``,
    ``t_collect`` is ours), slices record the window they asked for so a capped slice is
    visible as truncation, and no filtering happens here -- cohort construction belongs to
    the study.
    """
    import httpx

    from shitcoims_intelligence.adapters.x_apify import XApifyAdapter, XApifyConfig

    cfg = XApifyConfig(
        enabled=True, token_file=Path("~/.apify-token"), max_items_per_query=max_items
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    stats = {"queries": 0, "tweets": 0, "with_mint": 0, "capped_slices": 0, "failed": 0}
    seen: set[str] = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                seen.add(str(json.loads(line).get("tweet_id")))
        echo(f"collect: {len(seen)} tweet ids already on disk at {out.name}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as http:
        adapter = XApifyAdapter(cfg, http)
        with out.open("a") as fh:
            lo = start_unix
            while lo < end_unix:
                hi = min(lo + slice_seconds, end_unix)
                query = f"from:{handle} since_time:{lo} until_time:{hi}"
                stats["queries"] += 1
                try:
                    batch = await adapter.search(query, max_items=max_items)
                except Exception as exc:  # a dead slice must not kill the run
                    stats["failed"] += 1
                    echo(f"  ! {query}: {type(exc).__name__}: {exc}")
                    lo = hi
                    continue
                t_collect = datetime.now(UTC).isoformat()
                n = len(batch.results)
                if n >= max_items:
                    stats["capped_slices"] += 1
                fresh = 0
                for tweet in batch.results:
                    if tweet.tweet_id in seen:
                        continue
                    seen.add(tweet.tweet_id)
                    fresh += 1
                    stats["tweets"] += 1
                    if tweet.all_mints:
                        stats["with_mint"] += 1
                    row = {
                        "t_post": tweet.created_at.isoformat() if tweet.created_at else None,
                        "t_collect": t_collect,
                        "query": query,
                        "slice_start_unix": lo,
                        "slice_end_unix": hi,
                        "tweet_id": tweet.tweet_id,
                        "url": tweet.url,
                        "kind": tweet.kind,
                        "text": tweet.text,
                        "author_username": tweet.author_username,
                        "author_followers": tweet.author_followers,
                        "like_count": tweet.like_count,
                        "retweet_count": tweet.retweet_count,
                        "reply_count": tweet.reply_count,
                        "quote_count": tweet.quote_count,
                        "view_count": tweet.view_count,
                        "cashtags": list(tweet.cashtags),
                        "mentioned_handles": list(tweet.mentioned_handles),
                        "mint_candidates": list(tweet.mint_candidates),
                        "bare_mint_candidates": list(tweet.bare_mint_candidates),
                        "mints": list(tweet.all_mints),
                        "conversation_id": tweet.conversation_id,
                    }
                    fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                fh.flush()
                echo(
                    f"  {datetime.fromtimestamp(lo, UTC):%m-%d %H:%M} .. "
                    f"{datetime.fromtimestamp(hi, UTC):%m-%d %H:%M}  "
                    f"got={n:<3} new={fresh:<3} capped={n >= max_items}"
                )
                lo = hi
    return stats


def collect_path(handle: str = HANDLE) -> Path:
    """NOT under ``state/callouts/``, and that is deliberate.

    ``studies/callout_edge.py``'s ``CALLOUT_GLOB`` is ``state/callouts/*.jsonl`` and it is
    what ``callout_volatility.load_callout_events`` and ``caller_wallets`` both read. A
    one-account history dropped in there silently joins the AMBIENT census that this study
    uses as its control arm, and the control arm would then contain the treatment. It lives
    in ``.cache/`` instead, and the ambient census is loaded by explicit path below.
    """
    return CACHE / f"{handle}-history.jsonl"


def load_collection(handle: str = HANDLE) -> list[dict[str, Any]]:
    path = collect_path(handle)
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_id[str(row["tweet_id"])] = row
    return sorted(by_id.values(), key=lambda r: r.get("t_post") or "")


#: The two coins the operator named. This is the VERIFICATION GATE: if neither appears in
#: what was collected, the handle or the actor's history depth is wrong and everything
#: downstream is built on the wrong account.
def verify_named_calls(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Did he actually say `fatdogwithhat` / `calico`? Substring, deliberately generous.

    Generous because the alternative errs the dangerous way. A strict matcher that missed a
    real mention would let the study proceed on an unverified account, and every number
    after that would be about a stranger. A generous matcher that fires on a false positive
    is caught by reading the six rows it returns.
    """
    hits: dict[str, list[dict[str, Any]]] = {}
    for needle in NAMED_CALLS:
        found = []
        for row in rows:
            haystack = " ".join(
                [str(row.get("text") or ""), " ".join(row.get("cashtags") or ())]
            ).lower()
            if needle in haystack.replace(" ", "") or needle in haystack:
                found.append(row)
        hits[needle] = found
    return hits


@dataclass(frozen=True, slots=True)
class Call:
    """One mint-resolved thing he said. `confirmed` separates a CA from a ticker."""

    mint: str
    t_post: float
    tweet_id: str
    kind: str
    text: str
    followers: int
    views: int
    likes: int
    #: True when the address itself was in the tweet (URL or bare CA). False when the mint
    #: was resolved from a cashtag, which is a WEAKER claim -- three different coins were
    #: named `fatdogwithhat` on 2026-08-15 alone, so a ticker does not identify a coin.
    ca_confirmed: bool


def extract_calls(rows: Sequence[dict[str, Any]]) -> list[Call]:
    """Every mint the account actually put an address to. One row per (tweet, mint)."""
    from shitcoims_intelligence.adapters.x_apify import is_solana_mint

    out: list[Call] = []
    for row in rows:
        stamp = row.get("t_post")
        if not stamp:
            continue
        t_post = datetime.fromisoformat(stamp).timestamp()
        for mint in row.get("mints") or ():
            if not is_solana_mint(str(mint)):
                continue
            out.append(
                Call(
                    mint=str(mint),
                    t_post=t_post,
                    tweet_id=str(row.get("tweet_id")),
                    kind=str(row.get("kind") or ""),
                    text=str(row.get("text") or ""),
                    followers=int(row.get("author_followers") or 0),
                    views=int(row.get("view_count") or 0),
                    likes=int(row.get("like_count") or 0),
                    ca_confirmed=mint in (row.get("mint_candidates") or [])
                    or mint in (row.get("bare_mint_candidates") or []),
                )
            )
    out.sort(key=lambda c: c.t_post)
    return out


# ============================================================== 2. the free wallet tape


BULK: Final[Path] = REPO / "state" / "bulk_pump" / "daily"


def _duckdb(threads: int = 6, memory: str = "10GB") -> Any:
    import duckdb

    con = duckdb.connect()
    con.execute(f"SET threads TO {threads}")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute("SET preserve_insertion_order=false")
    return con


def bulk_days() -> list[Path]:
    return sorted(BULK.glob("*.parquet"))


def _sql_list(values: Sequence[str]) -> str:
    return ",".join("'" + v.replace("'", "") + "'" for v in values)


def scan_wallets(
    wallets: Sequence[str], *, out: Path, echo: Callable[[str], None] = print
) -> Path:
    """Every token-balance leg of a named wallet, over the whole ten-day corpus. $0.

    ``RESULT_caller_wallets.md`` paid $1.12 of BigQuery for 27 hours of this. It did not
    have to: ``state/bulk_pump/daily/`` carries both the ``pre`` and the ``post`` token
    balance array of every transaction, so a leg's delta is
    ``post.amount - pre.amount`` matched on ``account_index`` WITHIN one transaction --
    no lag across transactions, so no first-observation problem and no assumption that the
    corpus saw the wallet's previous trade.

    What it cannot see is the SOL leg (the bonding curve holds native lamports, not a token
    balance), so every size here is token base units, normalised per mint, exactly as that
    study's discipline requires.
    """
    days = bulk_days()
    if not days:
        raise SystemExit(f"no bulk parquet days under {BULK}")
    out.parent.mkdir(parents=True, exist_ok=True)
    listed = _sql_list(wallets)
    shard_dir = out.with_suffix("")
    shard_dir.mkdir(parents=True, exist_ok=True)
    echo(f"scan: {len(days)} day(s) {days[0].name} .. {days[-1].name} for {len(wallets)} wallet(s)")
    # ONE DAY PER QUERY, on purpose. Unnesting `pre` and `post` over all 106.6M rows at once
    # is the shape of pass that OOMs a laptop; a day is ~10.8M rows and finishes bounded.
    # Each day's shard is written before the next starts, so a killed run resumes.
    for day in days:
        shard = shard_dir / f"{day.stem}.parquet"
        if shard.exists():
            echo(f"scan: {day.stem} cached")
            continue
        con = _duckdb(threads=4, memory="8GB")
        con.execute(
            f"""
            COPY (
              WITH src AS (
                SELECT signature, block_time, block_slot, tx_index, pre, post
                FROM read_parquet('{day}')
                WHERE err = '' AND len(list_filter(post, x -> x.owner IN ({listed}))) > 0
              ), post_l AS (
                SELECT s.signature, s.block_time, s.block_slot, s.tx_index,
                       u.owner AS owner, u.mint AS mint, u.account_index AS ai,
                       CAST(u.amount AS HUGEINT) AS amt
                FROM src s, UNNEST(s.post) t(u) WHERE u.owner IN ({listed})
              ), pre_l AS (
                SELECT s.signature, u.account_index AS ai, CAST(u.amount AS HUGEINT) AS amt
                FROM src s, UNNEST(s.pre) t(u) WHERE u.owner IN ({listed})
              )
              SELECT p.signature, p.block_time, p.block_slot, p.tx_index, p.owner, p.mint,
                     CAST(p.amt - COALESCE(q.amt, 0) AS DOUBLE) AS delta,
                     CAST(p.amt AS DOUBLE) AS post_amt
              FROM post_l p LEFT JOIN pre_l q ON p.signature = q.signature AND p.ai = q.ai
            ) TO '{shard}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{shard}')").fetchone()[0]
        con.close()
        echo(f"scan: {day.stem} -> {n:,} legs")
    con = _duckdb(threads=4, memory="8GB")
    con.execute(
        f"""COPY (SELECT * FROM read_parquet('{shard_dir}/*.parquet')
                   ORDER BY block_time, tx_index)
            TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]
    con.close()
    echo(f"scan: {n:,} legs -> {out}")
    return out


WSOL: Final[str] = "So11111111111111111111111111111111111111112"


def build_mint_panel(
    mints: Sequence[str], *, out_prefix: Path, echo: Callable[[str], None] = print
) -> tuple[Path, Path]:
    """The `callout_volatility` panel, restricted to a mint set and widened to ten days.

    Identical construction to ``callout_volatility.build_panel`` -- the same counterparty
    heuristic, the same curve identity, the same ``pool_sol`` -- because the whole point of
    this arm is a contrast against that study's ambient numbers, and a panel built two ways
    is not a contrast. It differs in exactly two respects, both stated: the mint filter, and
    the ten-day span (that study pinned itself to the census window plus two days of
    pre-history; a wallet's ten-day trading record needs the whole corpus).

    Returns (trades panel, wallet leg tape). The leg tape is the object
    ``RESULT_caller_wallets.md`` bought from BigQuery, derived here from ``pre``/``post``
    for $0.
    """
    days = bulk_days()
    listed = _sql_list(mints)
    trades_path = out_prefix.with_name(out_prefix.name + "-trades.parquet")
    legs_path = out_prefix.with_name(out_prefix.name + "-legs.parquet")
    shard_dir = out_prefix.with_name(out_prefix.name + "-raw")
    shard_dir.mkdir(parents=True, exist_ok=True)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    echo(f"panel: {len(days)} day(s), {len(mints)} mint(s)")
    # Day-sharded for the same reason ``scan_wallets`` is: one UNNEST over all 106.6M rows
    # is the pass that kills the machine, and a shard already on disk is never recomputed.
    for day in days:
        shard = shard_dir / f"{day.stem}.parquet"
        if shard.exists():
            continue
        con = _duckdb(threads=4, memory="8GB")
        con.execute(
            f"""
            COPY (
              WITH src AS (
                SELECT signature, block_slot, block_time, tx_index, pre, post
                FROM read_parquet('{day}')
                WHERE err = ''
                  AND len(list_filter(post, x -> x.mint IN ({listed}))) > 0
              ), post_l AS (
                SELECT s.signature, s.block_slot, s.block_time, s.tx_index,
                       u.owner AS owner, u.mint AS mint, u.account_index AS ai,
                       CAST(u.amount AS HUGEINT) AS amt
                FROM src s, UNNEST(s.post) t(u)
                WHERE u.mint IN ({listed}) OR u.mint = '{WSOL}'
              ), pre_l AS (
                SELECT s.signature, u.account_index AS ai, CAST(u.amount AS HUGEINT) AS amt
                FROM src s, UNNEST(s.pre) t(u)
                WHERE u.mint IN ({listed}) OR u.mint = '{WSOL}'
              )
              SELECT p.signature, p.block_slot, p.block_time, p.tx_index, p.owner, p.mint,
                     CAST(p.amt AS DOUBLE) AS amt,
                     CAST(p.amt - COALESCE(q.amt, 0) AS DOUBLE) AS delta
              FROM post_l p LEFT JOIN pre_l q ON p.signature = q.signature AND p.ai = q.ai
            ) TO '{shard}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        n = con.execute(f"SELECT COUNT(*) FROM read_parquet('{shard}')").fetchone()[0]
        con.close()
        echo(f"panel: {day.stem} -> {n:,} legs")
    con = _duckdb()
    con.execute(
        f"CREATE OR REPLACE TABLE legs AS SELECT * FROM read_parquet('{shard_dir}/*.parquet')"
    )
    n_legs = con.execute("SELECT COUNT(*) FROM legs").fetchone()[0]
    echo(f"panel: {n_legs:,} legs")

    # The counterparty, identified exactly as callout_volatility does: the owner in the most
    # of that mint's transactions, tie-broken by largest balance. It is the only account on
    # the other side of every trade, so its balance IS the price state variable.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cp AS
        WITH per_owner AS (
          SELECT mint, owner, COUNT(*) AS n_tx, MAX(amt) AS max_amt
          FROM legs WHERE mint IN ({listed}) GROUP BY mint, owner
        ), ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY mint ORDER BY n_tx DESC, max_amt DESC) AS rk
          FROM per_owner
        )
        SELECT mint, owner AS cp_owner FROM ranked WHERE rk = 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cp_kind AS
        SELECT c.*, EXISTS (SELECT 1 FROM legs l
                             WHERE l.owner = c.cp_owner AND l.mint = '{WSOL}') AS is_pool
        FROM cp c
        """
    )
    con.execute(
        f"""
        COPY (
          WITH cur AS (
            SELECT l.mint, l.block_time, l.block_slot, l.tx_index,
                   CAST(l.amt AS DOUBLE) AS tok_bal,
                   CAST(l.delta AS DOUBLE) AS d_tok, k.is_pool
            FROM legs l JOIN cp_kind k ON l.mint = k.mint AND l.owner = k.cp_owner
            WHERE l.mint IN ({listed})
          ), wsol AS (
            SELECT l.block_slot, l.tx_index, k.mint, CAST(l.amt AS DOUBLE) AS wsol_bal
            FROM legs l JOIN cp_kind k ON l.owner = k.cp_owner
            WHERE l.mint = '{WSOL}' AND k.is_pool
          )
          SELECT c.mint, c.block_time, c.block_slot, c.tx_index, c.tok_bal, c.d_tok,
                 c.is_pool, w.wsol_bal,
                 CASE WHEN c.is_pool AND w.wsol_bal > 0 AND c.tok_bal > 0
                        THEN ln(w.wsol_bal) - ln(c.tok_bal)
                      WHEN NOT c.is_pool AND c.tok_bal + {CURVE_TOKEN_OFFSET} > 0
                        THEN ln({CURVE_K}) - 2 * ln(c.tok_bal + {CURVE_TOKEN_OFFSET})
                 END AS log_price,
                 CASE WHEN c.is_pool AND w.wsol_bal > 0 THEN w.wsol_bal / 1e9
                      WHEN NOT c.is_pool
                        THEN {CURVE_K} / (c.tok_bal + {CURVE_TOKEN_OFFSET}) / 1e9
                 END AS pool_sol,
                 CASE WHEN c.d_tok < 0 THEN 1 WHEN c.d_tok > 0 THEN -1 ELSE 0 END AS side
          FROM cur c LEFT JOIN wsol w
            ON c.mint = w.mint AND c.block_slot = w.block_slot AND c.tx_index = w.tx_index
          ORDER BY c.mint, c.block_slot, c.tx_index
        ) TO '{trades_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    con.execute(
        f"""
        COPY (
          SELECT l.mint, l.block_time, l.block_slot, l.tx_index, l.owner,
                 CAST(l.delta AS DOUBLE) AS delta, CAST(l.amt AS DOUBLE) AS post_amt
          FROM legs l JOIN cp_kind k ON l.mint = k.mint
          WHERE l.mint IN ({listed}) AND l.owner <> k.cp_owner AND l.delta <> 0
          ORDER BY l.mint, l.block_time
        ) TO '{legs_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    n_tr = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{trades_path}') WHERE log_price IS NOT NULL"
    ).fetchone()[0]
    n_lg = con.execute(f"SELECT COUNT(*) FROM read_parquet('{legs_path}')").fetchone()[0]
    con.close()
    echo(f"panel: {n_tr:,} priced counterparty prints -> {trades_path.name}")
    echo(f"panel: {n_lg:,} trader legs -> {legs_path.name}")
    return trades_path, legs_path


# ============================================================== 3. the kernels, retargeted

#: Horizons. 1 h and 8 h are the two the population studies quote, kept so this study is
#: commensurable with them. The three SHORT ones are here because the desk's own firehose
#: caught the subject wallet sniping a coin 14 s after creation and fully exiting 58 s
#: later: at that timescale a 1 h forward return is not a weak instrument, it is the wrong
#: one, and it would report a null about a regime he never trades in.
HORIZONS_S: Final[tuple[int, ...]] = (60, 300, 900, 3_600, 28_800)

#: Realized variance runs on a fixed 60 s grid (``callout_volatility.RV_GRID_S``), so it is
#: undefined below a few minutes and is reported only from here up. The wiggle filter is
#: trade-driven and has no such floor, which is why it is the primary short-horizon outcome.
RV_MIN_HORIZON_S: Final[int] = 900

CLIP_LAMPORTS: Final[int] = 100_000_000


def load_panel_series(path: Path, *, mints: set[str] | None = None) -> dict[str, Series]:
    """This module's panel -> ``callout_volatility.Series``, so the kernels are shared."""
    con = _duckdb()
    where = ""
    if mints is not None:
        listed = _sql_list(sorted(mints))
        where = f"WHERE mint IN ({listed})" if listed else "WHERE FALSE"
    rows = con.execute(
        f"""
        SELECT mint,
               list(block_time ORDER BY block_slot, tx_index) AS times,
               list(log_price ORDER BY block_slot, tx_index) AS logp,
               list(side ORDER BY block_slot, tx_index) AS side,
               list(pool_sol ORDER BY block_slot, tx_index) AS pool_sol,
               any_value(is_pool) AS is_pool
        FROM read_parquet('{path}') WHERE log_price IS NOT NULL
        {"AND" + where[5:] if where else ""}
        GROUP BY mint
        """
    ).fetchall()
    con.close()
    return {
        mint: Series(
            mint=mint,
            times=tuple(int(t) for t in times),
            logp=tuple(float(x) for x in logp),
            side=tuple(int(s) for s in side),
            pool_sol=tuple(float(p) if p is not None else float("nan") for p in pool),
            is_pool=bool(is_pool),
            migrated=bool(is_pool),
        )
        for mint, times, logp, side, pool, is_pool in rows
    }


def mcap_sol(series: Series, t0: float) -> float:
    lp = series.price_at(t0)
    return float("nan") if lp != lp else math.exp(lp) * PUMP_SUPPLY_RAW / 1e9


def measure_at(
    series: Series, t0: float, *, tape_end: int, horizons: Sequence[int] = HORIZONS_S
) -> dict[str, float]:
    """Forward return, wiggle and two-sided flow at one instant, over every horizon.

    CENSORED ROWS ARE NEVER DROPPED. A quiet pool is marked at its last traded price and
    ``stale_<h>`` reports how old that mark is. ``RESULT_callout_edge.md`` §3/§4 measured
    what the other choice does: dropping the coins that stopped trading turned a -12% into
    a +25%, because the coins that stop trading are the ones that died.
    """
    out: dict[str, float] = {}
    depth = series.depth_at(t0)
    take_bps = 105 if series.is_pool else 100
    threshold = round_trip_threshold(depth, take_bps=take_bps)
    out["friction_log"] = threshold
    out["depth_sol"] = depth
    p0 = series.price_at(t0)
    peak = series.peak_before(t0)
    out["drawdown"] = 1.0 - math.exp(p0 - peak) if peak == peak and p0 == p0 else float("nan")
    for horizon in horizons:
        tag = f"{horizon}s"
        t1 = t0 + horizon
        p1 = series.price_at(t1)
        idx = bisect_right(series.times, int(t1)) - 1
        out[f"ret_{tag}"] = math.exp(p1 - p0) - 1.0 if p0 == p0 and p1 == p1 else float("nan")
        out[f"stale_{tag}"] = float(t1 - series.times[idx]) if idx >= 0 else float("nan")
        out[f"beyond_tape_{tag}"] = 1.0 if t1 > tape_end else 0.0
        _times, logp, side = series.window(t0, t1)
        swings, amplitude = zigzag(logp, threshold)
        out[f"wiggle_n_{tag}"] = float(swings)
        out[f"wiggle_net_{tag}"] = amplitude - swings * threshold if swings else 0.0
        buys = sum(1 for s in side if s > 0)
        sells = sum(1 for s in side if s < 0)
        out[f"log_two_sided_{tag}"] = math.log1p(min(buys, sells))
        out[f"trades_{tag}"] = float(len(side))
        if horizon >= RV_MIN_HORIZON_S:
            rv, active = realized_variance(
                series.times, series.logp, t0, min(t1, float(tape_end))
            )
            out[f"rv_{tag}"] = rv
            out[f"active_min_{tag}"] = float(active)
    return out


# ============================================================== 4. his own trading record


@dataclass(frozen=True, slots=True)
class Leg:
    t: int
    slot: int
    tx_index: int
    mint: str
    delta: float  # token base units; > 0 is an increase
    sol: float    # SOL paid (buy) or received (sell), derived from the curve identity
    kind: str = "trade"  # "trade" or "transfer"; a transfer moves tokens at zero SOL


def exit_proceeds(series: Series, tokens: float, t: float) -> float:
    """What SELLING `tokens` at time `t` would actually collect, own impact included.

    Marking an open position at the MARGINAL price is the mistake this function exists to
    avoid, and it is a large one on a bonding curve: the first version of this study marked
    439 open lots that way and produced **+950 SOL** of paper value on 308 SOL of cost, on
    coins whose median forward return at 8 h is -70%. The desk already knows this -- it is
    the GHOST_TOWN own-exit-impact guard, and PROGRAM.md §1.4 caps a clip at 2% impact.

    On the curve the proceeds are the integral, not the tangent::

        sol = k * (1/v_tok - 1/(v_tok + tokens)) / 1e9

    which is bounded above by ``k / v_tok / 1e9`` -- i.e. by the whole pool -- no matter how
    many tokens are dumped, exactly as reality is. On a migrated pool the same constant
    product applies with the pool's own reserves, so the same shape is used there with the
    marginal price standing in for k/v_tok.
    """
    price = series.price_at(t)
    if price != price or tokens <= 0:
        return 0.0
    if series.is_pool:
        depth = series.depth_at(t)
        if not math.isfinite(depth) or depth <= 0:
            return 0.0
        v_tok = math.exp(math.log(depth * 1e9) - price)
        return (depth * 1e9) * (tokens / (v_tok + tokens)) / 1e9
    v_tok = math.exp((math.log(CURVE_K) - price) / 2.0)
    if v_tok <= 0:
        return 0.0
    return CURVE_K * (1.0 / v_tok - 1.0 / (v_tok + tokens)) / 1e9


def sol_ledger(
    trades_path: Path, keys: Sequence[tuple[str, int, int]]
) -> dict[tuple[str, int, int], float]:
    """(mint, slot, tx) -> the SOL that moved, DERIVED exactly on the bonding-curve branch.

    ``RESULT_caller_wallets.md`` states flatly that "SOL legs are not in token balances" and
    reports every size in token units for that reason. On the curve branch that is
    conservative rather than necessary. ``v_sol * v_tok = k`` with ``v_tok = ata + OFFSET``,
    both constants recovered FROM CHAIN by ``callout_volatility --validate`` (offset median
    exactly 7.30e13 over 27,076 matched board observations; k within 1e-6 of 3.219e25 on
    64.3% of them), so the quote leg of a trade is

        sol = k * (1/v_tok_after - 1/v_tok_before) / 1e9

    -- the integral of the curve between the two reserve levels, not a marginal price times
    a quantity. That distinction is not cosmetic: marginal-price-times-quantity over-prices
    every buy and under-prices every sell, so it would bias a P&L in one direction.

    TWO CAVEATS, both stated wherever the number appears.
    1. ``k`` is exactly the pinned value on 64.3% of observations. A coin on another launch
       configuration has its SOL scaled by the ratio of its true k to the pinned one. Within
       one mint that factor is COMMON to the buy and the sell, so it cancels out of a round
       trip's PERCENTAGE return and does not cancel out of its SOL figure. Percentages lead.
    2. On a MIGRATED coin the counterparty is a PumpSwap pool and the identity does not
       apply; those rows fall back to the marginal price and are counted separately.
    """
    if not keys:
        return {}
    con = _duckdb(threads=4)
    con.execute(
        "CREATE TEMP TABLE want (mint VARCHAR, block_slot BIGINT, tx_index BIGINT)"
    )
    con.executemany(
        "INSERT INTO want VALUES (?, ?, ?)", [(m, int(s), int(x)) for m, s, x in keys]
    )
    rows = con.execute(
        f"""SELECT t.mint, t.block_slot, t.tx_index, t.tok_bal, t.d_tok, t.is_pool,
                   t.log_price
            FROM read_parquet('{trades_path}') t
            JOIN want w ON t.mint = w.mint AND t.block_slot = w.block_slot
                       AND t.tx_index = w.tx_index
            WHERE t.log_price IS NOT NULL"""
    ).fetchall()
    con.close()
    out: dict[tuple[str, int, int], float] = {}
    for mint, slot, tx, tok_bal, d_tok, is_pool, log_price in rows:
        if is_pool:
            out[(str(mint), int(slot), int(tx))] = (
                abs(float(d_tok or 0.0)) * math.exp(float(log_price)) / 1e9
            )
            continue
        after = float(tok_bal) + CURVE_TOKEN_OFFSET
        before = float(tok_bal) - float(d_tok or 0.0) + CURVE_TOKEN_OFFSET
        if after <= 0 or before <= 0:
            continue
        out[(str(mint), int(slot), int(tx))] = abs(
            CURVE_K * (1.0 / after - 1.0 / before) / 1e9
        )
    return out


@dataclass
class RoundTrip:
    mint: str
    t_open: int
    t_close: int
    tokens: float
    sol_in: float
    sol_out: float
    #: False when either leg was a transfer rather than a trade. A gift out books as a
    #: -100% "return" and is marketing spend, not a losing trade; the headline win rate is
    #: computed on pure trade-to-trade trips and the mixed ones are reported beside it.
    pure: bool = True

    @property
    def hold_s(self) -> int:
        return self.t_close - self.t_open

    @property
    def pnl_sol(self) -> float:
        return self.sol_out - self.sol_in

    @property
    def pnl_pct(self) -> float:
        return (self.sol_out / self.sol_in - 1.0) if self.sol_in > 0 else float("nan")


def round_trips(
    legs: Sequence[Leg],
) -> tuple[list[RoundTrip], dict[str, float], list[tuple[str, float, float]]]:
    """FIFO round trips per mint. An unclosed position is reported, never silently dropped.

    FIFO rather than average cost because the operator's own live pattern is a sequence of
    small entries and one exit, and average cost would smear a 58-second scalp into the
    position that preceded it. The unclosed residual is counted and reported: a study that
    scored only closed trips would score only the trades he chose to finish.
    """
    by_mint: dict[str, list[Leg]] = defaultdict(list)
    for leg in legs:
        by_mint[leg.mint].append(leg)
    trips: list[RoundTrip] = []
    open_tokens = 0.0
    open_sol = 0.0
    n_open = 0
    open_positions: list[tuple[str, float, float]] = []
    uncovered_sol = 0.0
    uncovered_tokens = 0.0
    n_uncovered = 0
    for mint, seq in by_mint.items():
        seq.sort(key=lambda x: (x.t, x.slot, x.tx_index))
        lots: list[list[float]] = []  # [tokens, sol, t_open]
        for leg in seq:
            if leg.delta > 0:
                lots.append([leg.delta, leg.sol, float(leg.t), 1.0 if leg.kind == "trade" else 0.0])
                continue
            remaining = -leg.delta
            proceeds_rate = leg.sol / remaining if remaining > 0 else 0.0
            if not lots:
                # A sale with no lot to match is inventory acquired BEFORE the corpus opens
                # (or received as a transfer). It has no cost basis here, so it cannot enter
                # a return -- but it is real SOL he collected, and dropping it silently
                # would hide how much of his selling this tape cannot account for.
                uncovered_sol += leg.sol
                uncovered_tokens += remaining
                n_uncovered += 1
            while remaining > 1e-9 and lots:
                lot = lots[0]
                take = min(lot[0], remaining)
                share = take / lot[0] if lot[0] > 0 else 0.0
                trips.append(
                    RoundTrip(
                        mint=mint,
                        t_open=int(lot[2]),
                        t_close=leg.t,
                        tokens=take,
                        sol_in=lot[1] * share,
                        sol_out=proceeds_rate * take,
                        pure=bool(lot[3]) and leg.kind == "trade",
                    )
                )
                lot[0] -= take
                lot[1] -= lot[1] * share
                remaining -= take
                if lot[0] <= 1e-9:
                    lots.pop(0)
        for lot in lots:
            if lot[0] > 1e-9:
                n_open += 1
                open_tokens += lot[0]
                open_sol += lot[1]
                open_positions.append((mint, lot[0], lot[1]))
    trips.sort(key=lambda r: r.t_open)
    return (
        trips,
        {
            "open_lots": float(n_open),
            "open_sol_cost": open_sol,
            "uncovered_sells": float(n_uncovered),
            "uncovered_sol": uncovered_sol,
        },
        open_positions,
    )


# ============================================================== 5. the matched contrast

#: The ambient census's own span, which is the only window in which an ambient arm EXISTS.
#: The head-to-head is run inside it and nowhere else: comparing his ten-day record against
#: a ten-hour ambient stream would recover the diurnal envelope (measured 3.6-5.4x in this
#: market, larger than any effect claimed here) instead of a difference between the two.
CENSUS_START: Final[int] = 1_786_717_285
CENSUS_END: Final[int] = 1_786_753_261
TAPE_END: Final[int] = 1_786_752_000


def load_ambient(path: Path = CENSUS_PATH) -> list[dict[str, Any]]:
    """The 426-callout ambient stream, deduplicated on (mint, caller, minute).

    Same deduplication as ``callout_volatility.load_callout_events``, and for the same
    reason: the census was bought with four overlapping discovery queries, so one tweet
    returned by two of them is one callout and counting it twice would measure collector
    cadence. Loaded by explicit path rather than through ``CALLOUT_GLOB`` so that this
    module's own collection can never leak into its own control arm.
    """
    from shitcoims_intelligence.adapters.x_apify import is_solana_mint

    seen: set[tuple[str, str, int]] = set()
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        stamp = row.get("t_post")
        if not stamp:
            continue
        t_post = datetime.fromisoformat(stamp).timestamp()
        for mint in row.get("mints") or ():
            if not is_solana_mint(str(mint)):
                continue
            key = (str(mint), str(row.get("author_username") or ""), int(t_post // 60))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {"mint": str(mint), "t_post": t_post, "author": row.get("author_username")}
            )
    out.sort(key=lambda r: r["t_post"])
    return out


@dataclass
class ArmRow:
    arm: str  # "jack" | "ambient" | "control"
    mint: str
    t0: float
    log_mcap: float
    log_age: float
    pre_flow: float
    outcomes: dict[str, float]


def build_arm_rows(
    events: Sequence[tuple[str, float]],
    series: dict[str, Series],
    created: dict[str, float],
    *,
    arm: str,
    pre_flow_window_s: int = 600,
) -> list[ArmRow]:
    out: list[ArmRow] = []
    for mint, t0 in events:
        s = series.get(mint)
        if s is None or not s.times or s.times[0] > t0:
            continue
        mcap = mcap_sol(s, t0)
        if not math.isfinite(mcap) or mcap <= 0:
            continue
        birth = created.get(mint) or float(s.times[0])
        age = max(1.0, t0 - birth)
        pre, _lp, _sd = s.window(t0 - pre_flow_window_s, t0)
        out.append(
            ArmRow(
                arm=arm,
                mint=mint,
                t0=t0,
                log_mcap=math.log(mcap),
                log_age=math.log(age),
                pre_flow=math.log1p(len(pre)),
                outcomes=measure_at(s, t0, tape_end=TAPE_END),
            )
        )
    return out


def matched_controls(
    treated: Sequence[ArmRow],
    series: dict[str, Series],
    created: dict[str, float],
    pool: Sequence[str],
    *,
    seed: int,
    per_event: int = 3,
    offers: int = 8,
) -> list[ArmRow]:
    """Population controls in the same (log mcap, log age) bins, on the treated arm's clock.

    Lifted directly from ``callout_volatility.build_cohort`` rather than reinvented: the
    instants are drawn from the treated rows themselves so the control arm inherits the
    treated clock exactly, a candidate that is not alive at that instant is discarded rather
    than re-offered, and each mint contributes at most one row.
    """
    rng = random.Random(seed)
    need: dict[tuple[int, int], int] = defaultdict(int)
    for row in treated:
        need[(int(row.log_mcap * 2), int(row.log_age * 2))] += per_event
    instants = [r.t0 for r in treated]
    if not instants:
        return []
    order = list(pool)
    rng.shuffle(order)
    out: list[ArmRow] = []
    for mint in order:
        if not any(need.values()):
            break
        s = series.get(mint)
        if s is None or len(s.times) < 2:
            continue
        for _ in range(offers):
            t0 = rng.choice(instants)
            idx = bisect_right(s.times, int(t0)) - 1
            if idx < 0 or t0 - s.times[idx] > 300:
                continue
            mcap = mcap_sol(s, t0)
            if not math.isfinite(mcap) or mcap <= 0:
                continue
            birth = created.get(mint) or float(s.times[0])
            key = (int(math.log(mcap) * 2), int(math.log(max(1.0, t0 - birth)) * 2))
            if need.get(key, 0) <= 0:
                continue
            need[key] -= 1
            pre, _lp, _sd = s.window(t0 - 600, t0)
            out.append(
                ArmRow(
                    arm="control",
                    mint=mint,
                    t0=t0,
                    log_mcap=math.log(mcap),
                    log_age=math.log(max(1.0, t0 - birth)),
                    pre_flow=math.log1p(len(pre)),
                    outcomes=measure_at(s, t0, tape_end=TAPE_END),
                )
            )
            break
    return out


def precompute_donors(
    events: Sequence[tuple[str, float]],
    series: dict[str, Series],
    created: dict[str, float],
    pool: Sequence[str],
    *,
    echo: Callable[[str], None] = lambda _m: None,
) -> tuple[dict[tuple[str, float], list[str]], Counter[int]]:
    """For EACH event, the donor coins alive at THAT instant in the same mcap/age bin.

    Done per event and once, rather than on a coarse time grid, because a grid is exactly
    what broke the first two versions of this null. ``callout_volatility.swap_null`` bins
    every coin at one reference instant, which is sound over its ten-hour window; over ten
    days it is not, and the subject makes it worse -- he buys coins that are SECONDS old, so
    a reference instant even half an hour away is usually before his coin existed. Binned on
    a ten-point grid, 47% of his events could not be keyed at all and the "null" ran on 192
    of 362 events, which is not a null, it is a different and smaller experiment.

    Both arms are still keyed at the SAME instant -- that discipline is the point of the
    grid and is kept. The instant is just each event's own.

    Widening ladder, reported: 0 exact bin, 1 the eight neighbours, 2 age-matched at any
    market cap, 3 any coin alive at that instant.
    """

    def key_at(mint: str, t: float) -> tuple[int, int] | None:
        s = series.get(mint)
        if s is None or len(s.times) < 2 or s.times[0] > t:
            return None
        idx = bisect_right(s.times, int(t)) - 1
        if idx < 0 or t - s.times[idx] > 900:
            return None  # not alive: a dead coin is not a donor, it is a zero
        mcap = mcap_sol(s, t)
        if not math.isfinite(mcap) or mcap <= 0:
            return None
        birth = created.get(mint) or float(s.times[0])
        return (int(math.log(mcap) * 2), int(math.log(max(1.0, t - birth)) * 2))

    out: dict[tuple[str, float], list[str]] = {}
    levels: Counter[int] = Counter()
    for n, (mint, t) in enumerate(events):
        target = key_at(mint, t)
        if target is None:
            out[(mint, t)] = []
            levels[-1] += 1
            continue
        table: dict[tuple[int, int], list[str]] = defaultdict(list)
        for donor in pool:
            if donor == mint:
                continue
            k = key_at(donor, t)
            if k is not None:
                table[k].append(donor)
        for level, picked in enumerate(
            (
                table.get(target, []),
                [
                    m
                    for dm in (-1, 0, 1)
                    for da in (-1, 0, 1)
                    if (dm, da) != (0, 0)
                    for m in table.get((target[0] + dm, target[1] + da), [])
                ],
                [m for (_mc, age), g in table.items() if abs(age - target[1]) <= 1 for m in g],
                [m for g in table.values() for m in g],
            )
        ):
            if picked:
                out[(mint, t)] = picked
                levels[level] += 1
                break
        else:
            out[(mint, t)] = []
            levels[-1] += 1
        if n and n % 100 == 0:
            echo(f"    donors: {n}/{len(events)}")
    return out, levels


def contrast(
    rows: Sequence[ArmRow], key: str, *, left: str, right: str, control_flow: bool = False
) -> dict[str, float]:
    """`left` minus `right` on one outcome, conditional on log mcap and log age.

    Frisch-Waugh with a mint-clustered sandwich, i.e. ``callout_volatility``'s estimator on
    ``callout_volatility``'s conditioning set, so the number is commensurable with that
    study's ambient tables rather than merely similar to them.
    """
    import numpy as np

    subset = [r for r in rows if r.arm in (left, right)]
    if not subset:
        return {"n_l": 0.0, "n_r": 0.0, "diff": float("nan"), "z": float("nan")}
    xs = [1.0 if r.arm == left else 0.0 for r in subset]
    ys = [r.outcomes.get(key, float("nan")) for r in subset]
    controls: list[Sequence[float]] = [
        [r.log_mcap for r in subset],
        [r.log_age for r in subset],
    ]
    if control_flow:
        controls.append([r.pre_flow for r in subset])
    slope, se, n = clustered_slope(xs, ys, [r.mint for r in subset], controls=tuple(controls))
    lv = [r.outcomes.get(key, float("nan")) for r in subset if r.arm == left]
    rv = [r.outcomes.get(key, float("nan")) for r in subset if r.arm == right]
    lv = [v for v in lv if v == v]
    rv = [v for v in rv if v == v]
    return {
        "n_l": float(len(lv)),
        "n_r": float(len(rv)),
        "median_l": float(np.median(lv)) if lv else float("nan"),
        "median_r": float(np.median(rv)) if rv else float("nan"),
        "diff": slope,
        "se": se,
        "z": slope / se if se and math.isfinite(se) and se > 0 else float("nan"),
        "n": float(n),
    }


PUMP_API: Final[str] = "https://frontend-api-v3.pump.fun"


def fetch_coin_meta(
    mints: Sequence[str], *, pause: float = 0.15, echo: Callable[[str], None] = print
) -> dict[str, dict[str, Any]]:
    """pump.fun coin metadata, cached one file per mint. Free, browser-UA, rate-limited.

    Gives four things nothing else here can: the coin's `name` and `symbol` (so "did he
    trade `fatdogwithhat`?" is answerable at all), its `creator` (so "did he LAUNCH it?"
    is too), its `created_timestamp` (a real birth clock rather than "the first print this
    corpus happened to see"), and its advertised `twitter`.
    """
    import time

    import httpx

    out_dir = CACHE / "coins"
    out_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, Any]] = {}
    todo = []
    for mint in mints:
        path = out_dir / f"{mint}.json"
        if path.exists():
            try:
                meta = json.loads(path.read_text())
            except Exception:
                todo.append(mint)
                continue
            if not meta.get("_notfound"):
                out[mint] = meta
            continue
        todo.append(mint)
    echo(f"coins: {len(out)} cached, {len(todo)} to fetch")
    headers = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    with httpx.Client(timeout=httpx.Timeout(20, connect=5), headers=headers) as client:
        for i, mint in enumerate(todo):
            path = out_dir / f"{mint}.json"
            try:
                response = client.get(f"{PUMP_API}/coins/{mint}")
                meta = response.json() if response.status_code == 200 else {"_notfound": True}
            except Exception:
                meta = {"_notfound": True}
            if not isinstance(meta, dict):
                meta = {"_notfound": True}
            path.write_text(json.dumps(meta))
            if not meta.get("_notfound"):
                out[mint] = meta
            if i and i % 100 == 0:
                echo(f"coins: {i}/{len(todo)}")
            time.sleep(pause)
    return out


def counterparty_moves(trades_path: Path) -> dict[tuple[str, int, int], float]:
    """(mint, slot, tx_index) -> the counterparty's own token-balance change in that tx.

    THIS IS WHAT SEPARATES A SELL FROM A GIFT, and the distinction is not academic here:
    the subject tweets *"i legit will airdrop any and everyone who makes doxxed tiktoks for
    this coin"*, so his wallet emits large negative deltas that are **transfers to
    strangers, not sales into his own callout**. Scored on the owner's delta alone those
    are indistinguishable, and the study would report a textbook sell-into-the-call that
    never happened.

    A trade against the bonding curve moves the CURVE's balance in the opposite direction
    inside the same transaction. A transfer to a person does not touch the curve at all.
    """
    con = _duckdb(threads=4)
    rows = con.execute(
        f"""SELECT mint, block_slot, tx_index, SUM(d_tok)
            FROM read_parquet('{trades_path}') GROUP BY 1, 2, 3"""
    ).fetchall()
    con.close()
    return {(str(m), int(s), int(x)): float(d or 0.0) for m, s, x, d in rows}


def classify_leg(
    moves: dict[tuple[str, int, int], float], mint: str, slot: int, tx: int, delta: float
) -> str:
    """`trade` when the counterparty moved oppositely in the same tx, else `transfer`."""
    move = moves.get((mint, slot, tx))
    if move is None or move == 0.0:
        return "transfer"
    if (move > 0) == (delta > 0):
        return "transfer"
    # A partial match is still a trade: one transaction can route a buy and a transfer
    # together, and the curve leg is the part that was traded.
    return "trade"


def named_legs(wallet: str, *, pump_only: bool = True) -> list[tuple[int, int, int, str, float]]:
    """(block_time, slot, tx_index, mint, delta) for one wallet, non-zero deltas only."""
    path = CACHE / "named_wallet_legs.parquet"
    con = _duckdb(threads=4)
    clause = "AND mint LIKE '%pump'" if pump_only else ""
    rows = con.execute(
        f"""SELECT block_time, block_slot, tx_index, mint, delta
            FROM read_parquet('{path}')
            WHERE owner = '{wallet}' AND delta <> 0 {clause}
            ORDER BY block_time, block_slot, tx_index"""
    ).fetchall()
    con.close()
    return [(int(a), int(b), int(c), str(d), float(e)) for a, b, c, d, e in rows]


def study_mints(*, donors: int, seed: int) -> set[str]:
    """His mints, the imposter's, the ambient census's, and a donor sample.

    The donors are drawn from mints that traded inside the census window in
    ``callout_volatility``'s own panel -- i.e. from the population, not from the coins
    somebody tweeted about. Drawing donors from the callout cohort would make the control
    arm a *different callout cohort*, which is a comparison between two treatments.
    """
    from studies.callout_volatility import DATA as CV_DATA
    from studies.callout_volatility import active_mints

    mints = {m for _t, _s, _x, m, _d in named_legs(PROFILE_WALLET)}
    mints |= {m for _t, _s, _x, m, _d in named_legs(IMPOSTER_WALLET)}
    mints |= {e["mint"] for e in load_ambient()}
    panel = CV_DATA / f"trades-{CENSUS_START}-{CENSUS_END}.parquet"
    if panel.exists() and donors > 0:
        pool = [
            m
            for m in active_mints(panel, start_unix=CENSUS_START, end_unix=CENSUS_END)
            if m not in mints
        ]
        rng = random.Random(seed)
        rng.shuffle(pool)
        mints |= set(pool[:donors])
    return mints


# ============================================================== 6. his other wallets


@dataclass(frozen=True, slots=True)
class LegTape:
    """Every trader's signed deltas on one mint, time-ordered. The BigQuery object, free."""

    mint: str
    times: tuple[int, ...]
    wallets: tuple[str, ...]
    deltas: tuple[float, ...]

    def buyers_between(self, lo: float, hi: float) -> set[str]:
        i = bisect_left(self.times, math.ceil(lo))
        j = bisect_right(self.times, math.floor(hi))
        return {w for w, d in zip(self.wallets[i:j], self.deltas[i:j], strict=True) if d > 0}


def load_leg_tapes(path: Path, *, mints: set[str] | None = None) -> dict[str, LegTape]:
    con = _duckdb(threads=4)
    where = ""
    if mints is not None:
        listed = _sql_list(sorted(mints))
        where = f"WHERE mint IN ({listed})" if listed else "WHERE FALSE"
    rows = con.execute(
        f"""SELECT mint, list(block_time ORDER BY block_time) AS t,
                   list(owner ORDER BY block_time) AS w,
                   list(delta ORDER BY block_time) AS d
            FROM read_parquet('{path}') {where} GROUP BY mint"""
    ).fetchall()
    con.close()
    return {
        m: LegTape(m, tuple(int(x) for x in t), tuple(str(x) for x in w),
                   tuple(float(x) for x in d))
        for m, t, w, d in rows
    }


def temporal_join(
    events: Sequence[tuple[str, float]],
    tapes: dict[str, LegTape],
    donors_at: Callable[[str, float], list[str]],
    *,
    window: int,
    draws: int,
    seed: int,
    exclude: frozenset[str],
) -> dict[str, Any]:
    """Does any wallet repeatedly buy just before HIS buys, beyond a matched-coin null?

    The statistic is ``caller_wallets.temporal_join``'s: the largest number of his distinct
    coins that any single wallet bought inside ``window`` before his own first buy.

    THE NULL IS NOT HYPERGEOMETRIC AND THAT IS THE WHOLE METHODOLOGICAL CONTENT.
    ``RESULT_caller_wallets.md`` §3 tried the hypergeometric formulation FIRST and it
    returned **1,758** FDR-significant wallet-caller pairs where the correct null returns
    **1**; it treats events as exchangeable, so anyone who is simply awake during a busy
    hour scores as specific. Here each of his (coin, instant) pairs is replaced by
    (a DIFFERENT coin alive at THAT SAME instant in the same market-cap and age bin, the
    same instant), which holds fixed the hour, the market-wide burst structure, and every
    substituted coin's own trade tape. Only WHICH COIN HE PICKED varies.
    """
    rng = random.Random(seed)

    def best(pairs: Sequence[tuple[str, float]]) -> tuple[int, dict[str, int]]:
        hits: Counter[str] = Counter()
        for mint, t in pairs:
            tape = tapes.get(mint)
            if tape is None:
                continue
            for wallet in tape.buyers_between(t - window, t):
                if wallet in exclude:
                    continue
                hits[wallet] += 1
        return (max(hits.values(), default=0), dict(hits))

    observed, hits = best(events)
    null: list[int] = []
    usable = 0
    levels: Counter[int] = Counter()
    for _ in range(draws):
        sample: list[tuple[str, float]] = []
        for mint, t in events:
            options, level = donors_at(mint, t)
            if options:
                sample.append((rng.choice(options), t))
                levels[level] += 1
            else:
                levels[-1] += 1
        usable = max(usable, len(sample))
        null.append(best(sample)[0])
    exceed = sum(1 for v in null if v >= observed)
    top = sorted(hits.items(), key=lambda kv: -kv[1])[:12]
    return {
        "n_events": len(events),
        "window_s": window,
        "observed_best": observed,
        "n_wallets_at_best": sum(1 for v in hits.values() if v == observed),
        "top_wallets": top,
        "n_candidate_wallets": len(hits),
        "null_mean": statistics.fmean(null) if null else float("nan"),
        "null_p95": sorted(null)[int(0.95 * (len(null) - 1))] if null else float("nan"),
        "null_max": max(null) if null else 0,
        "null_events_placed": usable,
        "match_levels": dict(levels),
        "p_perm": (exceed + 1) / (draws + 1),
        "draws": draws,
    }


def crowd_check(
    events: Sequence[tuple[str, float]], tapes: dict[str, LegTape], *, window: int
) -> dict[str, float]:
    """How many strangers are in the same pre-buy band? §4's lesson, made mandatory.

    ``RESULT_caller_wallets.md`` §4: the ONE wallet-caller link that survived a proper null
    looked like a front-runner caught in the act -- 48 of 51 coins, a 26-second median lead,
    an 18-second interquartile spread -- and was an ECHO, because **161 other wallets** were
    in the same band on every one of those coins. Counting the company is what decides it,
    so nothing here is offered as "his wallet" without this table beside it.
    """
    import numpy as np

    counts = []
    for mint, t in events:
        tape = tapes.get(mint)
        if tape is None:
            continue
        counts.append(len(tape.buyers_between(t - window, t)))
    if not counts:
        return {"n": 0.0}
    arr = np.asarray(counts, dtype=float)
    return {
        "n": float(len(arr)),
        "median": float(np.median(arr)),
        "p90": float(np.percentile(arr, 90)),
        "mean": float(arr.mean()),
        "max": float(arr.max()),
    }


# ============================================================== 7. the report

#: The declared family for the matched contrast, fixed before any estimate. Three outcomes
#: x five horizons, less the four (rv at 60 s and 300 s, both arms) that the 60-second RV
#: grid cannot define. PROGRAM.md §3.9 makes the trials count part of the result.
FAMILY_OUTCOMES: Final[tuple[str, ...]] = ("wiggle_net", "log_two_sided", "rv")


def family_keys() -> list[str]:
    keys: list[str] = []
    for outcome in FAMILY_OUTCOMES:
        for horizon in HORIZONS_S:
            if outcome == "rv" and horizon < RV_MIN_HORIZON_S:
                continue
            keys.append(f"{outcome}_{horizon}s")
    return keys


def entry_events(legs: Sequence[tuple[int, int, int, str, float]]) -> list[tuple[str, float]]:
    """His FIRST buy on each mint. One opportunity per coin, not one per clip.

    ``caller_wallets.caller_mint_calls`` makes the same choice and says why: a wallet that
    buys the same coin nine times supplies one opportunity for a coincidence, not nine, and
    counting the repeats lets one busy afternoon manufacture a p-value.
    """
    first: dict[str, float] = {}
    for t, _slot, _tx, mint, delta in legs:
        if delta > 0 and (mint not in first or t < first[mint]):
            first[mint] = float(t)
    return sorted(first.items(), key=lambda kv: kv[1])


def render_contrast(title: str, rows: Sequence[ArmRow], left: str, right: str) -> list[str]:
    out = [f"  {title}", f"    {'outcome':<22} {'n_l':>5} {'n_r':>5} "
           f"{'median_l':>11} {'median_r':>11} {'diff':>9} {'z':>7} {'p':>9} BY"]
    keys = family_keys()
    cells = [contrast(rows, k, left=left, right=right) for k in keys]
    flags = by_fdr([two_sided_p(c["z"]) for c in cells], q=0.10)
    for key, cell, flag in zip(keys, cells, flags, strict=True):
        p = two_sided_p(cell["z"])
        out.append(
            f"    {key:<22} {cell['n_l']:>5.0f} {cell['n_r']:>5.0f} "
            f"{cell['median_l']:>11.5g} {cell['median_r']:>11.5g} "
            f"{cell['diff']:>9.3f} {cell['z']:>7.2f} {p:>9.4f} {'YES' if flag else ''}"
        )
    return out


def max_abs_z(rows: Sequence[ArmRow], left: str, right: str) -> float:
    best = float("nan")
    for key in family_keys():
        z = contrast(rows, key, left=left, right=right)["z"]
        if math.isfinite(z) and (not math.isfinite(best) or abs(z) > best):
            best = abs(z)
    return best


def on_curve(address: str) -> bool:
    """Is there a private key that can sign for this address?

    Mandatory before any address is written down as somebody's wallet. This repo has had
    TWO fabricated off-curve addresses in `wallet_labels.yaml` -- one of them a truncated
    display completed with an invented tail, which is off the ed25519 curve and therefore
    could never have received the money it was credited with. An off-curve hit here is a
    program-derived account (a bonding curve, a pool, an ATA), never a person.
    """
    try:
        from solders.pubkey import Pubkey

        return bool(Pubkey.from_string(address).is_on_curve())
    except Exception:
        return False


def quantiles(values: Sequence[float], qs: Sequence[float] = (0.1, 0.5, 0.9)) -> list[float]:
    import numpy as np

    clean = [v for v in values if v == v]
    if not clean:
        return [float("nan")] * len(qs)
    return [float(np.percentile(clean, q * 100)) for q in qs]


def run(
    *,
    draws: int,
    seed: int,
    breadth: Path | None = None,
    echo: Callable[[str], None] = print,
) -> None:

    trades_path = CACHE / "panel-trades.parquet"
    legs_path = CACHE / "panel-legs.parquet"
    if not trades_path.exists():
        raise SystemExit(f"build the panel first: {trades_path} is missing")

    tweets = load_collection("jackduval")
    calls = extract_calls(tweets)
    named = verify_named_calls(tweets)
    ambient = load_ambient()
    jack_all = named_legs(PROFILE_WALLET)
    imp_all = named_legs(IMPOSTER_WALLET)
    meta = fetch_coin_meta(
        sorted({m for _t, _s, _x, m, _d in jack_all + imp_all}), echo=lambda _m: None
    )
    series = load_panel_series(trades_path)
    moves = counterparty_moves(trades_path)
    # Everything downstream runs on TRADES, never on raw balance legs. A gift out and a
    # sale look identical in the owner's own delta, and this account gives coins away.
    jack = [
        leg for leg in jack_all
        if classify_leg(moves, leg[3], leg[1], leg[2], leg[4]) == "trade"
    ]
    imp = [
        leg for leg in imp_all
        if classify_leg(moves, leg[3], leg[1], leg[2], leg[4]) == "trade"
    ]

    echo("=" * 96)
    echo("§0  THE ACCOUNT, AND THE VERIFICATION GATE")
    echo("=" * 96)
    stamps = [t["t_post"] for t in tweets if t.get("t_post")]
    echo("  X handle collected                    from:jackduval")
    echo(f"  tweets collected                      {len(tweets)}")
    echo(f"  window                                {min(stamps)} .. {max(stamps)}")
    kinds = Counter(t.get("kind") for t in tweets)
    echo(f"  kinds                                 {dict(kinds)}")
    echo(f"  carrying a MINT                       {sum(1 for t in tweets if t.get('mints'))}")
    echo(f"  carrying a CASHTAG                    {sum(1 for t in tweets if t.get('cashtags'))}")
    echo(f"  mint-resolved calls (tweet x mint)    {len(calls)}")
    echo(f"    of which CA-confirmed               {sum(1 for c in calls if c.ca_confirmed)}")
    for needle, hits in named.items():
        echo(f"  VERIFICATION  '{needle}' in his tweets: {len(hits)}")
    traded_names = {
        m: f"{(meta.get(m) or {}).get('name') or ''}|{(meta.get(m) or {}).get('symbol') or ''}"
        for m in {mm for _t, _s, _x, mm, _d in jack_all}
    }
    for needle in NAMED_CALLS:
        hit = [m for m, nm in traded_names.items() if needle in nm.lower().replace(" ", "")]
        echo(f"  VERIFICATION  '{needle}' among the {len(traded_names)} mints his WALLET "
             f"touched: {len(hit)} {hit[:4]}")

    echo("")
    echo("=" * 96)
    echo("§1  HIS WALLET'S TEN-DAY TRADING RECORD  (the free corpus; $0)")
    echo("=" * 96)
    echo(f"  mints priced in the panel             {len(series):,}")
    ledger = sol_ledger(
        trades_path, [(m, s, x) for _t, s, x, m, _d in jack_all + imp_all]
    )
    echo(f"  legs with a derived SOL amount        {len(ledger):,}")
    for wallet, label, legs in (
        (PROFILE_WALLET, "jackduvalcalls  BAr5csYt", jack_all),
        (IMPOSTER_WALLET, "imposter        9T8QKsR2", imp_all),
    ):
        priced: list[Leg] = []
        unpriced = 0
        transfers = 0
        transfer_out = 0.0
        for t, slot, tx, mint, delta in legs:
            s = series.get(mint)
            if s is None:
                unpriced += 1
                continue
            if classify_leg(moves, mint, slot, tx, delta) == "transfer":
                transfers += 1
                if delta < 0:
                    transfer_out += 1
                # Carried into the FIFO at ZERO SOL rather than dropped. He tweets *"i legit
                # will airdrop any and everyone who makes doxxed tiktoks for this coin"*, so
                # tokens leave this wallet as gifts. Dropping those legs would leave the
                # given-away tokens sitting in the ledger as an open position and mark them
                # as if he still had them to sell.
                priced.append(
                    Leg(t=t, slot=slot, tx_index=tx, mint=mint, delta=delta, sol=0.0,
                        kind="transfer")
                )
                continue
            sol = ledger.get((mint, slot, tx), float("nan"))
            if not math.isfinite(sol) or sol <= 0:
                unpriced += 1
                continue
            priced.append(Leg(t=t, slot=slot, tx_index=tx, mint=mint, delta=delta, sol=sol))
        trips, residual, open_lots = round_trips(priced)
        buys = [x for x in priced if x.delta > 0 and x.kind == "trade"]
        sells = [x for x in priced if x.delta < 0 and x.kind == "trade"]
        echo(f"  --- {label}")
        echo(f"    legs / priced trades / unpriced     {len(legs)} / {len(buys) + len(sells)}"
             f" / {unpriced}")
        echo(f"    NON-TRADE legs (transfers)          {transfers} "
             f"({transfer_out:.0f} outbound) -- gifts and airdrops, not sales")
        echo(f"    distinct mints                      {len({x.mint for x in priced})}")
        echo(f"    buys / sells                        {len(buys)} / {len(sells)}")
        echo(f"    SOL bought / sold (derived)         {sum(x.sol for x in buys):.2f} / "
             f"{sum(x.sol for x in sells):.2f}")
        clip = quantiles([x.sol for x in buys])
        echo(f"    buy clip SOL  p10/median/p90        {clip[0]:.4f} / {clip[1]:.4f} / {clip[2]:.4f}")
        pure_trips = [t for t in trips if t.pure]
        if pure_trips:
            trips_all = trips
            trips = pure_trips
            holds = [t.hold_s for t in trips]
            pcts = [t.pnl_pct for t in trips if math.isfinite(t.pnl_pct)]
            hq = quantiles(holds)
            pq = quantiles(pcts)
            wins = sum(1 for p in pcts if p > 0)
            echo(f"    FIFO round trips, trade->trade      {len(trips)} of "
                 f"{len(trips_all)} ({len(trips_all) - len(trips)} involve a transfer leg)")
            echo(f"      lots left open                    {residual['open_lots']:.0f}, "
                 f"{residual['open_sol_cost']:.2f} SOL at cost")
            echo(f"    hold seconds p10/median/p90         {hq[0]:.0f} / {hq[1]:.0f} / {hq[2]:.0f}")
            quick = sum(1 for h in holds if h < 120) / len(holds)
            echo(f"    share held under 120 s              {quick:.3f}")
            echo(f"    round-trip return p10/median/p90    {pq[0]:+.3f} / {pq[1]:+.3f} / {pq[2]:+.3f}")
            echo(f"    win rate (gross, pre-friction)      {wins}/{len(pcts)} = {wins / len(pcts):.3f}")
            echo(f"    summed SOL P&L on closed trips      {sum(t.pnl_sol for t in trips):+.3f}")
            echo(f"    mean / median SOL per closed trip   "
                 f"{statistics.fmean(t.pnl_sol for t in trips):+.4f} / "
                 f"{statistics.median(t.pnl_sol for t in trips):+.4f}")
            # Closed trips alone are a SELECTION: FIFO closes the oldest lots first, so the
            # positions still open at the tape's edge are the ones he had not sold, and
            # scoring only what he chose to finish would score the wrong thing. They are
            # marked at their coin's last traded price -- the same discipline arm (a) uses.
            mark = 0.0
            naive_mark = 0.0
            unpriced_open = 0
            by_open_mint: dict[str, float] = defaultdict(float)
            open_cost = 0.0
            for mint, tokens, cost in open_lots:
                by_open_mint[mint] += tokens
                open_cost += cost
            for mint, tokens in by_open_mint.items():
                s = series.get(mint)
                if s is None:
                    unpriced_open += 1
                    continue
                price = s.price_at(float(TAPE_END))
                if price != price:
                    unpriced_open += 1
                    continue
                mark += exit_proceeds(s, tokens, float(TAPE_END))
                naive_mark += tokens * math.exp(price) / 1e9
            echo(f"    open position, exit-priced          {mark:.3f} SOL against "
                 f"{open_cost:.3f} SOL of cost ({unpriced_open} mints unpriceable)")
            echo(f"      the same position at the MARGINAL price would read {naive_mark:.1f} "
                 f"SOL -- that gap IS the illiquidity")
            echo(f"    TOTAL, closed + exit-priced open    "
                 f"{sum(t.pnl_sol for t in trips) + mark - open_cost:+.3f} SOL")
            echo(f"    sells with no lot to match          "
                 f"{residual['uncovered_sells']:.0f} legs, "
                 f"{residual['uncovered_sol']:.2f} SOL collected -- inventory older than "
                 f"the corpus, no cost basis, excluded from every return above")
        creators = sum(
            1 for m in {x.mint for x in priced} if (meta.get(m) or {}).get("creator") == wallet
        )
        echo(f"    mints he CREATED (pump.fun creator) {creators}")

    echo("")
    echo("=" * 96)
    echo("§2  ARM (a) — FORWARD RETURNS AT HIS ENTRY INSTANTS")
    echo("=" * 96)
    echo("  Censored rows are NEVER dropped: a quiet pool is marked at its last traded price")
    echo("  and the staleness of that mark is reported. RESULT_callout_edge §3/§4 measured")
    echo("  what the other choice does -- dropping them turned a -12% into a +25%.")
    events = entry_events(jack)
    echo(f"  first-buy events (one per mint)       {len(events)}")
    rows = build_arm_rows(events, series, _created_from_meta(meta), arm="jack")
    echo(f"  priced                                {len(rows)}")
    echo(f"    {'horizon':>8} {'n':>5} {'median':>9} {'mean':>9} {'win':>6} "
         f"{'stale_med':>10} {'past_tape':>9}")
    for horizon in HORIZONS_S:
        tag = f"{horizon}s"
        vals = [r.outcomes.get(f"ret_{tag}", float("nan")) for r in rows]
        vals = [v for v in vals if v == v]
        stale = [r.outcomes.get(f"stale_{tag}", float("nan")) for r in rows]
        beyond = statistics.fmean(
            r.outcomes.get(f"beyond_tape_{tag}", 0.0) for r in rows
        ) if rows else float("nan")
        if not vals:
            continue
        echo(f"    {tag:>8} {len(vals):>5} {statistics.median(vals):>+9.4f} "
             f"{statistics.fmean(vals):>+9.4f} "
             f"{sum(1 for v in vals if v > 0) / len(vals):>6.3f} "
             f"{quantiles(stale)[1]:>10.0f} {beyond:>9.3f}")

    echo("")
    echo("=" * 96)
    echo("§3  ARM (b) — WIGGLE QUALITY: HIM vs THE AMBIENT CALLOUT STREAM, MATCHED")
    echo("=" * 96)
    echo("  Priced on `callout_volatility`'s OWN panel, not this module's. That panel holds")
    echo("  the whole pump population over 2026-08-12T14:21Z..2026-08-15T00:00Z, so the")
    echo("  matched control arm is drawn from the POPULATION rather than from the ~1,250")
    echo("  mints this module happens to have pulled -- and the ambient arm's numbers are")
    echo("  then directly comparable with RESULT_callout_volatility.md's published table,")
    echo("  which is the instrument check.")
    from studies.callout_volatility import DATA as CV_DATA
    from studies.callout_volatility import active_mints
    from studies.callout_volatility import load_series as cv_load_series

    cv_panel = CV_DATA / f"trades-{CENSUS_START}-{CENSUS_END}.parquet"
    if not cv_panel.exists():
        raise SystemExit(f"missing {cv_panel}: run callout_volatility --build first")
    span_lo = CENSUS_START - 2 * 86_400
    amb_events = [(e["mint"], e["t_post"]) for e in ambient]
    in_window = [(m, t) for m, t in events if span_lo <= t <= TAPE_END]
    alive = active_mints(cv_panel, start_unix=span_lo, end_unix=TAPE_END)
    treated_mints = {m for m, _t in in_window} | {m for m, _t in amb_events}
    rng0 = random.Random(seed)
    donor_pool = [m for m in alive if m not in treated_mints]
    rng0.shuffle(donor_pool)
    donor_pool = donor_pool[:12_000]
    cv_series = cv_load_series(cv_panel, mints=treated_mints | set(donor_pool))
    created = _created_from_meta(meta)
    created.update(_cv_created())
    jack_rows = build_arm_rows(in_window, cv_series, created, arm="jack")
    amb_rows = build_arm_rows(amb_events, cv_series, created, arm="ambient")
    cv_pool = [m for m in donor_pool if m in cv_series]
    ctl_rows = matched_controls(
        list(jack_rows) + list(amb_rows), cv_series, created, cv_pool, seed=seed
    )
    echo(f"  panel mints materialised              {len(cv_series):,} "
         f"({len(cv_pool):,} donors for matching)")
    echo(f"  his entries in span / priced          {len(in_window)} / {len(jack_rows)}")
    echo(f"  ambient callouts / priced             {len(amb_events)} / {len(amb_rows)}")
    echo(f"  matched population controls           {len(ctl_rows)}")
    both = list(jack_rows) + list(amb_rows) + list(ctl_rows)
    for lines in (
        render_contrast("HIM minus AMBIENT (the headline)", both, "jack", "ambient"),
        render_contrast("HIM minus MATCHED CONTROL", both, "jack", "control"),
        render_contrast("AMBIENT minus MATCHED CONTROL (the published effect, reproduced)",
                        both, "ambient", "control"),
    ):
        for line in lines:
            echo(line)

    observed = max_abs_z(both, "jack", "ambient")
    echo(f"  observed max|z| over the {len(family_keys())}-cell family: {observed:.3f}")
    span = TAPE_END - span_lo
    rng = random.Random(seed)
    rot: list[float] = []
    swp: list[float] = []
    rot_rows: list[int] = []
    swp_rows: list[int] = []
    echo("  NULL A is a LOCAL shift, not a full circular rotation, and the difference is")
    echo("  measured rather than assumed. He buys coins SECONDS old; a rotation across the")
    echo("  2.4-day span lands most of his instants before his coins existed, so the arm")
    echo("  collapses and the sandwich runs out of clusters -- the exact pathology")
    echo("  RESULT_callout_volatility named. A common FORWARD offset of 5-60 minutes destroys")
    echo("  the alignment between his entry and his coin's own flow while leaving the coin")
    echo("  alive. Forward only, and that is not a free choice: a backward shift lands before")
    echo("  the coin was minted and empties the arm (measured -- a symmetric +/- shift left a")
    echo("  median of EIGHT rows). So this null asks the sharper question anyway: is his entry")
    echo("  MINUTE special against a minute an hour later on the same coin? The full rotation")
    echo("  is reported underneath as the diagnostic it now is.")
    donors_map, donor_levels = precompute_donors(
        in_window, cv_series, created, cv_pool, echo=echo
    )
    echo(f"  swap-null donor match levels          {dict(donor_levels)}")
    full_rot: list[float] = []
    full_rows: list[int] = []
    for draw in range(draws):
        local = rng.uniform(300, 3600)
        arm = build_arm_rows(
            [(m, t + local) for m, t in in_window], cv_series, created, arm="jack"
        )
        rot_rows.append(len(arm))
        rot.append(max_abs_z(arm + list(amb_rows), "jack", "ambient"))
        offset = rng.uniform(0.05 * span, 0.95 * span)
        arm = build_arm_rows(
            [(m, span_lo + ((t - span_lo + offset) % span)) for m, t in in_window],
            cv_series, created, arm="jack",
        )
        full_rows.append(len(arm))
        full_rot.append(max_abs_z(arm + list(amb_rows), "jack", "ambient"))
        swapped = [
            (rng.choice(donors_map[(m, t)]), t)
            for m, t in in_window
            if donors_map.get((m, t))
        ]
        arm = build_arm_rows(swapped, cv_series, created, arm="jack")
        swp_rows.append(len(arm))
        swp.append(max_abs_z(arm + list(amb_rows), "jack", "ambient"))
        if draw and draw % 25 == 0:
            echo(f"    nulls: {draw}/{draws}")
    echo("  A null whose arm is thinner than the real one is not a null, it is the sandwich")
    echo("  running out of clusters -- RESULT_callout_volatility measured exactly that")
    echo(f"  pathology (median max|z| 2.72, p95 12.73). Real jack arm: {len(jack_rows)} rows.")
    for label, values, sizes in (
        ("A forward shift 5-60m (timing)", rot, rot_rows),
        ("B matched-coin swap (identity)", swp, swp_rows),
        ("  diagnostic: full rotation", full_rot, full_rows),
    ):
        clean = sorted(v for v in values if v == v)
        if not clean:
            echo(f"  null {label:<26} no finite draws")
            continue
        exceed = sum(1 for v in clean if v >= observed)
        echo(
            f"  null {label:<26} draws {len(clean):>4}  median {statistics.median(clean):>6.2f}  "
            f"p95 {clean[int(0.95 * (len(clean) - 1))]:>6.2f}  max {clean[-1]:>6.2f}  "
            f"p = {(exceed + 1) / (len(clean) + 1):.4f}   "
            f"arm rows median {statistics.median(sizes):.0f}"
        )

    echo("")
    echo("=" * 96)
    echo("§4  ARM (c) — BUY -> TWEET -> SELL CHOREOGRAPHY")
    echo("=" * 96)
    echo("  For every mint he both TWEETED and TRADED: `tweet - first buy`, so a POSITIVE")
    echo("  number means he BOUGHT FIRST AND POSTED AFTERWARDS, which is the front-running")
    echo("  shape; and `first sell at or after the tweet - tweet`, so a small positive")
    echo("  number is selling into the callout.")
    echo("  THE TRUNCATION THAT DECIDES HOW TO READ THIS: the corpus starts 2026-08-05T00:00Z")
    echo("  and four of the five calls are older than that, so any position he opened before")
    echo("  the tweet is INVISIBLE BY CONSTRUCTION. A 'bought after' reading here is")
    echo("  therefore not evidence he did not front-run; it is evidence the tape cannot see.")
    by_mint_legs: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for t, _slot, _tx, mint, delta in jack:
        by_mint_legs[mint].append((t, delta))
    overlap = 0
    for call in calls:
        legs = sorted(by_mint_legs.get(call.mint, ()))
        if not legs:
            echo(f"    {datetime.fromtimestamp(call.t_post, UTC):%m-%d %H:%M}  "
                 f"{call.mint[:12]}..  ca={call.ca_confirmed}  NO TRADES BY THIS WALLET")
            continue
        overlap += 1
        first_buy = next((t for t, d in legs if d > 0), None)
        first_sell_after = next((t for t, d in legs if d < 0 and t >= call.t_post), None)
        echo(
            f"    tweet {datetime.fromtimestamp(call.t_post, UTC):%m-%d %H:%M}  "
            f"{call.mint[:12]}..  first buy "
            f"{datetime.fromtimestamp(first_buy, UTC):%m-%d %H:%M}" if first_buy
            else f"    tweet {datetime.fromtimestamp(call.t_post, UTC):%m-%d %H:%M}  "
                 f"{call.mint[:12]}..  first buy    none"
        )
        echo(
            f"        tweet - first buy {(call.t_post - first_buy) if first_buy else float('nan'):+9.0f}s"
            f"   first sell after tweet "
            f"{(first_sell_after - call.t_post) if first_sell_after else float('nan'):+9.0f}s"
        )
    echo(f"  mints both tweeted and traded         {overlap} of {len(calls)}")
    echo("  n forbids anything stronger than a lead; this is not an estimate.")

    echo("")
    echo("=" * 96)
    echo("§5  HIS OTHER WALLETS — TEMPORAL JOIN AGAINST A MATCHED-COIN NULL")
    echo("=" * 96)
    tapes = load_leg_tapes(legs_path) if legs_path.exists() else {}
    echo(f"  leg tapes loaded                      {len(tapes)} mints")
    echo("  Donors are drawn from THIS module's ten-day panel, whose mint set is his coins,")
    echo("  the imposter's, the ambient census's and a random population sample -- the only")
    echo("  mints for which a wallet-level leg tape exists at all. A donor a wallet cannot")
    echo("  have been seen trading is not a null, it is a zero.")
    his_mints = {m for _t, _s, _x, m, _d in jack_all}
    join_pool = [m for m in tapes if m not in his_mints and m in series]
    echo(f"  donor mints available for the null    {len(join_pool)}")
    join_donors, join_levels = precompute_donors(
        events, series, created, join_pool, echo=echo
    )
    echo(f"  donor match levels (0 exact .. 3 any) {dict(join_levels)}")

    def donors_at(mint: str, t: float) -> tuple[list[str], int]:
        return join_donors.get((mint, t), []), 0

    exclude = frozenset({PROFILE_WALLET})
    for window in (60, 300):
        result = temporal_join(
            events, tapes, donors_at, window=window, draws=min(draws, 200),
            seed=seed, exclude=exclude,
        )
        crowd = crowd_check(events, tapes, window=window)
        echo(f"  --- pre-buy window {window}s")
        echo(f"    his events / null events placed     {result['n_events']} / "
             f"{result['null_events_placed']}")
        echo(f"    best wallet overlap                 {result['observed_best']} "
             f"({result['n_wallets_at_best']} wallets tie, "
             f"{result['n_candidate_wallets']} candidates)")
        echo(f"    null mean / p95 / max               {result['null_mean']:.2f} / "
             f"{result['null_p95']:.0f} / {result['null_max']}")
        echo(f"    p_perm ({result['draws']} draws)              {result['p_perm']:.4f}")
        echo("    THE CROWD CHECK: distinct wallets buying in the same band")
        echo(f"      median {crowd.get('median', float('nan')):.0f}  "
             f"p90 {crowd.get('p90', float('nan')):.0f}  "
             f"max {crowd.get('max', float('nan')):.0f}  over {crowd.get('n', 0):.0f} coins")
        echo("    THE UNIVERSALITY CHECK: is the candidate HIS, or does it buy everything?")
        echo("      A wallet that buys most of the DONOR coins too -- coins he never")
        echo("      touched -- is a launch sniper that happens to be early on everything,")
        echo("      not a second wallet of his. This is §4 of RESULT_caller_wallets in its")
        echo("      cheapest form: count the company, then count what else the company does.")
        for wallet, k in result["top_wallets"][:6]:
            elsewhere = sum(
                1 for m in join_pool if wallet in tapes[m].buyers_between(0, 2**31)
            )
            echo(
                f"      {wallet}  {k}/{result['n_events']} of HIS coins, "
                f"{elsewhere}/{len(join_pool)} of the DONOR coins, on_curve={on_curve(wallet)}"
            )
    echo("")
    echo("  LEAD OR LAG, which is the whole question for the surviving candidates. The")
    echo("  pre-buy window above is inclusive of his own instant, so a wallet in the same")
    echo("  BLOCK scores identically to one that is genuinely early. This splits them.")
    echo("  RESULT_caller_wallets §7 is the standing warning about what a small lead buys:")
    echo("  a 26-second lead priced on this desk's tapes was a median +0.000%, below the")
    echo("  resolution of every price source here, before friction.")
    candidates = [w for w, _k in result["top_wallets"][:6]]
    profiles = _pump_profiles(candidates)
    for wallet in candidates:
        offsets: list[float] = []
        for mint, t in events:
            tape = tapes.get(mint)
            if tape is None:
                continue
            theirs = [
                tt
                for tt, w, d in zip(tape.times, tape.wallets, tape.deltas, strict=True)
                if w == wallet and d > 0
            ]
            if theirs:
                offsets.append(float(t - min(theirs)))
        if not offsets:
            continue
        q = quantiles(offsets)
        same = sum(1 for o in offsets if o == 0)
        ahead = sum(1 for o in offsets if o > 0)
        name = (profiles.get(wallet) or {}).get("username")
        echo(
            f"    {wallet[:14]}..  n={len(offsets):<4} his buy minus theirs "
            f"p10 {q[0]:+.0f}s med {q[1]:+.0f}s p90 {q[2]:+.0f}s   "
            f"same-second {same}  they-first {ahead}"
        )
        if name:
            echo(f"      pump.fun username: {name!r}  followers="
                 f"{(profiles.get(wallet) or {}).get('followers')}")
    echo("")
    echo("  SAME SECOND, OR SAME TRANSACTION? A block is ~400 ms, so 'same second' still")
    echo("  admits two independent transactions that happened to land together. Sharing a")
    echo("  (slot, tx_index) does not: that is ONE transaction buying for both wallets,")
    echo("  which is a bundle and not a coincidence. Measured against his own buy legs.")
    his_txs = {(m, s, x) for _t, s, x, m, d in jack if d > 0}
    his_slots = {(m, s) for m, s, _x in his_txs}
    for wallet in candidates:
        con = _duckdb(threads=2)
        rows = con.execute(
            f"""SELECT mint, block_slot, tx_index FROM read_parquet('{legs_path}')
                WHERE owner = '{wallet}' AND delta > 0"""
        ).fetchall()
        con.close()
        theirs = {(str(m), int(s), int(x)) for m, s, x in rows}
        same_tx = len(theirs & his_txs)
        same_slot = len({(m, s) for m, s, _x in theirs} & his_slots)
        echo(
            f"    {wallet[:14]}..  buy legs {len(theirs):<5} "
            f"sharing a TRANSACTION with his {same_tx:<5} "
            f"sharing a SLOT with his {same_slot}"
        )

    echo("")
    echo("=" * 96)
    echo("§6  THE IMPOSTER — 9T8QKsR28boKJL3x3td39rX8dk1xsd5zwWaF2nFzijvP")
    echo("=" * 96)
    jack_mints = {m for _t, _s, _x, m, _d in jack}
    imp_mints = {m for _t, _s, _x, m, _d in imp}
    shared = jack_mints & imp_mints
    echo(f"  its distinct mints                    {len(imp_mints)}")
    echo(f"  mints shared with BAr5csYt            {len(shared)}")
    echo(f"  its last trade                        "
         f"{datetime.fromtimestamp(max((t for t, *_ in imp), default=0), UTC)}")
    echo("  username set to the homoglyph         2026-08-09T12:22:51Z "
         "(pump.fun last_username_update_timestamp)")
    if shared:
        echo("  On the shared coins -- does it enter BEFORE him (predation) or AFTER (echo)?")
        offsets: list[float] = []
        for mint in sorted(shared):
            jb = min((t for t, _s, _x, m, d in jack if m == mint and d > 0), default=None)
            ib = min((t for t, _s, _x, m, d in imp if m == mint and d > 0), default=None)
            if jb is None or ib is None:
                continue
            offsets.append(float(ib - jb))
            name = (meta.get(mint) or {}).get("symbol") or ""
            echo(f"    {mint[:12]}.. {name:<12} imposter first buy {ib - jb:+.0f}s "
                 f"relative to his")
        if offsets:
            q = quantiles(offsets)
            echo(f"  offset p10/median/p90                 {q[0]:+.0f} / {q[1]:+.0f} / {q[2]:+.0f} s")
            echo(f"  entered BEFORE him on                 "
                 f"{sum(1 for o in offsets if o < 0)} of {len(offsets)} shared coins")
    echo("  n is small by construction; this is a description, not an estimate.")

    echo("")
    echo("  THE BREADTH CHECK — the number that actually decides §5, and it needs no null.")
    echo("  '0 of 693 donor coins' only bounds a wallet's breadth INSIDE this module's")
    echo("  1,242-mint panel; a wallet trading ten thousand coins outside it would look")
    echo("  identical. So each candidate is scanned against the WHOLE ten-day corpus and")
    echo("  asked one question: what fraction of everything it trades is also traded by him?")
    echo("  A launch sniper answers ~1%. A wallet that only exists to trade alongside him")
    echo("  answers ~99%, and that is not a coincidence any null needs to adjudicate.")
    if breadth:
        con = _duckdb(threads=3, memory="4GB")
        his_pump = {
            str(r[0])
            for r in con.execute(
                f"""SELECT DISTINCT mint FROM read_parquet('{CACHE / "named_wallet_legs.parquet"}')
                    WHERE owner = '{PROFILE_WALLET}' AND mint LIKE '%pump' AND delta <> 0"""
            ).fetchall()
        }
        for wallet in candidates:
            rows = con.execute(
                f"""SELECT DISTINCT mint FROM read_parquet('{breadth}')
                    WHERE owner = '{wallet}' AND mint LIKE '%pump' AND delta <> 0"""
            ).fetchall()
            mints = {str(m) for (m,) in rows}
            shared = len(mints & his_pump)
            if not mints:
                continue
            echo(
                f"    {wallet[:14]}..  trades {len(mints):>6} pump coins in ten days, "
                f"{shared:>4} of them his ({shared / len(mints):.1%}), "
                f"{len(mints) - shared:>6} not"
            )
        con.close()
    else:
        echo("    (not run: pass --breadth to scan the candidates against the whole corpus)")

    echo("")
    echo("=" * 96)
    echo("§7  TRIALS, AND THE LIMITS THAT DECIDE HOW TO READ ALL OF THE ABOVE")
    echo("=" * 96)
    echo(f"  Declared family in §3: 3 outcomes x 5 horizons - 2 undefined rv cells = "
         f"{len(family_keys())} cells,")
    echo("  fitted for three contrasts (him-ambient, him-control, ambient-control) = 39,")
    echo("  each against 3 null distributions of 200 draws. §2 is 5 horizons. §5 is 2 pre-buy")
    echo("  windows x 2 diagnostics. Call it ~50 substantive configurations. PROGRAM.md §3.9:")
    echo("  past ~7, an in-sample Sharpe of 1 is an out-of-sample zero. Nothing here is")
    echo("  offered as a positive result on a marginal cell -- §3 is a null, §1 is a")
    echo("  structural count that needs no model, and §5's survivor is decided by a")
    echo("  0-of-693 count rather than by its p-value.")
    echo("")
    echo("  LIMITS:")
    echo("  * ONE TEN-DAY WINDOW, and the corpus ends 2026-08-15T00:00Z. Regime shift in")
    echo("    this market is measured in weeks (PROGRAM.md §3.6).")
    echo("  * SOL amounts are DERIVED from the curve identity, exactly on the curve branch.")
    echo("    k is the pinned value on 64.3% of observations; a coin on another launch")
    echo("    configuration has its SOL scaled. Within one mint that factor is common to the")
    echo("    buy and the sell, so percentage round-trip returns are k-invariant and absolute")
    echo("    SOL figures are not.")
    echo("  * The forward returns in §2 are marked from his own post-trade price, so his own")
    echo("    impact is inside them. That is the right mark for the copy-trading question --")
    echo("    a copier fills at or after his price -- and the wrong one for 'what did the")
    echo("    coin do'.")
    echo("  * §3's jack arm is 144 rows on 2.4 days, because that is the span of the")
    echo("    population panel. The nulls now carry the same 144 rows, which is what makes")
    echo("    them nulls; the first two versions of this study did not, and their p-values")
    echo("    were artefacts. Both are shown.")
    echo("  * §5's donor match runs mostly at widening level 3 (any coin alive at that")
    echo("    instant): his coins are seconds old and the panel has 693 donors, so exact")
    echo("    (mcap, age) donors barely exist. The permutation p is therefore weak evidence.")
    echo("    THE DONOR-COIN COUNT IS THE EVIDENCE, and it needs no null at all.")
    echo("  * A wallet that mirrors him in the same slot and trades nothing else is")
    echo("    consistent with BOTH 'his own second wallet' and 'a copy bot that follows only")
    echo("    him'. This instrument does not separate those two, and neither reading is")
    echo("    stronger than `inferred`.")


def _pump_profiles(wallets: Sequence[str]) -> dict[str, dict[str, Any]]:
    """pump.fun's public profile for a wallet, cached. A named alt is a name, not a guess."""
    import time

    import httpx

    out_dir = CACHE / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, Any]] = {}
    headers = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    with httpx.Client(timeout=httpx.Timeout(20, connect=5), headers=headers) as client:
        for wallet in wallets:
            path = out_dir / f"{wallet}.json"
            if path.exists():
                try:
                    out[wallet] = json.loads(path.read_text())
                    continue
                except Exception:
                    pass
            try:
                response = client.get(f"{PUMP_API}/users/{wallet}")
                data = response.json() if response.status_code == 200 else {}
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            path.write_text(json.dumps(data))
            out[wallet] = data
            time.sleep(0.2)
    return out


def _cv_created() -> dict[str, float]:
    """The boards vendor's coin-creation clock, as ``callout_volatility`` derives it."""
    from studies.callout_volatility import _created_unix

    try:
        return _created_unix()
    except Exception:
        return {}


def _created_from_meta(meta: dict[str, dict[str, Any]]) -> dict[str, float]:
    """pump.fun's own creation clock, in seconds. Absent is absent -- never back-filled."""
    out: dict[str, float] = {}
    for mint, coin in meta.items():
        stamp = coin.get("created_timestamp")
        if isinstance(stamp, (int, float)) and stamp > 0:
            out[mint] = float(stamp) / 1000.0
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--scan-wallets", action="store_true")
    ap.add_argument("--build-panel", action="store_true")
    ap.add_argument("--donors", type=int, default=400)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--draws", type=int, default=200)
    ap.add_argument("--breadth", action="store_true")
    ap.add_argument("--handle", default=HANDLE)
    ap.add_argument("--start-unix", type=int, default=None)
    ap.add_argument("--end-unix", type=int, default=None)
    ap.add_argument("--slice-seconds", type=int, default=86_400)
    ap.add_argument("--max-items", type=int, default=100)
    args = ap.parse_args(argv)

    if args.collect:
        end = args.end_unix or int(datetime.now(UTC).timestamp())
        start = args.start_unix or (end - 14 * 86_400)
        stats = asyncio.run(
            _collect(
                handle=args.handle,
                start_unix=start,
                end_unix=end,
                slice_seconds=args.slice_seconds,
                max_items=args.max_items,
                out=collect_path(args.handle),
            )
        )
        print(json.dumps({**stats, "out": str(collect_path(args.handle))}, indent=1))
        return 0
    if args.scan_wallets:
        scan_wallets(
            [PROFILE_WALLET, IMPOSTER_WALLET], out=CACHE / "named_wallet_legs.parquet"
        )
        return 0
    if args.build_panel:
        build_mint_panel(
            sorted(study_mints(donors=args.donors, seed=args.seed)),
            out_prefix=CACHE / "panel",
        )
        return 0
    if args.report:
        breadth: Path | None = None
        if args.breadth:
            # The candidate set is stable given the seed; scanning it is one more day-sharded
            # corpus pass and the shards are cached, so this is free on every run but the
            # first. The wallets are the six §5 names printed by a --report without it.
            breadth = scan_wallets(
                [
                    "6Eegkyd2qNzxSzZz3PH3jiDyqL5HFcHdcsb9zfMzWHKB",
                    "DkWzWsQT9ZThfkFfdZqzNT59dZMiJXp81oob8QBG9UcT",
                    "D7xK1ZLz8KQNWN8aU1jbzNAuT5xwqgFrCUUYodVU4G42",
                    "FBvxneTq8dY7WKxj924CseuveWzDL5tN9JuSW3S9nJkN",
                ],
                out=CACHE / "candidate_legs.parquet",
                echo=lambda _m: None,
            )
        run(draws=args.draws, seed=args.seed, breadth=breadth)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
