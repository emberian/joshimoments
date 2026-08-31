"""Three gates. All required. Absence of any one is dry-run.

Lifted from `shitcoims_sentinel/executor.py::ExecutionGate`, which earned the shape: config
`enabled`, a `--live` argv flag, and a mode-checked arm file whose CONTENTS bind to the
wallet. Three because they fail independently -- a config committed by mistake, a process
started by a supervisor with the wrong argv, and a stale arm file left behind by a previous
session are three different accidents, and none of them alone can sign.

Two additions this package needs and the sentinel does not:

  KEY ABSENCE IS A GATE, not an exception. `~/.thafunds-wallet` may not exist. The desk must
  still plan, simulate and print on that machine -- that IS the review workflow -- so a
  missing key file is reported as one more open gate rather than raised. It reads
  "key file ... is absent (dry-run only)" and every other gate is still evaluated, so the
  operator sees the whole checklist at once instead of one error at a time.

  THE ARM VALUE NAMES THE PACKAGE. `lpexec:<pubkey>`, not `shitcoims:<pubkey>`. Arming the
  sentinel must not arm the LP executor, and one wallet's arm file must never satisfy
  another's. Copying an arm file between desks now fails a string comparison.

`status()` accumulates every failure rather than short-circuiting, because a report that
says "and four other things are also wrong" is what stops an operator fixing one gate at a
time and being surprised on the fifth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import LpExecConfig
from .secrets import SecretError, read_secret_file

ARM_PREFIX = "lpexec"


@dataclass(frozen=True, slots=True)
class GateStatus:
    live: bool
    failures: tuple[str, ...]

    @property
    def mode(self) -> str:
        return "LIVE" if self.live else "DRY_RUN"

    def describe(self) -> str:
        if self.live:
            return "LIVE: all gates open"
        return "DRY RUN: " + "; ".join(self.failures)


class ExecutionGate:
    def __init__(self, config: LpExecConfig, *, cli_live: bool) -> None:
        self.config = config
        self.cli_live = cli_live

    @property
    def expected_arm_value(self) -> str:
        return f"{ARM_PREFIX}:{self.config.wallet_address}"

    def status(self) -> GateStatus:
        failures: list[str] = []
        if not self.config.execution.enabled:
            failures.append("execution.enabled is false")
        if not self.cli_live:
            failures.append("process was not started with --live")

        try:
            arm = read_secret_file(self.config.execution.arm_file, required=False)
        except SecretError as exc:
            arm = None
            failures.append(f"arm file is unreadable ({exc})")
        if arm != self.expected_arm_value:
            failures.append("lpexec arm file is absent or does not match this wallet")

        key_path = self.config.secret_key_file
        if not key_path.exists():
            failures.append(f"key file {key_path} is absent (dry-run only)")
        else:
            try:
                read_secret_file(key_path, required=True)
            except SecretError as exc:
                failures.append(f"key file is unusable ({exc})")

        return GateStatus(live=not failures, failures=tuple(failures))


def write_arm(path: Path, value: str) -> None:
    """Create the arm file at 0600 without a umask race, then fsync it.

    `os.open` with an explicit mode rather than `write_text` + `chmod`: between those two
    calls the file exists at whatever the umask allowed, and `read_secret_file` would have
    accepted it in that window.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
