"""Callout-record facts straight from the archive sqlite — the record page's substrate.

There is no separate "record module" yet; this reads ``archive.sqlite`` directly
(read-only) and returns plain dicts in the dregg_wire.facts idiom: every section
carries a ``source`` string, and absence is a stated ``absent``/``note`` string,
never a zero wearing a measurement's clothes.

The measured-caller leaderboard has a MINIMUM N: a caller enters it only once
``min_priced`` of their callouts have a real 1h return computed. Until the first
cohorts mature (returns price at T+25h, finalize at T+7d) the leaderboard is an
honestly empty slot, and the page says so.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIN_PRICED = 5
TOP_CLAIMS = 5
TOP_MEASURED = 10


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def collect(archive_db: Path, *, min_priced: int = MIN_PRICED) -> dict:
    """Everything the record page renders, in one read-only pass."""

    source = f"dregg_archive {archive_db.name}, full board lifetime"
    if not archive_db.exists():
        return {"source": source, "absent": f"callout archive not present at {archive_db}"}

    db = _connect_ro(archive_db)
    try:
        n_callouts, n_callers, n_mints, t_first, t_last = db.execute(
            "SELECT count(*), count(DISTINCT wallet), count(DISTINCT mint),"
            "       min(t_event_ms), max(t_event_ms) FROM callouts"
        ).fetchone()

        removals_total, removals_removed = db.execute(
            "SELECT count(*), sum(CASE WHEN verdict = 'removed' THEN 1 ELSE 0 END)"
            "  FROM removal_verdicts"
        ).fetchone()

        outcome_rows, outcomes_priced, outcomes_final = db.execute(
            "SELECT count(*), sum(ret_1h IS NOT NULL), sum(dead_flag IS NOT NULL) FROM outcomes"
        ).fetchone()

        # Biggest provider claims, lifetime, each beside whatever we have measured.
        # method_version is pinned per callout to its max so the LEFT JOIN cannot fan out.
        claims = [
            dict(r)
            for r in db.execute(
                "SELECT c.mint, c.wallet, c.username_last, c.thesis, c.provider_multiple_last,"
                "       o.max_close_multiple, o.ret_1h, o.ret_24h, o.ret_7d"
                "  FROM callouts c LEFT JOIN outcomes o"
                "    ON o.callout_id = c.callout_id"
                "   AND o.method_version = (SELECT max(method_version) FROM outcomes o2"
                "                            WHERE o2.callout_id = c.callout_id)"
                " WHERE c.provider_multiple_last IS NOT NULL"
                " ORDER BY c.provider_multiple_last DESC, c.callout_id LIMIT ?",
                (TOP_CLAIMS,),
            ).fetchall()
        ]

        # The measured leaderboard: callers ranked by MEASURED mean 24h return, min n.
        measured = [
            dict(r)
            for r in db.execute(
                "SELECT c.wallet, max(c.username_last) AS username,"
                "       count(*) AS n_callouts, sum(o.ret_1h IS NOT NULL) AS n_priced,"
                "       avg(o.ret_1h) AS mean_ret_1h, avg(o.ret_24h) AS mean_ret_24h,"
                "       avg(o.max_close_multiple) AS mean_max_multiple"
                "  FROM callouts c JOIN outcomes o ON o.callout_id = c.callout_id"
                "   AND o.method_version = (SELECT max(method_version) FROM outcomes o2"
                "                            WHERE o2.callout_id = c.callout_id)"
                " GROUP BY c.wallet HAVING sum(o.ret_1h IS NOT NULL) >= ?"
                " ORDER BY avg(o.ret_24h) DESC, c.wallet LIMIT ?",
                (min_priced, TOP_MEASURED),
            ).fetchall()
        ]
    finally:
        db.close()

    return {
        "source": source,
        "board": {
            "callouts": int(n_callouts or 0),
            "callers": int(n_callers or 0),
            "mints": int(n_mints or 0),
            "t_first_ms": t_first,
            "t_last_ms": t_last,
        },
        "removals": {
            "verdicts": int(removals_total or 0),
            "removed": int(removals_removed or 0),
            "note": (
                None
                if removals_total
                else "armed; nothing has vanished from the provider's board yet"
            ),
        },
        "outcomes": {
            "rows": int(outcome_rows or 0),
            "priced_1h": int(outcomes_priced or 0),
            "final": int(outcomes_final or 0),
        },
        "top_claims": claims,
        "measured_leaderboard": measured,
        "min_priced": min_priced,
        "leaderboard_note": (
            None
            if measured
            else (
                f"no caller has {min_priced}+ measured callouts yet — post-call returns price "
                "at T+25h and finalize at T+7d, and the archive's first cohorts are still in "
                "flight. The slot publishes itself the day the data exists; nothing is "
                "backfilled from anyone's screenshots."
            )
        ),
    }
