"""Immutable, execution-free data contracts for local intelligence evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias

JSONScalar: TypeAlias = bool | int | float | str | None

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CONTENT_HASH = re.compile(r"^[0-9a-f]{64}$")


class FrozenJSON(Mapping[str, "JSONValue"]):
    """Small immutable mapping used inside frozen domain records."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, JSONValue] | None = None) -> None:
        self._values = dict(values or {})

    def __getitem__(self, key: str) -> JSONValue:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenJSON:
        return self

    def __repr__(self) -> str:
        return f"FrozenJSON({self._values!r})"


JSONValue: TypeAlias = JSONScalar | tuple["JSONValue", ...] | FrozenJSON


def _freeze_json(value: Any, *, depth: int = 0) -> JSONValue:
    if depth > 24:
        raise ValueError("JSON value nesting exceeds 24 levels")
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JSONValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            if len(key) > 256:
                raise ValueError("JSON object key exceeds 256 characters")
            result[key] = _freeze_json(child, depth=depth + 1)
        return FrozenJSON(result)
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(child, depth=depth + 1) for child in value)
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def thaw_json(value: JSONValue | Mapping[str, Any] | list[Any]) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple | list):
        return [thaw_json(child) for child in value]
    return value


def canonical_json(value: JSONValue | Mapping[str, Any] | list[Any]) -> str:
    frozen = _freeze_json(value)
    return json.dumps(
        thaw_json(frozen),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_hash(value: bytes | JSONValue | Mapping[str, Any] | list[Any]) -> str:
    body = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_datetime(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _identifier(value: str, name: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must match {_IDENTIFIER.pattern}")
    return value


class Finality(StrEnum):
    UNVERIFIED = "unverified"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class Observation:
    """A fact claimed by a source, never an instruction to execute a trade."""

    source_id: str
    source_native_id: str
    kind: str
    subject_type: str
    subject_id: str
    observed_at: datetime
    payload: Mapping[str, Any]
    emitted_at: datetime | None = None
    confidence: float = 1.0
    finality: Finality = Finality.UNVERIFIED
    parser_version: str = "unknown-v1"
    provenance: tuple[str, ...] = ()
    retention_class: str = "standard"
    raw_blob_ids: tuple[str, ...] = ()
    observation_id: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.source_id, "source_id"),
            (self.kind, "kind"),
            (self.subject_type, "subject_type"),
            (self.parser_version, "parser_version"),
            (self.retention_class, "retention_class"),
        ):
            _identifier(value, name)
        if not self.source_native_id or len(self.source_native_id) > 512:
            raise ValueError("source_native_id must contain 1-512 characters")
        if not self.subject_id or len(self.subject_id) > 512:
            raise ValueError("subject_id must contain 1-512 characters")
        if self.observation_id is not None:
            _identifier(self.observation_id, "observation_id")
        if not 0 <= self.confidence <= 1 or not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite and within [0, 1]")
        object.__setattr__(self, "observed_at", normalize_datetime(self.observed_at, "observed_at"))
        if self.emitted_at is not None:
            object.__setattr__(self, "emitted_at", normalize_datetime(self.emitted_at, "emitted_at"))
        object.__setattr__(self, "payload", _freeze_json(self.payload))
        if len(self.provenance) > 64 or any(not item or len(item) > 512 for item in self.provenance):
            raise ValueError("provenance must contain at most 64 nonempty bounded references")
        object.__setattr__(self, "provenance", tuple(self.provenance))
        if len(self.raw_blob_ids) > 32:
            raise ValueError("an observation may reference at most 32 raw blobs")
        for raw_blob_id in self.raw_blob_ids:
            _identifier(raw_blob_id, "raw_blob_id")
        object.__setattr__(self, "raw_blob_ids", tuple(self.raw_blob_ids))


@dataclass(frozen=True, slots=True)
class StoredObservation:
    sequence: int
    observation_id: str
    event_key: str
    source_id: str
    source_native_id: str
    kind: str
    subject_type: str
    subject_id: str
    observed_at: datetime
    emitted_at: datetime | None
    payload: Mapping[str, Any]
    content_hash: str
    confidence: float
    finality: Finality
    parser_version: str
    provenance: tuple[str, ...]
    retention_class: str
    raw_blob_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    kind: str
    display_name: str
    enabled: bool = True
    trust_tier: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _identifier(self.kind, "kind")
        if not self.display_name or len(self.display_name) > 160:
            raise ValueError("display_name must contain 1-160 characters")
        if not 0 <= self.trust_tier <= 5:
            raise ValueError("trust_tier must be within [0, 5]")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))
        object.__setattr__(self, "created_at", normalize_datetime(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: str
    status: HealthStatus
    checked_at: datetime
    last_success_at: datetime | None = None
    latency_ms: float | None = None
    error_code: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        object.__setattr__(self, "checked_at", normalize_datetime(self.checked_at, "checked_at"))
        if self.last_success_at is not None:
            object.__setattr__(
                self,
                "last_success_at",
                normalize_datetime(self.last_success_at, "last_success_at"),
            )
        if self.latency_ms is not None and (self.latency_ms < 0 or not math.isfinite(self.latency_ms)):
            raise ValueError("latency_ms must be finite and nonnegative")
        if self.error_code is not None:
            _identifier(self.error_code, "error_code")
        if self.detail is not None and len(self.detail) > 512:
            raise ValueError("health detail exceeds 512 characters")


@dataclass(frozen=True, slots=True)
class Watchlist:
    watchlist_id: str
    name: str
    description: str = ""
    max_entries: int = 2_000
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _identifier(self.watchlist_id, "watchlist_id")
        if not self.name or len(self.name) > 120 or len(self.description) > 512:
            raise ValueError("watchlist name or description is invalid")
        if not 1 <= self.max_entries <= 50_000:
            raise ValueError("max_entries must be within [1, 50000]")
        object.__setattr__(self, "created_at", normalize_datetime(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class WatchEntry:
    watchlist_id: str
    subject_type: str
    subject_id: str
    reason: str
    added_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    discovery_observation_id: str | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        _identifier(self.watchlist_id, "watchlist_id")
        _identifier(self.subject_type, "subject_type")
        if not self.subject_id or len(self.subject_id) > 512:
            raise ValueError("subject_id must contain 1-512 characters")
        if not self.reason or len(self.reason) > 512:
            raise ValueError("reason must contain 1-512 characters")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be within [0, 100]")
        object.__setattr__(self, "added_at", normalize_datetime(self.added_at, "added_at"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", normalize_datetime(self.expires_at, "expires_at"))
            if self.expires_at <= self.added_at:
                raise ValueError("expires_at must be after added_at")


@dataclass(frozen=True, slots=True)
class Feature:
    subject_type: str
    subject_id: str
    feature_key: str
    value: Any
    computed_at: datetime
    model_version: str
    confidence: float
    evidence_observation_ids: tuple[str, ...]
    valid_until: datetime | None = None
    feature_id: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.subject_type, "subject_type"),
            (self.feature_key, "feature_key"),
            (self.model_version, "model_version"),
        ):
            _identifier(value, name)
        if self.feature_id is not None:
            _identifier(self.feature_id, "feature_id")
        if not self.subject_id or len(self.subject_id) > 512:
            raise ValueError("subject_id must contain 1-512 characters")
        if not 0 <= self.confidence <= 1 or not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite and within [0, 1]")
        object.__setattr__(self, "value", _freeze_json(self.value))
        object.__setattr__(self, "computed_at", normalize_datetime(self.computed_at, "computed_at"))
        if self.valid_until is not None:
            object.__setattr__(
                self, "valid_until", normalize_datetime(self.valid_until, "valid_until")
            )
        if not self.evidence_observation_ids:
            raise ValueError("a feature requires at least one evidence observation")
        if len(self.evidence_observation_ids) > 256:
            raise ValueError("a feature may cite at most 256 observations")
        object.__setattr__(
            self, "evidence_observation_ids", tuple(self.evidence_observation_ids)
        )


@dataclass(frozen=True, slots=True)
class Cursor:
    source_id: str
    stream: str
    value: Mapping[str, Any]
    updated_at: datetime = field(default_factory=utc_now)
    generation: int = 0

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _identifier(self.stream, "stream")
        if self.generation < 0:
            raise ValueError("cursor generation cannot be negative")
        object.__setattr__(self, "value", _freeze_json(self.value))
        object.__setattr__(self, "updated_at", normalize_datetime(self.updated_at, "updated_at"))


@dataclass(frozen=True, slots=True)
class RawBlob:
    source_id: str
    request_fingerprint: str
    fetched_at: datetime
    parser_version: str
    body: bytes
    content_type: str = "application/json"
    retention_class: str = "standard"

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _identifier(self.parser_version, "parser_version")
        _identifier(self.retention_class, "retention_class")
        if not _CONTENT_HASH.fullmatch(self.request_fingerprint):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 digest")
        if not isinstance(self.body, bytes):
            raise ValueError("raw blob body must be bytes")
        if not self.body:
            raise ValueError("raw blob body cannot be empty")
        if len(self.body) > 64 * 1024 * 1024:
            raise ValueError("raw blob body exceeds the 64 MiB per-response limit")
        if not self.content_type or len(self.content_type) > 128:
            raise ValueError("content_type is invalid")
        object.__setattr__(self, "fetched_at", normalize_datetime(self.fetched_at, "fetched_at"))


def request_fingerprint(source_id: str, method: str, parameters: Mapping[str, Any]) -> str:
    """Hash credential-free request semantics; never pass headers or credentialed URLs."""

    _identifier(source_id, "source_id")
    _identifier(method, "method")
    lowered = {str(key).lower().replace("-", "_") for key in parameters}
    forbidden = {
        "api_key",
        "apikey",
        "x_api_key",
        "authorization",
        "headers",
        "credential",
        "secret",
        "token",
    }
    if lowered & forbidden:
        raise ValueError("request fingerprint parameters must not contain credentials")
    return content_hash({"source_id": source_id, "method": method, "parameters": parameters})
