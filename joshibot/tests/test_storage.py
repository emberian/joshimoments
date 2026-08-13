from pathlib import Path

from shitcoims_sentinel.storage import EventJournal, StateStore


def test_state_store_persists_nested_updates(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = StateStore(path)
    state.set("positions", "mint", value={"trailing_active": True})
    reloaded = StateStore(path)
    assert reloaded.get("positions", "mint", "trailing_active") is True
    assert not list(tmp_path.glob(".state.json.*"))


def test_event_journal_deduplicates_but_keeps_critical_context(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "events.jsonl")
    first = journal.emit(severity="critical", category="execution", message="failed")
    second = journal.emit(severity="critical", category="execution", message="failed")
    assert first is not None
    assert second is None
    assert len(journal.recent()) == 1


def test_dispose_policy_survives_concurrent_store_instances_without_clobber(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    server = StateStore(path)
    command = StateStore(path)
    command.set_dispose_policy("mint", enabled=True)
    server.set("last_heartbeat_at", value="now")

    reloaded = StateStore(path)
    assert reloaded.get("dispose_policies", "mint", "enabled") is True
    assert reloaded.get("positions", "mint", "last_pnl_pct") is None
    assert reloaded.get("last_heartbeat_at") == "now"
