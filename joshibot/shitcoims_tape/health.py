"""Coverage and censoring audit over a recorded tape.

``tape_health`` in the schema answers two questions: did we see the trades we should have
seen, and was anything censored informatively. This module computes both over real segments
on disk, and adds the third check the methodology standard demands and no published pump.fun
paper ran on itself.

**The truncation check (PROGRAM.md §3 rule 8).** Marino/Lillo measure a median
time-to-graduation of **4.4 minutes with a long tail**. An instrument that closes watches by
displacement reproduces the median perfectly — the fast graduations are all inside its window
— and destroys the tail. So a median near 264 seconds is *not* evidence the instrument is
sound; the tail is. This report prints median, p90 and max side by side and flags
``tail_present`` when the max is at least four times the median, because "my max is about
five minutes" is the actual signature of the bug.

**Unresolved watches are reported separately from closed ones.** A watch whose deadline has
passed with no close record is silent truncation: the mint left the tape without a censoring
reason. That is a recorder bug, it is invisible to ``tape_health`` (which only counts closed
windows), and it is exactly what ``unresolved_past_deadline`` exists to surface.

**Malformed lines are counted, never skipped quietly.** The writer fsyncs on rotate, so a
crash can leave a truncated final line. One is expected after an unclean stop; a hundred means
something else is wrong, and the difference must be visible.

    python -m shitcoims_tape.health TAPE_DIR --reference-trades 12345 [--json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from shitcoims_tape.schema import (
    INFORMATIVE_CLOSES,
    EventKind,
    TapeError,
    TapeEvent,
    TapeHealth,
    WatchClose,
    WatchWindow,
    event_from_json,
    tape_health,
)
from shitcoims_tape.writer import default_tape_root

#: Marino/Naviglio/Tarantelli/Lillo, arXiv:2602.14860: median time-to-graduation 4.4 minutes.
MARINO_MEDIAN_GRADUATION_SECONDS: Final[float] = 264.0

#: Below this ratio of max-to-median there is no tail, which is the displacement signature.
MINIMUM_TAIL_RATIO: Final[float] = 4.0

#: Fewer graduations than this and there is no distribution to judge. Flagging a tape as
#: truncated off three observations would be exactly the overclaiming this report exists to
#: prevent, in the opposite direction.
MINIMUM_TAIL_SAMPLE: Final[int] = 10


@dataclass(slots=True)
class WatchLifecycle:
    """One watch, reassembled from its open record and its close record.

    Both clocks are kept. ``opened_block_time``/``closed_block_time`` come from the WATCH
    events' chainstamps and are the ONLY correct origin for a survival measurement: the
    observer clock adds observer lag (a published pump.fun collector measured median 34.8s,
    p99 151.6s) and collapses to zero entirely when a captured tape is replayed. The observer
    clock is the fallback, and which one was used is reported rather than assumed.
    """

    mint: str
    opened_at: str
    deadline: str
    closed_at: str | None = None
    close_reason: WatchClose | None = None
    opened_block_time: int | None = None
    closed_block_time: int | None = None

    @property
    def resolved(self) -> bool:
        return self.closed_at is not None

    @property
    def chain_timed(self) -> bool:
        return self.opened_block_time is not None and self.closed_block_time is not None

    def duration_seconds(self) -> float | None:
        if self.chain_timed:
            assert self.closed_block_time is not None and self.opened_block_time is not None
            return float(self.closed_block_time - self.opened_block_time)
        if self.closed_at is None:
            return None
        return (
            datetime.fromisoformat(self.closed_at) - datetime.fromisoformat(self.opened_at)
        ).total_seconds()

    def as_window(self) -> WatchWindow:
        return WatchWindow(
            mint=self.mint,
            opened_at=self.opened_at,
            deadline=self.deadline,
            closed_at=self.closed_at,
            close_reason=self.close_reason,
        )


@dataclass(slots=True)
class TapeScan:
    """Everything a pass over the segments established. Facts only; verdicts come after."""

    lines: int = 0
    malformed_lines: int = 0
    events_by_kind: dict[str, int] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)
    mints: set[str] = field(default_factory=set)
    watches: dict[tuple[str, str], WatchLifecycle] = field(default_factory=dict)
    duplicate_event_ids: int = 0
    chain_events_without_block_time: int = 0
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    min_slot: int | None = None
    max_slot: int | None = None
    _event_ids: set[str] = field(default_factory=set)

    @property
    def trades(self) -> int:
        return self.events_by_kind.get(str(EventKind.TRADE), 0)

    def ingest(self, event: TapeEvent) -> None:
        kind = str(event.kind)
        self.events_by_kind[kind] = self.events_by_kind.get(kind, 0) + 1
        source = event.provenance.source
        self.sources[source] = self.sources.get(source, 0) + 1
        event_id = event.event_id
        if event_id in self._event_ids:
            self.duplicate_event_ids += 1
        else:
            self._event_ids.add(event_id)
        if self.first_observed_at is None or event.observed_at < self.first_observed_at:
            self.first_observed_at = event.observed_at
        if self.last_observed_at is None or event.observed_at > self.last_observed_at:
            self.last_observed_at = event.observed_at
        if event.chain is not None:
            if event.chain.block_time is None:
                # Slot still orders exactly and dates approximately (~0.4213 s/slot), so
                # these are usable; a study needing absolute chain time needs the count.
                self.chain_events_without_block_time += 1
            slot = event.chain.slot
            self.min_slot = slot if self.min_slot is None else min(self.min_slot, slot)
            self.max_slot = slot if self.max_slot is None else max(self.max_slot, slot)
        body = event.body
        mint = getattr(body, "mint", None)
        if isinstance(mint, str):
            self.mints.add(mint)
        if event.kind is EventKind.WATCH and isinstance(body, WatchWindow):
            block_time = event.chain.block_time if event.chain is not None else None
            self._ingest_watch(body, block_time)

    def _ingest_watch(self, window: WatchWindow, block_time: int | None) -> None:
        key = (window.mint, window.opened_at)
        lifecycle = self.watches.get(key)
        if lifecycle is None:
            lifecycle = WatchLifecycle(
                mint=window.mint, opened_at=window.opened_at, deadline=window.deadline
            )
            self.watches[key] = lifecycle
        if window.closed_at is None:
            lifecycle.opened_block_time = block_time
            return
        # A close record always wins: the open record is the earlier, weaker statement.
        lifecycle.closed_at = window.closed_at
        lifecycle.close_reason = window.close_reason
        lifecycle.closed_block_time = block_time


@dataclass(frozen=True, slots=True)
class GraduationTiming:
    """The rule-8 instrument check, reported as numbers rather than a verdict."""

    count: int
    median_seconds: float | None
    p90_seconds: float | None
    max_seconds: float | None
    chain_timed: int = 0

    @property
    def judgeable(self) -> bool:
        return self.count >= MINIMUM_TAIL_SAMPLE

    @property
    def observer_timed(self) -> int:
        """Durations measured on the wrong clock. Non-zero means the numbers carry lag."""

        return self.count - self.chain_timed

    @property
    def tail_present(self) -> bool:
        if self.median_seconds is None or self.max_seconds is None or self.median_seconds <= 0:
            return False
        return self.max_seconds / self.median_seconds >= MINIMUM_TAIL_RATIO

    @property
    def median_ratio_to_reference(self) -> float | None:
        if self.median_seconds is None:
            return None
        return self.median_seconds / MARINO_MEDIAN_GRADUATION_SECONDS

    def to_json(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "median_seconds": self.median_seconds,
            "p90_seconds": self.p90_seconds,
            "max_seconds": self.max_seconds,
            "tail_present": self.tail_present,
            "judgeable": self.judgeable,
            "minimum_tail_sample": MINIMUM_TAIL_SAMPLE,
            "chain_timed": self.chain_timed,
            "observer_timed": self.observer_timed,
            "reference_median_seconds": MARINO_MEDIAN_GRADUATION_SECONDS,
            "median_ratio_to_reference": self.median_ratio_to_reference,
        }


@dataclass(frozen=True, slots=True)
class TapeHealthReport:
    """The schema's verdict, plus the audit that explains it."""

    health: TapeHealth
    segments: tuple[str, ...]
    lines: int
    malformed_lines: int
    duplicate_event_ids: int
    chain_events_without_block_time: int
    events_by_kind: dict[str, int]
    sources: dict[str, int]
    distinct_mints: int
    watches_open: int
    unresolved_past_deadline: int
    close_reason_counts: dict[str, int]
    graduation: GraduationTiming
    first_observed_at: str | None
    last_observed_at: str | None
    slot_range: tuple[int | None, int | None]

    @property
    def censoring_reasons(self) -> dict[str, int]:
        return {
            reason: count
            for reason, count in self.close_reason_counts.items()
            if WatchClose(reason) in INFORMATIVE_CLOSES
        }

    @property
    def coverage_exceeds_reference(self) -> bool:
        """More trades on the tape than an independent count says exist.

        Either the reference is stale or the tape double-counted. Reported, but deliberately
        NOT a ``sound`` failure: reference counts are usually approximate, and a tool that
        fails on an approximation is a tool people learn to ignore.
        """

        return self.health.coverage > 1.02

    @property
    def sound(self) -> bool:
        """Stricter than ``TapeHealth.complete``: adds the checks the schema cannot see."""

        return (
            self.health.complete
            and self.malformed_lines == 0
            and self.unresolved_past_deadline == 0
            and (not self.graduation.judgeable or self.graduation.tail_present)
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "health": self.health.to_json(),
            "sound": self.sound,
            "coverage_exceeds_reference": self.coverage_exceeds_reference,
            "segments": list(self.segments),
            "lines": self.lines,
            "malformed_lines": self.malformed_lines,
            "duplicate_event_ids": self.duplicate_event_ids,
            "chain_events_without_block_time": self.chain_events_without_block_time,
            "events_by_kind": dict(sorted(self.events_by_kind.items())),
            "sources": dict(sorted(self.sources.items())),
            "distinct_mints": self.distinct_mints,
            "watches_open": self.watches_open,
            "unresolved_past_deadline": self.unresolved_past_deadline,
            "close_reason_counts": dict(sorted(self.close_reason_counts.items())),
            "censoring_reasons": dict(sorted(self.censoring_reasons.items())),
            "graduation": self.graduation.to_json(),
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "slot_range": list(self.slot_range),
        }


