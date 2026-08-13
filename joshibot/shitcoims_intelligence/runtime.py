"""Single-writer collector coordinator for advisory intelligence sources."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx

from .adapters.claudekol import SOURCE_ID as CLAUDEKOL_SOURCE_ID
from .adapters.claudekol import ClaudeKolAdapter
from .adapters.x_apify import (
    SOURCE_ID as X_SOURCE_ID,
)
from .adapters.x_apify import (
    XApifyAdapter,
    XApifyConfig,
    XTweetBatch,
    tweet_to_observations,
)
from .api import BackgroundRuntime
from .claudekol_collect import observations_from_batch
from .collector import (
    BoundedHistoryCollector,
    CanonicalObservationSink,
    CreditLedger,
    CreditLimits,
    mint_tape_observation,
)
from .config import IntelligenceConfig
from .helius import HeliusHistoryClient, HeliusIntelligenceError, HistoryBounds
from .helius_live import run_helius_live
from .kol_wallets import (
    KOL_WALLET_SOURCE_ID,
    observations_for_declared_wallets,
    wallets_from_kols,
    watch_entries_for_kols,
)
from .kol_wallets import (
    watchlist as kol_wallet_watchlist,
)
from .models import Cursor, HealthStatus, Source, SourceHealth, WatchEntry, Watchlist, thaw_json, utc_now
from .storage import ImmutableConflict, IntelligenceStore, SingleWriter
from .tape import (
    TapePrint,
    features_from_prints,
    holder_features,
    merge_feature_bags,
    prints_from_history_tx,
)

LOGGER = logging.getLogger("shitcoims.intelligence.runtime")
X_WATCHLIST_ID = "x-discovered-mints"
X_KOL_WATCHLIST_ID = "x-kols"
WRITE_TIMEOUT_SECONDS = 20
# Wall budget for the X query slice only. Catalog, ClaudeKOL, and Helius always
# run after X stops; they are local/bounded and must not be starved.
CYCLE_BUDGET_SECONDS = 90
QUERY_TIMEOUT_SECONDS = 20
STUCK_CYCLE_SECONDS = 180
# Mint-tape slice: never starve the rest of the cycle. Hard cap, not a ledger.
MINT_TAPE_MAX_MINTS = 6
MINT_TAPE_WALL_SECONDS = 15.0
MINT_TAPE_PAGE_LIMIT = 20
MINT_TAPE_PENDING_CAP = 32
_MINT_DISCOVERY_KINDS = ("x_mint_mention", "x_kol_post")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


@dataclass(slots=True)
class CollectorRuntime(BackgroundRuntime):
    """Owns the writable store and periodically ingests advisory sources."""

    config: IntelligenceConfig
    writer: SingleWriter
    collectors_requested: bool = True
    _query_timeout_seconds: float = QUERY_TIMEOUT_SECONDS
    _cycle_budget_seconds: float = CYCLE_BUDGET_SECONDS
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _live_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _http: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _started_at: datetime | None = field(default=None, init=False)
    _last_cycle_at: datetime | None = field(default=None, init=False)
    _cycle_started_at: datetime | None = field(default=None, init=False)
    _last_error: str | None = field(default=None, init=False)
    _cycles: int = field(default=0, init=False)
    _x_items_today: int = field(default=0, init=False)
    _x_day: date | None = field(default=None, init=False)
    _last_cycle_partial: bool = field(default=False, init=False)
    # Last-cycle count of adapter.search calls that hit QUERY_TIMEOUT_SECONDS.
    # Reset at the start of each _cycle so health reflects the cycle just run.
    _x_query_timeouts: int = field(default=0, init=False)
    # Index into the combined (queries + kols) work list. The next cycle
    # continues here instead of restarting at query 0 / the first KOL.
    _x_resume_index: int = field(default=0, init=False)
    _x_hit_budget: bool = field(default=False, init=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _mint_tape_fetched: set[str] = field(default_factory=set, init=False, repr=False)
    _pending_tape_mints: list[str] = field(default_factory=list, init=False, repr=False)

    async def start(self) -> None:
        self._started_at = utc_now()
        self._stop = asyncio.Event()
        if not self.collectors_requested:
            return
        self.writer.start()
        self._http = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(90, connect=5))
        await self._ensure_catalog()
        self._task = asyncio.create_task(self._loop(), name="shitcoims-intelligence-collectors")
        self._live_task = asyncio.create_task(self._run_live(), name="shitcoims-helius-live")

    async def stop(self) -> None:
        self._stop.set()
        for task_name in ("_task", "_live_task"):
            task = getattr(self, task_name)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                setattr(self, task_name, None)
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        if self.collectors_requested:
            self.writer.close()

    def health(self) -> Mapping[str, Any]:
        reasons: list[str] = []
        if not self.collectors_requested:
            reasons.append("collectors were disabled by the operator")
        now = utc_now()
        started = self._cycle_started_at
        last = self._last_cycle_at
        if (
            started is not None
            and (now - started).total_seconds() >= STUCK_CYCLE_SECONDS
            and (last is None or last < started)
        ):
            self._last_error = "collection cycle appears stuck"
        if self._last_error:
            reasons.append(self._last_error)
        if self._last_cycle_partial:
            reasons.append("last collection cycle was partial")
        writers_live = self.writer._started and not self.writer._closed
        # A live first cycle with last_cycle_at=None is not itself unhealthy.
        # Stuck cycles degrade (reason + last_error) without flipping healthy.
        return {
            "healthy": writers_live and (not self.collectors_requested or self._task is not None),
            "writer_active": writers_live,
            "collectors_active": int(self._task is not None) + int(self._live_task is not None),
            "helius_live": self._live_task is not None and not self._live_task.done(),
            "started_at": _iso(self._started_at),
            "last_cycle_at": _iso(self._last_cycle_at),
            "cycle_started_at": _iso(self._cycle_started_at),
            "cycle_in_progress": self._cycle_started_at is not None,
            "last_cycle_partial": self._last_cycle_partial,
            "last_error": self._last_error,
            "cycles": self._cycles,
            "x_items_today": self._x_items_today,
            "x_query_timeouts": self._x_query_timeouts,
            "x_resume_index": self._x_resume_index,
            "degraded_reasons": reasons,
        }

    async def _run_live(self) -> None:
        async def record(observation):
            await asyncio.to_thread(
                self.writer.record_observation(observation).result,
                WRITE_TIMEOUT_SECONDS,
            )

        try:
            await run_helius_live(self.config, record, self._stop)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Helius live stream failed")
            self._last_error = "helius live stream failed"

    async def run_once(self) -> Mapping[str, Any]:
        """Run one collection cycle. Used by ``--ingest-once`` and tests."""

        if self._http is None:
            self._http = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(90, connect=5))
        return await self._cycle()

    async def _loop(self) -> None:
        interval = self.config.adapters.x_apify.poll_interval_seconds
        try:
            while not self._stop.is_set():
                try:
                    await self._cycle()
                except Exception:
                    LOGGER.exception("intelligence collection cycle failed")
                    self._last_error = "collection cycle failed"
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise

    async def _cycle(self) -> Mapping[str, Any]:
        summary: dict[str, Any] = {"x_inserted": 0, "x_seen": 0, "x_quarantined": 0}
        self._cycle_started_at = utc_now()
        self._x_query_timeouts = 0
        self._x_hit_budget = False
        try:
            await self._ensure_catalog()
            if self.config.adapters.x_apify.enabled:
                try:
                    summary.update(await self._collect_x())
                except Exception as exc:
                    LOGGER.exception("X collection failed")
                    self._last_error = f"x adapter failed ({type(exc).__name__})"
            if self.config.adapters.claudekol.enabled:
                try:
                    summary.update(await self._collect_claudekol())
                except Exception:
                    LOGGER.exception("ClaudeKOL collection failed")
            try:
                summary.update(await self._collect_helius())
            except Exception:
                LOGGER.exception("Helius collection failed")
            try:
                summary.update(await self._collect_mint_tape())
            except Exception:
                LOGGER.exception("Helius mint-tape collection failed")
            return summary
        finally:
            # Partial cycles count. The clock ticks even when a source raises.
            self._last_cycle_partial = self._x_hit_budget
            self._cycles += 1
            self._last_cycle_at = utc_now()
            self._cycle_started_at = None

    async def _ensure_catalog(self) -> None:
        now = utc_now()
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.register_source(
                    Source(
                        CLAUDEKOL_SOURCE_ID,
                        "social",
                        "ClaudeKOL public actions",
                        enabled=self.config.adapters.claudekol.enabled,
                        trust_tier=1,
                        metadata={"contract": "reverse_engineered_public_client"},
                        created_at=now,
                    )
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.register_source(
                    Source(
                        "helius",
                        "chain",
                        "Helius history",
                        enabled=True,
                        trust_tier=4,
                        metadata={"contract": "documented_rpc"},
                        created_at=now,
                    )
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.register_source(
                    Source(
                        X_SOURCE_ID,
                        "social",
                        "Apify X search",
                        enabled=self.config.adapters.x_apify.enabled,
                        trust_tier=1,
                        metadata={"contract": "paid_third_party_scraper"},
                        created_at=now,
                    )
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.submit(
                    "create_watchlist",
                    Watchlist(
                        X_WATCHLIST_ID,
                        "X discovered mints",
                        "Mints extracted from X URLs, never from cashtags.",
                        2_000,
                        now,
                    ),
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.submit(
                    "create_watchlist",
                    Watchlist(
                        X_KOL_WATCHLIST_ID,
                        "X KOL watches",
                        "Configured X accounts. Posts are claims, not fills.",
                        200,
                        now,
                    ),
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )
        for kol in self.config.adapters.x_apify.kols:
            entry = WatchEntry(
                X_KOL_WATCHLIST_ID,
                "kol",
                kol.handle,
                kol.label,
                now,
                discovery_observation_id=None,
                priority=70,
            )
            with contextlib.suppress(ImmutableConflict, Exception):
                await asyncio.to_thread(
                    self.writer.submit("add_watch", entry).result,
                    WRITE_TIMEOUT_SECONDS,
                )
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.register_source(
                    Source(
                        KOL_WALLET_SOURCE_ID,
                        "config",
                        "Configured KOL wallets",
                        enabled=True,
                        trust_tier=1,
                        metadata={"contract": "operator_declared_claim"},
                        created_at=now,
                    )
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )
        with contextlib.suppress(ImmutableConflict):
            await asyncio.to_thread(
                self.writer.submit("create_watchlist", kol_wallet_watchlist(now)).result,
                WRITE_TIMEOUT_SECONDS,
            )
        for entry in watch_entries_for_kols(self.config.adapters.x_apify.kols, now=now):
            with contextlib.suppress(ImmutableConflict, Exception):
                await asyncio.to_thread(
                    self.writer.submit("add_watch", entry).result,
                    WRITE_TIMEOUT_SECONDS,
                )
        for observation in observations_for_declared_wallets(
            self.config.adapters.x_apify.kols, now=now
        ):
            with contextlib.suppress(ImmutableConflict, Exception):
                await asyncio.to_thread(
                    self.writer.record_observation(observation).result,
                    WRITE_TIMEOUT_SECONDS,
                )

    def _roll_x_budget(self) -> None:
        today = utc_now().date()
        if self._x_day != today:
            self._x_day = today
            self._x_items_today = 0

    def _x_primary_work(self) -> list[tuple[str, Any]]:
        cfg = self.config.adapters.x_apify
        work: list[tuple[str, Any]] = [("query", query) for query in cfg.queries]
        work.extend(("kol", kol) for kol in cfg.kols)
        return work

    def _x_over_budget(self, slice_started: datetime) -> bool:
        return (utc_now() - slice_started).total_seconds() >= self._cycle_budget_seconds

    async def _search_x(
        self, adapter: XApifyAdapter, query: str, *, max_items: int
    ) -> XTweetBatch | None:
        """Call adapter.search with a per-query timeout. None means timed out."""

        try:
            return await asyncio.wait_for(
                adapter.search(query, max_items=max_items),
                timeout=self._query_timeout_seconds,
            )
        except TimeoutError:
            self._x_query_timeouts += 1
            self._last_error = "x query timed out"
            LOGGER.warning("X query timed out: %s", query[:80])
            return None

    async def _ingest_x_batch(
        self, batch: XTweetBatch, *, watched_handle: str | None = None
    ) -> tuple[int, int, int]:
        seen = len(batch.results)
        quarantined = len(batch.quarantined)
        self._x_items_today += seen
        inserted = await self._store_tweets(batch.results, watched_handle=watched_handle)
        return seen, quarantined, inserted

    async def _collect_x(self) -> Mapping[str, int]:
        assert self._http is not None
        cfg = self.config.adapters.x_apify
        self._roll_x_budget()
        remaining = cfg.max_items_per_day - self._x_items_today
        if remaining <= 0:
            self._last_error = "daily X item budget exhausted"
            await self._mark_x(HealthStatus.DEGRADED, "daily_budget_exhausted")
            return {"x_inserted": 0, "x_seen": 0, "x_quarantined": 0, "x_budget_remaining": 0}

        adapter = XApifyAdapter(
            XApifyConfig(
                enabled=True,
                token_file=cfg.token_file,
                actor_id=cfg.actor_id,
                max_items_per_query=min(cfg.max_items_per_query, remaining),
            ),
            self._http,
        )
        inserted = 0
        seen = 0
        quarantined = 0
        started = utc_now()
        work = self._x_primary_work()
        completed_rotation = True
        try:
            if work:
                n = len(work)
                idx = self._x_resume_index % n
                start = idx
                while True:
                    if self._x_over_budget(started):
                        self._x_hit_budget = True
                        completed_rotation = False
                        break
                    self._roll_x_budget()
                    remaining = cfg.max_items_per_day - self._x_items_today
                    if remaining <= 0:
                        completed_rotation = False
                        break
                    kind, payload = work[idx]
                    if kind == "query":
                        take = min(cfg.max_items_per_query, remaining)
                        batch = await self._search_x(adapter, payload, max_items=take)
                        if batch is not None:
                            more_seen, more_q, more_ins = await self._ingest_x_batch(batch)
                            seen += more_seen
                            quarantined += more_q
                            inserted += more_ins
                    else:
                        kol = payload
                        take = min(kol.max_items, cfg.max_items_per_query, remaining)
                        batch = await self._search_x(
                            adapter, f"from:{kol.handle}", max_items=take
                        )
                        if batch is not None:
                            more_seen, more_q, more_ins = await self._ingest_x_batch(
                                batch, watched_handle=kol.handle
                            )
                            seen += more_seen
                            quarantined += more_q
                            inserted += more_ins
                            if kol.follow_replies and cfg.kol_thread_limit > 0:
                                extra = await self._collect_x_threads(
                                    adapter, kol, batch, started
                                )
                                seen += extra[0]
                                quarantined += extra[1]
                                inserted += extra[2]
                    idx = (idx + 1) % n
                    self._x_resume_index = idx
                    if idx == start:
                        break
            latency_ms = (utc_now() - started).total_seconds() * 1_000
            if self._x_query_timeouts or self._x_hit_budget or not completed_rotation:
                error_code = (
                    "x_query_timeout"
                    if self._x_query_timeouts
                    else "cycle_budget_exhausted"
                    if self._x_hit_budget
                    else "daily_budget_exhausted"
                )
                await self._mark_x(HealthStatus.DEGRADED, error_code, latency_ms=latency_ms)
                if not self._last_error and self._x_hit_budget:
                    self._last_error = "x cycle budget exhausted"
            else:
                await self._mark_x(HealthStatus.HEALTHY, None, latency_ms=latency_ms)
                self._last_error = None
        except Exception as exc:
            self._last_error = f"x adapter failed ({type(exc).__name__})"
            await self._mark_x(HealthStatus.DOWN, type(exc).__name__)
            LOGGER.warning("X collection failed: %s", type(exc).__name__)
        return {
            "x_inserted": inserted,
            "x_seen": seen,
            "x_quarantined": quarantined,
            "x_budget_remaining": max(cfg.max_items_per_day - self._x_items_today, 0),
        }

    async def _collect_x_threads(
        self,
        adapter: XApifyAdapter,
        kol: Any,
        batch: XTweetBatch,
        slice_started: datetime,
    ) -> tuple[int, int, int]:
        cfg = self.config.adapters.x_apify
        threads: list[str] = []
        for tweet in batch.results:
            if tweet.conversation_id and tweet.conversation_id not in threads:
                threads.append(tweet.conversation_id)
            if len(threads) >= cfg.kol_thread_limit:
                break
        seen = 0
        quarantined = 0
        inserted = 0
        for conversation_id in threads:
            if self._x_over_budget(slice_started):
                self._x_hit_budget = True
                break
            self._roll_x_budget()
            remaining = cfg.max_items_per_day - self._x_items_today
            if remaining <= 0:
                break
            replies = await self._search_x(
                adapter,
                f"conversation_id:{conversation_id}",
                max_items=min(6, remaining),
            )
            if replies is None:
                continue
            more_seen, more_q, more_ins = await self._ingest_x_batch(
                replies, watched_handle=kol.handle
            )
            seen += more_seen
            quarantined += more_q
            inserted += more_ins
        return seen, quarantined, inserted

    async def _collect_claudekol(self) -> Mapping[str, int]:
        if self._http is None:
            return {"claudekol_inserted": 0, "claudekol_seen": 0}
        try:
            batch = await ClaudeKolAdapter(self._http).actions(limit=10)
            inserted = 0
            for observation in observations_from_batch(batch):
                result = await asyncio.to_thread(
                    self.writer.record_observation(observation).result,
                    WRITE_TIMEOUT_SECONDS,
                )
                if result.inserted:
                    inserted += 1
            return {
                "claudekol_inserted": inserted,
                "claudekol_seen": len(batch.actions),
                "claudekol_quarantined": len(batch.quarantined),
            }
        except Exception as exc:
            LOGGER.warning("ClaudeKOL collection failed: %s", type(exc).__name__)
            return {"claudekol_inserted": 0, "claudekol_seen": 0}

    def _history_wallets(self) -> tuple[str, ...]:
        wallets: list[str] = []
        seen: set[str] = set()
        declared = wallets_from_kols(self.config.adapters.x_apify.kols)
        for wallet in (*self.config.helius.seed_wallets, *declared):
            if wallet in seen:
                continue
            seen.add(wallet)
            wallets.append(wallet)
            if len(wallets) >= min(self.config.helius.watchlist_max_addresses, 20):
                break
        return tuple(wallets)

    async def _collect_helius(self) -> Mapping[str, int]:
        wallets = self._history_wallets()
        if not wallets or self._http is None:
            return {"helius_wallets": 0, "helius_txs": 0}
        client = HeliusHistoryClient(
            api_key_file=self.config.helius.api_key_file,
            http_url_template=self.config.helius.http_url_template,
            http=self._http,
        )

        async def record(observation):
            await asyncio.to_thread(
                self.writer.record_observation(observation).result,
                WRITE_TIMEOUT_SECONDS,
            )

        sink = CanonicalObservationSink(record)
        credits = CreditLedger(
            CreditLimits(
                daily=self.config.helius.daily_credit_budget,
                monthly=self.config.helius.monthly_credit_budget,
            )
        )

        async def read_cursor(name: str) -> str | None:
            stream = name.replace(":", ".")[:128]
            cursor = await asyncio.to_thread(
                self.writer.get_cursor("helius", stream).result,
                WRITE_TIMEOUT_SECONDS,
            )
            if cursor is None:
                return None
            token = cursor.value.get("pagination_token")
            return token if isinstance(token, str) and token else None

        async def write_cursor(name: str, value: str | None) -> None:
            stream = name.replace(":", ".")[:128]
            await asyncio.to_thread(
                self.writer.set_cursor(
                    Cursor("helius", stream, {"pagination_token": value or ""})
                ).result,
                WRITE_TIMEOUT_SECONDS,
            )

        collector = BoundedHistoryCollector(
            client=client,
            sink=sink,
            credits=credits,
            read_cursor=read_cursor,
            write_cursor=write_cursor,
            max_wallets_per_run=20,
        )
        bounds = HistoryBounds(
            max_pages=min(self.config.helius.history_pages_per_run, 2),
            max_transactions=min(self.config.helius.history_transactions_per_run, 25),
            max_estimated_credits=150,
            page_size=min(self.config.helius.history_page_size, 25),
        )
        try:
            report = await collector.collect(wallets, bounds)
        except Exception as exc:
            LOGGER.warning("Helius history collection failed: %s", type(exc).__name__)
            self._last_error = f"helius history failed ({type(exc).__name__})"
            return {"helius_wallets": len(wallets), "helius_txs": 0}
        return {
            "helius_wallets": len(report.wallets),
            "helius_txs": report.total_transactions_recorded,
            "helius_credits": report.total_estimated_credits,
        }

    def _queue_tape_mint(self, mint: str) -> None:
        value = mint.strip()
        if (
            not value
            or value in self._mint_tape_fetched
            or value in self._pending_tape_mints
            or len(self._pending_tape_mints) >= MINT_TAPE_PENDING_CAP
            or not 32 <= len(value) <= 44
        ):
            return
        self._pending_tape_mints.append(value)

    def _discover_tape_mints(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            if not isinstance(value, str):
                return
            mint = value.strip()[:64]
            if (
                not mint
                or mint in seen
                or mint in self._mint_tape_fetched
                or not 32 <= len(mint) <= 44
            ):
                return
            seen.add(mint)
            found.append(mint)

        for mint in self._pending_tape_mints:
            add(mint)
        try:
            with IntelligenceStore.from_config(self.config, read_only=True) as store:
                for kind in _MINT_DISCOVERY_KINDS:
                    page = store.list_observations(kind=kind, limit=50)
                    for observation in page.items:
                        if observation.subject_type == "token":
                            add(observation.subject_id)
                        payload = thaw_json(observation.payload)
                        if not isinstance(payload, dict):
                            continue
                        add(payload.get("mint"))
                        candidates = payload.get("mint_candidates")
                        if isinstance(candidates, list | tuple):
                            for item in candidates:
                                add(item)
                for entry in store.list_watch_entries(X_WATCHLIST_ID):
                    if entry.subject_type == "token":
                        add(entry.subject_id)
        except Exception:
            LOGGER.debug("mint-tape discovery could not read recent observations", exc_info=True)
        return found[:MINT_TAPE_MAX_MINTS]

    async def _collect_mint_tape(self) -> dict[str, int]:
        """Bounded mint-centric holder book + one history page. Advisory only."""

        if self._http is None:
            return {"mint_tape_mints": 0, "mint_tape_recorded": 0}
        mints = self._discover_tape_mints()
        if not mints:
            return {"mint_tape_mints": 0, "mint_tape_recorded": 0}
        try:
            client = HeliusHistoryClient(
                api_key_file=self.config.helius.api_key_file,
                http_url_template=self.config.helius.http_url_template,
                http=self._http,
            )
        except Exception as exc:
            LOGGER.warning("Helius mint-tape client unavailable (%s)", type(exc).__name__)
            return {"mint_tape_mints": 0, "mint_tape_recorded": 0}

        started = utc_now()
        recorded = 0
        attempted = 0
        for mint in mints:
            if (utc_now() - started).total_seconds() >= MINT_TAPE_WALL_SECONDS:
                LOGGER.info("mint-tape wall budget reached; skipping remaining mints")
                break
            attempted += 1
            try:
                wrote = await self._record_one_mint_tape(client, mint)
            except Exception:
                LOGGER.warning("mint-tape failed for %s", mint[:8], exc_info=True)
                continue
            if wrote:
                recorded += 1
                self._mint_tape_fetched.add(mint)
                if mint in self._pending_tape_mints:
                    self._pending_tape_mints.remove(mint)
        return {"mint_tape_mints": attempted, "mint_tape_recorded": recorded}

    async def _record_one_mint_tape(self, client: HeliusHistoryClient, mint: str) -> bool:
        provenance: list[str] = []
        balances: tuple[float, ...] = ()
        prints: list[TapePrint] = []
        try:
            balances = await client.token_largest_accounts(mint)
            provenance.append("helius:getTokenLargestAccounts")
        except ValueError:
            return False
        except HeliusIntelligenceError as exc:
            LOGGER.warning("mint-tape holders failed for %s (%s)", mint[:8], type(exc).__name__)
        try:
            page = await client.mint_enhanced_page(mint, limit=MINT_TAPE_PAGE_LIMIT)
            provenance.append("helius:getTransactionsForAddress")
            for tx in page:
                prints.extend(prints_from_history_tx(tx, mint=mint))
        except ValueError:
            return False
        except HeliusIntelligenceError as exc:
            LOGGER.warning("mint-tape page failed for %s (%s)", mint[:8], type(exc).__name__)
        if not provenance:
            return False
        features = merge_feature_bags(holder_features(balances), features_from_prints(prints))
        serialized = [
            {
                "ts": print_.ts,
                "mint": print_.mint,
                "wallet": print_.wallet,
                "side": print_.side,
                "quote_sol": print_.quote_sol,
                "base": print_.base,
            }
            for print_ in prints
        ]
        observation = mint_tape_observation(
            mint,
            prints=serialized,
            features=features,
            provenance=tuple(provenance),
        )
        try:
            await asyncio.to_thread(
                self.writer.record_observation(observation).result,
                WRITE_TIMEOUT_SECONDS,
            )
        except ImmutableConflict:
            return True
        except Exception:
            LOGGER.warning("mint-tape write failed for %s", mint[:8], exc_info=True)
            return False
        return True

    async def _store_tweets(self, tweets, *, watched_handle: str | None = None) -> int:
        inserted = 0
        for tweet in tweets:
            for observation in tweet_to_observations(tweet, watched_handle=watched_handle):
                result = await asyncio.to_thread(
                    self.writer.record_observation(observation).result,
                    WRITE_TIMEOUT_SECONDS,
                )
                if result.inserted:
                    inserted += 1
            for mint in tweet.mint_candidates:
                self._queue_tape_mint(mint)
                await self._watch_mint(mint, tweet.tweet_id)
        return inserted

    async def _watch_mint(self, mint: str, tweet_id: str) -> None:
        entry = WatchEntry(
            X_WATCHLIST_ID,
            "token",
            mint,
            f"extracted from X tweet {tweet_id}",
            utc_now(),
            discovery_observation_id=None,
            priority=40,
        )
        try:
            await asyncio.to_thread(
                self.writer.submit("add_watch", entry).result,
                WRITE_TIMEOUT_SECONDS,
            )
        except ImmutableConflict:
            return
        except Exception:
            LOGGER.debug("could not add mint watch %s", mint[:8], exc_info=True)

    async def _mark_x(
        self,
        status: HealthStatus,
        error_code: str | None,
        *,
        latency_ms: float | None = None,
    ) -> None:
        now = utc_now()
        health = SourceHealth(
            X_SOURCE_ID,
            status,
            now,
            last_success_at=now if status is HealthStatus.HEALTHY else None,
            latency_ms=latency_ms,
            error_code=error_code,
        )
        await asyncio.to_thread(
            self.writer.update_source_health(health).result,
            WRITE_TIMEOUT_SECONDS,
        )
