"""End-to-end: captured transactions -> recorder process -> segments on disk -> health.

This is the only test that exercises the whole instrument, and it is the one that would
notice a component that is individually green but wired together wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from solders.keypair import Keypair

from shitcoims_tape import EventKind, WatchClose
from shitcoims_tape.cli import build_parser, main
from shitcoims_tape.health import report
from shitcoims_tape.recorder import WRAPPED_SOL_MINT
from tests.test_tape_recorder import _create_values, _trade_values, pump_logs, transaction

SIGS = ["5" * 88, "4" * 88, "3" * 88, "2" * 88]


def _mint() -> str:
    return str(Keypair().pubkey())


def _capture(path: Path) -> tuple[str, str]:
    """A launch, two trades and a graduation for one mint, as raw transactions."""

    mint, creator, curve = _mint(), _mint(), _mint()
    buyer = _mint()
    rows: list[dict[str, Any]] = [
        transaction(
            pump_logs(
                ("CreateEvent", _create_values(mint, creator, curve)),
                ("TradeEvent", _trade_values(mint, creator, is_buy=True, token_amount=42)),
            ),
            slot=1000,
            signature=SIGS[0],
        ),
        transaction(
            pump_logs(("TradeEvent", _trade_values(mint, buyer, is_buy=True))),
            slot=1001,
            signature=SIGS[1],
        ),
        transaction(
            pump_logs(("TradeEvent", _trade_values(mint, buyer, is_buy=False))),
            slot=1002,
            signature=SIGS[2],
        ),
        transaction(
            pump_logs(
                (
                    "CompleteEvent",
                    {
                        "user": creator,
                        "mint": mint,
                        "bonding_curve": curve,
                        "timestamp": 1786000264,
                        "quote_mint": WRAPPED_SOL_MINT,
                    },
                )
            ),
            slot=1003,
            signature=SIGS[3],
            block_time=1786000264,  # Marino's median, 4.4 minutes after the launch block
        ),
    ]
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    return mint, curve


def test_a_replayed_capture_produces_a_tape_that_passes_its_own_health_check(
    tmp_path: Path, capsys: object
) -> None:
    capture = tmp_path / "captured.jsonl"
    mint, curve = _capture(capture)
    tape = tmp_path / "tape"

    code = main(["--from-jsonl", str(capture), "--tape-dir", str(tape)])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["run"]["transactions"] == 4
    assert payload["run"]["gaps"] == []
    assert payload["run"]["credits_spent"] == 0  # a replay costs nothing
    assert payload["recorder"]["launches"] == 1
    assert payload["recorder"]["trades"] == 3
    assert payload["recorder"]["graduations"] == 1
    assert payload["watches"]["closed_by_reason"] == {"graduated": 1}
    assert payload["writer"]["events_written"] > 0
    assert payload["writer"]["fsyncs"] >= 1  # the segment is durable before the process exits

    # 3 trades on the tape, checked against an independent count of the capture file.
    result = report(tape, reference_trades=3)
    assert result.health.coverage == 1.0
    assert result.health.censoring_rate == 0.0
    assert result.health.complete is True
    assert result.malformed_lines == 0
    assert result.sound is True
    assert result.events_by_kind["launch"] == 1
    assert result.events_by_kind["trade"] == 3
    assert result.events_by_kind["reserve"] >= 4
    assert result.distinct_mints >= 1
    # The replay ingests everything within a millisecond of wall clock, so a graduation time
    # measured on the observer clock would read ~0. The chain clock says 264 seconds.
    assert result.graduation.chain_timed == 1
    assert result.graduation.median_seconds == 264.0

    # The watch opened at the launch and closed as GRADUATED; nothing was displaced.
    watches = [
        json.loads(line)
        for segment in tape.glob("*.jsonl")
        for line in segment.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == str(EventKind.WATCH)
    ]
    assert [body["body"].get("close_reason") for body in watches] == [
        None,
        str(WatchClose.GRADUATED),
    ]
    assert all(body["body"]["mint"] == mint for body in watches)
    assert curve  # the curve address is what attributed the reserve readings


def test_the_recorder_never_opens_a_socket_unless_live_is_named(tmp_path: Path) -> None:
    """A recorder that connects on a forgotten flag spends credits and reads a secret."""

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--tape-dir", str(tmp_path)])  # neither source chosen
    with pytest.raises(SystemExit, match="requires --helius-key"):
        main(["--live", "--tape-dir", str(tmp_path)])


def test_a_short_horizon_is_refused_by_the_process_too(tmp_path: Path) -> None:
    capture = tmp_path / "captured.jsonl"
    _capture(capture)
    with pytest.raises(ValueError, match="graduation tail"):
        main(
            [
                "--from-jsonl",
                str(capture),
                "--tape-dir",
                str(tmp_path / "tape"),
                "--horizon-hours",
                "0.1",
            ]
        )


def test_explicitly_watched_mints_are_opened_at_start_up(tmp_path: Path, capsys: object) -> None:
    capture = tmp_path / "captured.jsonl"
    _capture(capture)
    extra = [_mint(), _mint()]
    code = main(
        [
            "--from-jsonl",
            str(capture),
            "--tape-dir",
            str(tmp_path / "tape"),
            "--watch-mint",
            extra[0],
            "--watch-mint",
            extra[1],
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["watches"]["opened"] == 3  # two explicit, one from the launch
    # The two that never resolved are closed OPERATOR on a clean stop, never left dangling.
    assert payload["watches"]["closed_by_reason"]["operator"] == 2


def test_capacity_pressure_shows_up_on_the_tape_as_displaced(
    tmp_path: Path, capsys: object
) -> None:
    """The whole point: a truncated sampling frame is a counted row, not a silent drop."""

    capture = tmp_path / "captured.jsonl"
    _capture(capture)
    tape = tmp_path / "tape"
    code = main(
        [
            "--from-jsonl",
            str(capture),
            "--tape-dir",
            str(tape),
            "--capacity",
            "1",
            "--watch-mint",
            _mint(),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["watches"]["refused_at_capacity"] == 1
    assert payload["watches"]["closed_by_reason"]["displaced"] == 1

    result = report(tape, reference_trades=3)
    assert result.censoring_reasons == {"displaced": 1}
    assert result.health.complete is False
    assert result.sound is False
