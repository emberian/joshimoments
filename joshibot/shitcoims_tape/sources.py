"""Where transactions come from. One protocol, three implementations, zero duplicated secrets.

The recorder deliberately owns no transport, so this module is the only place that touches
Helius. It never re-implements the credential handling in
``shitcoims_intelligence.helius``: the 0600-permission check on the key file, the
approved-origin check on the endpoint template, and the sanitised errors that keep the
API key out of every exception and log line all live there and are *inherited or called*,
never copied. A mirrored credential path is how a key ends up in a log.

Three sources:

* :class:`IterableSource` — replays already-captured transactions. Used by the backfill
  loaders and by every test; costs nothing.
* :class:`HeliusHistorySource` — bounded ``getTransactionsForAddress`` paging for one mint,
  charged against an explicit :class:`~shitcoims_tape.recorder.CreditBudget` before the
  request is made, so a run cannot overspend and then apologise.
* :class:`PumpFirehose` — the program-level ``transactionSubscribe``. This is the only source
  that can achieve full coverage: pump.fun launches tens of thousands of tokens a day and
  per-mint history polling would cost more credits than a month's allowance.

**Gaps are reported, never papered over.** A dropped websocket means transactions were
missed. ``PumpFirehose`` yields an explicit :class:`SourceGap` on every disconnect so the
driver can schedule bounded backfill; a source that silently reconnects turns a hole in the
tape into an invisible dip in every intensity estimate.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from shitcoims_intelligence.helius import (
    HeliusHistoryClient,
    HeliusIntelligenceError,
    HeliusTransactionStream,
    WatchlistSnapshot,
)
from shitcoims_intelligence.pump_layouts import PUMP_AMM_PROGRAM_ID, PUMP_PROGRAM_ID
from shitcoims_tape.recorder import (
    CREDITS_PER_TRANSACTION_PAGE,
    CreditBudget,
    CreditBudgetExceeded,
    TapeRecorder,
)

LOGGER = logging.getLogger("shitcoims.tape.sources")

RawTransaction = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SourceGap:
    """An admission that transactions were missed. Recorded so the hole is not invisible."""

    reason: str
    last_observed_slot: int | None = None


SourceItem = RawTransaction | SourceGap


class TransactionSource(Protocol):
    """Anything that can hand the recorder full jsonParsed transactions."""

    def transactions(self) -> AsyncIterator[SourceItem]: ...


class IterableSource:
    """Replay a finite, already-captured sequence. No network, no credentials, no cost."""

    def __init__(self, items: Iterable[SourceItem]) -> None:
        self._items = tuple(items)

    def transactions(self) -> AsyncIterator[SourceItem]:
        async def iterator() -> AsyncIterator[SourceItem]:
            for item in self._items:
                yield item

        return iterator()


def transactions_from_jsonl(path: Path) -> IterableSource:
    """Load captured raw transactions, one JSON object per line."""

    items: list[SourceItem] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                LOGGER.warning("skipping malformed captured transaction at line %s", number)
                continue
            if isinstance(payload, dict):
                items.append(payload)
    return IterableSource(items)


class HeliusHistorySource:
    """Bounded per-mint history, charged before it is spent.

    ``getTransactionsForAddress`` costs 10 credits per 100 transactions, so one page is
    :data:`~shitcoims_tape.recorder.CREDITS_PER_TRANSACTION_PAGE`. The budget is charged
    *before* the request, which is the only ordering under which an exhausted budget stops
    the run instead of discovering the overspend afterwards.
    """

    def __init__(
        self,
        client: HeliusHistoryClient,
        mints: Sequence[str],
        *,
        budget: CreditBudget,
        page_size: int = 100,
    ) -> None:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        self._client = client
        self._mints = tuple(mints)
        self._budget = budget
        self._page_size = page_size

    @property
    def budget(self) -> CreditBudget:
        return self._budget

    def transactions(self) -> AsyncIterator[SourceItem]:
        async def iterator() -> AsyncIterator[SourceItem]:
            for mint in self._mints:
                if not self._budget.can_afford(CREDITS_PER_TRANSACTION_PAGE):
                    yield SourceGap(reason="credit_budget_exhausted")
                    return
                self._budget.charge(CREDITS_PER_TRANSACTION_PAGE)
                try:
                    page = await self._client.mint_enhanced_page(mint, limit=self._page_size)
                except HeliusIntelligenceError as exc:
                    # `exc` is already sanitised by the intelligence client and carries no URL.
                    yield SourceGap(reason=f"history_failed:{exc}")
                    continue
                for item in page:
                    yield item

        return iterator()


class PumpFirehose(HeliusTransactionStream):
    """Program-level ``transactionSubscribe`` on both pinned pump programs.

    Subclassing is deliberate: the parent's constructor performs the key-file permission
    check and builds the credentialed websocket URL, and ``_factory_for_connection`` applies
    the size and timeout limits. Re-implementing any of that here would be a second copy of
    the code that must never leak a key.

    The parent's ``events`` iterator normalises to per-wallet balance deltas and drops
    ``logMessages``, which is exactly the field the pump event decoder needs — hence this
    separate raw iterator rather than a reuse of that loop.
    """

    PROGRAM_IDS: tuple[str, ...] = (PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID)

    def subscription_request(self, snapshot: WatchlistSnapshot) -> dict[str, Any]:
        self._request_id += 1
        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "transactionSubscribe",
            "params": [
                {"vote": False, "failed": False, "accountInclude": list(snapshot.addresses)},
                {
                    "commitment": "confirmed",
                    "encoding": "jsonParsed",
                    "transactionDetails": "full",
                    "showRewards": False,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }

    def snapshot(self) -> WatchlistSnapshot:
        return WatchlistSnapshot(version="pump-programs-v1", addresses=self.PROGRAM_IDS)

    def transactions(self, *, stop: asyncio.Event | None = None) -> AsyncIterator[SourceItem]:
        async def iterator() -> AsyncIterator[SourceItem]:
            snapshot = self.snapshot()
            last_slot: int | None = None
            while stop is None or not stop.is_set():
                reason = "stream_disconnected"
                try:
                    context = await self._factory_for_connection()
                    async with context as socket:
                        request = self.subscription_request(snapshot)
                        await socket.send(json.dumps(request, separators=(",", ":")))
                        raw_ack = await asyncio.wait_for(socket.recv(), timeout=10)
                        ack = json.loads(raw_ack)
                        subscription = ack.get("result") if isinstance(ack, dict) else None
                        if ack.get("id") != request["id"] or not isinstance(subscription, int):
                            raise HeliusIntelligenceError("pump subscription was rejected")
                        while stop is None or not stop.is_set():
                            try:
                                raw = await asyncio.wait_for(
                                    socket.recv(), timeout=self._keepalive_seconds
                                )
                            except TimeoutError:
                                waiter = await socket.ping()
                                if isinstance(waiter, Awaitable):
                                    await asyncio.wait_for(waiter, timeout=10)
                                continue
                            item, slot = _notification_transaction(raw, subscription)
                            if item is None:
                                continue
                            last_slot = slot if last_slot is None else max(last_slot, slot)
                            yield item
                        return
                except asyncio.CancelledError:
                    raise
                except HeliusIntelligenceError as exc:
                    reason = str(exc)
                except Exception as exc:
                    # Never interpolate the exception itself: a transport error can carry the
                    # credentialed URL. The type name is enough to act on.
                    reason = f"pump_stream_failed:{type(exc).__name__}"
                yield SourceGap(reason=reason, last_observed_slot=last_slot)
                if stop is not None and stop.is_set():
                    return
                await self._sleeper(self._reconnect_seconds)

        return iterator()


def _notification_transaction(raw: str | bytes, subscription: int) -> tuple[RawTransaction | None, int]:
    """Reshape one notification into the full-transaction envelope the decoder expects."""

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return None, 0
    if not isinstance(body, dict) or body.get("method") != "transactionNotification":
        return None, 0
    params = body.get("params")
    if not isinstance(params, dict) or params.get("subscription") != subscription:
        return None, 0
    result = params.get("result")
    if not isinstance(result, dict):
        return None, 0
    wrapper = result.get("transaction")
    if not isinstance(wrapper, dict):
        return None, 0
    inner = wrapper.get("transaction")
    meta = wrapper.get("meta")
    if not isinstance(inner, dict) or not isinstance(meta, dict):
        return None, 0
    try:
        slot = int(result["slot"])
    except (KeyError, TypeError, ValueError):
        return None, 0
    signature = result.get("signature")
    if isinstance(signature, str):
        # The notification carries the signature outside the transaction envelope; put it
        # where the chainstamp builder reads it so no downstream code has to special-case
        # the streaming shape against the history shape.
        inner = {**inner, "signatures": [signature]}
    return (
        {
            "slot": slot,
            "transactionIndex": result.get("transactionIndex"),
            "blockTime": result.get("blockTime"),
            "transaction": inner,
            "meta": meta,
        },
        slot,
    )


@dataclass(frozen=True, slots=True)
class RunReport:
    transactions: int
    gaps: tuple[SourceGap, ...]
    events_written: int
    credits_spent: int

    def to_json(self) -> dict[str, object]:
        return {
            "transactions": self.transactions,
            "gaps": [
                {"reason": gap.reason, "last_observed_slot": gap.last_observed_slot}
                for gap in self.gaps
            ],
            "events_written": self.events_written,
            "credits_spent": self.credits_spent,
        }


async def run_recorder(
    source: TransactionSource,
    recorder: TapeRecorder,
    *,
    budget: CreditBudget | None = None,
    expire_every: int = 500,
    on_gap: Callable[[SourceGap], object] | None = None,
) -> RunReport:
    """Drive a recorder from a source until the source ends or the budget runs out.

    ``expire_every`` is why watches close on a clock at all: nothing else calls
    :meth:`WatchRegistry.expire`, and a registry that is never expired accumulates
    unresolved watches that look like an unbounded horizon.
    """

    transactions = 0
    written = 0
    gaps: list[SourceGap] = []
    try:
        async for item in source.transactions():
            if isinstance(item, SourceGap):
                gaps.append(item)
                LOGGER.warning("source gap recorded: %s", item.reason)
                if on_gap is not None:
                    on_gap(item)
                continue
            transactions += 1
            written += recorder.record_transaction(item)
            if expire_every and transactions % expire_every == 0:
                recorder.expire_watches()
    except CreditBudgetExceeded as exc:
        gaps.append(SourceGap(reason=f"credit_budget_exhausted:{exc}"))
    recorder.expire_watches()
    return RunReport(
        transactions=transactions,
        gaps=tuple(gaps),
        events_written=written,
        credits_spent=0 if budget is None else budget.spent,
    )
