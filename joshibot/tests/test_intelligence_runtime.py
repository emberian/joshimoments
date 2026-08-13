from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from shitcoims_intelligence.adapters.x_apify import ENDPOINT as X_APIFY_ENDPOINT
from shitcoims_intelligence.config import load_intelligence_config
from shitcoims_intelligence.runtime import X_KOL_WATCHLIST_ID, X_WATCHLIST_ID, CollectorRuntime
from shitcoims_intelligence.service import build_service
from shitcoims_intelligence.storage import IntelligenceStore, SingleWriter


def test_runtime_has_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence import runtime

    source = inspect.getsource(runtime)
    assert "shitcoims_sentinel.executor" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source


def _config(tmp_path: Path, token: Path) -> object:
    path = tmp_path / "intelligence.yaml"
    path.write_text(
        "\n".join(
            (
                "version: 1",
                "database:",
                '  path: "./intel.sqlite3"',
                "adapters:",
                "  x_apify:",
                "    enabled: true",
                f"    token_file: {token}",
                "    max_items_per_query: 2",
                "    max_items_per_day: 10",
                "    queries:",
                '      - "pump.fun"',
            )
        ),
        encoding="utf-8",
    )
    return load_intelligence_config(path)


@pytest.mark.asyncio
async def test_collector_runtime_persists_x_tweets_and_mint_watches(tmp_path: Path) -> None:
    token = tmp_path / "apify-token"
    token.write_text("apify_api_test-token\n", encoding="utf-8")
    token.chmod(0o600)
    mint = "So11111111111111111111111111111111111111112"
    config = _config(tmp_path, token)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == X_APIFY_ENDPOINT
        assert "token=" not in str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "type": "tweet",
                    "id": "1846846285917131130",
                    "url": "https://x.com/alpha/status/1846846285917131130",
                    "text": f"$BONK https://pump.fun/coin/{mint}",
                    "createdAt": datetime(2026, 8, 12, 19, tzinfo=UTC).strftime(
                        "%a %b %d %H:%M:%S +0000 %Y"
                    ),
                    "likeCount": 4,
                    "author": {"userName": "alpha", "followers": 9, "isBlueVerified": False},
                }
            ],
        )

    writer = SingleWriter.from_config(config)
    runtime = CollectorRuntime(config, writer, collectors_requested=True)
    runtime._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    writer.start()
    try:
        summary = await runtime.run_once()
    finally:
        await runtime._http.aclose()
        writer.close()

    assert summary["x_seen"] == 1
    assert summary["x_inserted"] >= 1
    with IntelligenceStore.from_config(config, read_only=True) as store:
        page = store.list_observations(source_id="apify_x_kaitoeasyapi_v1", limit=20)
        kinds = {item.kind for item in page.items}
        assert "x_tweet" in kinds
        assert "x_cashtag" in kinds
        assert "x_mint_mention" in kinds
        entries = store.list_watch_entries(X_WATCHLIST_ID)
        assert any(entry.subject_id == mint for entry in entries)


@pytest.mark.asyncio
async def test_collector_queries_from_configured_kol_handles(tmp_path: Path) -> None:
    token = tmp_path / "apify-token"
    token.write_text("apify_api_test-token\n", encoding="utf-8")
    token.chmod(0o600)
    path = tmp_path / "intelligence.yaml"
    path.write_text(
        "\n".join(
            (
                "version: 1",
                "database:",
                '  path: "./intel.sqlite3"',
                "adapters:",
                "  x_apify:",
                "    enabled: true",
                f"    token_file: {token}",
                "    max_items_per_query: 2",
                "    max_items_per_day: 10",
                "    queries: []",
                "    kols:",
                "      - handle: blknoiz06",
                "        label: Ansem",
                "        follow_replies: false",
                "        max_items: 2",
            )
        ),
        encoding="utf-8",
    )
    config = load_intelligence_config(path)
    queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        queries.append(body)
        return httpx.Response(
            200,
            json=[
                {
                    "type": "tweet",
                    "id": "1846846285917131131",
                    "url": "https://x.com/blknoiz06/status/1846846285917131131",
                    "text": "watching the trenches",
                    "createdAt": "2026-08-12T19:00:00+00:00",
                    "author": {"userName": "blknoiz06", "followers": 9},
                    "conversationId": "1846846285917131131",
                }
            ],
        )

    writer = SingleWriter.from_config(config)
    runtime = CollectorRuntime(config, writer, collectors_requested=True)
    runtime._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    writer.start()
    try:
        summary = await runtime.run_once()
    finally:
        await runtime._http.aclose()
        writer.close()

    assert any("from:blknoiz06" in item for item in queries)
    assert summary["x_seen"] == 1
    with IntelligenceStore.from_config(config, read_only=True) as store:
        kinds = {item.kind for item in store.list_observations(limit=20).items}
        assert "x_kol_post" in kinds
        assert any(
            entry.subject_id == "blknoiz06"
            for entry in store.list_watch_entries(X_KOL_WATCHLIST_ID)
        )


