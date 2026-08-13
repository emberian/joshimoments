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
    """The Lean oracle binary is not built. Run `lake build joshi-oracle` in kernel/."""


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
        if reply == "" or reply == "err":
            raise OracleUnavailable(f"oracle rejected or died on: {query!r}")
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
