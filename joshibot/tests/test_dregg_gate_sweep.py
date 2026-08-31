"""Offline tests for the re-verify sweep and the service loop.

The hard invariant under test: a provider error NEVER ejects anyone — the day's
sweep is skipped whole and the operator is alerted instead.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from dregg_gate.config import Config
from dregg_gate.gateway import GateGateway
from dregg_gate.helius import HeliusError
from dregg_gate.service import GateService
from dregg_gate.state import GateState
from dregg_gate.sweep import SWEEP_DAY_KEY, SWEEP_RESULT_KEY, Sweeper
from dregg_gate.telegram import PollerConflict, Telegram

OPERATOR = 6913902526
RAW_N = 888_888 * 10**6


def at(day: int, hour: int, minute: int = 0) -> float:
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc).timestamp()


def make_config(tmp_path: Path, **overrides) -> Config:
    cfg = Config(
        telegram_token_file=tmp_path / "token",
        helius_key_file=tmp_path / "helius",
        db_path=tmp_path / "gate.sqlite",
        heartbeat_path=tmp_path / "heartbeat.json",
    )
    return replace(cfg, **overrides) if overrides else cfg


class Clock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeHelius:
    def __init__(self, decimals: int = 6, balances: dict[str, int] | None = None):
        self.decimals = decimals
        self.balances = balances or {}
        self.fail_wallets: set[str] = set()
        self.balance_calls = 0

    async def mint_decimals(self, mint: str) -> int:
        return self.decimals

    async def balance_raw(self, owner: str, mint: str) -> int:
        self.balance_calls += 1
        if owner in self.fail_wallets:
            raise HeliusError("helius down")
        return self.balances[owner]


def build(tmp_path: Path, clock: Clock, helius: FakeHelius, **config_overrides):
    cfg = make_config(tmp_path, **config_overrides)
    state = GateState(cfg.db_path)
    state.bind_group(-100_500)
    state.record_mint_decimals(6)
    gateway = GateGateway(cfg, state, None, helius, clock=clock)  # type: ignore[arg-type]
    sweeper = Sweeper(cfg, state, gateway, helius, clock=clock)
    return cfg, state, sweeper


def sends(state: GateState) -> list[dict]:
    return [item.payload for item in state.pending(limit=1000) if item.method == "sendMessage"]


def eject_methods(state: GateState) -> list[str]:
    return [
        item.method
        for item in state.pending(limit=1000)
        if item.method in ("banChatMember", "unbanChatMember")
    ]


async def test_sweep_is_not_due_before_the_configured_hour(tmp_path: Path) -> None:
    clock = Clock(at(24, 13, 59))
    helius = FakeHelius(balances={"w1": RAW_N})
    _, state, sweeper = build(tmp_path, clock, helius, sweep_hour_utc=14)
    state.record_verification(1, "w1", RAW_N, clock.now)
    await sweeper.tick()
    assert sweeper.plan is None
    assert helius.balance_calls == 0
    state.close()


async def test_warn_then_grace_then_eject_across_three_days(tmp_path: Path) -> None:
    clock = Clock(at(24, 15))
    helius = FakeHelius(balances={"w1": RAW_N - 1})
    _, state, sweeper = build(tmp_path, clock, helius)
    state.record_verification(7, "w1", RAW_N, clock.now)

    # day 1: below threshold -> warning + 48h grace, no eject
    await sweeper.tick()
    member = state.member(7)
    assert member.status == "grace"
    assert member.grace_until == at(24, 15) + 48 * 3600
    assert any("48h to" in p["text"] or "48h" in p["text"] for p in sends(state) if p["chat_id"] == 7)
    assert eject_methods(state) == []
    assert state.day_marker(SWEEP_DAY_KEY) == "2026-08-24"

    # day 2: still below, still inside grace -> nothing changes
    clock.now = at(25, 15)
    await sweeper.tick()
    member = state.member(7)
    assert member.status == "grace"
    assert member.grace_until == at(24, 15) + 48 * 3600
    assert eject_methods(state) == []

    # day 3, grace expired -> ban then immediate unban, status ejected, rejoin DM
    clock.now = at(26, 15, 30)
    await sweeper.tick()
    assert state.member(7).status == "ejected"
    assert eject_methods(state) == ["banChatMember", "unbanChatMember"]
    ejects = [
        item.payload
        for item in state.pending(limit=1000)
        if item.method in ("banChatMember", "unbanChatMember")
    ]
    assert all(p["chat_id"] == -100_500 and p["user_id"] == 7 for p in ejects)
    assert ejects[1]["only_if_banned"] is True
    assert any("/verify to rejoin" in p["text"] for p in sends(state) if p["chat_id"] == 7)
    state.close()


async def test_provider_error_never_ejects_even_with_expired_grace(tmp_path: Path) -> None:
    clock = Clock(at(24, 15))
    helius = FakeHelius(balances={"w-ok": RAW_N - 1, "w-grace": 0})
    helius.fail_wallets.add("w-down")
    _, state, sweeper = build(tmp_path, clock, helius)
    state.record_verification(1, "w-ok", RAW_N, clock.now)  # will be warned before the outage hits
    state.record_verification(2, "w-down", RAW_N, clock.now)
    state.record_verification(3, "w-grace", RAW_N, clock.now)
    state.set_member_status(3, "grace", clock.now - 10)  # grace ALREADY expired

    await sweeper.tick()

    # nobody was ejected, the day is marked skipped, the operator was alerted
    assert eject_methods(state) == []
    assert state.member(3).status == "grace"
    assert helius.balance_calls == 3  # member 1, then the failing wallet twice (one retry)
    assert state.day_marker(SWEEP_DAY_KEY) == "2026-08-24"
    assert "skipped" in (state.day_marker(SWEEP_RESULT_KEY) or "")
    alerts = [p["text"] for p in sends(state) if p["chat_id"] == OPERATOR]
    assert any("SKIPPED" in text and "nobody was warned or ejected" in text for text in alerts)
    assert sweeper.plan is None

    # the next day, with the provider healthy, the sweep runs normally again:
    # the expired grace ejects NOW, proving the skip deferred rather than forgot
    helius.fail_wallets.clear()
    helius.balances["w-down"] = RAW_N
    clock.now = at(25, 15)
    await sweeper.tick()
    assert state.member(2).status == "ok"
    assert state.member(3).status == "ejected"
    assert eject_methods(state) == ["banChatMember", "unbanChatMember"]
    state.close()


async def test_recovery_during_grace_restores_the_seat(tmp_path: Path) -> None:
    clock = Clock(at(24, 15))
    helius = FakeHelius(balances={"w1": RAW_N})
    _, state, sweeper = build(tmp_path, clock, helius)
    state.record_verification(7, "w1", RAW_N, clock.now)
    state.set_member_status(7, "grace", clock.now + 3600)
    await sweeper.tick()
    member = state.member(7)
    assert member.status == "ok" and member.grace_until is None
    assert any("seat is safe" in p["text"] for p in sends(state) if p["chat_id"] == 7)
    assert eject_methods(state) == []
    state.close()


async def test_sweep_spreads_batches_and_never_blocks_the_loop(tmp_path: Path) -> None:
    clock = Clock(at(24, 15))
    helius = FakeHelius(balances={"w1": RAW_N, "w2": RAW_N})
    _, state, sweeper = build(
        tmp_path, clock, helius, sweep_batch_size=1, sweep_spread_seconds=3600
    )
    state.record_verification(1, "w1", RAW_N, clock.now)
    state.record_verification(2, "w2", RAW_N, clock.now)

    await sweeper.tick()  # first batch runs immediately
    assert helius.balance_calls == 1
    assert sweeper.plan is not None and sweeper.plan.next_batch_at == at(24, 15) + 1800.0

    await sweeper.tick()  # same instant: the gap has not elapsed, nothing happens
    assert helius.balance_calls == 1

    clock.now = at(24, 15) + 1801
    await sweeper.tick()
    assert helius.balance_calls == 2
    assert sweeper.plan is None
    assert state.day_marker(SWEEP_DAY_KEY) == "2026-08-24"
    assert "checked=2" in (state.day_marker(SWEEP_RESULT_KEY) or "")
    state.close()


async def test_poller_conflict_raises_distinctly_and_service_alerts_operator(tmp_path: Path) -> None:
    config_path = tmp_path / "gate.toml"
    config_path.write_text(
        '[paths]\ntelegram_token = "token"\nhelius_key = "helius"\n'
        'db = "gate.sqlite"\nheartbeat = "heartbeat.json"\n'
        "[gate]\nsweep_hour_utc = 23\n"
    )
    cfg = Config.load(config_path)
    state = GateState(cfg.db_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getUpdates"):
            return httpx.Response(
                409, json={"ok": False, "error_code": 409, "description": "terminated by other"}
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    clock = Clock(at(24, 10))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        telegram = Telegram("TESTTOKEN", http, state)
        with pytest.raises(PollerConflict):
            await telegram.updates(None, 1)
        service = GateService(config_path, cfg, state, telegram, FakeHelius(), clock=clock)  # type: ignore[arg-type]
        with pytest.raises(PollerConflict):
            await service.cycle()
        # the run loop turns that into a durable operator alert (exercised directly)
        service.gateway.alert_operator("poller conflict: test", "conflict:2026-08-24")
        alerts = [p for p in sends(state) if p["chat_id"] == OPERATOR]
        assert any("poller conflict" in p["text"] for p in alerts)
    state.close()


async def test_service_cycle_heartbeats_and_keeps_last_good_config(tmp_path: Path) -> None:
    config_path = tmp_path / "gate.toml"
    config_path.write_text(
        '[paths]\ntelegram_token = "token"\nhelius_key = "helius"\n'
        'db = "gate.sqlite"\nheartbeat = "heartbeat.json"\n'
        "[gate]\nsweep_hour_utc = 23\n"
    )
    cfg = Config.load(config_path)
    state = GateState(cfg.db_path)
    sent: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": []})
        if request.url.path.endswith("/sendMessage"):
            sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": True})

    clock = Clock(at(24, 10))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        telegram = Telegram("TESTTOKEN", http, state)
        service = GateService(config_path, cfg, state, telegram, FakeHelius(), clock=clock)  # type: ignore[arg-type]
        await service.cycle()
        heartbeat = json.loads(cfg.heartbeat_path.read_text())
        assert heartbeat["cycle"] == 1
        assert heartbeat["config_status"] == "ok"
        assert heartbeat["group_bound"] is False
        assert any("gate heartbeat 2026-08-24" in p["text"] for p in sends(state))

        await service.cycle()  # same day: the operator DM is not repeated
        heartbeats = [p for p in sent if "gate heartbeat" in p.get("text", "")]
        assert len(heartbeats) == 1
        assert heartbeats[0]["chat_id"] == OPERATOR

        # a broken config edit keeps the last good config and says so
        config_path.write_text("this is not toml [")
        await service.cycle()
        assert service.cfg_status.startswith("kept_last_good")
        assert service.cfg.sweep_hour_utc == 23
    state.close()
