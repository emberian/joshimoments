import json
import os
from pathlib import Path

import httpx
import pytest

from shitcoims_sentinel.config import NotificationConfig
from shitcoims_sentinel.notifier import Notifier, telegram_confirm_pairing
from shitcoims_sentinel.storage import EventJournal


@pytest.mark.asyncio
async def test_telegram_failure_never_logs_or_journals_token(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    token = "secret-bot-token"
    secret = tmp_path / "telegram"
    secret.write_text(token, encoding="utf-8")
    os.chmod(secret, 0o600)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False})

    events = tmp_path / "events.jsonl"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        notifier = Notifier(NotificationConfig(secret, "12345", 6), http, EventJournal(events))
        assert await notifier.probe() is False

    assert token not in caplog.text
    assert token not in (events.read_text(encoding="utf-8") if events.exists() else "")


@pytest.mark.asyncio
async def test_telegram_pairing_confirmation_is_explicit() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await telegram_confirm_pairing("secret-bot-token", "12345", http)

    assert len(requests) == 1
    assert requests[0].url.path.endswith("/sendMessage")
    assert json.loads(requests[0].content) == {
        "chat_id": "12345",
        "text": "✅ shitcoims Sentinel paired with this private chat. No trade was executed.",
    }
