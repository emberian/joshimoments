from __future__ import annotations

import dataclasses
import datetime as dt
import inspect
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

UTC = dt.timezone.utc
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_CURSOR_LENGTH = 256
MAX_STRING_LENGTH = 4_096
MAX_COLLECTION_LENGTH = 500
MAX_OBJECT_DEPTH = 8
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SAFE_CURSOR = re.compile(r"^[A-Za-z0-9_=+./:-]{1,256}$")
SAFE_FILTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

_BLOCKED_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bot_token",
    "credential",
    "keypair",
    "private_key",
    "secret",
    "serialized_transaction",
    "signed_transaction",
    "transaction_bytes",
    "wallet_key",
)
_BLOCKED_KEYS = {
    "body",
    "headers",
    "http_headers",
    "payload",
    "raw",
    "raw_body",
    "raw_payload",
    "request_body",
    "response_body",
    "transaction",
    "transaction_base64",
    "tx_bytes",
}


def utc_now() -> dt.datetime:
    return dt.datetime.now(tz=UTC)


def iso_now() -> str:
    return utc_now().isoformat()


class ReaderUnavailable(RuntimeError):
    """The intelligence read model cannot currently answer a query."""


@runtime_checkable
class IntelligenceReader(Protocol):
    """Read-only projection used by the local API.

    Implementations may be synchronous or asynchronous. They should return
    already-normalized mappings, but all responses are defensively redacted by
    the API before leaving this process.
    """

    def health(self) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...

    def summary(self) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...

    def feed(
        self,
        *,
        limit: int,
        cursor: str | None,
        source: str | None,
        kind: str | None,
        severity: str | None,
    ) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...

    def get_item(self, item_id: str) -> Mapping[str, Any] | Awaitable[Mapping[str, Any] | None] | None: ...

    def get_dossier(
        self, kind: str, identifier: str
    ) -> Mapping[str, Any] | Awaitable[Mapping[str, Any] | None] | None: ...

    def sources(self) -> Sequence[Mapping[str, Any]] | Awaitable[Sequence[Mapping[str, Any]]]: ...

    def watchlists(
        self,
    ) -> Sequence[Mapping[str, Any]] | Awaitable[Sequence[Mapping[str, Any]]]: ...

    def digests(
        self, *, limit: int, cursor: str | None
    ) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...

    def candidates(self) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...


@runtime_checkable
class BackgroundRuntime(Protocol):
    """Collector coordinator owned by the intelligence process.

    A runtime implementation must funnel collector writes through its single
    designated writer. The HTTP application only starts/stops it and reads its
    public health projection.
    """

    def start(self) -> Awaitable[None] | None: ...

    def stop(self) -> Awaitable[None] | None: ...

    def health(self) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]: ...


class UnavailableReader:
    """Safe startup fallback while storage is absent or being recovered."""

    def __init__(self, reason: str = "intelligence store is not configured") -> None:
        self.reason = reason

    def health(self) -> Mapping[str, Any]:
        return {
            "ready": False,
            "writer_healthy": False,
            "quota": {"healthy": False, "used_bytes": None, "limit_bytes": None},
            "degraded_reasons": [self.reason],
        }

    def summary(self) -> Mapping[str, Any]:
        raise ReaderUnavailable(self.reason)

    def feed(self, **_kwargs: Any) -> Mapping[str, Any]:
        raise ReaderUnavailable(self.reason)

    def get_item(self, _item_id: str) -> None:
        raise ReaderUnavailable(self.reason)

    def get_dossier(self, _kind: str, _identifier: str) -> None:
        raise ReaderUnavailable(self.reason)

    def sources(self) -> Sequence[Mapping[str, Any]]:
        return []

    def watchlists(self) -> Sequence[Mapping[str, Any]]:
        return []

    def digests(self, **_kwargs: Any) -> Mapping[str, Any]:
        raise ReaderUnavailable(self.reason)

    def candidates(self) -> Mapping[str, Any]:
        raise ReaderUnavailable(self.reason)


async def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _is_blocked_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _BLOCKED_KEYS or any(part in normalized for part in _BLOCKED_KEY_PARTS)


