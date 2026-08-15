"""Offline tests for the PumpPortal firehose.

Every payload here is a verbatim copy of a frame observed on the live socket on 2026-08-14,
so the fake is a fake *transport*, never a fake *schema* — a test suite that invents its own
payload shape verifies the test's imagination rather than the vendor's feed.

No network, no sleeping, no wall clock: the connector, the clock and the sleep are all
injected. Time only moves when a script step says it does, which is what makes the staleness
alarm testable at all — it fires on silence, and silence is exactly what a real-time test
cannot afford to wait for.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shitcoims_scalper.firehose import (
    CLOCK_ABSENT,
    CLOCK_LOCAL,
    VENDOR_FLOAT_FIELDS,
    Backoff,
    Feed,
    FirehoseClient,
    JsonlSink,
    ListSink,
    LivenessMonitor,
    MalformedFrame,
    build_parser,
    classify,
    event_clock,
    last_close_on_disk,
    parse_feeds,
    partition_of,
)
from shitcoims_tape.schema import WatchClose

# --- payloads observed live on 2026-08-14, copied verbatim -------------------------------

CREATE_SIGNATURE = (
    "3ShNEcfKhWrvFVTwHCK7FjgWXABAZgo9Cpr2S6AGngg9xDifcQyY2mGQQ85p11vxSRvQ3B3SbaajobL1rfSJmyjG"
)
MIGRATE_SIGNATURE = (
    "3GD3ohyHT3CvGgVAuXgqtMkxy6KNMFbV875eVePZRZGmP2GTUJSkvL2hrHLzqQvTkBE9HDXbmrSeaC2aUCncemVZ"
)

CREATE_FRAME = json.dumps(
    {
        "signature": CREATE_SIGNATURE,
        "mint": "8yZ1rj5nHbUFuCbnoowE6rHLZYiuTe1tbxEskgzUpump",
        "traderPublicKey": "HDypasvYsG5MuABAfaTf78FVYMmYedcbefZ7pxWEhVQV",
        "txType": "create",
        "initialBuy": 2115327.702796,
        "solAmount": 0.059259258,
        "bondingCurveKey": "Hgaf727Ccy1YfWAZ77otqmqW5QY8avMXi4pkbRdiomrH",
        "vTokensInBondingCurve": 1070884672.297204,
        "vSolInBondingCurve": 30.059259257999976,
        "marketCapSol": 28.069557848389476,
        "name": "Cash Elon ",
        "symbol": "CASHELON",
        "uri": "https://ipfs.io/ipfs/bafkreid55z3ln7vg3udpgagfeumjcd7stnfqri7zkc4n227eq4vs24rdj4",
        "is_mayhem_mode": True,
        "pool": "pump",
    }
)

MIGRATE_FRAME = json.dumps(
    {
        "signature": MIGRATE_SIGNATURE,
        "mint": "DU8QWqR361yn4VQbRjYke4vdaKQYcfvDHsn2bx2cpump",
        "txType": "migrate",
        "pool": "pump-amm",
    }
)

INT_SOL_SIGNATURE = (
    "4LiEUCpZpjNgVyd32FyvNcYKzDLzUDHibB13VGN4Dqs8FcPCjePUwDP4yLeVFdxFqkuJeaFd89C5VcHsdXFjgXDZ"
)

#: Observed in the same minute as CREATE_FRAME: the same ``solAmount`` field, but a bare JSON
#: integer rather than a float. The vendor's type is not stable across frames.
INT_SOL_AMOUNT_FRAME = json.dumps(
    {
        "signature": INT_SOL_SIGNATURE,
        "mint": "5Q1wj11auXNg4ckBUEagq2FxzQD5XUo5Gdz8UNaApump",
        "traderPublicKey": "satoshid33F5UWoeCy6itHuWUodVUT1pPwbdHM3yti6",
        "txType": "create",
        "initialBuy": 67062499.999999,
        "solAmount": 2,
        "bondingCurveKey": "eqNGFca6geT8dS4YxJbe5FaGXHQoqHHu6i3cAjAomZ4",
        "vTokensInBondingCurve": 1005937500.000001,
        "vSolInBondingCurve": 31.999999999999968,
        "marketCapSol": 31.811121466293816,
        "name": "America First Coalition",
        "symbol": "AMERICA",
        "uri": "https://metadata.j7tracker.io/metadata/b14043e13297466b.json",
        "is_mayhem_mode": False,
        "pool": "pump",
    }
)

ACK_FRAME = json.dumps({"message": "Successfully subscribed to token creation events."})

#: The vendor's rejection of the trade feeds without a funded API key. The subscription is
#: accepted at the protocol level and then produces nothing, so this frame is the only
#: evidence that the feed is dead.
FUNDED_KEY_FRAME = json.dumps(
    {
        "message": (
            "'subscribeTokenTrade' and 'subscribeAccountTrade' methods are only available "
            "when connecting with an API key funded with at least 0.02 SOL."
        )
    }
)

START = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


# --- fake transport ----------------------------------------------------------------------


class FakeClock:
    """A clock that only moves when a script step moves it."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@dataclass(frozen=True)
