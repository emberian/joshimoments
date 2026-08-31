from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

import intel
from shitcoims_intelligence.api import MAX_PAGE_SIZE, create_app, public_projection
from shitcoims_intelligence.config import load_intelligence_config
from shitcoims_intelligence.models import (
    HealthStatus,
    Observation,
    Source,
    SourceHealth,
    WatchEntry,
    Watchlist,
)
from shitcoims_intelligence.service import StoreReader, build_service
from shitcoims_intelligence.storage import IntelligenceStore


class FakeReader:
    def health(self) -> dict[str, Any]:
        return {
            "ready": True,
            "writer_healthy": True,
            "quota": {"healthy": True, "used_bytes": 100, "limit_bytes": 1_000},
            "private_key": "must-not-leak",
        }

    async def summary(self) -> dict[str, Any]:
        return {
            "totals": {"items": 2, "wallets": 1},
            "raw_payload": "nope",
            "candidates": [
                {
                    "mint": "MintOne",
                    "verdict": "skip",
                    "reasons": ["seen"],
                    "scores": {"mentions": 1},
                    "execution_effect": "none",
                    "api_key": "must-not-leak",
                }
            ],
        }

    def feed(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": "one",
                    "kind": "wallet_trade",
                    "summary": "Observed wallet activity",
                    "api_key": "must-not-leak",
                },
                {"id": "two", "kind": "source_status", "payload": {"secret": "nope"}},
            ],
            "next_cursor": "cursor:two",
            "has_more": True,
            "requested": kwargs,
        }

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        if item_id == "missing":
            return None
        return {"id": item_id, "evidence": [{"source": "helius"}], "raw": "nope"}

    def get_dossier(self, kind: str, identifier: str) -> dict[str, Any] | None:
        if identifier == "missing":
            return None
        return {"kind": kind, "id": identifier, "confidence": 0.5}

    def sources(self) -> list[dict[str, Any]]:
        return [{"id": "helius", "healthy": True}]

    def watchlists(self) -> list[dict[str, Any]]:
        return [{"id": "seeds", "member_count": 25}]

    def digests(self, **_kwargs: Any) -> dict[str, Any]:
        return {"items": [{"id": "digest-one", "title": "Latest"}], "next_cursor": None}

    def candidates(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "mint": "MintOne",
                    "name": "TEST",
                    "verdict": "skip",
                    "reasons": ["seen in firehose"],
                    "scores": {"mentions": 1},
                    "execution_effect": "none",
                    "api_key": "must-not-leak",
                    "private_key": "must-not-leak",
                }
            ],
            "execution_effect": "none",
        }


class BrokenReader(FakeReader):
    def summary(self) -> dict[str, Any]:
        raise RuntimeError("credentialed-url?api-key=must-not-leak")


@pytest.fixture
def app():
    return create_app(FakeReader())


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as value:
        yield value


