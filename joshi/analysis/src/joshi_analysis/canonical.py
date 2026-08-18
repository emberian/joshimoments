from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa


def canonical_json_bytes(value: Any, *, newline: bool = False) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return encoded + (b"\n" if newline else b"")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qualified_sha256_bytes(value: bytes) -> str:
    return "sha256:" + sha256_bytes(value)


def qualified_sha256_file(path: Path) -> str:
    return "sha256:" + sha256_file(path)


def require_qualified_sha256(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{context} must be sha256:<64 lowercase hex>")
    return value


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime has no as-known meaning")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite floats are not canonical")
        return {"float_hex": value.hex()}
    if isinstance(value, Mapping):
        return {str(key): _canonical_scalar(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_canonical_scalar(item) for item in value]
    raise TypeError(f"unsupported canonical scalar: {type(value).__name__}")


def schema_descriptor(schema: pa.Schema) -> dict[str, Any]:
    return {
        "fields": [
            {"name": field.name, "nullable": field.nullable, "type": str(field.type)}
            for field in schema
        ]
    }


def schema_sha256(schema: pa.Schema) -> str:
    return qualified_sha256_bytes(canonical_json_bytes(schema_descriptor(schema)))


def logical_table_sha256(table: pa.Table, primary_key: Iterable[str]) -> str:
    """Hash a typed relation in canonical primary-key order.

    This is intentionally simple and exact for initial snapshot-sized artifacts. Large exports can
    later stream canonical record batches while preserving this logical contract.
    """

    keys = tuple(primary_key)
    rows = table.to_pylist()
    rows.sort(key=lambda row: tuple(row[key] for key in keys))
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes(schema_descriptor(table.schema)))
    digest.update(b"\n")
    for row in rows:
        ordered = {field.name: _canonical_scalar(row[field.name]) for field in table.schema}
        digest.update(canonical_json_bytes(ordered, newline=True))
    return "sha256:" + digest.hexdigest()
