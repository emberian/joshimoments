"""Durable watch state: subscriptions, per-(sub, event) sent claims, digest queue, cursors.

Its OWN sqlite file — the brief's call, and the right one: the gate db's flock guards
the Telegram poller identity, and this file has TWO writers by design (the gateway's
command lane inserts/deletes subscriptions; the watch service claims events, queues
digests, advances cursors). WAL + busy timeout, no flock, same as every other
multi-writer dregg store.

THE DEDUP CONTRACT (why `sent` exists at all): the gate outbox's dedup_key already
refuses a duplicate INSERT — but outbox rows are DELETED after delivery, so a replayed
event after delivery would re-insert and double-send. `sent` is the durable record on
OUR side: a (sub_id, event_key) row is claimed BEFORE the outbox insert, so a restart
that replays events (cursors advance only after a cycle completes) re-claims, fails,
and sends nothing twice. The cost of that ordering is the mirror failure: a crash in
the instant between the claim commit and the outbox commit loses that one DM. For an
alerting feature, a rare lost alert beats a rare duplicate — the duplicate is what
gets the bot muted.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

KINDS = ("coin", "deployer", "crew", "caller", "clean")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_user_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('coin','deployer','crew','caller','clean')),
  spec TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'event' CHECK (mode IN ('event','digest')),
  created_at REAL NOT NULL,
  UNIQUE (tg_user_id, kind, spec)
);
CREATE INDEX IF NOT EXISTS subs_kind ON subscriptions (kind, spec);

CREATE TABLE IF NOT EXISTS sent (
  sub_id INTEGER NOT NULL,
  event_key TEXT NOT NULL,
  sent_at REAL NOT NULL,
  PRIMARY KEY (sub_id, event_key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS digest_pending (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id INTEGER NOT NULL,
  tg_user_id INTEGER NOT NULL,
  line TEXT NOT NULL,
  queued_at REAL NOT NULL,
  flush_stamp INTEGER
);
CREATE INDEX IF NOT EXISTS pending_user ON digest_pending (tg_user_id, flush_stamp);

CREATE TABLE IF NOT EXISTS dm_log (
  tg_user_id INTEGER NOT NULL,
  sent_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dm_log_user_t ON dm_log (tg_user_id, sent_at);

CREATE TABLE IF NOT EXISTS cursors (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class Subscription:
    id: int
    tg_user_id: int
    kind: str
    spec: str
    mode: str  # 'event' | 'digest'
    created_at: float


class WatchState:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- subscriptions (the gateway's command lane writes here) ---------------------

    def add(self, tg_user_id: int, kind: str, spec: str, mode: str, now: float) -> tuple[int, bool]:
        """Insert if new; returns (sub id, created?). Duplicate (user, kind, spec) is
        answered with the EXISTING id so the command lane can say 'already watching (#N)'."""

        if kind not in KINDS:
            raise ValueError(f"unknown watch kind {kind!r}")
        if mode not in ("event", "digest"):
            raise ValueError(f"unknown watch mode {mode!r}")
        # Check-then-insert instead of INSERT OR IGNORE: an ignored insert still burns
        # an AUTOINCREMENT id, and gap-riddled watch numbers read as missing watches.
        # Only the gateway process writes subscriptions, so the check cannot race.
        existing = self.db.execute(
            "SELECT id FROM subscriptions WHERE tg_user_id = ? AND kind = ? AND spec = ?",
            (tg_user_id, kind, spec),
        ).fetchone()
        if existing is not None:
            return int(existing["id"]), False
        with self.db:
            cur = self.db.execute(
                "INSERT INTO subscriptions (tg_user_id, kind, spec, mode, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (tg_user_id, kind, spec, mode, now),
            )
        return int(cur.lastrowid or 0), True

    def remove(self, tg_user_id: int, sub_id: int) -> bool:
        """Ownership-checked delete; a stranger's id removes nothing. Pending digest
        lines for the sub go with it — an unwatched watch must fall silent whole."""

        with self.db:
            cur = self.db.execute(
                "DELETE FROM subscriptions WHERE id = ? AND tg_user_id = ?",
                (sub_id, tg_user_id),
            )
            removed = cur.rowcount > 0
            if removed:
                self.db.execute("DELETE FROM digest_pending WHERE sub_id = ?", (sub_id,))
        return removed

    def subs_for_user(self, tg_user_id: int) -> list[Subscription]:
        rows = self.db.execute(
            "SELECT * FROM subscriptions WHERE tg_user_id = ? ORDER BY id", (tg_user_id,)
        ).fetchall()
        return [self._sub(row) for row in rows]

    def count_for_user(self, tg_user_id: int) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE tg_user_id = ?", (tg_user_id,)
        ).fetchone()
        return int(row["n"])

    def all_subs(self) -> list[Subscription]:
        rows = self.db.execute("SELECT * FROM subscriptions ORDER BY id").fetchall()
        return [self._sub(row) for row in rows]

    @staticmethod
    def _sub(row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=row["id"], tg_user_id=row["tg_user_id"], kind=row["kind"],
            spec=row["spec"], mode=row["mode"], created_at=row["created_at"],
        )

    # -- sent claims (the dedup contract) -------------------------------------------

    def claim(self, sub_id: int, event_key: str, now: float) -> bool:
        """True exactly once per (sub, event) — see the module docstring."""

        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO sent (sub_id, event_key, sent_at) VALUES (?, ?, ?)",
                (sub_id, event_key, now),
            )
        return cur.rowcount > 0

    def unclaim(self, sub_id: int, event_key: str) -> None:
        """Best-effort rollback when the outbox INSERT itself raised — so a transient
        gate-db failure retries next cycle instead of eating the alert."""

        with self.db:
            self.db.execute(
                "DELETE FROM sent WHERE sub_id = ? AND event_key = ?", (sub_id, event_key)
            )

    # -- cursors ---------------------------------------------------------------------

    def cursor(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM cursors WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_cursor(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO cursors (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def set_cursors(self, updates: dict[str, str]) -> None:
        if not updates:
            return
        with self.db:
            self.db.executemany(
                "INSERT INTO cursors (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                list(updates.items()),
            )

    def drop_cursors_except(self, prefix: str, keep: set[str]) -> None:
        rows = self.db.execute(
            "SELECT key FROM cursors WHERE key LIKE ?", (prefix + "%",)
        ).fetchall()
        stale = [row["key"] for row in rows if row["key"] not in keep]
        if stale:
            with self.db:
                self.db.executemany("DELETE FROM cursors WHERE key = ?", [(k,) for k in stale])

    # -- digest queue -----------------------------------------------------------------

    def queue_digest(self, sub_id: int, tg_user_id: int, line: str, now: float) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO digest_pending (sub_id, tg_user_id, line, queued_at) "
                "VALUES (?, ?, ?, ?)",
                (sub_id, tg_user_id, line, now),
            )

    def stamp_flush(self, now: float) -> list[tuple[int, int]]:
        """Claim every unstamped pending line, per user, with one durable stamp.
        Returns the (tg_user_id, stamp) pairs claimed. The stamp is the flush's
        identity: the outbox dedup key is derived from it, so a crash between the
        stamp and the outbox insert re-runs the SAME flush (same key) rather than
        minting a duplicate."""

        stamp = int(now * 1000)
        with self.db:
            self.db.execute(
                "UPDATE digest_pending SET flush_stamp = ? WHERE flush_stamp IS NULL", (stamp,)
            )
        rows = self.db.execute(
            "SELECT DISTINCT tg_user_id FROM digest_pending WHERE flush_stamp = ?", (stamp,)
        ).fetchall()
        return [(int(row["tg_user_id"]), stamp) for row in rows]

    def stamped_flushes(self) -> list[tuple[int, int]]:
        """Every (user, stamp) still pending delivery — normally what stamp_flush just
        made; after a crash mid-flush, the recovery set."""

        rows = self.db.execute(
            "SELECT DISTINCT tg_user_id, flush_stamp FROM digest_pending "
            "WHERE flush_stamp IS NOT NULL ORDER BY flush_stamp"
        ).fetchall()
        return [(int(row["tg_user_id"]), int(row["flush_stamp"])) for row in rows]

    def flush_lines(self, tg_user_id: int, stamp: int) -> list[tuple[int, str]]:
        rows = self.db.execute(
            "SELECT sub_id, line FROM digest_pending WHERE tg_user_id = ? AND flush_stamp = ? "
            "ORDER BY id",
            (tg_user_id, stamp),
        ).fetchall()
        return [(int(row["sub_id"]), row["line"]) for row in rows]

    def clear_flush(self, tg_user_id: int, stamp: int) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM digest_pending WHERE tg_user_id = ? AND flush_stamp = ?",
                (tg_user_id, stamp),
            )

    def pending_digest_count(self) -> int:
        row = self.db.execute("SELECT COUNT(*) AS n FROM digest_pending").fetchone()
        return int(row["n"])

    # -- per-user DM accounting (the rate ceiling's durable clock) ---------------------

    def log_dm(self, tg_user_id: int, now: float) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO dm_log (tg_user_id, sent_at) VALUES (?, ?)", (tg_user_id, now)
            )

    def dms_last_hour(self, tg_user_id: int, now: float) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM dm_log WHERE tg_user_id = ? AND sent_at >= ?",
            (tg_user_id, now - 3600.0),
        ).fetchone()
        return int(row["n"])

    # -- pruning ------------------------------------------------------------------------

    def prune(self, now: float | None = None, *, keep_sent_s: float = 14 * 86_400.0,
              keep_dm_log_s: float = 2 * 86_400.0) -> None:
        observed = time.time() if now is None else now
        with self.db:
            self.db.execute("DELETE FROM sent WHERE sent_at < ?", (observed - keep_sent_s,))
            self.db.execute("DELETE FROM dm_log WHERE sent_at < ?", (observed - keep_dm_log_s,))
