"""Deterministic daily facts for the DREGG wire.

One entry point: ``build_facts(day, ...)`` -> a plain dict. Same inputs, same dict —
no clocks, no randomness, no network. The rules it lives by:

* EVERY number carries its source and window (in the section's ``source`` string or
  beside the number itself).
* Absent data is a STATED absence (``absent``/``note`` strings), never a zero that
  pretends to be a measurement.
* The wallet layer is a stale batch artifact (corpus ends 2026-08-14): it is used
  ONLY for caller-wallet color, and always rendered with its as-of date, per
  ``state/wallets/JOIN_CONTRACT.md``.

stdlib sqlite3 + json only; the optional caller-color join uses duckdb or pyarrow
when one is importable and states its absence when neither is.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dregg_archive.store import day_end_ms, day_start_ms

MAX_NOTABLE_CLEANS = 5
MAX_CREWS = 5
MAX_CALLERS = 3
MAX_MEASURED = 8  # matured claimed-vs-measured rows carried for the desk panel

# The season anti-signal baseline: rendered beside any provider-claimed multiple so a
# reader never mistakes the platform's peak number for an expectation.
ANTI_SIGNAL = {
    "ret_1h_mean": -0.119,
    "ret_8h_mean": -0.436,
    "burst_ret_8h_median": -0.647,
    "burst_definition": "2+ callers within 10 minutes",
    "source": "callout-edge study, 314 callouts / 222 mints, run 2026-08-15 (studies/RESULT_callout_edge.md)",
    "short_source": "callout-edge study, run 2026-08-15",
}

WALLET_LAYER_NOTE = "wallet layer is a stale batch artifact — color only, never today's flow"


# -- screen ----------------------------------------------------------------------------


def load_scores(scores_dir: Path, day: str) -> list[dict]:
    """The day's score rows. The scorer partitions its ledger by UTC day already."""

    path = scores_dir / f"{day}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn tail line during live append is not news
    return rows


def _is_mayhem(row: dict) -> bool:
    if row.get("features", {}).get("is_mayhem_mode") is True:
        return True
    return any(str(n).startswith("vendor_flag:is_mayhem_mode") for n in row.get("population_notes", []))


def _hour_utc(row: dict) -> str | None:
    """The row's UTC hour bucket ("00".."23") from its own scored timestamp, or None
    when the timestamp cannot be placed — counted, never guessed."""

    t_scored = row.get("t_scored")
    if not isinstance(t_scored, str):
        return None
    try:
        return datetime.fromisoformat(t_scored).astimezone(UTC).strftime("%H")
    except ValueError:
        return None


def _operating_point(rows: list[dict]) -> dict | None:
    """The validated operating point the scorer stamped on its own rows (B1)."""

    for row in reversed(rows):
        base = row.get("base_rates") or {}
        rip = base.get("is_rip") or {}
        if "admit_rate" in rip:
            return {
                "admit_rate": rip["admit_rate"],
                "clean_precision": rip.get("clean_precision"),
                "clean_ci95": rip.get("clean_ci95"),
                "validated_span": base.get("validated_span"),
            }
    return None


def screen_facts(rows: list[dict], day: str) -> dict:
    source = f"dregg_screen scores/{day}.jsonl, UTC day {day}"
    if not rows:
        return {"source": source, "absent": f"no launches scored on {day} (scores file empty or missing)"}

    verdicts = Counter(str(r.get("verdict", "UNSCORED")) for r in rows)
    hourly: dict[str, dict[str, int]] = {}
    hourly_unplaced = 0
    for row in rows:
        hour = _hour_utc(row)
        if hour is None:
            hourly_unplaced += 1
            continue
        bucket = hourly.setdefault(hour, {})
        verdict = str(row.get("verdict", "UNSCORED"))
        bucket[verdict] = bucket.get(verdict, 0) + 1
    validated = [r for r in rows if r.get("in_validated_population")]
    validated_clean = [r for r in validated if r.get("verdict") == "CLEAN"]
    mayhem_n = sum(1 for r in rows if _is_mayhem(r))

    cleans: list[dict] = []
    seen_mints: set[str] = set()
    def _clean_order(r: dict) -> tuple:
        return (not r.get("in_validated_population"), r.get("features", {}).get("dev_buy_share") or 0.0)

    ordered = sorted((r for r in rows if r.get("verdict") == "CLEAN"), key=_clean_order)
    for row in ordered:
        mint = str(row.get("mint", ""))
        if mint in seen_mints:
            continue
        seen_mints.add(mint)
        cleans.append(
            {
                "symbol": row.get("symbol") or "?",
                "mint": mint,
                "dev_buy_share": row.get("features", {}).get("dev_buy_share"),
                "deployer_history": row.get("deployer_history") or {},
                "in_validated_population": bool(row.get("in_validated_population")),
            }
        )
        if len(cleans) >= MAX_NOTABLE_CLEANS:
            break

    crews: dict[int, dict] = {}
    for row in rows:
        match = row.get("crew_match")
        if not match:
            continue
        crew = crews.setdefault(
            int(match["crew_id"]),
            {
                "crew_id": int(match["crew_id"]),
                "launches_today": 0,
                "symbols": [],
                "max_jaccard": 0.0,
                "crew_coins": match.get("crew_coins"),
                "crew_rips": match.get("crew_rips"),
                "crew_dumps": match.get("crew_dumps"),
            },
        )
        crew["launches_today"] += 1
        crew["symbols"].append(row.get("symbol") or "?")
        crew["max_jaccard"] = max(crew["max_jaccard"], float(match.get("jaccard") or 0.0))
    crew_list = sorted(crews.values(), key=lambda c: (-c["launches_today"], -c["max_jaccard"]))[:MAX_CREWS]

    return {
        "source": source,
        "launches_scored": len(rows),
        "verdicts": dict(sorted(verdicts.items(), key=lambda kv: -kv[1])),
        "hourly": {h: dict(sorted(v.items())) for h, v in sorted(hourly.items())},
        "hourly_unplaced": hourly_unplaced,
        "validated": {
            "count": len(validated),
            "clean": len(validated_clean),
            "clean_rate": (len(validated_clean) / len(validated)) if validated else None,
            "operating_point": _operating_point(rows),
        },
        "mayhem": {
            "count": mayhem_n,
            "share": mayhem_n / len(rows),
            "definition": "vendor mayhem-mode flag at create; outside the validated population",
        },
        "notable_cleans": cleans,
        "crews": crew_list,
        "crews_note": None if crew_list else "no crew-fingerprint matches among today's launches",
    }


