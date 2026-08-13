"""Watch discipline: the censoring state machine.

This is the methodological heart of the recorder, and it exists because of one measured
failure. A published pump.fun collector polled a *top-50-newest* endpoint, so every token
fell out of view after a median ~2.77 minutes because **other tokens launched**. Its
"24-hour graduation rate" was therefore a ~6-minute graduation rate, and the resulting base
rate was wrong by a factor nobody could see from the output. That is displacement censoring:
the censoring time is correlated with the outcome (fast graduations are inside the window,
slow ones are not), so it is *informative*, and no survival estimator can repair it after
the fact.

The rule this module enforces:

    A WATCH CLOSES ON A CLOCK OR ON A TERMINAL OUTCOME. NEVER BECAUSE ATTENTION MOVED ON.

Three mechanisms make that structural rather than aspirational:

1. **Capacity pressure falls on admission, never on eviction.** The default
   :class:`AdmissionPolicy` is ``REFUSE``: at capacity, an *existing* watch is never touched,
   so every admitted mint runs to its clock deadline or a terminal outcome. Eviction requires
   constructing the registry with ``AdmissionPolicy.DISPLACE`` explicitly — you cannot reach
   it by accident, and it logs a warning every time it fires.

2. **Nothing is dropped silently.** A refusal at capacity still emits a ``WatchWindow``, and
   it emits it *already closed* with :data:`WatchClose.DISPLACED`. So the truncation of the
   sampling frame is a counted row on the tape, ``tape_health`` reports a non-zero censoring
   rate, and ``TapeHealth.complete`` goes False. A study reading that tape cannot mistake it
   for a full-horizon sample.

3. **There is exactly one removal path.** ``_close`` is the only code that removes a mint
   from the live set, and it always writes a close record first. A watch cannot leave the
   registry without a reason on the tape.

The horizon carries its own guard. Marino/Lillo measure a **median time-to-graduation of
4.4 minutes with a long tail**, so an instrument whose horizon is minutes reproduces the
median and destroys the tail — the exact signature of a truncated collector. Horizons below
:data:`MINIMUM_SAFE_HORIZON` therefore require an explicit ``allow_short_horizon=True``, which
makes "I only watched for six minutes" a statement someone had to write down.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from shitcoims_tape.schema import (
    INFORMATIVE_CLOSES,
    Chainstamp,
    EventKind,
    Provenance,
    TapeEvent,
    WatchClose,
    WatchWindow,
)

LOGGER = logging.getLogger("shitcoims.tape.watch")

#: Marino/Lillo: median time-to-graduation 4.4 min *with a tail*. Anything shorter than an
#: hour cannot observe the tail, and a rate measured over it is not a graduation rate.
MINIMUM_SAFE_HORIZON: Final[timedelta] = timedelta(hours=1)
DEFAULT_HORIZON: Final[timedelta] = timedelta(hours=24)

#: 0 means unbounded. A bound exists because memory and Helius credits are finite; making it
#: explicit is what lets the refusal be *counted* instead of emerging as a silent drop.
DEFAULT_CAPACITY: Final[int] = 20_000


class AdmissionPolicy(StrEnum):
    """What happens when a new mint arrives and the registry is full."""

    #: Refuse the newcomer. No existing watch is disturbed, so no admitted mint is ever
    #: displacement-censored. The refusal itself is recorded as DISPLACED, because the
    #: sampling frame *was* truncated by attention capacity even though no watch was cut short.
    REFUSE = "refuse"

    #: Evict the oldest open watch and close it DISPLACED. Reproduces the published
    #: collector's bug on purpose; only ever correct when replaying that instrument.
    DISPLACE = "displace"


class AdmissionResult(StrEnum):
    ADMITTED = "admitted"
    ALREADY_WATCHED = "already_watched"
    REFUSED_AT_CAPACITY = "refused_at_capacity"


@dataclass(frozen=True, slots=True)
class WatchDecision:
    """The outcome of asking to watch a mint, and the record that was written for it."""

    result: AdmissionResult
    window: WatchWindow
    displaced: tuple[WatchWindow, ...] = ()

    @property
    def admitted(self) -> bool:
        return self.result is AdmissionResult.ADMITTED


@dataclass(frozen=True, slots=True)
class WatchStats:
    opened: int
    refused_at_capacity: int
    duplicate_opens: int
    closed_by_reason: dict[str, int]
    open_now: int

    @property
    def informatively_censored(self) -> int:
        return sum(
            count
            for reason, count in self.closed_by_reason.items()
            if WatchClose(reason) in INFORMATIVE_CLOSES
        )

    def to_json(self) -> dict[str, object]:
        return {
            "opened": self.opened,
            "refused_at_capacity": self.refused_at_capacity,
            "duplicate_opens": self.duplicate_opens,
            "closed_by_reason": dict(sorted(self.closed_by_reason.items())),
            "open_now": self.open_now,
            "informatively_censored": self.informatively_censored,
        }


EventSink = Callable[[TapeEvent], object]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WatchRegistry:
    """The live set of watched mints, with every open and close written to the tape.

    ``sink`` receives a ``WATCH`` :class:`TapeEvent` for every state change: one *open*
    record when a mint is admitted (``closed_at`` is None) and one *close* record when it
    leaves (``closed_at`` and ``close_reason`` set). Reconstruction downstream groups the two
    by ``(mint, opened_at)``; an open record with no matching close is an *unresolved* watch,
    which :mod:`shitcoims_tape.health` reports separately because a watch left unresolved past
    its deadline is silent truncation and therefore a recorder bug.
    """

    def __init__(
        self,
        sink: EventSink,
        *,
        source: str = "recorder.watch",
        horizon: timedelta = DEFAULT_HORIZON,
        capacity: int = DEFAULT_CAPACITY,
        admission: AdmissionPolicy = AdmissionPolicy.REFUSE,
        allow_short_horizon: bool = False,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if horizon <= timedelta(0):
            raise ValueError("watch horizon must be positive")
        if horizon < MINIMUM_SAFE_HORIZON and not allow_short_horizon:
            raise ValueError(
                f"a watch horizon of {horizon} cannot observe the graduation tail "
                f"(median 4.4 min with a long tail); pass allow_short_horizon=True to state "
                f"that truncation deliberately"
            )
        if capacity < 0:
            raise ValueError("capacity must not be negative")
        self._sink = sink
        self._source = source
        self._horizon = horizon
        self._capacity = capacity
        self._admission = admission
        self._clock = clock
        self._open: dict[str, WatchWindow] = {}
        self._opened = 0
        self._refused = 0
        self._duplicate_opens = 0
        self._closed_by_reason: dict[str, int] = {}

    # -- public surface ------------------------------------------------------------

    def __contains__(self, mint: str) -> bool:
        return mint in self._open

    def __len__(self) -> int:
        return len(self._open)

    def __iter__(self) -> Iterator[WatchWindow]:
        return iter(tuple(self._open.values()))

    @property
    def horizon(self) -> timedelta:
        return self._horizon

    @property
    def admission(self) -> AdmissionPolicy:
        return self._admission

    def window(self, mint: str) -> WatchWindow | None:
        return self._open.get(mint)

    def open(
        self, mint: str, *, now: datetime | None = None, chain: Chainstamp | None = None
    ) -> WatchDecision:
        """Start watching ``mint`` until a clock deadline. Idempotent per mint.

        ``chain`` is the on-chain moment the watch is anchored to. It matters: the two
        clocks are not the same, observer lag is real (a published pump.fun collector
        measured median 34.8s, p99 151.6s), and a time-to-graduation measured on the
        observer clock is that lag plus the truth. Survival analysis needs chain time.
        """

        moment = self._moment(now)
        existing = self._open.get(mint)
        if existing is not None:
            self._duplicate_opens += 1
            return WatchDecision(AdmissionResult.ALREADY_WATCHED, existing)

        displaced: tuple[WatchWindow, ...] = ()
        if self._capacity and len(self._open) >= self._capacity:
            if self._admission is AdmissionPolicy.REFUSE:
                return self._refuse(mint, moment, chain)
            displaced = self._displace_oldest(moment)

        window = WatchWindow(
            mint=mint,
            opened_at=moment.isoformat(),
            deadline=(moment + self._horizon).isoformat(),
        )
        self._open[window.mint] = window
        self._opened += 1
        self._emit(window, moment, chain)
        return WatchDecision(AdmissionResult.ADMITTED, window, displaced)

    def close(
        self,
        mint: str,
        reason: WatchClose,
        *,
        now: datetime | None = None,
        chain: Chainstamp | None = None,
    ) -> WatchWindow | None:
        """Close one watch. Returns None when the mint was not being watched."""

        if reason is WatchClose.DISPLACED:
            # Displacement is never a caller's decision. It is produced only by the
            # capacity path, which is the one place where "attention moved on" is the
            # literal truth; letting arbitrary code stamp it would launder a dropped watch.
            raise ValueError(
                "DISPLACED is reserved for the capacity path; a caller-initiated close is "
                "OPERATOR, and a terminal outcome is GRADUATED or DIED"
            )
        return self._close(mint, reason, self._moment(now), chain)

    def graduated(
        self, mint: str, *, now: datetime | None = None, chain: Chainstamp | None = None
    ) -> WatchWindow | None:
        return self._close(mint, WatchClose.GRADUATED, self._moment(now), chain)

    def died(
        self, mint: str, *, now: datetime | None = None, chain: Chainstamp | None = None
    ) -> WatchWindow | None:
        return self._close(mint, WatchClose.DIED, self._moment(now), chain)

    def expire(self, *, now: datetime | None = None) -> tuple[WatchWindow, ...]:
        """Close every watch whose wall-clock deadline has passed. The benign censoring.

        This must be called on a timer by whatever drives the recorder. If it is never
        called, watches accumulate unresolved and the tape looks like an unbounded-horizon
        observation that it is not — which ``health`` flags as ``unresolved_past_deadline``.
        """

        moment = self._moment(now)
        due = [
            mint
            for mint, window in self._open.items()
            if datetime.fromisoformat(window.deadline) <= moment
        ]
        return tuple(
            closed
            for mint in due
            # A deadline is an observer fact, not a chain event: no chainstamp exists.
            if (closed := self._close(mint, WatchClose.DEADLINE, moment, None)) is not None
        )

    def shutdown(
        self, *, now: datetime | None = None, reason: WatchClose = WatchClose.OBSERVER_LOST
    ) -> tuple[WatchWindow, ...]:
        """Close everything still open. Default reason is the honest one for a crash/stop.

        ``OBSERVER_LOST`` is informative censoring and is counted as such. A clean operator
        stop should pass ``WatchClose.OPERATOR``; both are recorded, neither is silent.
        """

        moment = self._moment(now)
        return tuple(
            closed
            for mint in tuple(self._open)
            if (closed := self._close(mint, reason, moment, None)) is not None
        )

    @property
    def stats(self) -> WatchStats:
        return WatchStats(
            opened=self._opened,
            refused_at_capacity=self._refused,
            duplicate_opens=self._duplicate_opens,
            closed_by_reason=dict(self._closed_by_reason),
            open_now=len(self._open),
        )

    # -- internals -----------------------------------------------------------------

    def _moment(self, now: datetime | None) -> datetime:
        moment = now if now is not None else self._clock()
        if moment.tzinfo is None:
            raise ValueError("watch timestamps must carry a timezone")
        return moment.astimezone(UTC)

    def _refuse(
        self, mint: str, moment: datetime, chain: Chainstamp | None
    ) -> WatchDecision:
        """Record the refusal as a zero-length DISPLACED watch, then decline.

        The mint was never observed, so there is no survival information to censor — but the
        *frame* was truncated by attention capacity, and that is precisely the bias the
        published collector hid. Writing it as DISPLACED puts it in ``tape_health``'s
        informative-censoring count, so a downstream estimate cannot claim completeness.
        """

        window = WatchWindow(
            mint=mint,
            opened_at=moment.isoformat(),
            deadline=(moment + self._horizon).isoformat(),
            closed_at=moment.isoformat(),
            close_reason=WatchClose.DISPLACED,
        )
        self._refused += 1
        self._count(WatchClose.DISPLACED)
        LOGGER.warning(
            "watch capacity %s reached; refusing a new mint and recording it DISPLACED "
            "(refusals so far: %s)",
            self._capacity,
            self._refused,
        )
        self._emit(window, moment, chain)
        return WatchDecision(AdmissionResult.REFUSED_AT_CAPACITY, window)

    def _displace_oldest(self, moment: datetime) -> tuple[WatchWindow, ...]:
        oldest = min(self._open.values(), key=lambda window: (window.opened_at, window.mint))
        LOGGER.warning(
            "AdmissionPolicy.DISPLACE evicted an open watch: this is informative censoring "
            "and makes any survival estimate over this tape truncated"
        )
        closed = self._close(oldest.mint, WatchClose.DISPLACED, moment, None)
        return () if closed is None else (closed,)

    def _close(
        self, mint: str, reason: WatchClose, moment: datetime, chain: Chainstamp | None
    ) -> WatchWindow | None:
        window = self._open.pop(mint, None)
        if window is None:
            return None
        closed = WatchWindow(
            mint=window.mint,
            opened_at=window.opened_at,
            deadline=window.deadline,
            closed_at=moment.isoformat(),
            close_reason=reason,
        )
        self._count(reason)
        self._emit(closed, moment, chain)
        return closed

    def _count(self, reason: WatchClose) -> None:
        key = str(reason)
        self._closed_by_reason[key] = self._closed_by_reason.get(key, 0) + 1

    def _emit(
        self, window: WatchWindow, moment: datetime, chain: Chainstamp | None
    ) -> None:
        self._sink(
            TapeEvent(
                kind=EventKind.WATCH,
                observed_at=moment.isoformat(),
                provenance=Provenance(source=self._source, fetched_at=moment.isoformat()),
                body=window,
                chain=chain,
            )
        )
