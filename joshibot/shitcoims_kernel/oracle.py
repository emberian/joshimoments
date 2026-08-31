"""Run the Lean kernel as a subprocess and ask it. Authoritative, slow.

Used by the parity tests to check the Python fast path, and available to any study that would
rather be right than quick. If the binary is missing this raises rather than falling back to
the Python implementation: a silent fallback would make the parity test compare the fast path
against itself and pass vacuously, which is precisely the failure mode these tests exist to
catch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import TracebackType

_BINARY = Path(__file__).resolve().parent.parent / "kernel" / ".lake" / "build" / "bin" / "joshi-oracle"


class OracleUnavailable(RuntimeError):
    """The Lean oracle binary is not built or has died. Tests may legitimately SKIP on this."""


class OracleRejected(RuntimeError):
    """A live oracle answered `err`. This is a REAL failure and must never be skipped.

    Kept distinct from `OracleUnavailable` because conflating them reproduces the exact defect
    the trials test was written to prevent: a caller that skips on "oracle unavailable" would
    also skip when a working binary rejects a query it should have answered, reporting a
    broken dispatch as green. Demonstrated by adversarial audit against a binary whose
    `predcount` arity had drifted.
    """


class LeanOracle:
    """A live handle on the oracle process, speaking one query per line."""

    def __init__(self, binary: Path | None = None) -> None:
        self._path = binary or _BINARY
        if not self._path.exists():
            raise OracleUnavailable(
                f"{self._path} is missing; build it with `cd kernel && lake build joshi-oracle`"
            )
        self._proc = subprocess.Popen(
            [str(self._path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def _ask(self, query: str) -> str:
        proc = self._proc
        if proc.stdin is None or proc.stdout is None:
            raise OracleUnavailable("oracle process has no pipes")
        proc.stdin.write(query + "\n")
        proc.stdin.flush()
        reply = proc.stdout.readline().strip()
        if reply == "":
            raise OracleUnavailable(f"oracle produced no reply to: {query!r}")
        if reply == "err":
            raise OracleRejected(f"oracle rejected a query it should answer: {query!r}")
        return reply

    def sell_out(self, token_raw: int, sol_lamports: int, amount: int) -> int:
        return int(self._ask(f"sell {token_raw} {sol_lamports} {amount}"))

    def accepts(self, token_raw: int, sol_lamports: int, amount: int, floor: int) -> bool:
        return self._ask(f"accepts {token_raw} {sol_lamports} {amount} {floor}") == "1"

    def close(self) -> None:
        proc = self._proc
        if proc.stdin is not None:
            proc.stdin.close()
        proc.wait(timeout=10)

    def __enter__(self) -> LeanOracle:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
