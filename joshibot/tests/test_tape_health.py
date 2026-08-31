"""Tests for the coverage and censoring audit over a recorded tape."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from solders.keypair import Keypair

from shitcoims_tape import (
    Chainstamp,
    EventKind,
    Provenance,
    Side,
    TapeEvent,
    Trade,
    WatchClose,
    WatchWindow,
)
from shitcoims_tape.health import MINIMUM_TAIL_RATIO, main, render, report
from shitcoims_tape.writer import TapeWriter

T0 = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
LATER = T0 + timedelta(days=2)


def _mint() -> str:
    return str(Keypair().pubkey())


def _prov() -> Provenance:
    return Provenance(source="test.health", fetched_at="2026-08-13T00:00:00Z")


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _signature(value: int) -> str:
    """A distinct, valid base58 signature per slot. `0` is not in the base58 alphabet."""

    text = ""
    while value:
        value, remainder = divmod(value, 58)
        text = _B58[remainder] + text
    return (text or "1").rjust(88, "5")


def _trade_event(slot: int) -> TapeEvent:
    return TapeEvent(
        kind=EventKind.TRADE,
        observed_at=T0.isoformat(),
        provenance=_prov(),
        chain=Chainstamp(slot=slot, signature=_signature(slot), block_time=1786000000),
        body=Trade(
            mint=_mint(),
            wallet=_mint(),
            side=Side.BUY,
            sol_delta_lamports=-1,
            token_delta_raw=2,
        ),
    )


def _watch_event(window: WatchWindow, *, at: datetime) -> TapeEvent:
    return TapeEvent(
        kind=EventKind.WATCH,
        observed_at=at.isoformat(),
        provenance=_prov(),
        body=window,
    )


def _watch_pair(
    mint: str,
    *,
    opened: datetime,
    horizon: timedelta = timedelta(hours=24),
    closed: datetime | None = None,
    reason: WatchClose | None = None,
) -> list[TapeEvent]:
    deadline = opened + horizon
    events = [
        _watch_event(
            WatchWindow(
                mint=mint, opened_at=opened.isoformat(), deadline=deadline.isoformat()
            ),
            at=opened,
        )
    ]
    if closed is not None and reason is not None:
        events.append(
            _watch_event(
                WatchWindow(
                    mint=mint,
                    opened_at=opened.isoformat(),
                    deadline=deadline.isoformat(),
                    closed_at=closed.isoformat(),
                    close_reason=reason,
                ),
                at=closed,
            )
        )
    return events


def _write(root: Path, events: list[TapeEvent]) -> None:
    with TapeWriter(root) as writer:
        writer.write_all(events)


def test_a_clean_tape_reports_full_coverage_and_no_censoring(tmp_path: Path) -> None:
    events = [_trade_event(slot) for slot in range(1, 11)]
    # A Marino-shaped distribution: median near 264s, and a real tail out to two hours.
    for index, seconds in enumerate((120, 200, 264, 900, 7200)):
        events.extend(
            _watch_pair(
                _mint(),
                opened=T0 + timedelta(minutes=index),
                closed=T0 + timedelta(minutes=index, seconds=seconds),
                reason=WatchClose.GRADUATED,
            )
        )
    _write(tmp_path, events)

    result = report(tmp_path, reference_trades=10, now=LATER)

    assert result.health.coverage == 1.0
    assert result.health.censoring_rate == 0.0
    assert result.health.complete is True
    assert result.malformed_lines == 0
    assert result.unresolved_past_deadline == 0
    assert result.events_by_kind == {"trade": 10, "watch": 10}
    assert result.graduation.count == 5
    assert result.graduation.median_seconds == 264.0
    assert result.graduation.max_seconds == 7200.0
    assert result.graduation.tail_present is True
    assert result.sound is True


def test_one_displaced_watch_makes_the_whole_tape_unsound(tmp_path: Path) -> None:
    """Coverage alone is not health: a fully-covered tape can still be truncated."""

    events = [_trade_event(slot) for slot in range(1, 11)]
    events.extend(
        _watch_pair(
            _mint(),
            opened=T0,
            closed=T0 + timedelta(days=1),
            reason=WatchClose.DEADLINE,
        )
    )
    events.extend(
        _watch_pair(
            _mint(),
            opened=T0,
            closed=T0 + timedelta(seconds=166),
            reason=WatchClose.DISPLACED,
        )
    )
    _write(tmp_path, events)

    result = report(tmp_path, reference_trades=10, now=LATER)

    assert result.health.coverage == 1.0
    assert result.health.censoring_rate == 0.5
    assert result.sound is False
    assert result.censoring_reasons == {"displaced": 1}
    assert "informative censoring" in "\n".join(
        line for line in render(result).splitlines() if "displaced" in line
    )


def test_missing_trades_show_up_as_coverage_against_an_independent_count(tmp_path: Path) -> None:
    """The reference must come from outside this tape; a self-count always reports 1.0."""

    _write(tmp_path, [_trade_event(slot) for slot in range(1, 971)])
    result = report(tmp_path, reference_trades=1000, now=LATER)
    assert result.health.coverage == 0.97
    assert result.health.complete is False
    assert result.sound is False


def test_more_trades_than_the_reference_is_surfaced_as_a_warning_not_a_pass(
    tmp_path: Path,
) -> None:
    """Coverage over 1.0 means the reference is stale or the tape double-counted."""

    _write(tmp_path, [_trade_event(slot) for slot in range(1, 11)])
    result = report(tmp_path, reference_trades=8, now=LATER)
    assert result.health.coverage == 1.25
    assert result.coverage_exceeds_reference is True
    assert "WARNING" in render(result)
    # Not a soundness failure: reference counts are approximate, and a tool that fails on an
    # approximation is one people learn to ignore.
    assert result.sound is True


def test_a_watch_that_passed_its_deadline_with_no_close_record_is_named_as_a_bug(
    tmp_path: Path,
) -> None:
    """Silent truncation: the mint left the tape without a censoring reason."""

    events = [_trade_event(1)]
    events.extend(_watch_pair(_mint(), opened=T0))  # open record only
    _write(tmp_path, events)

    # Before the deadline it is simply still running, and we do not accuse.
    running = report(tmp_path, reference_trades=1, now=T0 + timedelta(hours=1))
    assert running.watches_open == 1
    assert running.unresolved_past_deadline == 0
    assert running.sound is True

    stale = report(tmp_path, reference_trades=1, now=LATER)
    assert stale.unresolved_past_deadline == 1
    assert stale.sound is False


def test_an_unreadable_line_is_counted_rather_than_skipped_quietly(tmp_path: Path) -> None:
    """One is an expected crash tail; a hundred is a storage fault, and the difference matters."""

    _write(tmp_path, [_trade_event(1)])
    segment = next(iter(tmp_path.glob("tape-*.jsonl")))
    with segment.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":1,"kind":"tra\n')  # a truncated final line
        handle.write('{"schema_version":999,"kind":"trade"}\n')  # a wrong-version line

    result = report(tmp_path, reference_trades=1, now=LATER)
    assert result.lines == 3
    assert result.malformed_lines == 2
    assert result.health.coverage == 1.0  # the one good trade is still counted
    assert result.sound is False


def test_graduations_with_no_tail_are_flagged_as_the_displacement_signature(
    tmp_path: Path,
) -> None:
    """Marino's median is 4.4 min WITH A TAIL. A tight band reproduces the median and lies."""

    events = [_trade_event(1)]
    for index in range(20):
        events.extend(
            _watch_pair(
                _mint(),
                opened=T0 + timedelta(minutes=index),
                closed=T0 + timedelta(minutes=index, seconds=150 + index * 5),
                reason=WatchClose.GRADUATED,
            )
        )
    _write(tmp_path, events)

    result = report(tmp_path, reference_trades=1, now=LATER)

    assert result.graduation.count == 20
    assert result.graduation.median_seconds is not None
    assert result.graduation.max_seconds is not None
    ratio = result.graduation.max_seconds / result.graduation.median_seconds
    assert ratio < MINIMUM_TAIL_RATIO
    assert result.graduation.tail_present is False
    assert result.sound is False
    assert result.health.complete is True  # the schema alone cannot see this


