from __future__ import annotations

from pathlib import Path

import pytest

from shitcoims_scout.state import ScoutState, ScoutStateError


def test_cursor_and_outbox_survive_reopen_and_deduplicate(tmp_path: Path) -> None:
    path = tmp_path / "private/scout.sqlite3"
    state = ScoutState(path)
    state.advance_cursor(10)
    state.advance_cursor(9)
    state.enqueue("update:10", "sendMessage", {"text": "one"})
    state.enqueue("update:10", "sendMessage", {"text": "duplicate"})
    state.close()

    reopened = ScoutState(path)
    assert reopened.last_update_id == 10
    items = reopened.pending()
    assert len(items) == 1
    assert items[0].payload == {"text": "one"}
    reopened.delivered(items[0].id)
    assert reopened.pending() == []
    reopened.close()
    assert path.stat().st_mode & 0o777 == 0o600


def test_callback_handles_are_opaque_expiring_and_single_use(tmp_path: Path) -> None:
    state = ScoutState(tmp_path / "scout.sqlite3")
    handle = state.create_callback("refresh", {"command": "/now"}, now=100, ttl_seconds=30)
    assert "/now" not in handle
    callback = state.consume_callback(handle, now=110)
    assert callback is not None
    assert callback.action == "refresh"
    assert callback.parameters == {"command": "/now"}
    assert state.consume_callback(handle, now=111) is None

    expired = state.create_callback("evidence", {"signal_id": "abc"}, now=200, ttl_seconds=10)
    assert state.consume_callback(expired, now=211) is None
    state.close()


def test_failed_outbox_delivery_is_retained_for_retry(tmp_path: Path) -> None:
    state = ScoutState(tmp_path / "scout.sqlite3")
    state.enqueue("update:1", "sendMessage", {"text": "hello"})
    item = state.pending()[0]
    state.delivery_failed(item.id, "ReadTimeout", 1)
    assert state.pending(now=0) == []
    row = state.connection.execute(
        "SELECT attempts, last_error_type FROM outbox WHERE id = ?", (item.id,)
    ).fetchone()
    assert tuple(row) == (1, "ReadTimeout")
    state.close()


def test_only_one_process_can_own_consumer_state(tmp_path: Path) -> None:
    path = tmp_path / "scout.sqlite3"
    first = ScoutState(path)
    with pytest.raises(ScoutStateError, match="already owns"):
        ScoutState(path)
    first.close()
    second = ScoutState(path)
    second.close()


def test_state_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("not sqlite", encoding="utf-8")
    link = tmp_path / "scout.sqlite3"
    link.symlink_to(target)
    with pytest.raises(ScoutStateError, match="not a symlink"):
        ScoutState(link)