def test_history_wallets_union_seed_and_declared_kol_wallets(tmp_path: Path) -> None:
    token = tmp_path / "apify-token"
    token.write_text("apify_api_test-token\n", encoding="utf-8")
    token.chmod(0o600)
    wallet = "Sh1WNJ8g68rXJGyDjVPcfxWN1WbMrLsgdXmSb6cccuE"
    kol_wallet = "GV6UUmNxz2RpKxmNAPadYKb7uQpszwqQAu3qLJxVdC52"
    path = tmp_path / "intelligence.yaml"
    path.write_text(
        "\n".join(
            (
                "version: 1",
                "helius:",
                f"  seed_wallets: [{wallet}]",
                "adapters:",
                "  x_apify:",
                f"    token_file: {token}",
                "    kols:",
                "      - handle: blknoiz06",
                "        label: Ansem",
                f"        wallet: {kol_wallet}",
            )
        ),
        encoding="utf-8",
    )
    config = load_intelligence_config(path)
    runtime = CollectorRuntime(config, SingleWriter.from_config(config), collectors_requested=False)
    assert runtime._history_wallets() == (wallet, kol_wallet)


def test_build_service_without_collectors_does_not_touch_executor(tmp_path: Path) -> None:
    path = tmp_path / "intelligence.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    components = build_service(load_intelligence_config(path), collectors_enabled=False)
    assert components.runtime.health()["collectors_active"] == 0
    close = getattr(components.reader, "close", None)
    if close is not None:
        close()


def _token(tmp_path: Path) -> Path:
    token = tmp_path / "apify-token"
    token.write_text("apify_api_test-token\n", encoding="utf-8")
    token.chmod(0o600)
    return token


def _kols_config(tmp_path: Path, token: Path, handles: tuple[str, ...]) -> object:
    kol_lines = []
    for handle in handles:
        kol_lines.extend(
            (
                f"      - handle: {handle}",
                f"        label: {handle}",
                "        follow_replies: false",
                "        max_items: 1",
            )
        )
    path = tmp_path / "intelligence.yaml"
    path.write_text(
        "\n".join(
            (
                "version: 1",
                "database:",
                '  path: "./intel.sqlite3"',
                "adapters:",
                "  x_apify:",
                "    enabled: true",
                f"    token_file: {token}",
                "    max_items_per_query: 2",
                "    max_items_per_day: 20",
                "    queries: []",
                "    kols:",
                *kol_lines,
            )
        ),
        encoding="utf-8",
    )
    return load_intelligence_config(path)


def _tweet_json(tweet_id: str, handle: str) -> dict[str, object]:
    return {
        "type": "tweet",
        "id": tweet_id,
        "url": f"https://x.com/{handle}/status/{tweet_id}",
        "text": f"watching the trenches @{handle}",
        "createdAt": "2026-08-12T19:00:00+00:00",
        "author": {"userName": handle, "followers": 9},
        "conversationId": tweet_id,
    }


def _query_from_request(request: httpx.Request) -> str:
    payload = json.loads(request.content)
    query = payload.get("twitterContent") if isinstance(payload, dict) else None
    return query if isinstance(query, str) else request.content.decode()


@pytest.mark.asyncio
async def test_cycle_increments_clock_on_partial_x_failure(tmp_path: Path) -> None:
    token = _token(tmp_path)
    config = _config(tmp_path, token)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "apify down"})

    writer = SingleWriter.from_config(config)
    runtime = CollectorRuntime(config, writer, collectors_requested=True)
    runtime._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    writer.start()
    try:
        summary = await runtime.run_once()
        health = runtime.health()
    finally:
        await runtime._http.aclose()
        writer.close()

    assert summary["x_seen"] == 0
    assert health["cycles"] == 1
    assert health["last_cycle_at"] is not None
    assert health["cycle_in_progress"] is False
    assert health["cycle_started_at"] is None
    assert health["last_error"] is not None


