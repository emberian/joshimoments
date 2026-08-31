"""The supervisor's own tests. No launchd, no network, no Telegram."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

# scripts/ is not a package, so load the module by path rather than inventing an __init__.py
# (the same approach tests/test_meteora_lp_report.py takes).
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "watchdog.py"
_SPEC = importlib.util.spec_from_file_location("watchdog_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
wd = importlib.util.module_from_spec(_SPEC)
# Register before exec: @dataclass resolves annotations through sys.modules[cls.__module__],
# so a module executed while unregistered raises on its first frozen dataclass.
sys.modules[_SPEC.name] = wd
_SPEC.loader.exec_module(wd)


T0 = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


class FakeLaunchCtl:
    """Records what would have been done to launchd, and does nothing."""

    def __init__(self, *, loaded: bool = True, restart_ok: bool = True) -> None:
        self.loaded = loaded
        self.restart_ok = restart_ok
        self.restarts: list[str] = []

    def is_loaded(self, label: str) -> bool:
        return self.loaded

    def restart(self, label: str, plist: Path | None) -> tuple[bool, str]:
        self.restarts.append(label)
        return (self.restart_ok, "kickstarted" if self.restart_ok else "kickstart failed")


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.configured = True

    def send(self, text: str) -> bool:
        self.messages.append(text)
        return True


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def make_supervisor(
    tmp_path: Path, specs, *, launchctl=None, telegram=None, now: datetime = T0, **kwargs
):
    return wd.Supervisor(
        collectors=specs,
        launchctl=launchctl if launchctl is not None else FakeLaunchCtl(),
        telegram=telegram if telegram is not None else FakeTelegram(),
        state_path=tmp_path / "state.json",
        journal_path=tmp_path / "journal.jsonl",
        clock=lambda: now,
        **kwargs,
    )


def heartbeat_spec(root: Path, *, cadence: float = 30.0, **kwargs) -> Any:
    return wd.CollectorSpec(
        name="probe-me",
        label="com.example.job",
        probe=wd.JsonlProbe(
            root=root, pattern="*.jsonl", kinds=frozenset({"heartbeat"}), time_fields=("t_ingest",)
        ),
        cadence_seconds=cadence,
        **kwargs,
    )


# ---------------------------------------------------------------------------------------
# reading the tapes backwards
# ---------------------------------------------------------------------------------------


def test_tail_lines_reads_backwards_and_stays_inside_its_budget(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    path.write_text("".join(f'{{"i":{i}}}\n' for i in range(50_000)), encoding="utf-8")
    first_three = [
        json.loads(line)["i"] for _, line in zip(range(3), wd.tail_lines(path), strict=False)
    ]
    assert first_three == [49_999, 49_998, 49_997]

    # A tiny budget must still return the newest rows, not the oldest, and must not read
    # the whole file: this is the property that keeps a once-a-minute pass cheap against a
    # 150 MB tape.
    limited = list(wd.tail_lines(path, budget_bytes=2048))
    assert len(limited) < 300
    assert json.loads(limited[0])["i"] == 49_999


def test_the_probe_ignores_event_rows_and_reads_only_the_liveness_row(tmp_path: Path) -> None:
    """A busy market must not be able to mask a dead heartbeat."""

    write_jsonl(
        tmp_path / "tape" / "2026-08-15.jsonl",
        [
            {"kind": "heartbeat", "t_ingest": "2026-08-15T11:00:00+00:00"},
            {"kind": "trade", "t_ingest": "2026-08-15T11:59:59+00:00"},
        ],
    )
    freshness = wd.JsonlProbe(
        root=tmp_path / "tape",
        pattern="*.jsonl",
        kinds=frozenset({"heartbeat"}),
        time_fields=("t_ingest",),
    )()
    assert freshness.age_seconds(T0) == pytest.approx(3600.0)


def test_epoch_seconds_and_iso_strings_are_both_understood() -> None:
    assert wd._parse_moment(1786579476) == datetime(2026, 8, 13, 0, 4, 36, tzinfo=UTC)
    # Millisecond stamps are rescaled rather than dated to the year 57000.
    assert wd._parse_moment(1786579476000) == datetime(2026, 8, 13, 0, 4, 36, tzinfo=UTC)
    # A naive stamp is UTC, not local: reading it as local would shift every age by the
    # host's offset and silently change every staleness verdict.
    assert wd._parse_moment("2026-08-15T12:00:00") == T0
    assert wd._parse_moment("2026-08-15T12:00:00Z") == T0
    assert wd._parse_moment(None) is None
    assert wd._parse_moment("not a date") is None
    assert wd._parse_moment(True) is None


def test_the_cursor_probe_takes_the_newest_pool_not_the_first(tmp_path: Path) -> None:
    path = tmp_path / "cursors.json"
    path.write_text(json.dumps({
        "poolA": {"last_poll_at": "2026-08-15T10:00:00+00:00"},
        "poolB": {"last_poll_at": "2026-08-15T11:59:00+00:00"},
    }), encoding="utf-8")
    assert wd.JsonMaxFieldProbe(path, "last_poll_at")().age_seconds(T0) == pytest.approx(60.0)


def test_the_sqlite_probe_opens_read_only(tmp_path: Path) -> None:
    db = tmp_path / "store.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE source_health_history (checked_at TEXT)")
        connection.execute("INSERT INTO source_health_history VALUES ('2026-08-15T11:30:00+00:00')")
    probe = wd.SqliteProbe(db, "SELECT MAX(checked_at) FROM source_health_history")
    assert probe().age_seconds(T0) == pytest.approx(1800.0)


def test_a_missing_artefact_is_absent_not_merely_stale(tmp_path: Path) -> None:
    assert wd.JsonlProbe(tmp_path / "nope", "*.jsonl", None, ("t",))().absent is True
    assert wd.JsonMaxFieldProbe(tmp_path / "nope.json", "t")().absent is True
    assert wd.SqliteProbe(tmp_path / "nope.sqlite3", "SELECT 1")().absent is True


# ---------------------------------------------------------------------------------------
# verdicts and restarts
# ---------------------------------------------------------------------------------------


def test_a_fresh_collector_is_left_alone(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T11:59:30+00:00"}])
    launchctl = FakeLaunchCtl()
    supervisor = make_supervisor(tmp_path, [heartbeat_spec(tmp_path / "tape")], launchctl=launchctl)
    verdicts = supervisor.run_once()
    assert [v.status for v in verdicts] == [wd.OK]
    assert launchctl.restarts == []


def test_a_stale_collector_is_restarted(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T10:00:00+00:00"}])
    launchctl = FakeLaunchCtl()
    supervisor = make_supervisor(tmp_path, [heartbeat_spec(tmp_path / "tape")], launchctl=launchctl)
    verdicts = supervisor.run_once()
    assert verdicts[0].status == wd.RESTARTED
    assert launchctl.restarts == ["com.example.job"]


def test_a_collector_that_never_wrote_anything_still_counts_as_dead(tmp_path: Path) -> None:
    """`absent` on a NON-optional collector is death, not a reason to stay quiet."""

    launchctl = FakeLaunchCtl()
    supervisor = make_supervisor(tmp_path, [heartbeat_spec(tmp_path / "tape")], launchctl=launchctl)
    verdict = supervisor.run_once()[0]
    assert verdict.status == wd.RESTARTED
    assert verdict.age_seconds is None
    assert launchctl.restarts == ["com.example.job"]


def test_an_optional_collector_that_does_not_exist_yet_is_skipped(tmp_path: Path) -> None:
    spec = heartbeat_spec(tmp_path / "not-built-yet", optional=True)
    launchctl = FakeLaunchCtl()
    supervisor = make_supervisor(tmp_path, [spec], launchctl=launchctl)
    assert supervisor.run_once()[0].status == wd.SKIPPED
    assert launchctl.restarts == []


def test_a_non_restartable_collector_is_reported_and_never_touched(tmp_path: Path) -> None:
    """The sentinel signs transactions. A supervisor that can start it can start it wrongly."""

    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-14T10:00:00+00:00"}])
    spec = heartbeat_spec(tmp_path / "tape", restartable=False)
    launchctl, telegram = FakeLaunchCtl(), FakeTelegram()
    supervisor = make_supervisor(tmp_path, [spec], launchctl=launchctl, telegram=telegram)
    verdict = supervisor.run_once()[0]
    assert verdict.status == wd.STALE
    assert launchctl.restarts == []
    assert "does NOT restart" in telegram.messages[0]


def test_the_restart_cooldown_stops_a_tight_respawn_loop(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T10:00:00+00:00"}])
    spec = heartbeat_spec(tmp_path / "tape")
    launchctl = FakeLaunchCtl()
    make_supervisor(tmp_path, [spec], launchctl=launchctl).run_once()
    assert launchctl.restarts == ["com.example.job"]

    # 30 seconds later the collector has not yet had time to write its first heartbeat.
    soon = make_supervisor(tmp_path, [spec], launchctl=launchctl, now=T0 + timedelta(seconds=30))
    assert soon.run_once()[0].status == wd.COOLDOWN
    assert len(launchctl.restarts) == 1

    # Past the cooldown, and still stale, it tries again.
    later = make_supervisor(tmp_path, [spec], launchctl=launchctl, now=T0 + timedelta(seconds=400))
    assert later.run_once()[0].status == wd.RESTARTED
    assert len(launchctl.restarts) == 2


def test_repeated_failed_restarts_escalate_to_a_scream(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T10:00:00+00:00"}])
    spec = heartbeat_spec(tmp_path / "tape")
    launchctl, telegram = FakeLaunchCtl(), FakeTelegram()

    make_supervisor(tmp_path, [spec], launchctl=launchctl, telegram=telegram).run_once()
    assert telegram.messages == []  # one restart is routine, not an emergency

    second = make_supervisor(tmp_path, [spec], launchctl=launchctl, telegram=telegram,
                             now=T0 + timedelta(seconds=400))
    assert second.run_once()[0].alerted is True
    assert "2 restarts in a row" in telegram.messages[0]


def test_the_restart_budget_is_finite_and_says_so(tmp_path: Path) -> None:
    """A crash loop against a metered RPC is worse than a stopped collector."""

    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T10:00:00+00:00"}])
    spec = heartbeat_spec(tmp_path / "tape")
    launchctl, telegram = FakeLaunchCtl(), FakeTelegram()
    for i in range(wd.DEFAULT_MAX_RESTARTS_PER_HOUR):
        supervisor = make_supervisor(tmp_path, [spec], launchctl=launchctl, telegram=telegram,
                                     now=T0 + timedelta(seconds=400 * i))
        assert supervisor.run_once()[0].status == wd.RESTARTED

    exhausted = make_supervisor(tmp_path, [spec], launchctl=launchctl, telegram=telegram,
                                now=T0 + timedelta(seconds=400 * wd.DEFAULT_MAX_RESTARTS_PER_HOUR))
    verdict = exhausted.run_once()[0]
    assert verdict.status == wd.GIVING_UP
    assert len(launchctl.restarts) == wd.DEFAULT_MAX_RESTARTS_PER_HOUR
    assert any("stopped restarting it" in m for m in telegram.messages)

    # An hour later the budget has rolled off and it may try again.
    recovered = make_supervisor(tmp_path, [spec], launchctl=launchctl, telegram=telegram,
                                now=T0 + timedelta(hours=3))
    assert recovered.run_once()[0].status == wd.RESTARTED


def test_a_failed_restart_screams_immediately(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T10:00:00+00:00"}])
    telegram = FakeTelegram()
    supervisor = make_supervisor(tmp_path, [heartbeat_spec(tmp_path / "tape")],
                                 launchctl=FakeLaunchCtl(restart_ok=False), telegram=telegram)
    assert supervisor.run_once()[0].status == wd.GIVING_UP
    assert "COULD NOT restart" in telegram.messages[0]


def test_alerts_are_deduped_and_then_cleared_by_recovery(tmp_path: Path) -> None:
    tape = tmp_path / "tape" / "a.jsonl"
    write_jsonl(tape, [{"kind": "heartbeat", "t_ingest": "2026-08-14T10:00:00+00:00"}])
    spec = heartbeat_spec(tmp_path / "tape", restartable=False)
    telegram = FakeTelegram()
    make_supervisor(tmp_path, [spec], telegram=telegram).run_once()
    make_supervisor(tmp_path, [spec], telegram=telegram, now=T0 + timedelta(seconds=60)).run_once()
    assert len(telegram.messages) == 1  # deduped inside the interval

    # Recovery clears the dedupe key, so the NEXT outage alerts rather than being swallowed.
    write_jsonl(tape, [{"kind": "heartbeat", "t_ingest": "2026-08-15T12:00:00+00:00"}])
    make_supervisor(tmp_path, [spec], telegram=telegram).run_once()
    write_jsonl(tape, [{"kind": "heartbeat", "t_ingest": "2026-08-14T10:00:00+00:00"}])
    make_supervisor(tmp_path, [spec], telegram=telegram, now=T0 + timedelta(seconds=120)).run_once()
    assert len(telegram.messages) == 2


def test_a_weak_proof_makes_a_weaker_claim(tmp_path: Path) -> None:
    """An event-only signal must never be reported with a heartbeat's confidence."""

    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-14T10:00:00+00:00"}])
    telegram = FakeTelegram()
    spec = heartbeat_spec(tmp_path / "tape", restartable=False, proof=wd.PROOF_EVENT)
    make_supervisor(tmp_path, [spec], telegram=telegram).run_once()
    assert "quiet market cannot be ruled out" in telegram.messages[0]

    telegram2 = FakeTelegram()
    spec2 = heartbeat_spec(tmp_path / "tape", restartable=False, proof=wd.PROOF_HEARTBEAT)
    # A fresh state file: the same (collector, key) pair would otherwise be deduped away.
    (tmp_path / "state.json").unlink()
    make_supervisor(tmp_path, [spec2], telegram=telegram2).run_once()
    assert "dead or wedged process" in telegram2.messages[0]


