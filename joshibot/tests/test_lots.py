from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shitcoims_sentinel.lots import (
    DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS,
    DEFAULT_NEW_BAG_SL_GRACE_SECONDS,
    ORIGIN_DEFAULT,
    ORIGIN_OPERATOR,
    basis_applied,
    due_for_default,
    mark_origin,
    note_seen,
    record_from_mapping,
    reopen_held,
    retire,
    skip_auto,
    sl_is_live,
)

NOW = datetime(2026, 8, 12, 23, 0, tzinfo=timezone.utc)
MINT = "5jUwEEKMawc1q1GCEKLgCYA77jbGfVvjz21nEpJrpump"


def test_first_sighting_schedules_delayed_default() -> None:
    record, fresh = note_seen(None, MINT, now=NOW)
    assert fresh is True
    assert record.generation == 1
    assert record.flat_since is None
    assert record.origin is None
    expected = NOW + timedelta(seconds=DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS)
    assert record.auto_protect_after == expected.isoformat()
    assert due_for_default(record, now=NOW) is False
    assert due_for_default(record, now=NOW + timedelta(seconds=599)) is False
    assert due_for_default(record, now=NOW + timedelta(seconds=600)) is True


def test_operator_or_skip_cancels_auto_protect() -> None:
    record, _ = note_seen(None, MINT, now=NOW)
    later = NOW + timedelta(seconds=700)
    assert due_for_default(skip_auto(record), now=later) is False
    assert due_for_default(mark_origin(record, ORIGIN_OPERATOR), now=later) is False
    armed = mark_origin(record, ORIGIN_DEFAULT)
    assert armed.origin == ORIGIN_DEFAULT
    assert due_for_default(armed, now=later) is False


def test_flat_kills_default_rule_and_rebuy_is_a_new_generation() -> None:
    record, _ = note_seen(None, MINT, now=NOW)
    record = mark_origin(record, ORIGIN_DEFAULT)
    dead = retire(record, now=NOW + timedelta(minutes=3))
    assert dead.is_flat is True
    assert dead.origin is None
    assert dead.auto_protect_after is None
    assert due_for_default(dead, now=NOW + timedelta(hours=1)) is False

    reborn, fresh = note_seen(dead, MINT, now=NOW + timedelta(minutes=4), delay_seconds=600)
    assert fresh is True
    assert reborn.generation == 2
    assert reborn.origin is None
    assert due_for_default(reborn, now=NOW + timedelta(minutes=4)) is False
    assert due_for_default(reborn, now=NOW + timedelta(minutes=14)) is True


def test_operator_policy_survives_flat_but_does_not_keep_a_schedule() -> None:
    record, _ = note_seen(None, MINT, now=NOW)
    record = mark_origin(record, ORIGIN_OPERATOR)
    dead = retire(record, now=NOW)
    assert dead.origin == ORIGIN_OPERATOR
    assert dead.needs_basis is True
    assert dead.auto_protect_after is None
    assert due_for_default(dead, now=NOW + timedelta(hours=1)) is False
    live = reopen_held(dead, now=NOW + timedelta(minutes=1))
    assert live.is_flat is False
    assert live.generation == dead.generation + 1
    assert live.needs_basis is True
    assert basis_applied(live).needs_basis is False


def test_default_origin_holds_stop_for_grace_operator_does_not() -> None:
    record, _ = note_seen(None, MINT, now=NOW)
    defaulted = mark_origin(record, ORIGIN_DEFAULT, now=NOW)
    assert defaulted.sl_live_after == (
        NOW + timedelta(seconds=DEFAULT_NEW_BAG_SL_GRACE_SECONDS)
    ).isoformat()
    assert sl_is_live(defaulted, now=NOW) is False
    assert sl_is_live(defaulted, now=NOW + timedelta(seconds=599)) is False
    assert sl_is_live(defaulted, now=NOW + timedelta(seconds=600)) is True
    operator = mark_origin(record, ORIGIN_OPERATOR, now=NOW)
    assert operator.sl_live_after is None
    assert sl_is_live(operator, now=NOW) is True


def test_empty_ghost_lot_still_gets_a_schedule() -> None:
    ghost = record_from_mapping(MINT, {})
    assert ghost.generation == 0
    assert ghost.auto_protect_after is None
    record, fresh = note_seen(ghost, MINT, now=NOW)
    assert fresh is True
    assert record.generation == 1
    assert record.auto_protect_after is not None
    assert due_for_default(record, now=NOW + timedelta(seconds=600)) is True


def test_corrupt_mapping_is_a_fresh_unknown_lot() -> None:
    record = record_from_mapping(
        MINT, {"generation": "nope", "origin": "panic", "auto_protect_after": "not-a-date"}
    )
    assert record.generation == 0
    assert record.origin is None
    assert record.auto_protect_after is None
    assert due_for_default(record, now=NOW) is False
