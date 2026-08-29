"""The portal's only writable state: single-use nonces and hourly rate buckets.

Both are DISPOSABLE. Delete this file and the worst that happens is every open sign-in
attempt has to be restarted and every rate bucket resets. Nothing here is an asset, which
is the point — the public box holds no state anyone would miss, so it never becomes a box
we cannot lose. (Contrast ``edge/relay``'s publication log, which is exactly the opposite
kind of file and lives on a declared state path for exactly that reason.)

SINGLE USE IS ENFORCED BY THE DELETE, NOT BY A FLAG. ``consume`` deletes the row inside
the same transaction that reads it and reports whether it deleted anything, so two
requests racing the same nonce cannot both win — sqlite serializes the writers. A
``used`` column checked and then set would have left exactly that race open.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import time
from dataclasses import dataclass
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS challenges (
    nonce      TEXT PRIMARY KEY,
    wallet     TEXT NOT NULL,
    message    TEXT NOT NULL,
    issued_at  REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS challenges_expiry ON challenges(expires_at);
CREATE TABLE IF NOT EXISTS buckets (
    scope   TEXT NOT NULL,
    subject TEXT NOT NULL,
    window  INTEGER NOT NULL,
    hits    INTEGER NOT NULL,
    PRIMARY KEY (scope, subject, window)
);
"""


class StoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Challenge:
    nonce: str
    wallet: str
    message: str
    issued_at: float
    expires_at: float


class PortalStore:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise StoreError("portal state path must be a regular file, not a symlink")
            if metadata.st_uid != os.getuid():
                raise StoreError("portal state file must be owned by the current user")
        self.path = path
        self.connection = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        os.chmod(path, 0o600)
        self.connection.row_factory = sqlite3.Row
        # WAL because the service is threaded: readers must not block the writer that is
        # consuming a nonce, and a blocked read here is a hung sign-in.
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript(DDL)
        self.connection.commit()

    # -- challenges ------------------------------------------------------------------

    def put_challenge(self, challenge: Challenge, *, max_open: int = 10_000) -> bool:
        """Store a fresh nonce, after expiring old ones. False when the table is full.

        The cap is not a performance guard, it is a refusal: an unbounded nonce table is a
        free write amplifier for anyone who can reach /portal/api/nonce, and the honest
        answer to "the table is full" is to stop minting, not to grow.
        """

        with self.connection:
            self.connection.execute(
                "DELETE FROM challenges WHERE expires_at <= ?", (challenge.issued_at,)
            )
            (open_count,) = self.connection.execute("SELECT count(*) FROM challenges").fetchone()
            if open_count >= max_open:
                return False
            self.connection.execute(
                "INSERT OR REPLACE INTO challenges(nonce, wallet, message, issued_at, expires_at) "
                "VALUES(?,?,?,?,?)",
                (
                    challenge.nonce,
                    challenge.wallet,
                    challenge.message,
                    challenge.issued_at,
                    challenge.expires_at,
                ),
            )
        return True

    def consume(self, nonce: object, *, now: float) -> Challenge | None:
        """Take a nonce out of the table and return it, or None. Never returns it twice."""

        if not isinstance(nonce, str) or not nonce or len(nonce) > 64:
            return None
        with self.connection:
            row = self.connection.execute(
                "SELECT nonce, wallet, message, issued_at, expires_at FROM challenges WHERE nonce = ?",
                (nonce,),
            ).fetchone()
            if row is None:
                return None
            deleted = self.connection.execute("DELETE FROM challenges WHERE nonce = ?", (nonce,))
            if deleted.rowcount != 1:
                return None
        if row["expires_at"] <= now:
            return None
        return Challenge(
            nonce=row["nonce"],
            wallet=row["wallet"],
            message=row["message"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
        )

    def open_challenges(self) -> int:
        (count,) = self.connection.execute("SELECT count(*) FROM challenges").fetchone()
        return int(count)

    # -- rate buckets ----------------------------------------------------------------

    def allow(self, scope: str, subject: str, *, limit: int, now: float, window: int = 3600) -> bool:
        """Fixed-window counter. Coarse on purpose: exact is not worth a second table."""

        slot = int(now // window)
        with self.connection:
            self.connection.execute("DELETE FROM buckets WHERE window < ?", (slot - 1,))
            row = self.connection.execute(
                "SELECT hits FROM buckets WHERE scope = ? AND subject = ? AND window = ?",
                (scope, subject, slot),
            ).fetchone()
            hits = int(row["hits"]) if row is not None else 0
            if hits >= limit:
                return False
            self.connection.execute(
                "INSERT INTO buckets(scope, subject, window, hits) VALUES(?,?,?,1) "
                "ON CONFLICT(scope, subject, window) DO UPDATE SET hits = hits + 1",
                (scope, subject, slot),
            )
        return True

    def close(self) -> None:
        self.connection.close()


def sweep_expired(store: PortalStore, *, now: float | None = None) -> int:
    now = time.time() if now is None else now
    with store.connection:
        cursor = store.connection.execute("DELETE FROM challenges WHERE expires_at <= ?", (now,))
    return cursor.rowcount
