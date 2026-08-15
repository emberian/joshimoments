"""Tests for the standing paper desk.

The gates here are the ones that cost real money to learn, so they are asserted rather
than assumed: pessimistic marking (entry at the NEXT observation, exit at the FIRST
observation after the trigger), censoring priced instead of dropped, one close-row builder
that cannot emit a partial row, propensities that construct the REAL tape contract type,
and the LP algebra where concentration is sign-preserving.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from shitcoims_cluster.pools import DREGG, NOSIS, WEAVE, WSOL_MINT
from shitcoims_paperdesk import BOOKS, Book
from shitcoims_paperdesk.books import DEAD_CURVE_LAMPORTS, DEPARTURE_TIMEOUT_S, MintBook
from shitcoims_paperdesk.feeds import (
    DRAWDOWN_UNKNOWN,
    BoardsSource,
    FirehoseSource,
    JsonlTail,
    MintObservation,
    PoolSwap,
    swap_as_mint_observation,
)
from shitcoims_paperdesk.friction import (
    BONDING_CURVE_TAKE_BPS,
    EFFECTIVE_TAKE_BPS,
    PRIORITY_FEE_LAMPORTS,
    Friction,
)
from shitcoims_paperdesk.ledger import Ledger, LedgerRow, close_row
from shitcoims_paperdesk.policy import DeskPolicy, MediumPolicy, ShortPolicy, TollPolicy, policy_for
from shitcoims_paperdesk.report import read_ledger, render
from shitcoims_paperdesk.toll import PoolFlow, TollBook, lp_fee_rate
from shitcoims_tape.schema import PropensityRecord, TapeError, WatchClose

SOL = 1_000_000_000
MINT = WEAVE
OTHER = NOSIS

T0 = 1_786_800_000.0


# ---------------------------------------------------------------------- fixtures


class AlwaysEnter(DeskPolicy):
    """A degenerate policy for testing BOOK mechanics without policy randomness.

    Ranges collapse to points, so ``draw`` is deterministic and the assertions below are
    about the state machine rather than about a seed.
    """

    book = Book.SHORT
    policy_id = "paperdesk-test-v1"
    ranges: ClassVar[dict[str, tuple[float, float]]] = {
        "hold_seconds": (3600.0, 3600.0),
        "take_profit": (0.20, 0.20),
        "stop_loss": (0.30, 0.30),
        "deterioration_drawdown": (0.25, 0.25),
        "deterioration_active_frac": (0.50, 0.50),
    }

    def rule(self, features: Any, t: Any) -> bool:
        return True


def observation(
    t: float,
    *,
    mint: str = MINT,
    vsol: float = 40.0,
    vtok: int = 10**15,
    source: str = "boards",
    complete: bool = False,
    last_trade: float | None = None,
    drawdown: float = 0.20,
) -> MintObservation:
    return MintObservation(
        mint=mint,
        source=source,
        t_ingest_unix=t,
        t_event_unix=last_trade,
        t_event_source="vendor:last_trade_timestamp" if last_trade else "absent:test",
        vsol_lamports=int(vsol * SOL),
        vtok_raw=vtok,
        usd_market_cap=50_000.0,
        ath_market_cap=100_000.0,
        drawdown_from_ath=drawdown,
        created_unix=t - 600.0,
        last_trade_unix=last_trade if last_trade is not None else t - 5.0,
        complete=complete,
    )


def make_book(tmp_path: Path, *, deterioration: bool = False, bankroll: int = 5 * SOL) -> MintBook:
    return MintBook(
        Book.SHORT,
        policy=AlwaysEnter(explore_eps=0.01, seed=0),
        friction=Friction(),
        ledger=Ledger(tmp_path, run_id="test-run"),
        bankroll_lamports=bankroll,
        deterioration_exit=deterioration,
    )


def rows_of(tmp_path: Path, kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(tmp_path.glob("ledger-*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                payload = json.loads(line)
                if payload.get("row") == kind:
                    out.append(payload)
    return out


# ---------------------------------------------------------------------- the ledger


def test_close_row_refuses_a_partial_record(tmp_path: Path) -> None:
    """The -151% bug, made unrepresentable: no spend, no row."""
    base = dict(
        run_id="r",
        book="short",
        position_id="p",
        decision_id="d",
        key=MINT,
        label=None,
        opened_at_unix=T0,
        closed_at_unix=T0 + 60,
        t_event_unix=None,
        t_event_source="absent:test",
        spend_lamports=0,
        proceeds_lamports=0,
        priority_fees_lamports=70_000,
        pnl_lamports=-70_000,
        pnl_pessimistic_lamports=-70_000,
        exit_reason="drain",
        censored=False,
        censor_reason=None,
        mark_source="observed",
        observations=1,
        entry_price=1.0,
        exit_price=1.0,
        peak_price=1.0,
    )
    with pytest.raises(ValueError, match="spend"):
        close_row(**base)
    ok = close_row(**{**base, "spend_lamports": 1000})
    assert ok.row == "close"


def test_close_row_requires_a_reason_for_censoring() -> None:
    with pytest.raises(ValueError, match="censored"):
        close_row(
            run_id="r", book="short", position_id="p", decision_id="d", key=MINT, label=None,
            opened_at_unix=T0, closed_at_unix=T0 + 1, t_event_unix=None, t_event_source="absent:test",
            spend_lamports=1, proceeds_lamports=0, priority_fees_lamports=0, pnl_lamports=-1,
            pnl_pessimistic_lamports=-1, exit_reason="departed", censored=True, censor_reason=None,
            mark_source="last_observed_before_trigger", observations=1,
            entry_price=1.0, exit_price=1.0, peak_price=1.0,
        )


def test_every_row_carries_two_clocks_and_a_reason_when_one_is_absent(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path, run_id="r")
    ledger.emit("heartbeat", "desk", t_ingest_unix=T0)
    ledger.close()
    row = rows_of(tmp_path, "heartbeat")[0]
    assert row["t_event"] is None
    # An absent event clock must say WHY it is absent, or a later reader will substitute
    # our ingest clock and measure a poll interval as latency.
    assert row["t_event_source"].startswith("absent:")
    assert row["t_ingest"].endswith("+00:00")


def test_ledger_row_refuses_to_shadow_its_own_envelope() -> None:
    row = LedgerRow(row="heartbeat", run_id="r", book="short", t_ingest_unix=T0, fields={"book": "x"})
    with pytest.raises(KeyError, match="collide"):
        row.to_json()


def test_unknown_row_kind_raises_rather_than_writing_an_unqueryable_row() -> None:
    with pytest.raises(KeyError, match="unknown ledger row kind"):
        LedgerRow(row="wat", run_id="r", book="short", t_ingest_unix=T0).to_json()


def test_desk_state_round_trips_atomically(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path, run_id="r")
    ledger.save_state({"short": {"counters": {"enters": 3}}})
    assert ledger.load_state()["short"]["counters"]["enters"] == 3
    # A desk killed mid-write must not lose the whole book, so the write is a replace.
    assert ledger.state_path.exists()


# ---------------------------------------------------------------------- policies


def test_propensity_is_the_probability_of_the_action_taken() -> None:
    policy = policy_for(Book.SHORT, explore_eps=0.05, seed=7)
    features = {
        "age_s": 120.0, "trade_recency_s": 3.0, "sol_in_curve": 40.0,
        "drawdown_from_ath": 0.10, "usd_market_cap": 1.0e6, "drawdown_known": 1.0,
    }
    seen = {"enter": 0, "skip": 0}
    for i in range(400):
        decision = policy.decide(
            key=MINT, features=features, now_unix=T0 + i,
            decided_at="2026-08-15T00:00:00+00:00", size_lamports=10**8,
        )
        assert 0.0 < decision.propensity <= 1.0
        expected = (0.95 if decision.verdict_pass else 0.05) if decision.acted else (
            0.05 if decision.verdict_pass else 0.95
        )
        assert decision.propensity == pytest.approx(expected)
        seen[decision.action] += 1
    # Both actions must occur or there is no overlap and no OPE.
    assert seen["enter"] > 0 and seen["skip"] > 0


def test_decision_constructs_the_real_tape_contract(tmp_path: Path) -> None:
    """The anti-mirror gate. A dict shaped like a PropensityRecord is not one."""
    decision = policy_for(Book.TOLL, seed=3).decide(
        key=WSOL_MINT,
        features={"eta": 2.0, "variance_ratio": 0.5},
        now_unix=T0,
        decided_at="2026-08-15T00:00:00+00:00",
        size_lamports=10**8,
    )
    record = decision.record()
    assert isinstance(record, PropensityRecord)
    assert record.policy_id == "paperdesk-toll-v1"
    assert record.envelope_verdict == "paper"

    from shitcoims_replay.ope import LoggedDecision

    LoggedDecision(action=record.action, propensity=record.propensity, reward=0.0)


def test_a_corrupt_key_is_refused_by_the_contract_not_written(tmp_path: Path) -> None:
    decision = policy_for(Book.SHORT, seed=1).decide(
        key=MINT.lower(),  # base58 is case-sensitive; the lowercased form is a DIFFERENT key
        features={
            "age_s": 60.0, "trade_recency_s": 1.0, "sol_in_curve": 40.0,
            "drawdown_from_ath": 0.1, "usd_market_cap": 1e6, "drawdown_known": 1.0,
        },
        now_unix=T0, decided_at="2026-08-15T00:00:00+00:00", size_lamports=1,
    )
    with pytest.raises(TapeError):
        decision.record()


def test_unknown_drawdown_does_not_read_as_the_shallowest_candidate() -> None:
    """``-1.0 < 0.50`` is true. The sentinel must not be the best-looking coin on the desk."""
    policy = ShortPolicy(seed=0)
    thresholds = dict.fromkeys(policy.ranges, 0.0)
    thresholds.update(
        dd_max=0.50, sol_min=10.0, mcap_min=1.0e4, max_trade_recency_s=600.0,
        min_age_s=20.0, max_age_s=3600.0,
    )
    known = {
        "age_s": 1e6, "trade_recency_s": 5.0, "sol_in_curve": 40.0,
        "drawdown_from_ath": 0.20, "usd_market_cap": 1e5, "drawdown_known": 1.0,
    }
    assert policy.rule(known, thresholds)
    # Same coin, drawdown unknown, and far outside the liveness age band: the sentinel
    # must NOT sneak through the shallow-drawdown branch.
    unknown = {**known, "drawdown_from_ath": DRAWDOWN_UNKNOWN, "drawdown_known": 0.0}
    assert not policy.rule(unknown, thresholds)


def test_short_policy_has_a_liveness_branch_for_coins_with_no_ath() -> None:
    policy = ShortPolicy(seed=0)
    thresholds = dict.fromkeys(policy.ranges, 0.0)
    thresholds.update(
        dd_max=0.50, sol_min=10.0, mcap_min=1.0e4, max_trade_recency_s=600.0,
        min_age_s=20.0, max_age_s=3600.0,
    )
    fresh = {
        "age_s": 120.0, "trade_recency_s": 5.0, "sol_in_curve": 40.0,
        "drawdown_from_ath": DRAWDOWN_UNKNOWN, "usd_market_cap": 0.0, "drawdown_known": 0.0,
    }
    assert policy.rule(fresh, thresholds)
    assert not policy.rule({**fresh, "age_s": 5.0}, thresholds)  # too young: a snipe


def test_medium_policy_requires_survivorship_not_a_price_view() -> None:
    policy = MediumPolicy(seed=0)
    thresholds = dict.fromkeys(policy.ranges, 0.0)
    thresholds.update(min_observed_s=7200.0, min_observations=8.0, dd_max=0.90, sol_min=5.0)
    base = {
        "observed_seconds": 10_000.0, "observations": 20.0, "drawdown_known": 1.0,
        "drawdown_from_ath": 0.60, "sol_in_curve": 30.0,
    }
    assert policy.rule(base, thresholds)
    assert not policy.rule({**base, "observed_seconds": 100.0}, thresholds)


def test_toll_gate_is_eta_times_duty_against_vr() -> None:
    policy = TollPolicy(seed=0)
    thresholds = {"assumed_duty": 0.95, "gate_margin": 1.0}
    assert policy.rule({"eta": 2.0, "variance_ratio": 1.0}, thresholds)
    # The measured regime: every cluster eta is below 1 against VR near 1.
    assert not policy.rule({"eta": 0.235, "variance_ratio": 1.0}, thresholds)
    assert not policy.rule({"eta": 0.0, "variance_ratio": 1.0}, thresholds)


def test_thresholds_supplied_by_the_caller_are_the_thresholds_logged() -> None:
    policy = TollPolicy(seed=1)
    fixed = {k: (lo + hi) / 2 for k, (lo, hi) in policy.ranges.items()}
    decision = policy.decide(
        key=WSOL_MINT, features={"eta": 5.0, "variance_ratio": 0.5}, now_unix=T0,
        decided_at="2026-08-15T00:00:00+00:00", size_lamports=1, thresholds=fixed,
    )
    assert decision.thresholds == fixed


def test_every_book_has_a_policy() -> None:
    for book in BOOKS:
        assert policy_for(book).book is book


# ---------------------------------------------------------------------- friction


def test_friction_uses_measured_constants_and_never_a_free_venue() -> None:
    friction = Friction()
    assert friction.priority_fee_lamports == PRIORITY_FEE_LAMPORTS == 35_000
    # A PumpSwap taker pays ALL THREE legs (LP + protocol + creator). The old 20 bps
    # constant was the vault-shortfall measurement, which structurally sees only the LP
    # leg — the other two move from the user's account, not the vault. Every PumpSwap
    # take must therefore be at least LP(20) + protocol(~5) + creator floor: a value
    # below 100 bps on a PumpSwap pool means the vault-shortfall bug is back.
    # (studies/RESULT_dregg_boundary.md; the operator's own ~25 bps DREGG take exists
    # because the creator leg returns to them — that belongs to a future DREGG book,
    # never to this desk's ordinary-taker model.)
    for label in ("DREGG/SOL", "SOLVE/SOL", "nosis/SOL", "weave/SOL"):
        assert friction.take_bps_for(label) == EFFECTIVE_TAKE_BPS[label] >= 100
    assert friction.take_bps_for("weave/SOL") > friction.take_bps_for("DREGG/SOL")
    # An unknown venue costs the curve rate, never zero: a free venue is where a paper
    # desk "discovers" an edge that is really a missing cost.
    assert friction.take_bps_for("who/knows") == BONDING_CURVE_TAKE_BPS
    assert friction.take_bps_for(None) == BONDING_CURVE_TAKE_BPS


def test_a_two_dollar_clip_pays_about_two_point_four_percent_round_trip() -> None:
    friction = Friction()
    pool = 30 * SOL
    size = friction.size_lamports(pool, bankroll_cap_lamports=SOL)
    cost = friction.round_trip(size, pool, take_bps=BONDING_CURVE_TAKE_BPS)
    assert 0.020 < cost < 0.030


# ---------------------------------------------------------------------- book mechanics


def test_entry_fills_at_the_next_observation_never_at_the_deciding_one(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    first = observation(T0)
    book.observe(first, source_stale=False)
    book.consider(first)
    assert book.pending and not book.positions  # decided, not filled

    second = observation(T0 + 30)
    book.observe(second, source_stale=False)
    assert not book.pending and len(book.positions) == 1
    position = next(iter(book.positions.values()))
    assert position.entry_unix == T0 + 30
    fill = rows_of(tmp_path, "fill")[0]
    assert fill["fill_lag_s"] == pytest.approx(30.0)


def test_exit_fills_at_the_first_observation_after_the_trigger(tmp_path: Path) -> None:
    """The trigger observation cannot also be the fill: that is trading on the tick that
    told you to trade."""
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)  # fill
    position = next(iter(book.positions.values()))

    # +25% on the price ratio, above the +20% take-profit. This ARMS it, does not fill it.
    book.observe(observation(T0 + 60, vsol=50.0), source_stale=False)
    assert position.armed_reason == "take_profit"
    assert not rows_of(tmp_path, "close")

    book.observe(observation(T0 + 90, vsol=52.0), source_stale=False)
    close = rows_of(tmp_path, "close")[0]
    assert close["exit_reason"] == "take_profit"
    assert close["mark_source"] == "observed"
    assert close["censored"] is False
    assert close["closed_at_unix"] == T0 + 90


def test_departure_is_marked_out_and_the_pessimistic_figure_is_carried_too(
    tmp_path: Path,
) -> None:
    """The +21.77% -> -12.24% correction, made structural.

    The headline number marks the position at the last price observed at-or-before the
    trigger; the pessimistic number treats departure as a total loss. Both are on the row,
    so neither can be quoted without the other being available.
    """
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    book.sweep(T0 + 30 + DEPARTURE_TIMEOUT_S + 1, source_stale=False)

    close = rows_of(tmp_path, "close")[0]
    assert close["censored"] is True
    assert close["censor_reason"] == str(WatchClose.DISPLACED)
    assert close["mark_source"] == "last_observed_before_trigger"
    assert close["proceeds_lamports"] > 0            # marked out, not dropped
    assert close["pnl_pessimistic_lamports"] == -close["spend_lamports"] - close[
        "priority_fees_lamports"
    ]
    assert close["pnl_lamports"] > close["pnl_pessimistic_lamports"]


def test_a_stale_source_censors_as_observer_lost_not_displaced(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    book.sweep(T0 + 30 + DEPARTURE_TIMEOUT_S + 1, source_stale=True)
    close = rows_of(tmp_path, "close")[0]
    assert close["censor_reason"] == str(WatchClose.OBSERVER_LOST)


def test_a_drained_curve_is_a_total_loss_and_both_figures_agree(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    dead = DEAD_CURVE_LAMPORTS / SOL / 2
    book.observe(observation(T0 + 60, vsol=dead), source_stale=False)
    close = rows_of(tmp_path, "close")[0]
    assert close["exit_reason"] == "curve_drained"
    assert close["mark_source"] == "total_loss"
    assert close["proceeds_lamports"] == 0
    assert close["pnl_lamports"] == close["pnl_pessimistic_lamports"]


def test_graduation_is_a_terminal_outcome_not_a_loss(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    book.observe(observation(T0 + 60, complete=True), source_stale=False)
    close = rows_of(tmp_path, "close")[0]
    assert close["exit_reason"] == "graduated"
    assert close["censored"] is False
    assert close["proceeds_lamports"] > 0


def test_stop_loss_arms_on_the_downside_too(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    book.observe(observation(T0 + 60, vsol=20.0), source_stale=False)  # -50%
    book.observe(observation(T0 + 90, vsol=20.0), source_stale=False)
    close = rows_of(tmp_path, "close")[0]
    assert close["exit_reason"] == "stop_loss"
    assert close["pnl_lamports"] < 0


def test_deterioration_exit_needs_both_surviving_signals(tmp_path: Path) -> None:
    """Only the two signals that survived RESULT_deterioration.md, and only together."""
    book = make_book(tmp_path, deterioration=True)
    book.observe(observation(T0, last_trade=T0), source_stale=False)
    book.consider(observation(T0, last_trade=T0))
    book.observe(observation(T0 + 10, last_trade=T0 + 10), source_stale=False)
    position = next(iter(book.positions.values()))

    # The path is chosen so NEITHER bracket leg can fire: it peaks at +18.75% (under the
    # +20% take-profit) and bottoms at -20% from entry (above the -30% stop). Only the
    # deterioration conjunction is left to explain an exit.
    def step(i: int, vsol: float) -> None:
        t = T0 + 10 + 10 * i
        book.observe(observation(t, vsol=vsol, last_trade=t), source_stale=False)

    for i in range(1, 14):
        step(i, 47.5)  # ratio 1.1875, sets the peak
    for i in range(14, 26):
        step(i, 32.0)  # ratio 0.80; 32.6% off the peak, every observation freshly traded

    assert position.drawdown_from_peak > 0.25
    assert position.active_frac > 0.5
    assert position.armed_reason == "deterioration"

    step(26, 32.0)  # the first observation AFTER the trigger is where it fills
    close = rows_of(tmp_path, "close")[0]
    assert close["exit_reason"] == "deterioration"
    assert close["mark_source"] == "observed"


def test_every_decision_is_logged_including_the_skips(tmp_path: Path) -> None:
    """Rejected candidates cost nothing on paper and buy the selection-vs-luck split."""
    book = MintBook(
        Book.SHORT,
        policy=policy_for(Book.SHORT, seed=11),
        friction=Friction(),
        ledger=Ledger(tmp_path, run_id="test-run"),
        bankroll_lamports=5 * SOL,
        decision_cooldown_s=0.0,
    )
    for i in range(30):
        obs = observation(T0 + i, mint=MINT if i % 2 else OTHER, drawdown=0.9)
        book.observe(obs, source_stale=False)
        book.consider(obs)
    decisions = rows_of(tmp_path, "decision")
    assert len(decisions) >= 20
    assert {d["action"] for d in decisions} <= {"enter", "skip"}
    assert all(0.0 < d["propensity"] <= 1.0 for d in decisions)


def test_bankroll_is_a_hard_cap_and_the_block_is_logged(tmp_path: Path) -> None:
    book = make_book(tmp_path, bankroll=10_000)  # far below any B*
    obs = observation(T0)
    book.observe(obs, source_stale=False)
    book.consider(obs)
    assert not book.pending
    decision = rows_of(tmp_path, "decision")[0]
    assert decision["blocked"] in {"bankroll", None}


def test_drain_writes_a_full_row_through_the_same_builder(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    book.drain(T0 + 100)
    close = rows_of(tmp_path, "close")[0]
    for required in (
        "spend_lamports", "proceeds_lamports", "priority_fees_lamports", "pnl_lamports",
        "pnl_pessimistic_lamports", "net_return", "exit_reason", "censored", "mark_source",
        "observations", "entry_price", "exit_price", "peak_price", "holding_seconds",
    ):
        assert required in close, required
    assert close["exit_reason"] == "drain"


def test_book_state_round_trips(tmp_path: Path) -> None:
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    state = json.loads(json.dumps(book.state()))
    revived = make_book(tmp_path)
    revived.restore(state)
    assert len(revived.positions) == 1
    assert next(iter(revived.positions.values())).tokens_raw == next(
        iter(book.positions.values())
    ).tokens_raw


# ---------------------------------------------------------------------- feeds


def test_jsonl_tail_buffers_a_half_written_final_line(tmp_path: Path) -> None:
    path = tmp_path / "feed.jsonl"
    path.write_text('{"a":1}\n{"a":2')
    tail = JsonlTail(lambda now: [path], from_start=True)
    assert [r["a"] for r in tail.poll(T0)] == [1]
    with path.open("a") as fh:
        fh.write('}\n{"a":3}\n')
    assert [r["a"] for r in tail.poll(T0 + 1)] == [2, 3]


def test_jsonl_tail_attaches_at_end_by_default(tmp_path: Path) -> None:
    path = tmp_path / "feed.jsonl"
    path.write_text('{"a":1}\n')
    tail = JsonlTail(lambda now: [path])
    assert list(tail.poll(T0)) == []  # history is not replayed as if it were live
    with path.open("a") as fh:
        fh.write('{"a":2}\n')
    assert [r["a"] for r in tail.poll(T0 + 1)] == [2]


def test_boards_source_reads_entries_and_snapshot_members(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    day = datetime.fromtimestamp(T0, tz=UTC).strftime("%Y%m%d")
    path = tmp_path / f"boards-{day}.jsonl"
    coin = {
        "mint": MINT, "symbol": "W", "rank": 0, "usd_market_cap": 50_000.0,
        "ath_market_cap": 100_000.0, "drawdown_from_ath": 0.5, "reply_count": 3,
        "is_currently_live": False, "complete": False, "created_unix": T0 - 900,
        "last_trade_unix": T0 - 4, "virtual_sol_reserves": 40 * SOL,
        "virtual_token_reserves": 10**15, "t_ingest": T0,
    }
    path.write_text(
        json.dumps({"kind": "board_entry", "board": "last_reply", **coin}) + "\n"
        + json.dumps({"kind": "board_snapshot", "board": "market_cap", "n": 1, "members": [coin]})
        + "\n"
        + json.dumps({"kind": "board_exit", "board": "market_cap", "mint": MINT, "t_ingest": T0})
        + "\n"
    )
    source = BoardsSource(tmp_path, from_start=True)
    got = source.poll(T0)
    assert len(got) == 2
    assert got[0].board == "last_reply" and got[1].board == "market_cap"
    assert got[0].drawdown_known and got[0].sol_in_curve == 40.0
    assert source.events == 2


def test_firehose_dedupes_on_signature_and_keeps_the_null_event_clock(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    day = datetime.fromtimestamp(T0, tz=UTC).strftime("%Y-%m-%d")
    path = tmp_path / f"{day}.jsonl"
    row = {
        "kind": "new_token",
        "t_ingest": datetime.fromtimestamp(T0, tz=UTC).isoformat(),
        "t_event": None,
        "t_event_source": "absent:vendor_payload_carries_no_event_clock",
        "mint": MINT,
        "signature": "s" * 88,
        "payload": {"vSolInBondingCurve": 30.5, "vTokensInBondingCurve": 1.05e9, "symbol": "W"},
    }
    path.write_text((json.dumps(row) + "\n") * 3)  # the real duplicate hazard
    source = FirehoseSource(tmp_path, from_start=True)
    got = source.poll(T0)
    assert len(got) == 1
    assert source.duplicates_dropped == 2
    assert got[0].t_event_unix is None
    assert got[0].t_event_source.startswith("absent:")
    assert got[0].drawdown_from_ath == DRAWDOWN_UNKNOWN  # never 0.0


def _swap(
    price: float,
    t: float,
    *,
    quote: str = WSOL_MINT,
    base: str = WEAVE,
    pool: str = "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
    label: str = "weave/SOL",
) -> PoolSwap:
    return PoolSwap(
        pool=pool,
        label=label,
        dex="pumpswap",
        t_ingest_unix=t,
        t_event_unix=t,
        t_event_source="chain:block_time",
        price=price,
        price_source="vault_ratio_marginal",
        quote_notional=10.0,
        quote_reserve=200.0,
        base_reserve=200.0 / price,
        base_mint=base,
        quote_mint=quote,
        row_id=f"row-{label}-{t}-{price}",
    )


def test_a_sol_quoted_swap_becomes_a_curve_observation(tmp_path: Path) -> None:
    obs = swap_as_mint_observation(_swap(0.001, T0))
    assert obs is not None
    assert obs.pool_label == "weave/SOL"
    assert obs.mint == WEAVE
    assert obs.drawdown_from_ath == DRAWDOWN_UNKNOWN


def test_a_token_token_swap_has_no_lamport_curve_and_says_so() -> None:
    """Inventing a cross rate here would put a fabricated price in a measured field."""
    assert swap_as_mint_observation(_swap(2.0, T0, quote=NOSIS, base=DREGG)) is None


# ---------------------------------------------------------------------- the toll book


def test_lp_fee_rate_is_the_lp_share_after_the_protocol_cut() -> None:
    # weave/nosis: 6.0% base, protocol takes 10%.
    assert lp_fee_rate("QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD") == pytest.approx(0.054)
    assert lp_fee_rate("FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD") == pytest.approx(0.045)
    # PumpSwap: the 0.20% LP leg, never the 1.44% taker leg.
    assert lp_fee_rate("GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn") == pytest.approx(0.0020)


def test_eta_dilutes_against_the_liquidity_already_in_the_pool() -> None:
    """A paper position captures its SHARE of the flow, not all of it.

    Computing eta against the position's own capacitance alone read eta = 13.7 on a
    1.25-SOL paper position in SOLVE/SOL, where the pool-level measurement in
    RESULT_circuit_theory.md is 0.055 -- a 250x false positive that would have opened the
    desk into every pool the studies proved -EV.
    """
    flow = PoolFlow(pool="p", label="weave/SOL")
    for i in range(40):
        flow.ingest(_swap(0.001 * (1.0 + 0.01 * (i % 5)), T0 + i * 400))
    assert flow.pool_capacitance == pytest.approx(flow.tvl_quote / 4.0)

    tiny = flow.eta(f_lp=0.002, position_capacitance=1e-9)
    pool_level = 2 * 0.002 * flow.notional_total / (flow.pool_capacitance * flow.realised_variance)
    assert tiny == pytest.approx(pool_level, rel=1e-6)  # converges to the study's quantity

    # A position the size of the pool's own capacitance halves eta: it is now half the
    # liquidity, so it earns half the fees against its own full LVR.
    same_size = flow.eta(f_lp=0.002, position_capacitance=flow.pool_capacitance)
    assert same_size == pytest.approx(tiny / 2.0, rel=1e-6)
    assert same_size < tiny


def test_flow_window_is_measured_on_the_flows_own_clock(tmp_path: Path) -> None:
    """A stale tape must read as 'flow from N hours ago', never as 'no flow'."""
    flow = PoolFlow(pool="p", label="weave/SOL")
    for i in range(30):
        flow.ingest(_swap(0.001 * (1.0 + 0.01 * (i % 5)), T0 + i * 400))
    flow.prune(T0 + 86_400 * 3)  # pruning three days later, against wall time
    assert flow.notional_total > 0
    assert len(flow.grid) > 1


def test_out_of_order_rows_are_counted_not_appended_to_the_series() -> None:
    """The tape is day-partitioned on CHAIN time; a boundary can hand back an older row."""
    flow = PoolFlow(pool="p", label="weave/SOL")
    flow.ingest(_swap(0.001, T0 + 1000))
    flow.ingest(_swap(0.002, T0))  # older than what we already have
    assert flow.out_of_order == 1
    assert len(flow.grid) == 1
    assert flow.last_price == 0.001


def test_concentration_is_sign_preserving() -> None:
    """Both terms of the LP ledger scale with C, so narrowing cannot flip the sign.

    Concretely: with the range shape held fixed, fees and impermanent loss are both linear
    in ``ell``, so ``fees + IL`` scales without changing sign. A four-fold concentration
    multiplies the answer by four; it does not rescue it.
    """
    from studies.lp_strategy import SpotPosition

    displacement = 0.35
    for f_lp, expected_sign in ((0.001, -1), (0.20, +1)):
        nets = []
        for value in (100.0, 400.0):
            position = SpotPosition.from_value(value, a=0.5, b=0.5)
            fees = f_lp * position.ell * position.overlap(0.0, displacement)
            nets.append(fees + position.il_quote(displacement))
        assert (1 if nets[0] > 0 else -1) == expected_sign
        assert (1 if nets[1] > 0 else -1) == expected_sign  # sign PRESERVED
        assert nets[1] == pytest.approx(nets[0] * 4.0, rel=1e-9)  # magnitude levered 4x


def test_fees_accrue_only_on_the_part_of_a_move_inside_the_range(tmp_path: Path) -> None:
    from studies.lp_strategy import SpotPosition

    position = SpotPosition.from_value(1000.0, a=0.2, b=0.2)
    assert position.overlap(0.0, 0.1) == pytest.approx(0.1)   # entirely inside
    assert position.overlap(0.0, 0.5) == pytest.approx(0.2)   # clipped at the edge
    assert position.overlap(0.5, 0.9) == pytest.approx(0.0)   # entirely outside: no fee


def test_toll_book_gate_row_reports_eta_vr_and_required_duty(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path, run_id="test-run")
    book = TollBook(
        policy=policy_for(Book.TOLL, seed=5),
        friction=Friction(),
        ledger=ledger,
        bankroll_lamports=5 * SOL,
        gate_interval_s=0.0,
    )
    for i in range(60):
        book.observe(_swap(0.001 * (1.0 + 0.02 * ((i * 7) % 11 - 5) / 5), T0 + i * 320))
    book.gate(T0 + 60 * 320)
    gates = rows_of(tmp_path, "gate")
    assert gates, "the gate must report even when it refuses"
    gate = gates[-1]
    assert gate["label"] == "weave/SOL"
    assert gate["f_lp"] == pytest.approx(0.0020)
    assert gate["realised_variance"] > 0
    if gate["eta"] is not None and gate["variance_ratio"] is not None:
        assert gate["required_duty"] == pytest.approx(gate["variance_ratio"] / gate["eta"])


def test_toll_book_refuses_to_open_on_a_stale_tape(tmp_path: Path) -> None:
    """A cold collector is not a quiet market, and the gate still reports on it."""
    ledger = Ledger(tmp_path, run_id="test-run")
    book = TollBook(
        policy=policy_for(Book.TOLL, seed=5),
        friction=Friction(),
        ledger=ledger,
        bankroll_lamports=5 * SOL,
        gate_interval_s=0.0,
    )
    for i in range(60):
        book.observe(_swap(0.001 * (1.0 + 0.01 * (i % 7)), T0 + i * 320))
    book.gate(T0 + 60 * 320 + 86_400)  # a day after the last swap
    gate = rows_of(tmp_path, "gate")[-1]
    assert gate["refusal"] in {"tape_stale", "insufficient_flow", "no_quote_rate"}
    assert not book.positions


def test_duty_cycle_is_measured_from_observed_in_range_time() -> None:
    from shitcoims_paperdesk.toll import PaperRange

    position = PaperRange(
        position_id="p", decision_id="d", pool="p", label="weave/SOL", quote_mint=WSOL_MINT,
        base_mint=WEAVE, dex="pumpswap", f_lp=0.002, half_width=0.5, rebalance_trigger=0.05,
        opened_unix=T0, opened_event_unix=T0, opened_t_event=T0,
        opened_t_event_source="chain:block_time",
        deadline_unix=T0 + 86400, value_quote=100.0, spend_lamports=10**8, entry_price=1.0,
        ref_price=1.0, a=0.5, b=0.5, ell=100.0, last_price=1.0, last_unix=T0,
        last_t_event=T0, last_t_event_source="chain:block_time", peak_price=1.0,
    )
    position.in_range_seconds = 494.0
    position.total_seconds = 1000.0
    assert position.duty_cycle == pytest.approx(0.494)  # the DREGG/nosis number


# ---------------------------------------------------------------------- the report


def test_report_renders_on_an_empty_ledger(tmp_path: Path) -> None:
    text = render(read_ledger(tmp_path))
    assert "PAPER DESK" in text
    assert "CROSS-BOOK" in text
    for book in BOOKS:
        assert str(book) in text


def test_report_prints_both_the_marked_and_the_pessimistic_return(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path, run_id="r")
    for i, (censored, proceeds) in enumerate([(False, 120_000_000), (True, 90_000_000)]):
        ledger.write(
            close_row(
                run_id="r", book="short", position_id=f"p{i}", decision_id=f"d{i}", key=MINT,
                label="boards", opened_at_unix=T0, closed_at_unix=T0 + 600,
                t_event_unix=None, t_event_source="absent:test",
                spend_lamports=100_000_000, proceeds_lamports=proceeds,
                priority_fees_lamports=70_000,
                pnl_lamports=proceeds - 100_000_000 - 70_000,
                pnl_pessimistic_lamports=(0 if censored else proceeds) - 100_000_000 - 70_000,
                exit_reason="departed" if censored else "take_profit",
                censored=censored,
                censor_reason=str(WatchClose.DISPLACED) if censored else None,
                mark_source="last_observed_before_trigger" if censored else "observed",
                observations=4, entry_price=1.0, exit_price=1.2, peak_price=1.3,
            )
        )
    ledger.close()
    rows = read_ledger(tmp_path)
    text = render(rows)
    assert "pess%" in text and "cens%" in text
    assert "CENSOR" in text.upper() or "censored" in text
    # The two figures must genuinely differ, or the column is decoration.
    from shitcoims_paperdesk.report import _weighted_return

    marked = _weighted_return(rows.closes, "pnl_lamports")
    pessimistic = _weighted_return(rows.closes, "pnl_pessimistic_lamports")
    assert marked > pessimistic


def test_report_reads_a_desk_run_end_to_end(tmp_path: Path) -> None:
    """The whole pipe: book -> ledger -> report, with no hand-built rows."""
    book = make_book(tmp_path)
    book.observe(observation(T0), source_stale=False)
    book.consider(observation(T0))
    book.observe(observation(T0 + 30), source_stale=False)
    book.observe(observation(T0 + 60, vsol=50.0), source_stale=False)
    book.observe(observation(T0 + 90, vsol=52.0), source_stale=False)
    book.ledger.close()
    rows = read_ledger(tmp_path)
    assert len(rows.closes) == 1
    assert len(rows.decisions) == 1
    text = render(rows)
    assert "short" in text
    assert "PROPENSITY LOG" in text


# ---------------------------------------------------------------------- the desk loop


def test_the_desk_refuses_to_fill_an_observation_it_could_not_have_acted_on(
    tmp_path: Path,
) -> None:
    """The bootstrap trap: days of historical tape are a MEASUREMENT, not a fill.

    The toll book's flow window is deliberately seeded from historical cluster-tape rows,
    because eta and VR are not estimable without hours of price series. Those same rows
    must never reach a position book: a paper position filled at a two-day-old price is
    lookahead of the purest kind, and it would also open already past its own horizon.
    """
    from shitcoims_paperdesk.desk import MAX_ACTIONABLE_AGE_S, Desk, DeskConfig

    desk = Desk(DeskConfig(minutes=0.0, tape_from_start=False), ledger=Ledger(tmp_path, run_id="r"))
    now = T0
    assert desk._actionable(observation(now - 10.0), now)
    assert not desk._actionable(observation(now - MAX_ACTIONABLE_AGE_S - 1.0), now)
    assert desk.stale_observations == 1


def test_a_toll_position_takes_its_horizon_from_the_desk_clock(tmp_path: Path) -> None:
    """A position stamped with the tape's clock would open past its own deadline."""
    ledger = Ledger(tmp_path, run_id="r")
    book = TollBook(
        policy=policy_for(Book.TOLL, seed=2),
        friction=Friction(),
        ledger=ledger,
        bankroll_lamports=5 * SOL,
        gate_interval_s=0.0,
    )
    # Flow whose CHAIN time is two days old, observed by the desk right now.
    chain_t = T0 - 2 * 86_400
    for i in range(40):
        swap = _swap(0.001 * (1.0 + 0.02 * (i % 5)), chain_t + i * 320)
        book.observe(swap, now=T0 + i)
    flow = next(iter(book.flows.values()))
    assert flow.last_unix == pytest.approx(chain_t + 39 * 320)  # accrual clock is the chain
    # The gate refuses on staleness, which is the honest outcome, and says so.
    book.gate(T0 + 100)
    gate = rows_of(tmp_path, "gate")[-1]
    assert gate["tape_staleness_s"] > 86_400
    assert gate["refusal"] == "tape_stale"
    # ... and the ledger row is written on OUR day, not the tape's.
    assert gate["t_ingest"][:10] != "2026-08-13"