def test_a_broken_probe_does_not_take_down_the_pass(tmp_path: Path) -> None:
    def explode() -> wd.Freshness:
        raise RuntimeError("probe is broken")

    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T11:59:30+00:00"}])
    specs = [
        wd.CollectorSpec(name="broken", label=None, probe=explode, cadence_seconds=30.0,
                         restartable=False),
        heartbeat_spec(tmp_path / "tape"),
    ]
    verdicts = make_supervisor(tmp_path, specs).run_once()
    assert verdicts[0].status == wd.STALE
    assert "probe raised RuntimeError" in verdicts[0].detail
    assert verdicts[1].status == wd.OK


def test_the_grace_floor_survives_a_short_cadence(tmp_path: Path) -> None:
    """cadence x grace can be seconds; a scheduling hiccup must not read as death."""

    assert heartbeat_spec(tmp_path, cadence=1.0, grace=2.0).stale_after == wd.MIN_GRACE_SECONDS
    assert heartbeat_spec(tmp_path, cadence=1800.0, grace=2.0).stale_after == 3600.0


# ---------------------------------------------------------------------------------------
# the supervisor's own tape, and idempotence
# ---------------------------------------------------------------------------------------


def test_every_pass_writes_the_watchdogs_own_heartbeat(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T11:59:30+00:00"}])
    supervisor = make_supervisor(tmp_path, [heartbeat_spec(tmp_path / "tape")])
    supervisor.run_once()
    supervisor.run_once()
    rows = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert all(r["kind"] == "watchdog_pass" for r in rows)
    assert rows[0]["collectors"][0]["status"] == wd.OK
    assert json.loads((tmp_path / "state.json").read_text())["_watchdog"]["passes"] == 2


def test_a_second_concurrent_pass_is_a_no_op(tmp_path: Path) -> None:
    """launchd firing on top of a slow pass must be harmless by construction."""

    lock_path = tmp_path / "watchdog.lock"
    held = wd.acquire_lock(lock_path)
    try:
        with pytest.raises(wd.AlreadyRunning):
            wd.acquire_lock(lock_path)
    finally:
        held.close()
    # Once released, the next pass takes it.
    wd.acquire_lock(lock_path).close()


def test_the_cli_exits_zero_when_another_pass_holds_the_lock(tmp_path: Path, monkeypatch) -> None:
    """And, load-bearing, it returns BEFORE building a Supervisor.

    An earlier version of this test bound the real repo lock because `acquire_lock` had
    `LOCK_PATH` as a default argument, evaluated at import time and therefore immune to the
    monkeypatch. The test then ran a full live pass and restarted real daemons. The guard
    below is that regression: if `main` ever gets past the lock here, it constructs a
    Supervisor, and this blows up instead of restarting the operator's collectors.
    """

    lock_path = tmp_path / "watchdog.lock"
    monkeypatch.setattr(wd, "LOCK_PATH", lock_path)
    monkeypatch.setattr(
        wd, "Supervisor",
        lambda **_: pytest.fail("main() built a Supervisor while the lock was held"),
    )
    held = wd.acquire_lock(lock_path)
    try:
        assert wd.main(["--no-telegram"]) == 0
    finally:
        held.close()


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "tape" / "a.jsonl",
                [{"kind": "heartbeat", "t_ingest": "2026-08-15T10:00:00+00:00"}])
    launchctl, telegram = FakeLaunchCtl(), FakeTelegram()
    supervisor = make_supervisor(tmp_path, [heartbeat_spec(tmp_path / "tape")],
                                 launchctl=launchctl, telegram=telegram, dry_run=True)
    supervisor.run_once()
    assert launchctl.restarts == []
    assert telegram.messages == []
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "journal.jsonl").exists()