def segment_paths(root: Path, *, pattern: str = "*.jsonl") -> tuple[Path, ...]:
    if root.is_file():
        return (root,)
    if not root.is_dir():
        return ()
    return tuple(sorted(root.glob(pattern)))


def read_events(paths: Iterable[Path]) -> Iterator[TapeEvent | None]:
    """Yield one item per non-blank line: the event, or None when the line is unreadable."""

    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    yield None
                    continue
                try:
                    yield event_from_json(payload)
                except (TapeError, KeyError, TypeError, ValueError):
                    yield None


def scan(paths: Sequence[Path]) -> TapeScan:
    result = TapeScan()
    for event in read_events(paths):
        result.lines += 1
        if event is None:
            result.malformed_lines += 1
            continue
        result.ingest(event)
    return result


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(round(fraction * (len(ordered) - 1)), len(ordered) - 1)
    return ordered[index]


def graduation_timing(scanned: TapeScan) -> GraduationTiming:
    graduated = [
        lifecycle
        for lifecycle in scanned.watches.values()
        if lifecycle.close_reason is WatchClose.GRADUATED
    ]
    durations = [
        seconds
        for lifecycle in graduated
        if (seconds := lifecycle.duration_seconds()) is not None
    ]
    if not durations:
        return GraduationTiming(count=0, median_seconds=None, p90_seconds=None, max_seconds=None)
    return GraduationTiming(
        count=len(durations),
        median_seconds=float(statistics.median(durations)),
        p90_seconds=_percentile(durations, 0.9),
        max_seconds=max(durations),
        chain_timed=sum(1 for lifecycle in graduated if lifecycle.chain_timed),
    )


