"""Mapping the shadow fleets, and — the actual ask — the structure BETWEEN them.

THE OPERATOR'S ASK, VERBATIM
---------------------------
"let's generalize somewhat and make sure we can map as much of clusters as possible,
including correlational flows among/between etc (not just within but without) so that we
can try and map out these. because i'm sure if we were to start mapping out *other other*
clusters of shadows we may find very interesting signals indeed, stuff that is *structure*
even if it isn't **edge** yet. finding structure is so important."

So the deliverable is a MAP, not a trade. Between-cluster relations are the product; a
clean statement that two fleets never interact is a complete answer.

WHAT THIS DOES NOT REBUILD
--------------------------
``RESULT_bundle_hypothesizer.md`` §1 settled it: **same-slot co-occurrence is not evidence
of coordination.** The universal-sniper negative control sits at 42.7% same-slot with the
known fleet's buys against the real members' 48.9-53.1% -- because everyone racing a launch
lands in the same few slots. A same-slot detector is a launch-sniping detector. Channels are
ranked by EVASION COST: timing is free to jitter, the set of coins you must trade is not.

THE SCALABLE PRIMITIVE: EVENT-FIRST, NEVER ALL-PAIRS
-----------------------------------------------------
All-pairs over 394,350 owners is 7.8e10 pairs and is infeasible. Instead index the events
and let the pairs fall out of them:

  * a ZERO-CROSSING EXIT leg (post balance 0, pre balance > 0) is the least deniable fleet
    signature there is -- the known fleet's four wallets all reach zero within 40 ms, in
    separate transactions -- and it is cheap to index: 10.8% of legs.
  * an OPENING ENTRY leg (pre balance 0, post > 0) is the same object at the other end.
  * an EVENT is a (mint, block_slot, kind) with k >= 2 distinct owners crossing together.

WEIGHTING, STATED EXPLICITLY (this is the whole method, so it is spelled out)
-----------------------------------------------------------------------------
An event with k co-crossing owners gives every unordered pair inside it

    w = 1 / (k - 1)                                   [Newman collaboration weight]

so each participating wallet injects exactly ONE unit of weight per event no matter how
crowded that event was. Two wallets zeroing alone on an obscure coin score 1.0; two wallets
inside a 200-wallet rug exit score 1/199. That IS the inverse-popularity term, applied at
the event rather than the coin, which is the finer grain of the two.

Pairs are then degree-normalised into a cosine

    S(u,v) = W(u,v) / sqrt(s_u * s_v),   s_u = number of k>=2 events u appears in

because W alone rewards promiscuity: a wallet in 10,000 events co-occurs with everything by
construction, and this is precisely the failure the curveball null was adopted for in
``operator_crime.py``. S = 1.0 iff the two wallets' event histories are identical.

CLUSTERING IS WEIGHTED INFOMAP, NOT UNION-FIND
-----------------------------------------------
``PROGRAM.md`` §4.1 is explicit and paid for: connected components put 99.6% of the FDR
network and 81% of the Bonferroni network in ONE blob. `giant_component_share` is printed
next to every clustering number here for the same reason.

THE GATE
--------
``RESULT_jackduval_workup.md`` §5.7 hands us one confirmed four-wallet fleet and one
negative control that must NOT be absorbed. A method that needs hand-tuning to rediscover a
fleet it was told about is worthless on the fleets nobody has found, so the gate runs before
anything is believed.

DECLARED GAPS -- not worked around, just stated
-----------------------------------------------
* **No fee payer and no native-SOL transfer legs exist anywhere in local data**, so
  funding-ancestry linkage (``PROGRAM.md`` signal #2) is NOT computable. Token balances only.
* The owner-bearing corpus is **ten days** (2026-08-05..2026-08-14), so cluster lifecycles
  longer than that are truncated, and DREGG / SOLVE / weave launched before the window.
* ``state/bulk_history/`` reaches 48 days back but is a single-pool swap tape with **no
  owner column** -- useless for wallet work.
* This method CANNOT separate one entity's own wallets from a copy bot that follows only
  that entity, nor either from a market maker quoting both sides. It separates
  "moves with" from "does not move with". Every label below is at confidence `inferred`.

RUNNING IT
----------
`--source panel` is the fast development substrate (~2 s a stage, coin-biased, never used
for a population claim). `--source bulk` is the ten-day corpus. Stages are ordered; each
reads the previous one's parquet out of ``.cache/clustermap/``.

    uv run --group research python -m studies.cluster_map --events   --source bulk  # ~32 min
    uv run --group research python -m studies.cluster_map --graph    --source bulk  # ~12 min
    uv run --group research python -m studies.cluster_map --gate     --source bulk  # THE GATE
    uv run --group research python -m studies.cluster_map --cluster  --source bulk
    uv run --group research python -m studies.cluster_map --channels --source bulk
    uv run --group research python -m studies.cluster_map --between  --source bulk --draws 200
    uv run --group research python -m studies.cluster_map --operator --source bulk
    uv run --group research python -m studies.cluster_map --probe 1504,6464,4899 --source bulk

Second wave (operator-deputized session, same seed discipline):

    uv run --group research python -m studies.cluster_map --resonance  --source bulk
      # wallet-grain locked-offset scan; BLIND to rungs >~2 slots apart (documented inline)
    uv run --group research python -m studies.cluster_map --resonance2 --source bulk
      # cluster-grain ladder scan; found the 110-cluster / 479-wallet decelerating schedule
    uv run --group research python -m studies.cluster_map --selection 1504,6464,... --source bulk
      # what picks a fleet's coins; day-matched, joins operator_crime coins.parquet
    uv run --group research python -m studies.cluster_map --deployer-territory --source bulk
    uv run --group research python -m studies.cluster_map --persistence --source bulk
    uv run --group research python -m studies.cluster_map --ecology --source bulk --draws 200
      # guild taxonomy (rules stated inline), guild food web, demography

REPRODUCIBILITY
---------------
Infomap is seeded, but that is NOT sufficient on its own: node ids are assigned in the order
duckdb hands back edges, `preserve_insertion_order=false` makes that order vary, and
Infomap's tie-breaking depends on node ids. Three runs of one command gave 24,180 / 24,196 /
24,199 modules before ``load_edges`` was given an ``ORDER BY u, v``. With it, the partition
hashes identically across runs and cluster ids mean the same thing from stage to stage.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Final, Sequence

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "clustermap"
STATE = ROOT / "state" / "crime"
BULK = ROOT / "state" / "bulk_pump" / "daily"
PANEL_LEGS = ROOT / ".cache" / "jackduval" / "panel-legs.parquet"

# RESULT_jackduval_workup.md 5.7 / RESULT_bundle_hypothesizer.md 4. Confirmed live: enter
# within 69 ms, all four sell to a ZERO balance within 40 ms in separate transactions, and
# each trades 99%+ of its coins in common with the others.
FLEET: Final = (
    "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh",  # the X caller, @jackduval
    "6Eegkyd2qNzxSzZz3PH3jiDyqL5HFcHdcsb9zfMzWHKB",
    "DkWzWsQT9ZThfkFfdZqzNT59dZMiJXp81oob8QBG9UcT",
    "D7xK1ZLz8KQNWN8aU1jbzNAuT5xwqgFrCUUYodVU4G42",
)
# The negative control that makes the fleet mean anything: a universal launch sniper,
# 17,908 coins in 10 days, 1.4% portfolio overlap with the fleet. Absorbing it is a FAILURE.
CONTROL: Final = "FBvxneTq8dY7WKxj924CseuveWzDL5tN9JuSW3S9nJkN"

OPERATOR_COINS: Final = {
    "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump": "nosis (2026-08-09, in-corpus launch)",
    "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump": "weave (2026-08-03, pre-corpus)",
    "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump": "SOLVE (2026-07-20, pre-corpus)",
    "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump": "DREGG (2026-06-27, pre-corpus)",
}

# An event where this many wallets cross together is a rug, a migration or a mass panic, and
# carries ~1/K_MAX of a unit of pair information anyway. Capping it bounds the pair
# explosion at C(K_MAX,2) per event instead of C(500,2). Excluded events are COUNTED and
# reported, never dropped silently.
K_MAX: Final = 50
K_MIN: Final = 2

# A pair supported by a single coin is a coincidence with a story. Edges must be carried by
# at least this many DISTINCT mints to enter the graph.
MIN_MINTS: Final = 3

# Hash buckets for the pair-aggregation combine; see the note in cmd_graph.
N_BUCKETS: Final = 32


def echo(msg: str) -> None:
    print(msg, flush=True)


def _duck(threads: int = 3, memory: str = "4GB"):
    """A deliberately SMALL duckdb.

    A full-day ``UNNEST(t.post)`` segfaulted this box once already, and other agents are
    running heavy duckdb on it right now. More, smaller passes; never raise these.
    """
    import duckdb

    con = duckdb.connect()
    tmp = CACHE / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET temp_directory='{tmp}'")
    return con


def bulk_days() -> list[Path]:
    return sorted(BULK.glob("*.parquet"))


def ev_dir(source: str) -> Path:
    d = CACHE / f"events_{source}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------------------
# STAGE 1 -- crossing legs.  Zero-crossing exits and opening entries, day-sharded.
#
# The shard is at LEG grain rather than event grain, and deliberately so: `amt` (the position
# actually closed or opened, in token base units) is what makes "A sells while B buys" a
# statement about FLOW instead of a statement about coincidence, and it is what makes a clip
# size reportable at all. Events are re-derived from legs by GROUP BY downstream, which costs
# seconds; re-deriving amounts would cost another full corpus pass.
# ---------------------------------------------------------------------------------------

# Legs -> (mint, slot, kind) events. `list(owner)` and the pre-aggregation by owner together
# guarantee one row per owner per event without a DISTINCT, so any parallel list stays
# positionally aligned with `owners`.
_EVENT_SELECT = """
  SELECT mint, block_slot, kind, min(block_time) AS block_time,
         count(*) AS k, list(owner) AS owners, list(amt) AS amts
  FROM (SELECT mint, block_slot, kind, owner,
               min(block_time) AS block_time, sum(amt) AS amt
        FROM legs GROUP BY mint, block_slot, kind, owner)
  GROUP BY mint, block_slot, kind