# ---------------------------------------------------------------------------------------
# Telegram, and the token that must never reach a log
# ---------------------------------------------------------------------------------------


def test_a_telegram_failure_never_stringifies_the_exception(capsys) -> None:
    """The bot token is inside the request URL, so httpx errors carry the credential."""

    secret = "123456:AAH-super-secret-token"

    def explode(token: str, chat_id: str, text: str) -> None:
        raise RuntimeError(f"connect to https://api.telegram.org/bot{token}/sendMessage failed")

    telegram = wd.Telegram(secret, "42", sender=explode)
    assert telegram.send("hello") is False
    assert telegram.last_error_type == "RuntimeError"
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "RuntimeError" in captured.err


def test_telegram_is_a_no_op_when_unconfigured() -> None:
    assert wd.Telegram(None, None).send("x") is False
    assert wd.Telegram("token", None).configured is False


def test_the_notifications_block_is_read_out_of_config_yaml(tmp_path: Path) -> None:
    token_file = tmp_path / "tg"
    token_file.write_text("secret-token\n")
    token_file.chmod(0o600)
    config = tmp_path / "config.yaml"
    config.write_text(
        "rpc:\n  commitment: confirmed\n"
        "notifications:\n"
        f"  telegram_bot_token_file: {token_file}\n"
        "  telegram_chat_id: '6913902526'\n"
        "server:\n  port: 8787\n",
        encoding="utf-8",
    )
    telegram = wd.telegram_from_config(config)
    assert telegram.token == "secret-token"
    assert telegram.chat_id == "6913902526"

    # A group/world-readable secret is refused, following shitcoims_sentinel/secrets.py.
    token_file.chmod(0o644)
    assert wd.telegram_from_config(config).token is None


