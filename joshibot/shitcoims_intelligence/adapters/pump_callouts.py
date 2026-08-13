"""Disabled-by-default specification for Pump.fun's unsupported Callouts surface.

Pump's public program documentation is at
https://github.com/pump-fun/pump-public-docs. It does not currently document a
Callouts API. This adapter therefore requires an explicit experimental contract
and private credential, never accepts browser cookies, and quarantines schema
drift instead of guessing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from solders.pubkey import Pubkey

from .common import (
    AdapterDisabled,
    QuarantinedRecord,
    SourceProvenance,
    bounded_text,
    read_private_env_value,
    response_json,
    safe_transport_error,
)

SOURCE_ID = "pump_callouts_experimental"
ADAPTER_VERSION = "pump-callouts-quarantine-v1"
EXPERIMENTAL_ENDPOINT = "https://advanced-api-v2.pump.fun/callouts"
EXPERIMENTAL_SCHEMA = "pump-advanced-callouts-v0"
MAX_ITEMS = 50
MAX_RESPONSE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class PumpCalloutsConfig:
    enabled: bool = False
    endpoint: str | None = None
    schema_version: str | None = None
    credential_env_file: Path | None = None
    credential_key_name: str = "PUMP_CALLOUTS_API_TOKEN"


@dataclass(frozen=True, slots=True)
class PumpCalloutClaim:
    source_event_id: str
    created_at: datetime
    mint: str
    caller_wallet_claim: str | None
    text_claim: str
    provenance: SourceProvenance
    policy_effect: str = "observe"
    can_execute: bool = False


@dataclass(frozen=True, slots=True)
class PumpCalloutsBatch:
    claims: tuple[PumpCalloutClaim, ...]
    quarantined: tuple[QuarantinedRecord, ...]
    provenance: SourceProvenance


def _canonical_pubkey(value: Any, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > 44:
        raise ValueError("invalid_pubkey")
    try:
        return str(Pubkey.from_string(value))
    except Exception as exc:
        raise ValueError("invalid_pubkey") from exc


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("invalid_timestamp")
    return parsed.astimezone(UTC)


class PumpCalloutsAdapter:
    """A quarantined experiment, not a supported or execution-bearing feed."""

    def __init__(self, config: PumpCalloutsConfig, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http

    def _validate_enabled(self) -> tuple[str, Path]:
        config = self._config
        if not config.enabled:
            raise AdapterDisabled("Pump Callouts experiment is disabled")
        if config.endpoint != EXPERIMENTAL_ENDPOINT or config.schema_version != EXPERIMENTAL_SCHEMA:
            raise AdapterDisabled("Pump Callouts has no configured recognized experimental contract")
        parsed = urlsplit(config.endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "advanced-api-v2.pump.fun"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
            or parsed.path != "/callouts"
        ):
            raise AdapterDisabled("Pump Callouts endpoint is not the fixed experimental origin")
        if config.credential_env_file is None:
            raise AdapterDisabled("Pump Callouts credential is not configured")
        return config.endpoint, config.credential_env_file

    async def fetch(self, *, limit: int = 25) -> PumpCalloutsBatch:
        if not 1 <= limit <= MAX_ITEMS:
            raise ValueError(f"limit must be between 1 and {MAX_ITEMS}")
        endpoint, env_file = self._validate_enabled()
        credential = read_private_env_value(env_file, self._config.credential_key_name)
        provenance = SourceProvenance(
            source_id=SOURCE_ID,
            source_url="https://pump.fun/callouts",
            endpoint_family="advanced-api-v2/callouts",
            adapter_version=ADAPTER_VERSION,
            contract_status="unsupported_reverse_engineered_experimental",
        )
        try:
            response = await self._http.get(
                endpoint,
                params={"limit": str(limit)},
                headers={
                    "authorization": f"Bearer {credential}",
                    "accept": "application/json",
                },
                follow_redirects=False,
                timeout=httpx.Timeout(10, connect=4),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise safe_transport_error("Pump Callouts experiment", exc) from exc
        body = response_json(response, limit=MAX_RESPONSE_BYTES, source="Pump Callouts")
        if not isinstance(body, dict) or set(body) - {"data", "next_cursor"}:
            return PumpCalloutsBatch(
                (),
                (QuarantinedRecord(source_id=SOURCE_ID, reason="top_level_schema_drift"),),
                provenance,
            )
        items = body.get("data")
        if not isinstance(items, list) or len(items) > limit:
            return PumpCalloutsBatch(
                (),
                (QuarantinedRecord(source_id=SOURCE_ID, reason="items_schema_drift"),),
                provenance,
            )
        claims: list[PumpCalloutClaim] = []
        quarantined: list[QuarantinedRecord] = []
        for item in items:
            try:
                if not isinstance(item, dict) or set(item) - {
                    "id",
                    "created_at",
                    "mint",
                    "caller_wallet",
                    "text",
                }:
                    raise ValueError("item_schema_drift")
                source_event_id = bounded_text(item.get("id"), limit=128)
                text = bounded_text(item.get("text"), limit=2_000, allow_empty=True)
                if source_event_id is None or text is None:
                    raise ValueError("required_field_missing")
                claims.append(
                    PumpCalloutClaim(
                        source_event_id=source_event_id,
                        created_at=_timestamp(item.get("created_at")),
                        mint=_canonical_pubkey(item.get("mint"), required=True) or "",
                        caller_wallet_claim=_canonical_pubkey(
                            item.get("caller_wallet"), required=False
                        ),
                        text_claim=text,
                        provenance=provenance,
                    )
                )
            except (TypeError, ValueError) as exc:
                digest = hashlib.sha256(
                    repr(item).encode("utf-8", errors="replace")[:16_384]
                ).hexdigest()[:24]
                quarantined.append(
                    QuarantinedRecord(
                        source_id=SOURCE_ID,
                        reason=f"schema_drift:{str(exc)[:80]}",
                        fingerprint=digest,
                    )
                )
        return PumpCalloutsBatch(tuple(claims), tuple(quarantined), provenance)
