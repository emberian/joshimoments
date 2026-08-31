"""The approvals outbox: how other dregg services ask Ember for a yes/no.

THE CONTRACT (wire drafts, removal verdicts, and future lanes build against this):

    CREATE TABLE IF NOT EXISTS approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,             -- which service asked, e.g. 'wire', 'verdict'
        kind TEXT NOT NULL,               -- request type within that service
        summary TEXT NOT NULL,            -- human text the bot renders to the operator DM
        payload_json TEXT NOT NULL DEFAULT '{}',  -- opaque callback payload, returned unchanged
        created_at REAL NOT NULL,         -- unix seconds
        presented_at REAL,                -- set by the bot when the buttons were enqueued
        decided_at REAL,                  -- set by the bot when the operator pressed a button
        decision TEXT CHECK (decision IN ('approve', 'reject')),
        decided_by TEXT                   -- operator chat id that decided
    );

Lifecycle: a service INSERTs (source, kind, summary, payload_json, created_at) and
remembers the rowid. The gate bot polls for undecided, unpresented rows, DMs the
operator a message with inline approve/reject buttons, and stamps presented_at.
When the operator presses a button the bot stamps decided_at/decision/decided_by.
The service polls its rowid until decided_at is set, then acts on `decision` and
its own payload. Rows are never deleted by the bot; history is the audit trail.

The table lives in the gate's own sqlite (config `paths.db`, deployed default
`state/dregg_gate/gate.sqlite`). The db is WAL with a busy timeout, so concurrent
writers from other processes are safe; the gate's exclusive flock guards the
TELEGRAM POLLER identity only, not the database.

Use the helpers below rather than raw SQL so the DDL stays in one place.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

APPROVALS_DDL = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    presented_at REAL,
    decided_at REAL,
    decision TEXT CHECK (decision IN ('approve', 'reject')),
    decided_by TEXT
);
"""


@dataclass(frozen=True, slots=True)
class Decision:
    id: int
    source: str
    kind: str
    decision: str
    decided_at: float
    payload: dict


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(APPROVALS_DDL)
    return connection


def enqueue_approval(
    db_path: Path,
    source: str,
    kind: str,
    summary: str,
    payload: dict | None = None,
    *,
    now: float | None = None,
) -> int:
    """INSERT one approval request; returns the row id the service must remember."""

    if not source or not kind or not summary:
        raise ValueError("source, kind, and summary are all required")
    connection = _connect(db_path)
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO approvals (source, kind, summary, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    source,
                    kind,
                    summary[:3500],
                    json.dumps(payload or {}, separators=(",", ":")),
                    time.time() if now is None else now,
                ),
            )
        row_id = cursor.lastrowid
        assert row_id is not None
        return row_id
    finally:
        connection.close()


def read_decision(db_path: Path, approval_id: int) -> Decision | None:
    """The service's poll: None until the operator has decided."""

    connection = _connect(db_path)
    try:
        row = connection.execute(
            "SELECT id, source, kind, decision, decided_at, payload_json "
            "FROM approvals WHERE id = ? AND decided_at IS NOT NULL",
            (approval_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return Decision(
        id=row["id"],
        source=row["source"],
        kind=row["kind"],
        decision=row["decision"],
        decided_at=row["decided_at"],
        payload=json.loads(row["payload_json"]),
    )
