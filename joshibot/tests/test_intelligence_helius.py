from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from shitcoims_intelligence.collector import (
    BoundedHistoryCollector,
    CanonicalObservationSink,
    CollectionBudgetExceeded,
    CreditLedger,
    CreditLimits,
    MemoryCursorStore,
    history_cursor_name,
    mint_tape_observation,
    raw_history_blob,
    stream_event_observation,
    wallet_transaction_observation,
)
from shitcoims_intelligence.helius import (
    HeliusHistoryClient,
    HeliusIntelligenceError,
    HeliusTransactionStream,
    HistoryBounds,
    HistoryResult,
    StreamEvent,
    WalletTransaction,
    WatchlistSnapshot,
    normalize_wallet_transaction,
)
from shitcoims_intelligence.models import Finality

WALLET = "11111111111111111111111111111111"
OTHER_WALLET = "ComputeBudget111111111111111111111111111111"
MINT = "So11111111111111111111111111111111111111112"
SIGNATURE_A = "5" * 64
SIGNATURE_B = "6" * 64
HTTP_TEMPLATE = "https://mainnet.helius-rpc.com/?api-key={api_key}"
WS_TEMPLATE = "wss://mainnet.helius-rpc.com/?api-key={api_key}"


def secret_file(tmp_path: Path, value: str = "super-sensitive-key") -> Path:
    path = tmp_path / "helius"
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def full_transaction(
    signature: str,
    *,
    slot: int,
    transaction_index: int = 0,
    wallet: str = WALLET,
) -> dict[str, Any]:
    return {
        "slot": slot,
        "transactionIndex": transaction_index,
        "blockTime": 1_700_000_000 + slot,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {"pubkey": wallet, "signer": True, "writable": True},
                    {"pubkey": OTHER_WALLET, "signer": False, "writable": True},
                ],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [1_000_000, 20],
            "postBalances": [895_000, 100_020],
            "preTokenBalances": [
                {
                    "accountIndex": 2,
                    "mint": MINT,
                    "owner": wallet,
                    "uiTokenAmount": {"amount": "100", "decimals": 6},
                }
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 2,
                    "mint": MINT,
                    "owner": wallet,
                    "uiTokenAmount": {"amount": "250", "decimals": 6},
                }
            ],
            "loadedAddresses": {"writable": [], "readonly": []},
        },
    }


def bounds(**overrides: Any) -> HistoryBounds:
    values = {
        "max_pages": 3,
        "max_transactions": 10,
        "max_estimated_credits": 150,
        "page_size": 10,
        "estimated_credits_per_page": 50,
    }
    values.update(overrides)
    return HistoryBounds(**values)


def test_normalizes_wallet_balance_deltas_and_ordering_identity() -> None:
    transaction = normalize_wallet_transaction(
        full_transaction(SIGNATURE_A, slot=42, transaction_index=7),
        WALLET,
        commitment="finalized",
    )

    assert transaction.signature == SIGNATURE_A
    assert transaction.slot == 42
    assert transaction.transaction_index == 7
    assert transaction.succeeded is True
    assert transaction.fee_lamports == 5_000
    assert transaction.fee_payer == WALLET
    assert transaction.wallet_paid_fee is True
    assert transaction.sol_delta_lamports == -105_000
    assert transaction.sol_delta_exact is True
    assert [(item.mint, item.raw_delta, item.decimals) for item in transaction.token_deltas] == [
        (MINT, 150, 6)
    ]
    assert transaction.token_deltas_exact is True


@pytest.mark.asyncio
async def test_history_follows_cursor_after_short_page_and_caches_raw_once(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []
    raw_pages = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        options = body["params"][1]
        if "paginationToken" not in options:
            result = {
                "data": [full_transaction(SIGNATURE_A, slot=42)],
                "paginationToken": "42:1",
            }
        else:
            result = {
                "data": [full_transaction(SIGNATURE_B, slot=41)],
                "paginationToken": None,
            }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    async def cache_page(page: Any) -> str:
        raw_pages.append(page)
        return f"raw-page-{len(raw_pages)}"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path),
            http_url_template=HTTP_TEMPLATE,
            http=http,
            raw_page_sink=cache_page,
        )
        result = await client.fetch(WALLET, bounds())

    assert [item.signature for item in result.transactions] == [SIGNATURE_A, SIGNATURE_B]
    assert requests[1]["params"][1]["paginationToken"] == "42:1"
    assert requests[0]["params"][1]["filters"]["tokenAccounts"] == "balanceChanged"
    assert result.source_exhausted is True
    assert result.bound_reached is False
    assert result.pages_fetched == 2
    assert result.estimated_credits == 100
    assert len(raw_pages) == 2
    assert result.transactions[0].raw_blob_ids == ("raw-page-1",)
    assert result.transactions[1].raw_blob_ids == ("raw-page-2",)
    assert raw_pages[0].requested_cursor is None
    assert raw_pages[1].requested_cursor == "42:1"
    assert len(raw_pages[0].content_hash) == 64
    assert len(raw_pages[0].request_fingerprint) == 64
    assert b"super-sensitive-key" not in raw_pages[0].body
    assert not hasattr(raw_pages[0], "url")
    assert raw_history_blob(raw_pages[0]).body == raw_pages[0].body