class Silence:
    """No frame for ``seconds``; the read times out and the clock jumps."""

    seconds: float


@dataclass(frozen=True)
class Drop:
    """The socket dies mid-stream."""

    detail: str = "connection reset"


class StopRun:
    """Ask the client to shut down; the read times out so the loop notices."""


class FakeSocket:
    def __init__(self, script: list[object], clock: FakeClock, client_box: list[object]) -> None:
        self.script = list(script)
        self.clock = clock
        self.sent: list[str] = []
        self._client_box = client_box

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if not self.script:
            raise ConnectionError("script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Silence):
            self.clock.advance(step.seconds)
            raise TimeoutError
        if isinstance(step, Drop):
            raise ConnectionError(step.detail)
        if isinstance(step, StopRun):
            client = self._client_box[0]
            client.stop()  # type: ignore[attr-defined]
            raise TimeoutError
        assert isinstance(step, str)
        self.clock.advance(0.001)
        return step


def make_connector(scripts: list[object], clock: FakeClock, client_box: list[object]):
    """Each entry is either a frame script (list) or an Exception raised by ``connect`` itself."""

    remaining = list(scripts)
    opened: list[FakeSocket] = []

    @asynccontextmanager
    async def connect(url: str):
        if not remaining:
            raise ConnectionError("no further connections scripted")
        step = remaining.pop(0)
        if isinstance(step, Exception):
            raise step
        socket = FakeSocket(list(step), clock, client_box)  # type: ignore[arg-type]
        opened.append(socket)
        yield socket

    connect.opened = opened  # type: ignore[attr-defined]
    return connect


def build_client(
    scripts: list[object],
    *,
    clock: FakeClock | None = None,
    heartbeat_seconds: float = 1000.0,
    stale_after_seconds: float = 1000.0,
    max_attempts: int | None = None,
    sink: ListSink | None = None,
    feeds: tuple[Feed, ...] = (Feed.NEW_TOKEN, Feed.MIGRATION),
) -> tuple[FirehoseClient, ListSink, FakeClock]:
    clock = clock or FakeClock()
    sink = sink or ListSink()
    box: list[object] = []
    connect = make_connector(scripts, clock, box)

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    client = FirehoseClient(
        sink=sink,
        feeds=feeds,
        connect=connect,
        clock=clock,
        sleep=sleep,
        heartbeat_seconds=heartbeat_seconds,
        stale_after_seconds=stale_after_seconds,
        max_attempts=max_attempts,
        backoff=Backoff(base=2.0, jitter=0.0),
    )
    box.append(client)
    client._connector = connect  # type: ignore[attr-defined]
    return client, sink, clock


# --- two clocks --------------------------------------------------------------------------


def test_absent_event_clock_is_null_and_says_so() -> None:
    """The whole point: no vendor clock means null, never our clock wearing a disguise."""

    row = classify(CREATE_FRAME, START)
    assert row["t_event"] is None
    assert row["t_event_source"] == CLOCK_ABSENT
    assert row["t_ingest"] == "2026-08-14T12:00:00.000000+00:00"


def test_t_ingest_carries_microseconds() -> None:
    stamped = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=UTC)
    assert classify(CREATE_FRAME, stamped)["t_ingest"] == "2026-08-14T12:00:00.123456+00:00"


def test_event_clock_absent_on_every_observed_payload() -> None:
    for frame in (CREATE_FRAME, MIGRATE_FRAME):
        assert event_clock(json.loads(frame)) == (None, CLOCK_ABSENT)


def test_event_clock_used_when_the_vendor_ever_supplies_one() -> None:
    """Forward compatibility: if PumpPortal adds a clock we record it instead of writing nulls."""

    assert event_clock({"timestamp": 1786753695}) == (
        "2026-08-15T00:28:15.000000+00:00",
        "vendor:timestamp:unix_s",
    )
    assert event_clock({"blockTime": 1786753695000}) == (
        "2026-08-15T00:28:15.000000+00:00",
        "vendor:blockTime:unix_ms",
    )
    assert event_clock({"timestamp": "2026-08-14T00:28:15+00:00"}) == (
        "2026-08-14T00:28:15.000000+00:00",
        "vendor:timestamp:iso8601",
    )


