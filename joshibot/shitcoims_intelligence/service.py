"""Read-only projections from the local intelligence evidence store."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .api import BackgroundRuntime, IntelligenceReader, UnavailableReader, public_projection
from .candidates import build_candidates
from .config import IntelligenceConfig
from .models import Feature, Source, SourceHealth, StoredObservation, WatchEntry, Watchlist, thaw_json
from .runtime import CollectorRuntime
from .storage import IntelligenceStorageError, IntelligenceStore, SingleWriter, StorageSummary
from .wallet_markout import summarize as summarize_wallet

MAX_DOSSIER_FEATURES = 100
MAX_DOSSIER_OBSERVATIONS = 50
MAX_WATCHLISTS = 100
MAX_SOURCES = 100
MAX_SEVERITY_SCAN = 500
MAX_SUMMARY_CANDIDATES = 12
CANDIDATE_OBSERVATION_LIMIT = 200
CANDIDATE_KOL_POST_LIMIT = 50
X_KOL_WATCHLIST_ID = "x-kols"
X_KOL_POST_KIND = "x_kol_post"
X_KOL_SUBJECT_TYPE = "kol"

_PUBLIC_DETAIL_KEYS = {
    "amount",
    "amount_lamports",
    "asset_candidates",
    "caller",
    "claim",
    "conflicts",
    "direction",
    "finality",
    "flags",
    "liquidity_sol",
    "market_cap_sol",
    "metrics",
    "mint",
    "name",
    "risk",
    "risk_flags",
    "signature",
    "slot",
    "sol_delta_lamports",
    "status",
    "symbol",
    "tags",
    "token_deltas",
    "verification_status",
    "wallet",
    "url",
    "author_username",
    "cashtags",
    "mint_candidates",
    "mentioned_handles",
    "tweet_kind",
    "classification",
    "watched_handle",
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _public_details(payload: Mapping[str, Any]) -> dict[str, Any]:
    selected = {key: value for key, value in payload.items() if key in _PUBLIC_DETAIL_KEYS}
    projected = public_projection(selected)
    return projected if isinstance(projected, dict) else {}


def _kol_handle(value: str) -> str:
    return str(value).strip().lstrip("@")[:15]


def _kol_label(reason: str, handle: str) -> str | None:
    text = reason.strip()
    if not text:
        return None
    folded = text.lower()
    handle_folded = handle.lower()
    if folded in {
        handle_folded,
        f"@{handle_folded}",
        f"configured watch for @{handle_folded}",
        f"configured watch for {handle_folded}",
    }:
        return None
    return text[:80]


def _observation_projection(observation: StoredObservation, *, detailed: bool = False) -> dict[str, Any]:
    payload = _mapping(thaw_json(observation.payload))
    result: dict[str, Any] = {
        "id": observation.observation_id,
        "kind": observation.kind,
        "source_id": observation.source_id,
        "subject_type": observation.subject_type,
        "subject_id": observation.subject_id[:512],
        "observed_at": observation.observed_at.isoformat(),
        "emitted_at": observation.emitted_at.isoformat() if observation.emitted_at else None,
        "confidence": observation.confidence,
        "finality": observation.finality.value,
        "title": str(payload.get("title", ""))[:240] or None,
        "summary": str(payload.get("summary", payload.get("claim", "")))[:1_000] or None,
        "severity": str(payload.get("severity", "info"))[:32],
        "status": str(payload.get("status", "observed"))[:64],
        "url": str(payload.get("url", ""))[:2_048] or None,
        "author_username": str(payload.get("author_username", ""))[:32] or None,
        "cashtags": [str(tag)[:16] for tag in payload.get("cashtags", ()) if tag][:8],
        "mint_candidates": [str(mint)[:64] for mint in payload.get("mint_candidates", ()) if mint][:8],
        "watched_handle": str(payload.get("watched_handle") or "")[:15] or None,
        "details": _public_details(payload),
    }
    if detailed:
        result.update(
            {
                "parser_version": observation.parser_version,
                # Source-native identifiers and free-form provenance may be
                # credentialed URLs. Keep useful cardinality without exposing
                # those opaque collector inputs through HTTP.
                "provenance_count": len(observation.provenance),
                "retention_class": observation.retention_class,
                "content_hash": observation.content_hash,
            }
        )
    return result


def _feature_projection(feature: Feature) -> dict[str, Any]:
    return {
        "id": feature.feature_id,
        "key": feature.feature_key,
        "value": public_projection(thaw_json(feature.value)),
        "computed_at": feature.computed_at.isoformat(),
        "valid_until": feature.valid_until.isoformat() if feature.valid_until else None,
        "model_version": feature.model_version,
        "confidence": feature.confidence,
        "evidence_observation_ids": list(feature.evidence_observation_ids[:256]),
    }


def _source_projection(source: Source, health: SourceHealth | None) -> dict[str, Any]:
    return {
        "id": source.source_id,
        "name": source.display_name,
        "kind": source.kind,
        "enabled": source.enabled,
        "trust_tier": source.trust_tier,
        "status": health.status.value if health else "unknown",
        "healthy": bool(health and health.status.value == "healthy"),
        "checked_at": health.checked_at.isoformat() if health else None,
        "last_success_at": (
            health.last_success_at.isoformat() if health and health.last_success_at else None
        ),
        "latency_ms": health.latency_ms if health else None,
        "error_code": health.error_code if health else None,
    }


@dataclass(slots=True)
class ReadOnlyRuntime(BackgroundRuntime):
    """Honest placeholder until the single-writer collector coordinator lands."""

    collectors_requested: bool

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def health(self) -> Mapping[str, Any]:
        reason = (
            "collector coordinator is not configured"
            if self.collectors_requested
            else "collectors were disabled by the operator"
        )
        return {
            "healthy": False,
            "writer_active": False,
            "collectors_active": 0,
            "degraded_reasons": [reason],
        }


class StoreReader(IntelligenceReader):
    def __init__(self, store: IntelligenceStore) -> None:
        if not store.read_only:
            raise ValueError("the intelligence HTTP reader requires a read-only store")
        self.store = store

    def close(self) -> None:
        self.store.close()

    def _storage(self) -> StorageSummary:
        return self.store.storage_summary()

    def health(self) -> Mapping[str, Any]:
        storage = self._storage()
        reasons: list[str] = []
        if storage.warning:
            reasons.append("intelligence storage has crossed its warning threshold")
        if storage.quota_exceeded:
            reasons.append("intelligence storage quota is exhausted")
        return {
            "ready": True,
            # Writer liveness is reported by BackgroundRuntime.health()["writer_active"],
            # not by the reader. This process's StoreReader is not the writer.
            "writer_healthy": False,
            "database": {
                "schema_version": storage.schema_version,
                "journal_mode": storage.journal_mode,
                "observations": storage.observations,
            },
            "quota": {
                "healthy": not storage.quota_exceeded,
                "warning": storage.warning,
                "used_bytes": storage.database_bytes,
                "warning_bytes": storage.warning_bytes,
                "limit_bytes": storage.limit_bytes,
            },
            "degraded_reasons": reasons,
        }

    def summary(self) -> Mapping[str, Any]:
        storage = self._storage()
        latest = self.store.list_observations(limit=100)
        sources = self.store.list_sources()
        kinds = Counter(observation.kind for observation in latest.items)
        return {
            "mode": "READ_ONLY",
            "totals": {
                "observations": storage.observations,
                "features": storage.features,
                "watch_entries": storage.watch_entries,
                "sources": len(sources),
                "conflicts": storage.conflicts,
            },
            "latest_observed_at": (latest.items[0].observed_at.isoformat() if latest.items else None),
            "recent_kinds": dict(kinds.most_common(20)),
            "storage": {
                "database_bytes": storage.database_bytes,
                "warning_bytes": storage.warning_bytes,
                "limit_bytes": storage.limit_bytes,
                "warning": storage.warning,
                "quota_exceeded": storage.quota_exceeded,
            },
            "kols": self._kols_projection(latest.items),
            "wallet_markouts": self._wallet_markouts(),
            "candidates": list(self._candidate_cards()[:MAX_SUMMARY_CANDIDATES]),
            "execution_effect": "none",
        }

    def candidates(self) -> Mapping[str, Any]:
        return {
            "items": list(self._candidate_cards()),
            "execution_effect": "none",
        }

    def _candidate_cards(self) -> tuple[dict[str, Any], ...]:
        latest = self.store.list_observations(limit=CANDIDATE_OBSERVATION_LIMIT)
        kol_posts = self.store.list_observations(kind=X_KOL_POST_KIND, limit=CANDIDATE_KOL_POST_LIMIT)
        seen: set[str] = set()
        observations: list[StoredObservation] = []
        for item in (*latest.items, *kol_posts.items):
            if item.observation_id in seen:
                continue
            seen.add(item.observation_id)
            observations.append(item)
        # Intel does not know the live wallet. wallet_markouts are advisory
        # flow counts, not holdings — held_mints stays empty.
        return build_candidates(observations=observations, held_mints=())

    def _wallet_markouts(self) -> list[dict[str, Any]]:
        page = self.store.list_observations(kind="wallet_transaction", limit=200)
        grouped: dict[str, list[Any]] = {}
        for observation in page.items:
            grouped.setdefault(observation.subject_id, []).append(observation)
        return [asdict(summarize_wallet(wallet, rows)) for wallet, rows in grouped.items()]

    def feed(
        self,
        *,
        limit: int,
        cursor: str | None,
        source: str | None,
        kind: str | None,
        severity: str | None,
    ) -> Mapping[str, Any]:
        if severity is None:
            page = self.store.list_observations(
                limit=limit,
                cursor=cursor,
                source_id=source,
                kind=kind,
            )
            items = [_observation_projection(observation) for observation in page.items]
            return {"items": items, "next_cursor": page.next_cursor}

        items: list[dict[str, Any]] = []
        scan_cursor = cursor
        next_cursor: str | None = None
        remaining_scan = MAX_SEVERITY_SCAN
        while len(items) < limit and remaining_scan:
            batch_size = min(100, remaining_scan)
            page = self.store.list_observations(
                limit=batch_size,
                cursor=scan_cursor,
                source_id=source,
                kind=kind,
            )
            for observation in page.items:
                projected = _observation_projection(observation)
                if projected["severity"] == severity:
                    items.append(projected)
                    if len(items) == limit:
                        break
            remaining_scan -= len(page.items)
            next_cursor = page.next_cursor
            if len(items) == limit or page.next_cursor is None:
                break
            scan_cursor = page.next_cursor
        return {"items": items, "next_cursor": next_cursor}

    def get_item(self, item_id: str) -> Mapping[str, Any] | None:
        observation = self.store.get_observation(item_id)
        return None if observation is None else _observation_projection(observation, detailed=True)

    def get_dossier(self, kind: str, identifier: str) -> Mapping[str, Any] | None:
        features = self.store.list_features(kind, identifier, limit=MAX_DOSSIER_FEATURES)
        observations = self.store.list_observations(
            limit=MAX_DOSSIER_OBSERVATIONS,
            subject_type=kind,
            subject_id=identifier,
        )
        watched = self._watched_kol(identifier) if kind == X_KOL_SUBJECT_TYPE else None
        if not features and not observations.items and watched is None:
            return None
        confidence_values = [feature.confidence for feature in features]
        confidence_values.extend(item.confidence for item in observations.items)
        timestamps = [feature.computed_at for feature in features]
        timestamps.extend(item.observed_at for item in observations.items)
        if timestamps:
            updated_at = max(timestamps).isoformat()
        elif watched is not None:
            updated_at = watched.added_at.isoformat()
        else:
            return None
        return {
            "kind": kind,
            "id": identifier,
            "confidence": (sum(confidence_values) / len(confidence_values) if confidence_values else 0),
            "features": [_feature_projection(feature) for feature in features],
            "recent_items": [_observation_projection(item) for item in observations.items],
            "next_cursor": observations.next_cursor,
            "updated_at": updated_at,
            "execution_effect": "none",
        }

    def _watched_kol(self, identifier: str) -> WatchEntry | None:
        wanted = _kol_handle(identifier).lower()
        if not wanted:
            return None
        for entry in self.store.list_watch_entries(X_KOL_WATCHLIST_ID):
            if entry.subject_type != X_KOL_SUBJECT_TYPE:
                continue
            if _kol_handle(entry.subject_id).lower() == wanted:
                return entry
        return None

    def _kols_projection(self, latest: tuple[StoredObservation, ...]) -> list[dict[str, Any]]:
        aggregated: dict[str, dict[str, Any]] = {}
        order: list[str] = []

        def row_for(handle: str) -> dict[str, Any]:
            key = handle.lower()
            existing = aggregated.get(key)
            if existing is not None:
                return existing
            created = {"handle": handle, "last_seen": None, "posts": 0}
            aggregated[key] = created
            order.append(key)
            return created

        for entry in self.store.list_watch_entries(X_KOL_WATCHLIST_ID):
            if entry.subject_type != X_KOL_SUBJECT_TYPE:
                continue
            handle = _kol_handle(entry.subject_id)
            if not handle:
                continue
            row = row_for(handle)
            label = _kol_label(entry.reason, handle)
            if label:
                row["label"] = label

        for observation in latest:
            if observation.kind != X_KOL_POST_KIND:
                continue
            payload = _mapping(thaw_json(observation.payload))
            handle = _kol_handle(
                str(payload.get("watched_handle") or "")
                or (observation.subject_id if observation.subject_type == X_KOL_SUBJECT_TYPE else "")
            )
            if not handle:
                continue
            row = row_for(handle)
            row["posts"] += 1
            seen = observation.observed_at
            previous = row["last_seen"]
            if previous is None or seen > previous:
                row["last_seen"] = seen

        result: list[dict[str, Any]] = []
        for key in order:
            row = dict(aggregated[key])
            last_seen = row["last_seen"]
            row["last_seen"] = last_seen.isoformat() if last_seen is not None else None
            result.append(row)
        return result

    def sources(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            _source_projection(source, health) for source, health in self.store.list_sources()[:MAX_SOURCES]
        )

    def watchlists(self) -> tuple[Mapping[str, Any], ...]:
        result: list[Mapping[str, Any]] = []
        for watchlist in self.store.list_watchlists()[:MAX_WATCHLISTS]:
            result.append(self._watchlist_projection(watchlist))
        return tuple(result)

    def _watchlist_projection(self, watchlist: Watchlist) -> Mapping[str, Any]:
        entries = self.store.list_watch_entries(watchlist.watchlist_id)
        types = Counter(entry.subject_type for entry in entries)
        return {
            "id": watchlist.watchlist_id,
            "name": watchlist.name,
            "description": watchlist.description,
            "member_count": len(entries),
            "member_types": dict(types.most_common(20)),
            "max_entries": watchlist.max_entries,
            "created_at": watchlist.created_at.isoformat(),
        }

    def digests(self, *, limit: int, cursor: str | None) -> Mapping[str, Any]:
        page = self.store.list_observations(limit=limit, cursor=cursor, kind="digest")
        return {
            "items": [_observation_projection(item, detailed=True) for item in page.items],
            "next_cursor": page.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class ServiceComponents:
    config: IntelligenceConfig
    reader: IntelligenceReader
    runtime: BackgroundRuntime


def build_service(config: IntelligenceConfig, *, collectors_enabled: bool = True) -> ServiceComponents:
    writer = SingleWriter.from_config(config)
    runtime: BackgroundRuntime = CollectorRuntime(
        config, writer, collectors_requested=collectors_enabled
    )
    try:
        if collectors_enabled:
            # Ensure the schema exists before the HTTP reader opens read-only.
            with IntelligenceStore.from_config(config, read_only=False):
                pass
        store = IntelligenceStore.from_config(config, read_only=True)
    except (OSError, sqlite3.Error, IntelligenceStorageError):
        reader: IntelligenceReader = UnavailableReader(
            "intelligence database is unavailable or has not been initialized"
        )
    else:
        reader = StoreReader(store)
    return ServiceComponents(config=config, reader=reader, runtime=runtime)
