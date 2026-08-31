"""Shared safety primitives for advisory-only, untrusted data adapters."""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

MAX_SECRET_FILE_BYTES = 64 * 1024
MAX_SECRET_BYTES = 4_096
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class AdvisoryAdapterError(RuntimeError):
    """A sanitized transport, configuration, or untrusted-data failure."""


class AdapterDisabled(AdvisoryAdapterError):
    """The experimental adapter has not satisfied its explicit enablement contract."""


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    source_id: str
    source_url: str
    endpoint_family: str
    adapter_version: str
    contract_status: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    source_id: str
    reason: str
    source_event_id: str | None = None
    fingerprint: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def bounded_text(value: Any, *, limit: int, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    if not text and not allow_empty:
        return None
    return text[:limit]


def ensure_bounded_response(response: httpx.Response, *, limit: int, source: str) -> bytes:
    declared = response.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise AdvisoryAdapterError(f"{source} response exceeded its size limit")
        except ValueError as exc:
            raise AdvisoryAdapterError(f"{source} returned an invalid content length") from exc
    content = response.content
    if len(content) > limit:
        raise AdvisoryAdapterError(f"{source} response exceeded its size limit")
    return content


def response_json(response: httpx.Response, *, limit: int, source: str) -> Any:
    content = ensure_bounded_response(response, limit=limit, source=source)
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdvisoryAdapterError(f"{source} returned malformed JSON") from exc


def read_private_token_file(path: Path) -> str:
    """Read a single secret from a mode-0600 token file.

    Used for dedicated credential files such as ``~/.apify-token``. Unlike
    ``read_private_env_value``, this file is the token itself, not a dotenv.
    """

    path = path.expanduser()
    if path.is_symlink():
        raise AdvisoryAdapterError(f"token path must not be a symlink: {path}")
    try:
        info = path.stat()
    except FileNotFoundError:
        raise AdvisoryAdapterError(f"token file is missing: {path}") from None
    if not stat.S_ISREG(info.st_mode):
        raise AdvisoryAdapterError(f"token path is not a regular file: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise AdvisoryAdapterError(
            f"token file must be private (0600 or stricter): {path} is {mode:o}"
        )
    if info.st_size > MAX_SECRET_BYTES:
        raise AdvisoryAdapterError("token file exceeded its size limit")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AdvisoryAdapterError("token file is not valid UTF-8") from exc
    if not value:
        raise AdvisoryAdapterError("token file is empty")
    if len(value.encode()) > MAX_SECRET_BYTES or any(character.isspace() for character in value):
        raise AdvisoryAdapterError("token file has an invalid format")
    return value


def read_private_env_value(path: Path, key_name: str) -> str:
    """Read exactly one value from a private dotenv file without mutating os.environ."""

    if not _ENV_NAME.fullmatch(key_name):
        raise AdvisoryAdapterError("environment key name is invalid")
    path = path.expanduser()
    try:
        info = path.stat()
    except FileNotFoundError:
        raise AdvisoryAdapterError(f"environment file is missing: {path}") from None
    if not stat.S_ISREG(info.st_mode):
        raise AdvisoryAdapterError(f"environment path is not a regular file: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise AdvisoryAdapterError(
            f"environment file must be private (0600 or stricter): {path} is {mode:o}"
        )
    if info.st_size > MAX_SECRET_FILE_BYTES:
        raise AdvisoryAdapterError("environment file exceeded its size limit")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise AdvisoryAdapterError("environment file is not valid UTF-8") from exc

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        if not separator or name.strip() != key_name:
            continue
        value = raw_value.strip()
        if value.startswith('"'):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as exc:
                raise AdvisoryAdapterError(f"{key_name} has invalid quoting") from exc
            if not isinstance(decoded, str):
                raise AdvisoryAdapterError(f"{key_name} must be a string")
            value = decoded
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise AdvisoryAdapterError(f"{key_name} has invalid quoting")
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        if not value:
            raise AdvisoryAdapterError(f"{key_name} is empty")
        if len(value.encode()) > MAX_SECRET_BYTES or any(character.isspace() for character in value):
            raise AdvisoryAdapterError(f"{key_name} has an invalid format")
        return value
    raise AdvisoryAdapterError(f"{key_name} is missing from the configured environment file")


def safe_transport_error(source: str, exc: Exception) -> AdvisoryAdapterError:
    # HTTP exceptions may render credential-bearing headers or URLs. Keep only the type.
    return AdvisoryAdapterError(f"{source} transport failed ({type(exc).__name__})")
