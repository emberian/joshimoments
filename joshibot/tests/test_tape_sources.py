"""Tests for the recorder's transports.

The properties that matter here are budgetary and epistemic: a run must not overspend Helius
credits, and a hole in the tape must be announced rather than silently reconnected around.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from solders.keypair import Keypair

from shitcoims_intelligence.pump_layouts import PUMP_PROGRAM_ID
from shitcoims_tape import EventKind
from shitcoims_tape.recorder import CreditBudget, TapeRecorder
from shitcoims_tape.sources import (
    HeliusHistorySource,
    IterableSource,
    PumpFirehose,
    SourceGap,
    run_recorder,
    transactions_from_jsonl,
)
from shitcoims_tape.watch import WatchRegistry
from tests.test_tape_recorder import (
    Sink,
    _create_values,
    _trade_values,
    pump_logs,
    transaction,
)

WS_TEMPLATE = "wss://mainnet.helius-rpc.com/?api-key={api_key}"


def _mint() -> str:
    return str(Keypair().pubkey())


def _secret(tmp_path: Path) -> Path:
    path = tmp_path / "helius"
    path.write_text("super-sensitive-key", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _recorder() -> tuple[Sink, TapeRecorder]:
    sink = Sink()
    return sink, TapeRecorder(sink, WatchRegistry(sink))


def _launch_tx(slot: int = 1000, signature: str = "5" * 88) -> dict[str, Any]:
    mint, creator, curve = _mint(), _mint(), _mint()
    return transaction(
        pump_logs(
            ("CreateEvent", _create_values(mint, creator, curve)),
            ("TradeEvent", _trade_values(mint, creator, is_buy=True)),
        ),
        slot=slot,
        signature=signature,
    )


async def test_a_finite_source_drives_the_recorder_and_reports_what_it_wrote() -> None:
    sink, recorder = _recorder()
    source = IterableSource([_launch_tx(), _launch_tx(slot=1001, signature="4" * 88)])

    result = await run_recorder(source, recorder)

    assert result.transactions == 2
    assert result.gaps == ()
    assert result.events_written == len(sink.events) - len(sink.of(EventKind.WATCH))
    assert len(sink.of(EventKind.LAUNCH)) == 2


async def test_a_gap_is_surfaced_rather_than_reconnected_around() -> None:
    """A dropped socket means transactions were missed; an invisible hole is a fake dip."""

    seen: list[SourceGap] = []
    sink, recorder = _recorder()
    source = IterableSource([_launch_tx(), SourceGap(reason="stream_disconnected", last_observed_slot=9)])

    result = await run_recorder(source, recorder, on_gap=seen.append)

    assert result.transactions == 1
    assert [gap.reason for gap in result.gaps] == ["stream_disconnected"]
    assert seen and seen[0].last_observed_slot == 9
    assert result.to_json()["gaps"] == [
        {"reason": "stream_disconnected", "last_observed_slot": 9}
    ]
    assert sink.of(EventKind.LAUNCH)


class FakeHistoryClient:
    """A paged history service. Cursors are page indices; ``None`` means exhausted."""

    def __init__(self, pages: dict[str, Sequence[Sequence[dict[str, Any]]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str | None]] = []
        self.succeeded_only: list[bool] = []

    async def address_history_page(
        self,
        address: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        sort_order: str = "asc",
        succeeded_only: bool = True,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        self.calls.append((address, cursor))
        self.succeeded_only.append(succeeded_only)
        pages = self.pages.get(address, ())
        index = 0 if cursor is None else int(cursor)
        if index >= len(pages):
            return (), None
        # The service hands back a continuation token even after a SHORT page; only the
        # token going away means the history is over. Reproducing that here is the whole
        # point — a fake that stops handing out cursors after a short page would let the
        # truncation bug pass.
        nxt = str(index + 1) if index + 1 <= len(pages) else None
        return tuple(pages[index]), nxt


async def test_history_paging_stops_at_the_budget_instead_of_apologising_afterwards() -> None:
    """10 credits per 100-transaction page, charged BEFORE the request goes out."""

    mints = [_mint() for _ in range(5)]
    client = FakeHistoryClient({mint: [[_launch_tx()]] for mint in mints})
    budget = CreditBudget(limit=25)  # two pages, and a third would overspend
    source = HeliusHistorySource(client, mints, budget=budget)  # type: ignore[arg-type]
    _sink, recorder = _recorder()

    result = await run_recorder(source, recorder, budget=budget)

    assert budget.spent == 20
    assert result.credits_spent == 20
    assert budget.spent <= budget.limit
    assert [gap.reason for gap in result.gaps][-1] == "credit_budget_exhausted"
    # Every mint the budget could not reach is named, so the caller can censor it explicitly
    # instead of the frame quietly shrinking.
    assert set(source.unreached) | {history.mint for history in source.histories} == set(mints)


async def test_a_short_page_is_not_the_end_of_the_history() -> None:
    """The service returns a cursor after a short page; stopping there truncates the tape.

    This is the failure that motivated the rewrite. It is invisible on quiet mints (where a
    short page really is the end) and eats the busy ones, which are the only testable mints.
    """

    mint = _mint()
    client = FakeHistoryClient(
        {
            mint: [
                [_launch_tx(slot=1000, signature="5" * 88)],  # SHORT, and not the end
                [_launch_tx(slot=1001, signature="4" * 88)],
                [_launch_tx(slot=1002, signature="3" * 88)],
            ]
        }
    )
    budget = CreditBudget(limit=10_000)
    source = HeliusHistorySource(client, [mint], budget=budget, page_size=100)  # type: ignore[arg-type]
    sink, recorder = _recorder()

    result = await run_recorder(source, recorder, budget=budget)

    assert result.transactions == 3
    assert len(sink.of(EventKind.LAUNCH)) == 3
    history = source.histories[0]
    assert history.stopped_by == "exhausted"
    assert history.truncated is False
    assert history.pages == 4  # three pages of data, and one to prove the cursor ran out
    # 59-62% of an unfiltered pump.fun page is failed slippage attempts the recorder throws
    # away, and every page costs 10 credits whatever is in it.
    assert client.succeeded_only == [True, True, True, True]


async def test_the_page_cap_is_recorded_as_truncation_rather_than_read_as_the_whole_history() -> None:
    mint = _mint()
    client = FakeHistoryClient(
        {mint: [[_launch_tx(slot=1000 + n, signature=str(n % 9 + 1) * 88)] for n in range(6)]}
    )
    budget = CreditBudget(limit=10_000)
    source = HeliusHistorySource(client, [mint], budget=budget, page_cap=2)  # type: ignore[arg-type]
    _sink, recorder = _recorder()

    await run_recorder(source, recorder, budget=budget)

    history = source.histories[0]
    assert history.pages == 2
    assert history.stopped_by == "page_cap"
    assert history.truncated is True


async def test_the_observation_window_is_anchored_to_the_mints_own_first_transaction() -> None:
    """A fixed clock window per mint, so co-occurrence counts are comparable across mints."""

    mint = _mint()
    inside = _launch_tx(slot=1001, signature="4" * 88)
    inside["blockTime"] = 1_700_000_000 + 30
    first = _launch_tx(slot=1000, signature="5" * 88)
    first["blockTime"] = 1_700_000_000
    outside = _launch_tx(slot=1002, signature="3" * 88)
    outside["blockTime"] = 1_700_000_000 + 601
    client = FakeHistoryClient({mint: [[first], [inside], [outside]]})
    budget = CreditBudget(limit=10_000)
    source = HeliusHistorySource(client, [mint], budget=budget, window_seconds=600)  # type: ignore[arg-type]
    _sink, recorder = _recorder()

    result = await run_recorder(source, recorder, budget=budget)

    assert result.transactions == 2  # the transaction past the window never reaches the tape
    history = source.histories[0]
    assert history.stopped_by == "window"
    assert history.truncated is False  # the clock closed it, not our budget
    assert history.observed_seconds == 30


async def test_a_sanitised_history_failure_becomes_a_gap_and_the_run_continues() -> None:
    from shitcoims_intelligence.helius import HeliusIntelligenceError

    mints = [_mint(), _mint()]

    class Failing(FakeHistoryClient):
        async def address_history_page(
            self,
            address: str,
            *,
            limit: int = 100,
            cursor: str | None = None,
            sort_order: str = "asc",
            succeeded_only: bool = True,
        ) -> tuple[tuple[dict[str, Any], ...], str | None]:
            self.calls.append((address, cursor))
            if len(self.calls) == 1:
                raise HeliusIntelligenceError("Helius history RPC returned error -32000")
            return (_launch_tx(),), None

    client = Failing({})
    budget = CreditBudget(limit=1000)
    source = HeliusHistorySource(client, mints, budget=budget)  # type: ignore[arg-type]
    sink, recorder = _recorder()

    result = await run_recorder(source, recorder, budget=budget)

    assert len(result.gaps) == 1
    assert result.gaps[0].reason.startswith("history_failed:")
    assert "api-key" not in result.gaps[0].reason  # the client sanitises; we must not undo it
    assert result.transactions == 1
    assert sink.of(EventKind.LAUNCH)
    assert source.histories[0].stopped_by == "error"
    assert source.histories[0].truncated is True


def test_the_firehose_subscribes_to_both_pinned_pump_programs(tmp_path: Path) -> None:
    firehose = PumpFirehose(api_key_file=_secret(tmp_path), websocket_url_template=WS_TEMPLATE)
    request = firehose.subscription_request(firehose.snapshot())
    assert request["method"] == "transactionSubscribe"
    assert PUMP_PROGRAM_ID in request["params"][0]["accountInclude"]
    assert len(request["params"][0]["accountInclude"]) == 2
    # Full jsonParsed detail is not optional: logMessages is where the pump events live.
    assert request["params"][1]["transactionDetails"] == "full"
    assert request["params"][1]["encoding"] == "jsonParsed"


class FakeSocket:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value)

    async def ping(self) -> None:
        return None


class FakeContext:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *_args: Any) -> None:
        return None


async def test_the_firehose_yields_decodable_transactions_then_announces_its_disconnect(
    tmp_path: Path,
) -> None:
    """A transport error must never be interpolated: it can carry the credentialed URL."""

    mint, creator, curve = _mint(), _mint(), _mint()
    logs = pump_logs(("CreateEvent", _create_values(mint, creator, curve)))
    notification = {
        "jsonrpc": "2.0",
        "method": "transactionNotification",
        "params": {
            "subscription": 77,
            "result": {
                "slot": 4242,
                "signature": "5" * 88,
                "transactionIndex": 1,
                "transaction": {
                    "transaction": {"message": {"accountKeys": []}},
                    "meta": {"err": None, "logMessages": logs},
                },
            },
        },
    }
    socket = FakeSocket(
        [
            {"jsonrpc": "2.0", "id": 1, "result": 77},
            notification,
            RuntimeError("https://mainnet.helius-rpc.com/?api-key=super-sensitive-key"),
        ]
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    firehose = PumpFirehose(
        api_key_file=_secret(tmp_path),
        websocket_url_template=WS_TEMPLATE,
        websocket_factory=lambda *_a, **_k: FakeContext(socket),
        reconnect_seconds=0,
        sleeper=no_sleep,
    )
    stop = asyncio.Event()
    items = []
    iterator = firehose.transactions(stop=stop)
    items.append(await anext(iterator))
    items.append(await anext(iterator))
    stop.set()
    await iterator.aclose()

    payload, gap = items
    assert not isinstance(payload, SourceGap)
    assert payload["slot"] == 4242
    assert payload["transaction"]["signatures"] == ["5" * 88]

    assert isinstance(gap, SourceGap)
    assert gap.reason == "pump_stream_failed:RuntimeError"
    assert "api-key" not in gap.reason
    assert gap.last_observed_slot == 4242

    sink, recorder = _recorder()
    assert recorder.record_transaction(payload) > 0
    assert sink.of(EventKind.LAUNCH)


def test_captured_transactions_replay_from_jsonl_and_skip_unreadable_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "captured.jsonl"
    lines = [
        json.dumps(_launch_tx()),
        "{not json",
        json.dumps(_launch_tx(slot=2, signature="4" * 88)),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    source = transactions_from_jsonl(path)
    sink, recorder = _recorder()
    result = asyncio.run(run_recorder(source, recorder))
    assert result.transactions == 2
    assert len(sink.of(EventKind.LAUNCH)) == 2


def test_a_notification_for_another_subscription_is_ignored() -> None:
    from shitcoims_tape.sources import _notification_transaction

    body = json.dumps(
        {
            "method": "transactionNotification",
            "params": {"subscription": 1, "result": {"slot": 1}},
        }
    )
    assert _notification_transaction(body, 2) == (None, 0)


@pytest.mark.parametrize("size", [0, 101])
def test_a_page_size_outside_one_page_is_refused(size: int) -> None:
    with pytest.raises(ValueError, match="page_size"):
        HeliusHistorySource(FakeHistoryClient({}), [], budget=CreditBudget(1), page_size=size)  # type: ignore[arg-type]


def test_an_arbitrary_base64_payload_from_a_pump_program_is_quarantined() -> None:
    sink, recorder = _recorder()
    logs = [
        f"Program {PUMP_PROGRAM_ID} invoke [1]",
        "Program data: " + base64.b64encode(b"not-an-event").decode("ascii"),
        f"Program {PUMP_PROGRAM_ID} success",
    ]
    assert recorder.record_transaction(transaction(logs)) == 0
    assert sink.events == []
    assert recorder.counters.events_quarantined == 1
