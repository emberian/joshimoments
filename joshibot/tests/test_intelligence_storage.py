from __future__ import annotations

import os
import sqlite3
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shitcoims_intelligence.config import IntelligenceConfigError, load_intelligence_config
from shitcoims_intelligence.models import (
    Cursor,
    Feature,
    Finality,
    Observation,
    RawBlob,
    Source,
    WatchEntry,
    Watchlist,
    request_fingerprint,
)
from shitcoims_intelligence.storage import (
    CursorConflict,
    ImmutableConflict,
    IntelligenceStore,
    SingleWriter,
)

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def source() -> Source:
    return Source("helius", "chain", "Helius RPC", trust_tier=4, created_at=NOW)


def observation(
    native_id: str = "signature:0", *, payload: dict | None = None, raw_blob_ids: tuple[str, ...] = ()
) -> Observation:
    return Observation(
        source_id="helius",
        source_native_id=native_id,
        kind="wallet.token_delta",
        subject_type="wallet",
        subject_id="wallet-public-address",
        observed_at=NOW,
        emitted_at=NOW - timedelta(seconds=1),
        payload=payload or {"mint": "mint-address", "delta": "100"},
        confidence=1,
        finality=Finality.FINALIZED,
        parser_version="helius-v1",
        provenance=("signature",),
        raw_blob_ids=raw_blob_ids,
    )


def test_models_are_frozen_and_nested_json_is_immutable() -> None:
    item = observation(payload={"nested": {"values": [1, 2]}})
    with pytest.raises(TypeError):
        item.payload["nested"] = {}  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        item.kind = "changed"  # type: ignore[misc]


def test_store_uses_strict_schema_private_file_and_rollback_journal(tmp_path: Path) -> None:
    path = tmp_path / "intelligence_state" / "intelligence.sqlite3"
    with IntelligenceStore(path) as store:
        assert store.journal_mode == "DELETE"
        assert store.integrity_check()
        strict = store._connection.execute(
            "SELECT strict FROM pragma_table_list WHERE name='observations'"
        ).fetchone()[0]
        assert strict == 1
    assert os.stat(path).st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_raw_blob_dedupe_round_trip_and_observation_reference(tmp_path: Path) -> None:
    with IntelligenceStore(tmp_path / "intelligence.sqlite3") as store:
        store.register_source(source())
        body = b'{"jsonrpc":"2.0","result":[' + b'"transaction",' * 500 + b'null]}'
        blob = RawBlob(
            "helius",
            request_fingerprint("helius", "getTransactionsForAddress", {"wallet": "public"}),
            NOW,
            "helius-v1",
            body,
        )
        first = store.record_raw_blob(blob)
        second = store.record_raw_blob(blob)
        assert first.inserted is True and second.inserted is False
        assert first.stored_bytes < first.original_bytes
        assert store.get_raw_blob(first.raw_blob_id) == blob

        inserted = store.record_observation(observation(raw_blob_ids=(first.raw_blob_id,)))
        stored = store.get_observation(inserted.observation_id)
        assert stored is not None
        assert stored.raw_blob_ids == (first.raw_blob_id,)


def test_observation_exact_dedupe_and_conflicting_source_claims_are_preserved(
    tmp_path: Path,
) -> None:
    with IntelligenceStore(tmp_path / "intelligence.sqlite3") as store:
        store.register_source(source())
        first = store.record_observation(observation())
        duplicate = store.record_observation(observation())
        changed = store.record_observation(observation(payload={"mint": "mint-address", "delta": "99"}))
        assert first.inserted is True
        assert duplicate.inserted is False
        assert duplicate.observation_id == first.observation_id
        assert changed.inserted is True and changed.conflict is True
        summary = store.storage_summary()
        assert summary.observations == 2
        assert summary.conflicts == 1


def test_explicit_identifier_collision_is_rejected(tmp_path: Path) -> None:
    with IntelligenceStore(tmp_path / "intelligence.sqlite3") as store:
        store.register_source(source())
        original = observation(payload={"value": 1})
        original = Observation(
            **{
                name: getattr(original, name)
                for name in original.__dataclass_fields__
                if name != "observation_id"
            },
            observation_id="obs_fixed",
        )
        store.record_observation(original)
        conflicting = observation(payload={"value": 2})
        conflicting = Observation(
            **{
                name: getattr(conflicting, name)
                for name in conflicting.__dataclass_fields__
                if name != "observation_id"
            },
            observation_id="obs_fixed",
        )
        with pytest.raises(ImmutableConflict):
            store.record_observation(conflicting)


