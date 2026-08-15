from __future__ import annotations

import asyncio
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from solders.keypair import Keypair

from shitcoims_sentinel.candles import (
    _CACHE,
    DEXSCREENER,
    WINDOWS,
    CandleError,
    _bars_from_windows,
    fetch_candles,
)
from shitcoims_sentinel.history import performance_summary, read_events, read_trades
from shitcoims_sentinel.policies import (
    policies_for_unmonitored,
    policy_from_payload,
    policy_to_api_mapping,
)
from shitcoims_sentinel.server import _TaskReentrantLock, create_app
from shitcoims_sentinel.storage import EventJournal

TRADE_FIELDS = [
    "timestamp",
    "wallet",
    "mint",
    "name",
    "reason",
    "input_amount",
    "output_lamports",
    "signature",
]


def _write_jsonl(path: Path, rows: list[Any]) -> None:
    lines: list[str] = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_trades(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in TRADE_FIELDS})


@pytest.fixture(autouse=True)
def _clear_candle_cache() -> None:
    _CACHE.clear()
    yield
    _CACHE.clear()


def test_dashboard_policy_payload_round_trips_to_api_item() -> None:
    mint = str(Keypair().pubkey())
    payload = {
        "name": "DASH",
        "cost_basis_sol": 1.25,
        "stop_loss_pct": -30,
        "take_profit_pct": 100,
        "trailing_stop_pct": 20,
        "rug_exit": True,
        "dispose_after_break_even": False,
    }
    item = policy_to_api_mapping(policy_from_payload(mint, payload))
    assert item["mint"] == mint
    assert item["name"] == "DASH"
    assert item["cost_basis_sol"] == 1.25
    assert "buy_price_sol" not in item
    assert item["stop_loss_pct"] == -30.0
    assert item["take_profit_pct"] == 100.0
    assert item["trailing_stop_pct"] == 20.0
    assert item["rug_exit"] is True
    assert item["dispose_after_break_even"] is False


def test_read_events_returns_last_n_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    _write_jsonl(
        path,
        [
            {"timestamp": "t1", "severity": "info", "category": "heartbeat", "message": "one"},
            {"timestamp": "t2", "severity": "warning", "category": "discovery", "message": "two"},
            {"timestamp": "t3", "severity": "critical", "category": "execution", "message": "three"},
            {"timestamp": "t4", "severity": "info", "category": "system", "message": "four"},
        ],
    )
    items = read_events(path, limit=3)
    assert [item["timestamp"] for item in items] == ["t4", "t3", "t2"]
    assert [item["message"] for item in items] == ["four", "three", "two"]
    assert items[0]["severity"] == "info"
    assert items[1]["category"] == "execution"


