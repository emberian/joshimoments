"""Outbox sendPhoto: multipart delivery, retry-vs-drop semantics, ordering.

Separate from test_dregg_gate.py deliberately — that file is under concurrent edit by
the lookup lane; these tests own only the outbox's new method. Same discipline: no
live Telegram anywhere, transports are httpx.MockTransport.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from dregg_gate.state import OUTBOX_METHODS, GateState
from dregg_gate.telegram import Telegram

PNG = b"\x89PNG\r\n\x1a\nFAKEBYTES"


def make_state(tmp_path: Path) -> GateState:
    return GateState(tmp_path / "gate.sqlite")


def enqueue_photo(state: GateState, tmp_path: Path, *, dedup: str = "p1") -> Path:
    photo = tmp_path / "chart.png"
    photo.write_bytes(PNG)
    state.enqueue(
        dedup,
        "sendPhoto",
        {
            "chat_id": -100_123,
            "photo_path": str(photo),
            "caption": "caption with <b>html</b>",
            "parse_mode": "HTML",
        },
    )
    return photo


def test_sendphoto_is_a_durable_method() -> None:
    assert "sendPhoto" in OUTBOX_METHODS


async def test_sendphoto_round_trip_is_multipart_with_caption(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    enqueue_photo(state, tmp_path)
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await Telegram("TESTTOKEN", http, state).flush_outbox()

    assert state.pending(now=9e12) == []
    (request,) = seen
    assert request.url.path.endswith("/sendPhoto")
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.read()
    assert PNG in body                                # the actual bytes, uploaded
    assert b"caption with <b>html</b>" in body        # caption rides as a form field
    assert b'name="parse_mode"' in body and b"HTML" in body
    assert b'name="chat_id"' in body
    assert b"photo_path" not in body                  # the local path never leaves the box
    state.close()


async def test_sendphoto_transport_failure_retries_in_order(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    enqueue_photo(state, tmp_path)
    state.enqueue("m2", "sendMessage", {"chat_id": -100_123, "text": "after"})
    responses = [httpx.Response(500, json={"ok": False})]

    async def handler(_request: httpx.Request) -> httpx.Response:
        if responses:
            return responses.pop(0)
        return httpx.Response(200, json={"ok": True, "result": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        telegram = Telegram("TESTTOKEN", http, state)
        await telegram.flush_outbox()
        # The 500 defers the photo and DAMS the queue: strict order preserved.
        deferred = state.pending(now=9e12)
        assert [item.method for item in deferred] == ["sendPhoto", "sendMessage"]
        assert deferred[0].attempts == 1
        state.connection.execute("UPDATE outbox SET next_attempt_at = 0")
        await telegram.flush_outbox()
        assert state.pending(now=9e12) == []
        assert telegram.drain_dropped() == []
    state.close()


async def test_missing_photo_file_drops_instead_of_damming(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    state.enqueue(
        "gone",
        "sendPhoto",
        {"chat_id": -1, "photo_path": str(tmp_path / "never-written.png"), "caption": "x"},
    )
    state.enqueue("m2", "sendMessage", {"chat_id": -1, "text": "still delivers"})
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json={"ok": True, "result": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        telegram = Telegram("TESTTOKEN", http, state)
        await telegram.flush_outbox()
        assert calls == ["sendMessage"]  # the photo never reached the wire
        assert state.pending(now=9e12) == []
        drops = telegram.drain_dropped()
        assert drops == [("sendPhoto", "photo_unreadable:FileNotFoundError")]
    state.close()


async def test_definitive_rejection_still_drops_photos(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    enqueue_photo(state, tmp_path)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "PHOTO_INVALID_DIMENSIONS"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        telegram = Telegram("TESTTOKEN", http, state)
        await telegram.flush_outbox()
        assert state.pending(now=9e12) == []
        assert telegram.drain_dropped() == [("sendPhoto", "PHOTO_INVALID_DIMENSIONS")]
    state.close()