# -- callout desk + archive receipts ---------------------------------------------------


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def callout_facts(archive_db: Path, day: str) -> dict:
    source = f"dregg_archive {archive_db.name}, callouts first archived on UTC day {day}"
    if not archive_db.exists():
        return {"source": source, "absent": f"callout archive not present at {archive_db}"}
    start, end = day_start_ms(day), day_end_ms(day)
    db = _connect_ro(archive_db)
    try:
        today = db.execute(
            "SELECT c.callout_id, c.wallet, c.mint, c.thesis, c.provider_multiple_last,"
            "       c.username_last, f.t_response_ms"
            "  FROM callouts c JOIN fetches f ON c.first_seen_fetch = f.id"
            " WHERE f.t_response_ms >= ? AND f.t_response_ms < ?",
            (start, end),
        ).fetchall()
        board_total, board_callers = db.execute(
            "SELECT count(*), count(DISTINCT wallet) FROM callouts"
        ).fetchone()
        removals_today, removals_total = db.execute(
            "SELECT sum(CASE WHEN t_verdict_ms >= ? AND t_verdict_ms < ? THEN 1 ELSE 0 END),"
            "       count(*) FROM removal_verdicts",
            (start, end),
        ).fetchone()
        outcomes_total, outcomes_final, outcomes_priced_1h = db.execute(
            "SELECT count(*), sum(dead_flag IS NOT NULL), sum(ret_1h IS NOT NULL) FROM outcomes"
        ).fetchone()
        matured = db.execute(
            "SELECT c.callout_id, c.mint, c.username_last, c.provider_multiple_last,"
            "       o.ret_1h, o.ret_24h, o.ret_7d, o.max_close_multiple, o.dead_flag"
            "  FROM outcomes o JOIN callouts c ON c.callout_id = o.callout_id"
            " WHERE o.ret_1h IS NOT NULL OR o.ret_24h IS NOT NULL"
            " ORDER BY o.computed_ms DESC, c.callout_id LIMIT ?",
            (MAX_MEASURED,),
        ).fetchall()
    finally:
        db.close()

    top = max(
        (r for r in today if r["provider_multiple_last"] is not None),
        key=lambda r: r["provider_multiple_last"],
        default=None,
    )
    caller_counts = Counter(r["wallet"] for r in today)
    usernames = {r["wallet"]: r["username_last"] for r in today if r["username_last"]}
    top_callers = [
        {"wallet": wallet, "username": usernames.get(wallet), "callouts_today": n}
        for wallet, n in sorted(caller_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_CALLERS]
    ]

    return {
        "source": source,
        "archived_today": len(today),
        "distinct_callers_today": len(caller_counts),
        "distinct_mints_today": len({r["mint"] for r in today}),
        "board_total": board_total,
        "board_callers": board_callers,
        "top_provider_claim": (
            None
            if top is None
            else {
                "multiple": top["provider_multiple_last"],
                "mint": top["mint"],
                "username": top["username_last"],
                "thesis": (top["thesis"] or "")[:80],
                "label": "provider-claimed peak multiple — their number, not our measurement",
            }
        ),
        "anti_signal": ANTI_SIGNAL,
        "measured": [
            {
                "callout_id": r["callout_id"],
                "mint": r["mint"],
                "username": r["username_last"],
                "claimed_multiple": r["provider_multiple_last"],
                "ret_1h": r["ret_1h"],
                "ret_24h": r["ret_24h"],
                "ret_7d": r["ret_7d"],
                "max_close_multiple": r["max_close_multiple"],
                "final": r["dead_flag"] is not None,
            }
            for r in matured
        ],
        "top_callers": top_callers,
        "removals": {
            "today": int(removals_today or 0),
            "total": int(removals_total or 0),
            "note": (
                None
                if removals_total
                else "armed; nothing has vanished from the provider's board yet"
            ),
        },
        "outcomes": {
            "rows": int(outcomes_total or 0),
            "final": int(outcomes_final or 0),
            "priced_1h": int(outcomes_priced_1h or 0),
            "note": (
                "real post-call returns mature at T+25h and finalize at T+7d; "
                "the archive's first cohorts are still in flight"
                if not outcomes_priced_1h
                else None
            ),
        },
    }