def test_time_to_graduation_is_measured_on_the_chain_clock_not_the_observer_clock(
    tmp_path: Path,
) -> None:
    """Observer time is lag + truth, and collapses to ~0 when a captured tape is replayed.

    The schema is explicit that chain time is the origin for survival analysis. Here the two
    clocks disagree by two orders of magnitude, and only the chain answer is defensible.
    """

    mint = _mint()
    block_open, block_close = 1786000000, 1786000264
    events = [
        _trade_event(1),
        TapeEvent(
            kind=EventKind.WATCH,
            observed_at=T0.isoformat(),
            provenance=_prov(),
            chain=Chainstamp(slot=10, signature=_signature(10), block_time=block_open),
            body=WatchWindow(
                mint=mint,
                opened_at=T0.isoformat(),
                deadline=(T0 + timedelta(days=1)).isoformat(),
            ),
        ),
        TapeEvent(
            kind=EventKind.WATCH,
            # One observer second later -- a replay ingests the whole capture at once.
            observed_at=(T0 + timedelta(seconds=1)).isoformat(),
            provenance=_prov(),
            chain=Chainstamp(slot=11, signature=_signature(11), block_time=block_close),
            body=WatchWindow(
                mint=mint,
                opened_at=T0.isoformat(),
                deadline=(T0 + timedelta(days=1)).isoformat(),
                closed_at=(T0 + timedelta(seconds=1)).isoformat(),
                close_reason=WatchClose.GRADUATED,
            ),
        ),
    ]
    _write(tmp_path, events)

    result = report(tmp_path, reference_trades=1, now=LATER)

    assert result.graduation.count == 1
    assert result.graduation.chain_timed == 1
    assert result.graduation.observer_timed == 0
    assert result.graduation.median_seconds == 264.0  # not 1.0
    assert result.graduation.median_ratio_to_reference == 1.0  # Marino's 4.4 minutes exactly


