"""Single-writer SQLite evidence store using a rollback journal, never WAL."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import sqlite3
import threading
import zlib
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal

from .config import DEFAULT_MAX_DISK_BYTES, DEFAULT_WARN_DISK_BYTES, RetentionConfig
from .models import (
    Cursor,
    Feature,
    Finality,
    HealthStatus,
    Observation,
    RawBlob,
    Source,
    SourceHealth,
    StoredObservation,
    WatchEntry,
    Watchlist,
    canonical_json,
    content_hash,
    normalize_datetime,
    utc_now,
)

SCHEMA_VERSION = 1
MAX_NORMALIZED_PAYLOAD_BYTES = 1024 * 1024
MAX_CURSOR_BYTES = 16 * 1024


class IntelligenceStorageError(RuntimeError):
    pass


class CursorConflict(IntelligenceStorageError):
    pass


class ImmutableConflict(IntelligenceStorageError):
    pass


class StorageQuotaExceeded(IntelligenceStorageError):
    pass


class WriterQueueFull(IntelligenceStorageError):
    pass


@dataclass(frozen=True, slots=True)
class InsertResult:
    observation_id: str
    inserted: bool
    conflict: bool
    content_hash: str


@dataclass(frozen=True, slots=True)
class RawBlobInsertResult:
    raw_blob_id: str
    content_hash: str
    inserted: bool
    original_bytes: int
    stored_bytes: int


@dataclass(frozen=True, slots=True)
class ObservationPage:
    items: tuple[StoredObservation, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class StorageSummary:
    schema_version: int
    journal_mode: str
    observations: int
    raw_blobs: int
    features: int
    watch_entries: int
    conflicts: int
    database_bytes: int
    warning_bytes: int
    limit_bytes: int
    warning: bool
    quota_exceeded: bool


@dataclass(frozen=True, slots=True)
class PruneResult:
    observations_deleted: int
    raw_blobs_deleted: int
    database_bytes_before: int
    database_bytes_after: int


_SCHEMA = """
CREATE TABLE schema_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL,
    migrated_at TEXT NOT NULL
) STRICT;

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    trust_tier INTEGER NOT NULL CHECK (trust_tier BETWEEN 0 AND 5),
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE source_health (
    source_id TEXT PRIMARY KEY REFERENCES sources(source_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('unknown','healthy','degraded','down','disabled')),
    checked_at TEXT NOT NULL,
    last_success_at TEXT,
    latency_ms REAL,
    error_code TEXT,
    detail TEXT
) STRICT;

CREATE TABLE source_health_history (
    sequence INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('unknown','healthy','degraded','down','disabled')),
    checked_at TEXT NOT NULL,
    last_success_at TEXT,
    latency_ms REAL,
    error_code TEXT,
    detail TEXT,
    UNIQUE(source_id, checked_at)
) STRICT;

CREATE TABLE raw_blobs (
    raw_blob_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    request_fingerprint TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content_type TEXT NOT NULL,
    compression TEXT NOT NULL CHECK (compression = 'zlib'),
    body BLOB NOT NULL,
    original_bytes INTEGER NOT NULL CHECK (original_bytes > 0),
    retention_class TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, request_fingerprint, parser_version, content_hash)
) STRICT;

CREATE INDEX raw_blobs_fetched_idx ON raw_blobs(fetched_at);
CREATE INDEX raw_blobs_content_idx ON raw_blobs(content_hash);

CREATE TABLE observations (
    sequence INTEGER PRIMARY KEY,
    observation_id TEXT NOT NULL UNIQUE,
    event_key TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_native_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    emitted_at TEXT,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    finality TEXT NOT NULL CHECK (finality IN ('unverified','processed','confirmed','finalized')),
    parser_version TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    retention_class TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(event_key, content_hash)
) STRICT;

CREATE INDEX observations_feed_idx ON observations(observed_at DESC, sequence DESC);
CREATE INDEX observations_subject_idx ON observations(subject_type, subject_id, observed_at DESC);
CREATE INDEX observations_source_kind_idx ON observations(source_id, kind, observed_at DESC);
CREATE INDEX observations_event_idx ON observations(event_key);