def archive_facts(archive_db: Path, day: str, manifest_dir: Path | None = None) -> dict:
    source = f"dregg_archive raw layer, fetches on UTC day {day}"
    if not archive_db.exists():
        return {"source": source, "absent": f"archive not present at {archive_db}"}
    db = _connect_ro(archive_db)
    try:
        fetch_count, zst_bytes = db.execute(
            "SELECT count(*), coalesce(sum(length(body_zst)), 0) FROM fetches"
            " WHERE t_response_ms >= ? AND t_response_ms < ?",
            (day_start_ms(day), day_end_ms(day)),
        ).fetchone()
    finally:
        db.close()
    manifests = sorted(p.name for p in manifest_dir.glob("*.json")) if manifest_dir else []
    return {
        "source": source,
        "fetches_today": fetch_count,
        "zst_bytes_today": zst_bytes,
        "manifests_anchored": len(manifests),
        "manifest_note": (
            None
            if manifests
            else "daily manifests anchor completed days only; "
            "the first publishes after the first full UTC day"
        ),
    }


# -- caller color from the (stale) wallet layer ---------------------------------------


def _read_wallet_rows(parquet: Path, wallets: list[str]) -> list[dict] | str:
    """Rows for these wallets, or a string reason the layer is unreadable."""

    columns = ["owner", "net_realized_sol", "win_rate", "n_coins_closed",
               "rp_mode", "guild", "updated_through"]
    try:
        import duckdb  # optional research-group dep; absence below is a stated fact
    except ImportError:
        duckdb = None  # type: ignore[assignment]
    if duckdb is not None:
        placeholders = ",".join("?" for _ in wallets)
        rows = duckdb.execute(
            f"SELECT {', '.join(columns)} FROM read_parquet(?) WHERE owner IN ({placeholders})",
            [str(parquet), *wallets],
        ).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError:
        return "wallet layer reader unavailable (neither duckdb nor pyarrow installed)"
    table = pq.read_table(parquet, columns=columns)
    return table.filter(pc.is_in(table["owner"], value_set=pa.array(wallets))).to_pylist()


def caller_color(wallet_parquet: Path | None, wallets: list[str]) -> dict:
    """Color-only join per JOIN_CONTRACT.md: stale-labeled, miss = null-with-reason."""

    if wallet_parquet is None or not wallet_parquet.exists():
        return {"absent": "wallet layer parquet not present on this host", "note": WALLET_LAYER_NOTE}
    if not wallets:
        return {"absent": "no caller wallets to join today", "note": WALLET_LAYER_NOTE}
    got = _read_wallet_rows(wallet_parquet, wallets)
    if isinstance(got, str):
        return {"absent": got, "note": WALLET_LAYER_NOTE}
    by_owner = {row["owner"]: row for row in got}
    as_of = max((row.get("updated_through") or 0 for row in got), default=0)
    entries = []
    for wallet in wallets:
        row = by_owner.get(wallet)
        if row is None:
            entries.append(
                {"wallet": wallet, "absent": "below activity threshold (< 3 priced legs in corpus)"}
            )
        else:
            entries.append(
                {
                    "wallet": wallet,
                    "net_realized_sol": row["net_realized_sol"],
                    "win_rate": row["win_rate"],
                    "n_coins_closed": row["n_coins_closed"],
                    "rp_mode": row["rp_mode"],
                    "guild": row["guild"],
                }
            )
    return {
        "as_of": datetime.fromtimestamp(as_of, UTC).strftime("%Y-%m-%d") if as_of else None,
        "stale": True,
        "note": WALLET_LAYER_NOTE,
        "entries": entries,
    }


# -- assembly --------------------------------------------------------------------------


def build_facts(
    day: str,
    scores_dir: Path,
    archive_db: Path,
    wallet_parquet: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict:
    rows = load_scores(scores_dir, day)
    callouts = callout_facts(archive_db, day)
    caller_wallets = [c["wallet"] for c in callouts.get("top_callers", [])]
    return {
        "day": day,
        "screen": screen_facts(rows, day),
        "callouts": callouts,
        "archive": archive_facts(archive_db, day, manifest_dir),
        "caller_color": caller_color(wallet_parquet, caller_wallets),
    }
