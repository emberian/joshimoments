"""The DLMM swap oracle: the deployed mainnet program, asked directly. Authoritative, slow.

This is the SVM analogue of `shitcoims_kernel/oracle.py`, and it holds the same line for the
same reason. When it cannot answer it RAISES. It never returns a computed default, a
best-effort estimate, or a zero, because a parity test whose oracle quietly degrades into an
approximation is comparing the fast path against itself and passing vacuously -- a failure
this project has already made once and caught.

Three failure modes, kept apart on purpose:

  * `OracleUnavailable` -- the harness cannot run at all (no snapshot, no bindings, no ELF).
    A caller may legitimately SKIP on this.
  * `OracleRejected` -- the deployed program REFUSED this swap. That is a real answer about
    the semantics, not an outage, and a caller that skips on it is reporting a live
    disagreement as green.
  * `OracleOutOfRange` -- the swap is real and would execute, but this snapshot does not
    carry enough bin arrays to answer it. Distinct from both: the snapshot is too small, and
    silently truncating the swap at the edge of the window would produce a WRONG number that
    looks right.

The unit of work is `answer(state, request) -> Answer`: pool state in, pool state and amount
out. The state going in is a snapshot of real mainnet accounts; the state coming out is
whatever the real program wrote.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


class OracleUnavailable(RuntimeError):
    """The harness cannot run. Tests may legitimately SKIP on this."""


class OracleRejected(RuntimeError):
    """The deployed program refused the swap. A REAL answer; must never be skipped."""


class OracleOutOfRange(RuntimeError):
    """The swap would leave the snapshot's bin window. Never answered by truncation."""


@dataclass(frozen=True, slots=True)
class SwapRequest:
    """A swap input, complete enough to be reproducible.

    `unix_timestamp` is not bookkeeping: the DLMM dynamic fee decays against the clock, so a
    swap is not fully specified without it. Leaving it out was measured to change
    `amount_out` while leaving the bin arithmetic exact.
    """

    amount_in: int
    swap_for_y: bool
    unix_timestamp: int | None = None
    slot: int | None = None
    min_amount_out: int = 0
    persist: bool = False
    """Chain from the previous answer's state instead of the snapshot. For forward replay."""
    host_fee_in: str | None = None
    """Referral account, when the recorded swap supplied one. It takes 20% of the protocol
    fee, so omitting a recorded one silently overstates `protocol_fee` by exactly that cut."""


@dataclass(frozen=True, slots=True)
class Answer:
    """What the deployed program did."""

    amount_out: int
    active_id_before: int
    active_id_after: int
    reserve_x_after: int
    reserve_y_after: int
    protocol_fee_x_after: int
    protocol_fee_y_after: int
    fee: int
    protocol_fee: int
    host_fee: int
    start_bin_id: int
    end_bin_id: int
    bin_diff: dict[int, dict[str, int]]
    compute_units: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def _require_backend() -> Any:
    try:
        import svm
    except ImportError as exc:  # pragma: no cover - environment failure
        raise OracleUnavailable(
            "solders.litesvm is not importable; install with "
            "`uv pip install solders` into kernel_svm/.venv"
        ) from exc
    return svm


