"""The watch ledger: what makes "no swaps" distinguishable from "not watching".

A tape with no rows for a pool between 14:00 and 15:00 says one of two completely different
things, and nothing in the rows themselves tells you which. Inside a watch window, absence is
evidence of zero flow. Outside one, absence is no information at all. The measured cost of
conflating them is in SWARM.md Track B: a wallet-indexed tape recorded structural zeros for
every (mint, hour) the watched wallets ignored, so every rate ratio came out ``+inf`` or
``0/0``, and 64% of tape mints had exactly one leg with a median observed span of 0.00 hours.

This module reuses :class:`shitcoims_tape.schema.WatchWindow` verbatim rather than
reimplementing it. Its field is named ``mint``; a pool address goes there. The field validates
as a 32-byte base58 address, which is exactly what a pool address is, so the constraint holds
and only the name is stretched — recorded here rather than papered over, because the mint-index
assumption is real and this cluster is pool-indexed.

**Gaps.** A poll that arrives more than ``gap_factor`` x the poll interval after the previous
one means the collector was not looking. That interval is emitted as its own row and the
window is closed with :attr:`WatchClose.OBSERVER_LOST`, which
``shitcoims_tape.schema.INFORMATIVE_CLOSES`` already marks as informative censoring — so the
existing ``tape_health`` counter picks it up without a new concept. A study whose analysis
window overlaps a gap must **exclude** the window, never zero-fill it; at the ~1-per-3.4-hours
disconnect rate measured on the live collector, a 60-minute window intersecting one is routine.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from shitcoims_tape.schema import WatchClose, WatchWindow

#: A poll later than this multiple of the interval is a gap, not jitter.
DEFAULT_GAP_FACTOR: Final[float] = 2.0


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class Gap:
    """An interval during which this pool was not being polled."""

    pool: str
    started_at: str
    ended_at: str
    seconds: float
    reason: str
    poll_interval_seconds: float

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "gap",
            "pool": self.pool,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "seconds": self.seconds,
            "reason": self.reason,
            "poll_interval_seconds": self.poll_interval_seconds,
        }


@dataclass
class PoolWatch:
    """The open/close ledger and the gap detector for one pool.

    ``deadline`` is a real clock deadline, per the schema's rule that a watch closes on a
    clock or on a terminal outcome and never because attention moved elsewhere. Displacement
    censoring is the failure mode that silently turned a published 24-hour graduation rate into
    a 6-minute one, and it cannot happen here as long as the deadline is the only expiry.
    """

    pool: str
    opened_at: datetime
    deadline: datetime
    poll_interval: float
    gap_factor: float = DEFAULT_GAP_FACTOR
    last_poll_at: datetime | None = None
    closed_at: datetime | None = None
    close_reason: WatchClose | None = None
    gaps: list[Gap] = field(default_factory=list)
    polls: int = 0

    @property
    def gap_threshold(self) -> timedelta:
        return timedelta(seconds=self.poll_interval * self.gap_factor)

    def window(self) -> WatchWindow:
        """The real tape ``WatchWindow``, constructed and therefore validated."""

        return WatchWindow(
            mint=self.pool,
            opened_at=_iso(self.opened_at),
            deadline=_iso(self.deadline),
            closed_at=_iso(self.closed_at) if self.closed_at is not None else None,
            close_reason=self.close_reason,
        )

    def open_row(self) -> dict[str, Any]:
        return {
            "kind": "watch_open",
            "pool": self.pool,
            "poll_interval_seconds": self.poll_interval,
            "gap_factor": self.gap_factor,
            "window": self.window().to_json(),
        }

    def heartbeat_row(self, now: datetime, *, watched: Sequence[str] = ()) -> dict[str, Any]:
        """A row that says "the observer was here and saw nothing", on a fixed clock.

        The gap rows above are *exception* rows: they appear only when the observer was late,
        failed or absent. That leaves the healthy-and-quiet case writing nothing at all, so a
        wedged process and a dead-quiet pool produce identical tapes — the same conflation this
        module's docstring exists to refuse, one level up. This row closes it: inside a watch
        window, a heartbeat beside no swaps is positive evidence of zero flow, and a missing
        heartbeat is positive evidence of no observer.

        ``watched`` records which addresses the poll actually covered, so a tape reader can
        tell a pool-address-only sweep from one that also swept the vaults.
        """

        return {
            "kind": "heartbeat",
            "pool": self.pool,
            "at": _iso(now),
            "polls": self.polls,
            "gaps": len(self.gaps),
            "poll_interval_seconds": self.poll_interval,
            "watched_addresses": list(watched),
        }

    def renew(self, now: datetime, horizon: timedelta) -> None:
        """Start a fresh window at ``now``. The caller closes the old one first.

        A watch window is a claim bounded by a real clock deadline. A daemon that outlives its
        deadline would otherwise keep polling under a window whose ``closed_at`` lands *after*
        its own ``deadline`` — a window that never expired and never renewed, which is
        precisely the displacement-censoring shape ``WatchWindow`` was built to make
        impossible. Renewal keeps the claim honest across an arbitrarily long run.
        """

        self.opened_at = now
        self.deadline = now + horizon
        self.closed_at = None
        self.close_reason = None
        self.polls = 0
        self.gaps = []

    def note_poll(self, now: datetime) -> Gap | None:
        """Record a successful poll; return a :class:`Gap` when the previous one was too old.

        The first poll of a process never reports a gap against nothing — resuming after a
        stopped process is a *different* gap, seeded by :meth:`seed_from_cursor`, and
        conflating the two would report a gap of unbounded length every cold start.
        """

        previous = self.last_poll_at
        self.last_poll_at = now
        self.polls += 1
        if previous is None:
            return None
        elapsed = now - previous
        if elapsed <= self.gap_threshold:
            return None
        gap = Gap(
            pool=self.pool,
            started_at=_iso(previous),
            ended_at=_iso(now),
            seconds=elapsed.total_seconds(),
            reason="poll_interval_exceeded",
            poll_interval_seconds=self.poll_interval,
        )
        self.gaps.append(gap)
        return gap

    def seed_from_cursor(self, last_seen: datetime | None, now: datetime) -> Gap | None:
        """Account for the time between a previous run's last poll and this run's start."""

        if last_seen is None:
            return None
        elapsed = now - last_seen
        if elapsed <= self.gap_threshold:
            self.last_poll_at = last_seen
            return None
        gap = Gap(
            pool=self.pool,
            started_at=_iso(last_seen),
            ended_at=_iso(now),
            seconds=elapsed.total_seconds(),
            reason="collector_not_running",
            poll_interval_seconds=self.poll_interval,
        )
        self.gaps.append(gap)
        return gap

    def note_failure(self, now: datetime, detail: str) -> Gap:
        """A poll that raised. The pool was not observed, and that is recorded as such."""

        started = self.last_poll_at or self.opened_at
        gap = Gap(
            pool=self.pool,
            started_at=_iso(started),
            ended_at=_iso(now),
            seconds=(now - started).total_seconds(),
            reason=f"poll_failed:{detail}",
            poll_interval_seconds=self.poll_interval,
        )
        self.gaps.append(gap)
        return gap

    def close(self, now: datetime, reason: WatchClose) -> dict[str, Any]:
        self.closed_at = now
        self.close_reason = reason
        return {
            "kind": "watch_close",
            "pool": self.pool,
            "polls": self.polls,
            "gaps": len(self.gaps),
            "gap_seconds": round(sum(g.seconds for g in self.gaps), 3),
            "window": self.window().to_json(),
        }

    @property
    def is_informatively_censored(self) -> bool:
        return self.window().is_informatively_censored
