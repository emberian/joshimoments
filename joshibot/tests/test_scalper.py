"""Tests for the shadow scalper: sizing math, book mechanics, propensity soundness,
pessimistic marking, and conformance to the real tape contract."""

from __future__ import annotations

import math
import random

import pytest

from shitcoims_scalper.book import Book, CircuitBreaker, DeadlineHeap, OpenPosition
from shitcoims_scalper.policy import (
    JitterRanges,
    ScalperPolicy,
    liveness_verdict,
    optimal_size_lamports,
    round_trip_friction,
)
from shitcoims_scalper.shadow import CurveState, ShadowMarker, curve_buy, curve_sell

SOL = 1_000_000_000
PRIO = 500_000

LIVE_FEATURES = {"age_s": 120.0, "trade_recency_s": 3.0, "sol_in_curve": 40.0}


# ---------------------------------------------------------------- sizing / friction


def test_optimal_size_is_sqrt_priority_times_pool() -> None:
    y = 60 * SOL
    b = optimal_size_lamports(y, priority_fee_lamports=PRIO, bankroll_cap_lamports=10 * SOL)
    assert b == math.isqrt(PRIO * y)
    # ~0.173 SOL at a 60-SOL pool — the few-dollars clip found empirically by hand.
    assert 0.15 * SOL < b < 0.20 * SOL