def test_a_watch_without_chainstamps_falls_back_to_the_observer_clock_and_says_so(
    tmp_path: Path,
) -> None:
    events = [
        _trade_event(1),
        *_watch_pair(
            _mint(), opened=T0, closed=T0 + timedelta(seconds=90), reason=WatchClose.GRADUATED
        ),
    ]
    _write(tmp_path, events)
    result = report(tmp_path, reference_trades=1, now=LATER)
    assert result.graduation.median_seconds == 90.0
    assert result.graduation.chain_timed == 0
    assert result.graduation.observer_timed == 1


def test_duplicate_event_ids_across_segments_are_reported(tmp_path: Path) -> None:
    event = _trade_event(1)
    _write(tmp_path, [event])
    with TapeWriter(tmp_path, prefix="backfill") as writer:
        writer.write(event)  # a second source, same content hash
    result = report(tmp_path, reference_trades=2, now=LATER)
    assert result.duplicate_event_ids == 1
    assert len(result.segments) == 2


def test_the_cli_exits_non_zero_on_an_unsound_tape_and_prints_machine_readable_json(
    tmp_path: Path, capsys: object
) -> None:
    events = [_trade_event(1)]
    events.extend(
        _watch_pair(
            _mint(), opened=T0, closed=T0 + timedelta(seconds=166), reason=WatchClose.DISPLACED
        )
    )
    _write(tmp_path, events)

    code = main([str(tmp_path), "--reference-trades", "1", "--json", "--now", LATER.isoformat()])
    assert code == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["sound"] is False
    assert payload["censoring_reasons"] == {"displaced": 1}
    assert payload["health"]["censoring_rate"] == 1.0


def test_the_cli_exits_zero_on_a_sound_tape(tmp_path: Path, capsys: object) -> None:
    events = [_trade_event(slot) for slot in range(1, 6)]
    events.extend(
        _watch_pair(
            _mint(), opened=T0, closed=T0 + timedelta(days=1), reason=WatchClose.DEADLINE
        )
    )
    _write(tmp_path, events)
    code = main([str(tmp_path), "--reference-trades", "5", "--now", LATER.isoformat()])
    assert code == 0
    assert "SOUND               True" in capsys.readouterr().out  # type: ignore[attr-defined]
