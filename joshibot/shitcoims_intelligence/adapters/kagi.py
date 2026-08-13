"""Bounded Kagi Search API v1 discovery adapter.

API reference: https://help.kagi.com/kagi/api/search.html
Only derived links, titles, and snippets cross this adapter boundary.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .common import (
    AdvisoryAdapterError,
    QuarantinedRecord,
    SourceProvenance,
    bounded_text,
    read_private_env_value,
    response_json,
    safe_transport_error,
)

SOURCE_ID = "kagi_search_v1"
ENDPOINT = "https://kagi.com/api/v1/search"
ADAPTER_VERSION = "kagi-search-v1-derived-v1"
MAX_QUERY_CHARS = 512
MAX_RESULTS = 20
MAX_RESPONSE_BYTES = 512 * 1024
_TAG = re.compile(r"<[^>]{0,200}>")


@dataclass(frozen=True, slots=True)
class KagiConfig:
    env_file: Path
    key_name: str = "KAGI_API_KEY"


@dataclass(frozen=True, slots=True)
class KagiSearchResult:
    title: str
    url: str
    snippet: str
    rank: int
    provenance: SourceProvenance
    policy_effect: str = "observe"
    can_execute: bool = False


@dataclass(frozen=True, slots=True)
class KagiSearchBatch:
    query: str
    results: tuple[KagiSearchResult, ...]
    quarantined: tuple[QuarantinedRecord, ...]
    provenance: SourceProvenance


def _clean(value: Any, *, limit: int) -> str:
    text = bounded_text(value, limit=limit * 2, allow_empty=True) or ""
    return bounded_text(html.unescape(_TAG.sub("", text)), limit=limit, allow_empty=True) or ""


def _safe_result_url(value: Any) -> str | None:
    text = bounded_text(value, limit=2_048)
    if text is None:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 80, 443}
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


class KagiSearchAdapter:
    def __init__(self, config: KagiConfig, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http

    async def search(self, query: str, *, limit: int = 10) -> KagiSearchBatch:
        query = " ".join(query.split())
        if not 1 <= len(query) <= MAX_QUERY_CHARS:
            raise ValueError(f"query must be between 1 and {MAX_QUERY_CHARS} characters")
        if not 1 <= limit <= MAX_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_RESULTS}")
        key = read_private_env_value(self._config.env_file, self._config.key_name)
        provenance = SourceProvenance(
            source_id=SOURCE_ID,
            source_url="https://help.kagi.com/kagi/api/search.html",
            endpoint_family="Kagi Search API v1",
            adapter_version=ADAPTER_VERSION,
            contract_status="documented_api",
        )
        try:
            response = await self._http.post(
                ENDPOINT,
                headers={
                    "authorization": f"Bearer {key}",
                    "content-type": "application/json",
                    "accept": "application/json",
                },
                json={"query": query},
                follow_redirects=False,
                timeout=httpx.Timeout(20, connect=5),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise safe_transport_error("Kagi Search", exc) from exc
        body = response_json(response, limit=MAX_RESPONSE_BYTES, source="Kagi Search")
        if not isinstance(body, dict) or len(body) > 12:
            raise AdvisoryAdapterError("Kagi Search response schema changed")
        data = body.get("data")
        items = data.get("search") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) > 100:
            raise AdvisoryAdapterError("Kagi Search response schema changed")

        results: list[KagiSearchResult] = []
        quarantined: list[QuarantinedRecord] = []
        for index, item in enumerate(items[:limit]):
            if not isinstance(item, dict) or len(item) > 30:
                quarantined.append(
                    QuarantinedRecord(source_id=SOURCE_ID, reason="result_schema_drift")
                )
                continue
            url = _safe_result_url(item.get("url"))
            if url is None:
                quarantined.append(
                    QuarantinedRecord(source_id=SOURCE_ID, reason="unsafe_result_url")
                )
                continue
            results.append(
                KagiSearchResult(
                    title=_clean(item.get("title"), limit=300),
                    url=url,
                    snippet=_clean(item.get("snippet"), limit=1_200),
                    rank=index + 1,
                    provenance=provenance,
                )
            )
        return KagiSearchBatch(query, tuple(results), tuple(quarantined), provenance)
