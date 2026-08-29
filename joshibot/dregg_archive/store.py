"""The archive's memory: raw bytes first, everything else derived.

TWO LAYERS, AND THE DIRECTION BETWEEN THEM IS THE WHOLE DESIGN
--------------------------------------------------------------
The raw layer (`fetches`) holds the EXACT BYTES of every HTTP response this service ever
received — 200s, 404s, 429s, garbage — zstd-compressed, sha256'd, with two clocks
(t_request, t_response). The derived layer (`callouts`, `sightings`, `fetch_windows`,
`removal_verdicts`, `outcomes`, `callers`) is computed FROM those bytes and never from
anything else. That direction is what makes the archive an instrument rather than a
belief: any derived row can be re-derived, any dispute about what the provider served on
a given day is settled by decompressing the body and checking its hash against the daily
manifest, and a parser bug found in month three costs a re-derivation, not the data.

The disciplines here are the joshi keeper's, not its code: exact-bytes retention, hard
budgets with a durable stop, absence recorded as a fact (`notes`, `fetch_windows` with
NULL bounds for an empty listing) rather than as silence.

WRITE MODEL
-----------
One process, one connection, WAL. Every method that writes commits before returning, so a
kill -9 between cycles loses nothing that was reported as recorded — this matters most for
`budget`, where an uncounted request is a hole in a hard ceiling.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import zstandard

METHOD_VERSION = "v1"

MS_HOUR = 3_600_000
MS_DAY = 86_400_000


class BudgetExhausted(RuntimeError):
    """The daily request ceiling is spent. Raised BEFORE a request, never after."""

    def __init__(self, day: str, spent: int, ceiling: int):
        super().__init__(f"budget for {day}: {spent} spent >= ceiling {ceiling}")
        self.day = day
        self.spent = spent
        self.ceiling = ceiling


def utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


def day_start_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def day_end_ms(day: str) -> int:
    """Exclusive end: first millisecond of the NEXT day."""

    return day_start_ms(day) + MS_DAY


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS fetches(
  id             INTEGER PRIMARY KEY,
  route          TEXT NOT NULL,
  url            TEXT NOT NULL,
  t_request_ms   INTEGER NOT NULL,
  t_response_ms  INTEGER NOT NULL,
  status         INTEGER NOT NULL,
  sha256         TEXT NOT NULL,
  body_zst       BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetches_t ON fetches(t_response_ms);
CREATE INDEX IF NOT EXISTS idx_fetches_route ON fetches(route, t_response_ms);

-- The deletion instrument. scope is the mint for per-mint surfaces and NULL for the
-- global firehose; without it a per-mint listing's window would falsely "span" every
-- other coin's callouts. NULL bounds mean the listing returned no rows — recorded, so an
-- empty answer stays distinguishable from an unasked question.
CREATE TABLE IF NOT EXISTS fetch_windows(
  fetch_id        INTEGER PRIMARY KEY REFERENCES fetches(id),
  route           TEXT NOT NULL,
  scope           TEXT,
  t_oldest_row_ms INTEGER,
  t_newest_row_ms INTEGER,
  row_count       INTEGER NOT NULL,
  truncated       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_windows_route ON fetch_windows(route, scope);

CREATE TABLE IF NOT EXISTS callouts(
  callout_id            TEXT PRIMARY KEY,
  wallet                TEXT NOT NULL,
  mint                  TEXT NOT NULL,
  t_event_ms            INTEGER,
  thesis                TEXT,
  callout_price_first   REAL,
  market_cap_first      REAL,
  first_seen_fetch      INTEGER NOT NULL,
  last_seen_fetch       INTEGER NOT NULL,
  n_sightings           INTEGER NOT NULL DEFAULT 1,
  provider_multiple_last REAL,
  provider_peak_t_last  INTEGER,
  username_last         TEXT,
  x_username_last       TEXT
);
CREATE INDEX IF NOT EXISTS idx_callouts_t ON callouts(t_event_ms);
CREATE INDEX IF NOT EXISTS idx_callouts_mint ON callouts(mint);
CREATE INDEX IF NOT EXISTS idx_callouts_wallet ON callouts(wallet);

CREATE TABLE IF NOT EXISTS sightings(
  callout_id TEXT NOT NULL,
  fetch_id   INTEGER NOT NULL,
  route      TEXT NOT NULL,
  PRIMARY KEY (callout_id, fetch_id)
);
CREATE INDEX IF NOT EXISTS idx_sightings_fetch ON sightings(fetch_id);

CREATE TABLE IF NOT EXISTS removal_verdicts(
  callout_id        TEXT PRIMARY KEY,
  t_verdict_ms      INTEGER NOT NULL,
  verdict           TEXT NOT NULL,          -- 'removed' | 'unknown-absent'
  evidence_fetch_ids TEXT NOT NULL,         -- JSON array of fetch ids
  published         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS outcomes(
  callout_id         TEXT NOT NULL,
  method_version     TEXT NOT NULL,
  ret_1h             REAL,
  ret_24h            REAL,
  ret_7d             REAL,
  max_close_multiple REAL,
  max_drawdown       REAL,
  dead_flag          INTEGER,               -- NULL until the +7d gate has passed
  computed_ms        INTEGER NOT NULL,
  PRIMARY KEY (callout_id, method_version)
);

CREATE TABLE IF NOT EXISTS callers(
  wallet           TEXT PRIMARY KEY,
  username_last    TEXT,
  x_username_last  TEXT,
  first_seen_ms    INTEGER,
  last_seen_ms     INTEGER,
  stats_fetched_ms INTEGER                  -- rotation bookkeeping for the stats sweep
);

CREATE TABLE IF NOT EXISTS due_work(
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL,
  key           TEXT NOT NULL,              -- mint or wallet
  due_ms        INTEGER NOT NULL,
  dedupe        TEXT NOT NULL UNIQUE,
  attempts      INTEGER NOT NULL DEFAULT 0,
  done_ms       INTEGER,
  done_fetch_id INTEGER,
  note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_due_pending ON due_work(due_ms) WHERE done_ms IS NULL;

CREATE TABLE IF NOT EXISTS budget(
  day     TEXT PRIMARY KEY,
  spent   INTEGER NOT NULL DEFAULT 0,
  stopped INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

-- Absence-as-record: gaps, budget stops, cleared verdicts, config kept-last-good.
CREATE TABLE IF NOT EXISTS notes(
  t_ms   INTEGER NOT NULL,
  kind   TEXT NOT NULL,
  detail TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        self.db.commit()
        self._compress = zstandard.ZstdCompressor(level=6).compress
        self._decompress = zstandard.ZstdDecompressor().decompress

    def close(self) -> None:
        self.db.close()

    # -- raw layer -------------------------------------------------------------

    def record_fetch(
        self, *, route: str, url: str, t_request_ms: int, t_response_ms: int, status: int, body: bytes
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO fetches(route, url, t_request_ms, t_response_ms, status, sha256, body_zst)"
            " VALUES(?,?,?,?,?,?,?)",
            (route, url, t_request_ms, t_response_ms, status,
             hashlib.sha256(body).hexdigest(), self._compress(body)),
        )
        self.db.commit()
        return int(cur.lastrowid or 0)

    def fetch_body(self, fetch_id: int) -> bytes:
        row = self.db.execute("SELECT body_zst FROM fetches WHERE id=?", (fetch_id,)).fetchone()
        if row is None:
            raise KeyError(f"no fetch {fetch_id}")
        return self._decompress(row[0])

    def decompress(self, body_zst: bytes) -> bytes:
        return self._decompress(body_zst)

    def fetch_row(self, fetch_id: int) -> sqlite3.Row | tuple:
        row = self.db.execute(
            "SELECT id, route, url, t_request_ms, t_response_ms, status, sha256 FROM fetches WHERE id=?",
            (fetch_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no fetch {fetch_id}")
        return row

    def record_window(
        self,
        fetch_id: int,
        *,
        route: str,
        scope: str | None,
        t_oldest_row_ms: int | None,
        t_newest_row_ms: int | None,
        row_count: int,
        truncated: bool,
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO fetch_windows(fetch_id, route, scope, t_oldest_row_ms,"
            " t_newest_row_ms, row_count, truncated) VALUES(?,?,?,?,?,?,?)",
            (fetch_id, route, scope, t_oldest_row_ms, t_newest_row_ms, row_count, int(truncated)),
        )
        self.db.commit()

    # -- derived: callouts and sightings ----------------------------------------

    def record_sighting(self, callout_id: str, fetch_id: int, route: str) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO sightings(callout_id, fetch_id, route) VALUES(?,?,?)",
            (callout_id, fetch_id, route),
        )
        self.db.commit()
        return cur.rowcount > 0

    def upsert_callout(
        self,
        *,
        callout_id: str,
        wallet: str,
        mint: str,
        t_event_ms: int | None,
        thesis: str | None,
        callout_price: float | None,
        market_cap: float | None,
        fetch_id: int,
        provider_multiple: float | None,
        provider_peak_t_ms: int | None,
        username: str | None,
        x_username: str | None,
    ) -> bool:
        """One sighting's worth of update. Returns True when the callout is NEW.

        `*_first` fields are set once and never overwritten — they are the record of the
        bar the call was made at, as first witnessed. `*_last` fields track the most
        recent NON-NULL observation: the firehose serves `username: null` on every row
        while `callout_top` serves real names, and "last observed value" that lets a null
        erase a name would be the feed's shape deciding our record.
        """

        cur = self.db.execute(
            """
            INSERT INTO callouts(callout_id, wallet, mint, t_event_ms, thesis,
                                 callout_price_first, market_cap_first,
                                 first_seen_fetch, last_seen_fetch, n_sightings,
                                 provider_multiple_last, provider_peak_t_last,
                                 username_last, x_username_last)
            VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?)
            ON CONFLICT(callout_id) DO UPDATE SET
              last_seen_fetch = excluded.last_seen_fetch,
              n_sightings = n_sightings + 1,
              t_event_ms = COALESCE(callouts.t_event_ms, excluded.t_event_ms),
              provider_multiple_last = COALESCE(excluded.provider_multiple_last, provider_multiple_last),
              provider_peak_t_last = COALESCE(excluded.provider_peak_t_last, provider_peak_t_last),
              username_last = COALESCE(excluded.username_last, username_last),
              x_username_last = COALESCE(excluded.x_username_last, x_username_last)
            """,
            (callout_id, wallet, mint, t_event_ms, thesis, callout_price, market_cap,
             fetch_id, fetch_id, provider_multiple, provider_peak_t_ms, username, x_username),
        )
        del cur  # lastrowid is unreliable across the upsert's two arms; count sightings instead
        new = self.db.execute(
            "SELECT n_sightings FROM callouts WHERE callout_id=?", (callout_id,)
        ).fetchone()[0] == 1
        self.db.commit()
        return bool(new)

    def upsert_caller(
        self,
        *,
        wallet: str,
        username: str | None,
        x_username: str | None,
        seen_ms: int | None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO callers(wallet, username_last, x_username_last, first_seen_ms, last_seen_ms)
            VALUES(?,?,?,?,?)
            ON CONFLICT(wallet) DO UPDATE SET
              username_last = COALESCE(excluded.username_last, username_last),
              x_username_last = COALESCE(excluded.x_username_last, x_username_last),
              first_seen_ms = MIN(COALESCE(callers.first_seen_ms, excluded.first_seen_ms),
                                  COALESCE(excluded.first_seen_ms, callers.first_seen_ms)),
              last_seen_ms = MAX(COALESCE(callers.last_seen_ms, excluded.last_seen_ms),
                                 COALESCE(excluded.last_seen_ms, callers.last_seen_ms))
            """,
            (wallet, username, x_username, seen_ms, seen_ms),
        )
        self.db.commit()

    def mark_caller_stats_fetched(self, wallet: str, t_ms: int) -> None:
        self.db.execute("UPDATE callers SET stats_fetched_ms=? WHERE wallet=?", (t_ms, wallet))
        self.db.commit()

    def active_mints(self, *, since_ms: int, limit: int) -> list[str]:
        """Mints with the freshest callout activity — the fallback lane's frontier."""

        rows = self.db.execute(
            "SELECT mint, MAX(t_event_ms) AS newest FROM callouts"
            " WHERE t_event_ms IS NOT NULL GROUP BY mint"
            " HAVING newest >= ? ORDER BY newest DESC LIMIT ?",
            (since_ms, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def callers_for_stats(self, *, active_since_ms: int, limit: int) -> list[str]:
        """Stalest-first rotation over callers seen recently enough to still matter."""

        rows = self.db.execute(
            "SELECT wallet FROM callers WHERE last_seen_ms >= ?"
            " ORDER BY stats_fetched_ms IS NOT NULL, stats_fetched_ms ASC LIMIT ?",
            (active_since_ms, limit),
        ).fetchall()
        return [r[0] for r in rows]

    # -- budget ------------------------------------------------------------------

    def budget_spend(self, day: str, n: int = 1) -> int:
        self.db.execute(
            "INSERT INTO budget(day, spent) VALUES(?,?)"
            " ON CONFLICT(day) DO UPDATE SET spent = spent + excluded.spent",
            (day, n),
        )
        self.db.commit()
        return self.budget(day)[0]

    def budget(self, day: str) -> tuple[int, bool]:
        row = self.db.execute("SELECT spent, stopped FROM budget WHERE day=?", (day,)).fetchone()
        return (0, False) if row is None else (int(row[0]), bool(row[1]))

    def budget_stop(self, day: str) -> None:
        self.db.execute(
            "INSERT INTO budget(day, spent, stopped) VALUES(?,0,1)"
            " ON CONFLICT(day) DO UPDATE SET stopped=1",
            (day,),
        )
        self.db.commit()

    def budget_guard(self, now_ms: int, ceiling: int) -> None:
        """Raise BudgetExhausted — and durably mark the stop — once the ceiling is spent.

        Called BEFORE every logical request. The transport recorder counts every attempt
        (retries included), so a burst of 429 retries can overshoot the ceiling by at most
        one retry chain; the next guard call is what halts the machine, and the stop
        survives a restart because it lives in the budget table, not in memory.
        """

        day = utc_day(now_ms)
        spent, stopped = self.budget(day)
        if spent >= ceiling:
            if not stopped:
                self.budget_stop(day)
                self.note(now_ms, "budget_stop", f"day {day}: {spent} requests >= ceiling {ceiling}")
            raise BudgetExhausted(day, spent, ceiling)

    # -- due work ------------------------------------------------------------------

    def enqueue(self, *, kind: str, key: str, due_ms: int, dedupe: str) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO due_work(kind, key, due_ms, dedupe) VALUES(?,?,?,?)",
            (kind, key, due_ms, dedupe),
        )
        self.db.commit()
        return cur.rowcount > 0

    def due_items(self, now_ms: int, limit: int) -> list[tuple[int, str, str, int]]:
        rows = self.db.execute(
            "SELECT id, kind, key, attempts FROM due_work"
            " WHERE done_ms IS NULL AND due_ms <= ? ORDER BY due_ms LIMIT ?",
            (now_ms, limit),
        ).fetchall()
        return [(int(r[0]), r[1], r[2], int(r[3])) for r in rows]

    def mark_done(self, item_id: int, *, done_ms: int, fetch_id: int | None, note: str | None = None) -> None:
        self.db.execute(
            "UPDATE due_work SET done_ms=?, done_fetch_id=?, note=? WHERE id=?",
            (done_ms, fetch_id, note, item_id),
        )
        self.db.commit()

    def defer(self, item_id: int, *, until_ms: int, note: str) -> None:
        self.db.execute(
            "UPDATE due_work SET due_ms=?, attempts=attempts+1, note=? WHERE id=?",
            (until_ms, note, item_id),
        )
        self.db.commit()

    def enqueued_today(self, kind: str, day: str) -> int:
        """How many of `kind` were enqueued for `day` (dedupe carries the day)."""

        row = self.db.execute(
            "SELECT COUNT(*) FROM due_work WHERE kind=? AND dedupe LIKE ?",
            (kind, f"{kind}:{day}:%"),
        ).fetchone()
        return int(row[0])

    # -- verdicts ------------------------------------------------------------------

    def upsert_verdict(
        self, *, callout_id: str, t_verdict_ms: int, verdict: str, evidence_fetch_ids: list[int]
    ) -> None:
        self.db.execute(
            "INSERT INTO removal_verdicts(callout_id, t_verdict_ms, verdict, evidence_fetch_ids)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(callout_id) DO UPDATE SET"
            "   t_verdict_ms=excluded.t_verdict_ms, verdict=excluded.verdict,"
            "   evidence_fetch_ids=excluded.evidence_fetch_ids",
            (callout_id, t_verdict_ms, verdict, json.dumps(sorted(evidence_fetch_ids))),
        )
        self.db.commit()

    def clear_verdict(self, callout_id: str) -> bool:
        cur = self.db.execute("DELETE FROM removal_verdicts WHERE callout_id=?", (callout_id,))
        self.db.commit()
        return cur.rowcount > 0

    def verdicts(self, *, verdict: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT v.callout_id, v.t_verdict_ms, v.verdict, v.evidence_fetch_ids, v.published,"
            " c.mint, c.wallet, c.t_event_ms"
            " FROM removal_verdicts v JOIN callouts c ON c.callout_id = v.callout_id"
        )
        args: tuple = ()
        if verdict is not None:
            sql += " WHERE v.verdict=?"
            args = (verdict,)
        return [
            {
                "callout_id": r[0], "t_verdict_ms": r[1], "verdict": r[2],
                "evidence_fetch_ids": json.loads(r[3]), "published": bool(r[4]),
                "mint": r[5], "wallet": r[6], "t_event_ms": r[7],
            }
            for r in self.db.execute(sql + " ORDER BY v.t_verdict_ms", args).fetchall()
        ]

    # -- outcomes ------------------------------------------------------------------

    def upsert_outcome(
        self,
        *,
        callout_id: str,
        ret_1h: float | None,
        ret_24h: float | None,
        ret_7d: float | None,
        max_close_multiple: float | None,
        max_drawdown: float | None,
        dead_flag: bool | None,
        computed_ms: int,
        method_version: str = METHOD_VERSION,
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO outcomes(callout_id, method_version, ret_1h, ret_24h, ret_7d,"
            " max_close_multiple, max_drawdown, dead_flag, computed_ms) VALUES(?,?,?,?,?,?,?,?,?)",
            (callout_id, method_version, ret_1h, ret_24h, ret_7d, max_close_multiple, max_drawdown,
             None if dead_flag is None else int(dead_flag), computed_ms),
        )
        self.db.commit()

    # -- meta / notes ----------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else row[0]

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))
        self.db.commit()

    def hwm_ms(self) -> int | None:
        raw = self.get_meta("hwm_ms")
        return int(raw) if raw else None

    def set_hwm_ms(self, value: int) -> None:
        self.set_meta("hwm_ms", str(value))

    def note(self, t_ms: int, kind: str, detail: str) -> None:
        self.db.execute("INSERT INTO notes(t_ms, kind, detail) VALUES(?,?,?)", (t_ms, kind, detail))
        self.db.commit()

    # -- reporting -------------------------------------------------------------------

    def counts(self) -> dict[str, Any]:
        one = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]  # noqa: E731
        return {
            "fetches": one("SELECT COUNT(*) FROM fetches"),
            "fetch_zst_bytes": one("SELECT COALESCE(SUM(LENGTH(body_zst)),0) FROM fetches"),
            "callouts": one("SELECT COUNT(*) FROM callouts"),
            "sightings": one("SELECT COUNT(*) FROM sightings"),
            "callers": one("SELECT COUNT(*) FROM callers"),
            "verdicts_removed": one("SELECT COUNT(*) FROM removal_verdicts WHERE verdict='removed'"),
            "verdicts_unknown_absent":
                one("SELECT COUNT(*) FROM removal_verdicts WHERE verdict='unknown-absent'"),
            "outcomes": one("SELECT COUNT(*) FROM outcomes"),
            "outcomes_complete": one("SELECT COUNT(*) FROM outcomes WHERE dead_flag IS NOT NULL"),
            "due_pending": one("SELECT COUNT(*) FROM due_work WHERE done_ms IS NULL"),
        }
