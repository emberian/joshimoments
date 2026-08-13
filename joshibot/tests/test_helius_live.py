from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from solders.pubkey import Pubkey

from shitcoims_intelligence.config import KolWatchConfig
from shitcoims_intelligence.helius_live import (
    WATCHLIST_ADDRESS_CAP,
    run_helius_live,
    watchlist_addresses,
)

SYSTEM = "11111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"
COMPUTE = "ComputeBudget111111111111111111111111111111"


def addr(n: int) -> str:
    return str(Pubkey.from_bytes(bytes([n]) + bytes(31)))


def kol(handle: str, wallet: str | None) -> KolWatchConfig:
    return KolWatchConfig(
        handle=handle,
        label=handle,
        wallet=wallet,
        follow_replies=False,
        max_items=8,
        notes="",
    )


def fake_config(
    seed_wallets: tuple[str, ...] = (),
    kols: tuple[KolWatchConfig, ...] = (),
    **helius_fields: object,
) -> SimpleNamespace:
    helius = SimpleNamespace(
        seed_wallets=seed_wallets,
        api_key_file="/nonexistent/helius-key",
        websocket_url_template="wss://mainnet.helius-rpc.com/?api-key={api_key}",
        keepalive_seconds=30,
        reconnect_seconds=1.0,
        **helius_fields,
    )
    return SimpleNamespace(
        helius=helius,
        adapters=SimpleNamespace(x_apify=SimpleNamespace(kols=kols)),
    )


def test_module_is_advisory_and_has_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence import helius_live

    source = inspect.getsource(helius_live)
    assert "shitcoims_sentinel.executor" not in source
    assert "shitcoims_sentinel" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source


def test_watchlist_addresses_uniqueness_first_seen_and_cap() -> None:
    seeds = tuple(addr(index) for index in range(12))
    kols = (
        kol("dupseed", seeds[0]),
        kol("threadguy", None),
        kol("blank", "   "),
        kol("empty", ""),
        *(kol(f"kol{index}", addr(10 + index)) for index in range(14)),
    )

    result = watchlist_addresses(fake_config(seeds, kols))

    assert len(result) == WATCHLIST_ADDRESS_CAP == 20
    assert len(set(result)) == 20
    assert result[:12] == seeds
    assert result[12:] == tuple(addr(12 + index) for index in range(8))
    assert seeds[0] not in result[12:]
    assert addr(19) in result
    assert addr(20) not in result
    assert addr(23) not in result


def test_watchlist_addresses_empty_when_no_seeds_or_declared_kols() -> None:
    config = fake_config((), (kol("threadguy", None), kol("blank", ""), kol("spaces", "   ")))
    assert watchlist_addresses(config) == ()


def test_watchlist_addresses_seed_then_kol_without_overlap() -> None:
    config = fake_config(
        (SYSTEM, WSOL),
        (kol("blknoiz06", COMPUTE), kol("A1lon9", WSOL), kol("threadguy", None)),
    )
    assert watchlist_addresses(config) == (SYSTEM, WSOL, COMPUTE)


async def test_run_helius_live_returns_immediately_when_watchlist_empty() -> None:
    recorded: list[object] = []
    await run_helius_live(fake_config((), ()), recorded.append, asyncio.Event())
    assert recorded == []


async def test_run_helius_live_wires_collector_without_network(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeStream:
        def __init__(self, **kwargs: object) -> None:
            captured["kwargs"] = kwargs

        async def events(self, watchlist_provider, *, stop=None):
            captured["snapshot"] = await watchlist_provider()
            captured["stop"] = stop
            if False:
                yield

    monkeypatch.setattr(
        "shitcoims_intelligence.helius_live.HeliusTransactionStream",
        FakeStream,
    )
    stop = asyncio.Event()
    recorded: list[object] = []
    await run_helius_live(
        fake_config((SYSTEM,), (kol("blknoiz06", WSOL),)),
        recorded.append,
        stop,
    )

    snapshot = captured["snapshot"]
    assert snapshot.addresses == (SYSTEM, WSOL)
    assert snapshot.version.startswith("helius-live-")
    assert captured["stop"] is stop
    kwargs = captured["kwargs"]
    assert kwargs["api_key_file"] == "/nonexistent/helius-key"
    assert kwargs["websocket_url_template"] == "wss://mainnet.helius-rpc.com/?api-key={api_key}"
    assert kwargs["keepalive_seconds"] == 30
    assert kwargs["reconnect_seconds"] == 1.0
    assert kwargs["max_addresses"] == WATCHLIST_ADDRESS_CAP
    assert recorded == []