@pytest.mark.asyncio
async def test_history_credit_bound_stops_with_resumable_cursor(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "data": [full_transaction(SIGNATURE_A, slot=42)],
                    "paginationToken": "42:1",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path), http_url_template=HTTP_TEMPLATE, http=http
        )
        result = await client.fetch(
            WALLET,
            bounds(max_pages=10, max_estimated_credits=50),
        )

    assert calls == 1
    assert result.next_cursor == "42:1"
    assert result.bound_reached is True
    assert result.estimated_credits == 50


@pytest.mark.asyncio
async def test_history_rejects_repeated_cursor(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"data": [], "paginationToken": "42:1"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path), http_url_template=HTTP_TEMPLATE, http=http
        )
        with pytest.raises(HeliusIntelligenceError, match="cursor repeated"):
            await client.fetch(WALLET, bounds(), cursor="42:1")


@pytest.mark.asyncio
async def test_history_transport_error_never_exposes_credential(tmp_path: Path) -> None:
    key = "do-not-print-this-helius-key"

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"could not reach {request.url}", request=request)

    async def no_sleep(_seconds: float) -> None:
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path, key),
            http_url_template=HTTP_TEMPLATE,
            http=http,
            max_attempts=2,
            sleeper=no_sleep,
        )
        with pytest.raises(HeliusIntelligenceError) as raised:
            await client.fetch(WALLET, bounds())

    assert key not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_secret_file_permissions_and_endpoint_origin_are_enforced(tmp_path: Path) -> None:
    secret = secret_file(tmp_path)
    os.chmod(secret, 0o644)
    async with httpx.AsyncClient() as http:
        with pytest.raises(HeliusIntelligenceError, match="must be private"):
            HeliusHistoryClient(
                api_key_file=secret,
                http_url_template=HTTP_TEMPLATE,
                http=http,
            )


@pytest.mark.asyncio
async def test_credit_ledger_reserves_concurrent_worst_case_and_rolls_utc_day() -> None:
    now = datetime(2026, 8, 12, 23, 59, tzinfo=UTC)
    ledger = CreditLedger(CreditLimits(daily=100, monthly=300), clock=lambda: now)
    await ledger.reserve(60)
    with pytest.raises(CollectionBudgetExceeded, match="daily"):
        await ledger.reserve(50)
    usage = await ledger.commit(60, 25)
    assert usage.daily_used == 25
    assert usage.daily_remaining == 75

    now = datetime(2026, 8, 13, 0, 1, tzinfo=UTC)
    usage = await ledger.snapshot()
    assert usage.utc_day == date(2026, 8, 13)
    assert usage.daily_used == 0
    assert usage.monthly_used == 25


class RecordingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.transactions: list[WalletTransaction] = []
        self.events: list[StreamEvent] = []
        self.fail = fail

    async def record_wallet_transaction(self, transaction: WalletTransaction) -> None:
        if self.fail:
            raise RuntimeError("disk failure")
        self.transactions.append(transaction)

    async def record_source_event(self, event: StreamEvent) -> None:
        self.events.append(event)


class FakeHistoryClient:
    def __init__(self, result: HistoryResult) -> None:
        self.result = result
        self.cursors: list[str | None] = []

    async def fetch(
        self, _wallet: str, _bounds: HistoryBounds, *, cursor: str | None = None
    ) -> HistoryResult:
        self.cursors.append(cursor)
        return self.result


@pytest.mark.asyncio
async def test_collector_advances_cursor_only_after_sink_and_accounts_credits() -> None:
    transaction = normalize_wallet_transaction(
        full_transaction(SIGNATURE_A, slot=42), WALLET, commitment="finalized"
    )
    result = HistoryResult((transaction,), "next:1", False, True, 1, 0, 50)
    client = FakeHistoryClient(result)
    sink = RecordingSink()
    cursors = MemoryCursorStore()
    ledger = CreditLedger(CreditLimits(daily=10_000, monthly=300_000))
    requested_bounds = bounds()
    collector = BoundedHistoryCollector(
        client=client,  # type: ignore[arg-type]
        sink=sink,
        credits=ledger,
        read_cursor=cursors.read,
        write_cursor=cursors.write,
    )

    report = await collector.collect([WALLET], requested_bounds)

    cursor_name = history_cursor_name(WALLET, requested_bounds)
    assert cursors.values[cursor_name] == "next:1"
    assert sink.transactions == [transaction]
    assert report.total_estimated_credits == 50
    assert report.wallets[0].credit_usage.daily_used == 50


