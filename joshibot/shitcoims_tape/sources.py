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
* :class:`HeliusHistorySource` — bounded ``getTransactionsForAddress`` paging per mint,
  charged against an explicit :class:`~shitcoims_tape.recorder.CreditBudget` before the
  request is made, so a run cannot overspend and then apologise. It pages to the cursor, it
  filters out failed transactions at the source (measured 59-62% of an unfiltered pump.fun
  page), and it reports per-mint what stopped it.
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
from typing import Any, Final, Literal, Protocol

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


#: Why a mint's backfill stopped. Only ``exhausted`` and ``window`` are benign: the other
#: three are truncation, they correlate with how busy the mint was, and a study that treats
#: them as complete history is reading a censored panel as an uncensored one.
STOP_EXHAUSTED: Final[str] = "exhausted"
STOP_WINDOW: Final[str] = "window"
STOP_PAGE_CAP: Final[str] = "page_cap"
STOP_BUDGET: Final[str] = "budget"
STOP_ERROR: Final[str] = "error"

#: Truncating stops. A mint that ended on one of these was cut off by *our* limits, not by
#: the chain running out of history.
TRUNCATING_STOPS: Final[frozenset[str]] = frozenset({STOP_PAGE_CAP, STOP_BUDGET, STOP_ERROR})


@dataclass(frozen=True, slots=True)
class MintHistory:
    """What one mint's bounded backfill actually achieved. Reported, never inferred."""

    mint: str
    pages: int
    transactions: int
    credits: int
    stopped_by: str
    first_block_time: int | None = None
    last_block_time: int | None = None

    @property
    def truncated(self) -> bool:
        return self.stopped_by in TRUNCATING_STOPS

    @property
    def observed_seconds(self) -> int | None:
        if self.first_block_time is None or self.last_block_time is None:
            return None
        return self.last_block_time - self.first_block_time

    def to_json(self) -> dict[str, object]:
        return {
            "mint": self.mint,
            "pages": self.pages,
            "transactions": self.transactions,
            "credits": self.credits,
            "stopped_by": self.stopped_by,
            "truncated": self.truncated,
            "first_block_time": self.first_block_time,
            "last_block_time": self.last_block_time,
        }


class HeliusHistorySource:
    """Bounded per-mint history paging, charged before it is spent.

    ``getTransactionsForAddress`` costs 10 credits per 100 transactions, so one page is
    :data:`~shitcoims_tape.recorder.CREDITS_PER_TRANSACTION_PAGE`. The budget is charged
    *before* the request, which is the only ordering under which an exhausted budget stops
    the run instead of discovering the overspend afterwards.

    Three properties are load-bearing and each one was measured against mainnet:

    **It pages.** The first version of this class read exactly one page per mint and dropped
    the continuation cursor, so a mint with 3,000 transactions contributed 100 of them and
    nothing said so. A panel built that way is not a shallow sample of each mint, it is a
    sample of each mint's *most recent* activity, which is the same shape of error as
    displacement censoring.

    **It stops on the cursor, never on a short page.** The service returns a continuation
    token *after* a short page, so ``len(page) < limit`` is not the end of the history. It is
    usually the end, which is precisely what makes assuming it dangerous: the assumption is
    right often enough to survive testing and wrong exactly on the busiest mints.

    **The observation window is anchored to the mint's own first transaction**, not to the
    wall clock. With ``sort_order='asc'`` page one begins at the mint's creation, so
    ``window_seconds`` yields the identical ``[launch, launch+W]`` window for every mint. A
    fixed *transaction count* would instead give busy mints a shorter time window than quiet
    ones, tying the observation window to the outcome being studied.
    """

    def __init__(
        self,
        client: HeliusHistoryClient,
        mints: Sequence[str],
        *,
        budget: CreditBudget,
        page_size: int = 100,
        page_cap: int = 25,
        window_seconds: int | None = None,
        succeeded_only: bool = True,
        sort_order: Literal["asc", "desc"] = "asc",
    ) -> None:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if page_cap < 1:
            raise ValueError("page_cap must be at least one page")
        if window_seconds is not None and window_seconds <= 0:
            raise ValueError("window_seconds must be positive when given")
        self._client = client
        self._mints = tuple(mints)
        self._budget = budget
        self._page_size = page_size
        self._page_cap = page_cap
        self._window_seconds = window_seconds
        self._succeeded_only = succeeded_only
        self._sort_order = sort_order
        self._histories: list[MintHistory] = []
        self._unreached: list[str] = []

    @property
    def budget(self) -> CreditBudget:
        return self._budget

    @property
    def histories(self) -> tuple[MintHistory, ...]:
        """One record per mint the source actually fetched."""

        return tuple(self._histories)

    @property
    def unreached(self) -> tuple[str, ...]:
        """Mints the budget never reached. The caller owns recording them as censored."""

        return tuple(self._unreached)

    def transactions(self) -> AsyncIterator[SourceItem]:
        async def iterator() -> AsyncIterator[SourceItem]:
            for index, mint in enumerate(self._mints):
                if not self._budget.can_afford(CREDITS_PER_TRANSACTION_PAGE):
                    self._unreached.extend(self._mints[index:])
                    yield SourceGap(reason="credit_budget_exhausted")
                    return
                async for item in self._one_mint(mint):
                    yield item

        return iterator()

    async def _one_mint(self, mint: str) -> AsyncIterator[SourceItem]:
        cursor: str | None = None
        pages = 0
        seen = 0
        credits = 0
        anchor: int | None = None
        first_block_time: int | None = None
        last_block_time: int | None = None
        stopped_by = STOP_EXHAUSTED
        while True:
            if pages >= self._page_cap:
                stopped_by = STOP_PAGE_CAP
                break
            if not self._budget.can_afford(CREDITS_PER_TRANSACTION_PAGE):
                stopped_by = STOP_BUDGET
                yield SourceGap(reason=f"credit_budget_exhausted:{mint}")
                break
            self._budget.charge(CREDITS_PER_TRANSACTION_PAGE)
            credits += CREDITS_PER_TRANSACTION_PAGE
            try:
                page, cursor = await self._client.address_history_page(
                    mint,
                    limit=self._page_size,
                    cursor=cursor,
                    sort_order=self._sort_order,
                    succeeded_only=self._succeeded_only,
                )
            except HeliusIntelligenceError as exc:
                # `exc` is already sanitised by the intelligence client and carries no URL.
                stopped_by = STOP_ERROR
                yield SourceGap(reason=f"history_failed:{exc}")
                break
            pages += 1
            past_window = False
            for item in page:
                block_time = item.get("blockTime")
                if isinstance(block_time, int):
                    if anchor is None:
                        anchor = block_time
                        first_block_time = block_time
                    if self._window_seconds is not None and block_time > anchor + self._window_seconds:
                        past_window = True
                        break
                    last_block_time = block_time
                seen += 1
                yield item
            if past_window:
                stopped_by = STOP_WINDOW
                break
            if cursor is None or not page:
                stopped_by = STOP_EXHAUSTED
                break
        self._histories.append(
            MintHistory(
                mint=mint,
                pages=pages,
                transactions=seen,
                credits=credits,
                stopped_by=stopped_by,
                first_block_time=first_block_time,
                last_block_time=last_block_time,
            )
        )


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