def test_read_events_skips_blank_invalid_and_non_objects(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    _write_jsonl(
        path,
        [
            {"timestamp": "keep-old", "message": "old"},
            "",
            "not-json",
            ["array"],
            12,
            {"timestamp": "keep-new", "severity": "warning", "category": "discovery", "message": "new"},
        ],
    )
    items = read_events(path, limit=10)
    assert [item["timestamp"] for item in items] == ["keep-new", "keep-old"]
    assert items[0]["severity"] == "warning"
    assert items[1]["severity"] == "info"
    assert items[1]["category"] == "event"


def test_read_events_missing_file_and_nonpositive_limit(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    assert read_events(path) == []
    path.write_text('{"message": "x"}\n', encoding="utf-8")
    assert read_events(path, limit=0) == []
    assert read_events(path, limit=-3) == []


def test_read_events_truncates_fields_and_caps_limit(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        {
            "timestamp": "T" * 80,
            "severity": "S" * 20,
            "category": "C" * 40,
            "message": "M" * 600,
        }
        for _ in range(520)
    ]
    _write_jsonl(path, rows)
    items = read_events(path, limit=1000)
    assert len(items) == 500
    assert items[0]["timestamp"] == "T" * 64
    assert items[0]["severity"] == "S" * 16
    assert items[0]["category"] == "C" * 32
    assert items[0]["message"] == "M" * 500


def test_read_events_from_event_journal_is_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    journal = EventJournal(path)
    journal.emit(severity="info", category="system", message="started")
    journal.emit(severity="warning", category="discovery", message="unmonitored")
    items = read_events(path, limit=10)
    assert [item["message"] for item in items] == ["unmonitored", "started"]
    assert set(items[0]) == {"timestamp", "severity", "category", "message"}
    assert items[0]["severity"] == "warning"


def test_read_trades_returns_last_n_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    _write_trades(
        path,
        [
            {
                "timestamp": "t1",
                "wallet": "shitcoims",
                "mint": "mint-a",
                "name": "AAA",
                "reason": "exit_stop",
                "input_amount": "100",
                "output_lamports": "111",
                "signature": "sig-a",
            },
            {
                "timestamp": "t2",
                "wallet": "shitcoims",
                "mint": "mint-b",
                "name": "BBB",
                "reason": "exit_rug",
                "input_amount": "200",
                "output_lamports": "222",
                "signature": "sig-b",
            },
            {
                "timestamp": "t3",
                "wallet": "shitcoims",
                "mint": "mint-c",
                "name": "CCC",
                "reason": "exit_tp",
                "input_amount": "300",
                "output_lamports": "333",
                "signature": "sig-c",
            },
        ],
    )
    items = read_trades(path, limit=2)
    assert [item["timestamp"] for item in items] == ["t3", "t2"]
    assert items[0]["mint"] == "mint-c"
    assert items[0]["name"] == "CCC"
    assert items[0]["reason"] == "exit_tp"
    assert items[0]["input_amount"] == "300"
    assert items[0]["output_lamports"] == "333"
    assert items[0]["signature"] == "sig-c"
    assert "wallet" not in items[0]


def test_read_trades_missing_file_empty_csv_and_nonpositive_limit(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    assert read_trades(path) == []
    _write_trades(path, [])
    assert read_trades(path) == []
    _write_trades(
        path,
        [
            {
                "timestamp": "t1",
                "mint": "mint",
                "name": "X",
                "reason": "exit_stop",
                "input_amount": "1",
                "output_lamports": "2",
                "signature": "sig",
            }
        ],
    )
    assert read_trades(path, limit=0) == []
    assert read_trades(path, limit=-1) == []


def test_read_trades_truncates_fields_and_caps_limit(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    rows = [
        {
            "timestamp": "T" * 80,
            "mint": "M" * 80,
            "name": "N" * 60,
            "reason": "R" * 40,
            "input_amount": "I" * 40,
            "output_lamports": "O" * 40,
            "signature": "S" * 100,
        }
        for _ in range(520)
    ]
    _write_trades(path, rows)
    items = read_trades(path, limit=900)
    assert len(items) == 500
    assert items[0]["timestamp"] == "T" * 64
    assert items[0]["mint"] == "M" * 64
    assert items[0]["name"] == "N" * 48
    assert items[0]["reason"] == "R" * 32
    assert items[0]["input_amount"] == "I" * 32
    assert items[0]["output_lamports"] == "O" * 32
    assert items[0]["signature"] == "S" * 88


def test_performance_summary_realized_sol_from_output_lamports() -> None:
    trades = [
        {"timestamp": "2026-08-12T16:00:00+00:00", "output_lamports": "1500000000"},
        {"timestamp": "2026-08-12T15:00:00+00:00", "output_lamports": "500000000"},
        {"timestamp": "2026-08-12T14:00:00+00:00", "output_lamports": "not-a-number"},
    ]
    events = [
        {"severity": "info"},
        {"severity": "warning"},
        {"severity": "info"},
        {"severity": "critical"},
    ]
    snapshot = {
        "wallet": {"sol": "3.25", "portfolio_exit_sol": "8.50"},
        "positions": [{"mint": "a"}, {"mint": "b"}],
        "unmonitored": [{"mint": "c"}],
        "system": {"mode": "dry-run", "protection_state": "OBSERVE_ONLY"},
    }
    summary = performance_summary(snapshot=snapshot, trades=trades, events=events)
    assert summary["realized_sol"] == str(Decimal("2.0"))
    assert summary["trade_count"] == 3
    assert summary["last_exit_at"] == "2026-08-12T16:00:00+00:00"
    assert summary["native_sol"] == "3.25"
    assert summary["portfolio_exit_sol"] == "8.50"
    assert summary["protected_positions"] == 2
    assert summary["observe_only"] == 1
    assert summary["event_counts"] == {"info": 2, "warning": 1, "critical": 1}
    assert summary["mode"] == "dry-run"
    assert summary["protection_state"] == "OBSERVE_ONLY"


def test_performance_summary_empty_inputs_and_missing_wallet() -> None:
    summary = performance_summary(
        snapshot={"system": {}, "wallet": "not-a-mapping"},
        trades=[],
        events=[],
    )
    assert summary["realized_sol"] == "0"
    assert summary["trade_count"] == 0
    assert summary["last_exit_at"] is None
    assert summary["native_sol"] is None
    assert summary["portfolio_exit_sol"] is None
    assert summary["protected_positions"] == 0
    assert summary["observe_only"] == 0
    assert summary["event_counts"] == {}
    assert summary["mode"] is None
    assert summary["protection_state"] is None


def test_bars_from_windows_reconstructs_earlier_prices() -> None:
    now = 1_700_000_000
    price = 110.0
    bars = _bars_from_windows(
        price,
        {"m5": 10, "h1": 0, "h6": -10, "h24": 10},
        now,
    )
    expected_times = [now - seconds for _key, seconds in reversed(WINDOWS)] + [now]
    assert [bar["t"] for bar in bars] == expected_times
    by_time = {bar["t"]: bar for bar in bars}
    assert by_time[now]["c"] == pytest.approx(110.0)
    assert by_time[now - 5 * 60]["c"] == pytest.approx(100.0)
    assert by_time[now - 3600]["c"] == pytest.approx(110.0)
    assert by_time[now - 6 * 3600]["c"] == pytest.approx(110.0 / 0.9)
    assert by_time[now - 86400]["c"] == pytest.approx(100.0)
    for bar in bars:
        assert bar["o"] == bar["h"] == bar["l"] == bar["c"]
        assert bar["v"] == 0


def test_bars_from_windows_skips_missing_nan_and_total_loss() -> None:
    now = 50
    bars = _bars_from_windows(
        80.0,
        {"m5": None, "h1": "nope", "h6": float("nan"), "h24": -100, "other": 12},
        now,
    )
    assert bars == [{"t": now, "o": 80.0, "h": 80.0, "l": 80.0, "c": 80.0, "v": 0}]


def _dex_body(*, pairs: list[Any]) -> dict[str, Any]:
    return {"pairs": pairs}


def _solana_pair(**overrides: Any) -> dict[str, Any]:
    pair: dict[str, Any] = {
        "chainId": "solana",
        "pairAddress": "pair-abc",
        "dexId": "raydium",
        "priceUsd": "1.10",
        "priceChange": {"m5": 10, "h1": 0, "h6": -10, "h24": 10},
        "volume": {"h24": 1000},
        "liquidity": {"usd": 50000},
        "fdv": 123456,
    }
    pair.update(overrides)
    return pair


@pytest.mark.asyncio
async def test_fetch_candles_uses_mocked_dexscreener_windows() -> None:
    mint = str(Keypair().pubkey())
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        assert request.url.host == "api.dexscreener.com"
        assert str(request.url).startswith(f"{DEXSCREENER}/{mint}")
        return httpx.Response(
            200,
            json=_dex_body(
                pairs=[
                    {"chainId": "ethereum", "priceUsd": "9.99", "pairAddress": "eth-pair"},
                    _solana_pair(),
                ]
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        first = await fetch_candles(http, mint, interval="15m", limit=120)
        second = await fetch_candles(http, mint, interval="15m", limit=120)

    assert requested == [f"{DEXSCREENER}/{mint}"]
    assert first == second
    assert first["mint"] == mint
    assert first["interval"] == "15m"
    assert first["source"] == "dexscreener-windows"
    assert first["pair"] == "pair-abc"
    assert first["dex"] == "raydium"
    assert first["stats"]["price_usd"] == pytest.approx(1.10)
    assert first["stats"]["change_m5"] == pytest.approx(10)
    assert first["stats"]["volume_h24"] == pytest.approx(1000)
    assert first["stats"]["liquidity_usd"] == pytest.approx(50000)
    assert first["stats"]["fdv"] == pytest.approx(123456)
    assert first["bars"][-1]["c"] == pytest.approx(1.10)
    assert first["bars"][0]["c"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_fetch_candles_rejects_bad_mint_interval_and_empty_pairs() -> None:
    mint = str(Keypair().pubkey())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("network must not be called"))
    ) as http:
        with pytest.raises(CandleError, match="mint is not a Solana public key"):
            await fetch_candles(http, "not-a-mint")
        with pytest.raises(CandleError, match="unsupported interval"):
            await fetch_candles(http, mint, interval="2m")

    async def empty_pairs(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pairs": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(empty_pairs)) as http:
        with pytest.raises(CandleError, match="no DexScreener pair"):
            await fetch_candles(http, mint)

    async def no_price(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_dex_body(pairs=[_solana_pair(priceUsd=None)]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(no_price)) as http:
        with pytest.raises(CandleError, match="no USD price"):
            await fetch_candles(http, mint)

    async def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        with pytest.raises(CandleError, match="candle source unavailable"):
            await fetch_candles(http, mint)


def test_protect_unmonitored_round_trips_to_mapping() -> None:
    mint = str(Keypair().pubkey())
    merged, created, skipped = policies_for_unmonitored(
        unmonitored=[{"mint": mint, "name": "L00T", "exit_sol": "0.542"}],
        current=[],
    )
    item = policy_to_api_mapping(merged[0])
    assert item["mint"] == mint
    assert item["name"] == "L00T"
    # the row carries an exit quote; it must NOT become a cost basis
    assert "cost_basis_sol" not in item
    assert "buy_price_sol" not in item
    assert created == [mint]
    assert skipped == []

    merged_rug, created_rug, skipped_rug = policies_for_unmonitored(
        unmonitored=[{"mint": mint, "name": "L00T", "exit_sol": "0.542"}],
        current=[],
        mode="rug_only",
    )
    rug_item = policy_to_api_mapping(merged_rug[0])
    assert created_rug == [mint]
    assert skipped_rug == []
    assert "cost_basis_sol" not in rug_item
    assert "buy_price_sol" not in rug_item
    assert rug_item["rug_exit"] is True


class _FakeJournal:
    def recent(self) -> list[dict[str, Any]]:
        return []


class FakeEngine:
    def __init__(self, tmp_path: Path, unmonitored: list[dict[str, Any]]) -> None:
        self.config = type(
            "Config",
            (),
            {
                "positions": (),
                "config_path": tmp_path / "config.yaml",
                "poll_interval_seconds": 10,
                "events_file": tmp_path / "events.jsonl",
                "trades_file": tmp_path / "trades.csv",
                "server": type(
                    "Server", (), {"allowed_origins": ("http://127.0.0.1:3000",)}
                )(),
            },
        )()
        self._unmonitored = list(unmonitored)
        self.apply_calls: list[list[Any]] = []
        self.journal = _FakeJournal()

    async def run(self) -> None:
        import asyncio

        await asyncio.Event().wait()

    async def close(self) -> None:
        return None

    async def snapshot(self) -> dict[str, Any]:
        return {
            "unmonitored": list(self._unmonitored),
            "system": {
                "running": True,
                "rpc_ready": True,
                "protection_state": "DEGRADED",
                "last_cycle_at": "2026-08-12T00:00:00+00:00",
                "unprotected_count": len(self._unmonitored),
            },
        }

    def list_policies(self) -> list[dict[str, Any]]:
        return [policy_to_api_mapping(policy) for policy in self.config.positions]

    async def apply_positions(self, policies: list[Any], **_kwargs: Any) -> list[dict[str, Any]]:
        self.apply_calls.append(list(policies))
        self.config.positions = tuple(policies)
        return self.list_policies()


@pytest.mark.asyncio
async def test_protect_unmonitored_http_creates_then_noops(tmp_path: Path) -> None:
    mint = str(Keypair().pubkey())
    engine = FakeEngine(
        tmp_path,
        [{"mint": mint, "name": "SPARKY", "exit_sol": "0.172"}],
    )
    app = create_app(engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        created = await client.post(
            "/api/policies/protect-unmonitored",
            json={},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["can_execute"] is False
        assert body["created"] == [mint]
        assert body["skipped"] == []
        # protecting from the dashboard must not stamp the exit quote as basis
        assert "cost_basis_sol" not in body["items"][0]
        assert len(engine.apply_calls) == 1

        again = await client.post("/api/policies/protect-unmonitored", json={})
        assert again.status_code == 200
        assert again.json()["created"] == []
        assert again.json()["can_execute"] is False
        assert len(engine.apply_calls) == 1

        health = await client.get("/api/health")
        assert "unprotected_count" in health.json()
        assert health.json()["unprotected_count"] == 1


@pytest.mark.asyncio
async def test_protect_unmonitored_http_rug_only_and_rejects_remote(
    tmp_path: Path,
) -> None:
    mint = str(Keypair().pubkey())
    engine = FakeEngine(
        tmp_path,
        [{"mint": mint, "name": "AKitty", "exit_sol": "0.127"}],
    )
    app = create_app(engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        response = await client.post(
            "/api/policies/protect-unmonitored",
            json={"mode": "rug_only"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["can_execute"] is False
        assert body["created"] == [mint]
        assert "cost_basis_sol" not in body["items"][0]
        assert "buy_price_sol" not in body["items"][0]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("8.8.8.8", 123)),
        base_url="http://8.8.8.8",
    ) as remote:
        denied = await remote.post(
            "/api/policies/protect-unmonitored",
            json={"mode": "rug_only"},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "loopback only"
        assert len(engine.apply_calls) == 1


class RacingEngine(FakeEngine):
    """FakeEngine that mirrors the real engine's lock discipline.

    `SentinelEngine.apply_positions` swaps `config.positions` under
    `_policy_lock`, and it awaits before doing so. That await is the window in
    which the engine's auto-protect pass can land its own write. This stub
    reproduces the window so a handler that reads `config.positions` outside the
    lock demonstrably loses the concurrent write.
    """

    def __init__(self, tmp_path: Path, unmonitored: list[dict[str, Any]]) -> None:
        super().__init__(tmp_path, unmonitored)
        self._policy_lock = asyncio.Lock()
        self.entered_apply = asyncio.Event()
        self.writes: list[str] = []

    async def apply_positions(self, policies: list[Any], **_kwargs: Any) -> list[dict[str, Any]]:
        self.apply_calls.append(list(policies))
        # By the time persistence is entered the handler has already read
        # config.positions, so this is precisely the lost-update window.
        self.entered_apply.set()
        for _ in range(10):
            await asyncio.sleep(0)
        async with self._policy_lock:
            self.config.positions = tuple(policies)
            self.writes.append("handler")
        return self.list_policies()

    def skip_auto_protect(self, mint: str) -> None:
        return None


async def _auto_protect_writer(engine: RacingEngine, policy: Any) -> None:
    """Stand-in for the engine cycle's auto-protect pass.

    Contends for the same lock the handler must be holding, and only starts
    contending once the handler has read config.positions.
    """
    await engine.entered_apply.wait()
    async with engine._policy_lock:
        engine.config.positions = (*engine.config.positions, policy)
        engine.writes.append("auto")


def _policy(mint: str, name: str) -> Any:
    return policy_from_payload(mint, {"name": name, "cost_basis_sol": 1.0})


@pytest.mark.asyncio
async def test_upsert_policy_does_not_drop_a_concurrent_auto_protect_rule(
    tmp_path: Path,
) -> None:
    operator_mint = str(Keypair().pubkey())
    auto_mint = str(Keypair().pubkey())
    engine = RacingEngine(tmp_path, [])
    app = create_app(engine)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        racer = asyncio.create_task(_auto_protect_writer(engine, _policy(auto_mint, "AUTOBAG")))
        response = await client.put(
            f"/api/policies/{operator_mint}",
            json={"name": "OPERATOR", "cost_basis_sol": 2.0},
        )
        await asyncio.wait_for(racer, timeout=5)

    assert response.status_code == 200
    assert len(engine.apply_calls) == 1
    mints = {policy.mint for policy in engine.config.positions}
    assert auto_mint in mints, "auto-protect rule was dropped: that bag lost its stop"
    assert operator_mint in mints
    # The handler's write must complete before the concurrent writer is let in;
    # the reverse order is the lost update.
    assert engine.writes == ["handler", "auto"]


@pytest.mark.asyncio
async def test_delete_policy_does_not_drop_a_concurrent_auto_protect_rule(
    tmp_path: Path,
) -> None:
    doomed_mint = str(Keypair().pubkey())
    kept_mint = str(Keypair().pubkey())
    auto_mint = str(Keypair().pubkey())
    engine = RacingEngine(tmp_path, [])
    engine.config.positions = (_policy(doomed_mint, "DOOMED"), _policy(kept_mint, "KEPT"))
    app = create_app(engine)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        racer = asyncio.create_task(_auto_protect_writer(engine, _policy(auto_mint, "AUTOBAG")))
        response = await client.delete(f"/api/policies/{doomed_mint}")
        await asyncio.wait_for(racer, timeout=5)

    assert response.status_code == 200
    assert engine.writes == ["handler", "auto"]
    mints = {policy.mint for policy in engine.config.positions}
    assert mints == {kept_mint, auto_mint}


@pytest.mark.asyncio
async def test_protect_unmonitored_does_not_drop_a_concurrent_auto_protect_rule(
    tmp_path: Path,
) -> None:
    unmonitored_mint = str(Keypair().pubkey())
    auto_mint = str(Keypair().pubkey())
    engine = RacingEngine(
        tmp_path,
        [{"mint": unmonitored_mint, "name": "SPARKY", "exit_sol": "0.172"}],
    )
    app = create_app(engine)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        racer = asyncio.create_task(_auto_protect_writer(engine, _policy(auto_mint, "AUTOBAG")))
        response = await client.post(
            "/api/policies/protect-unmonitored",
            json={},
        )
        await asyncio.wait_for(racer, timeout=5)

    assert response.status_code == 200
    assert response.json()["created"] == [unmonitored_mint]
    assert engine.writes == ["handler", "auto"]
    mints = {policy.mint for policy in engine.config.positions}
    assert mints == {unmonitored_mint, auto_mint}


@pytest.mark.asyncio
async def test_mutating_routes_reject_non_loopback_clients(tmp_path: Path) -> None:
    mint = str(Keypair().pubkey())
    engine = FakeEngine(tmp_path, [{"mint": mint, "name": "SPARKY", "exit_sol": "0.172"}])
    engine.config.positions = (_policy(mint, "SPARKY"),)
    app = create_app(engine)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("8.8.8.8", 123)),
        base_url="http://8.8.8.8",
    ) as remote:
        responses = [
            await remote.put(f"/api/policies/{mint}", json={"name": "X", "cost_basis_sol": 1.0}),
            await remote.delete(f"/api/policies/{mint}"),
            await remote.post("/api/policies/protect-unmonitored", json={}),
            await remote.post(f"/api/policies/{mint}/skip-auto"),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert {response.json()["detail"] for response in responses} == {"loopback only"}
    assert engine.apply_calls == []
    assert {policy.mint for policy in engine.config.positions} == {mint}

    # The read-only routes stay reachable, so the 403s above are the loopback
    # check and not a blanket failure.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("8.8.8.8", 123)),
        base_url="http://8.8.8.8",
    ) as remote:
        listed = await remote.get("/api/policies")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["mint"] == mint


@pytest.mark.asyncio
async def test_task_reentrant_lock_reenters_owner_and_excludes_other_tasks() -> None:
    lock = _TaskReentrantLock(asyncio.Lock())
    order: list[str] = []

    async def contender() -> None:
        async with lock:
            order.append("other")

    async with lock:
        task = asyncio.create_task(contender())
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "a second task must not enter while the lock is held"
        async with lock:
            order.append("reentered")
        assert lock.locked()
    await asyncio.wait_for(task, timeout=1)

    assert order == ["reentered", "other"]
    assert not lock.locked()


@pytest.mark.asyncio
async def test_reentrant_policy_lock_install_is_idempotent(tmp_path: Path) -> None:
    engine = RacingEngine(tmp_path, [])
    create_app(engine)
    first = engine._policy_lock
    assert isinstance(first, _TaskReentrantLock)
    create_app(engine)
    assert engine._policy_lock is first
