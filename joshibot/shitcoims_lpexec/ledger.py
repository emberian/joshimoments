"""Every action, one JSONL row, built by one function.

House discipline, from `shitcoims_paperdesk/ledger.py`: two clocks on every row, a `run_id`
on every row, a closed set of row kinds so a typo raises at write time, watch windows around
anything that can be quiet, heartbeats so silence is distinguishable from death, and
`sort_keys` + flush-per-row so `tail -f` shows a live desk.

WHAT THIS FILE ADDS: the reconciliation shape.

The operator's sim2real loop needs to classify every divergence as {bug, modeling error,
parameter gap, irreducible}, and a classification is only possible if the three quantities
were recorded SEPARATELY at the time, by three different mechanisms:

  intended   what the PLANNER decided, before any transaction existed. Our model of the world.
  simulated  what `simulateTransaction` said would happen against live chain state.
  actual     what the chain did. Null until a signature confirms, and null forever in dry-run.

A ledger that records only "we removed 583,896 nosis" cannot tell you whether the plan was
wrong, the simulation was wrong, or the world moved between them. `reconcile_row` writes all
three plus `divergence_class`, which starts as `"pending"` and is only ever set to one of the
four labels by an analyst -- never by this code, because a program that classifies its own
errors classifies them all as irreducible.

The `divergence_class` column existing and being empty is the point. It is a question the
schema forces someone to answer, and the study that eventually reads this file cannot
silently skip it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, TextIO

SCHEMA: Final[str] = "lpexec.v1"

ROW_KINDS: Final[frozenset[str]] = frozenset(
    {
        "plan",  # a planner decision, before any transaction is built
        "build",  # the sidecar returned bytes
        "guard",  # the allowlist verdict, pass or refuse
        "simulate",  # simulateTransaction result, decoded
        "gate",  # the three-gate status at the moment execution was attempted
        "submit",  # a signature left this machine (never written in dry-run)
        "confirm",  # a signature landed
        "reconcile",  # intended vs simulated vs actual
        "rent",  # what a plan owes in account rent, split refundable/not
        "watch_open",
        "watch_close",
        "heartbeat",
        "defect",  # anything that must not silently vanish
    }
)

DIVERGENCE_CLASSES: Final[frozenset[str]] = frozenset(
    {"pending", "none", "bug", "modeling_error", "parameter_gap", "irreducible"}
)

NO_EVENT_CLOCK: Final[str] = "absent:local_row_has_no_source_clock"
VENDOR_CLOCK: Final[str] = "vendor:dlmm.datapi.meteora.ag"
CHAIN_CLOCK: Final[str] = "chain:solana.block_time"


def iso(unix: float) -> str:
    """UTC ISO-8601 with an explicit offset. A naive timestamp is refused downstream."""
    return datetime.fromtimestamp(unix, tz=UTC).isoformat()


def new_run_id() -> str:
    return f"lpx-{int(time.time())}-{os.getpid()}"


@dataclass(frozen=True, slots=True)
class LedgerRow:
    kind: str
    run_id: str
    t_ingest_unix: float
    t_event_unix: float | None = None
    t_event_source: str = NO_EVENT_CLOCK
    fields: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        if self.kind not in ROW_KINDS:
            raise KeyError(f"{self.kind!r} is not a known lpexec row kind")
        out: dict[str, Any] = {
            "schema": SCHEMA,
            "kind": self.kind,
            "run_id": self.run_id,
            "t_ingest": iso(self.t_ingest_unix),
            "t_ingest_unix": self.t_ingest_unix,
            "t_event": iso(self.t_event_unix) if self.t_event_unix is not None else None,
            "t_event_source": self.t_event_source,
        }
        overlap = out.keys() & self.fields.keys()
        if overlap:
            raise KeyError(f"ledger row fields collide with the envelope: {sorted(overlap)}")
        out.update(self.fields)
        return out


class Ledger:
    def __init__(self, root: Path, *, run_id: str | None = None) -> None:
        self.root = root
        self.run_id = run_id or new_run_id()
        self.rows_written = 0
        self._fh: TextIO | None = None
        self._day: str | None = None

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def path_for(self, unix: float) -> Path:
        return self.root / f"lpexec-{datetime.fromtimestamp(unix, tz=UTC):%Y%m%d}.jsonl"

    def write(self, row: LedgerRow) -> None:
        payload = row.to_json()
        day = str(payload["t_ingest"])[:10]
        if day != self._day:
            if self._fh is not None:
                self._fh.close()
            self.root.mkdir(parents=True, exist_ok=True)
            self._fh = self.path_for(row.t_ingest_unix).open("a", encoding="utf-8")
            self._day = day
        assert self._fh is not None
        self._fh.write(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str) + "\n")
        self._fh.flush()
        self.rows_written += 1

    def emit(
        self,
        kind: str,
        *,
        t_ingest_unix: float | None = None,
        t_event_unix: float | None = None,
        t_event_source: str = NO_EVENT_CLOCK,
        **fields: Any,
    ) -> None:
        self.write(
            LedgerRow(
                kind=kind,
                run_id=self.run_id,
                t_ingest_unix=t_ingest_unix if t_ingest_unix is not None else time.time(),
                t_event_unix=t_event_unix,
                t_event_source=t_event_source,
                fields=fields,
            )
        )

    def reconcile(
        self,
        *,
        step: str,
        pool: str,
        position: str | None,
        intended: dict[str, Any],
        simulated: dict[str, Any] | None,
        actual: dict[str, Any] | None,
        divergence_class: str = "pending",
        note: str = "",
        mode: str = "dry_run",
    ) -> None:
        """The row the sim2real loop reads. Three columns, one unanswered question."""
        if divergence_class not in DIVERGENCE_CLASSES:
            raise KeyError(
                f"{divergence_class!r} is not a divergence class; expected one of "
                f"{sorted(DIVERGENCE_CLASSES)}"
            )
        self.emit(
            "reconcile",
            step=step,
            pool=pool,
            position=position,
            mode=mode,
            intended=intended,
            simulated=simulated,
            actual=actual,
            divergence_class=divergence_class,
            note=note,
        )

    def heartbeat(self, *, stage: str, **fields: Any) -> None:
        """Positive evidence of liveness. Absence of rows means nothing without one of these."""
        self.emit("heartbeat", stage=stage, **fields)

    def defect(self, *, reason: str, detail: Any = None) -> None:
        self.emit("defect", reason=reason, detail=detail)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def read_day(root: Path, unix: float | None = None) -> list[dict[str, Any]]:
    """Read back one UTC day of rows. The cap accounting's only source of truth."""
    when = unix if unix is not None else time.time()
    path = root / f"lpexec-{datetime.fromtimestamp(when, tz=UTC):%Y%m%d}.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


@dataclass(frozen=True, slots=True)
class DaySpend:
    """What today has already cost, read from the ledger rather than an in-memory counter.

    An in-memory counter resets when the process restarts, which is precisely the moment a
    per-day cap most needs to hold. Only SUBMITTED rows count: a dry-run plan that was never
    signed did not spend anything, and counting it would let a day of review exhaust the cap.
    """

    sol_lamports: int
    token_usd: float
    transactions: int
    last_submit_unix: float | None


def day_spend(root: Path, unix: float | None = None) -> DaySpend:
    lamports = 0
    usd = 0.0
    count = 0
    last: float | None = None
    for row in read_day(root, unix):
        if row.get("kind") != "submit":
            continue
        count += 1
        lamports += int(row.get("sol_lamports") or 0)
        usd += float(row.get("token_usd") or 0.0)
        stamp = row.get("t_ingest_unix")
        if isinstance(stamp, int | float):
            last = max(last or 0.0, float(stamp))
    return DaySpend(sol_lamports=lamports, token_usd=usd, transactions=count, last_submit_unix=last)