"""


def events_from_panel(out: Path) -> None:
    """Dev substrate: 9.87M legs over 1,183 pump mints, already unnested.

    This is a COIN-BIASED sample -- the mints are the ones a watched caller touched -- so it
    is used to develop and gate the clustering logic fast, never to make a population claim.
    It is also the HARDEST gate available: it is exactly the territory where the negative
    control's overlap with the fleet is maximal.
    """
    con = _duck()
    con.execute(
        f"""
        CREATE OR REPLACE TABLE legs AS
        SELECT mint, block_slot, block_time, owner,
               CASE WHEN post_amt = 0 AND delta < 0 THEN 'exit'
                    WHEN post_amt - delta = 0 AND delta > 0 THEN 'entry' END AS kind,
               -- the position crossed: what an exit CLOSED (its pre-balance) and what an
               -- entry OPENED (its post-balance). Token base units; see the size caveat in
               -- cmd_between 5.1.
               CASE WHEN post_amt = 0 AND delta < 0 THEN -delta ELSE post_amt END AS amt
        FROM read_parquet('{PANEL_LEGS}')
        WHERE mint LIKE '%pump'
          AND ((post_amt = 0 AND delta < 0) OR (post_amt - delta = 0 AND delta > 0))
        """
    )
    con.execute(f"COPY ({_EVENT_SELECT}) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    echo(f"events(panel): {n:,} (mint, slot, kind) events -> {out.name}")
    con.close()


def events_from_bulk_day(day: Path, out: Path) -> None:
    """One day of the real corpus.

    The ``mint LIKE '%pump'`` predicate lives INSIDE the unnest on purpose; that is the only
    form of this pass measured to survive on this box. ``err = ''`` drops failed
    transactions, whose balance deltas are not trades.
    """
    con = _duck()
    con.execute(
        f"""
        CREATE OR REPLACE TABLE legs AS
        WITH src AS (
          SELECT signature, block_slot, block_time, pre, post
          FROM read_parquet('{day}')
          WHERE err = ''
        ), post_l AS (
          SELECT s.signature, s.block_slot, s.block_time,
                 u.owner AS owner, u.mint AS mint, u.account_index AS ai,
                 CAST(u.amount AS HUGEINT) AS amt
          FROM src s, UNNEST(s.post) t(u)
          WHERE u.mint LIKE '%pump'
        ), pre_l AS (
          SELECT s.signature, u.account_index AS ai, CAST(u.amount AS HUGEINT) AS amt
          FROM src s, UNNEST(s.pre) t(u)
          WHERE u.mint LIKE '%pump'
        )
        SELECT p.block_slot, p.block_time, p.owner, p.mint,
               CASE WHEN p.amt = 0 AND COALESCE(q.amt, 0) > 0 THEN 'exit'
                    WHEN p.amt > 0 AND COALESCE(q.amt, 0) = 0 THEN 'entry' END AS kind,
               -- the position crossed: an exit closes its pre-balance, an entry opens its
               -- post-balance. Token base units.
               CAST(CASE WHEN p.amt = 0 THEN q.amt ELSE p.amt END AS DOUBLE) AS amt
        FROM post_l p LEFT JOIN pre_l q
          ON p.signature = q.signature AND p.ai = q.ai
        WHERE (p.amt = 0 AND COALESCE(q.amt, 0) > 0)
           OR (p.amt > 0 AND COALESCE(q.amt, 0) = 0)
        """
    )
    con.execute(f"COPY ({_EVENT_SELECT}) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    row = con.execute(
        f"""SELECT count(*), sum(k), count(*) FILTER (WHERE k >= 2)
            FROM read_parquet('{out}')"""
    ).fetchone()
    echo(
        f"events(bulk) {day.stem}: {row[0]:,} events, {row[1]:,} crossing legs, "
        f"{row[2]:,} with k>=2 -> {out.name}"
    )
    con.close()


def cmd_events(source: str, force: bool = False) -> None:
    d = ev_dir(source)
    if source == "panel":
        out = d / "panel.parquet"
        if out.exists() and not force:
            echo(f"events(panel): {out.name} exists, skipping")
        else:
            events_from_panel(out)
        return
    for day in bulk_days():
        out = d / f"{day.stem}.parquet"
        if out.exists() and not force:
            echo(f"events(bulk) {day.stem}: cached, skipping")
            continue
        events_from_bulk_day(day, out)


# ---------------------------------------------------------------------------------------
# STAGE 2 -- the weighted wallet graph.
# ---------------------------------------------------------------------------------------


def cmd_graph(
    source: str, kinds: Sequence[str] = ("exit", "entry"), label: str = "",
    quiet: bool = False,
) -> None:
    _e = (lambda _m: None) if quiet else echo
    d = ev_dir(source)
    files = sorted(d.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no events under {d}; run --events --source {source} first")
    glob = f"{d}/*.parquet"
    con = _duck()

    kind_pred = " OR ".join(f"kind = '{k}'" for k in kinds)
    con.execute(
        f"""
        CREATE OR REPLACE VIEW ev AS
        SELECT * FROM read_parquet('{glob}') WHERE ({kind_pred})
        """
    )

    # ---- exclusions, itemised, never silent -------------------------------------------
    tot = con.execute(
        """SELECT count(*) AS events, sum(k) AS legs,
                  count(*) FILTER (WHERE k < 2) AS singleton,
                  sum(k) FILTER (WHERE k < 2) AS singleton_legs,
                  count(*) FILTER (WHERE k > ?) AS oversize,
                  sum(k) FILTER (WHERE k > ?) AS oversize_legs,
                  count(*) FILTER (WHERE k BETWEEN 2 AND ?) AS kept,
                  sum(k) FILTER (WHERE k BETWEEN 2 AND ?) AS kept_legs
           FROM ev""",
        [K_MAX, K_MAX, K_MAX, K_MAX],
    ).fetchone()
    _e("\n=== 2.1 event census and exclusions ===")
    _e(f"  events total                     : {tot[0]:,}  ({tot[1]:,} crossing legs)")
    _e(
        f"  EXCLUDED k<{K_MIN} (nobody to pair) : {tot[2]:,}  ({tot[3]:,} legs, "
        f"{tot[3] / max(tot[1], 1):.1%} of legs)"
    )
    _e(
        f"  EXCLUDED k>{K_MAX} (rug/migration)  : {tot[4]:,}  ({tot[5] or 0:,} legs, "
        f"{(tot[5] or 0) / max(tot[1], 1):.1%} of legs)"
    )
    _e(
        f"  KEPT  {K_MIN}<=k<={K_MAX}                  : {tot[6]:,}  ({tot[7]:,} legs, "
        f"{tot[7] / max(tot[1], 1):.1%} of legs)"
    )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW keep AS
        SELECT mint, block_slot, kind, k, owners FROM ev WHERE k BETWEEN {K_MIN} AND {K_MAX}
        """
    )

    # ---- s_u : the number of kept events each wallet appears in ------------------------
    con.execute(
        """
        CREATE OR REPLACE TABLE strength AS
        SELECT o AS owner, count(*) AS s
        FROM keep, UNNEST(owners) t(o)
        GROUP BY o
        """
    )
    nw = con.execute("SELECT count(*), max(s) FROM strength").fetchone()
    _e(f"  wallets in >=1 kept event        : {nw[0]:,}   busiest: {nw[1]:,} events")

    # A LOSSLESS prefilter, and the only reason the bulk pass fits. An edge requires
    # n_mints >= MIN_MINTS distinct mints, which requires at least that many events, which
    # requires s_u >= MIN_MINTS. So a wallet below that threshold provably cannot appear in
    # ANY surviving edge and can be dropped before the pair explosion rather than after.
    # The weight still uses the event's ORIGINAL k, because k is the true crowding of that
    # event and filtering the roster must not make a crowded event look intimate.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE elig AS
        SELECT owner FROM strength WHERE s >= {MIN_MINTS}
        """
    )
    ne_ = con.execute("SELECT count(*) FROM elig").fetchone()[0]
    _e(
        f"  eligible after lossless s>={MIN_MINTS} cut  : {ne_:,} "
        f"({ne_ / max(nw[0], 1):.1%} of wallets; an edge needs {MIN_MINTS} mints "
        f"hence {MIN_MINTS} events)"
    )

    # ---- pair accumulation, event-first ------------------------------------------------
    # w = 1/(k-1) per event: every wallet injects exactly one unit of weight per event, so a
    # 200-wallet exit cannot manufacture a strong edge out of crowding.
    #
    # This stage is HASH-PARTITIONED BY `u`, and that is the third shape it has taken,
    # because the first two OOM'd on the real corpus and both failures were informative:
    #   1. one GROUP BY (u,v) carrying `count(DISTINCT mint)` -- a DISTINCT aggregate is the
    #      one thing duckdb's hash aggregate cannot spill, so it died at 3.7 GiB with half a
    #      terabyte of disk free beside it. Counting rows of a (u,v,mint) pre-aggregate
    #      gives the identical n_mints and spills.
    #   2. those two levels, still in one query -- died anyway: the (u,v,mint) hash table
    #      over 6.7M events does not fit even with spilling on.
    # Pairs are stored canonically with u < v, so every row of a given pair lands in the same
    # bucket under hash(u): each bucket aggregates to completion independently and the
    # concatenation is EXACT, not approximate. Day-sharding on the way in keeps each input
    # hash table small, bucket-sharding on the way out keeps the combine small, and both are
    # needed -- day-sharding alone still leaves one giant cross-day combine at the end.
    strength_path = CACHE / f"strength_{source}{label}.parquet"
    elig_path = CACHE / f"elig_{source}{label}.parquet"
    con.execute(f"COPY strength TO '{strength_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY elig TO '{elig_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()

    import shutil

    part_dir = CACHE / f"pairparts_{source}{label}"
    if part_dir.exists():
        shutil.rmtree(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        c = _duck()
        c.execute(
            f"CREATE OR REPLACE VIEW elig AS SELECT * FROM read_parquet('{elig_path}')"
        )
        c.execute(
            f"""
            CREATE OR REPLACE TABLE keep2 AS
            SELECT mint, block_slot, kind, k, list(o) AS owners
            FROM (SELECT e.mint, e.block_slot, e.kind, e.k, t.o
                  FROM read_parquet('{f}') e, UNNEST(e.owners) t(o)
                  JOIN elig g ON g.owner = t.o
                  WHERE e.k BETWEEN {K_MIN} AND {K_MAX} AND ({kind_pred}))
            GROUP BY mint, block_slot, kind, k
            HAVING count(*) >= 2
            """
        )
        c.execute(
            f"""
            COPY (
              SELECT a.o AS u, b.o AS v, mint,
                     hash(a.o) % {N_BUCKETS} AS bucket,
                     sum(1.0 / (k - 1)) AS w,
                     count(*) AS n_events,
                     count(*) FILTER (WHERE kind = 'exit') AS n_exit,
                     count(*) FILTER (WHERE kind = 'entry') AS n_entry
              FROM keep2, UNNEST(owners) a(o), UNNEST(owners) b(o)
              WHERE a.o < b.o
              GROUP BY a.o, b.o, mint
            ) TO '{part_dir}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (bucket),
                               OVERWRITE_OR_IGNORE, FILENAME_PATTERN '{f.stem}_{{i}}')
            """
        )
        c.close()
        _e(f"    pairs sharded: {f.stem}")

    # ---- per-bucket combine ------------------------------------------------------------
    out = CACHE / f"edges_{source}{label}.parquet"
    edge_dir = CACHE / f"edgeparts_{source}{label}"
    if edge_dir.exists():
        shutil.rmtree(edge_dir)
    edge_dir.mkdir(parents=True, exist_ok=True)
    for b in range(N_BUCKETS):
        bdir = part_dir / f"bucket={b}"
        if not bdir.exists():
            continue
        c = _duck()
        c.execute(
            f"""
            CREATE OR REPLACE TABLE pairs AS
            SELECT u, v, sum(w) AS w, count(*) AS n_mints, sum(n_events) AS n_events,
                   sum(n_exit) AS n_exit, sum(n_entry) AS n_entry
            FROM (SELECT u, v, mint, sum(w) AS w, sum(n_events) AS n_events,
                         sum(n_exit) AS n_exit, sum(n_entry) AS n_entry
                  FROM read_parquet('{bdir}/*.parquet')
                  GROUP BY u, v, mint)
            GROUP BY u, v
            HAVING count(*) >= {MIN_MINTS}
            """
        )
        c.execute(
            f"""
            COPY (
              SELECT p.u, p.v, p.w, p.n_mints, p.n_events, p.n_exit, p.n_entry,
                     su.s AS s_u, sv.s AS s_v,
                     p.w / sqrt(su.s::DOUBLE * sv.s::DOUBLE) AS cos,
                     -- companion, unweighted: the plain event-set Jaccard. Reported because
                     -- `cos` is deliberately harsh on crowded events and a reader deserves
                     -- to see the raw overlap next to the discounted one.
                     p.n_events::DOUBLE / (su.s + sv.s - p.n_events) AS jac,
                     -- the discriminator the gate turned up: the known control shares ENTRY
                     -- events with the fleet and ZERO exit events. Entry co-occurrence
                     -- carries the launch-sniping confound; exit co-occurrence does not.
                     p.n_exit::DOUBLE / p.n_events AS exit_share
              FROM pairs p
              JOIN read_parquet('{strength_path}') su ON su.owner = p.u
              JOIN read_parquet('{strength_path}') sv ON sv.owner = p.v
            ) TO '{edge_dir}/b{b}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        c.close()

    con = _duck()
    con.execute(
        f"COPY (SELECT * FROM read_parquet('{edge_dir}/*.parquet')) TO '{out}' "
        f"(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.execute(f"CREATE OR REPLACE VIEW edges AS SELECT * FROM read_parquet('{out}')")
    ne = con.execute("SELECT count(*) FROM edges").fetchone()[0]
    _e(f"  pairs with >={MIN_MINTS} shared mints      : {ne:,}   "
       f"(all-pairs over the population would be {nw[0] * (nw[0] - 1) // 2:,}, "
       f"a {nw[0] * (nw[0] - 1) // 2 / max(ne, 1):,.0f}x reduction)")
    _e(f"  edges in the graph               : {ne:,}")

    _e("\n=== 2.2 cosine distribution of surviving edges ===")
    qs = con.execute(
        """SELECT quantile_cont(cos, [0.5,0.9,0.99,0.999,0.9999]) FROM edges"""
    ).fetchone()[0]
    for lab, val in zip(("p50", "p90", "p99", "p99.9", "p99.99"), qs):
        _e(f"  {lab:>7} : {val:.4f}")
    for t in (0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9):
        c = con.execute("SELECT count(*) FROM edges WHERE cos >= ?", [t]).fetchone()[0]
        _e(f"  cos >= {t:<4} : {c:,} edges")

    _e(f"\n  wrote {out}")
    con.close()


# ---------------------------------------------------------------------------------------
# STAGE 2b -- which CHANNEL carries the coordination, exit or entry?
# ---------------------------------------------------------------------------------------


def cmd_channels(source: str) -> None:
    """Rank the two channels by how well each separates the known fleet from the control.

    This exists because the gate turned up something sharper than expected: the negative
    control shares 88-90 ENTRY events with each fleet member and **zero** EXIT events. That
    is exactly the ``RESULT_bundle_hypothesizer.md`` §1 thesis made quantitative -- entry
    co-occurrence is contaminated by launch-sniping (everyone races the same first seconds),
    while a synchronized zero-out has no such ambient explanation.
    """
    import itertools

    import duckdb

    combos = {
        "exit-only": ("exit",),
        "entry-only": ("entry",),
        "both": ("exit", "entry"),
    }
    echo("\n=== 2b. channel comparison: which co-crossing is expensive to evade? ===")
    echo("  Fleet-internal = the 6 pairs among the 4 known members.")
    echo("  Fleet-control  = the 4 pairs between a member and the universal-sniper control.")
    echo("  `separation` is median(fleet-internal cos) / median(fleet-control cos):")
    echo("  higher means the channel tells coordination apart from mere speed.")
    echo(
        f"  {'channel':>11} {'edges':>10} {'pop p99':>9} {'fleet cos':>10} "
        f"{'ctrl cos':>9} {'separation':>11} {'fleet pctile':>13}"
    )
    for name, kinds in combos.items():
        # "both" IS the main graph, so reuse it rather than spending another corpus pass.
        label = "" if name == "both" else "_" + name.replace("-", "_")
        if not (CACHE / f"edges_{source}{label}.parquet").exists():
            cmd_graph(source, kinds=kinds, label=label, quiet=True)
        con = _duck()
        path = CACHE / f"edges_{source}{label}.parquet"
        con.execute(f"CREATE OR REPLACE VIEW e AS SELECT * FROM read_parquet('{path}')")
        ne = con.execute("SELECT count(*) FROM e").fetchone()[0]
        p99 = con.execute("SELECT quantile_cont(cos, 0.99) FROM e").fetchone()[0]

        def cosof(a: str, b: str):
            u, v = sorted((a, b))
            r = con.execute("SELECT cos FROM e WHERE u=? AND v=?", [u, v]).fetchone()
            return r[0] if r else 0.0

        fin = sorted(cosof(a, b) for a, b in itertools.combinations(FLEET, 2))
        fct = sorted(cosof(a, CONTROL) for a in FLEET)
        med_in = fin[len(fin) // 2]
        med_ct = fct[len(fct) // 2]
        sep = med_in / med_ct if med_ct > 0 else float("inf")
        pct = con.execute(
            "SELECT avg(CASE WHEN cos < ? THEN 1.0 ELSE 0.0 END) FROM e", [med_in]
        ).fetchone()[0]
        con.close()
        echo(
            f"  {name:>11} {ne:>10,} {p99:>9.4f} {med_in:>10.4f} {med_ct:>9.4f} "
            f"{(f'{sep:.1f}x' if sep != float('inf') else 'inf'):>11} {pct:>12.4%}"
        )
    echo(
        "\n  An `inf` separation means the control shares ZERO events with the fleet on that\n"
        "  channel -- i.e. the channel is not merely better, it is CLEAN on this case."
    )


# ---------------------------------------------------------------------------------------
# STAGE 3 -- clustering.  Weighted Infomap, with the union-find pathology printed beside it.
# ---------------------------------------------------------------------------------------


def load_edges(source: str, thresh: float, min_mints: int = MIN_MINTS):
    """Edge list above a cosine threshold, as (u, v, cos) with integer node ids."""
    con = _duck()
    # ORDER BY is load-bearing, not tidiness. `preserve_insertion_order=false` lets duckdb
    # return rows in whatever order the scan finishes in, node ids are assigned in first-seen
    # order, and Infomap's tie-breaking depends on node ids -- so an unordered read made the
    # partition differ run to run (24,180 / 24,196 / 24,199 modules on three runs of the same
    # command) and cluster ids meant nothing across stages. Sorted input makes both the
    # partition and the ids reproducible from the seed.
    rows = con.execute(
        f"""SELECT u, v, cos, n_mints, n_exit, n_entry
            FROM read_parquet('{CACHE}/edges_{source}.parquet')
            WHERE cos >= ? AND n_mints >= ?
            ORDER BY u, v""",
        [thresh, min_mints],
    ).fetchall()
    con.close()
    ids: dict[str, int] = {}
    for u, v, *_ in rows:
        ids.setdefault(u, len(ids))
        ids.setdefault(v, len(ids))
    return rows, ids


def _union_find_components(rows, ids) -> dict[int, int]:
    parent = list(range(len(ids)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u, v, *_ in rows:
        a, b = find(ids[u]), find(ids[v])
        if a != b:
            parent[a] = b
    return {i: find(i) for i in range(len(ids))}


def _infomap(rows, ids, seed: int = 20260815, trials: int = 10) -> dict[int, int]:
    from infomap import Infomap

    im = Infomap(f"--two-level --silent --seed {seed} --num-trials {trials}")
    for u, v, cos, *_ in rows:
        im.add_link(ids[u], ids[v], float(cos))
    im.run()
    return dict(im.get_modules())


def cluster_at(source: str, thresh: float, seed: int = 20260815) -> dict[str, Any]:
    rows, ids = load_edges(source, thresh)
    if not rows:
        return {"thresh": thresh, "edges": 0, "nodes": 0}
    inv = {i: w for w, i in ids.items()}
    mods = _infomap(rows, ids, seed=seed)
    comps = _union_find_components(rows, ids)

    msize: dict[int, int] = defaultdict(int)
    for m in mods.values():
        msize[m] += 1
    csize: dict[int, int] = defaultdict(int)
    for c in comps.values():
        csize[c] += 1

    n = len(ids)
    return {
        "thresh": thresh,
        "edges": len(rows),
        "nodes": n,
        "n_modules": len(msize),
        "biggest_module": max(msize.values()),
        "giant_module_share": max(msize.values()) / n,
        "n_components": len(csize),
        "biggest_component": max(csize.values()),
        # PROGRAM.md 4.1: union-find on this kind of graph collapses to one blob and
        # reports a triumph. This number is printed so that never happens silently.
        "giant_component_share": max(csize.values()) / n,
        "modules": {inv[i]: m for i, m in mods.items()},
        "components": {inv[i]: c for i, c in comps.items()},
        "msize": dict(msize),
    }


def cmd_cluster(source: str, seed: int = 20260815) -> None:
    echo("\n=== 3.1 threshold scan: Infomap modules vs union-find components ===")
    echo("  (union-find's giant-component share is the pathology PROGRAM.md 4.1 warns of)")
    echo(
        f"  {'cos>=':>6} {'nodes':>8} {'edges':>8} {'modules':>8} {'maxmod':>7} "
        f"{'mod share':>10} {'comps':>7} {'maxcomp':>8} {'UF share':>9}"
    )
    best = None
    for t in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
        r = cluster_at(source, t, seed=seed)
        if not r.get("edges"):
            continue
        echo(
            f"  {t:>6.2f} {r['nodes']:>8,} {r['edges']:>8,} {r['n_modules']:>8,} "
            f"{r['biggest_module']:>7,} {r['giant_module_share']:>9.1%} "
            f"{r['n_components']:>7,} {r['biggest_component']:>8,} "
            f"{r['giant_component_share']:>8.1%}"
        )
        if t == 0.10:
            best = r
    return best


# ---------------------------------------------------------------------------------------
# STAGE 4 -- THE GATE.  Rediscover the known fleet; refuse the known control.
# ---------------------------------------------------------------------------------------


def cmd_gate(source: str, seed: int = 20260815) -> bool:
    """The method must find the four, as one module, without the control.

    A method that needs hand-tuning to rediscover a fleet it was TOLD about is worthless on
    the fleets nobody has found, so this runs at every threshold rather than at a chosen one.
    """
    echo("\n=== 4.1 THE GATE ===")
    echo("  PASS requires, at one threshold and with no per-case tuning:")
    echo("    (a) all four known fleet wallets in ONE Infomap module, and")
    echo("    (b) the universal-sniper control NOT in that module.")
    echo(
        f"  {'cos>=':>6} {'fleet found':>12} {'same module':>12} {'module size':>12} "
        f"{'control in?':>12} {'verdict':>8}"
    )
    passed_any = False
    for t in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
        r = cluster_at(source, t, seed=seed)
        if not r.get("edges"):
            continue
        mods = r["modules"]
        present = [w for w in FLEET if w in mods]
        mids = {mods[w] for w in present}
        one = len(present) == len(FLEET) and len(mids) == 1
        mid = next(iter(mids)) if len(mids) == 1 else None
        size = r["msize"].get(mid, 0) if mid is not None else 0
        ctrl_in = CONTROL in mods and mid is not None and mods[CONTROL] == mid
        ok = one and not ctrl_in
        passed_any = passed_any or ok
        echo(
            f"  {t:>6.2f} {len(present):>8}/{len(FLEET)} {str(one):>12} {size:>12,} "
            f"{str(ctrl_in):>12} {'PASS' if ok else 'fail':>8}"
        )
    echo(f"\n  GATE: {'PASS' if passed_any else 'FAIL'}")
    return passed_any


# ---------------------------------------------------------------------------------------
# STAGE 5 -- what the operator actually asked for: the structure BETWEEN clusters.
# ---------------------------------------------------------------------------------------


def build_cluster_table(source: str, thresh: float, min_size: int, seed: int):
    """Freeze an Infomap partition to disk so duckdb can join against it."""
    r = cluster_at(source, thresh, seed=seed)
    if not r.get("edges"):
        raise SystemExit(f"no edges at cos>={thresh}")
    sizes = r["msize"]
    keep = {m for m, s in sizes.items() if s >= min_size}
    rows = [(w, m) for w, m in r["modules"].items() if m in keep]
    import pandas as pd

    df = pd.DataFrame(rows, columns=["owner", "cid"])
    out = CACHE / f"clusters_{source}.parquet"
    df.to_parquet(out, index=False)
    echo(
        f"  partition: cos>={thresh}, {len(sizes):,} modules, "
        f"{len(keep):,} with >={min_size} wallets, {len(df):,} wallets assigned"
    )
    return out, r


def _member_events(con, source: str, cl_path: Path) -> None:
    """(cid, mint, slot, time, kind) for every cluster member's crossing events."""
    d = ev_dir(source)
    con.execute(f"CREATE OR REPLACE VIEW cl AS SELECT * FROM read_parquet('{cl_path}')")
    # Two `unnest`s in one SELECT list zip positionally in duckdb, which is why the event
    # writer pre-aggregates by owner instead of using list(DISTINCT ...): `owners[i]` and
    # `amts[i]` must be the same wallet.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE me AS
        WITH x AS (
          SELECT mint, block_slot AS slot, block_time AS t, kind,
                 unnest(owners) AS owner, unnest(amts) AS amt
          FROM read_parquet('{d}/*.parquet')
        )
        SELECT cl.cid, x.mint, x.slot, x.t, x.kind, x.owner, x.amt
        FROM x JOIN cl ON cl.owner = x.owner
        """
    )
    # A coin's first observed crossing is the corpus-visible birth proxy. For coins born
    # before 2026-08-05 this is a LEFT-CENSORED number and latency off it is meaningless;
    # `born_in_window` marks the ones where it is not.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE mint_t0 AS
        SELECT mint, min(block_time) AS t0, min(block_slot) AS slot0,
               min(block_time) > (SELECT min(block_time) + 3600 FROM read_parquet('{d}/*.parquet'))
                 AS born_in_window
        FROM read_parquet('{d}/*.parquet')
        GROUP BY mint
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE cm AS
        SELECT me.cid, me.mint,
               min(me.t) FILTER (WHERE kind='entry')    AS first_entry_t,
               min(me.slot) FILTER (WHERE kind='entry') AS first_entry_slot,
               max(me.t) FILTER (WHERE kind='exit')     AS last_exit_t,
               count(*) FILTER (WHERE kind='entry')     AS n_entry,
               count(*) FILTER (WHERE kind='exit')      AS n_exit,
               count(DISTINCT me.owner)                 AS n_members,
               sum(me.amt) FILTER (WHERE kind='entry')  AS bought,
               sum(me.amt) FILTER (WHERE kind='exit')   AS sold,
               any_value(m0.t0) AS t0, any_value(m0.born_in_window) AS born_in_window
        FROM me JOIN mint_t0 m0 ON m0.mint = me.mint
        GROUP BY me.cid, me.mint
        """
    )


def cmd_between(
    source: str,
    thresh: float = 0.10,
    min_size: int = 3,
    seed: int = 20260815,
    n_null: int = 200,
    top: int = 25,
) -> None:
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    echo("\n=== 5.0 partition ===")
    cl_path, part = build_cluster_table(source, thresh, min_size, seed)
    echo(
        f"  union-find giant component at the same threshold: "
        f"{part['giant_component_share']:.1%} "
        f"(Infomap's largest module: {part['giant_module_share']:.1%})"
    )
    con = _duck()
    _member_events(con, source, cl_path)

    # ---- 5.1 cluster profiles ----------------------------------------------------------
    echo("\n=== 5.1 cluster profiles (size / reach / lifecycle) ===")
    prof = con.execute(
        """
        WITH sz AS (SELECT cid, count(*) AS n_wallets FROM cl GROUP BY cid),
             rt AS (
               SELECT cid, mint, first_entry_t, last_exit_t,
                      last_exit_t - first_entry_t AS hold
               FROM cm WHERE first_entry_t IS NOT NULL AND last_exit_t IS NOT NULL
                         AND last_exit_t >= first_entry_t
             )
        SELECT c.cid, sz.n_wallets,
               count(DISTINCT c.mint) AS coins,
               sum(c.n_entry) AS entries, sum(c.n_exit) AS exits,
               median(rt.hold) AS median_hold_s,
               quantile_cont(rt.hold, 0.9) AS p90_hold_s,
               median(c.first_entry_t - c.t0) FILTER (WHERE c.born_in_window)
                 AS median_latency_s,
               any_value(clip.med_clip) AS med_clip
        FROM cm c JOIN sz ON sz.cid = c.cid
             LEFT JOIN rt ON rt.cid = c.cid AND rt.mint = c.mint
             LEFT JOIN (SELECT cid, median(amt) AS med_clip FROM me
                        WHERE kind = 'entry' AND amt > 0 GROUP BY cid) clip
               ON clip.cid = c.cid
        GROUP BY c.cid, sz.n_wallets
        ORDER BY coins DESC
        """
    ).fetchdf()
    prof["coins_per_day"] = prof["coins"] / 10.0
    echo(f"  clusters profiled: {len(prof):,}")
    echo(f"  wallets in clusters: {int(prof['n_wallets'].sum()):,}")
    echo("\n  cluster size distribution:")
    vc = prof["n_wallets"].value_counts().sort_index()
    for k, v in vc.items():
        if k <= 10 or v > 1:
            echo(f"    {k:>4} wallets : {v:>5,} clusters")
    echo(f"    largest cluster: {int(prof['n_wallets'].max()):,} wallets")
    echo(f"\n  top {top} clusters by coins touched:")
    echo("  `clip %sup` is the median OPENING position as a share of a pump.fun mint's fixed")
    echo("  1e9-token supply (1e15 base units at 6 decimals). It is NOT SOL and cannot be:")
    echo("  the corpus carries no native-SOL leg to convert with (see DECLARED GAPS).")
    echo(
        f"    {'cid':>7} {'wal':>4} {'coins':>7} {'coins/d':>8} {'entries':>8} "
        f"{'exits':>8} {'med hold':>9} {'p90 hold':>9} {'med lat':>8} {'clip %sup':>10}"
    )
    for _, r in prof.head(top).iterrows():
        clip = (
            f"{100 * r.med_clip / 1e15:.3f}%"
            if r.med_clip == r.med_clip and r.med_clip
            else "-"
        )
        echo(
            f"    {int(r.cid):>7} {int(r.n_wallets):>4} {int(r.coins):>7,} "
            f"{r.coins_per_day:>8.1f} {int(r.entries):>8,} {int(r.exits):>8,} "
            f"{_fmt_s(r.median_hold_s):>9} {_fmt_s(r.p90_hold_s):>9} "
            f"{_fmt_s(r.median_latency_s):>8} {clip:>10}"
        )
    prof.to_parquet(CACHE / f"profiles_{source}.parquet", index=False)

    big = prof.nlargest(top, "coins")["cid"].tolist()

    # ---- 5.2 territory: coin-set overlap against a degree-preserving null --------------
    echo("\n=== 5.2 TERRITORY: do clusters share coins, or avoid them? ===")
    echo("  Null: curveball (Strona et al.) on the WALLET x COIN incidence, holding every")
    echo("  wallet's coin count and every coin's wallet count fixed, cluster labels frozen.")
    echo("  This is operator_crime.py:_curveball, reused. A naive null was wrong here four")
    echo("  times already (RESULT_flow_signals, RESULT_copytrading 73x->0.98x,")
    echo("  RESULT_caller_wallets 2.1 20x->1.20x, RESULT_cluster_callers 5).")
    terr = _territory(con, big, rng, n_null=n_null, top=top)

    # ---- 5.3 lead-lag -----------------------------------------------------------------
    echo("\n=== 5.3 LEAD-LAG: does A enter before B, and by how much? ===")
    _lead_lag(con, big, top=top)

    # ---- 5.4 predation ----------------------------------------------------------------
    echo("\n=== 5.4 PREDATION: does A's EXIT land where B's ENTRY does? ===")
    _predation(con, big, rng, n_null=n_null, top=top)

    # ---- 5.5 co-firing ----------------------------------------------------------------
    echo("\n=== 5.5 CO-FIRING: several clusters onto one coin inside a minute ===")
    _cofiring(con)

    con.close()


def _fmt_s(x) -> str:
    import math as _m

    if x is None or (isinstance(x, float) and _m.isnan(x)):
        return "-"
    x = float(x)
    if x < 90:
        return f"{x:.0f}s"
    if x < 5400:
        return f"{x / 60:.1f}m"
    return f"{x / 3600:.1f}h"


def _territory(con, big: list[int], rng, n_null: int, top: int):
    import numpy as np

    sys.path.insert(0, str(ROOT))
    from studies.operator_crime import _curveball  # the null this repo already paid for

    wc = con.execute(
        """SELECT me.owner, me.mint, any_value(cl.cid) AS cid
           FROM me JOIN cl ON cl.owner = me.owner
           WHERE cl.cid IN ({}) GROUP BY me.owner, me.mint""".format(
            ",".join(str(c) for c in big)
        )
    ).fetchdf()
    if wc.empty:
        echo("  no incidence to test")
        return None
    mints = {m: i for i, m in enumerate(wc["mint"].unique())}
    owners = sorted(wc["owner"].unique())
    oidx = {o: i for i, o in enumerate(owners)}
    rows: list[set[int]] = [set() for _ in owners]
    for o, m in zip(wc["owner"], wc["mint"]):
        rows[oidx[o]].add(mints[m])
    cid_of = dict(zip(wc["owner"], wc["cid"]))
    labels = np.array([cid_of[o] for o in owners])
    echo(
        f"  incidence: {len(owners):,} wallets x {len(mints):,} coins, "
        f"{sum(len(r) for r in rows):,} cells, over the top {len(big)} clusters"
    )

    def overlaps(rs: list[set[int]]) -> dict[tuple[int, int], float]:
        cs: dict[int, set[int]] = {}
        for i, lab in enumerate(labels):
            cs.setdefault(int(lab), set()).update(rs[i])
        out = {}
        ks = sorted(cs)
        for i, a in enumerate(ks):
            for b in ks[i + 1 :]:
                u = len(cs[a] | cs[b])
                out[(a, b)] = len(cs[a] & cs[b]) / u if u else 0.0
        return out

    obs = overlaps(rows)
    # 20 curveball trades per row per draw is the mixing budget; each draw restarts from the
    # observed matrix so draws are independent.
    null: dict[tuple[int, int], list[float]] = {k: [] for k in obs}
    for _ in range(n_null):
        rs = _curveball(rows, 20 * len(rows), rng)
        for k, v in overlaps(rs).items():
            null[k].append(v)
    recs = []
    for k, o in obs.items():
        arr = np.array(null[k])
        mu, sd = arr.mean(), arr.std()
        ge = int((arr >= o).sum())
        recs.append(
            (k[0], k[1], o, mu, (o - mu) / sd if sd > 0 else float("nan"),
             (ge + 1) / (n_null + 1), (min(ge, n_null - ge) + 1) / (n_null + 1))
        )
    recs.sort(key=lambda r: -abs(r[4]) if r[4] == r[4] else 0)
    echo(f"  trials: {len(obs):,} cluster pairs x {n_null} curveball draws")
    echo(
        f"  {'A':>7} {'B':>7} {'obs J':>8} {'null J':>8} {'z':>8} "
        f"{'p(>=)':>8}  interpretation"
    )
    n_over = n_under = 0
    for a, b, o, mu, z, p, _pt in recs[:top]:
        if z == z and z > 2:
            interp = "PILE-ON (share coins more than chance)"
        elif z == z and z < -2:
            interp = "TERRITORY (systematic avoidance)"
        else:
            interp = "indistinguishable from the null"
        echo(f"  {a:>7} {b:>7} {o:>8.4f} {mu:>8.4f} {z:>8.2f} {p:>8.3f}  {interp}")
    for *_, z, _p, _pt in recs:
        if z == z and z > 2:
            n_over += 1
        elif z == z and z < -2:
            n_under += 1
    echo(
        f"\n  across all {len(recs):,} pairs: {n_over:,} pile-on (z>2), "
        f"{n_under:,} territory (z<-2), "
        f"{len(recs) - n_over - n_under:,} null."
    )
    return recs


def _lead_lag(con, big: list[int], top: int, min_shared: int = 20):
    ins = ",".join(str(c) for c in big)
    df = con.execute(
        f"""
        WITH e AS (SELECT cid, mint, first_entry_t FROM cm
                   WHERE cid IN ({ins}) AND first_entry_t IS NOT NULL)
        SELECT a.cid AS A, b.cid AS B, count(*) AS shared,
               median(b.first_entry_t - a.first_entry_t) AS med_off,
               quantile_cont(b.first_entry_t - a.first_entry_t, 0.25) AS q25,
               quantile_cont(b.first_entry_t - a.first_entry_t, 0.75) AS q75,
               avg(CASE WHEN a.first_entry_t < b.first_entry_t THEN 1.0
                        WHEN a.first_entry_t > b.first_entry_t THEN 0.0 END) AS a_leads,
               avg(CASE WHEN a.first_entry_t = b.first_entry_t THEN 1.0 ELSE 0.0 END) AS ties
        FROM e a JOIN e b ON a.mint = b.mint AND a.cid < b.cid
        GROUP BY a.cid, b.cid
        HAVING count(*) >= {min_shared}
        ORDER BY shared DESC
        """
    ).fetchdf()
    if df.empty:
        echo(f"  no cluster pair shares >= {min_shared} coins. No lead-lag to report.")
        return df
    echo(f"  pairs sharing >= {min_shared} coins: {len(df):,}")
    echo("  `A leads` is the share of shared coins where A's first entry strictly precedes")
    echo("  B's; 0.50 with a wide IQR is NO lead-lag, and is the expected result.")
    echo(
        f"  {'A':>7} {'B':>7} {'coins':>7} {'med off':>9} {'IQR':>19} "
        f"{'A leads':>8} {'ties':>7}"
    )
    for _, r in df.head(top).iterrows():
        echo(
            f"  {int(r.A):>7} {int(r.B):>7} {int(r.shared):>7,} "
            f"{_fmt_signed(r.med_off):>9} "
            f"{('[' + _fmt_signed(r.q25) + ', ' + _fmt_signed(r.q75) + ']'):>19} "
            f"{r.a_leads:>8.3f} {r.ties:>7.3f}"
        )
    strong = df[(df["a_leads"] > 0.75) | (df["a_leads"] < 0.25)]
    echo(
        f"\n  pairs with a decisive direction (A leads >75% or <25% of shared coins): "
        f"{len(strong):,} of {len(df):,}"
    )
    # A pair whose median offset is ~0 with a TIGHT interquartile range is not a lead-lag
    # relation at all -- it is one operator that this threshold happened to cut in two, or
    # two operators on a shared trigger. Naming them is the honest reading of a 0.50 `A
    # leads` with no spread, and it is the "swarm of swarms" case at pair grain.
    lock = df[
        (df["med_off"].abs() <= 2) & ((df["q75"] - df["q25"]) <= 10)
    ]
    echo(
        f"  pairs LOCKED rather than leading (|median offset| <= 2 s AND IQR width <= 10 s): "
        f"{len(lock):,} of {len(df):,}"
    )
    if len(lock):
        echo("    these are candidate SPLIT FLEETS -- one entity cut in two by the threshold,")
        echo("    or two entities on one trigger. This method cannot tell those apart.")
        for _, r in lock.head(10).iterrows():
            echo(
                f"      {int(r.A):>7} <-> {int(r.B):<7} {int(r.shared):>6,} coins, "
                f"median {_fmt_signed(r.med_off)}, IQR width "
                f"{r.q75 - r.q25:.0f}s, ties {r.ties:.1%}"
            )
    return df


def _fmt_signed(x) -> str:
    import math as _m

    if x is None or (isinstance(x, float) and _m.isnan(x)):
        return "-"
    s = "+" if x >= 0 else "-"
    return s + _fmt_s(abs(float(x)))


def _predation(con, big: list[int], rng, n_null: int, top: int, window: int = 2):
    """A goes flat in the same slot (+/- `window`) that B opens, on the same coin.

    One fleet using another as exit liquidity is the most interesting possible finding, so
    it gets the most careful null -- and the OBVIOUS null here is wrong, which was measured
    rather than reasoned. Drawing B's entry slots uniformly from the coin's active-slot
    support returned null means of 21-280 against observed counts of 0-136, i.e. a hugely
    NEGATIVE z on every pair. That is an artifact, not avoidance: entries are front-loaded
    into a coin's first seconds and exits are spread over its life, so a uniform draw pushes
    B's entries later, straight into where A's exits already are, and manufactures
    coincidences the real data cannot have.

    The null used instead is a MATCHED-MOMENT SUBSTITUTION, the same shape that worked in
    ``RESULT_caller_wallets`` where a hypergeometric null returned 1,758 false positives and
    the time-matched one returned 1: B's entry slots are resampled from the pool of entry
    slots that ANY profiled cluster actually used on THAT SAME COIN. The front-loading is
    preserved because the pool is made of real entries; what is destroyed is only whether it
    was B specifically. The question becomes the right one -- does B enter where A exits more
    than a generic cluster entering that same coin would.
    """
    import numpy as np

    ins = ",".join(str(c) for c in big)
    ev = con.execute(
        f"""
        SELECT me.cid, me.mint, me.slot, me.kind, me.amt
        FROM me WHERE me.cid IN ({ins})
        """
    ).fetchdf()
    if ev.empty:
        echo("  no member events")
        return
    mint_ids = {m: i for i, m in enumerate(ev["mint"].unique())}
    ev["mi"] = ev["mint"].map(mint_ids)
    ex = ev[ev["kind"] == "exit"]
    en = ev[ev["kind"] == "entry"]
    # The matched-moment pool: every entry slot any profiled cluster actually used on this
    # coin. Sampling from it keeps the front-loading that a uniform support draw destroys.
    entry_pool: dict[int, np.ndarray] = {
        mi: np.asarray(g) for mi, g in en.groupby("mi")["slot"]
    }
    exl = {
        (c, m): (np.asarray(g["slot"]), np.asarray(g["amt"], dtype=float))
        for (c, m), g in ex.groupby(["cid", "mi"])[["slot", "amt"]]
    }
    enl = {(c, m): np.asarray(g) for (c, m), g in en.groupby(["cid", "mi"])["slot"]}
    # Denominator for the volume statistic: everything A ever closed on a coin B also
    # opened. Reporting the ABSORBED SHARE rather than a raw token count keeps clusters of
    # wildly different size comparable, and keeps one whale coin from carrying the number.
    def exposure_on(A: int, shared_l) -> float:
        return sum(float(exl[(A, m)][1].sum()) for m in shared_l) or 1.0

    # Iterating every coin A ever exited, for every null draw, is quadratic waste: only the
    # coins B also entered can ever produce a hit. The shared list is computed once per pair
    # and both the statistic and the resampling run over it alone.
    ex_mints: dict[int, set] = defaultdict(set)
    for c, m in exl:
        ex_mints[c].add(m)
    en_mints: dict[int, set] = defaultdict(set)
    for c, m in enl:
        en_mints[c].add(m)

    def hits(A: int, shared: list, end):
        """(count, volume) of A's exits with a B entry inside the slot window."""
        n = 0
        vol = 0.0
        for m in shared:
            sl, am = exl[(A, m)]
            bb = end.get(m)
            if bb is None or len(bb) == 0:
                continue
            hit = (np.abs(sl[:, None] - bb[None, :]) <= window).any(axis=1)
            n += int(hit.sum())
            vol += float(am[hit].sum())
        return n, vol

    pairs = []
    for A in big:
        for B in big:
            if A == B:
                continue
            sh = ex_mints[A] & en_mints[B]
            if len(sh) >= 10:
                pairs.append((A, B, sorted(sh)))
    pairs.sort(key=lambda p: -len(p[2]))
    pairs = pairs[: top * 2]
    if not pairs:
        echo("  no ordered cluster pair shares >= 10 coins with A-exit and B-entry. Null.")
        return
    echo(f"  trials: {len(pairs):,} ordered cluster pairs x {n_null} within-coin slot draws")
    echo(f"  window: |slot(A exit) - slot(B entry)| <= {window}")
    echo("  `absorbed` = share of A's total closed position (by token volume) that goes")
    echo("  flat inside the window of a B opening. That is the FLOW statement; `obs` counts")
    echo("  the same coincidences unweighted.")
    echo(
        f"  {'A(sell)':>8} {'B(buy)':>8} {'coins':>6} {'obs':>7} {'null mu':>8} "
        f"{'z(n)':>7} {'absorbed':>9} {'null':>8} {'z(vol)':>7} {'p':>6}  verdict"
    )
    out = []
    for A, B, shared_l in pairs:
        shared = len(shared_l)
        obs_n, obs_v = hits(A, shared_l, {m: enl[(B, m)] for m in shared_l})
        nn, nv = [], []
        for _ in range(n_null):
            perm = {}
            for m in shared_l:
                sl = enl[(B, m)]
                pool = entry_pool.get(m)
                perm[m] = (
                    sl if pool is None or len(pool) == 0
                    else rng.choice(pool, size=len(sl), replace=True)
                )
            a, b = hits(A, shared_l, perm)
            nn.append(a)
            nv.append(b)
        an = np.array(nn, dtype=float)
        av = np.array(nv, dtype=float)
        expo = exposure_on(A, shared_l)
        zn = (obs_n - an.mean()) / an.std() if an.std() > 0 else float("nan")
        zv = (obs_v - av.mean()) / av.std() if av.std() > 0 else float("nan")
        p = (int((av >= obs_v).sum()) + 1) / (n_null + 1)
        out.append(
            (A, B, shared, obs_n, an.mean(), zn, obs_v / expo, av.mean() / expo, zv, p)
        )
    out.sort(key=lambda r: -(r[8] if r[8] == r[8] else -9e9))
    for A, B, shared, on, mn, zn, ov, mv, zv, p in out[:top]:
        v = (
            "EXIT-INTO-ENTRY above chance"
            if zv == zv and zv > 3 and p < 0.05
            else "no predation signal"
        )
        echo(
            f"  {A:>8} {B:>8} {shared:>6} {on:>7,} {mn:>8.1f} {zn:>7.2f} "
            f"{ov:>8.2%} {mv:>7.2%} {zv:>7.2f} {p:>6.3f}  {v}"
        )
    sig = [r for r in out if r[8] == r[8] and r[8] > 3 and r[9] < 0.05]
    echo(f"\n  ordered pairs above the null (z_vol>3, p<0.05): {len(sig):,} of {len(out):,}")
    return out


def _cofiring(con, window: int = 60):
    df = con.execute(
        f"""
        WITH fe AS (SELECT cid, mint, first_entry_t FROM cm WHERE first_entry_t IS NOT NULL),
             w AS (
               SELECT mint, count(DISTINCT cid) AS n_cl,
                      max(first_entry_t) - min(first_entry_t) AS spread
               FROM fe GROUP BY mint
             )
        SELECT count(*) AS coins,
               count(*) FILTER (WHERE n_cl >= 2) AS multi,
               count(*) FILTER (WHERE n_cl >= 2 AND spread <= {window}) AS cofire,
               count(*) FILTER (WHERE n_cl >= 3 AND spread <= {window}) AS cofire3,
               max(n_cl) AS max_cl
        FROM w
        """
    ).fetchdf().iloc[0]
    echo(f"  coins touched by >=1 profiled cluster : {int(df.coins):,}")
    echo(f"  touched by >=2 clusters               : {int(df.multi):,} "
         f"({df.multi / max(df.coins, 1):.1%})")
    echo(f"  >=2 clusters entering within {window}s     : {int(df.cofire):,} "
         f"({df.cofire / max(df.coins, 1):.1%} of touched coins)")
    echo(f"  >=3 clusters entering within {window}s     : {int(df.cofire3):,}")
    echo(f"  most clusters on any one coin         : {int(df.max_cl):,}")


# ---------------------------------------------------------------------------------------
# STAGE 6 -- where the operator's own four coins sit in the map.
# ---------------------------------------------------------------------------------------


def cmd_operator(source: str, thresh: float = 0.10, min_size: int = 3,
                 seed: int = 20260815) -> None:
    echo("\n=== 6. the operator's coins in the map ===")
    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    _member_events(con, source, cl_path)
    d = ev_dir(source)
    for mint, label in OPERATOR_COINS.items():
        echo(f"\n  --- {label} ---\n      {mint}")
        tot = con.execute(
            f"""SELECT count(*) AS events, sum(k) AS legs, min(block_time) AS t0,
                       max(block_time) AS t1
                FROM read_parquet('{d}/*.parquet') WHERE mint = ?""",
            [mint],
        ).fetchone()
        if not tot[0]:
            echo("      NOT PRESENT in the crossing-event corpus (no entries or exits).")
            continue
        import datetime as _dt

        echo(
            f"      crossing events in corpus: {tot[0]:,} ({int(tot[1]):,} legs), "
            f"{_dt.datetime.fromtimestamp(tot[2], _dt.UTC):%Y-%m-%d %H:%M} -> "
            f"{_dt.datetime.fromtimestamp(tot[3], _dt.UTC):%Y-%m-%d %H:%M} UTC"
        )
        rows = con.execute(
            """SELECT cid, n_members, n_entry, n_exit, first_entry_t, last_exit_t,
                      first_entry_t - t0 AS latency
               FROM cm WHERE mint = ? ORDER BY first_entry_t NULLS LAST""",
            [mint],
        ).fetchdf()
        if rows.empty:
            echo("      NO profiled cluster touched this coin.")
            continue
        import pandas as pd

        echo(f"      clusters that touched it: {len(rows):,}")
        never_exited = int((rows["n_exit"].fillna(0) == 0).sum())
        echo(
            f"      of those, {never_exited:,} never went flat on it inside the corpus "
            f"({never_exited / len(rows):.1%})"
        )
        echo("      earliest 20 by first entry:")
        echo(
            f"      {'cid':>7} {'wal':>4} {'entries':>8} {'exits':>7} "
            f"{'latency vs t0':>14} {'held':>9}"
        )

        def _n(x, d=0):
            return d if pd.isna(x) else int(x)

        for _, r in rows.head(20).iterrows():
            held = (
                float("nan")
                if pd.isna(r.last_exit_t) or pd.isna(r.first_entry_t)
                else r.last_exit_t - r.first_entry_t
            )
            echo(
                f"      {_n(r.cid):>7} {_n(r.n_members):>4} {_n(r.n_entry):>8} "
                f"{_n(r.n_exit):>7} "
                f"{(_fmt_signed(None) if pd.isna(r.latency) else _fmt_signed(r.latency)):>14} "
                f"{_fmt_s(held):>9}"
            )
    con.close()


# ---------------------------------------------------------------------------------------
# STAGE 7 -- probe named clusters, and the one test that decides what an "entry" IS.
# ---------------------------------------------------------------------------------------


def cmd_probe(source: str, cids: list[int], thresh: float = 0.10,
              min_size: int = 3, seed: int = 20260815) -> None:
    """Characterise specific clusters, and run the AIRDROP TEST on them.

    An `entry` here is `pre balance 0 -> post balance > 0`, and a token-balance corpus
    CANNOT SEE WHETHER THAT WAS A PURCHASE OR AN INCOMING TRANSFER. That ambiguity is not
    cosmetic: a dust spammer airdropping a token to a list of wallets in timed batches would
    produce co-crossing wallets, a fixed inter-batch offset, and a near-zero exit rate --
    i.e. it would counterfeit a disciplined accumulation fleet exactly.

    The test that separates them is AMOUNT CONCENTRATION. A buy against a bonding curve
    lands at whatever price the curve is at, so amounts are near-all-distinct. A dust
    airdrop sends the same number of base units to everybody, so a handful of values cover
    the whole history. `top1 share` and `distinct/entries` are the discriminator.
    """
    import pandas as pd

    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    cl = pd.read_parquet(cl_path)
    members = cl[cl["cid"].isin(cids)]
    if members.empty:
        echo("  none of those cluster ids exist in this partition")
        return
    lst = ",".join("'" + w + "'" for w in members["owner"])
    d = ev_dir(source)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE probe AS
        WITH x AS (
          SELECT mint, block_slot AS slot, block_time AS t, kind,
                 unnest(owners) AS owner, unnest(amts) AS amt
          FROM read_parquet('{d}/*.parquet')
        )
        SELECT * FROM x WHERE owner IN ({lst})
        """
    )
    con.execute(
        f"CREATE OR REPLACE VIEW cl AS SELECT * FROM read_parquet('{cl_path}')"
    )
    echo("\n=== 7.1 the AIRDROP TEST ===")
    echo("  An `entry` is pre=0 -> post>0. That is a BUY *or* an incoming transfer, and this")
    echo("  corpus cannot tell them apart -- no instruction data, no SOL leg. A bonding-curve")
    echo("  buy lands at whatever price the curve is at, so amounts are near-all-distinct; a")
    echo("  dust airdrop sends identical base units to everyone. So:")
    echo(
        f"  {'cid':>7} {'wal':>4} {'entries':>9} {'exits':>8} {'distinct amt':>13} "
        f"{'distinct/ent':>13} {'top1 share':>11} {'med amt %sup':>13}"
    )
    df = con.execute(
        """
        SELECT c.cid,
               count(DISTINCT p.owner) AS wal,
               count(*) FILTER (WHERE p.kind='entry') AS entries,
               count(*) FILTER (WHERE p.kind='exit') AS exits,
               count(DISTINCT CASE WHEN p.kind='entry' THEN p.amt END) AS damt,
               median(p.amt) FILTER (WHERE p.kind='entry') AS medamt
        FROM probe p JOIN cl c ON c.owner = p.owner
        GROUP BY c.cid ORDER BY entries DESC
        """
    ).fetchdf()
    top1 = con.execute(
        """
        WITH e AS (SELECT c.cid, p.amt, count(*) AS n
                   FROM probe p JOIN cl c ON c.owner = p.owner
                   WHERE p.kind='entry' GROUP BY c.cid, p.amt)
        SELECT cid, max(n) AS top1 FROM e GROUP BY cid
        """
    ).fetchdf().set_index("cid")["top1"].to_dict()
    for _, r in df.iterrows():
        e = max(int(r.entries), 1)
        echo(
            f"  {int(r.cid):>7} {int(r.wal):>4} {int(r.entries):>9,} {int(r.exits):>8,} "
            f"{int(r.damt):>13,} {int(r.damt) / e:>13.4f} "
            f"{top1.get(r.cid, 0) / e:>11.2%} {100 * r.medamt / 1e15:>12.4f}%"
        )
    echo(
        "\n  READ IT THIS WAY: distinct/entries near 1.00 with a negligible top1 share means"
        "\n  every position is a different size -- consistent with buying a moving curve and"
        "\n  NOT with a spammer's fixed dust. Near 0 with a large top1 share is the airdrop."
    )
    echo("\n=== 7.2 active windows -- the confound check for 'territory' ===")
    echo("  Two clusters that never share a coin have a boring explanation available: they")
    echo("  were alive in different weeks. Systematic avoidance only means anything between")
    echo("  clusters that were BOTH TRADING AT THE SAME TIME, so the overlap is measured.")
    import datetime as _dt

    act = con.execute(
        """
        SELECT c.cid, min(p.t) AS t0, max(p.t) AS t1,
               count(DISTINCT date_trunc('day', to_timestamp(p.t))) AS active_days,
               count(DISTINCT p.mint) AS coins
        FROM probe p JOIN cl c ON c.owner = p.owner
        GROUP BY c.cid ORDER BY c.cid
        """
    ).fetchdf()
    echo(f"  {'cid':>7} {'first':>17} {'last':>17} {'days':>5} {'coins':>8}")
    for _, r in act.iterrows():
        echo(
            f"  {int(r.cid):>7} "
            f"{_dt.datetime.fromtimestamp(r.t0, _dt.UTC):%Y-%m-%d %H:%M:%S} "
            f"{_dt.datetime.fromtimestamp(r.t1, _dt.UTC):%Y-%m-%d %H:%M:%S} "
            f"{int(r.active_days):>5} {int(r.coins):>8,}"
        )
    echo("\n  pairwise: calendar overlap vs coin overlap")
    echo(f"  {'A':>7} {'B':>7} {'co-active days':>15} {'shared coins':>13} {'Jaccard':>9}")
    ids = list(act["cid"])
    days = {
        int(r.cid): set(
            con.execute(
                "SELECT DISTINCT date_trunc('day', to_timestamp(p.t)) FROM probe p "
                "JOIN cl c ON c.owner=p.owner WHERE c.cid = ?", [int(r.cid)]
            ).fetchdf().iloc[:, 0]
        )
        for _, r in act.iterrows()
    }
    coins = {
        int(r.cid): set(
            con.execute(
                "SELECT DISTINCT p.mint FROM probe p JOIN cl c ON c.owner=p.owner "
                "WHERE c.cid = ?", [int(r.cid)]
            ).fetchdf().iloc[:, 0]
        )
        for _, r in act.iterrows()
    }
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            a, b = int(a), int(b)
            sh = len(coins[a] & coins[b])
            un = len(coins[a] | coins[b])
            echo(
                f"  {a:>7} {b:>7} {len(days[a] & days[b]):>15} {sh:>13,} "
                f"{(sh / un if un else 0):>9.4f}"
            )
    echo("\n=== 7.3 the operator's coins ===")
    ops = ",".join("'" + m + "'" for m in OPERATOR_COINS)
    op = con.execute(
        f"""
        SELECT c.cid, p.mint, min(p.t) FILTER (WHERE p.kind='entry') AS first_entry,
               count(*) FILTER (WHERE p.kind='entry') AS entries,
               count(*) FILTER (WHERE p.kind='exit') AS exits
        FROM probe p JOIN cl c ON c.owner = p.owner
        WHERE p.mint IN ({ops})
        GROUP BY c.cid, p.mint ORDER BY p.mint, first_entry
        """
    ).fetchdf()
    if op.empty:
        echo("  none of these clusters touched any of the operator's four coins.")
    else:
        for mint, g in op.groupby("mint"):
            t0 = con.execute(
                f"SELECT min(block_time) FROM read_parquet('{d}/*.parquet') WHERE mint = ?",
                [mint],
            ).fetchone()[0]
            echo(f"\n  {OPERATOR_COINS.get(mint, mint)}")
            echo(f"    corpus-visible first crossing on this coin: t0")
            echo(f"    {'cid':>7} {'entry vs t0':>12} {'entries':>8} {'exits':>7}")
            for _, r in g.sort_values("first_entry").iterrows():
                off = (
                    "-" if pd.isna(r.first_entry) else f"{int(r.first_entry - t0):+d}s"
                )
                echo(
                    f"    {int(r.cid):>7} {off:>12} {int(r.entries):>8} {int(r.exits):>7}"
                )
    echo("\n=== 7.4 per-WALLET offsets: did the partition find rungs, or invent them? ===")
    echo("  A cluster-level lead-lag can be an artifact of clustering: if a partition cuts a")
    echo("  smooth continuum of wallet latencies into groups, the group medians will look")
    echo("  like a ladder no matter what. So this drops the partition entirely, takes the")
    echo("  single busiest wallet as reference, and measures every OTHER wallet's own median")
    echo("  first-entry offset from it over their shared coins. If the cluster labels are")
    echo("  real, wallets inside one cluster land on ONE offset and clusters separate.")
    ref_row = con.execute(
        """SELECT owner, count(DISTINCT mint) n FROM probe WHERE kind='entry'
           GROUP BY owner ORDER BY n DESC LIMIT 1"""
    ).fetchone()
    if ref_row:
        ref, refn = ref_row
        con.execute(
            """CREATE OR REPLACE TABLE fe AS
               SELECT mint, owner, min(t) AS t FROM probe WHERE kind='entry'
               GROUP BY mint, owner"""
        )
        off = con.execute(
            """
            WITH r AS (SELECT mint, t FROM fe WHERE owner = ?),
                 d AS (SELECT c.cid, f.owner, f.t - r.t AS off
                       FROM fe f JOIN r ON r.mint = f.mint JOIN cl c ON c.owner = f.owner
                       WHERE f.owner <> ?),
                 a AS (SELECT cid, owner, count(*) AS coins, median(off) AS med,
                              quantile_cont(off, 0.25) AS q1, quantile_cont(off, 0.75) AS q3,
                              mode(off) AS mode_off
                       FROM d GROUP BY cid, owner HAVING count(*) >= 200)
            SELECT a.*, (SELECT count(*) FROM d WHERE d.owner = a.owner
                         AND d.off = a.mode_off)::DOUBLE / a.coins AS mode_share
            FROM a ORDER BY a.med, a.cid
            """,
            [ref, ref],
        ).fetchdf()
        echo(f"  reference wallet {ref} (cluster {cl[cl.owner == ref]['cid'].iloc[0]}), "
             f"{refn:,} coins")
        echo(
            f"  {'wallet':>14} {'cid':>7} {'coins':>7} {'median':>8} {'IQR':>13} "
            f"{'mode':>7} {'mode share':>11}"
        )
        for _, r in off.iterrows():
            echo(
                f"  {r.owner[:12]:>14} {int(r.cid):>7} {int(r.coins):>7,} "
                f"{r.med:>+7.0f}s [{r.q1:>+5.0f},{r.q3:>+5.0f}]s "
                f"{r.mode_off:>+6.0f}s {r.mode_share:>10.1%}"
            )
        spread = off.groupby("cid")["med"].agg(["min", "max", "count"])
        bad = spread[spread["min"] != spread["max"]]
        echo(
            f"\n  clusters whose wallets do NOT all share one median offset: "
            f"{len(bad):,} of {len(spread):,}"
        )

    echo("\n=== 7.5 wallets ===")
    for cid in sorted(set(members["cid"])):
        ws = sorted(members[members["cid"] == cid]["owner"])
        echo(f"  cluster {cid} ({len(ws)} wallets):")
        for w in ws:
            echo(f"      {w}")
    con.close()


# ---------------------------------------------------------------------------------------
# STAGE 9 -- what SELECTS a cluster's coins, and whether territory is deployer allegiance.
# The deployer/curve features come from studies/data/operator_crime/coins.parquet, which
# covers this exact window (266,928 coins, 218,652 with a deployer, 53,335 deployers).
# ---------------------------------------------------------------------------------------

CRIME_COINS = ROOT / "studies" / "data" / "operator_crime" / "coins.parquet"


def cmd_selection(source: str, cids: list[int], thresh: float = 0.10,
                  min_size: int = 3, seed: int = 20260815) -> None:
    """The named clusters touch ~1.5% of corpus mints. What picks them?

    Contrast is DAY-MATCHED: touched coins vs all same-birth-day corpus coins, because
    launch volume and ambient quality drift day to day and an unmatched contrast would
    measure the calendar (the repo has paid for that mistake more than once).
    """
    import pandas as pd

    if not CRIME_COINS.exists():
        echo(f"  {CRIME_COINS} missing; run operator_crime first")
        return
    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    cl = pd.read_parquet(cl_path)
    members = cl[cl["cid"].isin(cids)]
    lst = ",".join("'" + w + "'" for w in members["owner"])
    d = ev_dir(source)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE touched AS
        WITH x AS (SELECT mint, unnest(owners) AS owner
                   FROM read_parquet('{d}/*.parquet') WHERE kind = 'entry')
        SELECT DISTINCT mint FROM x WHERE owner IN ({lst})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE coins AS
        SELECT c.*, date_trunc('day', to_timestamp(c.birth_time)) AS bday,
               t.mint IS NOT NULL AS touched
        FROM read_parquet('{CRIME_COINS}') c LEFT JOIN touched t ON t.mint = c.mint
        """
    )
    cov = con.execute(
        """SELECT count(*) FILTER (WHERE touched) t_in,
                  (SELECT count(*) FROM touched) t_all, count(*) uni FROM coins"""
    ).fetchone()
    echo(f"\n=== 9.1 selection: clusters {cids} ===")
    echo(
        f"  touched mints: {cov[1]:,}; with birth/curve features: {cov[0]:,} "
        f"({cov[0] / max(cov[1], 1):.1%} joined); corpus universe: {cov[2]:,}"
    )
    echo("  day-matched contrast (medians unless noted):")
    rows = con.execute(
        """
        SELECT touched, count(*) n,
               median(n_snipers) med_snipers,
               avg(graduated::INT) grad_rate,
               median(dev_buy_share) med_devbuy,
               median(peak_mcap_sol) med_peak_mcap,
               median(lifetime_s) med_lifetime,
               median(drawdown_from_peak) med_drawdown,
               median(n_birth_legs) med_birth_legs
        FROM coins GROUP BY touched ORDER BY touched
        """
    ).fetchdf()
    echo(rows.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    echo("\n  per-day touch rate (is the selector stable?):")
    per = con.execute(
        """SELECT bday, count(*) launches, count(*) FILTER (WHERE touched) sel,
                  count(*) FILTER (WHERE touched)::DOUBLE / count(*) rate
           FROM coins GROUP BY bday ORDER BY bday"""
    ).fetchdf()
    for _, r in per.iterrows():
        echo(f"    {str(r.bday)[:10]}  {int(r.launches):>7,} launches  "
             f"{int(r.sel):>6,} touched  {r.rate:>6.2%}")

    echo("\n=== 9.2 deployer concentration of the touched set ===")
    echo("  If the clusters are a paid service, WHO they buy is a ledger of who paid;")
    echo("  concentration in few deployers is the signature. Contrast: top-10-deployer")
    echo("  share of touched coins vs the same share among all same-day launches.")
    dep = con.execute(
        """
        WITH t AS (SELECT deployer, count(*) n FROM coins
                   WHERE touched AND deployer IS NOT NULL GROUP BY deployer),
             a AS (SELECT deployer, count(*) n FROM coins
                   WHERE deployer IS NOT NULL GROUP BY deployer)
        SELECT (SELECT sum(n) FROM (SELECT n FROM t ORDER BY n DESC LIMIT 10))::DOUBLE
                 / (SELECT sum(n) FROM t) AS top10_touched,
               (SELECT sum(n) FROM (SELECT n FROM a ORDER BY n DESC LIMIT 10))::DOUBLE
                 / (SELECT sum(n) FROM a) AS top10_all,
               (SELECT count(*) FROM t) AS touched_deployers,
               (SELECT count(*) FROM a) AS all_deployers
        """
    ).fetchone()
    echo(f"  distinct deployers among touched : {dep[2]:,} (universe {dep[3]:,})")
    echo(f"  top-10 deployer share, touched   : {dep[0]:.2%}")
    echo(f"  top-10 deployer share, universe  : {dep[1]:.2%}")
    top = con.execute(
        """SELECT deployer, count(*) n,
                  (SELECT count(*) FROM coins c2 WHERE c2.deployer = coins.deployer)
                    AS dep_total
           FROM coins WHERE touched AND deployer IS NOT NULL
           GROUP BY deployer ORDER BY n DESC LIMIT 12"""
    ).fetchdf()
    echo("  busiest deployers in the touched set (n touched / deployer's total launches):")
    for _, r in top.iterrows():
        echo(f"    {r.deployer}  {int(r.n):>5,} / {int(r.dep_total):>5,} "
             f"({r.n / r.dep_total:.0%} of their launches)")
    con.close()


def cmd_deployer_territory(source: str, thresh: float = 0.10, min_size: int = 3,
                           seed: int = 20260815, top: int = 25) -> None:
    """Is the territory partition a DEPLOYER partition?

    For the same top clusters the territory test ran on: each cluster's coin set joined to
    deployers; then pairwise deployer-set overlap next to coin-set overlap. If avoidance is
    deployer allegiance, coin-disjoint pairs are also deployer-disjoint and, conversely,
    each cluster's coins concentrate on deployers the others do not touch.
    """
    import pandas as pd

    if not CRIME_COINS.exists():
        echo(f"  {CRIME_COINS} missing")
        return
    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    prof = pd.read_parquet(CACHE / f"profiles_{source}.parquet")
    big = prof.nlargest(top, "coins")["cid"].tolist()
    _member_events(con, source, cl_path)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cd AS
        SELECT DISTINCT me.cid, me.mint, c.deployer
        FROM me JOIN read_parquet('{CRIME_COINS}') c ON c.mint = me.mint
        WHERE me.cid IN ({",".join(str(c) for c in big)}) AND c.deployer IS NOT NULL
        """
    )
    echo(f"\n=== 9.3 territory vs deployers (top {top} clusters) ===")
    per = con.execute(
        """SELECT cid, count(DISTINCT mint) coins, count(DISTINCT deployer) deployers
           FROM cd GROUP BY cid ORDER BY coins DESC"""
    ).fetchdf()
    echo(f"  {'cid':>7} {'coins(joined)':>14} {'deployers':>10} {'coins/deployer':>15}")
    for _, r in per.iterrows():
        echo(f"  {int(r.cid):>7} {int(r.coins):>14,} {int(r.deployers):>10,} "
             f"{r.coins / r.deployers:>15.2f}")
    echo("\n  pairwise: coin Jaccard vs deployer Jaccard "
         "(deployer-aligned avoidance => both near zero; coin-only avoidance =>")
    echo("  deployer overlap HIGH while coin overlap is low -- they know the same houses")
    echo("  but split the catalogue):")
    pairs = con.execute(
        """
        WITH cm2 AS (SELECT DISTINCT cid, mint FROM cd),
             dm AS (SELECT DISTINCT cid, deployer FROM cd)
        SELECT a.cid A, b.cid B,
               (SELECT count(*) FROM cm2 x JOIN cm2 y
                 ON x.mint = y.mint AND x.cid = a.cid AND y.cid = b.cid) inter_c,
               (SELECT count(*) FROM dm x JOIN dm y
                 ON x.deployer = y.deployer AND x.cid = a.cid AND y.cid = b.cid) inter_d,
               (SELECT count(*) FROM cm2 WHERE cid = a.cid) ca,
               (SELECT count(*) FROM cm2 WHERE cid = b.cid) cb,
               (SELECT count(*) FROM dm WHERE cid = a.cid) da,
               (SELECT count(*) FROM dm WHERE cid = b.cid) db
        FROM (SELECT DISTINCT cid FROM cd) a JOIN (SELECT DISTINCT cid FROM cd) b
          ON a.cid < b.cid
        """
    ).fetchdf()
    pairs["jc"] = pairs.inter_c / (pairs.ca + pairs.cb - pairs.inter_c)
    pairs["jd"] = pairs.inter_d / (pairs.da + pairs.db - pairs.inter_d)
    echo(f"  {'A':>7} {'B':>7} {'coin J':>8} {'deployer J':>11}")
    show = pairs.sort_values("jc").head(10)
    for _, r in show.iterrows():
        echo(f"  {int(r.A):>7} {int(r.B):>7} {r.jc:>8.4f} {r.jd:>11.4f}")
    import numpy as np

    lo = pairs[pairs.jc < 0.01]
    echo(
        f"\n  among the {len(lo):,} coin-disjoint pairs (coin J < 0.01): "
        f"median deployer J = {lo['jd'].median():.4f}"
    )
    echo(
        f"  among all {len(pairs):,} pairs:               "
        f"median deployer J = {pairs['jd'].median():.4f}"
    )
    echo("  READ: if coin-disjoint pairs still share deployers heavily, the fleets shop the")
    echo("  same catalogue and split coins some other way; if deployer J collapses with coin")
    echo("  J, the avoidance IS deployer allegiance.")
    con.close()


# ---------------------------------------------------------------------------------------
# STAGE 13 -- PvP meta-events: theme bursts in the live launch stream.
#
# Measured live on the 2026-08-15 "Scratch" storm (Disney character announcement):
# 39 instances in 2 h; the war resolved in ~35 s; first mover lost despite an 11.85 SOL dev
# buy; 3 organic winners launched at +22 s and +35 s; a 16-instance zero-dev-buy "OG"
# scavenger wave at +3 min captured nothing; one 85 SOL dev buy at +17 min forced a fourth
# migration; the 35 losers held 1.3 SOL combined. The organic winners' first-60 txs were
# full of FLASH-guild wallets from this module's ten-day map; the ladder sat the storm out.
# ---------------------------------------------------------------------------------------

FIREHOSE_NEW = ROOT / "state" / "firehose" / "new_token"


def cmd_pvp(min_instances: int = 8, window_s: int = 7200) -> None:
    """Detect theme bursts (PvP storms) in the firehose launch stream.

    A burst is a name token whose launch count inside a sliding window is >= min_instances
    while the token is otherwise rare in the day's stream. Common carrier words are
    suppressed by a document-frequency cut rather than a stopword list, so tomorrow's meme
    vocabulary needs no code change.
    """
    import json as _json
    import re

    files = sorted(FIREHOSE_NEW.glob("*.jsonl"))
    if not files:
        echo(f"  no launch stream under {FIREHOSE_NEW}")
        return
    rows = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                try:
                    r = _json.loads(line)
                except Exception:
                    continue
                p = r.get("payload", {})
                rows.append((
                    r.get("t_ingest", ""), p.get("mint"),
                    (p.get("name") or ""), (p.get("symbol") or ""),
                    p.get("traderPublicKey"), p.get("solAmount") or 0.0,
                ))
    echo(f"\n=== 13.1 launch stream: {len(rows):,} launches in {len(files)} file(s) ===")
    from datetime import datetime as _dt

    def ts(s: str) -> float:
        try:
            return _dt.fromisoformat(s).timestamp()
        except Exception:
            return 0.0

    tok_hits: dict[str, list] = defaultdict(list)
    for r in rows:
        for w in set(re.findall(r"[a-z]{4,}", (r[2] + " " + r[3]).lower())):
            tok_hits[w].append(r)
    n = len(rows)
    bursts = []
    for w, hs in tok_hits.items():
        # carrier words appear all day at a steady rate; a theme burst is concentrated
        if len(hs) < min_instances or len(hs) > 0.02 * n:
            continue
        times = sorted(ts(h[0]) for h in hs)
        best = 0
        lo = 0
        for hi in range(len(times)):
            while times[hi] - times[lo] > window_s:
                lo += 1
            best = max(best, hi - lo + 1)
        if best >= min_instances and best >= 0.7 * len(hs):
            bursts.append((w, len(hs), best, hs))
    bursts.sort(key=lambda b: -b[2])
    echo(f"  theme bursts (>= {min_instances} instances inside {window_s / 3600:.0f} h, "
         f"concentrated): {len(bursts)}")
    echo(f"  {'token':<14} {'total':>6} {'in-window':>10} {'first':>20} "
         f"{'shotgun devs':>13} {'zero-buy':>9}")
    for w, tot, best, hs in bursts[:15]:
        devs = Counter(h[4] for h in hs)
        shot = sum(1 for _, c in devs.items() if c > 1)
        zero = sum(1 for h in hs if (h[5] or 0) < 0.05)
        first = min(hs, key=lambda h: h[0])
        echo(f"  {w:<14} {tot:>6} {best:>10} {first[0][:19]:>20} {shot:>13} {zero:>9}")
    echo("\n  anatomy lesson from the measured storm: winners come from the +20-40 s cohort,")
    echo("  not the first instance; a zero-dev-buy wave minutes later is scavengers; a huge")
    echo("  late dev buy is a forced winner, visible instantly in this stream.")


# ---------------------------------------------------------------------------------------
# STAGE 14 -- ATTENTION STORMS in the corpus, detected without names.
#
# The live launch stream carries names, so theme bursts are visible there directly (stage
# 13). The ten-day corpus does not -- but competing instances of one theme share EARLY
# BUYERS racing across them, so the storm is recoverable from wallet overlap alone: coins
# born close together whose first-minute buyer sets overlap far above chance are one
# attention event. This buys the thing stage 13 cannot: outcomes, rotation, and fleet
# identity for HUNDREDS of storms instead of one.
# ---------------------------------------------------------------------------------------

# MEASURED (--storms, --storm-edge, 10-day corpus, 6,003 buyer-overlap storms):
#   * buyer overlap recovers CO-SNIPING clusters, not name-themes: board-name modal purity
#     is only 33% (25/130 storms >= 2/3 pure). Honest negative -- the same racing crowd hits
#     many concurrent coins regardless of theme. So these are "same early crowd," not "same
#     meme."
#   * the graduation signal is ACCUMULATOR/LADDER touch, and it is enormous and clean:
#     ladder-touched coins graduate 62.2% (0 FLASH competitors) / 34.8% (contested) vs
#     3-5% untouched -- 11-13x, holding every one of the 10 days.
#   * the apparent "FLASH presence lowers graduation" is SIMPSON'S PARADOX: FLASH marks
#     contested storms (low per-coin base rate), and the 0-FLASH bucket was enriched in
#     ladder picks. Stratifying on ladder touch dissolves it.
#   * WITHIN a storm (self-controlled: same theme, moment, crowd) FLASH concentration still
#     points at the eventual winner in 37% of storms vs a 14.2% random-instance null (2.6x).
#   * EDGE STATUS: all of this is IN-SAMPLE -- the clusters were built from this same corpus,
#     so "fleet presence predicts" is not yet an edge. The ladder touches within 5 s, giving
#     a t+5s graduation posterior of 35-62% vs a ~3% base, BUT the predict-vs-manufacture
#     ambiguity is unresolved offline, and out-of-sample (Aug-15) confirmation is the gate.
#
# OUT-OF-SAMPLE (Aug-15 live stream, 29 named bursts / 2,994 instances, curves probed):
#   * the Scratch arrival-order rule ("winners come from the +20-60s cohort, never first")
#     is DEAD, and in the OPPOSITE direction: advantage is MONOTONE-EARLY -- rank-1
#     instances win 17.2% (~15x the 1.1% base), decaying with rank; +20-60s won 1 of 43.
#     (An earlier read of these numbers in this session was wrong -- a case-sensitive state
#     filter dropped 32 of 34 winners. The agent report with the against-opportunity table
#     is authoritative.)
#   * the scavenger rule REPLICATED: 1 winner in 2,325 late zero-dev-buy instances (0.043%).
#   * NEW SPECIES: a forced-migration operator -- ten "winners" across nine storms are ONE
#     actor, fresh wallet each time, dev buy exactly 85.005359 SOL = the curve-completion
#     amount. Mechanical self-migration, not a market outcome; it also re-reads the Scratch
#     late whale as the same operation. Fingerprint: the magic number.
#   * 10 of 29 bursts produced no winner; organic winners are 24/2,994 (0.8%).
#   * the within-storm fleet-pointer FAILED its cheap OOS test: on the 3 bursts where the
#     winner's first minute was reachable, early fleet presence did not separate winners
#     from big-dev-buy losers (1W/2L vs a 0.75-win null; funded losers carried 4-10 FLASH
#     wallets, one winner carried zero). Fleet presence marks WHICH STORMS the pros attend,
#     not which instance wins. Caveat: all six unreachable instances were winners (25k+ txs
#     within hours), so the test is winner-side truncated -- rerun on the daily parquet.
#   * the ladder was absent from storm flow entirely: 1 rung wallet across 33 instances.
#   * the ladder-touch OOS test is BLOCKED by RPC shape (a winner accumulates >25k txs in
#     hours; newest-first pagination cannot reach its first minute -- measured: 25 pages,
#     still 66 min short). It becomes FREE when the Aug-15 daily parquet lands: rerun
#     --events for the new day, then --storms/--storm-edge with clusters frozen from the
#     PRIOR ten days. That is the single highest-value next run this module leaves open.
#
# A wallet early-buying more than this many coins inside one 5-minute birth bucket is a
# universal sniper spraying everything concurrent -- zero theme information, and the edges
# it would create link every concurrent coin into one blob. Excluded, with counts.
STORM_BUCKET_S: Final = 300
STORM_MAX_PER_BUCKET: Final = 15
STORM_PAIR_DT: Final = 600
STORM_MIN_SHARED: Final = 3
STORM_MIN_COS: Final = 0.25


def _storm_tables(con) -> None:
    """early (owner, mint, birth) legs + informative-buyer filter, shared by both stages."""
    d = ev_dir("bulk")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE births AS
        SELECT mint, birth_time, deployer, dev_buy_share, graduated,
               peak_mcap_sol, lifetime_s
        FROM read_parquet('{CRIME_COINS}') WHERE birth_time IS NOT NULL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE early AS
        WITH e AS (
          SELECT e.mint, e.block_time, e.block_slot, unnest(e.owners) AS owner
          FROM read_parquet('{d}/*.parquet') e
          WHERE e.kind = 'entry'
        )
        SELECT e.owner, e.mint, b.birth_time,
               e.block_time - b.birth_time AS lat,
               (b.birth_time // {STORM_BUCKET_S}) AS bucket
        FROM e JOIN births b ON b.mint = e.mint
        WHERE e.block_time <= b.birth_time + 60
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE inform AS
        SELECT owner, bucket, count(*) AS k
        FROM (SELECT DISTINCT owner, mint, bucket FROM early)
        GROUP BY owner, bucket
        HAVING count(*) BETWEEN 2 AND {STORM_MAX_PER_BUCKET}
        """
    )


def cmd_storms() -> None:
    """Detect attention storms from early-buyer overlap; validate against board names."""
    import json as _json
    import re

    import pandas as pd

    con = _duck()
    _storm_tables(con)
    tot = con.execute(
        """SELECT (SELECT count(*) FROM early),
                  (SELECT count(DISTINCT owner) FROM early),
                  (SELECT count(*) FROM inform),
                  (SELECT count(DISTINCT owner) FROM
                     (SELECT owner, bucket, count(DISTINCT mint) c FROM early
                      GROUP BY owner, bucket HAVING c > {mx}) t)
        """.format(mx=STORM_MAX_PER_BUCKET)
    ).fetchone()
    echo("\n=== 14.1 storm detection (buyer-overlap, no names) ===")
    echo(f"  early (<=60 s) entry legs          : {tot[0]:,} from {tot[1]:,} wallets")
    echo(f"  informative (owner, bucket) pairs  : {tot[2]:,}  "
         f"(2..{STORM_MAX_PER_BUCKET} early buys per {STORM_BUCKET_S}s birth bucket)")
    echo(f"  EXCLUDED spray wallets (theme-free): {tot[3]:,} wallet-buckets over the cap")

    # pairs via informative wallets; weight 1/(k-1) per wallet so one selective racer
    # contributes one unit of evidence total, however many instances it raced.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cpairs AS
        WITH ie AS (
          SELECT DISTINCT e.owner, e.mint, e.birth_time, e.bucket, i.k
          FROM early e JOIN inform i ON i.owner = e.owner AND i.bucket = e.bucket
        )
        SELECT a.mint AS ma, b.mint AS mb,
               sum(1.0 / (a.k - 1)) AS w,
               count(DISTINCT a.owner) AS shared
        FROM ie a JOIN ie b
          ON a.owner = b.owner AND a.mint < b.mint
         AND abs(a.birth_time - b.birth_time) <= {STORM_PAIR_DT}
        GROUP BY a.mint, b.mint
        HAVING count(DISTINCT a.owner) >= {STORM_MIN_SHARED}
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE csize AS
        SELECT mint, count(DISTINCT owner) AS n FROM
          (SELECT e.owner, e.mint FROM early e JOIN inform i
             ON i.owner = e.owner AND i.bucket = e.bucket)
        GROUP BY mint
        """
    )
    edges = con.execute(
        f"""
        SELECT p.ma, p.mb, p.w, p.shared,
               p.w / sqrt(sa.n::DOUBLE * sb.n::DOUBLE) AS cos
        FROM cpairs p JOIN csize sa ON sa.mint = p.ma JOIN csize sb ON sb.mint = p.mb
        WHERE p.w / sqrt(sa.n::DOUBLE * sb.n::DOUBLE) >= {STORM_MIN_COS}
        """
    ).fetchdf()
    echo(f"  coin pairs >= {STORM_MIN_SHARED} shared informative buyers, "
         f"cos >= {STORM_MIN_COS}: {len(edges):,}")

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in edges.itertuples():
        a, b = find(r.ma), find(r.mb)
        if a != b:
            parent[a] = b
    comp: dict[str, list] = defaultdict(list)
    for m in parent:
        comp[find(m)].append(m)
    storms = sorted((v for v in comp.values() if len(v) >= 3), key=len, reverse=True)
    nodes = len(parent)
    echo(f"  storm candidates (components >= 3 instances): {len(storms):,} "
         f"covering {sum(len(s) for s in storms):,} coins")
    if storms:
        echo(f"  giant-component share of graph nodes: {len(storms[0]) / max(nodes, 1):.1%} "
             f"(union-find pathology check; sizes: "
             + ", ".join(str(len(s)) for s in storms[:12]) + " ...)")

    rows = []
    for i, s in enumerate(storms):
        for m in s:
            rows.append((i, m))
    sdf = pd.DataFrame(rows, columns=["storm_id", "mint"])
    sdf.to_parquet(CACHE / "storms_bulk.parquet", index=False)
    echo(f"  -> {CACHE}/storms_bulk.parquet")

    # ---- 14.2 external validation against board names ----------------------------------
    echo("\n=== 14.2 validation: do buyer-overlap storms share NAME tokens? ===")
    echo("  Board snapshots (state/boards/) carry symbols for board-visible coins. For every")
    echo("  storm with >= 3 board-named members, the modal name-token share is computed.")
    names: dict[str, str] = {}
    for f in sorted((ROOT / "state" / "boards").glob("boards-*.jsonl")):
        with open(f) as fh:
            for line in fh:
                try:
                    r = _json.loads(line)
                except Exception:
                    continue
                for mrow in r.get("members", []) or []:
                    if mrow.get("mint") and mrow.get("symbol"):
                        names[mrow["mint"]] = str(mrow["symbol"])
    echo(f"  board-named mints available: {len(names):,}")
    sdf["symbol"] = sdf["mint"].map(names)
    purities = []
    examples = []
    for sid, g in sdf.dropna(subset=["symbol"]).groupby("storm_id"):
        if len(g) < 3:
            continue
        toks = [re.sub(r"[^a-z]", "", s.lower()) for s in g["symbol"]]
        toks = [t for t in toks if t]
        if len(toks) < 3:
            continue
        top, cnt = Counter(toks).most_common(1)[0]
        purities.append(cnt / len(toks))
        if len(examples) < 8:
            examples.append((sid, len(g), top, cnt, len(toks)))
    if purities:
        import numpy as np

        echo(f"  storms with >=3 board-named members: {len(purities):,}; "
             f"median modal-token purity: {np.median(purities):.0%}; "
             f">=2/3 pure: {sum(1 for p in purities if p >= 2 / 3)}/{len(purities)}")
        for sid, n, top, cnt, nt in examples:
            echo(f"    storm {sid:>5} ({n} named): modal '{top}' {cnt}/{nt}")
    else:
        echo("  no storm had 3+ board-named members; validation is indeterminate on names.")
    con.close()


def cmd_storm_edge(seed: int = 20260815) -> None:
    """The edge test: features observable at t+60 s vs outcomes, across all storms.

    Everything here is a CONDITIONAL RATE with its n, never a fit; the within-storm rank
    comparisons are self-controlled (same theme, same moment, same crowd), which is the
    strongest design available offline. Trials accounting: five features are examined
    (arrival rank, arrival offset, dev-buy share, mapped-fleet presence, ladder touch) --
    PROGRAM.md 3.9 says say so.
    """
    import numpy as np
    import pandas as pd

    con = _duck()
    _storm_tables(con)
    sp = CACHE / "storms_bulk.parquet"
    if not sp.exists():
        raise SystemExit("run --storms first")
    con.execute(f"CREATE OR REPLACE TABLE storms AS SELECT * FROM read_parquet('{sp}')")
    cl_path = CACHE / "clusters_bulk.parquet"
    gd = pd.read_parquet(CACHE / "guilds_bulk.parquet")[["cid", "guild"]]
    con.execute(f"CREATE OR REPLACE TABLE cl AS SELECT * FROM read_parquet('{cl_path}')")
    con.register("gdf", gd)
    con.execute("CREATE OR REPLACE TABLE guilds AS SELECT * FROM gdf")
    lad = ",".join(str(c) for c in (1504, 6464, 4899, 17569, 16518, 13755))

    con.execute(
        f"""
        CREATE OR REPLACE TABLE inst AS
        WITH fleet AS (
          SELECT e.mint,
                 count(DISTINCT cl.cid) AS n_fleets,
                 count(DISTINCT CASE WHEN g.guild = 'FLASH' THEN cl.cid END) AS n_flash,
                 count(DISTINCT CASE WHEN cl.cid IN ({lad}) THEN cl.cid END) AS n_ladder
          FROM early e
          JOIN cl ON cl.owner = e.owner
          LEFT JOIN guilds g ON g.cid = cl.cid
          GROUP BY e.mint
        )
        SELECT s.storm_id, s.mint, b.birth_time, b.dev_buy_share, b.graduated,
               b.peak_mcap_sol,
               rank() OVER (PARTITION BY s.storm_id ORDER BY b.birth_time) AS arrival_rank,
               b.birth_time - min(b.birth_time) OVER (PARTITION BY s.storm_id) AS offset_s,
               COALESCE(f.n_fleets, 0) AS n_fleets,
               COALESCE(f.n_flash, 0) AS n_flash,
               COALESCE(f.n_ladder, 0) > 0 AS ladder
        FROM storms s
        JOIN births b ON b.mint = s.mint
        LEFT JOIN fleet f ON f.mint = s.mint
        """
    )
    df = con.execute("SELECT * FROM inst").fetchdf()
    df["day"] = pd.to_datetime(df["birth_time"], unit="s", utc=True).dt.date
    ns = df["storm_id"].nunique()
    echo(f"\n=== 14.3 the edge test: {len(df):,} instances in {ns:,} storms ===")
    echo("  five features examined; every number is a conditional rate with its n.")

    # winner = max peak mcap within storm
    df["win"] = (
        df.groupby("storm_id")["peak_mcap_sol"].transform("max") == df["peak_mcap_sol"]
    ) & df["peak_mcap_sol"].notna()

    def rate(dd, mask, label):
        n = int(mask.sum())
        if n == 0:
            echo(f"    {label:<38} n=0")
            return
        g = float(dd.loc[mask, "graduated"].mean())
        w = float(dd.loc[mask, "win"].mean())
        echo(f"    {label:<38} n={n:>7,}  P(grad)={g:>7.2%}  P(storm-win)={w:>7.2%}")

    echo("\n  arrival ORDER within storm (the Scratch rule at population scale):")
    rate(df, df.arrival_rank == 1, "first instance")
    rate(df, df.arrival_rank.isin([2, 3]), "rank 2-3")
    rate(df, (df.arrival_rank >= 4) & (df.arrival_rank <= 10), "rank 4-10")
    rate(df, df.arrival_rank > 10, "rank > 10")

    echo("\n  arrival OFFSET from storm start:")
    rate(df, df.offset_s == 0, "t+0 (storm opener)")
    rate(df, (df.offset_s > 0) & (df.offset_s <= 60), "1-60 s")
    rate(df, (df.offset_s > 60) & (df.offset_s <= 300), "1-5 min")
    rate(df, df.offset_s > 300, "> 5 min")

    echo("\n  mapped-fleet presence in first 60 s:")
    rate(df, df.n_fleets == 0, "no mapped fleet")
    rate(df, (df.n_fleets >= 1) & (df.n_fleets <= 3), "1-3 fleets")
    rate(df, (df.n_fleets >= 4) & (df.n_fleets <= 10), "4-10 fleets")
    rate(df, df.n_fleets > 10, "> 10 fleets")

    echo("\n  FLASH-guild fleets specifically:")
    rate(df, df.n_flash == 0, "no FLASH fleet")
    rate(df, (df.n_flash >= 1) & (df.n_flash <= 2), "1-2 FLASH")
    rate(df, df.n_flash >= 3, ">= 3 FLASH")

    echo("\n  ladder touch (<= 60 s):")
    rate(df, ~df.ladder, "not touched")
    rate(df, df.ladder, "touched by the ladder")

    echo("\n  per-day stability of the strongest contrast (>=3 FLASH vs 0), P(grad):")
    for day, g in df.groupby("day"):
        a = g[g.n_flash >= 3]["graduated"]
        b = g[g.n_flash == 0]["graduated"]
        if len(a) >= 20:
            echo(f"    {day}  >=3 FLASH: {a.mean():>6.2%} (n={len(a):,})   "
                 f"0 FLASH: {b.mean():>6.2%} (n={len(b):,})")

    echo("\n  WITHIN-storm self-controlled test: in storms with >= 5 instances and exactly")
    echo("  one max-mcap winner, does the winner have the most FLASH fleets in its first")
    echo("  minute? (null: winner is a random instance, so P = 1/n_instances)")
    hits = tries = 0
    exp = 0.0
    for sid, g in df.groupby("storm_id"):
        if len(g) < 5 or g["win"].sum() != 1:
            continue
        w = g[g["win"]].iloc[0]
        mx = g["n_flash"].max()
        if mx == 0:
            continue
        tries += 1
        exp += 1.0 / len(g)
        top = g[g["n_flash"] == mx]
        if w["n_flash"] == mx and len(top) == 1:
            hits += 1
    if tries:
        echo(f"    winner is the UNIQUE max-FLASH instance in {hits}/{tries} storms "
             f"({hits / tries:.1%}); random-instance null expects ~{exp / tries:.1%}")
    df.to_parquet(CACHE / "storm_instances.parquet", index=False)
    echo(f"\n  -> {CACHE}/storm_instances.parquet")
    con.close()


# ---------------------------------------------------------------------------------------
# STAGE 11 -- persistence: does a fleet live for a day, a week, or the whole window?
# ---------------------------------------------------------------------------------------


def cmd_persistence(source: str, thresh: float = 0.10, min_size: int = 3,
                    seed: int = 20260815) -> None:
    """Per-day cohesion of every profiled cluster.

    A cluster 'co-fires' on a day if at least one (mint, slot) event that day contains two
    or more of its members. Ten days cannot measure a lifetime longer than ten days, but
    they can measure TURNOVER: if most fleets co-fire on one or two days, the map decays in
    days and the detector matters more than any snapshot; if most span the window, the
    snapshot is an asset. Days are UTC.
    """
    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    _member_events(con, source, cl_path)
    con.execute(
        """
        CREATE OR REPLACE TABLE codays AS
        WITH co AS (
          SELECT cid, date_trunc('day', to_timestamp(t)) AS day
          FROM me GROUP BY cid, mint, slot, kind, day
          HAVING count(DISTINCT owner) >= 2
        )
        SELECT cid, count(DISTINCT day) AS n_days,
               min(day) AS first_day, max(day) AS last_day,
               date_diff('day', min(day), max(day)) + 1 AS span
        FROM co GROUP BY cid
        """
    )
    echo("\n=== 11.1 cluster persistence (co-firing days per cluster) ===")
    tot, nco = con.execute(
        "SELECT (SELECT count(DISTINCT cid) FROM me), count(*) FROM codays"
    ).fetchone()
    echo(f"  profiled clusters: {tot:,}; ever co-firing (>=2 members in one event): {nco:,}")
    dist = con.execute(
        "SELECT n_days, count(*) n FROM codays GROUP BY n_days ORDER BY n_days"
    ).fetchdf()
    for _, r in dist.iterrows():
        echo(f"    co-active on {int(r.n_days):>2} day(s): {int(r.n):>6,} clusters "
             f"{'#' * min(int(r.n) // 40, 60)}")
    gaps = con.execute(
        "SELECT avg((span - n_days)::DOUBLE) FROM codays WHERE n_days > 1"
    ).fetchone()[0]
    echo(f"  mean skipped days inside a span: {gaps:.2f}")
    surv = con.execute(
        """
        SELECT count(*) FILTER (WHERE first_day = (SELECT min(first_day) FROM codays)
                                  AND last_day = (SELECT max(last_day) FROM codays)) fs,
               count(*) FILTER (WHERE first_day = (SELECT min(first_day) FROM codays)) d1,
               count(*) n
        FROM codays
        """
    ).fetchone()
    echo(f"  co-firing already on day 1 (left-censored) : {surv[1]:,} "
         f"({surv[1] / max(surv[2], 1):.1%})")
    echo(f"  co-firing on BOTH day 1 and day 10         : {surv[0]:,} "
         f"({surv[0] / max(surv[2], 1):.1%})")
    births = con.execute(
        "SELECT first_day, count(*) n FROM codays GROUP BY first_day ORDER BY first_day"
    ).fetchdf()
    echo("  first-co-fire day (fleet 'births'; day 1 is left-censored):")
    for _, r in births.iterrows():
        echo(f"    {str(r.first_day)[:10]}  {int(r.n):>6,} {'#' * min(int(r.n) // 40, 60)}")
    con.execute(
        f"COPY codays TO '{CACHE}/persistence_{source}.parquet' "
        f"(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    echo(f"\n  -> {CACHE}/persistence_{source}.parquet")
    con.close()


# ---------------------------------------------------------------------------------------
# STAGE 12 -- ECOLOGY: guilds, niches, the food web, and demography.
# ---------------------------------------------------------------------------------------

GUILD_RULES = """
guild rules, stated up front (interpretable rules, not a hidden fit):
  AFTERMARKET : <50% of touched coins are in-window launches (trades OLD coins)
  ACCUMULATOR : exit_ratio < 0.2 (buys and does not leave; the ladder's guild)
  FLASH       : median hold <= 60 s (in and out inside the launch spike)
  HARVESTER   : median hold 60 s .. 1 h (rides the first wave, then leaves)
  SLOW        : median hold > 1 h (position traders on fresh launches)
rules apply top to bottom; first match wins. exit_ratio = exits / entries.
"""


def _guild(fresh_frac, exit_ratio, med_hold) -> str:
    import math as _m

    if fresh_frac is not None and fresh_frac == fresh_frac and fresh_frac < 0.5:
        return "AFTERMARKET"
    if exit_ratio < 0.2:
        return "ACCUMULATOR"
    if med_hold is None or (isinstance(med_hold, float) and _m.isnan(med_hold)):
        return "FLASH"
    if med_hold <= 60:
        return "FLASH"
    if med_hold <= 3600:
        return "HARVESTER"
    return "SLOW"


def cmd_ecology(source: str, thresh: float = 0.10, min_size: int = 3,
                seed: int = 20260815, n_null: int = 200) -> None:
    """The map, read as an ecosystem.

    Taxonomy first (guild assignment by stated rules), then the trait distributions that
    justify the cut points, then the guild-level FOOD WEB (exit-into-entry with the
    matched-moment null, pooled by guild so the test is strong), then demography (per-guild
    persistence). Retail is not in the map -- wallets appear here only if they co-cross with
    somebody -- so 'retail' appears implicitly: it is the counterparty of every flow that
    does not net to zero inside the mapped guilds. Said out loud in the output.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    _member_events(con, source, cl_path)

    # ---- 12.1 traits and taxonomy -------------------------------------------------------
    echo("\n=== 12.1 traits and taxonomy ===")
    echo(GUILD_RULES)
    fresh = con.execute(
        f"""
        SELECT cid,
               avg(CASE WHEN c.mint IS NOT NULL THEN 1.0 ELSE 0.0 END) AS fresh_frac
        FROM (SELECT DISTINCT cid, mint FROM cm) t
        LEFT JOIN read_parquet('{CRIME_COINS}') c ON c.mint = t.mint
        GROUP BY cid
        """
    ).fetchdf().set_index("cid")["fresh_frac"]
    prof = pd.read_parquet(CACHE / f"profiles_{source}.parquet").set_index("cid")
    prof["fresh_frac"] = fresh
    prof["exit_ratio"] = prof["exits"] / prof["entries"].clip(lower=1)
    prof["guild"] = [
        _guild(r.fresh_frac, r.exit_ratio, r.median_hold_s) for r in prof.itertuples()
    ]
    echo("  trait quantiles that motivate the cut points:")
    q = prof[["exit_ratio", "median_hold_s", "fresh_frac"]].quantile(
        [0.1, 0.25, 0.5, 0.75, 0.9]
    )
    echo(q.to_string(float_format=lambda x: f"{x:,.3f}"))
    echo("\n  guild populations:")
    pop = prof.groupby("guild").agg(
        clusters=("n_wallets", "size"), wallets=("n_wallets", "sum"),
        coins_pd=("coins_per_day", "median"), med_hold=("median_hold_s", "median"),
        exit_ratio=("exit_ratio", "median"), fresh=("fresh_frac", "median"),
    ).sort_values("clusters", ascending=False)
    echo(pop.to_string(float_format=lambda x: f"{x:,.2f}"))
    prof.reset_index().to_parquet(CACHE / f"guilds_{source}.parquet", index=False)

    # ---- 12.2 the food web --------------------------------------------------------------
    echo("\n=== 12.2 the food web: guild-level exit-into-entry, matched-moment null ===")
    echo("  pooled by guild: every guild-A exit vs every guild-B entry on the same coin,")
    echo(f"  |slot difference| <= 2, {n_null} within-coin draws from the pooled entry slots.")
    gmap = prof["guild"].to_dict()
    ev = con.execute("SELECT cid, mint, slot, kind, amt FROM me").fetchdf()
    ev["guild"] = ev["cid"].map(gmap)
    ev = ev.dropna(subset=["guild"])
    mint_ids = {m: i for i, m in enumerate(ev["mint"].unique())}
    ev["mi"] = ev["mint"].map(mint_ids)
    ex = ev[ev["kind"] == "exit"]
    en = ev[ev["kind"] == "entry"]
    entry_pool = {mi: np.asarray(g) for mi, g in en.groupby("mi")["slot"]}
    exl = {
        (g, m): (np.asarray(x["slot"]), np.asarray(x["amt"], dtype=float))
        for (g, m), x in ex.groupby(["guild", "mi"])[["slot", "amt"]]
    }
    enl = {(g, m): np.asarray(x) for (g, m), x in en.groupby(["guild", "mi"])["slot"]}
    ex_mints: dict[str, set] = defaultdict(set)
    for g, m in exl:
        ex_mints[g].add(m)
    en_mints: dict[str, set] = defaultdict(set)
    for g, m in enl:
        en_mints[g].add(m)
    guilds = sorted(pop.index)

    def hits(A, shared, end):
        n, vol = 0, 0.0
        for m in shared:
            sl, am = exl[(A, m)]
            bb = end.get(m)
            if bb is None or len(bb) == 0:
                continue
            hit = (np.abs(sl[:, None] - bb[None, :]) <= 2).any(axis=1)
            n += int(hit.sum())
            vol += float(am[hit].sum())
        return n, vol

    echo(f"\n  {'prey(sell)':>12} {'predator(buy)':>14} {'coins':>7} {'absorbed':>9} "
         f"{'null':>7} {'z(vol)':>7} {'p':>6}  verdict")
    web = []
    for A in guilds:
        for B in guilds:
            if A == B:
                continue
            shared = sorted(ex_mints[A] & en_mints[B])
            if len(shared) < 30:
                continue
            # subsample huge shared sets for tractability; stated, not hidden
            if len(shared) > 4000:
                shared = list(rng.choice(shared, size=4000, replace=False))
            expo = sum(float(exl[(A, m)][1].sum()) for m in shared) or 1.0
            obs_n, obs_v = hits(A, shared, {m: enl[(B, m)] for m in shared})
            nv = []
            for _ in range(n_null):
                perm = {}
                for m in shared:
                    sl = enl[(B, m)]
                    pool = entry_pool.get(m)
                    perm[m] = (
                        sl if pool is None or len(pool) == 0
                        else rng.choice(pool, size=len(sl), replace=True)
                    )
                nv.append(hits(A, shared, perm)[1])
            av = np.array(nv)
            zv = (obs_v - av.mean()) / av.std() if av.std() > 0 else float("nan")
            p = (int((av >= obs_v).sum()) + 1) / (n_null + 1)
            web.append((A, B, len(shared), obs_v / expo, av.mean() / expo, zv, p))
    web.sort(key=lambda r: -(r[5] if r[5] == r[5] else -9e9))
    for A, B, ns, ov, mv, zv, p in web:
        v = "FLOW" if zv == zv and zv > 3 and p < 0.05 else "-"
        echo(f"  {A:>12} {B:>14} {ns:>7,} {ov:>8.2%} {mv:>6.2%} {zv:>7.2f} {p:>6.3f}  {v}")
    echo("\n  what does not net out inside these guilds is absorbed by wallets not in the")
    echo("  map -- retail and singletons. The map only sees actors who co-move.")
    pd.DataFrame(
        web, columns=["prey", "predator", "coins", "absorbed", "null", "z", "p"]
    ).to_parquet(CACHE / f"foodweb_{source}.parquet", index=False)

    # ---- 12.3 demography ---------------------------------------------------------------
    echo("\n=== 12.3 demography (needs --persistence run first; reuses its parquet) ===")
    pp = CACHE / f"persistence_{source}.parquet"
    if pp.exists():
        cod = pd.read_parquet(pp).set_index("cid")
        prof2 = prof.join(cod, how="inner")
        demo = prof2.groupby("guild").agg(
            clusters=("n_days", "size"), med_co_days=("n_days", "median"),
            full_window=("n_days", lambda s: (s >= 10).mean()),
            one_day=("n_days", lambda s: (s <= 1).mean()),
        ).sort_values("clusters", ascending=False)
        echo(demo.to_string(float_format=lambda x: f"{x:,.2f}"))
        echo("  READ: full_window = share of the guild co-firing on 10+ of the 11 UTC days;")
        echo("  one_day = share that co-fired exactly once. Ten days censor longer lives.")
    else:
        echo("  (skipped: persistence parquet missing)")
    con.close()


def cmd_resonance(source: str, cos_min: float = 0.05, mints_min: int = 50,
                  n_min: int = 50, width_max: int = 2) -> None:
    """Scan every strong edge for a LOCKED first-entry offset.

    The 8-second ladder was found by eye in a top-25 table. This is the systematic version:
    a pair of wallets whose first entries on hundreds of different coins sit at a CONSTANT
    offset (IQR width <= `width_max` seconds) is driven by a scheduler, full stop -- no
    market process holds two independent actors at a fixed relative latency across weeks of
    distinct launches. Zero-offset locked pairs are co-triggered; nonzero-offset locked
    pairs are RUNGS of a work queue, and their offsets should assemble into consistent
    one-dimensional ladders if they come from one scheduler.

    The scan is edge-first (only pairs already strong in the co-crossing graph), so it
    inherits the gate's validation and costs one join, not an all-pairs pass.
    """
    import numpy as np
    import pandas as pd

    con = _duck()
    E = CACHE / f"edges_{source}.parquet"
    d = ev_dir(source)
    con.execute(
        f"""CREATE OR REPLACE TABLE cand AS
            SELECT u, v, cos, n_mints FROM read_parquet('{E}')
            WHERE cos >= {cos_min} AND n_mints >= {mints_min}"""
    )
    ncand = con.execute("SELECT count(*) FROM cand").fetchone()[0]
    con.execute(
        """CREATE OR REPLACE TABLE ws AS
           SELECT DISTINCT w FROM (SELECT u AS w FROM cand UNION ALL SELECT v FROM cand)"""
    )
    nws = con.execute("SELECT count(*) FROM ws").fetchone()[0]
    echo(f"\n=== 8.1 resonance scan: {ncand:,} candidate edges over {nws:,} wallets ===")
    echo(f"  candidates: cos >= {cos_min}, shared mints >= {mints_min}")

    # First entry per (owner, mint), over ALL entry events including k=1: a wallet's own
    # schedule does not care whether anyone else crossed in its slot.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE fe AS
        WITH x AS (
          SELECT mint, block_time AS t, unnest(owners) AS owner
          FROM read_parquet('{d}/*.parquet') WHERE kind = 'entry'
        )
        SELECT owner, mint, min(t) AS t
        FROM x JOIN ws ON ws.w = x.owner
        GROUP BY owner, mint
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE off AS
        SELECT c.u, c.v, c.cos, count(*) AS n,
               median(b.t - a.t) AS med,
               quantile_cont(b.t - a.t, 0.25) AS q1,
               quantile_cont(b.t - a.t, 0.75) AS q3,
               quantile_cont(b.t - a.t, 0.10) AS p10,
               quantile_cont(b.t - a.t, 0.90) AS p90
        FROM cand c
        JOIN fe a ON a.owner = c.u
        JOIN fe b ON b.owner = c.v AND b.mint = a.mint
        GROUP BY c.u, c.v, c.cos
        """
    )
    lk = con.execute(
        f"""SELECT u, v, cos, n, med, q1, q3, p10, p90
            FROM off WHERE n >= {n_min} AND (q3 - q1) <= {width_max}
            ORDER BY n DESC"""
    ).fetchdf()
    tot = con.execute("SELECT count(*) FROM off").fetchone()[0]
    echo(f"  edges with >= {n_min} co-entered coins   : {tot:,}")
    echo(
        f"  LOCKED (IQR width <= {width_max}s)          : {len(lk):,}  "
        f"({len(lk) / max(tot, 1):.1%})"
    )
    z = lk[lk["med"].abs() <= 1]
    nz = lk[lk["med"].abs() > 1]
    echo(f"    at zero offset (co-triggered)    : {len(z):,}")
    echo(f"    at NONZERO offset (rungs)        : {len(nz):,}")
    if len(nz):
        echo("\n  offset spectrum of nonzero locked pairs (|median|, seconds):")
        spec = nz["med"].abs().round().astype(int).value_counts().sort_index()
        for k, v in spec.items():
            echo(f"    {k:>5}s : {v:>4} pairs {'#' * min(v, 60)}")

    # ---- assemble automation groups ---------------------------------------------------
    # Components over ALL locked pairs; then, inside each component, solve the 1-D embedding
    # from rounded median offsets and COUNT THE MISMATCHES instead of trusting it.
    echo("\n=== 8.2 automation groups (components of locked pairs) ===")
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, r in lk.iterrows():
        a, b = find(r.u), find(r.v)
        if a != b:
            parent[a] = b
    comp: dict[str, list] = defaultdict(list)
    for w in parent:
        comp[find(w)].append(w)
    groups = sorted(comp.values(), key=len, reverse=True)
    echo(f"  groups: {len(groups):,}   sizes: "
         + ", ".join(str(len(g)) for g in groups[:20])
         + (" ..." if len(groups) > 20 else ""))

    cl_path = CACHE / f"clusters_{source}.parquet"
    cid_of = {}
    if cl_path.exists():
        cldf = pd.read_parquet(cl_path)
        cid_of = dict(zip(cldf["owner"], cldf["cid"]))

    edges_by_pair = {(r.u, r.v): r for _, r in lk.iterrows()}
    out_rows = []
    for gi, g in enumerate(groups):
        if len(g) < 3:
            continue
        gset = set(g)
        ge = [r for (u, v), r in edges_by_pair.items() if u in gset and v in gset]
        # BFS embedding from the best-connected node
        deg = Counter()
        for r in ge:
            deg[r.u] += 1
            deg[r.v] += 1
        root = max(deg, key=deg.get)
        pos = {root: 0.0}
        for _ in range(len(g)):
            for r in ge:
                m = round(r.med)
                if r.u in pos and r.v not in pos:
                    pos[r.v] = pos[r.u] + m
                if r.v in pos and r.u not in pos:
                    pos[r.u] = pos[r.v] - m
        mism = sum(
            1 for r in ge
            if r.u in pos and r.v in pos and abs((pos[r.v] - pos[r.u]) - round(r.med)) > 1
        )
        checks = len(ge) - (len(pos) - 1)
        rungs = sorted(set(pos.values()))
        spac = [int(rungs[i + 1] - rungs[i]) for i in range(len(rungs) - 1)]
        cids = sorted({cid_of.get(w, -1) for w in g})
        coins = int(np.median([r.n for r in ge]))
        out_rows.append((gi, len(g), len(ge), checks, mism, rungs, spac, cids, coins))
    echo("\n  groups with >=3 wallets, embedded and CHECKED:")
    echo(f"  {'grp':>4} {'wal':>4} {'edges':>6} {'checks':>7} {'mismatch':>9} "
         f"{'rungs (s)':>28} {'spacing':>14} {'med coins':>10}  clusters")
    for gi, nwal, nedge, checks, mism, rungs, spac, cids, coins in out_rows[:20]:
        rt = ",".join(f"{int(r):+d}" for r in rungs[:8]) + ("…" if len(rungs) > 8 else "")
        st = ",".join(str(x) for x in spac[:6]) + ("…" if len(spac) > 6 else "")
        echo(
            f"  {gi:>4} {nwal:>4} {nedge:>6} {checks:>7} {mism:>9} {rt:>28} {st:>14} "
            f"{coins:>10,}  {cids}"
        )
    lk.to_parquet(CACHE / f"resonance_{source}.parquet", index=False)
    echo(f"\n  locked pairs -> {CACHE}/resonance_{source}.parquet")
    echo("\n  RECALL CAVEAT, learned from the 8s ladder: rungs spaced more than ~2 slots")
    echo("  apart never co-cross in one (mint, slot) event, so they have NO edge in this")
    echo("  graph and this scan cannot see them. Coarse ladders live at CLUSTER grain --")
    echo("  that is what --resonance2 is for.")
    con.close()


def cmd_resonance2(source: str, thresh: float = 0.10, min_size: int = 3,
                   seed: int = 20260815, min_shared: int = 50, crowd_cap: int = 30,
                   width_max: int = 4) -> None:
    """The CLUSTER-grain ladder scan -- the one that can see coarse rungs.

    A wallet pair 8 seconds apart never lands in the same (mint, slot) event, so the
    co-crossing graph carries no edge between rungs and ``cmd_resonance`` is structurally
    blind to any scheduler whose spacing exceeds a slot or two. At cluster grain the
    blindness disappears: each cluster has a first-entry time per coin, and a locked
    cluster-pair offset over hundreds of distinct coins is the same smoking gun.

    Pair candidates are generated mint-first with a crowd cap: a coin entered by hundreds
    of clusters is a stampede and carries no scheduler information (and would blow the
    pair count); a coin entered by a handful is where a fixed offset can be seen. Offset
    stats are then computed over ALL shared coins of the surviving pairs.
    """
    import numpy as np
    import pandas as pd

    cl_path, _ = build_cluster_table(source, thresh, min_size, seed)
    con = _duck()
    _member_events(con, source, cl_path)
    # cluster-level first entry per coin, from the cm table _member_events built
    con.execute(
        """CREATE OR REPLACE TABLE cfe AS
           SELECT cid, mint, first_entry_t AS t FROM cm WHERE first_entry_t IS NOT NULL"""
    )
    n = con.execute("SELECT count(*) FROM cfe").fetchone()[0]
    echo(f"\n=== 10.1 cluster-grain resonance: {n:,} (cluster, coin) first entries ===")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cand AS
        WITH low AS (
          SELECT mint FROM cfe GROUP BY mint HAVING count(*) BETWEEN 2 AND {crowd_cap}
        )
        SELECT a.cid A, b.cid B, count(*) n_low
        FROM cfe a JOIN cfe b ON a.mint = b.mint AND a.cid < b.cid
        JOIN low l ON l.mint = a.mint
        GROUP BY a.cid, b.cid
        HAVING count(*) >= {min_shared}
        """
    )
    nc = con.execute("SELECT count(*) FROM cand").fetchone()[0]
    echo(f"  cluster pairs sharing >= {min_shared} low-crowd (<= {crowd_cap} clusters) "
         f"coins: {nc:,}")
    con.execute(
        """
        CREATE OR REPLACE TABLE coff AS
        SELECT c.A, c.B, c.n_low, count(*) n,
               median(b.t - a.t) med,
               quantile_cont(b.t - a.t, 0.25) q1,
               quantile_cont(b.t - a.t, 0.75) q3
        FROM cand c
        JOIN cfe a ON a.cid = c.A
        JOIN cfe b ON b.cid = c.B AND b.mint = a.mint
        GROUP BY c.A, c.B, c.n_low
        """
    )
    lk = con.execute(
        f"""SELECT * FROM coff WHERE (q3 - q1) <= {width_max} ORDER BY n DESC"""
    ).fetchdf()
    tot = con.execute("SELECT count(*) FROM coff").fetchone()[0]
    echo(f"  pairs measured: {tot:,}   LOCKED (IQR width <= {width_max}s): {len(lk):,}")
    z = lk[lk["med"].abs() <= 1]
    nz = lk[lk["med"].abs() > 1]
    echo(f"    zero-offset (co-triggered fleets)  : {len(z):,}")
    echo(f"    NONZERO offset (LADDER RUNGS)      : {len(nz):,}")
    if len(nz):
        echo("\n  offset spectrum (|median|, s):")
        spec = nz["med"].abs().round().astype(int).value_counts().sort_index()
        for k, v in spec.items():
            echo(f"    {k:>5}s : {v:>4} pairs {'#' * min(v, 60)}")
        echo(f"\n  nonzero locked pairs (top 30 by shared coins):")
        echo(f"  {'A':>7} {'B':>7} {'coins':>7} {'med off':>8} {'IQR':>15}")
        for _, r in nz.head(30).iterrows():
            echo(f"  {int(r.A):>7} {int(r.B):>7} {int(r.n):>7,} {r.med:>+7.0f}s "
                 f"[{r.q1:>+5.0f},{r.q3:>+5.0f}]s")
    # ladder assembly over nonzero locked pairs
    echo("\n=== 10.2 ladders (components over nonzero locked cluster pairs) ===")
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, r in nz.iterrows():
        a, b = find(int(r.A)), find(int(r.B))
        if a != b:
            parent[a] = b
    comp: dict[int, list] = defaultdict(list)
    for c in parent:
        comp[find(c)].append(c)
    groups = sorted(comp.values(), key=len, reverse=True)
    sizes = pd.read_parquet(cl_path).groupby("cid").size()
    pair_map = {(int(r.A), int(r.B)): r for _, r in nz.iterrows()}
    for gi, g in enumerate(groups[:15]):
        gset = set(g)
        ge = [r for (a, b), r in pair_map.items() if a in gset and b in gset]
        deg = Counter()
        for r in ge:
            deg[int(r.A)] += 1
            deg[int(r.B)] += 1
        root = max(deg, key=deg.get)
        pos = {root: 0.0}
        for _ in range(len(g)):
            for r in ge:
                m = round(r.med)
                if int(r.A) in pos and int(r.B) not in pos:
                    pos[int(r.B)] = pos[int(r.A)] + m
                if int(r.B) in pos and int(r.A) not in pos:
                    pos[int(r.A)] = pos[int(r.B)] - m
        mism = sum(
            1 for r in ge
            if abs((pos[int(r.B)] - pos[int(r.A)]) - round(r.med)) > 1
        )
        checks = len(ge) - (len(pos) - 1)
        rungs = sorted(pos.items(), key=lambda kv: kv[1])
        wal = sum(int(sizes.get(c, 0)) for c in g)
        echo(f"\n  ladder {gi}: {len(g)} clusters, {wal} wallets, {len(ge)} locked pairs, "
             f"{checks} independent checks, {mism} MISMATCHES")
        echo("    " + "  ".join(f"{c}@{int(p):+d}s" for c, p in rungs))
    lk.to_parquet(CACHE / f"resonance2_{source}.parquet", index=False)
    echo(f"\n  -> {CACHE}/resonance2_{source}.parquet")
    con.close()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--events", action="store_true")
    ap.add_argument("--graph", action="store_true")
    ap.add_argument("--channels", action="store_true")
    ap.add_argument("--cluster", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--between", action="store_true")
    ap.add_argument("--operator", action="store_true")
    ap.add_argument("--probe", type=str, default="", help="comma-separated cluster ids")
    ap.add_argument("--resonance", action="store_true")
    ap.add_argument("--resonance2", action="store_true")
    ap.add_argument("--selection", type=str, default="",
                    help="comma-separated cluster ids for coin-selection analysis")
    ap.add_argument("--deployer-territory", action="store_true")
    ap.add_argument("--persistence", action="store_true")
    ap.add_argument("--ecology", action="store_true")
    ap.add_argument("--pvp", action="store_true")
    ap.add_argument("--storms", action="store_true")
    ap.add_argument("--storm-edge", action="store_true")
    ap.add_argument("--source", default="panel", choices=("panel", "bulk"))
    ap.add_argument("--thresh", type=float, default=0.10)
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--draws", type=int, default=200)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20260815)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    if args.events:
        cmd_events(args.source, force=args.force)
        return 0
    if args.graph:
        cmd_graph(args.source)
        return 0
    if args.channels:
        cmd_channels(args.source)
        return 0
    if args.cluster:
        cmd_cluster(args.source, seed=args.seed)
        return 0
    if args.gate:
        cmd_gate(args.source, seed=args.seed)
        return 0
    if args.between:
        cmd_between(
            args.source, thresh=args.thresh, min_size=args.min_size,
            seed=args.seed, n_null=args.draws, top=args.top,
        )
        return 0
    if args.resonance:
        cmd_resonance(args.source)
        return 0
    if args.resonance2:
        cmd_resonance2(args.source, thresh=args.thresh, min_size=args.min_size,
                       seed=args.seed)
        return 0
    if args.selection:
        cmd_selection(
            args.source, [int(x) for x in args.selection.split(",") if x.strip()],
            thresh=args.thresh, min_size=args.min_size, seed=args.seed,
        )
        return 0
    if args.deployer_territory:
        cmd_deployer_territory(args.source, thresh=args.thresh, min_size=args.min_size,
                               seed=args.seed)
        return 0
    if args.persistence:
        cmd_persistence(args.source, thresh=args.thresh, min_size=args.min_size,
                        seed=args.seed)
        return 0
    if args.ecology:
        cmd_ecology(args.source, thresh=args.thresh, min_size=args.min_size,
                    seed=args.seed, n_null=args.draws)
        return 0
    if args.pvp:
        cmd_pvp()
        return 0
    if args.storms:
        cmd_storms()
        return 0
    if args.storm_edge:
        cmd_storm_edge(seed=args.seed)
        return 0
    if args.probe:
        cmd_probe(
            args.source, [int(x) for x in args.probe.split(",") if x.strip()],
            thresh=args.thresh, min_size=args.min_size, seed=args.seed,
        )
        return 0
    if args.operator:
        cmd_operator(
            args.source, thresh=args.thresh, min_size=args.min_size, seed=args.seed
        )
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
