"""Tests for the watch/censoring state machine.

Every test here pins the same rule from a different angle: a watch closes on a clock or on a
terminal outcome, never because attention moved on — and when capacity does force attention
to move, the fact is written to the tape rather than dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from solders.keypair import Keypair

from shitcoims_tape import EventKind, TapeEvent, WatchClose, WatchWindow, tape_health
from shitcoims_tape.watch import (
    DEFAULT_HORIZON,
    AdmissionPolicy,
    AdmissionResult,
    WatchRegistry,
)

T0 = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)


def _mint() -> str:
    return str(Keypair().pubkey())


class Recorded:
    """Collects the watch events a registry emits, exactly as the writer would see them."""

    def __init__(self) -> None:
        self.events: list[TapeEvent] = []

    def __call__(self, event: TapeEvent) -> bool:
        assert event.kind is EventKind.WATCH
        self.events.append(event)
        return True

    @property
    def windows(self) -> list[WatchWindow]:
        return [event.body for event in self.events if isinstance(event.body, WatchWindow)]

    def closed(self) -> list[WatchWindow]:
        return [window for window in self.windows if window.closed_at is not None]


def _registry(sink: Recorded, **kwargs: object) -> WatchRegistry:
    return WatchRegistry(sink, **kwargs)  # type: ignore[arg-type]


# --- the displacement rule ---------------------------------------------------------


def test_capacity_refuses_the_newcomer_and_never_cuts_an_existing_watch_short() -> None:
    """Capacity pressure falls on ADMISSION. An admitted mint always reaches its deadline."""

    sink = Recorded()
    registry = _registry(sink, capacity=2)
    first, second = _mint(), _mint()
    registry.open(first, now=T0)
    registry.open(second, now=T0 + timedelta(seconds=1))

    decision = registry.open(_mint(), now=T0 + timedelta(seconds=2))

    assert decision.result is AdmissionResult.REFUSED_AT_CAPACITY
    assert decision.displaced == ()
    # The two admitted mints are untouched and still running.
    assert first in registry
    assert second in registry
    assert [window.mint for window in sink.closed()] == [decision.window.mint]


def test_a_refusal_is_recorded_as_displaced_so_tape_health_can_count_it() -> None:
    """A silently dropped mint is invisible truncation of the sampling frame.

    This is the failure that turned a published 24-hour graduation rate into a ~6-minute one:
    the collector's attention moved on and nothing on disk said so.
    """

    sink = Recorded()
    registry = _registry(sink, capacity=1)
    registry.open(_mint(), now=T0)
    refused = _mint()

    decision = registry.open(refused, now=T0 + timedelta(seconds=5))

    assert decision.result is AdmissionResult.REFUSED_AT_CAPACITY
    record = decision.window
    assert record.mint == refused
    assert record.close_reason is WatchClose.DISPLACED
    assert record.is_informatively_censored
    # And the record is on the tape, not merely returned to the caller.
    assert record in sink.windows

    health = tape_health(observed_trades=100, reference_trades=100, watches=sink.windows)
    assert health.watches_informatively_censored == 1
    assert health.censoring_rate == 1.0
    assert health.complete is False


def test_eviction_requires_choosing_the_displace_policy_explicitly() -> None:
    """You cannot reach the published collector's bug by accident."""

    assert WatchRegistry(Recorded()).admission is AdmissionPolicy.REFUSE

    sink = Recorded()
    registry = _registry(sink, capacity=1, admission=AdmissionPolicy.DISPLACE)
    oldest = _mint()
    registry.open(oldest, now=T0)

    decision = registry.open(_mint(), now=T0 + timedelta(seconds=5))

    assert decision.admitted
    assert [window.mint for window in decision.displaced] == [oldest]
    assert decision.displaced[0].close_reason is WatchClose.DISPLACED
    assert oldest not in registry


def test_a_caller_cannot_stamp_displaced_on_a_watch_it_wants_to_drop() -> None:
    """DISPLACED belongs to the capacity path alone; anywhere else it launders a drop."""

    sink = Recorded()
    registry = _registry(sink)
    mint = _mint()
    registry.open(mint, now=T0)
    with pytest.raises(ValueError, match="reserved for the capacity path"):
        registry.close(mint, WatchClose.DISPLACED, now=T0 + timedelta(minutes=1))
    assert mint in registry


# --- clock discipline --------------------------------------------------------------