@pytest.mark.parametrize(
    "payload",
    [{"timestamp": "not a date"}, {"timestamp": None}, {"timestamp": True}, {"timestamp": {}}],
)
def test_unparseable_event_clock_is_null_not_substituted(payload: dict) -> None:
    value, source = event_clock(payload)
    assert value is None
    assert source.startswith("unparseable:")


def test_naive_iso_event_clock_is_refused() -> None:
    """A timestamp with no zone is not a moment. Guessing UTC is how a clock silently shifts."""

    assert event_clock({"timestamp": "2026-08-14T00:28:15"}) == (None, "unparseable:timestamp:naive")


async def test_no_row_ever_borrows_the_ingest_clock() -> None:
    """The regression guard for the 169-fake-timestamps bug, over a whole run's worth of rows."""

    client, sink, _ = build_client(
        [[CREATE_FRAME, MIGRATE_FRAME, ACK_FRAME, "{ not json", Silence(2000.0), StopRun()]],
        heartbeat_seconds=100.0,
        stale_after_seconds=100.0,
        max_attempts=1,
    )
    await client.run()
    assert sink.rows
    for _, row in sink.rows:
        assert "t_ingest" in row
        assert "t_event" in row
        assert "t_event_source" in row
        if row["t_event"] is None:
            assert row["t_event_source"] in (CLOCK_ABSENT, CLOCK_LOCAL) or row[
                "t_event_source"
            ].startswith("unparseable:")
        else:
            assert row["t_event_source"].startswith("vendor:")


def test_local_rows_declare_they_have_no_vendor_clock() -> None:
    monitor = LivenessMonitor(heartbeat_seconds=1.0, stale_after_seconds=1000.0)
    monitor.start(START)
    rows = monitor.due(START + timedelta(seconds=5), connected=True, window_id="w-1")
    assert rows
    assert rows[0]["t_event"] is None
    assert rows[0]["t_event_source"] == CLOCK_LOCAL


# --- classification ----------------------------------------------------------------------


def test_create_frame_classifies_and_keeps_the_payload_verbatim() -> None:
    row = classify(CREATE_FRAME, START)
    assert row["kind"] == "new_token"
    assert row["tx_type"] == "create"
    assert row["mint"] == "8yZ1rj5nHbUFuCbnoowE6rHLZYiuTe1tbxEskgzUpump"
    assert row["venue"] == "pump"
    assert row["payload"] == json.loads(CREATE_FRAME)


def test_vendor_floats_are_preserved_bit_for_bit_and_not_scaled() -> None:
    """Never float for money: so we do not invent integers out of vendor-rounded floats either."""

    row = classify(CREATE_FRAME, START)
    assert row["payload"]["solAmount"] == 0.059259258
    assert row["payload"]["marketCapSol"] == 28.069557848389476
    assert "lamports" not in row
    assert json.loads(json.dumps(row))["payload"]["vSolInBondingCurve"] == 30.059259257999976