def test_friction_is_u_shaped_with_minimum_at_b_star() -> None:
    y = 60 * SOL
    b_star = optimal_size_lamports(
        y, priority_fee_lamports=PRIO, bankroll_cap_lamports=10 * SOL
    )
    at = lambda b: round_trip_friction(b, y, swap_fee_bps=100, priority_fee_lamports=PRIO)
    assert at(b_star) < at(b_star // 4)
    assert at(b_star) < at(b_star * 4)


def test_size_respects_pool_impact_and_bankroll_caps() -> None:
    # sqrt(p*Y) grows slower than rho*Y, so the impact cap binds on SHALLOW pools:
    # it binds iff Y < p / rho^2 (= 1.25 SOL at p=5e5 lamports, rho=2%).
    y = 1 * SOL
    b = optimal_size_lamports(
        y, priority_fee_lamports=PRIO, rho_max_bps=200, bankroll_cap_lamports=100_000 * SOL
    )
    assert b == y * 200 // 10_000  # rho cap binds
    y_deep = 10_000 * SOL
    b2 = optimal_size_lamports(
        y_deep, priority_fee_lamports=PRIO, rho_max_bps=200, bankroll_cap_lamports=SOL // 10
    )
    assert b2 == SOL // 10  # bankroll cap binds on the deep pool


# ---------------------------------------------------------------- book mechanics


def test_deadline_heap_pops_in_deadline_order_only_when_due() -> None:
    h = DeadlineHeap()
    for i, dl in enumerate((30.0, 10.0, 20.0)):
        h.push(OpenPosition(f"d{i}", f"m{i}", 1, dl))
    assert h.due(5.0) == []
    popped = h.due(25.0)
    assert [p.deadline_unix for p in popped] == [10.0, 20.0]
    assert len(h) == 1


def test_book_caps_positions_and_exposure() -> None:
    book = Book(max_positions=2, max_exposure_lamports=100)
    assert book.admits(mint="a", size_lamports=60, now_unix=0)
    book.open(OpenPosition("d1", "a", 60, 100.0))
    assert not book.admits(mint="a", size_lamports=1, now_unix=0)  # same mint
    assert not book.admits(mint="b", size_lamports=50, now_unix=0)  # exposure
    assert book.admits(mint="b", size_lamports=40, now_unix=0)
    book.open(OpenPosition("d2", "b", 40, 100.0))
    assert not book.admits(mint="c", size_lamports=1, now_unix=0)  # count


def test_circuit_breaker_trips_and_recovers() -> None:
    cb = CircuitBreaker(window=3, max_drawdown_lamports=100, pause_seconds=60.0)
    cb.record_close(-50, 0.0)
    cb.record_close(-40, 1.0)
    assert not cb.paused(2.0)
    cb.record_close(-30, 2.0)  # window sum -120 < -100
    assert cb.paused(3.0)
    assert not cb.paused(63.0)


# ---------------------------------------------------------------- policy / propensity


def test_liveness_verdict_is_five_comparisons_no_forecast() -> None:
    t = JitterRanges().draw(random.Random(0))
    ok = dict(LIVE_FEATURES)
    assert liveness_verdict(ok, t)
    for k, bad in (("age_s", 1.0), ("trade_recency_s", 9999.0), ("sol_in_curve", 0.1)):
        assert not liveness_verdict({**ok, k: bad}, t)


def test_propensity_is_probability_of_action_taken() -> None:
    policy = ScalperPolicy(seed=7, explore_eps=0.05)
    seen = {"enter": 0, "skip": 0}
    for i in range(400):
        d = policy.decide(
            mint="A" * 44, features=LIVE_FEATURES, now_unix=1000.0 + i, decided_at="2026-08-13T00:00:00+00:00"
        )
        assert 0.0 < d.propensity <= 1.0
        # verdict passes and pool is deep: enter carries 0.95, an explore-skip carries 0.05
        assert d.propensity == (0.95 if d.action == "enter" else pytest.approx(0.05))
        seen[d.action] += 1
    # epsilon actually explores: some skips must exist despite a passing verdict
    assert seen["skip"] > 0
    assert seen["enter"] > seen["skip"] * 5


def test_unaffordable_friction_folds_into_verdict() -> None:
    policy = ScalperPolicy(seed=1)
    shallow = {"age_s": 120.0, "trade_recency_s": 3.0, "sol_in_curve": 0.05}
    d = policy.decide(
        mint="B" * 44, features=shallow, now_unix=0.0, decided_at="2026-08-13T00:00:00+00:00"
    )
    assert not d.verdict_pass


def test_decisions_are_reproducible_given_seed() -> None:
    a = ScalperPolicy(seed=42).decide(
        mint="C" * 44, features=LIVE_FEATURES, now_unix=5.0, decided_at="2026-08-13T00:00:00+00:00"
    )
    b = ScalperPolicy(seed=42).decide(
        mint="C" * 44, features=LIVE_FEATURES, now_unix=5.0, decided_at="2026-08-13T00:00:00+00:00"
    )
    assert a == b


# ---------------------------------------------------------------- tape conformance


def test_decision_conforms_to_real_propensity_record() -> None:
    """The anti-mirror gate: our JSON must construct the REAL tape contract type."""
    from shitcoims_tape.schema import PropensityRecord

    d = ScalperPolicy(seed=3).decide(
        mint="So11111111111111111111111111111111111111112",
        features=LIVE_FEATURES,
        now_unix=1000.0,
        decided_at="2026-08-13T00:00:00+00:00",
    )
    rec = PropensityRecord(**d.propensity_record_json())
    assert rec.policy_id == "scalper-shadow-v1"
    assert rec.to_json()["propensity"] == d.propensity


def test_logged_decision_feeds_ope() -> None:
    from shitcoims_replay.ope import LoggedDecision

    d = ScalperPolicy(seed=4).decide(
        mint="D" * 44, features=LIVE_FEATURES, now_unix=0.0, decided_at="2026-08-13T00:00:00+00:00"
    )
    LoggedDecision(action=d.action, propensity=d.propensity, reward=0.0)  # must not raise


# ---------------------------------------------------------------- shadow marking


def _state(t: float, sol: float, tok: int = 10**15) -> CurveState:
    return CurveState(t_ingest_unix=t, vsol_lamports=int(sol * SOL), vtok_raw=tok)


def test_round_trip_on_unchanged_reserves_loses_exactly_fees() -> None:
    s = _state(0.0, 45.0)
    spend = SOL // 10
    tokens = curve_buy(s, spend, fee_bps=100)
    back = curve_sell(s, tokens, fee_bps=100)
    assert back < spend  # fees + impact, strictly
    # loss is bounded by two fees plus one impact step (~1% + ~1% + ~0.22%)
    assert back > spend * 97 // 100


def test_entry_fills_at_next_observation_never_at_decision() -> None:
    m = ShadowMarker()
    m.submit("d1", "MINT", SOL // 10)
    assert m.open_count == 0  # nothing filled at decision time
    fills = m.on_observation("MINT", _state(5.0, 45.0))
    assert len(fills) == 1 and m.open_count == 1
    assert fills[0].entry_state.t_ingest_unix == 5.0


def test_feed_lost_marks_total_loss() -> None:
    m = ShadowMarker(priority_fee_lamports=PRIO)
    m.submit("d1", "MINT", SOL // 10)
    m.on_observation("MINT", _state(5.0, 45.0))
    close = m.close("d1", None)
    assert close is not None
    assert close.exit_reason == "feed_lost"
    assert close.pnl_lamports == -(SOL // 10) - 2 * PRIO


def test_deadline_close_pays_priority_both_ways() -> None:
    m = ShadowMarker(priority_fee_lamports=PRIO)
    m.submit("d1", "MINT", SOL // 10)
    m.on_observation("MINT", _state(5.0, 45.0))
    close = m.close("d1", _state(300.0, 45.0))
    assert close is not None
    assert close.priority_fees_lamports == 2 * PRIO
    assert close.pnl_lamports == close.proceeds_lamports - close.spend_lamports - 2 * PRIO
