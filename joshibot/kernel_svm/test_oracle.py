"""The oracle held to mainnet, and to its own refusal contract.

Two jobs. The first is the headline: every recorded fixture must replay through the deployed
program to EXACT agreement with what mainnet did -- amount out, fee, protocol fee, bin range,
to the lamport. The second is less obvious and matters more over time: the oracle must RAISE
when it cannot answer. An oracle that degrades into a plausible number would let a future
parity test compare the Lean model against a guess and pass, and nobody would find out.

These tests need `kernel_svm/.venv`:

    cd kernel_svm && .venv/bin/python -m pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle import (
    Answer,
    DlmmOracle,
    OracleOutOfRange,
    OracleRejected,
    OracleUnavailable,
    SwapRequest,
)

HERE = Path(__file__).resolve().parent
FIXTURES = sorted((HERE / "fixtures").glob("*.json"))
SNAPSHOTS = sorted((HERE / "snapshots").glob("*.json"))


_NO_FIXTURES = (
    "no fixtures recorded; capture some with "
    "`.venv/bin/python capture.py <pool> --repeat 5 --save` "
    "or `.venv/bin/python stream.py <pool> --save`"
)


def _require_fixtures() -> None:
    if not FIXTURES:
        pytest.skip(_NO_FIXTURES)


def _cases() -> list:
    """Parametrisation that stays VISIBLE when the corpus is empty.

    `parametrize` over an empty list collects zero tests, and a run with zero tests reports
    green -- the parity suite would announce success while checking nothing against mainnet.
    An explicit skipped placeholder makes an empty corpus show up as a skip in the summary
    instead of as silence.
    """
    if not FIXTURES:
        return [pytest.param(None, marks=pytest.mark.skip(reason=_NO_FIXTURES), id="no-fixtures")]
    return list(FIXTURES)


@pytest.mark.parametrize("path", _cases(), ids=lambda p: p.stem if p else "none")
def test_recorded_mainnet_swap_replays_exactly(path: Path) -> None:
    """The deployed program, re-run on the pre-state, reproduces mainnet to the lamport."""
    oracle, request, observed = DlmmOracle.from_fixture(path)
    answer = oracle.answer(request)

    assert answer.amount_out == observed["amount_out"]
    assert answer.fee == observed["fee"]
    assert answer.protocol_fee == observed["protocol_fee"]
    assert answer.start_bin_id == observed["start_bin_id"]
    assert answer.end_bin_id == observed["end_bin_id"]


@pytest.mark.parametrize("path", _cases(), ids=lambda p: p.stem if p else "none")
def test_replay_is_deterministic(path: Path) -> None:
    """Same question, same answer. A drifting oracle is not an oracle."""
    oracle, request, _ = DlmmOracle.from_fixture(path)
    assert oracle.answer(request).to_json() == oracle.answer(request).to_json()


@pytest.mark.parametrize("path", _cases(), ids=lambda p: p.stem if p else "none")
def test_answers_do_not_compound(path: Path) -> None:
    """Every question is asked of the snapshot state, not of the previous answer's state."""
    oracle, request, observed = DlmmOracle.from_fixture(path)
    for _ in range(3):
        answer = oracle.answer(request)
        assert answer.amount_out == observed["amount_out"]
        assert answer.active_id_before == observed["start_bin_id"]


@pytest.mark.parametrize("path", _cases(), ids=lambda p: p.stem if p else "none")
def test_timestamp_is_a_real_input(path: Path) -> None:
    """Dropping the timestamp must change the answer, not be quietly tolerated.

    The dynamic fee decays against the clock. This test exists because the harness first
    replayed with the wrong clock and produced bin arithmetic that was exact to the lamport
    alongside an `amount_out` that was wrong -- the most dangerous shape of near-miss, and
    one a coarser test would have called success.
    """
    oracle, request, observed = DlmmOracle.from_fixture(path)
    shifted = SwapRequest(
        amount_in=request.amount_in,
        swap_for_y=request.swap_for_y,
        unix_timestamp=(request.unix_timestamp or 0) - 86_400,
        slot=request.slot,
    )
    answer = oracle.answer(shifted)
    # The gross amount leaving the bins is fee-independent, so it stays put; the fee moves.
    assert answer.amount_out + answer.fee == observed["amount_out"] + observed["fee"]


def test_missing_snapshot_raises_rather_than_returning_a_default() -> None:
    with pytest.raises(OracleUnavailable):
        DlmmOracle.from_snapshot_file(HERE / "snapshots" / "does-not-exist.json")


def test_malformed_snapshot_raises() -> None:
    with pytest.raises(OracleUnavailable):
        DlmmOracle({"pool": "x"})


def test_zero_amount_is_rejected_not_answered() -> None:
    _require_fixtures()
    oracle, _, _ = DlmmOracle.from_fixture(FIXTURES[0])
    with pytest.raises(ValueError):
        oracle.answer(SwapRequest(amount_in=0, swap_for_y=True))


def test_unanswerable_swap_raises_rather_than_returning_a_number() -> None:
    """A swap far past available liquidity must raise, never return a truncated amount.

    Which exception is itself the assertion: `OracleRejected` when the snapshot's bin window
    is walled in by uninitialised arrays (so the revert is what mainnet would do), and
    `OracleOutOfRange` when it is not (so the harness cannot honestly tell). What must never
    happen is a returned `Answer`.
    """
    _require_fixtures()
    oracle, request, _ = DlmmOracle.from_fixture(FIXTURES[0])
    with pytest.raises((OracleRejected, OracleOutOfRange)):
        oracle.answer(
            SwapRequest(
                amount_in=10**18,
                swap_for_y=request.swap_for_y,
                unix_timestamp=request.unix_timestamp,
                slot=request.slot,
            )
        )


def test_fixture_files_pin_what_mainnet_did() -> None:
    """A fixture without an observed answer is a fixture that cannot fail. Reject it."""
    _require_fixtures()
    for path in FIXTURES:
        fixture = json.loads(path.read_text())
        observed = fixture["observed"]
        assert observed["amount_out"] > 0, f"{path.name} pins no outcome"
        assert fixture["input"]["amount_in"] > 0
        assert fixture["input"]["unix_timestamp"], f"{path.name} has no timestamp"
        assert fixture["snapshot"]["pool"] == fixture["pool"]


def test_answer_is_a_full_post_state() -> None:
    """The oracle returns pool state after, not merely a scalar."""
    _require_fixtures()
    oracle, request, _ = DlmmOracle.from_fixture(FIXTURES[0])
    answer = oracle.answer(request)
    assert isinstance(answer, Answer)
    for field in ("reserve_x_after", "reserve_y_after", "active_id_after", "bin_diff"):
        assert getattr(answer, field) is not None
    assert answer.bin_diff, "a swap that moved tokens must have moved at least one bin"
