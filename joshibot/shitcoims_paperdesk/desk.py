"""The desk daemon: one loop, four books, one ledger, two clocks, heartbeats.

RUNNING IT
----------
``uv run python -m shitcoims_paperdesk run --minutes 10``    a bounded session
``uv run python -m shitcoims_paperdesk run --minutes 0``     daemon: until killed
``uv run python -m shitcoims_paperdesk report``              the cross-book table

Positions PERSIST. A bounded run does not drain unless asked (``--drain``), because the
operator's actual complaint was that nothing survives the afternoon it was tested in. The
desk writes ``state/paperdesk/desk-state.json`` atomically every minute and on exit, and a
restarted desk resumes the same book, the same counters and the same seen-set.

THE HEARTBEAT IS NOT DECORATION
-------------------------------
Two daemons died silently in this tree for a day. A heartbeat row every minute carries the
per-book counters, the open position count, the breaker state and -- the part that matters
-- the seconds since each SOURCE last produced anything. A desk with a live heartbeat and
four stale sources is a different failure from a dead desk, and only one of them is a
market observation.

WATCH WINDOWS
-------------
Each source opens a window at startup and its transitions are logged: alive -> stale emits
a ``watch_close`` with ``OBSERVER_LOST`` (informative censoring, per the tape contract),
stale -> alive opens a new one. Positions closed while their marking source is stale are
censored as ``OBSERVER_LOST`` rather than ``DISPLACED``, so the report can separate "the
market moved on from this coin" from "we stopped watching".
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import time
from dataclasses import dataclass
from types import FrameType
from typing import Any, Final

from shitcoims_paperdesk import BOOKS, Book
from shitcoims_paperdesk.books import MintBook
from shitcoims_paperdesk.feeds import (
    BoardsSource,
    CalloutSource,
    ClusterTapeSource,
    FirehoseSource,
    MintRefreshSource,
    Source,
    swap_as_mint_observation,
)
from shitcoims_paperdesk.friction import LAMPORTS_PER_SOL, Friction
from shitcoims_paperdesk.ledger import Ledger, iso
from shitcoims_paperdesk.policy import policy_for
from shitcoims_paperdesk.toll import TollBook
from shitcoims_paperdesk.wiggle import CalloutActivity, WiggleBook
from shitcoims_tape.schema import WatchClose

__all__ = ["Desk", "DeskConfig", "main"]

#: A source quiet for longer than this is not observing. Boards polls 5 boards every 30s
#: and the firehose delivers 18-28 mints a minute, so five minutes of silence from either
#: is a collector problem, not a market state.
STALE_AFTER_S: Final[float] = 300.0

#: The cluster tape is polled, not streamed, and its pools are quiet for long stretches.
#: A separate, looser bound so a genuinely quiet pool is not reported as a dead collector.
TAPE_STALE_AFTER_S: Final[float] = 3600.0

#: The callout feed is INHERENTLY low-rate and the 300 s bound was set for a high-rate one.
#: Measured 2026-08-15 against the live collector: ``poll_callout_snapshots`` returns 0
#: mint-resolved callouts over a 900 s window and 5 over a 7200 s one -- roughly one every
#: 24 minutes. Under the 300 s bound this source therefore reads STALE nearly all the time
#: while working perfectly, which inverts the whole point of the flag: a state that is
#: almost always on carries no information, and the heartbeat exists precisely to tell a
#: cold collector from a quiet market. One hour is ~2.5x the measured mean interval.
CALLOUT_STALE_AFTER_S: Final[float] = 3600.0

#: An observation older than this cannot be traded on, so it is not offered to a position
#: book. This matters because the desk BOOTSTRAPS the toll book's flow window from days of
#: historical tape: those swaps are a legitimate measurement of a past window, and a
#: catastrophic thing to fill a paper position against. Routed to the flow window (a
#: measurement) but never to a book (an action).
MAX_ACTIONABLE_AGE_S: Final[float] = 300.0


@dataclass(frozen=True, slots=True)
class DeskConfig:
    """Identical capital and identical friction, stated once.

    ``bankroll_sol`` is PER BOOK. Handing the short book more capital than the toll book
    and then comparing their P&L would answer a question about capital allocation while
    appearing to answer one about horizon.
    """

    bankroll_sol: float = 5.0
    poll_seconds: float = 3.0
    minutes: float = 10.0
    seed: int | None = None
    explore_eps: float = 0.05
    max_positions: int = 8
    drain_on_exit: bool = False
    #: Read the cluster tape from its start rather than from EOF. The tape is polled in
    #: bursts and may be hours cold, so the gate needs history to be computable at all.
    tape_from_start: bool = True
    tape_days_back: int = 3

    @property
    def bankroll_lamports(self) -> int:
        return int(self.bankroll_sol * LAMPORTS_PER_SOL)


#: The operator's own clip, from the 36 h chain reconstruction of their live trades. The
#: wiggle book is a paper replay of those trades and must be sized like them.
WIGGLE_CLIP_LAMPORTS: Final[int] = 100_000_000


class Desk:
    """Four books over five sources, sharing one ledger and one wall clock."""

    def __init__(self, config: DeskConfig, *, ledger: Ledger | None = None) -> None:
        self.config = config
        self.ledger = ledger or Ledger()
        self.friction = Friction()
        seed = config.seed

        self.short = MintBook(
            Book.SHORT,
            policy=policy_for(Book.SHORT, explore_eps=config.explore_eps, seed=seed),
            friction=self.friction,
            ledger=self.ledger,
            bankroll_lamports=config.bankroll_lamports,
            max_positions=config.max_positions,
        )
        self.medium = MintBook(
            Book.MEDIUM,
            policy=policy_for(
                Book.MEDIUM,
                explore_eps=config.explore_eps,
                seed=None if seed is None else seed + 1,
            ),
            friction=self.friction,
            ledger=self.ledger,
            bankroll_lamports=config.bankroll_lamports,
            max_positions=config.max_positions,
            # The only structural difference between the two mint books: the medium book
            # exits on deterioration, the short book on its bracket.
            deterioration_exit=True,
            decision_cooldown_s=1800.0,
        )
        self.toll = TollBook(
            policy=policy_for(
                Book.TOLL,
                explore_eps=config.explore_eps,
                seed=None if seed is None else seed + 2,
            ),
            friction=self.friction,
            ledger=self.ledger,
            bankroll_lamports=config.bankroll_lamports,
            max_positions=4,
        )
        self.wiggle = WiggleBook(
            Book.WIGGLE,
            policy=policy_for(
                Book.WIGGLE,
                explore_eps=config.explore_eps,
                seed=None if seed is None else seed + 3,
            ),
            friction=self.friction,
            ledger=self.ledger,
            bankroll_lamports=config.bankroll_lamports,
            max_positions=config.max_positions,
            clip_lamports=WIGGLE_CLIP_LAMPORTS,
            # A five-minute book must be free to look at the same coin again soon: its
            # candidate is a MOMENT (a live oscillation at a tested bottom), not a coin,
            # and a half-hour cooldown would let the desk watch every one of them go by.
            decision_cooldown_s=120.0,
        )

        self.boards = BoardsSource()
        self.firehose = FirehoseSource()
        self.callouts = CalloutSource()
        self.refresh = MintRefreshSource()
        self.tape = ClusterTapeSource(
            from_start=config.tape_from_start, days_back=config.tape_days_back
        )
        self.sources: tuple[Source, ...] = (
            self.boards,
            self.firehose,
            self.callouts,
            self.refresh,
            self.tape,
        )
        #: Callout counts per mint over the last hour. Logged on every wiggle decision and
        #: gating none of them -- see ``wiggle.CALLOUT_ARM`` for the study verdict behind
        #: that, and ``wiggle.CalloutActivity`` for why an unused column is still worth
        #: writing down.
        self.callout_activity = CalloutActivity()
        self._window_open: dict[str, float] = {}
        self._window_events: dict[str, int] = {}
        self._stopping = False
        #: Observations too old to have been acted on. Counted, reported, never filled.
        self.stale_observations = 0

    # ---------------------------------------------------------------- lifecycle

    def _stale_bound(self, source: Source) -> float:
        """Per-source, because "silent" means a different thing per source's own rate."""
        if source is self.tape:
            return TAPE_STALE_AFTER_S
        if source is self.callouts:
            return CALLOUT_STALE_AFTER_S
        return STALE_AFTER_S

    def stale(self, source: Source, now: float) -> bool:
        return source.seconds_since_event(now) > self._stale_bound(source)

    def _actionable(self, obs: Any, now: float) -> bool:
        """Could the desk have acted on this observation? If not, it is data, not a fill."""
        age = now - obs.t_ingest_unix
        if age <= MAX_ACTIONABLE_AGE_S:
            return True
        self.stale_observations += 1
        return False

    def open_windows(self, now: float) -> None:
        for source in self.sources:
            # The window's clock is the DESK's clock. Source.__init__ stamps wall time,
            # which under simulated time makes seconds_since_event negative — a source
            # that can never go stale. (The daemon's `now` is wall time, so production
            # never saw it; the test that caught it rotted as real time passed its fixed
            # T0.) Two clocks, never mixed — including our own.
            source.opened_at_unix = now
            self._window_open[source.name] = now
            self._window_events[source.name] = source.events
            self.ledger.watch_open(
                "desk",
                source=source.name,
                opened_at_unix=now,
                stale_after_s=self._stale_bound(source),
            )

    def check_windows(self, now: float) -> None:
        """Turn a source going quiet into a logged, reasoned censoring event."""
        for source in self.sources:
            was_open = source.name in self._window_open
            is_stale = self.stale(source, now)
            if was_open and is_stale:
                opened = self._window_open.pop(source.name)
                self.ledger.watch_close(
                    "desk",
                    source=source.name,
                    opened_at_unix=opened,
                    closed_at_unix=now,
                    reason=WatchClose.OBSERVER_LOST,
                    events=source.events - self._window_events.get(source.name, 0),
                    silent_seconds=source.seconds_since_event(now),
                )
            elif not was_open and not is_stale:
                self._window_open[source.name] = now
                self._window_events[source.name] = source.events
                self.ledger.watch_open(
                    "desk",
                    source=source.name,
                    opened_at_unix=now,
                    stale_after_s=self._stale_bound(source),
                    detail="source_recovered",
                )

    def load(self) -> None:
        state = self.ledger.load_state()
        if not state:
            return
        self.short.restore(state.get("short") or {})
        self.medium.restore(state.get("medium") or {})
        self.toll.restore(state.get("toll") or {})
        self.wiggle.restore(state.get("wiggle") or {})

    def save(self) -> None:
        self.ledger.save_state(
            {
                "saved_at": iso(time.time()),
                "run_id": self.ledger.run_id,
                "short": self.short.state(),
                "medium": self.medium.state(),
                "toll": self.toll.state(),
                "wiggle": self.wiggle.state(),
            }
        )

    # ---------------------------------------------------------------- the loop

    def step(self, now: float) -> None:
        boards_stale = self.stale(self.boards, now)
        tape_stale = self.stale(self.tape, now)

        # 1. Boards: the marking feed for the mint books, the survivorship record the
        #    medium book's entry rule is built on, and the wiggle book's ONLY source of a
        #    measured drawdown -- the boards vendor is the one feed that serves an ATH, and
        #    without an ATH there is no such thing as a post-collapse bottom.
        for obs in self.boards.poll(now):
            if not self._actionable(obs, now):
                continue
            self.short.observe(obs, source_stale=boards_stale)
            self.short.consider(obs)
            self.medium.observe(obs, source_stale=boards_stale)
            self.medium.consider(obs)
            self.wiggle.observe(obs, source_stale=boards_stale)
            self.wiggle.consider(obs, extra_features=self.callout_activity.features(obs.mint, now))

        # 2. Firehose: short-book candidates only. A mint two seconds old is not a
        #    medium-horizon position, and it is not a wiggle candidate either -- it has no
        #    all-time high to have collapsed from, so its drawdown is not merely unmeasured
        #    but undefined. Callouts go to BOTH: the study demoted them from an entry
        #    condition to a candidate generator, and a candidate generator's whole job is
        #    to put a coin in front of a book that the boards may never carry.
        for obs in self.firehose.poll(now):
            if not self._actionable(obs, now):
                continue
            self.short.observe(obs, source_stale=boards_stale)
            self.short.consider(obs)
        for obs in self.callouts.poll(now):
            self.callout_activity.record(obs.mint, obs.t_event_unix or obs.t_ingest_unix)
            if not self._actionable(obs, now):
                continue
            self.short.observe(obs, source_stale=boards_stale)
            self.short.consider(obs)
            self.wiggle.observe(obs, source_stale=boards_stale)
            self.wiggle.consider(obs, extra_features=self.callout_activity.features(obs.mint, now))

        # 3. Cluster tape: the toll book's flow, and the medium book's held-cluster arm.
        #    EVERY swap feeds the flow window -- that is a measurement over a past window
        #    and history is exactly what makes eta and VR estimable at all. Only FRESH
        #    swaps reach the medium book, because a position cannot be opened against a
        #    price from two days ago.
        for swap in self.tape.poll(now):
            self.toll.observe(swap, now=now)
            mint_obs = swap_as_mint_observation(swap)
            if mint_obs is None or not self._actionable(mint_obs, now):
                continue
            self.medium.observe(mint_obs, source_stale=tape_stale)
            self.medium.consider(mint_obs)

        # 4. Refresh held mints so positions from any source can be marked. Without this
        #    a firehose entry could never be observed again and would resolve as censored
        #    whatever it did -- a hole in the instrument, not a property of the market.
        #    The wiggle book's holdings are PRIORITY, because its exit is a five-minute
        #    clock and an unmarked wiggle position is the exact failure the book exists to
        #    prevent. Measured on a four-minute live probe before this was wired: a stop
        #    armed at -16.5% filled at -64.7% because the next observation of that coin was
        #    43 seconds later and it had gapped through. The desk cannot trade the tick that
        #    told it to trade, so the only lever is how soon the NEXT tick arrives.
        wiggle_held = {p.mint for p in self.wiggle.positions.values()} | set(self.wiggle.pending)
        held = sorted(
            wiggle_held
            | {p.mint for p in self.short.positions.values()}
            | {p.mint for p in self.medium.positions.values()}
            | set(self.short.pending)
            | set(self.medium.pending)
        )
        for obs in self.refresh.refresh(held, now, priority=wiggle_held):
            self.short.observe(obs, source_stale=False)
            self.medium.observe(obs, source_stale=False)
            self.wiggle.observe(obs, source_stale=False)

        # 5. Gates, sweeps, windows.
        self.toll.gate(now)
        self.short.sweep(now, source_stale=boards_stale)
        self.medium.sweep(now, source_stale=boards_stale and tape_stale)
        self.toll.sweep(now, source_stale=tape_stale)
        self.wiggle.sweep(now, source_stale=boards_stale)
        self.callout_activity.expire(now)
        self.check_windows(now)

    def heartbeat(self, now: float) -> None:
        self.ledger.emit(
            "heartbeat",
            "desk",
            t_ingest_unix=now,
            sources={
                s.name: {
                    "events": s.events,
                    "silent_seconds": s.seconds_since_event(now),
                    "stale": self.stale(s, now),
                }
                for s in self.sources
            },
            books={
                "short": self._book_state(self.short, now),
                "medium": self._book_state(self.medium, now),
                "toll": {
                    "open_positions": len(self.toll.positions),
                    "deployed_lamports": self.toll.deployed_lamports,
                    "pools_with_flow": len(self.toll.flows),
                    **self.toll.counters,
                },
                "wiggle": {
                    **self._book_state(self.wiggle, now),
                    "mints_watched": len(self.wiggle.watch),
                },
            },
            firehose_duplicates_dropped=self.firehose.duplicates_dropped,
            refresh_failures=self.refresh.failures,
            stale_observations_not_filled=self.stale_observations,
            tape_out_of_order_rows=sum(f.out_of_order for f in self.toll.flows.values()),
            rows_written=self.ledger.rows_written,
        )

    @staticmethod
    def _book_state(book: MintBook, now: float) -> dict[str, Any]:
        return {
            "open_positions": len(book.positions),
            "pending": len(book.pending),
            "deployed_lamports": book.deployed_lamports,
            "breaker_paused": book.breaker.paused(now),
            "mints_seen": len(book.seen),
            **book.counters,
        }

    def run(self) -> dict[str, Any]:
        start = time.time()
        deadline = start + self.config.minutes * 60 if self.config.minutes > 0 else None
        self.load()
        self.open_windows(start)
        self.ledger.emit(
            "heartbeat",
            "desk",
            t_ingest_unix=start,
            detail="desk_started",
            daemon=deadline is None,
            bankroll_lamports_per_book=self.config.bankroll_lamports,
            priority_fee_lamports=self.friction.priority_fee_lamports,
            explore_eps=self.config.explore_eps,
            books=[str(b) for b in BOOKS],
        )

        def _stop(signum: int, frame: FrameType | None) -> None:
            self._stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            # Not the main thread? The loop still honours the flag; it just will not be
            # set by a signal. A daemon that refuses to start because it cannot install a
            # handler is worse than one that stops on its deadline.
            with contextlib.suppress(ValueError):
                signal.signal(sig, _stop)

        last_heartbeat = 0.0
        last_save = start
        while not self._stopping and (deadline is None or time.time() < deadline):
            now = time.time()
            self.step(now)
            if now - last_heartbeat >= 60.0:
                last_heartbeat = now
                self.heartbeat(now)
            if now - last_save >= 60.0:
                last_save = now
                self.save()
            time.sleep(max(0.0, self.config.poll_seconds - (time.time() - now)))

        end = time.time()
        if self.config.drain_on_exit:
            self.short.drain(end)
            self.medium.drain(end)
            self.toll.drain(end)
            self.wiggle.drain(end)
        self.heartbeat(end)
        self.save()
        self.ledger.close()
        return {
            "run_id": self.ledger.run_id,
            "seconds": end - start,
            "rows": self.ledger.rows_written,
            "short": self.short.counters,
            "medium": self.medium.counters,
            "toll": self.toll.counters,
            "wiggle": self.wiggle.counters,
        }


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--minutes",
        type=float,
        default=10.0,
        help="run length; <= 0 runs as a daemon until killed",
    )
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--bankroll-sol", type=float, default=5.0, help="PER BOOK")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--explore-eps", type=float, default=0.05)
    parser.add_argument("--max-positions", type=int, default=8)
    parser.add_argument(
        "--drain",
        action="store_true",
        help="close every open position on exit; off by default so the book persists",
    )
    parser.add_argument("--tape-days-back", type=int, default=3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperdesk-run")
    add_run_arguments(parser)
    args = parser.parse_args(argv)
    config = DeskConfig(
        bankroll_sol=args.bankroll_sol,
        poll_seconds=args.poll_seconds,
        minutes=args.minutes,
        seed=args.seed,
        explore_eps=args.explore_eps,
        max_positions=args.max_positions,
        drain_on_exit=args.drain,
        tape_days_back=args.tape_days_back,
    )
    summary = Desk(config).run()
    import json

    print(json.dumps(summary, indent=1, default=str))
    return 0
