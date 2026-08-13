from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from shitcoims_scout.config import ScoutConfig
from shitcoims_scout.gateway import ScoutGateway
from shitcoims_scout.local_api import LocalAPI
from shitcoims_scout.state import ScoutState
from shitcoims_scout.telegram import Telegram


def config(tmp_path: Path) -> ScoutConfig:
    return ScoutConfig(
        config_path=tmp_path / "intelligence.yaml",
        enabled=True,
        telegram_bot_token_file=tmp_path / "token",
        telegram_chat_id="123",
        telegram_user_id="123",
        state_file=tmp_path / "scout.sqlite3",
        api_base="http://127.0.0.1:8788",
        sentinel_api_base="http://127.0.0.1:8787",
        poll_timeout_seconds=25,
        message_max_age_seconds=120,
    )


def message_update(
    update_id: int,
    text: str,
    *,
    chat_id: int = 123,
    user_id: int = 123,
    date: int = 1_000,
    is_bot: bool = False,
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "date": date,
            "text": text,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "is_bot": is_bot},
        },
    }


@pytest.mark.asyncio
async def test_authenticated_command_uses_only_fixed_local_get_and_durable_outbox(
    tmp_path: Path,
) -> None:
    local_requests: list[httpx.Request] = []

    async def local_handler(request: httpx.Request) -> httpx.Response:
        local_requests.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "signal-1",
                        "kind": "status",
                        "summary": "No urgent signals.",
                        "severity": "info",
                    }
                ],
                "next_cursor": "page2",
                "has_more": True,
            },
        )

    state = ScoutState(tmp_path / "scout.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(local_handler)) as local_http:
        gateway = ScoutGateway(
            config(tmp_path),
            state,
            telegram=None,  # type: ignore[arg-type]
            local_api=LocalAPI("http://127.0.0.1:8788", "http://127.0.0.1:8787", local_http),
            clock=lambda: 1_010,
        )
        await gateway.process_update(message_update(7, "/now"))

    assert state.last_update_id == 7
    assert len(local_requests) == 1
    assert local_requests[0].method == "GET"
    assert str(local_requests[0].url) == "http://127.0.0.1:8788/api/intelligence/feed?limit=10"
    outbox = state.pending()
    assert len(outbox) == 1
    assert "No urgent signals" in outbox[0].payload["text"]
    buttons = outbox[0].payload["reply_markup"]["inline_keyboard"]
    assert buttons[0][0]["text"] == "Evidence"
    assert buttons[0][0]["callback_data"].startswith("scout:")
    assert buttons[1][0]["text"] == "Next >"
    state.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update",
    [
        message_update(1, "/now", chat_id=999),
        message_update(2, "/now", user_id=999),
        message_update(3, "/now", is_bot=True),
        message_update(4, "/now", date=800),
    ],
)
async def test_unauthorized_bot_and_stale_messages_never_query_or_reply(tmp_path: Path, update: dict) -> None:
    called = False

    async def local_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    state = ScoutState(tmp_path / f"{update['update_id']}.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(local_handler)) as local_http:
        gateway = ScoutGateway(
            config(tmp_path),
            state,
            telegram=None,  # type: ignore[arg-type]
            local_api=LocalAPI("http://127.0.0.1:8788", "http://127.0.0.1:8787", local_http),
            clock=lambda: 1_000,
        )
        await gateway.process_update(update)
    assert called is False
    assert state.pending() == []
    assert state.last_update_id == update["update_id"]
    state.close()


@pytest.mark.asyncio
async def test_denied_trade_command_never_queries_local_api(tmp_path: Path) -> None:
    local_calls = 0

    async def local_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal local_calls
        local_calls += 1
        return httpx.Response(200, json={})

    state = ScoutState(tmp_path / "scout.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(local_handler)) as local_http:
        gateway = ScoutGateway(
            config(tmp_path),
            state,
            telegram=None,  # type: ignore[arg-type]
            local_api=LocalAPI("http://127.0.0.1:8788", "http://127.0.0.1:8787", local_http),
            clock=lambda: 1_000,
        )
        await gateway.process_update(message_update(1, "/sell"))
    assert local_calls == 0
    assert "read-only" in state.pending()[0].payload["text"]
    state.close()


@pytest.mark.asyncio
async def test_callback_is_answered_before_local_request_and_is_single_use(tmp_path: Path) -> None:
    order: list[str] = []

    async def telegram_handler(request: httpx.Request) -> httpx.Response:
        order.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True})

    async def local_handler(_request: httpx.Request) -> httpx.Response:
        order.append("local-get")
        return httpx.Response(200, json={"summary": "fresh"})

    state = ScoutState(tmp_path / "scout.sqlite3")
    handle = state.create_callback("refresh", {"command": "/now"})
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler)) as telegram_http,
        httpx.AsyncClient(transport=httpx.MockTransport(local_handler)) as local_http,
    ):
        telegram = Telegram("secret-token", telegram_http, state)
        gateway = ScoutGateway(
            config(tmp_path),
            state,
            telegram,
            LocalAPI("http://127.0.0.1:8788", "http://127.0.0.1:8787", local_http),
            clock=lambda: 1_000,
        )
        callback = {
            "id": "callback-1",
            "data": f"scout:{handle}",
            "from": {"id": 123, "is_bot": False},
            "message": {"chat": {"id": 123, "type": "private"}},
        }
        await gateway.process_update({"update_id": 1, "callback_query": callback})
        callback["id"] = "callback-2"
        await gateway.process_update({"update_id": 2, "callback_query": callback})

    assert order[:2] == ["answerCallbackQuery", "local-get"]
    assert order.count("local-get") == 1
    assert "already used" in state.pending()[1].payload["text"]
    state.close()


@pytest.mark.asyncio
async def test_telegram_outbox_failure_does_not_leak_token(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    token = "extremely-secret-bot-token"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False})

    state = ScoutState(tmp_path / "scout.sqlite3")
    state.enqueue("update:1", "sendMessage", {"chat_id": "123", "text": "hello"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await Telegram(token, http, state).flush_outbox()
    assert token not in caplog.text
    assert state.connection.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    state.close()


@pytest.mark.asyncio
async def test_unknown_local_fields_are_not_dumped_into_telegram(tmp_path: Path) -> None:
    async def local_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"raw_secretish_vendor_blob": "must-not-escape"})

    state = ScoutState(tmp_path / "scout.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(local_handler)) as local_http:
        gateway = ScoutGateway(
            config(tmp_path),
            state,
            telegram=None,  # type: ignore[arg-type]
            local_api=LocalAPI("http://127.0.0.1:8788", "http://127.0.0.1:8787", local_http),
            clock=lambda: 1_000,
        )
        await gateway.process_update(message_update(1, "/now"))
    text = state.pending()[0].payload["text"]
    assert "must-not-escape" not in text
    assert "not recognized safely" in text
    state.close()
