"""Coordination and budget gates for read-only wallet intelligence collection."""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from .helius import (
    HeliusHistoryClient,
    HeliusTransactionStream,
    HistoryBounds,
    HistoryResult,
    RawHistoryPage,
    StreamEvent,
    WalletTransaction,
    WatchlistProvider,
)
from .models import Finality, Observation, RawBlob, utc_now


class CollectionBudgetExceeded(RuntimeError):
    """The requested collection cannot fit inside a configured credit envelope."""


@dataclass(frozen=True, slots=True)
class CreditLimits:
    daily: int = 10_000
    monthly: int = 300_000

    def __post_init__(self) -> None:
        if self.daily <= 0 or self.monthly <= 0:
            raise ValueError("Helius credit limits must be positive")
        if self.daily > self.monthly:
            raise ValueError("daily Helius credit limit cannot exceed monthly limit")


@dataclass(frozen=True, slots=True)
class CreditUsage:
    utc_day: date
    utc_month: str
    daily_used: int
    daily_limit: int
    monthly_used: int
    monthly_limit: int
    reserved: int = 0

    @property
    def daily_remaining(self) -> int:
        return max(self.daily_limit - self.daily_used, 0)

    @property
    def monthly_remaining(self) -> int:
        return max(self.monthly_limit - self.monthly_used, 0)