def public_projection(value: Any, *, _depth: int = 0) -> Any:
    """Return a JSON-safe, size-bounded value with sensitive fields removed."""

    if _depth > MAX_OBJECT_DEPTH:
        return None
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:MAX_STRING_LENGTH]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in list(value.items())[:MAX_COLLECTION_LENGTH]:
            public_key = str(key)[:128]
            if _is_blocked_key(public_key):
                continue
            result[public_key] = public_projection(child, _depth=_depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | memoryview):
        return [public_projection(child, _depth=_depth + 1) for child in value[:MAX_COLLECTION_LENGTH]]
    return str(value)[:MAX_STRING_LENGTH]


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    projected = public_projection(value)
    if not isinstance(projected, dict):
        raise ReaderUnavailable(f"intelligence store returned an invalid {name} projection")
    return projected


def _as_items(value: Any, name: str) -> list[dict[str, Any]]:
    projected = public_projection(value)
    if not isinstance(projected, list) or any(not isinstance(item, dict) for item in projected):
        raise ReaderUnavailable(f"intelligence store returned an invalid {name} projection")
    return projected


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _add_security_headers(response: Response) -> Response:
    response.headers["cache-control"] = "no-store"
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["content-security-policy"] = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    return response


def _safe_health(value: Mapping[str, Any]) -> dict[str, Any]:
    projected = _as_mapping(value, "health")
    quota = projected.get("quota")
    if not isinstance(quota, dict):
        quota = {"healthy": False, "used_bytes": None, "limit_bytes": None}
    reasons = projected.get("degraded_reasons", [])
    if not isinstance(reasons, list):
        reasons = ["invalid health state"]
    return {
        **projected,
        "ready": bool(projected.get("ready", False)),
        "writer_healthy": bool(projected.get("writer_healthy", False)),
        "quota": quota,
        "degraded_reasons": [str(reason)[:256] for reason in reasons[:20]],
    }


