"""Mint-indexed panel collection: a frame of mints in, a recorded tape out, on a hard budget.

Every signal lane so far came back UNRESOLVABLE for the same reason — the only chain data on
disk was a two-address *wallet* watchlist, and a wallet-indexed tape records a structural zero
for every ``(mint, hour)`` the watched wallets ignored. This module is the other index: pick
mints first, then read each mint's own history.

Three things here are not conveniences.

**The frame is a separate, declared object.** ``FrameMint`` rows are written to disk before a
single credit is spent, so "how were these mints chosen" is auditable after the fact rather
than reconstructed from the tape's contents. Selecting mints *by outcome* (graduated, high
market cap) is legitimate and cheap, but it is only legitimate if it is written down: a panel
whose selection rule is implicit will be read as a sample of pump.fun, which it is not.

**The observation window is anchored per mint, to its own first transaction.** Paging ``asc``
means page one starts at the mint's creation, so every mint contributes the same
``[launch, launch+W]`` window. The alternative — a fixed transaction count — hands busy mints
a shorter *time* window than quiet ones, which ties the observation window to the very thing
being measured. That is displacement censoring wearing a different hat.

**Truncation is a close reason, never a smaller number.** A mint whose history we read to the
end, or to the end of its window, closes ``DEADLINE`` — a clock stopped us. A mint cut off by
the page cap, a transport error, or the credit budget closes ``OBSERVER_LOST``, which
:data:`~shitcoims_tape.schema.INFORMATIVE_CLOSES` counts, so ``tape_health`` reports a
non-zero censoring rate and no downstream study can read the panel as complete. A mint the
budget never reached at all is written as a zero-length ``DISPLACED`` window: the frame was
truncated by attention capacity, exactly the bias the published pump.fun collector hid.

Read-only. Nothing here signs, submits, or reads a wallet key.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from shitcoims_tape.recorder import (
    CREDITS_PER_TRANSACTION_PAGE,
    CreditBudget,
    TapeRecorder,
)
from shitcoims_tape.schema import (
    EventKind,
    Provenance,
    TapeError,
    TapeEvent,
    WatchClose,
    WatchWindow,
)
from shitcoims_tape.sources import (
    TRUNCATING_STOPS,
    HeliusHistorySource,
    MintHistory,
    run_recorder,
)
from shitcoims_tape.watch import WatchRegistry

LOGGER = logging.getLogger("shitcoims.tape.panel")

#: The default per-mint observation window. One hour is not a round number chosen for looks:
#: it is :data:`~shitcoims_tape.watch.MINIMUM_SAFE_HORIZON`, the shortest horizon that can
#: observe the tail of Marino/Lillo's 4.4-minute median time-to-graduation rather than just
#: reproducing its median.
DEFAULT_WINDOW_SECONDS: Final[int] = 3600

#: Pages per mint. 25 pages is 2,500 transactions and 250 credits — the point past which one
#: hot mint would eat the panel's whole allowance.
DEFAULT_PAGE_CAP: Final[int] = 25


class PanelError(RuntimeError):
    """A panel run could not proceed. Sanitised: never carries a credentialed URL."""


@dataclass(frozen=True, slots=True)
class FrameMint:
    """One row of the sampling frame, with the covariates that were free to observe.

    ``launched_at`` and ``listed_market_cap_usd`` come from the public listing, not from
    chain, and they are recorded here rather than on the tape precisely because they are
    third-party claims. The tape carries what the chain said.
    """

    mint: str
    stratum: str
    launched_at: str | None = None
    listed_complete: bool | None = None
    listed_market_cap_usd: float | None = None
    listed_last_trade_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "stratum": self.stratum,
            "launched_at": self.launched_at,
            "listed_complete": self.listed_complete,
            "listed_market_cap_usd": self.listed_market_cap_usd,
            "listed_last_trade_at": self.listed_last_trade_at,
        }

    @staticmethod
    def from_json(payload: Mapping[str, Any]) -> FrameMint:
        return FrameMint(
            mint=str(payload["mint"]),
            stratum=str(payload["stratum"]),
            launched_at=payload.get("launched_at"),
            listed_complete=payload.get("listed_complete"),
            listed_market_cap_usd=payload.get("listed_market_cap_usd"),
            listed_last_trade_at=payload.get("listed_last_trade_at"),
        )


def write_frame(path: Path, frame: Sequence[FrameMint]) -> int:
    """Persist the frame before spending anything. JSONL, one mint per line."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in frame:
            handle.write(json.dumps(row.to_json(), sort_keys=True, separators=(",", ":")) + "\n")
    return len(frame)