def test_vendor_float_fields_names_every_quantity_in_an_observed_payload() -> None:
    """Keeps the docstring's claim honest: if the vendor adds a quantity, this fails."""

    for frame in (CREATE_FRAME, MIGRATE_FRAME, INT_SOL_AMOUNT_FRAME):
        payload = json.loads(frame)
        numeric = {
            key
            for key, value in payload.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        assert numeric <= VENDOR_FLOAT_FIELDS, f"unnamed quantity in {payload.get('txType')}"


def test_a_round_money_amount_arrives_as_a_json_int_and_survives() -> None:
    """Observed live: ``solAmount`` came through as ``2``, not ``2.0``. A consumer keying on
    isinstance(v, float) would silently skip exactly the large deliberate trades."""

    payload = classify(INT_SOL_AMOUNT_FRAME, START)["payload"]
    assert payload["solAmount"] == 2
    assert isinstance(payload["solAmount"], int)
    assert json.loads(json.dumps(payload))["solAmount"] == 2


def test_migrate_frame_classifies_with_its_four_keys() -> None:
    row = classify(MIGRATE_FRAME, START)
    assert row["kind"] == "migration"
    assert row["venue"] == "pump-amm"
    assert set(row["payload"]) == {"signature", "mint", "txType", "pool"}


def test_control_frames_are_control_not_events() -> None:
    row = classify(ACK_FRAME, START)
    assert row["kind"] == "control"
    assert "Successfully subscribed" in row["message"]


def test_unknown_tx_type_is_kept_not_dropped() -> None:
    """An unknown event we stored is recoverable; one we discarded is gone forever."""

    row = classify(json.dumps({"txType": "somethingNew", "mint": "m"}), START)
    assert row["kind"] == "event_unclassified"
    assert row["payload"]["txType"] == "somethingNew"


@pytest.mark.parametrize(
    "frame",
    ["not json at all", "[1,2,3]", '"a string"', "", "{", json.dumps({"txType": 7})],
)
def test_malformed_frames_raise_the_defect_type(frame: str) -> None:
    with pytest.raises(MalformedFrame):
        classify(frame, START)


async def test_malformed_payload_is_defected_not_crashed() -> None:
    client, sink, _ = build_client(
        [["not json at all", CREATE_FRAME, StopRun()]],
        max_attempts=1,
    )
    stats = await client.run()
    defects = sink.of_kind("defect")
    assert len(defects) == 1
    assert defects[0]["reason"] == "frame is not json"
    assert defects[0]["raw_excerpt"] == "not json at all"
    assert stats.defects == 1
    # The stream kept going: the good frame after the bad one still landed.
    assert stats.events_by_kind == {"new_token": 1}


async def test_defect_excerpt_is_bounded() -> None:
    client, sink, _ = build_client([["x" * 10_000, StopRun()]], max_attempts=1)
    await client.run()
    defect = sink.of_kind("defect")[0]
    assert len(defect["raw_excerpt"]) == 2000
    assert defect["raw_length"] == 10_000


# --- watch window ledger -----------------------------------------------------------------


async def test_window_opens_on_connect_and_closes_on_drop_then_reopens() -> None:
    """A gap must be recoverable as "we were not listening", never as "nothing happened"."""

    client, sink, _clock = build_client(
        [
            [CREATE_FRAME, Drop("reset by peer")],
            [MIGRATE_FRAME, StopRun()],
        ],
        max_attempts=2,
    )
    stats = await client.run()

    opens = sink.of_kind("watch_open")
    closes = sink.of_kind("watch_close")
    gaps = sink.of_kind("gap")
    assert len(opens) == 2
    assert len(closes) == 2
    assert len(gaps) == 1

    first = closes[0]
    assert first["window"]["close_reason"] == str(WatchClose.OBSERVER_LOST)
    assert first["informative_censoring"] is True
    assert "reset by peer" in first["window"]["close_detail"]
    assert first["events"] == 1

    # The gap spans exactly close -> reopen, and is labelled with why we were not listening.
    gap = gaps[0]
    assert gap["started_at"] == first["window"]["closed_at"]
    assert gap["ended_at"] == opens[1]["window"]["opened_at"]
    assert gap["seconds"] == pytest.approx(2.0)  # the backoff delay, jitter disabled
    assert gap["reason"] == f"not_listening:{WatchClose.OBSERVER_LOST}"
    assert stats.gaps == 1
    assert stats.gap_seconds == pytest.approx(2.0)

    # Second window is a distinct window id, and it carried the migration.
    assert opens[0]["window"]["window_id"] != opens[1]["window"]["window_id"]
    assert closes[1]["events"] == 1
    assert stats.windows == 2


async def test_restart_downtime_is_recorded_as_a_gap_like_any_other(tmp_path: Path) -> None:
    """A day of blindness because nobody restarted the daemon is the same blindness as a
    dropped socket, and the tape must say so in the same shape."""

    # Run one: connect, take an event, shut down cleanly.
    clock = FakeClock()
    sink = JsonlSink(tmp_path)
    box: list[object] = []
    first = FirehoseClient(
        sink=sink,
        connect=make_connector([[CREATE_FRAME, StopRun()]], clock, box),
        clock=clock,
        max_attempts=1,
    )
    box.append(first)
    await first.run()

    previous = last_close_on_disk(tmp_path)
    assert previous is not None
    assert previous.reason == str(WatchClose.OPERATOR)

    # Run two, a day later. Nothing was listening in between.
    later = FakeClock(START + timedelta(days=1))
    sink2 = JsonlSink(tmp_path)
    box2: list[object] = []
    second = FirehoseClient(
        sink=sink2,
        connect=make_connector([[MIGRATE_FRAME, StopRun()]], later, box2),
        clock=later,
        max_attempts=1,
        resume_from=previous,
    )
    box2.append(second)
    stats = await second.run()

    ledger = [
        json.loads(line)
        for path in sorted((tmp_path / "ledger").glob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]
    gaps = [row for row in ledger if row["kind"] == "gap"]
    assert len(gaps) == 1
    assert gaps[0]["seconds"] == pytest.approx(86_400.0, abs=1.0)
    assert gaps[0]["reason"] == f"not_listening:process_not_running:{WatchClose.OPERATOR}"
    assert stats.gaps == 1


def test_last_close_on_disk_returns_nothing_for_a_fresh_tape(tmp_path: Path) -> None:
    """No claim is better than a false one: an unknown downtime is not a zero-second downtime."""

    assert last_close_on_disk(tmp_path) is None
    (tmp_path / "ledger").mkdir()
    assert last_close_on_disk(tmp_path) is None


def test_last_close_on_disk_survives_a_torn_final_line(tmp_path: Path) -> None:
    """A crash truncates the last line. That must not hide the close before it."""

    ledger = tmp_path / "ledger"
    ledger.mkdir()
    good = {
        "kind": "watch_close",
        "window": {"closed_at": "2026-08-14T12:00:00.000000+00:00", "close_reason": "deadline"},
    }
    (ledger / "2026-08-14.jsonl").write_text(
        json.dumps(good) + "\n" + '{"kind":"watch_close","window":{"closed_'
    )
    found = last_close_on_disk(tmp_path)
    assert found is not None
    assert found.closed_at == datetime(2026, 8, 14, 12, tzinfo=UTC)
    assert found.reason == "deadline"


def test_last_close_on_disk_prefers_the_newest_day(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    for day, hour in (("2026-08-13", 9), ("2026-08-14", 10)):
        row = {
            "kind": "watch_close",
            "window": {
                "closed_at": f"{day}T{hour:02d}:00:00.000000+00:00",
                "close_reason": "operator",
            },
        }
        (ledger / f"{day}.jsonl").write_text(json.dumps(row) + "\n")
    found = last_close_on_disk(tmp_path)
    assert found is not None
    assert found.closed_at == datetime(2026, 8, 14, 10, tzinfo=UTC)


async def test_reconnect_resubscribes_every_feed() -> None:
    """A reconnect that forgets to resubscribe leaves a socket that is open and permanently silent."""

    client, _, _ = build_client(
        [[Drop()], [CREATE_FRAME, StopRun()]],
        max_attempts=2,
    )
    await client.run()
    sockets = client._connector.opened  # type: ignore[attr-defined]
    assert len(sockets) == 2
    for socket in sockets:
        methods = [json.loads(frame)["method"] for frame in socket.sent]
        assert methods == ["subscribeNewToken", "subscribeMigration"]


async def test_clean_shutdown_closes_the_window_as_operator_not_observer_lost() -> None:
    """SIGINT is not censoring. Recording it as OBSERVER_LOST would poison every survival rate."""

    client, sink, _ = build_client([[CREATE_FRAME, StopRun()]], max_attempts=1)
    await client.run()
    close = sink.of_kind("watch_close")[0]
    assert close["window"]["close_reason"] == str(WatchClose.OPERATOR)
    assert close["informative_censoring"] is False


async def test_deadline_closes_the_window_benignly() -> None:
    clock = FakeClock()
    deadline = START + timedelta(seconds=5)
    client, sink, _ = build_client(
        [[CREATE_FRAME, Silence(30.0), CREATE_FRAME]],
        clock=clock,
        max_attempts=1,
    )
    await client.run(deadline=deadline)
    close = sink.of_kind("watch_close")[0]
    assert close["window"]["close_reason"] == str(WatchClose.DEADLINE)
    assert close["informative_censoring"] is False


async def test_failure_to_connect_records_that_we_were_not_listening() -> None:
    """No window was opened, so nothing closes — and without this row the silence looks benign."""

    client, sink, _ = build_client(
        [OSError("nodename nor servname provided"), [CREATE_FRAME, StopRun()]],
        max_attempts=2,
    )
    stats = await client.run()
    failures = sink.of_kind("connect_failed")
    assert len(failures) == 1
    assert "nodename" in failures[0]["detail"]
    assert failures[0]["retry_in_seconds"] == pytest.approx(2.0)
    assert stats.connect_failures == 1
    assert sink.of_kind("watch_open")  # and we did get on the feed afterwards


async def test_heartbeat_continues_through_a_vendor_outage() -> None:
    """A process wedged mid-backoff must not look like one patiently retrying."""

    client, sink, _ = build_client(
        [OSError("down"), OSError("down"), [CREATE_FRAME, StopRun()]],
        heartbeat_seconds=1.0,
        max_attempts=3,
    )
    await client.run()
    beats = sink.of_kind("heartbeat")
    assert len(beats) >= 2
    assert [beat["connected"] for beat in beats[:2]] == [False, False]
    assert all(beat["window_id"] is None for beat in beats[:2])


async def test_backoff_grows_between_repeated_connect_failures() -> None:
    client, sink, _ = build_client(
        [OSError("down"), OSError("down"), OSError("down"), [CREATE_FRAME, StopRun()]],
        max_attempts=4,
    )
    await client.run()
    delays = [row["retry_in_seconds"] for row in sink.of_kind("connect_failed")]
    assert delays == [2.0, 4.0, 8.0]


def test_backoff_is_capped_and_resettable() -> None:
    backoff = Backoff(base=1.0, factor=2.0, cap=60.0, jitter=0.0)
    delays = [backoff.next_delay() for _ in range(10)]
    assert delays[:4] == [1.0, 2.0, 4.0, 8.0]
    assert max(delays) == 60.0
    backoff.reset()
    assert backoff.next_delay() == 1.0


def test_backoff_jitter_stays_inside_its_band() -> None:
    backoff = Backoff(base=10.0, jitter=0.25)
    low = Backoff(base=10.0, jitter=0.25).next_delay(rand=lambda: 0.0)
    high = Backoff(base=10.0, jitter=0.25).next_delay(rand=lambda: 1.0)
    assert (low, high) == (7.5, 12.5)
    assert 7.5 <= backoff.next_delay() <= 12.5


# --- heartbeat and staleness -------------------------------------------------------------


async def test_heartbeat_is_emitted_while_idle() -> None:
    """Liveness needs a positive signal. Inferring it from data that may be legitimately absent
    is exactly how the intelligence daemon stayed 'green' for a day after it died."""

    client, sink, _ = build_client(
        [[Silence(40.0), Silence(40.0), StopRun()]],
        heartbeat_seconds=30.0,
        stale_after_seconds=10_000.0,
        max_attempts=1,
    )
    stats = await client.run()
    beats = sink.of_kind("heartbeat")
    assert len(beats) == 2
    assert stats.heartbeats == 2
    assert all(beat["connected"] is True for beat in beats)
    assert all(beat["events_total"] == 0 for beat in beats)
    assert beats[0]["window_id"] == sink.of_kind("watch_open")[0]["window"]["window_id"]


async def test_staleness_alarm_fires_and_then_clears() -> None:
    client, sink, _ = build_client(
        [[CREATE_FRAME, Silence(200.0), CREATE_FRAME, StopRun()]],
        heartbeat_seconds=10_000.0,
        stale_after_seconds=120.0,
        max_attempts=1,
    )
    stats = await client.run()

    alarms = sink.of_kind("stale")
    assert len(alarms) == 1
    assert alarms[0]["silent_seconds"] == pytest.approx(200.0, abs=0.01)
    assert alarms[0]["threshold_seconds"] == 120.0
    assert alarms[0]["busy_hour"] is True
    assert stats.stale_alarms == 1

    cleared = sink.of_kind("stale_cleared")
    assert len(cleared) == 1
    assert cleared[0]["stale_since"] == alarms[0]["stale_since"]
    assert cleared[0]["silent_seconds"] == pytest.approx(200.0, abs=0.01)


async def test_staleness_alarm_warns_and_repeats_during_a_long_outage() -> None:
    """One row for a two-hour silence would be a footnote. It repeats, so the outage has a shape."""

    client, sink, _ = build_client(
        [[CREATE_FRAME, Silence(130.0), Silence(130.0), Silence(130.0), StopRun()]],
        heartbeat_seconds=10_000.0,
        stale_after_seconds=120.0,
        max_attempts=1,
    )
    await client.run()
    alarms = sink.of_kind("stale")
    assert len(alarms) == 3
    # All three name the same silence origin: it is one outage, not three.
    assert len({row["stale_since"] for row in alarms}) == 1
    assert [round(row["silent_seconds"]) for row in alarms] == [130, 260, 390]


async def test_quiet_market_is_distinguishable_from_a_dead_socket() -> None:
    """The requirement in one assertion: heartbeats keep coming, but only silence raises stale."""

    client, sink, _ = build_client(
        [[Silence(30.0), CREATE_FRAME, Silence(30.0), CREATE_FRAME, Silence(30.0), StopRun()]],
        heartbeat_seconds=25.0,
        stale_after_seconds=120.0,
        max_attempts=1,
    )
    await client.run()
    assert len(sink.of_kind("heartbeat")) >= 3  # the process is demonstrably alive
    assert sink.of_kind("stale") == []  # and the trickle of events is not an alarm


def test_stale_outside_busy_hours_is_still_recorded() -> None:
    """Only the log level changes with the hour. The row is written either way, because a
    reader reconstructing the past must not depend on when we happened to be paying attention."""

    monitor = LivenessMonitor(
        heartbeat_seconds=10_000.0, stale_after_seconds=60.0, busy_hours=frozenset({9, 10})
    )
    monitor.start(START)  # START is 12:00 UTC, outside the busy set
    rows = monitor.due(START + timedelta(seconds=90), connected=True, window_id="w-1")
    assert [row["kind"] for row in rows] == ["stale"]
    assert rows[0]["busy_hour"] is False


def test_staleness_is_measured_from_start_before_any_event_arrives() -> None:
    """A socket that connects and never delivers anything is the loudest failure of all, and it
    has no 'last event' to measure from."""

    monitor = LivenessMonitor(heartbeat_seconds=10_000.0, stale_after_seconds=60.0)
    monitor.start(START)
    assert monitor.due(START + timedelta(seconds=30), connected=True, window_id="w") == []
    rows = monitor.due(START + timedelta(seconds=61), connected=True, window_id="w")
    assert [row["kind"] for row in rows] == ["stale"]
    assert rows[0]["events_total"] == 0


def test_disconnected_time_does_not_raise_a_staleness_alarm() -> None:
    """While disconnected the watch ledger already says we were not listening. A stale row on
    top of that would double-count one outage as two different failures."""

    monitor = LivenessMonitor(heartbeat_seconds=10_000.0, stale_after_seconds=60.0)
    monitor.start(START)
    assert monitor.due(START + timedelta(seconds=600), connected=False, window_id=None) == []


def test_read_timeout_bounds_sigint_latency() -> None:
    """A quiet feed must not hold the read for a whole heartbeat interval: Ctrl-C would look
    hung and the watch window would close late or not at all."""

    client, _, _ = build_client([[StopRun()]], heartbeat_seconds=1000.0, stale_after_seconds=1000.0)
    assert client.read_timeout(START, None) == pytest.approx(1.0)


def test_read_timeout_takes_the_tightest_of_its_three_bounds() -> None:
    client, _, _ = build_client([[StopRun()]], heartbeat_seconds=1000.0, stale_after_seconds=1000.0)
    client._poll_seconds = 30.0
    client.monitor.start(START)
    # heartbeat/stale are far away, so the run deadline binds
    assert client.read_timeout(START, START + timedelta(seconds=4)) == pytest.approx(4.0)
    # past the deadline the read must not block at all
    assert client.read_timeout(START + timedelta(seconds=9), START + timedelta(seconds=4)) == 0.001
    # and a near heartbeat binds instead
    client.monitor.heartbeat_seconds = 2.0
    assert client.read_timeout(START, None) == pytest.approx(2.0)


def test_next_deadline_bounds_the_socket_read() -> None:
    monitor = LivenessMonitor(heartbeat_seconds=30.0, stale_after_seconds=120.0)
    monitor.start(START)
    assert monitor.next_deadline_seconds(START) == pytest.approx(30.0)
    assert monitor.next_deadline_seconds(START + timedelta(seconds=29)) == pytest.approx(1.0)
    assert monitor.next_deadline_seconds(START + timedelta(seconds=999)) == 0.0


# --- the funded-key gate on the trade feeds ----------------------------------------------


async def test_trade_feed_rejection_is_recorded_as_a_control_row() -> None:
    """subscribeTokenTrade is accepted and then silent without a funded key. The rejection frame
    is the only evidence, so it is stored rather than logged and forgotten."""

    client, sink, _ = build_client(
        [[FUNDED_KEY_FRAME, StopRun()]],
        feeds=(Feed.TOKEN_TRADE,),
        max_attempts=1,
    )
    stats = await client.run()
    controls = sink.of_kind("control")
    assert len(controls) == 1
    assert "0.02 SOL" in controls[0]["message"]
    assert stats.controls == 1
    assert stats.events_by_kind == {}


async def test_trade_feeds_send_their_keys() -> None:
    clock = FakeClock()
    sink = ListSink()
    box: list[object] = []
    connect = make_connector([[StopRun()]], clock, box)

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    client = FirehoseClient(
        sink=sink,
        feeds=(Feed.TOKEN_TRADE, Feed.ACCOUNT_TRADE),
        keys=("MintOne", "WalletTwo"),
        connect=connect,
        clock=clock,
        sleep=sleep,
        max_attempts=1,
    )
    box.append(client)
    await client.run()
    sent = [json.loads(frame) for frame in connect.opened[0].sent]  # type: ignore[attr-defined]
    assert sent == [
        {"method": "subscribeTokenTrade", "keys": ["MintOne", "WalletTwo"]},
        {"method": "subscribeAccountTrade", "keys": ["MintOne", "WalletTwo"]},
    ]


def test_feed_metadata_matches_the_wire() -> None:
    assert Feed.NEW_TOKEN.method == "subscribeNewToken"
    assert Feed.MIGRATION.method == "subscribeMigration"
    assert Feed.NEW_TOKEN.needs_keys is False
    assert Feed.TOKEN_TRADE.needs_keys is True
    assert Feed.TOKEN_TRADE.needs_funded_key is True
    assert Feed.ACCOUNT_TRADE.needs_funded_key is True
    assert Feed.NEW_TOKEN.needs_funded_key is False


# --- partitioning and the sink ------------------------------------------------------------


def test_partitions_split_events_and_keep_the_ledger_as_one_timeline() -> None:
    assert partition_of("new_token") == "new_token"
    assert partition_of("migration") == "migration"
    assert partition_of("trade") == "trade"
    assert partition_of("event_unclassified") == "event_unclassified"
    for operational in ("watch_open", "watch_close", "gap", "heartbeat", "stale", "defect"):
        assert partition_of(operational) == "ledger"


def test_jsonl_sink_partitions_by_kind_and_utc_day(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path)
    sink.write("new_token", classify(CREATE_FRAME, datetime(2026, 8, 14, 23, 59, tzinfo=UTC)))
    sink.write("new_token", classify(CREATE_FRAME, datetime(2026, 8, 15, 0, 1, tzinfo=UTC)))
    sink.write("migration", classify(MIGRATE_FRAME, datetime(2026, 8, 15, 0, 2, tzinfo=UTC)))
    sink.close()

    assert (tmp_path / "new_token" / "2026-08-14.jsonl").exists()
    assert (tmp_path / "new_token" / "2026-08-15.jsonl").exists()
    assert (tmp_path / "migration" / "2026-08-15.jsonl").exists()
    rows = [
        json.loads(line)
        for line in (tmp_path / "new_token" / "2026-08-14.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["kind"] == "new_token"


def test_jsonl_sink_appends_rather_than_truncating(tmp_path: Path) -> None:
    """Append-only: a restart must never eat the morning's tape."""

    for _ in range(2):
        sink = JsonlSink(tmp_path)
        sink.write("new_token", classify(CREATE_FRAME, START))
        sink.close()
    path = tmp_path / "new_token" / "2026-08-14.jsonl"
    assert len(path.read_text().splitlines()) == 2


async def test_end_to_end_writes_readable_jsonl(tmp_path: Path) -> None:
    clock = FakeClock()
    sink = JsonlSink(tmp_path)
    box: list[object] = []
    connect = make_connector([[CREATE_FRAME, MIGRATE_FRAME, StopRun()]], clock, box)

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    client = FirehoseClient(
        sink=sink, connect=connect, clock=clock, sleep=sleep, max_attempts=1
    )
    box.append(client)
    stats = await client.run()

    assert stats.events_by_kind == {"new_token": 1, "migration": 1}
    assert stats.events == 2
    ledger = [
        json.loads(line)
        for line in (tmp_path / "ledger" / "2026-08-14.jsonl").read_text().splitlines()
    ]
    assert [row["kind"] for row in ledger] == ["watch_open", "watch_close"]
    payload = json.loads((tmp_path / "new_token" / "2026-08-14.jsonl").read_text())
    assert payload["payload"]["symbol"] == "CASHELON"
    assert payload["window_id"] == ledger[0]["window"]["window_id"]
    assert stats.to_json()["gaps"] == 0


# --- CLI ------------------------------------------------------------------------------------


def test_parse_feeds_accepts_the_documented_spelling() -> None:
    assert parse_feeds("newToken,migration") == (Feed.NEW_TOKEN, Feed.MIGRATION)
    assert parse_feeds(" migration , newToken ") == (Feed.MIGRATION, Feed.NEW_TOKEN)
    assert parse_feeds("newToken,newToken") == (Feed.NEW_TOKEN,)


@pytest.mark.parametrize("spec", ["", " , ", "newtoken", "subscribeNewToken", "trades"])
def test_parse_feeds_refuses_anything_else(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_feeds(spec)


def test_cli_defaults_match_the_documented_invocation() -> None:
    args = build_parser().parse_args(["--minutes", "3"])
    assert args.minutes == 3.0
    assert parse_feeds(args.subscribe) == (Feed.NEW_TOKEN, Feed.MIGRATION)
    assert args.url.startswith("wss://pumpportal.fun")
    assert args.minutes is not None


def test_cli_runs_without_a_deadline_when_minutes_is_omitted() -> None:
    assert build_parser().parse_args([]).minutes is None


def test_client_refuses_a_configuration_that_cannot_alarm() -> None:
    sink = ListSink()
    with pytest.raises(ValueError):
        FirehoseClient(sink=sink, feeds=())
    with pytest.raises(ValueError):
        FirehoseClient(sink=sink, heartbeat_seconds=0)
    with pytest.raises(ValueError):
        FirehoseClient(sink=sink, stale_after_seconds=-1)