def test_desk_heartbeat_reports_source_staleness_per_source(tmp_path: Path) -> None:
    from shitcoims_paperdesk.desk import Desk, DeskConfig

    desk = Desk(DeskConfig(minutes=0.0, tape_from_start=False), ledger=Ledger(tmp_path, run_id="r"))
    desk.open_windows(T0)
    desk.heartbeat(T0 + 10)
    desk.ledger.close()
    beat = rows_of(tmp_path, "heartbeat")[-1]
    assert set(beat["sources"]) == {"boards", "firehose", "callouts", "mint_refresh", "cluster_tape"}
    for state in beat["sources"].values():
        assert "silent_seconds" in state and "stale" in state
    assert set(beat["books"]) == {"short", "medium", "toll"}


def test_a_source_going_quiet_closes_its_window_as_observer_lost(tmp_path: Path) -> None:
    """A cold collector must be distinguishable from a quiet market."""
    from shitcoims_paperdesk.desk import STALE_AFTER_S, Desk, DeskConfig

    desk = Desk(DeskConfig(minutes=0.0, tape_from_start=False), ledger=Ledger(tmp_path, run_id="r"))
    desk.open_windows(T0)
    desk.check_windows(T0 + STALE_AFTER_S + 1)
    desk.ledger.close()
    closes = rows_of(tmp_path, "watch_close")
    assert closes
    assert all(c["reason"] == str(WatchClose.OBSERVER_LOST) for c in closes)
    assert all(c["informative"] for c in closes)