CREATE TABLE observation_raw_refs (
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    raw_blob_id TEXT NOT NULL REFERENCES raw_blobs(raw_blob_id),
    PRIMARY KEY(observation_id, raw_blob_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE observation_conflicts (
    sequence INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL,
    original_observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    conflicting_observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    detected_at TEXT NOT NULL,
    UNIQUE(original_observation_id, conflicting_observation_id)
) STRICT;

CREATE TABLE cursors (
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    stream TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    PRIMARY KEY(source_id, stream)
) STRICT, WITHOUT ROWID;

CREATE TABLE watchlists (
    watchlist_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    max_entries INTEGER NOT NULL CHECK (max_entries BETWEEN 1 AND 50000),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE watch_entries (
    watchlist_id TEXT NOT NULL REFERENCES watchlists(watchlist_id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    added_at TEXT NOT NULL,
    expires_at TEXT,
    discovery_observation_id TEXT REFERENCES observations(observation_id) ON DELETE SET NULL,
    priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 100),
    PRIMARY KEY(watchlist_id, subject_type, subject_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX watch_entries_subject_idx ON watch_entries(subject_type, subject_id);
CREATE INDEX watch_entries_expiry_idx ON watch_entries(expires_at);

CREATE TABLE features (
    sequence INTEGER PRIMARY KEY,
    feature_id TEXT NOT NULL UNIQUE,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    valid_until TEXT,
    model_version TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    created_at TEXT NOT NULL,
    UNIQUE(subject_type, subject_id, feature_key, model_version, computed_at, value_hash)
) STRICT;

CREATE INDEX features_subject_idx ON features(subject_type, subject_id, feature_key, computed_at DESC);

CREATE TABLE feature_evidence (
    feature_id TEXT NOT NULL REFERENCES features(feature_id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    PRIMARY KEY(feature_id, observation_id)
) STRICT, WITHOUT ROWID;
"""


def _iso(value: datetime) -> str:
    return normalize_datetime(value, "datetime").isoformat(timespec="microseconds")


def _datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value).astimezone(UTC)


def _hash_text(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _default_retention() -> RetentionConfig:
    return RetentionConfig(
        observation_days=180,
        raw_blob_days=30,
        max_observations=5_000_000,
        max_disk_bytes=DEFAULT_MAX_DISK_BYTES,
        warn_disk_bytes=DEFAULT_WARN_DISK_BYTES,
        prune_batch_size=10_000,
    )


class IntelligenceStore:
    """One SQLite connection with writes confined to its constructing thread.

    Separate processes may open read-only connections. A deployment must create
    exactly one writable instance (normally owned by :class:`SingleWriter`).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
        journal_mode: Literal["DELETE", "TRUNCATE"] = "DELETE",
        retention: RetentionConfig | None = None,
        read_only: bool = False,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.read_only = read_only
        self.retention = retention or _default_retention()
        self._owner_thread = threading.get_ident()
        if journal_mode not in {"DELETE", "TRUNCATE"}:
            raise IntelligenceStorageError("only rollback journal modes DELETE and TRUNCATE are supported")
        self._journal_mode = journal_mode
        if read_only:
            uri = f"file:{self.path.as_posix()}?mode=ro"
            self._connection = sqlite3.connect(
                uri, uri=True, isolation_level=None, timeout=busy_timeout_ms / 1_000
            )
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with suppress(OSError):
                os.chmod(self.path.parent, 0o700)
            self._connection = sqlite3.connect(
                self.path, isolation_level=None, timeout=busy_timeout_ms / 1_000
            )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        self._connection.execute("PRAGMA temp_store=MEMORY")
        if read_only:
            self._connection.execute("PRAGMA query_only=ON")
            self._verify_schema()
        else:
            actual_mode = str(self._connection.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0])
            if actual_mode.upper() == "WAL" or actual_mode.upper() != journal_mode:
                raise IntelligenceStorageError(
                    f"refusing unexpected SQLite journal mode: {actual_mode}"
                )
            self._migrate()
            with suppress(OSError):
                os.chmod(self.path, 0o600)

    @classmethod
    def from_config(cls, config: Any, *, read_only: bool = False) -> IntelligenceStore:
        return cls(
            config.database.path,
            busy_timeout_ms=config.database.busy_timeout_ms,
            journal_mode=config.database.journal_mode,
            retention=config.retention,
            read_only=read_only,
        )

    def __enter__(self) -> IntelligenceStore:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def _assert_writer(self) -> None:
        if self.read_only:
            raise IntelligenceStorageError("store is read-only")
        if threading.get_ident() != self._owner_thread:
            raise IntelligenceStorageError("writes must use the designated store thread")

    @contextmanager
    def _transaction(self):
        self._assert_writer()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _migrate(self) -> None:
        exists = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if not exists:
            migrated_at = _iso(utc_now())
            # ``executescript`` commits any pending transaction before running,
            # so the transaction must be part of the script itself to keep the
            # first migration atomic.
            script = (
                "BEGIN EXCLUSIVE;\n"
                + _SCHEMA
                + "\nINSERT INTO schema_meta(singleton, version, migrated_at) "
                + f"VALUES (1, {SCHEMA_VERSION}, '{migrated_at}');\nCOMMIT;"
            )
            try:
                self._connection.executescript(script)
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        self._verify_schema()

    def _verify_schema(self) -> None:
        try:
            row = self._connection.execute(
                "SELECT version FROM schema_meta WHERE singleton=1"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise IntelligenceStorageError("intelligence database has no recognized schema") from exc
        if row is None or int(row[0]) != SCHEMA_VERSION:
            version = None if row is None else int(row[0])
            raise IntelligenceStorageError(
                f"unsupported intelligence schema version {version}; expected {SCHEMA_VERSION}"
            )

    @property
    def journal_mode(self) -> str:
        return str(self._connection.execute("PRAGMA journal_mode").fetchone()[0]).upper()

    def _database_bytes(self) -> int:
        total = 0
        for candidate in (self.path, Path(f"{self.path}-journal")):
            with suppress(FileNotFoundError):
                total += candidate.stat().st_size
        return total

    def _check_quota(self, additional_bytes: int = 0) -> None:
        if self._database_bytes() + max(additional_bytes, 0) > self.retention.max_disk_bytes:
            raise StorageQuotaExceeded(
                "intelligence store disk quota reached; collection is paused until retention runs"
            )

    def register_source(self, source: Source) -> bool:
        self._assert_writer()
        metadata = canonical_json(source.metadata)
        existing = self._connection.execute(
            "SELECT * FROM sources WHERE source_id=?", (source.source_id,)
        ).fetchone()
        values = (
            source.kind,
            source.display_name,
            int(source.enabled),
            source.trust_tier,
            metadata,
            _iso(source.created_at),
        )
        if existing is not None:
            actual = tuple(existing[key] for key in (
                "kind", "display_name", "enabled", "trust_tier", "metadata_json", "created_at"
            ))
            if actual != values:
                raise ImmutableConflict(f"source {source.source_id} is already registered differently")
            return False
        with self._transaction():
            self._connection.execute(
                """INSERT INTO sources(
                    source_id,kind,display_name,enabled,trust_tier,metadata_json,created_at
                ) VALUES (?,?,?,?,?,?,?)""",
                (source.source_id, *values),
            )
        return True

    def set_source_enabled(self, source_id: str, enabled: bool) -> None:
        self._assert_writer()
        with self._transaction():
            result = self._connection.execute(
                "UPDATE sources SET enabled=? WHERE source_id=?", (int(enabled), source_id)
            )
            if result.rowcount != 1:
                raise KeyError(source_id)

    def update_source_health(self, health: SourceHealth) -> None:
        self._assert_writer()
        values = (
            health.source_id,
            health.status.value,
            _iso(health.checked_at),
            _iso(health.last_success_at) if health.last_success_at else None,
            health.latency_ms,
            health.error_code,
            health.detail,
        )
        with self._transaction():
            self._connection.execute(
                """INSERT OR IGNORE INTO source_health_history(
                    source_id,status,checked_at,last_success_at,latency_ms,error_code,detail
                ) VALUES (?,?,?,?,?,?,?)""",
                values,
            )
            self._connection.execute(
                """INSERT INTO source_health(
                    source_id,status,checked_at,last_success_at,latency_ms,error_code,detail
                ) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    status=excluded.status, checked_at=excluded.checked_at,
                    last_success_at=excluded.last_success_at, latency_ms=excluded.latency_ms,
                    error_code=excluded.error_code, detail=excluded.detail
                WHERE excluded.checked_at >= source_health.checked_at""",
                values,
            )

    def record_raw_blob(self, blob: RawBlob) -> RawBlobInsertResult:
        self._assert_writer()
        self._check_quota(len(blob.body))
        digest = content_hash(blob.body)
        identity = _hash_text(blob.source_id, blob.request_fingerprint, blob.parser_version, digest)
        raw_blob_id = f"raw_{identity[:40]}"
        compressed = zlib.compress(blob.body, level=6)
        existing = self._connection.execute(
            "SELECT original_bytes,length(body) AS stored_bytes FROM raw_blobs WHERE raw_blob_id=?",
            (raw_blob_id,),
        ).fetchone()
        if existing is not None:
            return RawBlobInsertResult(
                raw_blob_id, digest, False, int(existing["original_bytes"]), int(existing["stored_bytes"])
            )
        with self._transaction():
            self._connection.execute(
                """INSERT INTO raw_blobs(
                    raw_blob_id,source_id,request_fingerprint,fetched_at,parser_version,
                    content_hash,content_type,compression,body,original_bytes,retention_class,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    raw_blob_id,
                    blob.source_id,
                    blob.request_fingerprint,
                    _iso(blob.fetched_at),
                    blob.parser_version,
                    digest,
                    blob.content_type,
                    "zlib",
                    compressed,
                    len(blob.body),
                    blob.retention_class,
                    _iso(utc_now()),
                ),
            )
        return RawBlobInsertResult(raw_blob_id, digest, True, len(blob.body), len(compressed))

    def get_raw_blob(self, raw_blob_id: str) -> RawBlob | None:
        row = self._connection.execute(
            "SELECT * FROM raw_blobs WHERE raw_blob_id=?", (raw_blob_id,)
        ).fetchone()
        if row is None:
            return None
        body = zlib.decompress(bytes(row["body"]))
        if len(body) != int(row["original_bytes"]) or content_hash(body) != row["content_hash"]:
            raise IntelligenceStorageError(f"raw blob integrity check failed: {raw_blob_id}")
        return RawBlob(
            source_id=row["source_id"],
            request_fingerprint=row["request_fingerprint"],
            fetched_at=_datetime(row["fetched_at"]),  # type: ignore[arg-type]
            parser_version=row["parser_version"],
            body=body,
            content_type=row["content_type"],
            retention_class=row["retention_class"],
        )

    def record_observation(self, observation: Observation) -> InsertResult:
        self._assert_writer()
        payload_json = canonical_json(observation.payload)
        if len(payload_json.encode("utf-8")) > MAX_NORMALIZED_PAYLOAD_BYTES:
            raise IntelligenceStorageError("normalized observation payload exceeds 1 MiB")
        provenance_json = canonical_json(list(observation.provenance))
        event_key = _hash_text(observation.source_id, observation.source_native_id, observation.kind)
        semantic = {
            "source_id": observation.source_id,
            "source_native_id": observation.source_native_id,
            "kind": observation.kind,
            "subject_type": observation.subject_type,
            "subject_id": observation.subject_id,
            "emitted_at": _iso(observation.emitted_at) if observation.emitted_at else None,
            "payload": observation.payload,
            "confidence": observation.confidence,
            "finality": observation.finality.value,
            "parser_version": observation.parser_version,
            "provenance": observation.provenance,
        }
        digest = content_hash(semantic)
        observation_id = observation.observation_id or f"obs_{_hash_text(event_key, digest)[:40]}"
        existing_id = self._connection.execute(
            "SELECT content_hash FROM observations WHERE observation_id=?", (observation_id,)
        ).fetchone()
        if existing_id is not None:
            if existing_id["content_hash"] != digest:
                raise ImmutableConflict(f"observation ID collision: {observation_id}")
            return InsertResult(observation_id, False, False, digest)
        exact = self._connection.execute(
            "SELECT observation_id FROM observations WHERE event_key=? AND content_hash=?",
            (event_key, digest),
        ).fetchone()
        if exact is not None:
            return InsertResult(str(exact["observation_id"]), False, False, digest)
        prior = self._connection.execute(
            "SELECT observation_id FROM observations WHERE event_key=? ORDER BY sequence",
            (event_key,),
        ).fetchall()
        self._check_quota(len(payload_json))
        now = _iso(utc_now())
        with self._transaction():
            self._connection.execute(
                """INSERT INTO observations(
                    observation_id,event_key,source_id,source_native_id,kind,subject_type,subject_id,
                    observed_at,emitted_at,payload_json,content_hash,confidence,finality,
                    parser_version,provenance_json,retention_class,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id,
                    event_key,
                    observation.source_id,
                    observation.source_native_id,
                    observation.kind,
                    observation.subject_type,
                    observation.subject_id,
                    _iso(observation.observed_at),
                    _iso(observation.emitted_at) if observation.emitted_at else None,
                    payload_json,
                    digest,
                    observation.confidence,
                    observation.finality.value,
                    observation.parser_version,
                    provenance_json,
                    observation.retention_class,
                    now,
                ),
            )
            for raw_blob_id in observation.raw_blob_ids:
                self._connection.execute(
                    "INSERT INTO observation_raw_refs(observation_id,raw_blob_id) VALUES (?,?)",
                    (observation_id, raw_blob_id),
                )
            for old in prior:
                self._connection.execute(
                    """INSERT OR IGNORE INTO observation_conflicts(
                        event_key,original_observation_id,conflicting_observation_id,detected_at
                    ) VALUES (?,?,?,?)""",
                    (event_key, old["observation_id"], observation_id, now),
                )
        return InsertResult(observation_id, True, bool(prior), digest)

    def _stored_observation(self, row: sqlite3.Row) -> StoredObservation:
        raw_rows = self._connection.execute(
            "SELECT raw_blob_id FROM observation_raw_refs WHERE observation_id=? ORDER BY raw_blob_id",
            (row["observation_id"],),
        ).fetchall()
        return StoredObservation(
            sequence=int(row["sequence"]),
            observation_id=row["observation_id"],
            event_key=row["event_key"],
            source_id=row["source_id"],
            source_native_id=row["source_native_id"],
            kind=row["kind"],
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            observed_at=_datetime(row["observed_at"]),  # type: ignore[arg-type]
            emitted_at=_datetime(row["emitted_at"]),
            payload=json.loads(row["payload_json"]),
            content_hash=row["content_hash"],
            confidence=float(row["confidence"]),
            finality=Finality(row["finality"]),
            parser_version=row["parser_version"],
            provenance=tuple(json.loads(row["provenance_json"])),
            retention_class=row["retention_class"],
            raw_blob_ids=tuple(item["raw_blob_id"] for item in raw_rows),
        )

    def get_observation(self, observation_id: str) -> StoredObservation | None:
        row = self._connection.execute(
            "SELECT * FROM observations WHERE observation_id=?", (observation_id,)
        ).fetchone()
        return None if row is None else self._stored_observation(row)

    @staticmethod
    def _page_cursor(observed_at: str, sequence: int) -> str:
        material = json.dumps([observed_at, sequence], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(material).decode().rstrip("=")

    @staticmethod
    def _decode_page_cursor(cursor: str) -> tuple[str, int]:
        if not cursor or len(cursor) > 256:
            raise ValueError("invalid observation cursor")
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if (
                not isinstance(value, list)
                or len(value) != 2
                or not isinstance(value[0], str)
                or not isinstance(value[1], int)
            ):
                raise ValueError
            _datetime(value[0])
            return value[0], value[1]
        except Exception:
            raise ValueError("invalid observation cursor") from None

    def list_observations(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        source_id: str | None = None,
        kind: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> ObservationPage:
        if not 1 <= limit <= 500:
            raise ValueError("observation page limit must be within [1, 500]")
        clauses: list[str] = []
        values: list[Any] = []
        if cursor is not None:
            before_time, before_sequence = self._decode_page_cursor(cursor)
            clauses.append("(observed_at < ? OR (observed_at = ? AND sequence < ?))")
            values.extend((before_time, before_time, before_sequence))
        for column, value in (
            ("source_id", source_id),
            ("kind", kind),
            ("subject_type", subject_type),
            ("subject_id", subject_id),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM observations{where} ORDER BY observed_at DESC, sequence DESC LIMIT ?",
            (*values, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = tuple(self._stored_observation(row) for row in rows)
        next_cursor = None
        if has_more and rows:
            next_cursor = self._page_cursor(rows[-1]["observed_at"], int(rows[-1]["sequence"]))
        return ObservationPage(items, next_cursor)

    def set_cursor(
        self,
        cursor: Cursor,
        *,
        expected_generation: int | None = None,
    ) -> Cursor:
        self._assert_writer()
        value_json = canonical_json(cursor.value)
        if len(value_json.encode()) > MAX_CURSOR_BYTES:
            raise ValueError("cursor value exceeds 16 KiB")
        existing = self._connection.execute(
            "SELECT generation FROM cursors WHERE source_id=? AND stream=?",
            (cursor.source_id, cursor.stream),
        ).fetchone()
        actual_generation = None if existing is None else int(existing["generation"])
        if expected_generation is not None and actual_generation != expected_generation:
            raise CursorConflict(
                f"cursor generation changed (expected {expected_generation}, found {actual_generation})"
            )
        next_generation = 1 if actual_generation is None else actual_generation + 1
        updated_at = _iso(cursor.updated_at)
        with self._transaction():
            self._connection.execute(
                """INSERT INTO cursors(source_id,stream,value_json,updated_at,generation)
                VALUES (?,?,?,?,?) ON CONFLICT(source_id,stream) DO UPDATE SET
                value_json=excluded.value_json,updated_at=excluded.updated_at,generation=excluded.generation""",
                (cursor.source_id, cursor.stream, value_json, updated_at, next_generation),
            )
        return Cursor(
            cursor.source_id,
            cursor.stream,
            json.loads(value_json),
            cursor.updated_at,
            next_generation,
        )

    def get_cursor(self, source_id: str, stream: str) -> Cursor | None:
        row = self._connection.execute(
            "SELECT * FROM cursors WHERE source_id=? AND stream=?", (source_id, stream)
        ).fetchone()
        if row is None:
            return None
        return Cursor(
            row["source_id"],
            row["stream"],
            json.loads(row["value_json"]),
            _datetime(row["updated_at"]),  # type: ignore[arg-type]
            int(row["generation"]),
        )

    def create_watchlist(self, watchlist: Watchlist) -> bool:
        self._assert_writer()
        row = self._connection.execute(
            "SELECT * FROM watchlists WHERE watchlist_id=?", (watchlist.watchlist_id,)
        ).fetchone()
        values = (
            watchlist.name,
            watchlist.description,
            watchlist.max_entries,
            _iso(watchlist.created_at),
        )
        if row is not None:
            actual = tuple(row[key] for key in ("name", "description", "max_entries", "created_at"))
            if actual != values:
                raise ImmutableConflict(f"watchlist {watchlist.watchlist_id} already differs")
            return False
        with self._transaction():
            self._connection.execute(
                """INSERT INTO watchlists(
                    watchlist_id,name,description,max_entries,created_at
                ) VALUES (?,?,?,?,?)""",
                (watchlist.watchlist_id, *values),
            )
        return True

    def add_watch(self, entry: WatchEntry) -> bool:
        self._assert_writer()
        existing = self._connection.execute(
            """SELECT * FROM watch_entries
            WHERE watchlist_id=? AND subject_type=? AND subject_id=?""",
            (entry.watchlist_id, entry.subject_type, entry.subject_id),
        ).fetchone()
        values = (
            entry.reason,
            _iso(entry.added_at),
            _iso(entry.expires_at) if entry.expires_at else None,
            entry.discovery_observation_id,
            entry.priority,
        )
        if existing is not None:
            actual = tuple(existing[key] for key in (
                "reason", "added_at", "expires_at", "discovery_observation_id", "priority"
            ))
            if actual != values:
                raise ImmutableConflict("watch entry already exists with different evidence")
            return False
        maximum = self._connection.execute(
            "SELECT max_entries FROM watchlists WHERE watchlist_id=?", (entry.watchlist_id,)
        ).fetchone()
        if maximum is None:
            raise KeyError(entry.watchlist_id)
        count = int(self._connection.execute(
            "SELECT count(*) FROM watch_entries WHERE watchlist_id=?", (entry.watchlist_id,)
        ).fetchone()[0])
        if count >= int(maximum["max_entries"]):
            raise IntelligenceStorageError("watchlist capacity reached")
        with self._transaction():
            self._connection.execute(
                """INSERT INTO watch_entries(
                    watchlist_id,subject_type,subject_id,reason,added_at,expires_at,
                    discovery_observation_id,priority
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    entry.watchlist_id,
                    entry.subject_type,
                    entry.subject_id,
                    *values,
                ),
            )
        return True

    def remove_watch(self, watchlist_id: str, subject_type: str, subject_id: str) -> bool:
        self._assert_writer()
        with self._transaction():
            result = self._connection.execute(
                "DELETE FROM watch_entries WHERE watchlist_id=? AND subject_type=? AND subject_id=?",
                (watchlist_id, subject_type, subject_id),
            )
        return result.rowcount == 1

    def list_watchlists(self) -> tuple[Watchlist, ...]:
        rows = self._connection.execute("SELECT * FROM watchlists ORDER BY watchlist_id").fetchall()
        return tuple(
            Watchlist(
                row["watchlist_id"],
                row["name"],
                row["description"],
                int(row["max_entries"]),
                _datetime(row["created_at"]),  # type: ignore[arg-type]
            )
            for row in rows
        )

    def list_watch_entries(
        self, watchlist_id: str, *, include_expired: bool = False, now: datetime | None = None
    ) -> tuple[WatchEntry, ...]:
        clauses = ["watchlist_id=?"]
        values: list[Any] = [watchlist_id]
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            values.append(_iso(now or utc_now()))
        rows = self._connection.execute(
            f"SELECT * FROM watch_entries WHERE {' AND '.join(clauses)} "
            "ORDER BY priority DESC, added_at DESC",
            values,
        ).fetchall()
        return tuple(
            WatchEntry(
                row["watchlist_id"],
                row["subject_type"],
                row["subject_id"],
                row["reason"],
                _datetime(row["added_at"]),  # type: ignore[arg-type]
                _datetime(row["expires_at"]),
                row["discovery_observation_id"],
                int(row["priority"]),
            )
            for row in rows
        )

    def record_feature(self, feature: Feature) -> tuple[str, bool]:
        self._assert_writer()
        value_json = canonical_json(feature.value)
        value_hash = content_hash(feature.value)
        identity = _hash_text(
            feature.subject_type,
            feature.subject_id,
            feature.feature_key,
            feature.model_version,
            _iso(feature.computed_at),
            value_hash,
        )
        feature_id = feature.feature_id or f"feat_{identity[:40]}"
        existing = self._connection.execute(
            "SELECT value_hash FROM features WHERE feature_id=?", (feature_id,)
        ).fetchone()
        if existing is not None:
            if existing["value_hash"] != value_hash:
                raise ImmutableConflict(f"feature ID collision: {feature_id}")
            return feature_id, False
        with self._transaction():
            self._connection.execute(
                """INSERT INTO features(
                    feature_id,subject_type,subject_id,feature_key,value_json,value_hash,
                    computed_at,valid_until,model_version,confidence,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    feature_id,
                    feature.subject_type,
                    feature.subject_id,
                    feature.feature_key,
                    value_json,
                    value_hash,
                    _iso(feature.computed_at),
                    _iso(feature.valid_until) if feature.valid_until else None,
                    feature.model_version,
                    feature.confidence,
                    _iso(utc_now()),
                ),
            )
            for observation_id in feature.evidence_observation_ids:
                self._connection.execute(
                    "INSERT INTO feature_evidence(feature_id,observation_id) VALUES (?,?)",
                    (feature_id, observation_id),
                )
        return feature_id, True

    def list_features(
        self, subject_type: str, subject_id: str, *, limit: int = 500
    ) -> tuple[Feature, ...]:
        if not 1 <= limit <= 1_000:
            raise ValueError("feature limit must be within [1, 1000]")
        rows = self._connection.execute(
            """SELECT * FROM features WHERE subject_type=? AND subject_id=?
            ORDER BY computed_at DESC, sequence DESC LIMIT ?""",
            (subject_type, subject_id, limit),
        ).fetchall()
        result: list[Feature] = []
        for row in rows:
            evidence = self._connection.execute(
                "SELECT observation_id FROM feature_evidence WHERE feature_id=? ORDER BY observation_id",
                (row["feature_id"],),
            ).fetchall()
            result.append(
                Feature(
                    subject_type=row["subject_type"],
                    subject_id=row["subject_id"],
                    feature_key=row["feature_key"],
                    value=json.loads(row["value_json"]),
                    computed_at=_datetime(row["computed_at"]),  # type: ignore[arg-type]
                    model_version=row["model_version"],
                    confidence=float(row["confidence"]),
                    evidence_observation_ids=tuple(
                        item["observation_id"] for item in evidence
                    ),
                    valid_until=_datetime(row["valid_until"]),
                    feature_id=row["feature_id"],
                )
            )
        return tuple(result)

    def list_sources(self) -> tuple[tuple[Source, SourceHealth | None], ...]:
        rows = self._connection.execute(
            """SELECT s.*,h.status,h.checked_at,h.last_success_at,h.latency_ms,h.error_code,h.detail
            FROM sources s LEFT JOIN source_health h USING(source_id) ORDER BY s.source_id"""
        ).fetchall()
        result: list[tuple[Source, SourceHealth | None]] = []
        for row in rows:
            source = Source(
                row["source_id"],
                row["kind"],
                row["display_name"],
                bool(row["enabled"]),
                int(row["trust_tier"]),
                json.loads(row["metadata_json"]),
                _datetime(row["created_at"]),  # type: ignore[arg-type]
            )
            health = None
            if row["status"] is not None:
                health = SourceHealth(
                    row["source_id"],
                    HealthStatus(row["status"]),
                    _datetime(row["checked_at"]),  # type: ignore[arg-type]
                    _datetime(row["last_success_at"]),
                    row["latency_ms"],
                    row["error_code"],
                    row["detail"],
                )
            result.append((source, health))
        return tuple(result)

    def storage_summary(self) -> StorageSummary:
        def count(table: str) -> int:
            # Table is only ever a constant at the call sites below.
            return int(self._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

        database_bytes = self._database_bytes()
        return StorageSummary(
            schema_version=SCHEMA_VERSION,
            journal_mode=self.journal_mode,
            observations=count("observations"),
            raw_blobs=count("raw_blobs"),
            features=count("features"),
            watch_entries=count("watch_entries"),
            conflicts=count("observation_conflicts"),
            database_bytes=database_bytes,
            warning_bytes=self.retention.warn_disk_bytes,
            limit_bytes=self.retention.max_disk_bytes,
            warning=database_bytes >= self.retention.warn_disk_bytes,
            quota_exceeded=database_bytes >= self.retention.max_disk_bytes,
        )

    def prune(self, *, now: datetime | None = None, vacuum: bool = False) -> PruneResult:
        self._assert_writer()
        current = normalize_datetime(now or utc_now(), "now")
        before = self._database_bytes()
        observation_cutoff = _iso(current - timedelta(days=self.retention.observation_days))
        raw_cutoff = _iso(current - timedelta(days=self.retention.raw_blob_days))
        observations_deleted = 0
        raw_deleted = 0
        with self._transaction():
            result = self._connection.execute(
                """DELETE FROM observations WHERE sequence IN (
                    SELECT o.sequence FROM observations o
                    WHERE o.retention_class != 'pinned' AND o.observed_at < ?
                      AND NOT EXISTS (
                        SELECT 1 FROM feature_evidence e WHERE e.observation_id=o.observation_id
                      )
                    ORDER BY o.observed_at LIMIT ?
                )""",
                (observation_cutoff, self.retention.prune_batch_size),
            )
            observations_deleted += result.rowcount
            overflow = max(
                int(self._connection.execute("SELECT count(*) FROM observations").fetchone()[0])
                - self.retention.max_observations,
                0,
            )
            if overflow:
                result = self._connection.execute(
                    """DELETE FROM observations WHERE sequence IN (
                        SELECT o.sequence FROM observations o
                        WHERE o.retention_class != 'pinned'
                          AND NOT EXISTS (
                            SELECT 1 FROM feature_evidence e WHERE e.observation_id=o.observation_id
                          )
                        ORDER BY o.observed_at LIMIT ?
                    )""",
                    (min(overflow, self.retention.prune_batch_size),),
                )
                observations_deleted += result.rowcount
            result = self._connection.execute(
                """DELETE FROM raw_blobs WHERE raw_blob_id IN (
                    SELECT b.raw_blob_id FROM raw_blobs b
                    WHERE b.retention_class != 'pinned' AND b.fetched_at < ?
                      AND NOT EXISTS (
                        SELECT 1 FROM observation_raw_refs r WHERE r.raw_blob_id=b.raw_blob_id
                      )
                    ORDER BY b.fetched_at LIMIT ?
                )""",
                (raw_cutoff, self.retention.prune_batch_size),
            )
            raw_deleted += result.rowcount
            self._connection.execute(
                "DELETE FROM watch_entries WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (_iso(current),),
            )
        if vacuum and (observations_deleted or raw_deleted):
            self._connection.execute("VACUUM")
        return PruneResult(observations_deleted, raw_deleted, before, self._database_bytes())

    def integrity_check(self) -> bool:
        return self._connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@dataclass(slots=True)
class _WriteRequest:
    operation: str
    arguments: tuple[Any, ...]
    keywords: dict[str, Any]
    future: Future[Any]


class SingleWriter:
    """Bounded command queue owning the sole writable SQLite connection."""

    _ALLOWED_OPERATIONS: ClassVar[set[str]] = {
        "register_source",
        "set_source_enabled",
        "update_source_health",
        "record_raw_blob",
        "record_observation",
        "set_cursor",
        "get_cursor",
        "create_watchlist",
        "add_watch",
        "remove_watch",
        "record_feature",
        "prune",
    }

    def __init__(
        self,
        path: str | Path,
        *,
        queue_capacity: int = 10_000,
        busy_timeout_ms: int = 5_000,
        journal_mode: Literal["DELETE", "TRUNCATE"] = "DELETE",
        retention: RetentionConfig | None = None,
    ) -> None:
        if not 1 <= queue_capacity <= 1_000_000:
            raise ValueError("queue_capacity must be within [1, 1000000]")
        self._path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._journal_mode = journal_mode
        self._retention = retention
        self._queue: queue.Queue[_WriteRequest | None] = queue.Queue(queue_capacity)
        self._thread = threading.Thread(target=self._run, name="shitcoims-intelligence-writer", daemon=True)
        self._started = False
        self._closed = False

    @classmethod
    def from_config(cls, config: Any) -> SingleWriter:
        return cls(
            config.database.path,
            queue_capacity=config.ingestion.queue_capacity,
            busy_timeout_ms=config.database.busy_timeout_ms,
            journal_mode=config.database.journal_mode,
            retention=config.retention,
        )

    def start(self) -> SingleWriter:
        if not self._started:
            self._started = True
            self._thread.start()
        return self

    def close(self, *, timeout: float = 10) -> None:
        if self._closed:
            return
        self._closed = True
        if self._started:
            self._queue.put(None)
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise IntelligenceStorageError("intelligence writer did not stop cleanly")

    def __enter__(self) -> SingleWriter:
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def _run(self) -> None:
        with IntelligenceStore(
            self._path,
            busy_timeout_ms=self._busy_timeout_ms,
            journal_mode=self._journal_mode,
            retention=self._retention,
        ) as store:
            while True:
                request = self._queue.get()
                try:
                    if request is None:
                        return
                    method = getattr(store, request.operation)
                    request.future.set_result(method(*request.arguments, **request.keywords))
                except BaseException as exc:
                    if request is not None:
                        request.future.set_exception(exc)
                finally:
                    self._queue.task_done()

    def submit(self, operation: str, *arguments: Any, **keywords: Any) -> Future[Any]:
        if operation not in self._ALLOWED_OPERATIONS:
            raise ValueError(f"unsupported writer operation: {operation}")
        if self._closed:
            raise IntelligenceStorageError("intelligence writer is closed")
        if not self._started:
            self.start()
        future: Future[Any] = Future()
        try:
            self._queue.put_nowait(_WriteRequest(operation, arguments, keywords, future))
        except queue.Full:
            raise WriterQueueFull(
                "intelligence writer queue is full; source must apply backpressure"
            ) from None
        return future

    def record_observation(self, observation: Observation) -> Future[InsertResult]:
        return self.submit("record_observation", observation)

    def record_raw_blob(self, blob: RawBlob) -> Future[RawBlobInsertResult]:
        return self.submit("record_raw_blob", blob)

    def register_source(self, source: Source) -> Future[bool]:
        return self.submit("register_source", source)

    def update_source_health(self, health: SourceHealth) -> Future[None]:
        return self.submit("update_source_health", health)

    def get_cursor(self, source_id: str, stream: str) -> Future[Cursor | None]:
        return self.submit("get_cursor", source_id, stream)

    def set_cursor(self, cursor: Cursor, **keywords: Any) -> Future[Cursor]:
        return self.submit("set_cursor", cursor, **keywords)

    @property
    def pending(self) -> int:
        return self._queue.qsize()