def test_a_missing_config_yields_an_unconfigured_notifier(tmp_path: Path) -> None:
    assert wd.telegram_from_config(tmp_path / "absent.yaml").configured is False


# ---------------------------------------------------------------------------------------
# the shipped table, checked against the repo it actually supervises
# ---------------------------------------------------------------------------------------


def test_every_shipped_collector_that_claims_a_launchd_label_has_a_plist() -> None:
    for spec in wd.default_collectors():
        if spec.label is not None:
            assert spec.plist is not None and spec.plist.exists(), spec.name


def test_the_live_money_daemons_are_never_restartable() -> None:
    by_name = {spec.name: spec for spec in wd.default_collectors()}
    assert by_name["sentinel"].restartable is False
    assert by_name["sentinel"].label is None


def test_launchctl_bootstraps_a_job_that_is_not_loaded(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(list(argv))
        if argv[1] == "print":
            return subprocess.CompletedProcess(argv, 1, "", "not found")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plist = tmp_path / "com.example.job.plist"
    plist.write_text("<plist/>")
    ok, _detail = wd.LaunchCtl(runner).restart("com.example.job", plist)
    assert ok is True
    verbs = [c[1] for c in calls]
    assert verbs == ["print", "bootstrap", "enable", "kickstart"]
    assert (tmp_path / "Library" / "LaunchAgents" / "com.example.job.plist").exists()


def test_the_cluster_probe_reads_process_liveness_not_pool_progress(tmp_path: Path) -> None:
    """A pool catching up from a day-old cursor must not read as a dead recorder."""

    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({
        "t": "2026-08-15T11:59:50+00:00", "phase": "listing", "pid": 123,
    }), encoding="utf-8")
    freshness = wd.JsonFieldProbe(path, "t")()
    assert freshness.age_seconds(T0) == pytest.approx(10.0)
    assert "phase=listing" in freshness.detail
    assert wd.JsonFieldProbe(tmp_path / "absent.json", "t")().absent is True


