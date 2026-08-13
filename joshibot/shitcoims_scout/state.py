from __future__ import annotations

import fcntl
import json
import os
import secrets
import sqlite3
import stat
import time
from dataclasses import dataclass
from pathlib import Path


class ScoutStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutboxItem:
    id: int
    method: str
    payload: dict
    attempts: int


@dataclass(frozen=True)
class Callback:
    action: str
    parameters: dict


class ScoutState:
    """Single-process durable Telegram cursor, outbox, and capability store."""

    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = path
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ScoutStateError("Scout state path must be a regular file, not a symlink")
            if metadata.st_uid != os.getuid():
                raise ScoutStateError("Scout state file must be owned by the current user")
        else:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(descriptor)
        os.chmod(path, 0o600)
        lock_path = path.with_suffix(path.suffix + ".lock")
        self._lock_descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(self._lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lock_descriptor)
            raise ScoutStateError(
                "another shitcoims Scout process already owns the Telegram consumer state"
            ) from None
        self.connection = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key TEXT NOT NULL UNIQUE,
                method TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                last_error_type TEXT
            );
            CREATE TABLE IF NOT EXISTS callbacks (
                handle TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                expires_at REAL NOT NULL,
                consumed_at REAL
            );
            """
        )
        self.connection.commit()

    @property
    def last_update_id(self) -> int | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = 'last_update_id'").fetchone()
        return int(row["value"]) if row else None

    def advance_cursor(self, update_id: int) -> None:
        current = self.last_update_id
        if current is not None and update_id <= current:
            return
        with self.connection:
            self.connection.execute(
                "INSERT INTO metadata(key, value) VALUES('last_update_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(update_id),),
            )

    def enqueue(self, dedup_key: str, method: str, payload: dict) -> None:
        if method not in {"sendMessage"}:
            raise ValueError("unsupported durable Telegram method")
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO outbox"
                "(dedup_key, method, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (dedup_key, method, json.dumps(payload, separators=(",", ":")), time.time()),
            )

    def pending(self, *, now: float | None = None, limit: int = 20) -> list[OutboxItem]:
        observed = time.time() if now is None else now
        rows = self.connection.execute(
            "SELECT id, method, payload_json, attempts FROM outbox "
            "WHERE next_attempt_at <= ? ORDER BY id LIMIT ?",
            (observed, limit),
        ).fetchall()
        return [
            OutboxItem(row["id"], row["method"], json.loads(row["payload_json"]), row["attempts"])
            for row in rows
        ]

    def delivered(self, item_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM outbox WHERE id = ?", (item_id,))

    def delivery_failed(self, item_id: int, error_type: str, attempts: int) -> None:
        delay = min(300, 2 ** min(attempts, 8))
        with self.connection:
            self.connection.execute(
                "UPDATE outbox SET attempts = ?, next_attempt_at = ?, last_error_type = ? WHERE id = ?",
                (attempts, time.time() + delay, error_type[:80], item_id),
            )

    def create_callback(
        self,
        action: str,
        parameters: dict,
        *,
        ttl_seconds: int = 900,
        now: float | None = None,
    ) -> str:
        if action not in {
            "refresh",
            "evidence",
            "page",
            "desk",
            "bag",
            "protect",
            "skip",
            "sl",
            "tp",
            "trail",
            "rug",
            "delete",
            "candidates",
        }:
            raise ValueError("unsupported callback action")
        observed = time.time() if now is None else now
        self.purge_callbacks(now=observed)
        for _ in range(3):
            handle = secrets.token_urlsafe(18)
            try:
                with self.connection:
                    self.connection.execute(
                        "INSERT INTO callbacks"
                        "(handle, action, parameters_json, expires_at) VALUES (?, ?, ?, ?)",
                        (
                            handle,
                            action,
                            json.dumps(parameters, separators=(",", ":")),
                            observed + ttl_seconds,
                        ),
                    )
                return handle
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("could not allocate callback handle")

    def consume_callback(self, handle: str, *, now: float | None = None) -> Callback | None:
        observed = time.time() if now is None else now
        with self.connection:
            row = self.connection.execute(
                "SELECT action, parameters_json, expires_at, consumed_at FROM callbacks WHERE handle = ?",
                (handle,),
            ).fetchone()
            if row is None or row["consumed_at"] is not None or row["expires_at"] < observed:
                return None
            changed = self.connection.execute(
                "UPDATE callbacks SET consumed_at = ? WHERE handle = ? AND consumed_at IS NULL",
                (observed, handle),
            ).rowcount
        if changed != 1:
            return None
        return Callback(row["action"], json.loads(row["parameters_json"]))

    def purge_callbacks(self, *, now: float | None = None) -> None:
        observed = time.time() if now is None else now
        with self.connection:
            self.connection.execute(
                "DELETE FROM callbacks WHERE expires_at < ? OR (consumed_at IS NOT NULL AND consumed_at < ?)",
                (observed, observed - 3600),
            )

    def close(self) -> None:
        self.connection.close()
        fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
        os.close(self._lock_descriptor)