@pytest.mark.asyncio
async def test_per_query_timeout_continues_to_next_kol(tmp_path: Path) -> None:
    token = _token(tmp_path)
    config = _kols_config(tmp_path, token, ("slowkol", "fastkol"))
    queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = _query_from_request(request)
        queries.append(query)
        if "from:slowkol" in query:
            await asyncio.sleep(60)
        return httpx.Response(200, json=[_tweet_json("1846846285917131200", "fastkol")])

    writer = SingleWriter.from_config(config)
    runtime = CollectorRuntime(
        config,
        writer,
        collectors_requested=True,
        _query_timeout_seconds=0.05,
    )
    runtime._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    writer.start()
    try:
        summary = await runtime.run_once()
        health = runtime.health()
    finally:
        await runtime._http.aclose()
        writer.close()

    assert any("from:fastkol" in item for item in queries)
    assert health["x_query_timeouts"] >= 1
    assert health["cycles"] == 1
    assert health["last_cycle_at"] is not None
    assert summary["x_seen"] == 1
    assert health["last_error"] == "x query timed out"
    assert health["x_items_today"] == 1


@pytest.mark.asyncio
async def test_cycle_budget_rotates_kols(tmp_path: Path) -> None:
    token = _token(tmp_path)
    handles = ("alpha", "bravo", "charlie")
    config = _kols_config(tmp_path, token, handles)
    queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = _query_from_request(request)
        queries.append(query)
        await asyncio.sleep(0.08)
        handle = query.split("from:", 1)[-1] if "from:" in query else "unknown"
        return httpx.Response(200, json=[_tweet_json("1846846285917131300", handle)])

    writer = SingleWriter.from_config(config)
    runtime = CollectorRuntime(
        config,
        writer,
        collectors_requested=True,
        _cycle_budget_seconds=0.04,
    )
    runtime._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    writer.start()
    try:
        await runtime.run_once()
        first = [item for item in queries if item.startswith("from:")]
        first_handles = [item.removeprefix("from:") for item in first]
        queries.clear()
        await runtime.run_once()
        second = [item for item in queries if item.startswith("from:")]
        second_handles = [item.removeprefix("from:") for item in second]
        health = runtime.health()
    finally:
        await runtime._http.aclose()
        writer.close()

    assert first_handles, "first cycle should query at least one KOL"
    assert first_handles != list(handles), "budget should stop the rotation short"
    assert first_handles == list(handles[: len(first_handles)])
    assert second_handles, "second cycle should continue the rotation"
    later = handles[len(first_handles) % len(handles)]
    assert later in second_handles
    assert health["last_cycle_partial"] is True
    assert health["cycles"] == 2
    assert isinstance(health["x_resume_index"], int)


def test_health_honest_during_first_cycle(tmp_path: Path) -> None:
    token = _token(tmp_path)
    config = _config(tmp_path, token)
    writer = SingleWriter.from_config(config)
    runtime = CollectorRuntime(config, writer, collectors_requested=True)
    writer.start()
    try:
        runtime._task = object()  # type: ignore[assignment]
        runtime._started_at = datetime.now(UTC)
        health = runtime.health()
        assert health["healthy"] is True
        assert health["last_cycle_at"] is None
        assert health["cycle_in_progress"] is False
        assert health["cycle_started_at"] is None
        assert health["cycles"] == 0
        assert health["last_cycle_partial"] is False
        assert health["x_query_timeouts"] == 0
        assert health["x_resume_index"] == 0

        runtime._cycle_started_at = datetime.now(UTC)
        in_progress = runtime.health()
        assert in_progress["healthy"] is True
        assert in_progress["cycle_in_progress"] is True
        assert in_progress["cycle_started_at"] is not None
        assert in_progress["last_cycle_at"] is None

        runtime._cycle_started_at = datetime.now(UTC) - timedelta(seconds=200)
        stuck = runtime.health()
        assert stuck["healthy"] is True
        assert stuck["last_error"] == "collection cycle appears stuck"
        assert "collection cycle appears stuck" in stuck["degraded_reasons"]
    finally:
        writer.close()