def test_a_just_bootstrapped_job_is_started_not_kicked(tmp_path: Path, monkeypatch) -> None:
    """`kickstart -k` on a job bootstrap just started SIGTERMs it and blocks. See restart()."""

    calls: list[list[str]] = []

    def runner(argv):
        calls.append(list(argv))
        code = 1 if argv[1] == "print" else 0
        return subprocess.CompletedProcess(argv, code, "", "")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    plist = tmp_path / "com.example.job.plist"
    plist.write_text("<plist/>")
    wd.LaunchCtl(runner).restart("com.example.job", plist)
    assert calls[-1] == ["launchctl", "kickstart", "gui/%d/com.example.job" % __import__("os").getuid()]

    # A job that WAS loaded is the wedged case, and there -k is the whole point.
    calls.clear()
    wd.LaunchCtl(lambda a: (calls.append(list(a)), subprocess.CompletedProcess(a, 0, "", ""))[1]).restart(
        "com.example.job", plist
    )
    assert "-k" in calls[-1]


def test_a_hanging_launchctl_fails_the_restart_instead_of_the_whole_pass(monkeypatch) -> None:
    """One slow collector must not leave every other collector unchecked.

    `kickstart -k` blocks until the old instance is gone and timed out for real against the
    cluster recorder; the raise propagated out of the pass, so the other five collectors were
    never probed that minute.
    """

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 30)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = wd.LaunchCtl._subprocess(["launchctl", "kickstart", "-k", "gui/501/x"])
    assert result.returncode == 124
    assert "timed out" in result.stderr

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert wd.LaunchCtl._subprocess(["launchctl", "print", "x"]).returncode == 127