def read_frame(path: Path) -> tuple[FrameMint, ...]:
    rows: list[FrameMint] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(FrameMint.from_json(json.loads(text)))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise PanelError(f"frame line {number} is malformed") from exc
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class MintOutcome:
    """What the panel got for one frame mint, and what stopped it."""

    mint: str
    stratum: str
    history: MintHistory | None
    close_reason: str
    trades: int
    wallets: int

    @property
    def reached(self) -> bool:
        return self.history is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "stratum": self.stratum,
            "close_reason": self.close_reason,
            "trades": self.trades,
            "wallets": self.wallets,
            "history": None if self.history is None else self.history.to_json(),
        }


@dataclass(frozen=True, slots=True)
class PanelReport:
    """The run, in numbers that can be checked against the tape afterwards."""

    started_at: str
    finished_at: str
    frame_size: int
    mints_reached: int
    mints_displaced: int
    mints_truncated: int
    transactions: int
    events_written: int
    credits_spent: int
    credit_limit: int
    window_seconds: int
    page_cap: int
    gaps: tuple[str, ...]
    outcomes: tuple[MintOutcome, ...]
    #: The recorder's own tally of everything it chose not to write, and why. Carried on the
    #: report because a panel that silently discards a whole class of event -- a quote-mint
    #: spelling, an unattributed pool -- produces a well-formed tape with a hole in it, and
    #: the only place that hole is visible is here.
    counters: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "frame_size": self.frame_size,
            "mints_reached": self.mints_reached,
            "mints_displaced": self.mints_displaced,
            "mints_truncated": self.mints_truncated,
            "transactions": self.transactions,
            "events_written": self.events_written,
            "credits_spent": self.credits_spent,
            "credit_limit": self.credit_limit,
            "window_seconds": self.window_seconds,
            "page_cap": self.page_cap,
            "gaps": list(self.gaps),
            "counters": dict(self.counters),
            "outcomes": [outcome.to_json() for outcome in self.outcomes],
        }


def refusal_window(
    mint: str, *, now: datetime, horizon: timedelta, source: str
) -> TapeEvent:
    """The record for a frame mint the budget never reached.

    A zero-length window closed ``DISPLACED``, byte-identical in shape to what
    :meth:`WatchRegistry._refuse` writes when its capacity binds. It is written here rather
    than through the registry for one structural reason: the registry only refuses once
    ``capacity`` watches are simultaneously open, and this collector closes each mint's watch
    as soon as it finishes reading that mint — including the terminal GRADUATED and DIED
    closes the recorder makes on its own — so the live set never reaches capacity even when
    the *frame* has plainly been truncated. Silence is the alternative, and silence is the
    failure this whole module exists to prevent: the mint was in the frame, it was never
    observed, and ``tape_health`` must count it.
    """

    moment = now.astimezone(UTC).isoformat()
    window = WatchWindow(
        mint=mint,
        opened_at=moment,
        deadline=(now.astimezone(UTC) + horizon).isoformat(),
        closed_at=moment,
        close_reason=WatchClose.DISPLACED,
    )
    return TapeEvent(
        kind=EventKind.WATCH,
        observed_at=moment,
        provenance=Provenance(source=source, fetched_at=moment),
        body=window,
    )


#: Closes the recorder makes on its own, from chain evidence. The panel must never overwrite
#: one with its own clock-based close: a GRADUATED window carries the chainstamps that make it
#: the panel's only real time-to-graduation observation.
TERMINAL_CLOSES: Final[frozenset[WatchClose]] = frozenset(
    {WatchClose.GRADUATED, WatchClose.DIED}
)


class _CountingSink:
    """Wrap the tape sink so the panel can attribute trades and closes to each mint."""

    def __init__(self, sink: Callable[[TapeEvent], bool]) -> None:
        self._sink = sink
        self.trades = 0
        self.wallets: set[str] = set()
        self.closes: list[tuple[str, WatchClose]] = []

    def reset(self) -> None:
        self.trades = 0
        self.wallets = set()
        self.closes = []

    def __call__(self, event: TapeEvent) -> bool:
        written = self._sink(event)
        if not written:
            return written
        if event.kind is EventKind.TRADE:
            self.trades += 1
            wallet = getattr(event.body, "wallet", None)
            if isinstance(wallet, str):
                self.wallets.add(wallet)
        elif event.kind is EventKind.WATCH:
            reason = getattr(event.body, "close_reason", None)
            mint = getattr(event.body, "mint", None)
            # Keyed by mint, because one mint's transactions routinely carry pump events for
            # OTHER mints -- a bundled launch, a router, an arbitrage leg. An unkeyed list
            # would let a neighbour's graduation be read as this mint's terminal outcome and
            # suppress this mint's own censoring record.
            if isinstance(reason, WatchClose) and isinstance(mint, str):
                self.closes.append((mint, reason))
        return written


