"""Durable gate state: Telegram cursor, ordered outbox, challenges, members, approvals.

One sqlite file. The flock guards the TELEGRAM POLLER identity — a second gate (or
any other consumer of this bot token) refuses to start. The database itself is WAL
with a busy timeout precisely so that OTHER processes may INSERT approval requests
(dregg_gate.approvals) while the bot runs.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .approvals import APPROVALS_DDL

OUTBOX_METHODS = {"sendMessage", "banChatMember", "unbanChatMember"}


class GateStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutboxItem:
    id: int
    method: str
    payload: dict
    attempts: int


@dataclass(frozen=True, slots=True)
class Challenge:
    tg_user_id: int
    wallet: str
    nonce: str
    message: str
    issued_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class Member:
    tg_user_id: int
    wallet: str
    verified_at: float
    status: str  # 'ok' | 'grace' | 'ejected'
    grace_until: float | None
    last_checked_at: float | None
    last_balance_raw: int | None


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    id: int
    source: str
    kind: str
    summary: str
    payload: dict
    created_at: float


class GateState:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = path
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise GateStateError("gate state path must be a regular file, not a symlink")
            if metadata.st_uid != os.getuid():
                raise GateStateError("gate state file must be owned by the current user")
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
            raise GateStateError(
                "another process already owns this bot token's getUpdates consumer; refusing to start"
            ) from None
        self.connection = sqlite3.connect(path, timeout=5.0)
        os.chmod(path, 0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=5000")
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
            CREATE TABLE IF NOT EXISTS challenges (
                tg_user_id INTEGER PRIMARY KEY,
                wallet TEXT NOT NULL,
                nonce TEXT NOT NULL,
                message TEXT NOT NULL,
                issued_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS members (
                tg_user_id INTEGER PRIMARY KEY,
                wallet TEXT NOT NULL UNIQUE,
                verified_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'grace', 'ejected')),
                grace_until REAL,
                last_checked_at REAL,
                last_balance_raw TEXT
            );
            """
            + APPROVALS_DDL
        )
        self.connection.commit()

    # -- metadata ------------------------------------------------------------------

    def _get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    @property
    def last_update_id(self) -> int | None:
        value = self._get_meta("last_update_id")
        return int(value) if value is not None else None

    def advance_cursor(self, update_id: int) -> None:
        current = self.last_update_id
        if current is not None and update_id <= current:
            return
        self._set_meta("last_update_id", str(update_id))

    @property
    def group_id(self) -> int | None:
        value = self._get_meta("group_id")
        return int(value) if value is not None else None

    def bind_group(self, chat_id: int) -> None:
        self._set_meta("group_id", str(chat_id))

    @property
    def mint_decimals(self) -> int | None:
        value = self._get_meta("mint_decimals")
        return int(value) if value is not None else None

    def record_mint_decimals(self, decimals: int) -> None:
        known = self.mint_decimals
        if known is not None and known != decimals:
            raise GateStateError(f"on-chain mint decimals changed ({known} -> {decimals}); refusing")
        self._set_meta("mint_decimals", str(decimals))

    def day_marker(self, key: str) -> str | None:
        return self._get_meta(key)

    def set_day_marker(self, key: str, day: str) -> None:
        self._set_meta(key, day)

    # -- outbox --------------------------------------------------------------------

    def enqueue(self, dedup_key: str, method: str, payload: dict) -> None:
        if method not in OUTBOX_METHODS:
            raise ValueError("unsupported durable Telegram method")
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO outbox (dedup_key, method, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
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

    # -- challenges ----------------------------------------------------------------

    def put_challenge(self, challenge: Challenge) -> None:
        """One live challenge per user; a new /verify replaces the old one."""

        with self.connection:
            self.connection.execute(
                "INSERT INTO challenges (tg_user_id, wallet, nonce, message, issued_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(tg_user_id) DO UPDATE SET "
                "wallet = excluded.wallet, nonce = excluded.nonce, message = excluded.message, "
                "issued_at = excluded.issued_at, expires_at = excluded.expires_at",
                (
                    challenge.tg_user_id,
                    challenge.wallet,
                    challenge.nonce,
                    challenge.message,
                    challenge.issued_at,
                    challenge.expires_at,
                ),
            )

    def get_challenge(self, tg_user_id: int, *, now: float | None = None) -> Challenge | None:
        """Returns the live challenge, deleting it if expired (expiry is single-shot)."""

        observed = time.time() if now is None else now
        row = self.connection.execute(
            "SELECT tg_user_id, wallet, nonce, message, issued_at, expires_at "
            "FROM challenges WHERE tg_user_id = ?",
            (tg_user_id,),
        ).fetchone()
        if row is None:
            return None
        challenge = Challenge(
            row["tg_user_id"], row["wallet"], row["nonce"], row["message"],
            row["issued_at"], row["expires_at"],
        )
        if challenge.expires_at < observed:
            self.consume_challenge(tg_user_id)
            return None
        return challenge

    def consume_challenge(self, tg_user_id: int) -> None:
        """Single-use: the nonce can never grant (or be replayed) again."""

        with self.connection:
            self.connection.execute("DELETE FROM challenges WHERE tg_user_id = ?", (tg_user_id,))

    # -- members (tg_user_id <-> wallet, 1:1 both ways) ----------------------------

    def member(self, tg_user_id: int) -> Member | None:
        row = self.connection.execute(
            "SELECT * FROM members WHERE tg_user_id = ?", (tg_user_id,)
        ).fetchone()
        return self._member_row(row)

    def member_by_wallet(self, wallet: str) -> Member | None:
        row = self.connection.execute("SELECT * FROM members WHERE wallet = ?", (wallet,)).fetchone()
        return self._member_row(row)

    def members(self) -> list[Member]:
        rows = self.connection.execute("SELECT * FROM members ORDER BY tg_user_id").fetchall()
        result = []
        for row in rows:
            member = self._member_row(row)
            assert member is not None
            result.append(member)
        return result

    @staticmethod
    def _member_row(row: sqlite3.Row | None) -> Member | None:
        if row is None:
            return None
        raw = row["last_balance_raw"]
        return Member(
            tg_user_id=row["tg_user_id"],
            wallet=row["wallet"],
            verified_at=row["verified_at"],
            status=row["status"],
            grace_until=row["grace_until"],
            last_checked_at=row["last_checked_at"],
            last_balance_raw=int(raw) if raw is not None else None,
        )

    def record_verification(self, tg_user_id: int, wallet: str, balance_raw: int, now: float) -> None:
        """Bind (or re-bind) this tg user to this wallet. 1:1 is enforced by the caller
        checking member_by_wallet first and by the UNIQUE constraint as the backstop."""

        with self.connection:
            self.connection.execute(
                "INSERT INTO members (tg_user_id, wallet, verified_at, status, grace_until, "
                "last_checked_at, last_balance_raw) VALUES (?, ?, ?, 'ok', NULL, ?, ?) "
                "ON CONFLICT(tg_user_id) DO UPDATE SET wallet = excluded.wallet, "
                "verified_at = excluded.verified_at, status = 'ok', grace_until = NULL, "
                "last_checked_at = excluded.last_checked_at, "
                "last_balance_raw = excluded.last_balance_raw",
                (tg_user_id, wallet, now, now, str(balance_raw)),
            )

    def record_balance(self, tg_user_id: int, balance_raw: int, now: float) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE members SET last_checked_at = ?, last_balance_raw = ? WHERE tg_user_id = ?",
                (now, str(balance_raw), tg_user_id),
            )

    def set_member_status(self, tg_user_id: int, status: str, grace_until: float | None) -> None:
        if status not in ("ok", "grace", "ejected"):
            raise ValueError("invalid member status")
        with self.connection:
            self.connection.execute(
                "UPDATE members SET status = ?, grace_until = ? WHERE tg_user_id = ?",
                (status, grace_until, tg_user_id),
            )

    def member_counts(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS n FROM members GROUP BY status"
        ).fetchall()
        counts = {"ok": 0, "grace": 0, "ejected": 0}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    # -- approvals (bot side; the service side lives in dregg_gate.approvals) ------

    def unpresented_approvals(self, limit: int = 10) -> list[ApprovalRequest]:
        rows = self.connection.execute(
            "SELECT id, source, kind, summary, payload_json, created_at FROM approvals "
            "WHERE decided_at IS NULL AND presented_at IS NULL ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            ApprovalRequest(
                row["id"], row["source"], row["kind"], row["summary"],
                json.loads(row["payload_json"]), row["created_at"],
            )
            for row in rows
        ]

    def mark_presented(self, approval_id: int, now: float) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE approvals SET presented_at = ? WHERE id = ? AND presented_at IS NULL",
                (now, approval_id),
            )

    def decide_approval(self, approval_id: int, decision: str, decided_by: str, now: float) -> bool:
        """Stamp the decision; False if the row is missing or already decided."""

        if decision not in ("approve", "reject"):
            raise ValueError("invalid decision")
        with self.connection:
            changed = self.connection.execute(
                "UPDATE approvals SET decided_at = ?, decision = ?, decided_by = ? "
                "WHERE id = ? AND decided_at IS NULL",
                (now, decision, decided_by, approval_id),
            ).rowcount
        return changed == 1

    def pending_approval_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM approvals WHERE decided_at IS NULL"
        ).fetchone()
        return int(row["n"])

    def close(self) -> None:
        self.connection.close()
        fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
        os.close(self._lock_descriptor)