async def test_health_reports_read_only_and_storage_quota(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["healthy"] is True
    assert response.json()["mode"] == "READ_ONLY"
    assert response.json()["store"]["quota"]["used_bytes"] == 100
    assert "private_key" not in response.text


async def test_feed_is_paginated_capped_and_redacted(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/intelligence/feed", params={"limit": MAX_PAGE_SIZE})

    assert response.status_code == 200
    assert response.json()["next_cursor"] == "cursor:two"
    assert len(response.json()["items"]) == 2
    assert "api_key" not in response.text
    assert "payload" not in response.text
    too_large = await client.get("/api/intelligence/feed", params={"limit": MAX_PAGE_SIZE + 1})
    assert too_large.status_code == 422


async def test_candidates_are_read_only_and_redacted(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/intelligence/candidates")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_effect"] == "none"
    assert "generated_at" in body
    assert body["items"][0]["mint"] == "MintOne"
    assert body["items"][0]["verdict"] == "skip"
    assert body["items"][0]["execution_effect"] == "none"
    assert "must-not-leak" not in response.text
    assert "api_key" not in response.text
    assert "private_key" not in response.text
    mutated = await client.post("/api/intelligence/candidates", json={"mint": "nope"})
    assert mutated.status_code == 405


async def test_summary_includes_candidates_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/intelligence/summary")

    assert response.status_code == 200
    body = response.json()
    assert "candidates" in body
    assert body["candidates"][0]["mint"] == "MintOne"
    assert "must-not-leak" not in response.text


async def test_read_endpoints_and_not_found(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/intelligence/summary")).status_code == 200
    assert (await client.get("/api/intelligence/candidates")).status_code == 200
    assert (await client.get("/api/intelligence/items/one")).json()["item"]["id"] == "one"
    assert (await client.get("/api/intelligence/items/missing")).status_code == 404
    dossier = await client.get("/api/intelligence/dossiers/wallet/abc")
    assert dossier.json()["dossier"]["kind"] == "wallet"
    assert (await client.get("/api/intelligence/sources")).status_code == 200
    assert (await client.get("/api/intelligence/watchlists")).status_code == 200
    assert (await client.get("/api/intelligence/digests")).status_code == 200


async def test_required_short_read_routes_are_available(client: httpx.AsyncClient) -> None:
    assert (await client.get("/feed")).status_code == 200
    assert (await client.get("/items/one")).status_code == 200
    assert (await client.get("/dossiers/wallet/abc")).status_code == 200
    assert (await client.get("/sources")).status_code == 200
    assert (await client.get("/watchlists")).status_code == 200
    assert (await client.get("/digests")).status_code == 200


async def test_store_failures_degrade_without_reflecting_exception_details() -> None:
    app = create_app(BrokenReader())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://inteld.local",
    ) as client:
        response = await client.get("/api/intelligence/summary")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "intelligence_unavailable"
    assert "api-key" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_api_rejects_mutations_and_sets_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/intelligence/watchlists", json={"id": "danger"})

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"


async def test_invalid_identifiers_and_cursors_are_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/intelligence/items/not%20safe")).status_code == 422
    assert (await client.get("/api/intelligence/feed", params={"cursor": "bad cursor"})).status_code == 422


def test_public_projection_removes_sensitive_and_raw_fields() -> None:
    projected = public_projection(
        {
            "id": "safe",
            "raw_body": "raw",
            "nested": {"telegram_bot_token": "secret", "value": 4},
            "serialized_transaction": "transaction",
            "transaction": {"message": "must-not-leak"},
        }
    )

    assert projected == {"id": "safe", "nested": {"value": 4}}


def test_cli_uses_intelligence_config_without_network_overrides() -> None:
    args = intel._parser().parse_args(["--config", "private-intelligence.yaml"])

    assert args.config == Path("private-intelligence.yaml")
    with pytest.raises(SystemExit):
        intel._parser().parse_args(["--host", "0.0.0.0"])


def test_launch_agent_is_loopback_only() -> None:
    plist = Path("ops/com.shitcoims.inteld.plist").read_text(encoding="utf-8")

    assert "intelligence.yaml" in plist
    assert "0.0.0.0" not in plist
    assert "--live" not in plist
    assert "shitcoims-wallet" not in plist


def _configured_store(tmp_path: Path):
    config_file = tmp_path / "intelligence.yaml"
    config_file.write_text(
        "\n".join(
            (
                "version: 1",
                "database:",
                '  path: "./private/intelligence.sqlite3"',
                "server:",
                '  host: "127.0.0.1"',
                "  port: 8788",
                "  allowed_origins:",
                '    - "http://127.0.0.1:8787"',
                '    - "http://127.0.0.1:3000"',
            )
        ),
        encoding="utf-8",
    )
    config = load_intelligence_config(config_file)
    observed_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    with IntelligenceStore.from_config(config) as store:
        source = Source("helius", "chain", "Helius", trust_tier=4, created_at=observed_at)
        store.register_source(source)
        store.update_source_health(
            SourceHealth(
                "helius",
                HealthStatus.HEALTHY,
                observed_at,
                observed_at,
                25.0,
            )
        )
        observation = Observation(
            source_id="helius",
            source_native_id="signature-one",
            kind="wallet_trade",
            subject_type="wallet",
            subject_id="WalletOne",
            observed_at=observed_at,
            payload={
                "title": "Wallet bought a token",
                "summary": "A confirmed on-chain acquisition.",
                "severity": "info",
                "signature": "signature-one",
                "raw_body": "must-not-leak",
                "api_key": "must-not-leak",
            },
        )
        result = store.record_observation(observation)
        store.create_watchlist(Watchlist("seeds", "Seed wallets", created_at=observed_at))
        store.add_watch(
            WatchEntry(
                "seeds",
                "wallet",
                "WalletOne",
                "manual seed",
                added_at=observed_at,
            )
        )
    return config, result.observation_id


async def test_concrete_store_reader_serves_only_curated_read_models(tmp_path: Path) -> None:
    config, observation_id = _configured_store(tmp_path)
    components = build_service(config, collectors_enabled=False)
    assert isinstance(components.reader, StoreReader)
    app = create_app(
        components.reader,
        runtime=components.runtime,
        allowed_origins=config.server.allowed_origins,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as client:
        health = await client.get("/api/health")
        feed = await client.get("/api/intelligence/feed")
        summary = await client.get("/api/intelligence/summary")
        dossier = await client.get("/api/intelligence/dossiers/wallet/WalletOne")
        sources = await client.get("/api/intelligence/sources")
        watchlists = await client.get("/api/intelligence/watchlists")
        item = await client.get(f"/api/intelligence/items/{observation_id}")

    assert health.status_code == 503
    assert health.json()["store"]["ready"] is True
    assert health.json()["store"]["writer_healthy"] is False
    assert health.json()["runtime"]["collectors_active"] == 0
    assert feed.json()["items"][0]["id"] == observation_id
    assert summary.json()["execution_effect"] == "none"
    assert summary.json()["kols"] == []
    assert summary.json()["candidates"] == []
    assert dossier.json()["dossier"]["execution_effect"] == "none"
    assert sources.json()["items"][0]["id"] == "helius"
    assert watchlists.json()["items"][0]["member_count"] == 1
    assert item.json()["item"]["details"]["signature"] == "signature-one"
    combined = " ".join(
        response.text for response in (health, feed, summary, dossier, sources, watchlists, item)
    )
    assert "must-not-leak" not in combined
    components.reader.close()  # type: ignore[attr-defined]


async def test_missing_database_starts_in_explicit_degraded_mode(tmp_path: Path) -> None:
    config_file = tmp_path / "intelligence.yaml"
    config_file.write_text(
        'version: 1\ndatabase:\n  path: "./missing/intelligence.sqlite3"\n',
        encoding="utf-8",
    )
    config = load_intelligence_config(config_file)
    components = build_service(config, collectors_enabled=False)
    app = create_app(components.reader, runtime=components.runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as client:
        health = await client.get("/api/health")
        summary = await client.get("/api/intelligence/summary")

    assert health.status_code == 503
    assert health.json()["store"]["ready"] is False
    assert summary.status_code == 503


async def test_store_reader_health_does_not_claim_missing_writer_when_storage_is_fine(
    tmp_path: Path,
) -> None:
    config, _observation_id = _configured_store(tmp_path)
    components = build_service(config, collectors_enabled=False)
    assert isinstance(components.reader, StoreReader)
    app = create_app(
        components.reader,
        runtime=components.runtime,
        allowed_origins=config.server.allowed_origins,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as client:
        health = await client.get("/api/health")

    assert health.status_code == 503
    body = health.json()
    assert "writer is not active in this process" not in health.text
    assert body["store"]["ready"] is True
    assert body["store"]["writer_healthy"] is False
    assert body["store"]["degraded_reasons"] == []
    assert body["runtime"]["writer_active"] is False
    components.reader.close()  # type: ignore[attr-defined]


async def test_health_with_live_runtime_writer_is_not_degraded_by_store_copy(
    tmp_path: Path,
) -> None:
    class FakeRuntime:
        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def health(self) -> dict[str, Any]:
            return {
                "healthy": True,
                "writer_active": True,
                "collectors_active": 2,
                "degraded_reasons": [],
            }

    config, _observation_id = _configured_store(tmp_path)
    components = build_service(config, collectors_enabled=False)
    assert isinstance(components.reader, StoreReader)
    app = create_app(components.reader, runtime=FakeRuntime())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as client:
        health = await client.get("/api/health")

    assert health.status_code == 200
    body = health.json()
    assert body["healthy"] is True
    assert body["store"]["ready"] is True
    assert body["store"]["writer_healthy"] is False
    assert body["store"]["degraded_reasons"] == []
    assert body["runtime"]["writer_active"] is True
    assert "writer is not active in this process" not in health.text
    components.reader.close()  # type: ignore[attr-defined]


def _configured_kol_store(tmp_path: Path):
    config, _ = _configured_store(tmp_path)
    posted_at = datetime(2026, 8, 12, 13, tzinfo=UTC)
    watched_at = datetime(2026, 8, 12, 11, tzinfo=UTC)
    with IntelligenceStore.from_config(config) as store:
        store.create_watchlist(Watchlist("x-kols", "X KOL watches", created_at=watched_at))
        store.add_watch(
            WatchEntry(
                "x-kols",
                "kol",
                "blknoiz06",
                "Ansem",
                added_at=watched_at,
                priority=80,
            )
        )
        store.add_watch(
            WatchEntry(
                "x-kols",
                "kol",
                "quietkol",
                "configured watch for @quietkol",
                added_at=watched_at,
                priority=40,
            )
        )
        store.record_observation(
            Observation(
                source_id="helius",
                source_native_id="tweet-one:kol:blknoiz06",
                kind="x_kol_post",
                subject_type="kol",
                subject_id="blknoiz06",
                observed_at=posted_at,
                payload={
                    "title": "KOL @blknoiz06: gm",
                    "summary": "gm",
                    "watched_handle": "blknoiz06",
                    "author_username": "blknoiz06",
                    "cashtags": ["BONK"],
                    "api_key": "must-not-leak",
                },
            )
        )
        store.record_observation(
            Observation(
                source_id="helius",
                source_native_id="tweet-two:kol:driveby",
                kind="x_kol_post",
                subject_type="kol",
                subject_id="driveby",
                observed_at=posted_at,
                payload={
                    "title": "KOL @driveby: hey",
                    "watched_handle": "driveby",
                    "author_username": "driveby",
                    "api_key": "must-not-leak",
                },
            )
        )
    return config, posted_at


async def test_summary_and_kol_dossier_expose_watched_handles_without_execution(
    tmp_path: Path,
) -> None:
    config, posted_at = _configured_kol_store(tmp_path)
    components = build_service(config, collectors_enabled=False)
    assert isinstance(components.reader, StoreReader)
    app = create_app(
        components.reader,
        runtime=components.runtime,
        allowed_origins=config.server.allowed_origins,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as client:
        summary = await client.get("/api/intelligence/summary")
        posted = await client.get("/api/intelligence/dossiers/kol/blknoiz06")
        stub = await client.get("/api/intelligence/dossiers/kol/quietkol")
        cased = await client.get("/api/intelligence/dossiers/kol/QuietKol")
        driveby = await client.get("/api/intelligence/dossiers/kol/driveby")
        missing = await client.get("/api/intelligence/dossiers/kol/missingkol")
        wallet_missing = await client.get("/api/intelligence/dossiers/wallet/not-watched")

    body = summary.json()
    assert summary.status_code == 200
    assert body["execution_effect"] == "none"
    assert body["kols"] == [
        {
            "handle": "blknoiz06",
            "label": "Ansem",
            "last_seen": posted_at.isoformat(),
            "posts": 1,
        },
        {
            "handle": "quietkol",
            "last_seen": None,
            "posts": 0,
        },
        {
            "handle": "driveby",
            "last_seen": posted_at.isoformat(),
            "posts": 1,
        },
    ]
    assert posted.json()["dossier"]["execution_effect"] == "none"
    assert posted.json()["dossier"]["recent_items"][0]["kind"] == "x_kol_post"
    assert posted.json()["dossier"]["recent_items"][0]["watched_handle"] == "blknoiz06"
    assert stub.status_code == 200
    assert stub.json()["dossier"] == {
        "kind": "kol",
        "id": "quietkol",
        "confidence": 0,
        "features": [],
        "recent_items": [],
        "next_cursor": None,
        "updated_at": datetime(2026, 8, 12, 11, tzinfo=UTC).isoformat(),
        "execution_effect": "none",
    }
    assert cased.status_code == 200
    assert cased.json()["dossier"]["id"] == "QuietKol"
    assert cased.json()["dossier"]["recent_items"] == []
    assert cased.json()["dossier"]["execution_effect"] == "none"
    assert driveby.status_code == 200
    assert driveby.json()["dossier"]["recent_items"][0]["watched_handle"] == "driveby"
    assert missing.status_code == 404
    assert wallet_missing.status_code == 404
    combined = " ".join(
        response.text for response in (summary, posted, stub, cased, driveby, missing)
    )
    assert "must-not-leak" not in combined
    assert "Keypair" not in combined
    components.reader.close()  # type: ignore[attr-defined]


def _configured_candidate_store(tmp_path: Path):
    config, _ = _configured_store(tmp_path)
    posted_at = datetime(2026, 8, 12, 14, tzinfo=UTC)
    mint = "So11111111111111111111111111111111111111112"
    with IntelligenceStore.from_config(config) as store:
        store.record_observation(
            Observation(
                source_id="helius",
                source_native_id="tweet-candidate:kol:blknoiz06",
                kind="x_kol_post",
                subject_type="kol",
                subject_id="blknoiz06",
                observed_at=posted_at,
                payload={
                    "title": "KOL @blknoiz06: mint",
                    "summary": "look at this",
                    "watched_handle": "blknoiz06",
                    "author_username": "blknoiz06",
                    "mint_candidates": [mint],
                    "name": "WSOL",
                    "early_coin": {
                        "unique_wallet_count": 24,
                        "wallet_volume_hhi": 0.09,
                        "top_wallet_quote_share": 0.11,
                    },
                    "api_key": "must-not-leak",
                },
            )
        )
        store.record_observation(
            Observation(
                source_id="helius",
                source_native_id="wallet-candidate:WalletOne",
                kind="wallet_transaction",
                subject_type="wallet",
                subject_id="WalletOne",
                observed_at=posted_at,
                payload={
                    "title": "wallet touched a mint",
                    "token_deltas": [{"mint": mint, "raw_delta": 10, "decimals": 9}],
                    "api_key": "must-not-leak",
                },
            )
        )
    return config, mint


async def test_store_reader_candidates_rank_observed_mints_without_execution(
    tmp_path: Path,
) -> None:
    config, mint = _configured_candidate_store(tmp_path)
    components = build_service(config, collectors_enabled=False)
    assert isinstance(components.reader, StoreReader)
    app = create_app(
        components.reader,
        runtime=components.runtime,
        allowed_origins=config.server.allowed_origins,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inteld.local"
    ) as client:
        health = await client.get("/api/health")
        summary = await client.get("/api/intelligence/summary")
        response = await client.get("/api/intelligence/candidates")

    assert health.status_code == 503
    assert response.status_code == 200
    body = response.json()
    assert body["execution_effect"] == "none"
    assert body["items"]
    card = body["items"][0]
    assert card["mint"] == mint
    assert card["execution_effect"] == "none"
    assert card["verdict"]
    assert isinstance(card["reasons"], list)
    assert isinstance(card["scores"], dict)
    assert "candidates" in summary.json()
    assert summary.json()["candidates"][0]["mint"] == mint
    assert summary.json()["execution_effect"] == "none"
    combined = " ".join(response.text for response in (health, summary, response))
    assert "must-not-leak" not in combined
    assert "Keypair" not in combined
    components.reader.close()  # type: ignore[attr-defined]