def test_feed_cursor_is_stable_and_filters_subject(tmp_path: Path) -> None:
    with IntelligenceStore(tmp_path / "intelligence.sqlite3") as store:
        store.register_source(source())
        for index in range(5):
            item = observation(f"signature:{index}")
            item = Observation(
                **{
                    name: getattr(item, name)
                    for name in item.__dataclass_fields__
                    if name not in {"observation_id", "observed_at"}
                },
                observed_at=NOW + timedelta(seconds=index),
            )
            store.record_observation(item)
        first = store.list_observations(limit=2, subject_type="wallet")
        second = store.list_observations(limit=2, cursor=first.next_cursor, subject_type="wallet")
        third = store.list_observations(limit=2, cursor=second.next_cursor, subject_type="wallet")
        ids = [item.source_native_id for page in (first, second, third) for item in page.items]
        assert ids == [f"signature:{index}" for index in (4, 3, 2, 1, 0)]
        assert third.next_cursor is None


def test_cursor_optimistic_generation_prevents_lost_updates(tmp_path: Path) -> None:
    with IntelligenceStore(tmp_path / "intelligence.sqlite3") as store:
        store.register_source(source())
        first = store.set_cursor(Cursor("helius", "wallet-history", {"page": "one"}, NOW))
        assert first.generation == 1
        second = store.set_cursor(
            Cursor("helius", "wallet-history", {"page": "two"}, NOW),
            expected_generation=1,
        )
        assert second.generation == 2
        with pytest.raises(CursorConflict):
            store.set_cursor(
                Cursor("helius", "wallet-history", {"page": "stale"}, NOW),
                expected_generation=1,
            )


def test_watchlists_and_features_retain_explicit_evidence(tmp_path: Path) -> None:
    with IntelligenceStore(tmp_path / "intelligence.sqlite3") as store:
        store.register_source(source())
        result = store.record_observation(observation())
        store.create_watchlist(Watchlist("hot-wallets", "Hot wallets", max_entries=1, created_at=NOW))
        assert store.add_watch(
            WatchEntry(
                "hot-wallets",
                "wallet",
                "wallet-public-address",
                "seed wallet",
                NOW,
                discovery_observation_id=result.observation_id,
                priority=80,
            )
        )
        feature = Feature(
            "wallet",
            "wallet-public-address",
            "copyable-markout-30s",
            {"sol": "0.01"},
            NOW,
            "markout-v1",
            0.6,
            (result.observation_id,),
        )
        feature_id, inserted = store.record_feature(feature)
        assert inserted and feature_id.startswith("feat_")
        assert store.list_features("wallet", "wallet-public-address")[0].feature_id == feature_id
        assert store.list_watch_entries("hot-wallets")[0].priority == 80


def test_single_writer_owns_writable_connection(tmp_path: Path) -> None:
    path = tmp_path / "intelligence.sqlite3"
    with SingleWriter(path, queue_capacity=10) as writer:
        assert writer.register_source(source()).result(timeout=3) is True
        result = writer.record_observation(observation()).result(timeout=3)
        assert result.inserted is True
    with IntelligenceStore(path, read_only=True) as reader:
        assert reader.storage_summary().observations == 1


def test_config_defaults_are_isolated_and_reject_wal_or_sentinel_state(tmp_path: Path) -> None:
    path = tmp_path / "intelligence.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    config = load_intelligence_config(path)
    assert config.database.path.parent == tmp_path / "intelligence_state"
    assert config.database.journal_mode == "DELETE"
    assert config.retention.max_disk_bytes == 5 * 1024**3
    assert config.scout.enabled is False

    path.write_text("version: 1\ndatabase:\n  journal_mode: WAL\n", encoding="utf-8")
    with pytest.raises(IntelligenceConfigError, match="WAL is forbidden"):
        load_intelligence_config(path)
    path.write_text("version: 1\ndatabase:\n  path: ./state/intelligence.sqlite3\n", encoding="utf-8")
    with pytest.raises(IntelligenceConfigError, match="Sentinel"):
        load_intelligence_config(path)


def test_request_fingerprint_rejects_credential_material() -> None:
    with pytest.raises(ValueError, match="credentials"):
        request_fingerprint("helius", "history", {"x-api-key": "do-not-store"})