def create_app(
    reader: IntelligenceReader | None = None,
    *,
    runtime: BackgroundRuntime | None = None,
    allowed_origins: Sequence[str] = (
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ),
) -> FastAPI:
    reader = reader or UnavailableReader()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if runtime is not None:
            await _resolve(runtime.start())
        try:
            yield
        finally:
            if runtime is not None:
                await _resolve(runtime.stop())
            close = getattr(reader, "close", None)
            if close is not None:
                await _resolve(close())

    app = FastAPI(
        title="shitcoims Intelligence local API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["accept"],
    )

    @app.middleware("http")
    async def local_read_only_boundary(request: Request, call_next: Callable[..., Awaitable[Response]]):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return _add_security_headers(
                _error_response(405, "method_not_allowed", "the intelligence API is read-only")
            )
        response = await call_next(request)
        return _add_security_headers(response)

    @app.exception_handler(ReaderUnavailable)
    async def reader_unavailable(_request: Request, _exc: ReaderUnavailable) -> JSONResponse:
        return _add_security_headers(
            _error_response(
                503,
                "intelligence_unavailable",
                "intelligence data is temporarily unavailable",
            )
        )

    @app.exception_handler(Exception)
    async def unexpected_reader_failure(_request: Request, _exc: Exception) -> JSONResponse:
        # Store/provider exceptions sometimes contain credentialed URLs or raw
        # payload fragments. Never reflect their text across the HTTP boundary.
        return _add_security_headers(
            _error_response(
                503,
                "intelligence_unavailable",
                "intelligence data is temporarily unavailable",
            )
        )

    @app.get("/api/health")
    async def health(response: Response) -> dict[str, Any]:
        reasons: list[str] = []
        try:
            store_health = _safe_health(await _resolve(reader.health()))
        except Exception:
            store_health = _safe_health({})
            reasons.append("store health unavailable")
        runtime_health: dict[str, Any] | None = None
        if runtime is not None:
            try:
                runtime_health = _as_mapping(await _resolve(runtime.health()), "runtime health")
            except Exception:
                runtime_health = {"healthy": False, "degraded_reasons": ["runtime health unavailable"]}
        reasons.extend(store_health.get("degraded_reasons", []))
        if runtime_health:
            runtime_reasons = runtime_health.get("degraded_reasons", [])
            if isinstance(runtime_reasons, list):
                reasons.extend(str(item) for item in runtime_reasons[:20])
        runtime_ok = runtime_health is None or bool(runtime_health.get("healthy", False))
        quota_ok = bool(store_health["quota"].get("healthy", False))
        writer_ok = (
            bool(runtime_health.get("writer_active"))
            if runtime_health is not None
            else bool(store_health["writer_healthy"])
        )
        healthy = bool(store_health["ready"] and writer_ok and quota_ok and runtime_ok)
        if not healthy:
            response.status_code = 503
        return {
            "healthy": healthy,
            "service": "shitcoims-intelligence",
            "mode": "READ_ONLY",
            "checked_at": iso_now(),
            "store": store_health,
            "runtime": runtime_health,
            "degraded_reasons": list(dict.fromkeys(reasons))[:20],
        }

    @app.get("/api/intelligence/summary")
    async def summary() -> dict[str, Any]:
        value = _as_mapping(await _resolve(reader.summary()), "summary")
        return {"generated_at": iso_now(), **value}

    @app.get("/feed", include_in_schema=False)
    @app.get("/api/intelligence/feed")
    async def feed(
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(None, max_length=MAX_CURSOR_LENGTH, pattern=SAFE_CURSOR.pattern),
        source: str | None = Query(None, max_length=64, pattern=SAFE_FILTER.pattern),
        kind: str | None = Query(None, max_length=64, pattern=SAFE_FILTER.pattern),
        severity: str | None = Query(None, max_length=64, pattern=SAFE_FILTER.pattern),
    ) -> dict[str, Any]:
        value = _as_mapping(
            await _resolve(
                reader.feed(
                    limit=limit,
                    cursor=cursor,
                    source=source,
                    kind=kind,
                    severity=severity,
                )
            ),
            "feed",
        )
        items = _as_items(value.get("items", []), "feed items")[:limit]
        return {
            "items": items,
            "limit": limit,
            "next_cursor": value.get("next_cursor"),
            "has_more": bool(value.get("has_more", value.get("next_cursor"))),
        }

    @app.get("/items/{item_id}", include_in_schema=False)
    @app.get("/api/intelligence/items/{item_id}")
    async def item(
        item_id: str = Path(min_length=1, max_length=128, pattern=SAFE_IDENTIFIER.pattern),
    ) -> dict[str, Any]:
        value = await _resolve(reader.get_item(item_id))
        if value is None:
            raise HTTPException(status_code=404, detail="intelligence item not found")
        return {"item": _as_mapping(value, "item")}

    @app.get("/dossiers/{kind}/{identifier}", include_in_schema=False)
    @app.get("/api/intelligence/dossiers/{kind}/{identifier}")
    async def dossier(
        kind: str = Path(min_length=1, max_length=64, pattern=SAFE_FILTER.pattern),
        identifier: str = Path(min_length=1, max_length=128, pattern=SAFE_IDENTIFIER.pattern),
    ) -> dict[str, Any]:
        value = await _resolve(reader.get_dossier(kind, identifier))
        if value is None:
            raise HTTPException(status_code=404, detail="dossier not found")
        return {"dossier": _as_mapping(value, "dossier")}

    @app.get("/sources", include_in_schema=False)
    @app.get("/api/intelligence/sources")
    async def sources() -> dict[str, Any]:
        return {"items": _as_items(await _resolve(reader.sources()), "sources")}

    @app.get("/watchlists", include_in_schema=False)
    @app.get("/api/intelligence/watchlists")
    async def watchlists() -> dict[str, Any]:
        return {"items": _as_items(await _resolve(reader.watchlists()), "watchlists")}

    @app.get("/digests", include_in_schema=False)
    @app.get("/api/intelligence/digests")
    async def digests(
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(None, max_length=MAX_CURSOR_LENGTH, pattern=SAFE_CURSOR.pattern),
    ) -> dict[str, Any]:
        value = _as_mapping(
            await _resolve(reader.digests(limit=limit, cursor=cursor)),
            "digests",
        )
        items = _as_items(value.get("items", []), "digest items")[:limit]
        return {
            "items": items,
            "limit": limit,
            "next_cursor": value.get("next_cursor"),
            "has_more": bool(value.get("has_more", value.get("next_cursor"))),
        }

    @app.get("/api/intelligence/candidates")
    async def candidates() -> dict[str, Any]:
        value = _as_mapping(await _resolve(reader.candidates()), "candidates")
        items = _as_items(value.get("items", []), "candidate items")
        return {
            "generated_at": iso_now(),
            "items": items,
            "execution_effect": "none",
        }

    return app