def report(
    root: Path,
    *,
    reference_trades: int,
    pattern: str = "*.jsonl",
    now: datetime | None = None,
) -> TapeHealthReport:
    """Scan a tape directory (or one segment) and produce the full audit."""

    paths = segment_paths(root, pattern=pattern)
    scanned = scan(paths)
    lifecycles = list(scanned.watches.values())
    windows = [lifecycle.as_window() for lifecycle in lifecycles]
    close_counts: dict[str, int] = {}
    for lifecycle in lifecycles:
        if lifecycle.close_reason is not None:
            key = str(lifecycle.close_reason)
            close_counts[key] = close_counts.get(key, 0) + 1
    moment = now
    unresolved = 0
    for lifecycle in lifecycles:
        if lifecycle.resolved:
            continue
        # An unresolved watch is only a *bug* once its deadline has passed; before that it is
        # simply still running. Without a clock we cannot tell, so we do not accuse.
        if moment is not None and datetime.fromisoformat(lifecycle.deadline) <= moment:
            unresolved += 1
    return TapeHealthReport(
        health=tape_health(
            observed_trades=scanned.trades,
            reference_trades=reference_trades,
            watches=windows,
        ),
        segments=tuple(str(path) for path in paths),
        lines=scanned.lines,
        malformed_lines=scanned.malformed_lines,
        duplicate_event_ids=scanned.duplicate_event_ids,
        chain_events_without_block_time=scanned.chain_events_without_block_time,
        events_by_kind=dict(scanned.events_by_kind),
        sources=dict(scanned.sources),
        distinct_mints=len(scanned.mints),
        watches_open=sum(1 for lifecycle in lifecycles if not lifecycle.resolved),
        unresolved_past_deadline=unresolved,
        close_reason_counts=close_counts,
        graduation=graduation_timing(scanned),
        first_observed_at=scanned.first_observed_at,
        last_observed_at=scanned.last_observed_at,
        slot_range=(scanned.min_slot, scanned.max_slot),
    )