class CreditLedger:
    """In-process UTC daily/monthly Helius budget with reservation semantics.

    A persistence adapter can restore usage after restart with ``restore``. The
    ledger reserves a run's worst case before any provider request, preventing
    concurrent collectors from overspending. Unused reservation is returned.
    """

    def __init__(
        self,
        limits: CreditLimits | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._limits = limits or CreditLimits()
        self._clock = clock
        self._lock = asyncio.Lock()
        self._day: date | None = None
        self._month: str | None = None
        self._daily_used = 0
        self._monthly_used = 0
        self._reserved = 0

    def _roll_periods(self) -> tuple[date, str]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("credit clock must return a timezone-aware datetime")
        now = now.astimezone(UTC)
        day = now.date()
        month = f"{now.year:04d}-{now.month:02d}"
        if self._month != month:
            self._month = month
            self._monthly_used = 0
            self._day = day
            self._daily_used = 0
        elif self._day != day:
            self._day = day
            self._daily_used = 0
        return day, month

    async def restore(
        self,
        *,
        utc_day: date,
        daily_used: int,
        utc_month: str,
        monthly_used: int,
    ) -> None:
        if daily_used < 0 or monthly_used < 0:
            raise ValueError("restored credit usage cannot be negative")
        async with self._lock:
            current_day, current_month = self._roll_periods()
            if utc_month == current_month:
                self._monthly_used = monthly_used
            if utc_day == current_day:
                self._daily_used = daily_used

    async def reserve(self, credits: int) -> None:
        if credits <= 0:
            raise ValueError("credit reservation must be positive")
        async with self._lock:
            self._roll_periods()
            if self._daily_used + self._reserved + credits > self._limits.daily:
                raise CollectionBudgetExceeded("daily Helius credit budget would be exceeded")
            if self._monthly_used + self._reserved + credits > self._limits.monthly:
                raise CollectionBudgetExceeded("monthly Helius credit budget would be exceeded")
            self._reserved += credits

    async def commit(self, reserved: int, used: int) -> CreditUsage:
        if reserved <= 0 or not 0 <= used <= reserved:
            raise ValueError("credit commitment must be within its reservation")
        async with self._lock:
            day, month = self._roll_periods()
            if reserved > self._reserved:
                raise RuntimeError("credit reservation is no longer active")
            self._reserved -= reserved
            self._daily_used += used
            self._monthly_used += used
            return CreditUsage(
                utc_day=day,
                utc_month=month,
                daily_used=self._daily_used,
                daily_limit=self._limits.daily,
                monthly_used=self._monthly_used,
                monthly_limit=self._limits.monthly,
                reserved=self._reserved,
            )

    async def cancel(self, reserved: int) -> None:
        if reserved <= 0:
            raise ValueError("credit cancellation must be positive")
        async with self._lock:
            self._roll_periods()
            if reserved > self._reserved:
                raise RuntimeError("credit reservation is no longer active")
            self._reserved -= reserved

    async def snapshot(self) -> CreditUsage:
        async with self._lock:
            day, month = self._roll_periods()
            return CreditUsage(
                utc_day=day,
                utc_month=month,
                daily_used=self._daily_used,
                daily_limit=self._limits.daily,
                monthly_used=self._monthly_used,
                monthly_limit=self._limits.monthly,
                reserved=self._reserved,
            )


class WalletTransactionSink(Protocol):
    async def record_wallet_transaction(self, transaction: WalletTransaction) -> None: ...

    async def record_source_event(self, event: StreamEvent) -> None: ...


ObservationRecorder = Callable[[Observation], object | Awaitable[object]]


class CanonicalObservationSink:
    """Adapt the collectors to a sync store or an async single-writer queue."""

    def __init__(self, record_observation: ObservationRecorder) -> None:
        self._record_observation = record_observation

    async def _record(self, observation: Observation) -> None:
        result = self._record_observation(observation)
        if inspect.isawaitable(result):
            await result

    async def record_wallet_transaction(self, transaction: WalletTransaction) -> None:
        await self._record(wallet_transaction_observation(transaction))

    async def record_source_event(self, event: StreamEvent) -> None:
        await self._record(stream_event_observation(event))


class LiveStreamCollector:
    """Persist every source-health, gap, and confirmed transaction stream event."""

    def __init__(
        self,
        *,
        stream: HeliusTransactionStream,
        sink: WalletTransactionSink,
    ) -> None:
        self._stream = stream
        self._sink = sink

    async def run(
        self,
        watchlist_provider: WatchlistProvider,
        *,
        stop: asyncio.Event | None = None,
    ) -> None:
        async for event in self._stream.events(watchlist_provider, stop=stop):
            await self._sink.record_source_event(event)


CursorReader = Callable[[str], Awaitable[str | None]]
CursorWriter = Callable[[str, str | None], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WalletHistoryReport:
    wallet: str
    transactions_seen: int
    transactions_recorded: int
    next_cursor: str | None
    source_exhausted: bool
    bound_reached: bool
    pages_fetched: int
    estimated_credits: int
    credit_usage: CreditUsage


@dataclass(frozen=True, slots=True)
class CollectionRunReport:
    run_id: str
    started_at: datetime
    completed_at: datetime
    wallets: tuple[WalletHistoryReport, ...]
    total_transactions_recorded: int
    total_estimated_credits: int


def raw_history_blob(page: RawHistoryPage) -> RawBlob:
    """Convert a credential-free provider page into the canonical raw cache record."""

    return RawBlob(
        source_id="helius",
        request_fingerprint=page.request_fingerprint,
        fetched_at=page.observed_at,
        parser_version=page.parser_version,
        body=page.body,
        content_type="application/json",
        retention_class="chain_evidence",
    )


def wallet_transaction_observation(transaction: WalletTransaction) -> Observation:
    """Project normalized chain facts into the repository-wide evidence contract."""

    emitted_at = (
        datetime.fromtimestamp(transaction.block_time, tz=UTC)
        if transaction.block_time is not None
        else None
    )
    return Observation(
        source_id="helius",
        source_native_id=f"{transaction.signature}:{transaction.wallet}",
        kind="wallet_transaction",
        subject_type="wallet",
        subject_id=transaction.wallet,
        observed_at=transaction.observed_at,
        emitted_at=emitted_at,
        payload={
            "title": f"wallet {transaction.wallet[:6]}… {transaction.signature[:8]}",
            "summary": (
                f"slot {transaction.slot} sol_delta={transaction.sol_delta_lamports} "
                f"tokens={len(transaction.token_deltas)}"
            ),
            "severity": "info",
            "status": "observed",
            "signature": transaction.signature,
            "slot": transaction.slot,
            "transaction_index": transaction.transaction_index,
            "succeeded": transaction.succeeded,
            "fee_lamports": transaction.fee_lamports,
            "fee_payer": transaction.fee_payer,
            "wallet_paid_fee": transaction.wallet_paid_fee,
            "sol_delta_lamports": transaction.sol_delta_lamports,
            "sol_delta_exact": transaction.sol_delta_exact,
            "token_deltas_exact": transaction.token_deltas_exact,
            "token_deltas": [
                {
                    "mint": delta.mint,
                    "raw_delta": delta.raw_delta,
                    "decimals": delta.decimals,
                }
                for delta in transaction.token_deltas
            ],
        },
        confidence=1.0,
        finality=(
            Finality.FINALIZED
            if transaction.commitment == "finalized"
            else Finality.CONFIRMED
        ),
        parser_version=transaction.parser_version,
        provenance=("helius:getTransactionsForAddress",),
        retention_class="chain_evidence",
        raw_blob_ids=transaction.raw_blob_ids,
    )


def mint_tape_observation(
    mint: str,
    *,
    prints: Sequence[Mapping[str, Any]] = (),
    features: Mapping[str, Any] | None = None,
    provenance: Sequence[str] = (),
    observed_at: datetime | None = None,
) -> Observation:
    """Advisory mint-centric tape + holder book. Never an execution instruction."""

    stamp = observed_at if observed_at is not None else utc_now()
    bag = dict(features or {})
    serialized = [dict(item) for item in prints]
    holder_count = bag.get("holder_count")
    trade_count = bag.get("trade_count", len(serialized))
    payload: dict[str, Any] = {
        "title": f"mint tape {mint[:8]}…",
        "summary": f"holders={holder_count} trades={trade_count}",
        "severity": "info",
        "status": "observed",
        "mint": mint,
        "prints": serialized,
        **bag,
    }
    used = tuple(item for item in provenance if item)
    if not used:
        used = ("helius:getTokenLargestAccounts",)
    return Observation(
        source_id="helius",
        source_native_id=f"mint-tape:{mint}:{stamp.isoformat()}",
        kind="mint_tape",
        subject_type="token",
        subject_id=mint,
        observed_at=stamp,
        payload=payload,
        confidence=1.0,
        finality=Finality.FINALIZED,
        parser_version="helius-mint-tape-v1",
        provenance=used,
        retention_class="chain_evidence",
    )


def stream_event_observation(event: StreamEvent) -> Observation:
    """Preserve stream health and continuity gaps as first-class evidence."""

    if event.kind == "transaction":
        if event.transaction is None:
            raise ValueError("transaction stream event omitted its transaction")
        return wallet_transaction_observation(event.transaction)
    native_material = (
        f"{event.kind}:{event.watchlist_version}:{event.observed_at.isoformat()}"
    )
    return Observation(
        source_id="helius",
        source_native_id=native_material,
        kind=f"stream_{event.kind}",
        subject_type="watchlist",
        subject_id=event.watchlist_version,
        observed_at=event.observed_at,
        payload={
            "watchlist_version": event.watchlist_version,
            "status": event.status,
            "reason": event.reason,
            "last_observed_slot": event.last_observed_slot,
        },
        confidence=1.0,
        finality=Finality.CONFIRMED,
        parser_version="helius-transaction-subscribe-v1",
        provenance=("helius:transactionSubscribe",),
        retention_class="source_health",
    )


def history_cursor_name(wallet: str, bounds: HistoryBounds) -> str:
    """Stable cursor namespace; changing history semantics creates a new cursor."""

    material = json.dumps(
        {
            "wallet": wallet,
            "sort_order": bounds.sort_order,
            "commitment": bounds.commitment,
            "min_slot": bounds.min_slot,
            "max_slot": bounds.max_slot,
            "min_block_time": bounds.min_block_time,
            "max_block_time": bounds.max_block_time,
            "token_accounts": "balanceChanged",
            "transaction_details": "full",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"helius-history:{hashlib.sha256(material).hexdigest()[:24]}"


class BoundedHistoryCollector:
    """Collect a finite wallet set with budget reservation and resumable cursors."""

    def __init__(
        self,
        *,
        client: HeliusHistoryClient,
        sink: WalletTransactionSink,
        credits: CreditLedger,
        read_cursor: CursorReader,
        write_cursor: CursorWriter,
        max_wallets_per_run: int = 50,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= max_wallets_per_run <= 10_000:
            raise ValueError("max_wallets_per_run must be between 1 and 10000")
        self._client = client
        self._sink = sink
        self._credits = credits
        self._read_cursor = read_cursor
        self._write_cursor = write_cursor
        self._max_wallets_per_run = max_wallets_per_run
        self._clock = clock

    async def collect(
        self, wallets: Sequence[str], bounds: HistoryBounds
    ) -> CollectionRunReport:
        if not wallets:
            raise ValueError("history collection requires at least one wallet")
        if len(wallets) > self._max_wallets_per_run:
            raise ValueError(
                f"history run has {len(wallets)} wallets; limit is {self._max_wallets_per_run}"
            )
        if len(wallets) != len(set(wallets)):
            raise ValueError("history run wallets must be unique")
        started_at = self._clock()
        if started_at.tzinfo is None:
            raise ValueError("collector clock must return a timezone-aware datetime")
        run_id = hashlib.sha256(
            (started_at.astimezone(UTC).isoformat() + "\0" + "\0".join(wallets)).encode()
        ).hexdigest()[:24]

        reports: list[WalletHistoryReport] = []
        recorded_total = 0
        credits_total = 0
        for wallet in wallets:
            # Cursor overlap and duplicates can consume every allowed page, so
            # reserve the page ceiling rather than estimating from desired rows.
            reservation = min(
                bounds.max_estimated_credits,
                bounds.max_pages * bounds.estimated_credits_per_page,
            )
            await self._credits.reserve(reservation)
            try:
                cursor_name = history_cursor_name(wallet, bounds)
                cursor = await self._read_cursor(cursor_name)
                result: HistoryResult = await self._client.fetch(wallet, bounds, cursor=cursor)
                recorded = 0
                for transaction in result.transactions:
                    await self._sink.record_wallet_transaction(transaction)
                    recorded += 1
                # Advance only after all observations are durable in the sink.
                await self._write_cursor(cursor_name, result.next_cursor)
            except BaseException:
                # A transport/cache/sink failure can occur after Helius accepted
                # one or more requests. Conservatively charge the entire reserved
                # envelope: uncertain metering must never reopen budget capacity.
                await self._credits.commit(reservation, reservation)
                raise
            usage = await self._credits.commit(reservation, result.estimated_credits)
            reports.append(
                WalletHistoryReport(
                    wallet=wallet,
                    transactions_seen=len(result.transactions),
                    transactions_recorded=recorded,
                    next_cursor=result.next_cursor,
                    source_exhausted=result.source_exhausted,
                    bound_reached=result.bound_reached,
                    pages_fetched=result.pages_fetched,
                    estimated_credits=result.estimated_credits,
                    credit_usage=usage,
                )
            )
            recorded_total += recorded
            credits_total += result.estimated_credits

        completed_at = self._clock()
        return CollectionRunReport(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            wallets=tuple(reports),
            total_transactions_recorded=recorded_total,
            total_estimated_credits=credits_total,
        )


class MemoryCursorStore:
    """Small test/dev cursor adapter; production should use IntelligenceStore."""

    def __init__(self, initial: Mapping[str, str | None] | None = None) -> None:
        self.values = dict(initial or {})

    async def read(self, name: str) -> str | None:
        return self.values.get(name)

    async def write(self, name: str, value: str | None) -> None:
        self.values[name] = value


def days_in_utc_month(when: datetime) -> int:
    """Exposed for dashboards estimating safe daily spend from a monthly cap."""

    when = when.astimezone(UTC)
    return calendar.monthrange(when.year, when.month)[1]