async def collect_panel(
    client: Any,
    sink: Callable[[TapeEvent], bool],
    frame: Sequence[FrameMint],
    *,
    budget: CreditBudget,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    page_cap: int = DEFAULT_PAGE_CAP,
    source: str = "helius.getTransactionsForAddress",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_mint: Callable[[MintOutcome], object] | None = None,
) -> PanelReport:
    """Read each frame mint's own history into the tape, one mint at a time.

    One mint at a time is deliberate rather than lazy: the credit budget is charged per page,
    so stopping between mints leaves a *whole* mint's window either present or absent, never a
    half-read one masquerading as a quiet token.
    """

    started = clock()
    horizon = timedelta(seconds=window_seconds)
    counting = _CountingSink(sink)
    registry = WatchRegistry(counting, horizon=horizon, capacity=0, clock=clock)
    recorder = TapeRecorder(counting, registry, source=source, clock=clock)

    outcomes: list[MintOutcome] = []
    gaps: list[str] = []
    transactions = 0
    events = 0
    truncated = 0
    displaced = 0

    for index, row in enumerate(frame):
        if not budget.can_afford(CREDITS_PER_TRANSACTION_PAGE):
            now = clock()
            for remaining in frame[index:]:
                counting(refusal_window(remaining.mint, now=now, horizon=horizon, source=source))
                displaced += 1
                outcomes.append(
                    MintOutcome(
                        mint=remaining.mint,
                        stratum=remaining.stratum,
                        history=None,
                        close_reason=str(WatchClose.DISPLACED),
                        trades=0,
                        wallets=0,
                    )
                )
            gaps.append("credit_budget_exhausted")
            break

        counting.reset()
        source_for_mint = HeliusHistorySource(
            client,
            [row.mint],
            budget=budget,
            page_cap=page_cap,
            window_seconds=window_seconds,
        )
        result = await run_recorder(source_for_mint, recorder, budget=budget, expire_every=0)
        transactions += result.transactions
        events += result.events_written
        gaps.extend(gap.reason for gap in result.gaps)
        history = source_for_mint.histories[0] if source_for_mint.histories else None
        stopped = history.stopped_by if history is not None else "error"
        is_truncated = stopped in TRUNCATING_STOPS
        truncated += int(is_truncated)

        now = clock()
        # A terminal outcome the recorder already saw (GRADUATED / DIED) wins: it closed the
        # watch on chain evidence, and re-opening the mint to stamp our own clock on it would
        # both duplicate the window and throw away the panel's only chain-timed survival
        # observations.
        terminal = next(
            (
                close
                for mint, close in counting.closes
                if mint == row.mint and close in TERMINAL_CLOSES
            ),
            None,
        )
        reason = WatchClose.OBSERVER_LOST if is_truncated else WatchClose.DEADLINE
        if terminal is None:
            if row.mint not in registry and result.transactions:
                # We observed the mint but never witnessed its creation, so no watch opened.
                # The window still has to exist, or the observation is not censorable at all.
                registry.open(row.mint, now=now)
            closed = registry.close(row.mint, reason, now=now)
        else:
            closed = None
        outcome = MintOutcome(
            mint=row.mint,
            stratum=row.stratum,
            history=history,
            close_reason=(
                str(terminal)
                if terminal is not None
                else str(reason)
                if closed is not None
                else "never_observed"
            ),
            trades=counting.trades,
            wallets=len(counting.wallets),
        )
        outcomes.append(outcome)
        if on_mint is not None:
            on_mint(outcome)

    return PanelReport(
        started_at=started.astimezone(UTC).isoformat(),
        finished_at=clock().astimezone(UTC).isoformat(),
        frame_size=len(frame),
        mints_reached=sum(1 for outcome in outcomes if outcome.reached),
        mints_displaced=displaced,
        mints_truncated=truncated,
        transactions=transactions,
        events_written=events,
        credits_spent=budget.spent,
        credit_limit=budget.limit,
        window_seconds=window_seconds,
        page_cap=page_cap,
        gaps=tuple(gaps),
        outcomes=tuple(outcomes),
        counters=recorder.counters.to_json(),
    )


def wallet_activity(paths: Iterable[Path]) -> dict[str, set[str]]:
    """``wallet -> set of mints it traded``, read back off the tape.

    This is the number that decides whether signal #1 is feasible at all: Tumminello's
    hypergeometric test has power only for wallets active on enough tokens, and the usable
    universe is capped by ``C(T, N) >= 9 n(n-1) / (2 alpha)``. A panel that yields thousands of
    one-token tourists has not bought anything, however many mints it contains.
    """

    activity: dict[str, set[str]] = {}
    for path in paths:
        for event in _events(path):
            if event.kind is not EventKind.TRADE:
                continue
            wallet = getattr(event.body, "wallet", None)
            mint = getattr(event.body, "mint", None)
            if isinstance(wallet, str) and isinstance(mint, str):
                activity.setdefault(wallet, set()).add(mint)
    return activity


