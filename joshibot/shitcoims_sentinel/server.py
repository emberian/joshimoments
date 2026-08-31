from __future__ import annotations

import asyncio
import datetime as dt
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .candles import CandleError, fetch_candles
from .domain import utc_now
from .engine import SentinelEngine
from .history import performance_summary, read_events, read_trades
from .policies import (
    PolicyError,
    policies_for_unmonitored,
    policy_defaults_from_payload,
    policy_from_payload,
    policy_to_api_mapping,
)


class _TaskReentrantLock:
    """Task-reentrant view of the engine's policy lock.

    Every mutating policy route reads ``engine.config.positions``, merges, and
    then persists through ``SentinelEngine.apply_positions``. Those two steps
    have to be one atomic step against the engine's own writers: the auto-protect
    pass creates default policies for new bags on the cycle task, and an
    interleave between a handler's read and its write erases that rule from
    config.yaml, so a bag the dashboard reported as protected silently loses its
    stop.

    ``apply_positions`` acquires the same lock internally and ``asyncio.Lock`` is
    not reentrant, so a handler that simply held the raw lock across the call
    would deadlock. Re-entry is granted only to the asyncio task that already
    owns the lock, so the engine's cycle task still blocks -- which is exactly
    the exclusion the invariant needs.
    """

    __slots__ = ("_depth", "_inner", "_owner")

    def __init__(self, inner: asyncio.Lock) -> None:
        self._inner = inner
        self._owner: asyncio.Task | None = None
        self._depth = 0

    def locked(self) -> bool:
        return self._inner.locked()

    async def acquire(self) -> bool:
        task = asyncio.current_task()
        if self._depth and task is not None and task is self._owner:
            self._depth += 1
            return True
        await self._inner.acquire()
        self._owner = task
        self._depth = 1
        return True

    def release(self) -> None:
        if self._depth <= 0:
            raise RuntimeError("policy lock released more times than it was acquired")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._inner.release()

    async def __aenter__(self) -> _TaskReentrantLock:
        await self.acquire()
        return self

    async def __aexit__(self, *_exception: object) -> None:
        self.release()


def _install_reentrant_policy_lock(engine: SentinelEngine) -> _TaskReentrantLock:
    """Swap the engine's policy lock for a task-reentrant one and return it.

    Fails closed: a real ``SentinelEngine`` that no longer exposes an
    ``asyncio.Lock`` named ``_policy_lock`` means the atomicity this server
    depends on has moved, and serving a dashboard that can silently drop stops is
    worse than refusing to start.
    """
    existing = getattr(engine, "_policy_lock", None)
    if isinstance(existing, _TaskReentrantLock):
        return existing
    if isinstance(existing, asyncio.Lock):
        lock = _TaskReentrantLock(existing)
    elif isinstance(engine, SentinelEngine):
        raise RuntimeError(
            "SentinelEngine no longer exposes an asyncio _policy_lock; the dashboard's "
            "read-modify-write of config.positions cannot be made atomic"
        )
    else:
        lock = _TaskReentrantLock(asyncio.Lock())
    engine._policy_lock = lock
    return lock


