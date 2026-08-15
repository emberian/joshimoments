"""The one ledger. Every row run_id-stamped, two-clocked, and built by one function.

ONE FILE, ONE SHAPE
-------------------
All three books write to ``state/paperdesk/ledger-YYYYMMDD.jsonl`` (UTC day, cut on OUR
clock, because a row's day must not depend on a clock the source may not have). Every row
carries ``row`` (its kind), ``run_id``, ``book``, ``t_ingest``, ``t_event`` and
``t_event_source``. There is no second file to join against and no per-book variant to
forget: a report over the desk is a scan of one stream.

THE CLOSE ROW IS BUILT IN EXACTLY ONE PLACE
-------------------------------------------
:func:`close_row` is the only constructor of a close record. This is not tidiness. An
earlier drain path in ``shitcoims_scalper.run_shadow`` emitted a *partial* close --
decision_id, mint and pnl, no ``spend_lamports`` -- and the report divided ten positions'
P&L by one position's spend and printed **-151%**. The row looked like data, so nothing
raised. Every close row from this module carries every field whatever ended the position,
including the fields that are zero because of how it ended.

CENSORING IS A FIELD, NOT AN OMISSION
-------------------------------------
``studies/RESULT_board_entry.md`` reported +21.77% at 8h. The same cohort, repriced with
the censored 96% marked out at the last price observed at-or-before the trigger, is
**-12.24%**. The difference is entirely that the first number was computed on survivors.
So a close row carries, always:

``pnl_lamports``
    The headline. Marked out at the last observation at-or-before the trigger when the
    position left observation for any reason other than evidence of death.
``pnl_pessimistic_lamports``
    The same position scored with departure-from-observation as a TOTAL LOSS.
``censored`` / ``censor_reason``
    Whether the headline number rests on a mark-out, and which
    :class:`shitcoims_tape.schema.WatchClose` reason applies.

Reporting only the first is the +21.77% error. Reporting only the second throws away
every position that merely graduated off a board while perfectly alive. The desk reports
both, and the spread between them is the size of the assumption.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from shitcoims_tape.schema import PropensityRecord, WatchClose

__all__ = [
    "LEDGER_DIR",
    "Ledger",
    "LedgerRow",
    "close_row",
    "iso",
    "new_run_id",
]

LEDGER_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "state" / "paperdesk"

#: Row kinds. Kept as a closed set so a typo becomes a KeyError at write time rather than
#: a row nothing ever queries.
ROW_KINDS: Final[frozenset[str]] = frozenset(
    {
        "decision",      # a propensity-logged decision, taken or not
        "fill",          # an entry filled at the next observation after the decision
        "mark",          # periodic mark-to-market of an open position
        "close",         # a position closed; see close_row
        "watch_open",    # a source observation window opened
        "watch_close",   # ... and why it closed
        "heartbeat",     # the desk is alive; per-book counters
        "gate",          # a book-level decision rule evaluated (toll: eta * D vs VR)
        "accrual",       # LP fees accrued from observed flow crossing a paper range
        "rebalance",     # a one-sided redeploy
        "defect",        # something the desk could not price and refused to guess at
        # The operator's own gestures, mirrored out of state/hunches.jsonl so that the
        # ledger alone tells the whole story of a position -- who asked for it, in what
        # words, and which entry gates disagreed. The hunch tape remains the durable
        # original (it is fsynced by the CLI before the desk has heard of it); this row is
        # the desk's acknowledgement, carrying its own ingest clock against the gesture's.
        "hunch",
        # A claim with a horizon and no capital behind it: the down / up / watch kinds,
        # recorded, falsified early if the market says so, and SCORED at the horizon.
        # Separate from `close` because a close row must have a spend to divide by and an
        # expectation has none -- exactly the -151% partial-row failure, refused up front.
        "expectation",
    }
)


def iso(unix: float) -> str:
    """UTC ISO-8601 with an explicit offset. Naive timestamps are refused downstream."""
    return datetime.fromtimestamp(unix, tz=UTC).isoformat()


def new_run_id() -> str:
    """Every row carries one. Without it, rows from different code and different
    thresholds pool silently in one file and get averaged together."""
    return f"pd-{int(time.time())}-{os.getpid()}"


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One row, two clocks. ``t_event`` is null WITH A REASON when the source has none.

    The firehose carries no event clock in any payload -- that is a property of the
    vendor, established by inspection, not a gap in our collector. Recording
    ``t_event_source="absent:vendor_payload_carries_no_event_clock"`` keeps that fact in
    the data, so a later analyst cannot mistake our ingest clock for an event clock and
    compute a latency that is really a poll interval.
    """

    row: str
    run_id: str
    book: str
    t_ingest_unix: float
    t_event_unix: float | None = None
    t_event_source: str = "absent:local_row_has_no_source_clock"
    fields: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        if self.row not in ROW_KINDS:
            raise KeyError(f"unknown ledger row kind {self.row!r}")
        out: dict[str, Any] = {
            "row": self.row,
            "run_id": self.run_id,
            "book": self.book,
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


def close_row(
    *,
    run_id: str,
    book: str,
    position_id: str,
    decision_id: str,
    key: str,
    label: str | None,
    opened_at_unix: float,
    closed_at_unix: float,
    t_event_unix: float | None,
    t_event_source: str,
    spend_lamports: int,
    proceeds_lamports: int,
    priority_fees_lamports: int,
    pnl_lamports: int,
    pnl_pessimistic_lamports: int,
    exit_reason: str,
    censored: bool,
    censor_reason: str | None,
    mark_source: str,
    observations: int,
    entry_price: float,
    exit_price: float,
    peak_price: float,
    extra: dict[str, Any] | None = None,
) -> LedgerRow:
    """THE close-row builder. Every field, every time, whatever ended the position.

    ``mark_source`` is the audit trail for the headline number:

    ``observed``
        Filled against reserves actually observed at-or-after the trigger. The only
        unqualified number.
    ``last_observed_before_trigger``
        The position left observation; marked at the last price seen at-or-before the
        trigger, NEVER after. This is the +21.77% -> -12.24% correction made structural.
    ``total_loss``
        Evidence of death, not merely of departure. Proceeds are zero and the two P&L
        figures agree.
    """
    if censored and censor_reason is None:
        raise ValueError("a censored close must record why it was censored")
    if mark_source not in {"observed", "last_observed_before_trigger", "total_loss"}:
        raise ValueError(f"unknown mark_source {mark_source!r}")
    if spend_lamports <= 0:
        raise ValueError("a close row without a spend cannot be divided by; refuse it here")
    fields: dict[str, Any] = {
        "position_id": position_id,
        "decision_id": decision_id,
        "key": key,
        "label": label,
        "opened_at": iso(opened_at_unix),
        "opened_at_unix": opened_at_unix,
        "closed_at": iso(closed_at_unix),
        "closed_at_unix": closed_at_unix,
        "holding_seconds": max(0.0, closed_at_unix - opened_at_unix),
        "spend_lamports": spend_lamports,
        "proceeds_lamports": proceeds_lamports,
        "priority_fees_lamports": priority_fees_lamports,
        "pnl_lamports": pnl_lamports,
        "pnl_pessimistic_lamports": pnl_pessimistic_lamports,
        "net_return": pnl_lamports / spend_lamports,
        "net_return_pessimistic": pnl_pessimistic_lamports / spend_lamports,
        "exit_reason": exit_reason,
        "censored": censored,
        "censor_reason": censor_reason,
        "mark_source": mark_source,
        "observations": observations,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "peak_price": peak_price,
    }
    if extra:
        collide = fields.keys() & extra.keys()
        if collide:
            raise KeyError(f"close-row extras collide with the contract: {sorted(collide)}")
        fields.update(extra)
    return LedgerRow(
        row="close",
        run_id=run_id,
        book=book,
        t_ingest_unix=closed_at_unix,
        t_event_unix=t_event_unix,
        t_event_source=t_event_source,
        fields=fields,
    )


class Ledger:
    """Append-only JSONL writer, one file per UTC day, plus resumable desk state.

    Flushes per row so ``tail -f`` shows a live desk. Rotates on OUR clock: a row whose
    day depended on a source clock would land in yesterday's file whenever a source has
    no clock at all, which is most of them.
    """

    def __init__(self, root: Path | None = None, *, run_id: str | None = None) -> None:
        self.root = root or LEDGER_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or new_run_id()
        self._day: str | None = None
        self._fh: Any = None
        self.rows_written = 0

    # ---------------------------------------------------------------- writing

    def path_for(self, unix: float) -> Path:
        return self.root / f"ledger-{datetime.fromtimestamp(unix, tz=UTC):%Y%m%d}.jsonl"

    def write(self, row: LedgerRow) -> None:
        payload = row.to_json()
        day = payload["t_ingest"][:10]
        if day != self._day:
            if self._fh is not None:
                self._fh.close()
            self._fh = self.path_for(row.t_ingest_unix).open("a")
            self._day = day
        self._fh.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
        self._fh.flush()
        self.rows_written += 1

    def emit(
        self,
        row: str,
        book: str,
        *,
        t_ingest_unix: float | None = None,
        t_event_unix: float | None = None,
        t_event_source: str = "absent:local_row_has_no_source_clock",
        **fields: Any,
    ) -> None:
        self.write(
            LedgerRow(
                row=row,
                run_id=self.run_id,
                book=book,
                t_ingest_unix=t_ingest_unix if t_ingest_unix is not None else time.time(),
                t_event_unix=t_event_unix,
                t_event_source=t_event_source,
                fields=fields,
            )
        )

    def decision(
        self,
        *,
        book: str,
        record: PropensityRecord,
        t_ingest_unix: float,
        t_event_unix: float | None,
        t_event_source: str,
        **fields: Any,
    ) -> None:
        """Log a decision through the REAL tape contract type.

        Constructing :class:`shitcoims_tape.schema.PropensityRecord` here rather than
        emitting a dict shaped like one is the anti-mirror gate: if the contract changes,
        this raises instead of silently writing a record no OPE run can read.
        """
        self.emit(
            "decision",
            book,
            t_ingest_unix=t_ingest_unix,
            t_event_unix=t_event_unix,
            t_event_source=t_event_source,
            **record.to_json(),
            **fields,
        )

    def watch_open(self, book: str, *, source: str, opened_at_unix: float, **fields: Any) -> None:
        self.emit("watch_open", book, t_ingest_unix=opened_at_unix, source=source, **fields)

    def watch_close(
        self,
        book: str,
        *,
        source: str,
        opened_at_unix: float,
        closed_at_unix: float,
        reason: WatchClose,
        events: int,
        **fields: Any,
    ) -> None:
        """Close a source's observation window with a REAL WatchClose reason.

        ``OBSERVER_LOST`` and ``DISPLACED`` are informative censoring; the report counts
        them separately because a survival estimate that treats them as benign is
        reporting a truncated rate as a full-horizon one.
        """
        self.emit(
            "watch_close",
            book,
            t_ingest_unix=closed_at_unix,
            source=source,
            opened_at=iso(opened_at_unix),
            closed_at=iso(closed_at_unix),
            seconds=max(0.0, closed_at_unix - opened_at_unix),
            reason=str(reason),
            informative=reason in {WatchClose.DISPLACED, WatchClose.OBSERVER_LOST},
            events=events,
            **fields,
        )

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self._day = None

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- persistence

    @property
    def state_path(self) -> Path:
        return self.root / "desk-state.json"

    def load_state(self) -> dict[str, Any]:
        """Resume open positions across restarts.

        The operator's complaint was that nothing persists between days. A desk that
        forgets its book every time it restarts is a study with extra steps.
        """
        try:
            with self.state_path.open() as fh:
                loaded = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def save_state(self, state: dict[str, Any]) -> None:
        """Atomic replace: a desk killed mid-write must not lose the whole book."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.root), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(state, fh, separators=(",", ":"), sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.state_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