def _events(path: Path) -> Iterator[TapeEvent]:
    from shitcoims_tape.schema import event_from_json

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                yield event_from_json(json.loads(text))
            except (json.JSONDecodeError, TapeError, KeyError, TypeError):
                continue


@dataclass(frozen=True, slots=True)
class FrameCoverage:
    """How much of a population a repeated-sweep frame actually caught.

    Chao1 and Good-Turing rather than Lincoln-Petersen, and the difference is not academic
    here. Lincoln-Petersen assumes independent captures; measured over twelve sweeps of
    pump.fun's listing the capture counts were *under*-dispersed (every mint seen 6-10 times
    out of 12, none seen 11 or 12, none seen fewer than 6), which is the signature of a
    rotating slice rather than independent sampling. Under negative dependence
    Lincoln-Petersen is biased UP, and it duly reported 525 against a 12-sweep union of 469,
    i.e. a permanent 11% shortfall no amount of sweeping could close. Chao1 answers the
    question actually being asked — *is there unobserved mass* — from the singleton and
    doubleton counts, and needs no independence assumption.

    ``chao1 == observed`` when there are no singletons. That is a LOWER BOUND meeting the
    observed count, i.e. no evidence of anything missed. It is not proof of completeness, and
    a frame built on it should say so.
    """

    observed: int
    singletons: int
    doubletons: int
    captures: int

    @property
    def chao1(self) -> float:
        if self.singletons == 0:
            return float(self.observed)
        if self.doubletons == 0:
            return self.observed + self.singletons * (self.singletons - 1) / 2
        return self.observed + self.singletons**2 / (2 * self.doubletons)

    @property
    def coverage(self) -> float:
        return self.observed / self.chao1 if self.chao1 else 0.0

    @property
    def good_turing(self) -> float:
        """Sample coverage: the share of captures that are NOT one-off sightings."""

        return 1 - self.singletons / self.captures if self.captures else 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "observed": self.observed,
            "singletons": self.singletons,
            "doubletons": self.doubletons,
            "captures": self.captures,
            "chao1": self.chao1,
            "coverage": self.coverage,
            "good_turing": self.good_turing,
        }


def frame_coverage(capture_counts: Iterable[int]) -> FrameCoverage:
    """Chao1 over how many sweeps saw each member. One count per distinct member."""

    counts = [count for count in capture_counts if count > 0]
    return FrameCoverage(
        observed=len(counts),
        singletons=sum(1 for count in counts if count == 1),
        doubletons=sum(1 for count in counts if count == 2),
        captures=sum(counts),
    )


def feasible_universe(tokens: int, floor: int, *, alpha: float = 0.01, tests: int = 9) -> int:
    """Largest wallet count for which a pair on ``floor`` of ``tokens`` can EVER validate.

    PROGRAM.md 4.1: Bonferroni over ``n(n-1)/2`` pairs with ``tests`` typed tests each gives a
    threshold of ``alpha / (tests * n(n-1)/2)``, while the smallest p-value attainable by a
    pair each active on ``floor`` of ``tokens`` is ``1 / C(tokens, floor)``. Equating them:

        C(tokens, floor) >= tests * n(n-1) / (2 * alpha)

    This is a feasibility gate, checkable before a credit is spent, and it is the arithmetic
    the first draft of the signal-#1 row got wrong by a factor of ~2,700.
    """

    from fractions import Fraction
    from math import comb

    if floor < 1 or tokens < floor or tests < 1 or not 0 < alpha <= 1:
        return 0
    # Exact rationals, not floats: C(1000, 20) is ~3e41 and the whole point of the gate is
    # that it is checkable rather than approximately right.
    ceiling = Fraction(comb(tokens, floor)) * Fraction(alpha) * 2 / tests
    if ceiling < 2:
        return 0
    low, high = 1, 2
    while high * (high - 1) <= ceiling:
        high *= 2
    while low < high:
        mid = (low + high + 1) // 2
        if mid * (mid - 1) <= ceiling:
            low = mid
        else:
            high = mid - 1
    return low


__all__ = [
    "DEFAULT_PAGE_CAP",
    "DEFAULT_WINDOW_SECONDS",
    "FrameCoverage",
    "FrameMint",
    "MintOutcome",
    "PanelError",
    "PanelReport",
    "collect_panel",
    "feasible_universe",
    "frame_coverage",
    "read_frame",
    "refusal_window",
    "wallet_activity",
    "write_frame",
]