class DlmmOracle:
    """A loaded pool snapshot that answers swap questions by running the real program.

    Reusable and cheap to ask repeatedly: each `answer()` re-funds the synthetic user and
    swaps from the SAME snapshot state, so questions are independent rather than compounding.
    """

    def __init__(self, snapshot: dict[str, Any]) -> None:
        svm = _require_backend()
        required = {"pool", "lb_pair", "accounts", "programs", "bin_arrays", "block_time"}
        missing = required - set(snapshot)
        if missing:
            raise OracleUnavailable(f"snapshot is missing {sorted(missing)}")
        try:
            self._svm = svm.DlmmSvm(snapshot)
        except svm.HarnessUnsupported as exc:
            raise OracleUnavailable(f"snapshot cannot be driven by this harness: {exc}") from exc
        self._backend = svm
        self.snapshot = snapshot
        self.pool = snapshot["pool"]
        self.bin_step = snapshot["lb_pair"]["bin_step"]

    # -- constructors --------------------------------------------------------------------

    @classmethod
    def from_snapshot_file(cls, path: str | Path) -> DlmmOracle:
        path = Path(path)
        if not path.exists():
            raise OracleUnavailable(
                f"{path} is missing; capture one with "
                f"`.venv/bin/python snapshot.py <pool>`"
            )
        return cls(json.loads(path.read_text()))

    @classmethod
    def from_fixture(cls, path: str | Path) -> tuple[DlmmOracle, SwapRequest, dict[str, int]]:
        """Load a recorded mainnet swap: the oracle at its pre-state, the input, the truth."""
        path = Path(path)
        if not path.exists():
            raise OracleUnavailable(f"fixture {path} is missing")
        fixture = json.loads(path.read_text())
        request = SwapRequest(
            amount_in=fixture["input"]["amount_in"],
            swap_for_y=fixture["input"]["swap_for_y"],
            unix_timestamp=fixture["input"]["unix_timestamp"],
            slot=fixture["input"].get("slot"),
            host_fee_in=fixture["input"].get("host_fee_in"),
        )
        return cls(fixture["snapshot"]), request, fixture["observed"]

    @staticmethod
    def fixtures() -> list[Path]:
        return sorted(FIXTURE_DIR.glob("*.json"))

    # -- the question --------------------------------------------------------------------

    def answer(self, request: SwapRequest) -> Answer:
        """Run the swap on the real program. Raises rather than guessing."""
        if request.amount_in <= 0:
            raise ValueError("amount_in must be positive")
        try:
            result = self._svm.swap(
                request.amount_in,
                swap_for_y=request.swap_for_y,
                min_amount_out=request.min_amount_out,
                unix_timestamp=request.unix_timestamp,
                slot=request.slot,
                persist=request.persist,
                host_fee_in=request.host_fee_in,
            )
        except self._backend.HarnessUnsupported as exc:
            raise OracleUnavailable(f"{self.pool}: {exc}") from exc
        except self._backend.SwapFailed as exc:
            # A revert is only a semantic answer if the snapshot's bin window is walled in by
            # genuinely uninitialised arrays. Otherwise the program may simply have run past
            # what we loaded, and reporting that as "the program refuses this swap" would be
            # a harness limitation dressed up as a finding.
            if not self.snapshot.get("window_complete", False):
                raise OracleOutOfRange(
                    f"{self.pool}: swap reverted, but the snapshot's bin window "
                    f"{self.snapshot.get('bin_window_requested')} is not bounded by "
                    "uninitialised arrays, so this cannot be distinguished from the window "
                    f"being too small. Re-snapshot with a larger --bin-window. ({exc})"
                ) from exc
            raise OracleRejected(
                f"{self.pool}: deployed program refused amount_in={request.amount_in} "
                f"swap_for_y={request.swap_for_y}: {exc}"
            ) from exc

        event = result.event
        if event is None:
            raise OracleUnavailable(
                f"{self.pool}: swap executed but emitted no decodable Swap event; the "
                "harness cannot confirm what the program did and will not report a number "
                "it has not corroborated"
            )
        if result.amount_out != event["amount_out"]:
            raise OracleUnavailable(
                f"{self.pool}: token account delta {result.amount_out} disagrees with the "
                f"program's own event {event['amount_out']}; the harness is misreading state"
            )

        after = result.after
        return Answer(
            amount_out=result.amount_out,
            active_id_before=result.before.active_id,
            active_id_after=after.active_id,
            reserve_x_after=after.reserve_x,
            reserve_y_after=after.reserve_y,
            protocol_fee_x_after=after.protocol_fee_x,
            protocol_fee_y_after=after.protocol_fee_y,
            fee=event["fee"],
            protocol_fee=event["protocol_fee"],
            host_fee=event["host_fee"],
            start_bin_id=event["start_bin_id"],
            end_bin_id=event["end_bin_id"],
            bin_diff=result.bin_diff,
            compute_units=result.compute_units,
        )

def load_all_fixtures() -> list[tuple[Path, DlmmOracle, SwapRequest, dict[str, int]]]:
    out = []
    for path in DlmmOracle.fixtures():
        oracle, request, observed = DlmmOracle.from_fixture(path)
        out.append((path, oracle, request, observed))
    return out