def render(result: TapeHealthReport) -> str:
    health = result.health
    lines = [
        f"segments            {len(result.segments)}",
        f"lines               {result.lines} ({result.malformed_lines} malformed)",
        f"duplicate ids       {result.duplicate_event_ids}",
        f"no block time       {result.chain_events_without_block_time} "
        f"(slot still orders them; absolute chain time is unavailable)",
        f"distinct mints      {result.distinct_mints}",
        "events              "
        + ", ".join(f"{kind}={count}" for kind, count in sorted(result.events_by_kind.items())),
        "sources             "
        + ", ".join(f"{name}={count}" for name, count in sorted(result.sources.items())),
        f"observed window     {result.first_observed_at} .. {result.last_observed_at}",
        f"slot range          {result.slot_range[0]} .. {result.slot_range[1]}",
        "",
        f"coverage            {health.coverage:.4f} "
        f"({health.observed_trades}/{health.reference_trades} trades)",
        f"watches closed      {health.watches_closed} (open now {result.watches_open})",
        f"censoring rate      {health.censoring_rate:.4f} "
        f"({health.watches_informatively_censored} informative)",
        "close reasons       "
        + (
            ", ".join(f"{reason}={count}" for reason, count in sorted(result.close_reason_counts.items()))
            or "none"
        ),
        f"unresolved past dl  {result.unresolved_past_deadline}",
        "",
        f"graduations         n={result.graduation.count} "
        f"median={_fmt(result.graduation.median_seconds)}s "
        f"p90={_fmt(result.graduation.p90_seconds)}s "
        f"max={_fmt(result.graduation.max_seconds)}s",
        f"timed on            chain={result.graduation.chain_timed} "
        f"observer={result.graduation.observer_timed} "
        f"(observer time is lag + truth, and zero on a replay)",
        f"tail present        {result.graduation.tail_present} "
        + (
            f"(reference median {MARINO_MEDIAN_GRADUATION_SECONDS:.0f}s, with a long tail)"
            if result.graduation.judgeable
            else f"(n < {MINIMUM_TAIL_SAMPLE}: no distribution to judge, not counted against SOUND)"
        ),
        "",
        f"schema complete     {health.complete}",
        f"SOUND               {result.sound}",
    ]
    if result.coverage_exceeds_reference:
        lines.insert(
            -2,
            "WARNING             the tape holds more trades than the independent reference: "
            "either the reference is stale or events were double-counted",
        )
    if not result.sound:
        lines.append("")
        lines.extend(_explain(result))
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _explain(result: TapeHealthReport) -> list[str]:
    notes: list[str] = ["why not sound:"]
    if result.health.coverage < 0.98:
        notes.append(
            f"  coverage {result.health.coverage:.4f} is below 0.98 against the independent "
            f"reference count; trades are missing from the tape"
        )
    for reason, count in sorted(result.censoring_reasons.items()):
        notes.append(
            f"  {count} watch(es) closed {reason}: informative censoring, so any survival "
            f"estimate over this tape is truncated and its rate is a lower bound"
        )
    if result.malformed_lines:
        notes.append(
            f"  {result.malformed_lines} unreadable line(s); one is an expected crash tail, "
            f"many are a writer or storage fault"
        )
    if result.unresolved_past_deadline:
        notes.append(
            f"  {result.unresolved_past_deadline} watch(es) passed their deadline with no "
            f"close record: silent truncation, and a recorder bug -- expire() is not running"
        )
    if result.graduation.judgeable and not result.graduation.tail_present:
        notes.append(
            f"  graduation times have no tail (max/median = "
            f"{(result.graduation.max_seconds or 0) / (result.graduation.median_seconds or 1):.1f}x, "
            f"want >= {MINIMUM_TAIL_RATIO:.0f}x): the displacement signature -- the fast "
            f"graduations are inside the window and the slow ones were never seen"
        )
    return notes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shitcoims_tape.health",
        description="Coverage and censoring audit over a recorded tape.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=None,
        help="tape directory or one segment (default: $JOSHIBOT_TAPE_DIR or ./tape)",
    )
    parser.add_argument(
        "--reference-trades",
        type=int,
        required=True,
        help="independently counted trades for the same window; coverage is meaningless "
        "against a count derived from this tape",
    )
    parser.add_argument("--pattern", default="*.jsonl", help="segment glob (default: *.jsonl)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--now",
        default=None,
        help="ISO-8601 instant used to decide which open watches are past their deadline "
        "(default: now, so the check is never silently skipped)",
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else default_tape_root()
    moment = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if moment is not None and moment.tzinfo is None:
        parser.error("--now must carry a timezone")
    result = report(root, reference_trades=args.reference_trades, pattern=args.pattern, now=moment)
    print(json.dumps(result.to_json(), indent=2, sort_keys=True) if args.json else render(result))
    return 0 if result.sound else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