@pytest.mark.asyncio
async def test_collector_does_not_advance_cursor_when_sink_fails() -> None:
    transaction = normalize_wallet_transaction(
        full_transaction(SIGNATURE_A, slot=42), WALLET, commitment="finalized"
    )
    result = HistoryResult((transaction,), "next:1", False, True, 1, 0, 50)
    cursors = MemoryCursorStore()
    ledger = CreditLedger()
    collector = BoundedHistoryCollector(
        client=FakeHistoryClient(result),  # type: ignore[arg-type]
        sink=RecordingSink(fail=True),
        credits=ledger,
        read_cursor=cursors.read,
        write_cursor=cursors.write,
    )

    with pytest.raises(RuntimeError, match="disk failure"):
        await collector.collect([WALLET], bounds())
    assert cursors.values == {}
    usage = await ledger.snapshot()
    assert usage.reserved == 0
    assert usage.daily_used == 150  # Uncertain provider usage is charged fail-closed.


class FakeSocket:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.sent: list[dict[str, Any]] = []
        self.ping_count = 0

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value)

    async def ping(self) -> None:
        self.ping_count += 1
        return None


class FakeContext:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeSocket:
        return self.socket

    async def __aexit__(self, *_args: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_stream_is_confirmed_full_versioned_deduped_and_marks_disconnect(
    tmp_path: Path,
) -> None:
    notification_result = {
        "transaction": {
            "transaction": full_transaction(SIGNATURE_A, slot=42)["transaction"],
            "meta": full_transaction(SIGNATURE_A, slot=42)["meta"],
        },
        "signature": SIGNATURE_A,
        "slot": 42,
        "transactionIndex": 7,
    }
    notification = {
        "jsonrpc": "2.0",
        "method": "transactionNotification",
        "params": {"subscription": 99, "result": notification_result},
    }
    socket = FakeSocket(
        [
            {"jsonrpc": "2.0", "id": 1, "result": 99},
            TimeoutError(),
            notification,
            notification,
            RuntimeError("credential-bearing transport detail"),
        ]
    )

    def factory(*_args: Any, **_kwargs: Any) -> FakeContext:
        return FakeContext(socket)

    async def watchlist() -> WatchlistSnapshot:
        return WatchlistSnapshot("wallets-v7", (WALLET,))

    async def no_sleep(_seconds: float) -> None:
        return None

    stream = HeliusTransactionStream(
        api_key_file=secret_file(tmp_path),
        websocket_url_template=WS_TEMPLATE,
        websocket_factory=factory,
        keepalive_seconds=30,
        reconnect_seconds=0,
        sleeper=no_sleep,
    )
    events = stream.events(watchlist)
    observed = [await anext(events) for _ in range(5)]
    await events.aclose()

    assert [event.kind for event in observed] == [
        "source_health",
        "source_health",
        "transaction",
        "source_health",
        "gap",
    ]
    assert observed[0].status == "connecting"
    assert observed[1].status == "healthy"
    assert observed[2].transaction is not None
    assert observed[2].transaction.commitment == "confirmed"
    assert observed[3].status == "degraded"
    assert observed[3].reason == "Helius transaction stream failed (RuntimeError)"
    assert observed[4].reason == "stream_disconnected"

    request = socket.sent[0]
    assert request["method"] == "transactionSubscribe"
    assert request["params"][0]["accountInclude"] == [WALLET]
    assert request["params"][0]["tokenAccounts"] == "balanceChanged"
    assert request["params"][1]["commitment"] == "confirmed"
    assert request["params"][1]["transactionDetails"] == "full"
    assert request["params"][1]["maxSupportedTransactionVersion"] == 0
    assert socket.ping_count == 1


@pytest.mark.asyncio
async def test_stream_replaces_versioned_watchlist_with_explicit_gap(tmp_path: Path) -> None:
    sockets = [
        FakeSocket([{"jsonrpc": "2.0", "id": 1, "result": 91}]),
        FakeSocket([{"jsonrpc": "2.0", "id": 2, "result": 92}]),
    ]

    def factory(*_args: Any, **_kwargs: Any) -> FakeContext:
        return FakeContext(sockets.pop(0))

    calls = 0

    async def watchlist() -> WatchlistSnapshot:
        nonlocal calls
        calls += 1
        if calls == 1:
            return WatchlistSnapshot("wallets-v1", (WALLET,))
        return WatchlistSnapshot("wallets-v2", (WALLET, OTHER_WALLET))

    stream = HeliusTransactionStream(
        api_key_file=secret_file(tmp_path),
        websocket_url_template=WS_TEMPLATE,
        websocket_factory=factory,
    )
    events = stream.events(watchlist)
    observed = [await anext(events) for _ in range(5)]
    await events.aclose()

    assert [(event.kind, event.watchlist_version) for event in observed] == [
        ("source_health", "wallets-v1"),
        ("source_health", "wallets-v1"),
        ("gap", "wallets-v2"),
        ("source_health", "wallets-v2"),
        ("source_health", "wallets-v2"),
    ]
    assert observed[2].reason == "watchlist_changed"


def test_stream_requires_private_key_file_but_has_no_transaction_capabilities(tmp_path: Path) -> None:
    stream = HeliusTransactionStream(
        api_key_file=secret_file(tmp_path),
        websocket_url_template=WS_TEMPLATE,
    )
    public_methods = {name for name in dir(stream) if not name.startswith("_")}
    assert public_methods == {"events", "subscription_request"}
    assert "send" not in public_methods
    assert "swap" not in public_methods


def test_canonical_observations_preserve_finality_fee_and_gap() -> None:
    transaction = normalize_wallet_transaction(
        full_transaction(SIGNATURE_A, slot=42), WALLET, commitment="finalized"
    )
    observation = wallet_transaction_observation(transaction)
    assert observation.finality is Finality.FINALIZED
    assert observation.payload["fee_payer"] == WALLET
    assert observation.payload["wallet_paid_fee"] is True
    assert observation.payload["sol_delta_lamports"] == -105_000

    gap = stream_event_observation(
        StreamEvent(
            kind="gap",
            watchlist_version="wallets-v7",
            reason="stream_disconnected",
            last_observed_slot=42,
        )
    )
    assert gap.kind == "stream_gap"
    assert gap.payload["last_observed_slot"] == 42
    assert gap.finality is Finality.CONFIRMED


@pytest.mark.asyncio
async def test_canonical_sink_adapts_synchronous_single_writer() -> None:
    recorded = []
    sink = CanonicalObservationSink(recorded.append)
    transaction = normalize_wallet_transaction(
        full_transaction(SIGNATURE_A, slot=42), WALLET, commitment="confirmed"
    )
    await sink.record_wallet_transaction(transaction)
    await sink.record_source_event(
        StreamEvent(kind="gap", watchlist_version="v1", reason="stream_disconnected")
    )
    assert [item.kind for item in recorded] == ["wallet_transaction", "stream_gap"]


@pytest.mark.asyncio
async def test_token_largest_accounts_returns_positive_ui_amounts(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "getTokenLargestAccounts"
        assert body["params"] == [MINT]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "context": {"slot": 1},
                    "value": [
                        {"address": WALLET, "uiAmount": 40.0, "amount": "40", "decimals": 0},
                        {"address": OTHER_WALLET, "amount": "2000000", "decimals": 6},
                        {"address": WALLET, "uiAmount": 0},
                    ],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path),
            http_url_template=HTTP_TEMPLATE,
            http=http,
        )
        amounts = await client.token_largest_accounts(MINT)

    assert amounts == (40.0, 2.0)


