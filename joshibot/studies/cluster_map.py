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
from collections import defaultdict
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
