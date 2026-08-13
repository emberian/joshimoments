"""The live subscription path must never emit a row without an event clock.

``transactionNotification`` carries a slot and no block time, which is how 169 of
169 live-path rows reached the store with ``block_time=None`` while every backfill
row (arriving a median 31 hours late) had one.  These tests pin the fix: the slot
is resolved through ``getBlockTime`` behind a bounded cache, and a slot that will
not resolve produces a defect event instead of a clockless row.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from shitcoims_intelligence.collector import (
    stream_event_observation,
    wallet_transaction_observation,
)
from shitcoims_intelligence.helius import (
    HeliusIntelligenceError,
    HeliusTransactionStream,
    SlotBlockTimeCache,
    WatchlistSnapshot,
)

WALLET = "11111111111111111111111111111111"
OTHER_WALLET = "ComputeBudget111111111111111111111111111111"
MINT = "So11111111111111111111111111111111111111112"
SIGNATURE_A = "5" * 64
SIGNATURE_B = "6" * 64
WS_TEMPLATE = "wss://mainnet.helius-rpc.com/?api-key={api_key}"
ATLAS_WS_TEMPLATE = "wss://atlas-mainnet.helius-rpc.com/?api-key={api_key}"
BLOCK_TIME = 1_755_000_000


def secret_file(tmp_path: Path, value: str = "super-sensitive-key") -> Path:
    path = tmp_path / "helius"
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def notification(
    signature: str,
    *,
    slot: int,
    subscription: int = 99,
    block_time: int | None = None,
) -> dict[str, Any]:
    """A ``transactionNotification`` shaped like the live Helius payload."""

    result: dict[str, Any] = {
        "transaction": {
            "transaction": {
                "signatures": [signature],
                "message": {
                    "accountKeys": [
                        {"pubkey": WALLET, "signer": True, "writable": True},
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
                        "owner": WALLET,
                        "uiTokenAmount": {"amount": "100", "decimals": 6},
                    }
                ],
                "postTokenBalances": [
                    {
                        "accountIndex": 2,
                        "mint": MINT,
                        "owner": WALLET,
                        "uiTokenAmount": {"amount": "250", "decimals": 6},
                    }
                ],
                "loadedAddresses": {"writable": [], "readonly": []},
            },
        },
        "signature": signature,
        "slot": slot,
        "transactionIndex": 7,
    }
    if block_time is not None:
        result["blockTime"] = block_time
    return {
        "jsonrpc": "2.0",
        "method": "transactionNotification",
        "params": {"subscription": subscription, "result": result},
    }


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


class FakeRpc:
    """An offline ``getBlockTime`` endpoint that records every request."""

    def __init__(self, answers: dict[int, Any] | None = None, default: Any = None) -> None:
        self.answers = answers or {}
        self.default = default
        self.slots: list[int] = []
        self.urls: list[httpx.URL] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "getBlockTime"
        slot = int(body["params"][0])
        self.slots.append(slot)
        self.urls.append(request.url)
        answer = self.answers.get(slot, self.default)
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": answer})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def no_sleep(_seconds: float) -> None:
    return None


async def watchlist() -> WatchlistSnapshot:
    return WatchlistSnapshot("wallets-v7", (WALLET,))


def build_stream(
    tmp_path: Path,
    socket: FakeSocket,
    *,
    http: httpx.AsyncClient | None = None,
    websocket_url_template: str = WS_TEMPLATE,
    **overrides: Any,
) -> HeliusTransactionStream:
    def factory(*_args: Any, **_kwargs: Any) -> FakeContext:
        return FakeContext(socket)

    return HeliusTransactionStream(
        api_key_file=secret_file(tmp_path),
        websocket_url_template=websocket_url_template,
        websocket_factory=factory,
        keepalive_seconds=30,
        reconnect_seconds=0,
        sleeper=no_sleep,
        http=http,
        **overrides,
    )


async def collect(stream: HeliusTransactionStream, count: int) -> list[Any]:
    events = stream.events(watchlist)
    try:
        return [await anext(events) for _ in range(count)]
    finally:
        await events.aclose()


async def test_live_row_gets_its_block_time_from_the_slot(tmp_path: Path) -> None:
    rpc = FakeRpc({42: BLOCK_TIME})
    socket = FakeSocket(
        [{"jsonrpc": "2.0", "id": 1, "result": 99}, notification(SIGNATURE_A, slot=42)]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 3)

    assert [event.kind for event in observed] == ["source_health", "source_health", "transaction"]
    transaction = observed[2].transaction
    assert transaction is not None
    assert transaction.slot == 42
    assert transaction.block_time == BLOCK_TIME
    assert rpc.slots == [42]
    # Derived from the WebSocket template: the RPC goes to the https origin.
    assert rpc.urls[0].scheme == "https"
    assert rpc.urls[0].host == "mainnet.helius-rpc.com"
    # The whole point: the persisted observation now has an event clock.
    assert wallet_transaction_observation(transaction).emitted_at is not None


async def test_atlas_websocket_template_still_resolves_against_the_rpc_host(
    tmp_path: Path,
) -> None:
    rpc = FakeRpc({42: BLOCK_TIME})
    socket = FakeSocket(
        [{"jsonrpc": "2.0", "id": 1, "result": 99}, notification(SIGNATURE_A, slot=42)]
    )
    async with rpc.client() as http:
        stream = build_stream(
            tmp_path, socket, http=http, websocket_url_template=ATLAS_WS_TEMPLATE
        )
        observed = await collect(stream, 3)

    assert observed[2].transaction is not None
    assert observed[2].transaction.block_time == BLOCK_TIME
    assert rpc.urls[0].host == "mainnet.helius-rpc.com"


async def test_second_transaction_in_the_same_slot_is_a_cache_hit(tmp_path: Path) -> None:
    rpc = FakeRpc({42: BLOCK_TIME})
    socket = FakeSocket(
        [
            {"jsonrpc": "2.0", "id": 1, "result": 99},
            notification(SIGNATURE_A, slot=42),
            notification(SIGNATURE_B, slot=42),
        ]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 4)

    transactions = [event.transaction for event in observed if event.kind == "transaction"]
    assert [item.signature for item in transactions if item is not None] == [
        SIGNATURE_A,
        SIGNATURE_B,
    ]
    assert all(item is not None and item.block_time == BLOCK_TIME for item in transactions)
    assert rpc.slots == [42]  # One RPC for two rows sharing a slot.


async def test_payload_block_time_is_used_without_any_rpc(tmp_path: Path) -> None:
    rpc = FakeRpc({42: BLOCK_TIME})
    socket = FakeSocket(
        [
            {"jsonrpc": "2.0", "id": 1, "result": 99},
            notification(SIGNATURE_A, slot=42, block_time=BLOCK_TIME - 5),
        ]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 3)

    assert observed[2].transaction is not None
    assert observed[2].transaction.block_time == BLOCK_TIME - 5
    assert rpc.slots == []


async def test_unresolvable_slot_defects_and_emits_no_row(tmp_path: Path) -> None:
    rpc = FakeRpc(default=None)  # getBlockTime keeps answering null.
    socket = FakeSocket(
        [{"jsonrpc": "2.0", "id": 1, "result": 99}, notification(SIGNATURE_A, slot=42)]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 3)

    assert [event.kind for event in observed] == ["source_health", "source_health", "defect"]
    defect = observed[2]
    assert defect.transaction is None
    assert defect.reason == f"block_time_unresolved:{SIGNATURE_A}"
    assert defect.last_observed_slot == 42
    assert rpc.slots == [42, 42, 42]  # Bounded retries, then give up.
    # The refusal is recorded evidence, not a silent hole.
    observation = stream_event_observation(defect)
    assert observation.kind == "stream_defect"
    assert observation.payload["reason"] == f"block_time_unresolved:{SIGNATURE_A}"


async def test_rpc_error_defects_rather_than_guessing(tmp_path: Path) -> None:
    rpc = FakeRpc(default=httpx.ConnectError("boom"))
    socket = FakeSocket(
        [{"jsonrpc": "2.0", "id": 1, "result": 99}, notification(SIGNATURE_A, slot=42)]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 3)

    assert observed[2].kind == "defect"
    assert observed[2].transaction is None


async def test_transient_null_is_retried_then_resolved(tmp_path: Path) -> None:
    rpc = FakeRpc({42: [None, BLOCK_TIME]})
    socket = FakeSocket(
        [{"jsonrpc": "2.0", "id": 1, "result": 99}, notification(SIGNATURE_A, slot=42)]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 3)

    assert observed[2].kind == "transaction"
    assert observed[2].transaction is not None
    assert observed[2].transaction.block_time == BLOCK_TIME
    assert rpc.slots == [42, 42]


async def test_stream_keeps_draining_after_a_defect(tmp_path: Path) -> None:
    rpc = FakeRpc({42: None, 43: BLOCK_TIME + 1})
    socket = FakeSocket(
        [
            {"jsonrpc": "2.0", "id": 1, "result": 99},
            notification(SIGNATURE_A, slot=42),
            notification(SIGNATURE_B, slot=43),
        ]
    )
    async with rpc.client() as http:
        observed = await collect(build_stream(tmp_path, socket, http=http), 4)

    assert [event.kind for event in observed] == [
        "source_health",
        "source_health",
        "defect",
        "transaction",
    ]
    assert observed[3].transaction is not None
    assert observed[3].transaction.signature == SIGNATURE_B
    assert observed[3].transaction.block_time == BLOCK_TIME + 1


async def test_hanging_resolver_hits_the_deadline_and_the_stream_continues(
    tmp_path: Path,
) -> None:
    async def resolver(slot: int) -> int | None:
        if slot == 42:
            await asyncio.sleep(30)
            raise AssertionError("unreachable")
        return BLOCK_TIME + 1

    socket = FakeSocket(
        [
            {"jsonrpc": "2.0", "id": 1, "result": 99},
            notification(SIGNATURE_A, slot=42),
            notification(SIGNATURE_B, slot=43),
        ]
    )
    stream = build_stream(
        tmp_path,
        socket,
        block_time_resolver=resolver,
        block_time_timeout_seconds=0.1,
    )
    observed = await collect(stream, 4)

    assert [event.kind for event in observed] == [
        "source_health",
        "source_health",
        "defect",
        "transaction",
    ]
    assert observed[3].transaction is not None
    assert observed[3].transaction.block_time == BLOCK_TIME + 1


async def test_cache_evicts_least_recently_used_and_never_caches_a_failure() -> None:
    answers: dict[int, Any] = {1: 101, 2: 102, 3: 103, 4: [None, 104]}
    calls: list[int] = []

    async def fetch(slot: int) -> int | None:
        calls.append(slot)
        answer = answers[slot]
        if isinstance(answer, list):
            answer = answer.pop(0)
        return answer

    cache = SlotBlockTimeCache(fetch=fetch, max_entries=2, sleeper=no_sleep)
    assert await cache.resolve(1) == 101
    assert await cache.resolve(2) == 102
    assert await cache.resolve(1) == 101  # Hit; also makes slot 2 the LRU victim.
    assert await cache.resolve(3) == 103
    assert calls == [1, 2, 3]

    stats = cache.stats()
    assert (stats.lookups, stats.hits, stats.misses, stats.evictions, stats.size) == (
        4,
        1,
        3,
        1,
        2,
    )
    assert await cache.resolve(2) == 102  # Evicted, so refetched.
    assert calls == [1, 2, 3, 2]

    # A null answer is the node being behind, never a fact: it must not be cached.
    assert await cache.resolve(4) == 104
    assert calls[-2:] == [4, 4]
    assert await cache.resolve(4) == 104
    assert calls.count(4) == 2


async def test_cache_retries_bounded_number_of_times_then_reports_failure() -> None:
    calls = 0

    async def fetch(_slot: int) -> int | None:
        nonlocal calls
        calls += 1
        raise HeliusIntelligenceError("Helius RPC returned error -32004")

    cache = SlotBlockTimeCache(fetch=fetch, max_attempts=4, sleeper=no_sleep)
    assert await cache.resolve(42) is None
    assert calls == 4
    assert cache.stats().size == 0


def test_stream_still_has_no_transaction_capabilities(tmp_path: Path) -> None:
    stream = HeliusTransactionStream(
        api_key_file=secret_file(tmp_path),
        websocket_url_template=WS_TEMPLATE,
    )
    public_methods = {name for name in dir(stream) if not name.startswith("_")}
    assert public_methods == {"events", "subscription_request"}


@pytest.mark.parametrize("slot", [-1, True, "42"])
async def test_cache_rejects_a_slot_that_is_not_a_slot(slot: Any) -> None:
    async def fetch(_slot: int) -> int | None:
        raise AssertionError("must not be called")

    cache = SlotBlockTimeCache(fetch=fetch, sleeper=no_sleep)
    with pytest.raises(ValueError):
        await cache.resolve(slot)