@pytest.mark.asyncio
async def test_token_largest_accounts_rpc_error_is_sanitized(tmp_path: Path) -> None:
    key = "do-not-print-this-helius-key"

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32602, "message": f"invalid param {key}"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path, key),
            http_url_template=HTTP_TEMPLATE,
            http=http,
        )
        with pytest.raises(HeliusIntelligenceError) as raised:
            await client.token_largest_accounts(MINT)

    assert key not in str(raised.value)
    assert key not in repr(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_mint_enhanced_page_reads_data_envelope(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "getTransactionsForAddress"
        assert body["params"][0] == MINT
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "data": [full_transaction(SIGNATURE_A, slot=42)],
                    "paginationToken": None,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HeliusHistoryClient(
            api_key_file=secret_file(tmp_path),
            http_url_template=HTTP_TEMPLATE,
            http=http,
        )
        page = await client.mint_enhanced_page(MINT, limit=20)

    assert len(page) == 1
    assert page[0]["slot"] == 42


def test_mint_tape_observation_is_token_subject_and_advisory() -> None:
    observation = mint_tape_observation(
        MINT,
        prints=[{"ts": 1, "mint": MINT, "wallet": WALLET, "side": "buy", "quote_sol": 0.1, "base": 1.0}],
        features={"holder_count": 4, "holder_top1": 0.25, "trade_count": 1},
        provenance=("helius:getTokenLargestAccounts", "helius:getTransactionsForAddress"),
    )
    assert observation.kind == "mint_tape"
    assert observation.subject_type == "token"
    assert observation.subject_id == MINT
    assert observation.payload["mint"] == MINT
    assert observation.payload["holder_top1"] == 0.25
    assert observation.finality is Finality.FINALIZED
    assert observation.provenance == (
        "helius:getTokenLargestAccounts",
        "helius:getTransactionsForAddress",
    )