def create_app(engine: SentinelEngine) -> FastAPI:
    policy_lock = _install_reentrant_policy_lock(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(engine.run(), name="shitcoims-sentinel")

        def fail_closed(completed: asyncio.Task) -> None:
            if completed.cancelled():
                return
            if completed.exception() is not None:
                # Uvicorn otherwise keeps serving a stale dashboard after its
                # protection task dies. Terminate so launchd can restart us.
                os.kill(os.getpid(), signal.SIGTERM)

        task.add_done_callback(fail_closed)
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await engine.close()

    app = FastAPI(
        title="shitcoims Sentinel local API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(engine.config.server.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["accept", "content-type"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["cache-control"] = "no-store"
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["content-security-policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' http://127.0.0.1:8788 http://localhost:8788; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/api/snapshot")
    async def snapshot():
        return await engine.snapshot()

    def _loopback(request: Request) -> None:
        host = (request.client.host if request.client else "") or ""
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=403, detail="loopback only")

    @app.get("/api/policies")
    async def policies():
        return {"items": engine.list_policies(), "can_execute": False}

    @app.put("/api/policies/{mint}")
    async def upsert_policy(mint: str, request: Request):
        _loopback(request)
        try:
            body = await request.json()
            policy = policy_from_payload(mint, body)
        except PolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            raise HTTPException(status_code=400, detail="invalid policy payload") from None
        # Read and write under one lock hold: an auto-protect rule created
        # between the two would otherwise be dropped from config.yaml.
        async with policy_lock:
            current = {item.mint: item for item in engine.config.positions}
            current[policy.mint] = policy
            items = await engine.apply_positions(
                list(current.values()), origin="operator", touch=[policy.mint]
            )
        return {"item": policy_to_api_mapping(policy), "items": items, "can_execute": False}

    @app.delete("/api/policies/{mint}")
    async def delete_policy(mint: str, request: Request):
        _loopback(request)
        async with policy_lock:
            remaining = [item for item in engine.config.positions if item.mint != mint]
            if len(remaining) == len(engine.config.positions):
                raise HTTPException(status_code=404, detail="policy not found")
            engine.skip_auto_protect(mint)
            items = await engine.apply_positions(remaining)
        return {"removed": True, "items": items, "can_execute": False}

    @app.post("/api/policies/protect-unmonitored")
    async def protect_unmonitored(request: Request):
        _loopback(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be an object")
        # Taken before the lock: snapshot() waits on the engine's snapshot lock,
        # and holding the policy lock across an unrelated wait is a deadlock the
        # merge does not need. Only `current` has to be fresh -- a stale
        # unmonitored row is skipped by policies_for_unmonitored once a policy for
        # that mint exists in `current`.
        snapshot = await engine.snapshot()
        try:
            # Any threshold the caller omits falls through to `PolicyDefaults`. This
            # endpoint used to restate -30/100/20 inline, which is how the dashboard came
            # to protect a bag under a different rule than the engine would have.
            defaults = policy_defaults_from_payload(body)
        except PolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        async with policy_lock:
            try:
                merged, created, skipped = policies_for_unmonitored(
                    unmonitored=list(snapshot.get("unmonitored") or []),
                    current=list(engine.config.positions),
                    mode=str(body.get("mode") or "rug_only"),
                    defaults=defaults,
                )
            except PolicyError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            items = (
                await engine.apply_positions(merged, origin="operator", touch=created)
                if created
                else engine.list_policies()
            )
        return {
            "created": created,
            "skipped": skipped,
            "items": items,
            "can_execute": False,
        }

    @app.post("/api/policies/{mint}/skip-auto")
    async def skip_auto_protect(mint: str, request: Request):
        _loopback(request)
        engine.skip_auto_protect(mint)
        return {"skipped": True, "mint": mint, "can_execute": False}

    @app.get("/api/events")
    async def events(limit: int = Query(200, ge=1, le=500)):
        memory = engine.journal.recent()[:limit]
        persisted = read_events(engine.config.events_file, limit=limit)
        items = memory or persisted
        return {"items": items[:limit]}

    @app.get("/api/trades")
    async def trades(limit: int = Query(200, ge=1, le=500)):
        return {"items": read_trades(engine.config.trades_file, limit=limit)}

    @app.get("/api/performance")
    async def performance():
        snapshot = await engine.snapshot()
        trades = read_trades(engine.config.trades_file, limit=500)
        events = read_events(engine.config.events_file, limit=500)
        return performance_summary(snapshot=snapshot, trades=trades, events=events)

    @app.get("/api/candles")
    async def candles(
        mint: str = Query(..., min_length=32, max_length=44),
        interval: str = Query("15m"),
        limit: int = Query(120, ge=10, le=250),
    ):
        try:
            return await fetch_candles(engine.http, mint, interval=interval, limit=limit)
        except CandleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/health")
    async def health(response: Response):
        value = await engine.snapshot()
        last_cycle = value["system"].get("last_cycle_at")
        fresh = False
        if last_cycle:
            observed = dt.datetime.fromisoformat(last_cycle)
            fresh = (utc_now() - observed).total_seconds() <= max(
                30, engine.config.poll_interval_seconds * 3
            )
        healthy = bool(
            value["system"]["running"] and value["system"]["rpc_ready"] and fresh
        )
        if not healthy:
            response.status_code = 503
        return {
            "healthy": healthy,
            "wallet": "shitcoims",
            "protection_state": value["system"]["protection_state"],
            "last_cycle_at": value["system"]["last_cycle_at"],
            "unprotected_count": value["system"].get(
                "unprotected_count", len(value.get("unmonitored") or [])
            ),
        }

    dashboard = engine.config.config_path.parent / "dist"
    if dashboard.joinpath("index.html").is_file():
        app.mount("/", StaticFiles(directory=dashboard, html=True), name="dashboard")

    return app