def test_a_watch_closes_on_its_deadline_and_not_before() -> None:
    sink = Recorded()
    registry = _registry(sink, horizon=timedelta(hours=2))
    mint = _mint()
    registry.open(mint, now=T0)

    assert registry.expire(now=T0 + timedelta(hours=1, minutes=59)) == ()
    assert mint in registry

    closed = registry.expire(now=T0 + timedelta(hours=2))
    assert [window.mint for window in closed] == [mint]
    assert closed[0].close_reason is WatchClose.DEADLINE
    assert not closed[0].is_informatively_censored


def test_a_horizon_too_short_to_see_the_graduation_tail_must_be_declared() -> None:
    """Marino's median is 4.4 min WITH A TAIL; a minutes-long horizon is the truncation bug."""

    with pytest.raises(ValueError, match="graduation tail"):
        WatchRegistry(Recorded(), horizon=timedelta(minutes=6))
    # Stating the truncation deliberately is allowed; doing it silently is not.
    registry = WatchRegistry(
        Recorded(), horizon=timedelta(minutes=6), allow_short_horizon=True
    )
    assert registry.horizon == timedelta(minutes=6)


def test_the_default_horizon_is_a_full_day() -> None:
    assert WatchRegistry(Recorded()).horizon == DEFAULT_HORIZON == timedelta(hours=24)


# --- every removal leaves a reason -------------------------------------------------


def test_every_watch_that_leaves_the_registry_leaves_a_close_record() -> None:
    """There is exactly one removal path and it always writes first."""

    sink = Recorded()
    registry = _registry(sink, capacity=0)
    graduated, died, expired, lost = _mint(), _mint(), _mint(), _mint()
    for mint in (graduated, died, expired):
        registry.open(mint, now=T0)
    registry.open(lost, now=T0 + timedelta(hours=2))  # deadline T0+26h, survives the expiry

    registry.graduated(graduated, now=T0 + timedelta(minutes=4))
    registry.died(died, now=T0 + timedelta(minutes=30))
    registry.expire(now=T0 + timedelta(hours=25))
    registry.shutdown(now=T0 + timedelta(hours=25, minutes=30))

    opened = [window for window in sink.windows if window.closed_at is None]
    closed = sink.closed()
    assert len(opened) == 4
    assert {window.mint for window in closed} == {graduated, died, expired, lost}
    reasons = {window.mint: window.close_reason for window in closed}
    assert reasons[graduated] is WatchClose.GRADUATED
    assert reasons[died] is WatchClose.DIED
    assert reasons[expired] is WatchClose.DEADLINE
    # A crash or stop is informative censoring and is reported as such, never as a deadline.
    assert reasons[lost] is WatchClose.OBSERVER_LOST
    assert len(registry) == 0


def test_an_open_and_its_close_share_a_key_so_the_pair_reassembles() -> None:
    sink = Recorded()
    registry = _registry(sink)
    mint = _mint()
    opened = registry.open(mint, now=T0).window
    closed = registry.graduated(mint, now=T0 + timedelta(minutes=4, seconds=24))
    assert closed is not None
    assert (closed.mint, closed.opened_at, closed.deadline) == (
        opened.mint,
        opened.opened_at,
        opened.deadline,
    )


def test_watching_the_same_mint_twice_does_not_double_count_it() -> None:
    sink = Recorded()
    registry = _registry(sink)
    mint = _mint()
    first = registry.open(mint, now=T0)
    again = registry.open(mint, now=T0 + timedelta(minutes=1))
    assert again.result is AdmissionResult.ALREADY_WATCHED
    assert again.window is first.window
    assert len(sink.events) == 1
    assert registry.stats.duplicate_opens == 1


def test_closing_an_unwatched_mint_is_a_no_op_rather_than_a_fabricated_record() -> None:
    sink = Recorded()
    registry = _registry(sink)
    assert registry.graduated(_mint(), now=T0) is None
    assert sink.events == []


def test_stats_separate_benign_from_informative_closes() -> None:
    sink = Recorded()
    registry = _registry(sink, capacity=1)
    kept = _mint()
    registry.open(kept, now=T0)
    registry.open(_mint(), now=T0)  # refused -> DISPLACED
    registry.expire(now=T0 + timedelta(hours=25))  # kept -> DEADLINE

    stats = registry.stats
    assert stats.opened == 1
    assert stats.refused_at_capacity == 1
    assert stats.closed_by_reason == {"displaced": 1, "deadline": 1}
    assert stats.informatively_censored == 1
    assert stats.open_now == 0


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc() -> None:
    registry = _registry(Recorded())
    with pytest.raises(ValueError, match="timezone"):
        registry.open(_mint(), now=datetime(2026, 8, 13, 0, 0))