def test_a_position_is_never_marked_against_a_different_price_basis(tmp_path: Path) -> None:
    """A curve quote and a pool quote for the same mint are on incomparable scales.

    The curve carries 30+ SOL of VIRTUAL reserves against ~1e15 raw tokens; the graduated
    pool carries real vault balances. Crossing them produces a price ratio with no meaning
    -- and a meaningless ratio trips the stop-loss on the very next observation, which
    reads in the ledger as a real loss with a real timestamp.
    """
    book = make_book(tmp_path)
    # DREGG/SOL, whose MEASURED effective take is 20 bps. weave/SOL would be refused here
    # on friction alone -- its measured take is ~909 bps, so a round trip costs ~18% and
    # the desk correctly declines to trade it at any threshold.
    dregg = dict(pool="2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU", label="DREGG/SOL", base=DREGG)
    pool_obs = swap_as_mint_observation(_swap(0.001, T0, **dregg))
    assert pool_obs is not None
    book.observe(pool_obs, source_stale=False)
    book.consider(pool_obs)
    assert book.pending

    # A CURVE observation of the same mint must neither fill nor mark the pool position.
    curve = observation(T0 + 10, mint=pool_obs.mint)
    assert curve.pool_label is None
    book.observe(curve, source_stale=False)
    assert book.pending and not book.positions  # refused the cross-basis fill

    later = swap_as_mint_observation(_swap(0.001, T0 + 20, **dregg))
    assert later is not None
    book.observe(later, source_stale=False)
    assert len(book.positions) == 1
    position = next(iter(book.positions.values()))
    assert position.label == "DREGG/SOL"

    # A curve quote 400x away must not mark it, so no bogus stop-loss can fire.
    book.observe(observation(T0 + 30, mint=pool_obs.mint), source_stale=False)
    assert position.armed_reason is None
    assert not rows_of(tmp_path, "close")
