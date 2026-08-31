"""Tests for the tape's durability layer.

Each test pins a property the recorder relies on and is named for the failure it prevents.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from solders.keypair import Keypair

from shitcoims_tape import (
    Chainstamp,
    EventKind,
    Launch,
    Provenance,
    Reserves,
    Side,
    TapeEvent,
    Trade,
)
from shitcoims_tape.writer import (
    TAPE_ROOT_ENV,
    TapeWriteError,
    TapeWriter,
    default_tape_root,
)

SIG = "5" * 88


def _mint() -> str:
    return str(Keypair().pubkey())


def _prov() -> Provenance:
    return Provenance(source="test.writer", fetched_at="2026-08-13T00:00:00Z")


def _launch(name: str = "n", symbol: str = "S") -> TapeEvent:
    return TapeEvent(
        kind=EventKind.LAUNCH,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        body=Launch(mint=_mint(), creator=_mint(), name=name, symbol=symbol),
    )


def _trade(slot: int = 1) -> TapeEvent:
    return TapeEvent(
        kind=EventKind.TRADE,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        chain=Chainstamp(slot=slot, signature=SIG, block_time=1786000000),
        body=Trade(
            mint=_mint(),
            wallet=_mint(),
            side=Side.BUY,
            sol_delta_lamports=-1_000,
            token_delta_raw=2_000,
        ),
    )


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_a_written_line_is_byte_identical_to_the_contracts_own_serialisation(tmp_path: Path) -> None:
    """The writer serialises from the payload it already built; drift here forks the format."""

    event = _launch()
    with TapeWriter(tmp_path) as writer:
        assert writer.write(event) is True
        segment = writer.path
    assert segment is not None
    assert segment.read_text(encoding="utf-8") == event.to_jsonl() + "\n"


def test_the_same_fill_seen_twice_is_written_once(tmp_path: Path) -> None:
    """A firehose and an HTTP backfill overlap by design; double-counting corrupts intensity."""

    event = _trade()
    with TapeWriter(tmp_path) as writer:
        assert writer.write(event) is True
        assert writer.write(event) is False
        stats = writer.stats
        segment = writer.path
    assert stats.events_written == 1
    assert stats.events_deduped == 1
    assert segment is not None
    assert len(_lines(segment)) == 1


def test_a_symbol_with_a_newline_stays_one_record_per_line(tmp_path: Path) -> None:
    """Memecoin names contain commas, quotes and newlines by design — hence JSONL, not CSV."""

    event = _launch(name='ha\nha,"x"\r\n', symbol="A,B\n")
    with TapeWriter(tmp_path) as writer:
        writer.write(event)
        segment = writer.path
    assert segment is not None
    text = segment.read_text(encoding="utf-8")
    assert text.count("\n") == 1
    assert _lines(segment)[0]["body"]["name"] == 'ha\nha,"x"\r\n'  # type: ignore[index]


def test_rotation_fsyncs_before_it_abandons_a_segment(tmp_path: Path) -> None:
    """Durability is a segment-boundary property; a rotate that skips fsync loses the segment."""

    writer = TapeWriter(tmp_path, max_segment_bytes=1024)
    for _ in range(40):
        writer.write(_trade())
    mid = writer.stats
    writer.close()
    stats = writer.stats
    assert mid.rotations >= 1
    # One fsync per rotation, plus the one on close.
    assert stats.fsyncs == stats.rotations + 1
    segments = sorted(tmp_path.glob("tape-*.jsonl"))
    assert len(segments) == stats.rotations + 1  # rotation always moves to a NEW file
    assert sum(len(_lines(path)) for path in segments) == 40


def test_a_utc_day_boundary_starts_a_new_segment(tmp_path: Path) -> None:
    """Segments are the retention and re-import unit, so they must align to a day."""

    days = iter(
        [
            datetime(2026, 8, 13, 23, 59, tzinfo=UTC),
            datetime(2026, 8, 14, 0, 1, tzinfo=UTC),
        ]
    )
    with TapeWriter(tmp_path, clock=lambda: next(days)) as writer:
        writer.write(_trade(slot=1))
        writer.write(_trade(slot=2))
    names = sorted(path.name for path in tmp_path.glob("tape-*.jsonl"))
    assert names == ["tape-20260813-0000.jsonl", "tape-20260814-0000.jsonl"]


def test_reopening_a_tape_appends_rather_than_truncating(tmp_path: Path) -> None:
    """A recorded fill is a fact. Nothing may overwrite a segment that already exists."""

    clock = lambda: datetime(2026, 8, 13, 12, 0, tzinfo=UTC)  # noqa: E731
    with TapeWriter(tmp_path, clock=clock) as first:
        first.write(_trade(slot=1))
    with TapeWriter(tmp_path, clock=clock) as second:
        second.write(_trade(slot=2))
    segments = sorted(tmp_path.glob("tape-*.jsonl"))
    assert len(segments) == 1
    assert len(_lines(segments[0])) == 2


def test_a_closed_writer_refuses_further_events(tmp_path: Path) -> None:
    writer = TapeWriter(tmp_path)
    writer.write(_trade())
    writer.close()
    with pytest.raises(TapeWriteError, match="closed"):
        writer.write(_trade(slot=9))


def test_backfill_prefixes_do_not_share_segments_with_live_recording(tmp_path: Path) -> None:
    """Retention, re-import and deletion all act on whole segments."""

    with TapeWriter(tmp_path, prefix="tape") as live:
        live.write(_trade(slot=1))
    with TapeWriter(tmp_path, prefix="red-pump") as imported:
        imported.write(_launch())
    names = sorted(path.name.split("-")[0] for path in tmp_path.glob("*.jsonl"))
    assert names == ["red", "tape"]


def test_the_default_root_is_local_unless_the_environment_says_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production is /tank on hbox; nothing may default to a production volume."""

    monkeypatch.delenv(TAPE_ROOT_ENV, raising=False)
    assert default_tape_root() == Path("tape")
    monkeypatch.setenv(TAPE_ROOT_ENV, str(tmp_path / "elsewhere"))
    assert default_tape_root() == tmp_path / "elsewhere"


def test_reserves_past_the_float_cliff_survive_the_round_trip_through_disk(tmp_path: Path) -> None:
    """The schema keeps raw amounts as strings; the writer must not reintroduce a float."""

    huge = 9_007_199_254_740_993  # 2**53 + 1
    event = TapeEvent(
        kind=EventKind.RESERVE,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        chain=Chainstamp(slot=7, signature=SIG),
        body=Reserves(
            pool=_mint(), virtual_sol=huge, virtual_tokens=1, real_sol=2, real_tokens=3
        ),
    )
    with TapeWriter(tmp_path) as writer:
        writer.write(event)
        segment = writer.path
    assert segment is not None
    assert _lines(segment)[0]["body"]["virtual_sol"] == str(huge)  # type: ignore[index]
