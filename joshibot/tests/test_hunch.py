"""Tests for the hunch loop: capture, transport, the operator book, and the scoring.

The gates asserted here are the ones that would silently corrupt the ONE signal this whole
feature exists to measure:

* the utterance is stored VERBATIM and is never replaced by its parse;
* resolution REFUSES on ambiguity rather than picking (the address-fabrication scars);
* the operator book inherits the wiggle book's execution unchanged, so a difference between
  the two arms is a difference in selection and not in machinery;
* the gates are computed and CANNOT veto -- including the ghost-town depth leg, which warns
  and tags instead;
* propensity is exactly 1.0 and the action is always ``enter``;
* a hunch survives a restart, is idempotent in ``hunch_id``, and a hunch the desk was not
  around to see is refused as censored rather than backfilled into a fabricated fill.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from shitcoims_cluster.pools import NOSIS, WEAVE
from shitcoims_paperdesk import BOOKS, Book
from shitcoims_paperdesk.feeds import MintObservation
from shitcoims_paperdesk.friction import Friction
from shitcoims_paperdesk.hunch import (
    HUNCH_ACTIONABLE_S,
    KIND_CLAIMS,
    Hunch,
    HunchSource,
    append_hunch,
    default_horizon_s,
    new_hunch_id,
    read_hunches,
)
from shitcoims_paperdesk.ledger import Ledger
from shitcoims_paperdesk.operator import (
    ANY_BASIS,
    OPERATOR_SOURCE,
    WAIT_TIMEOUT_S,
    OperatorBook,
    brier,
)
from shitcoims_paperdesk.policy import OperatorPolicy, WigglePolicy, policy_for
from shitcoims_paperdesk.readout import Candidate, is_mint, resolve
from shitcoims_paperdesk.report import read_ledger, render
from shitcoims_paperdesk.wiggle import WiggleBook

SOL = 1_000_000_000
MINT = WEAVE
OTHER = NOSIS
T0 = 1_786_800_000.0


# ---------------------------------------------------------------------- fixtures


def observation(
    at: float,
    *,
    mint: str = MINT,
    vsol: int = 40 * SOL,
    vtok: int = 900_000_000_000_000,
    drawdown: float = 0.75,
    last_trade: float | None = None,
    complete: bool = False,
    pool_label: str | None = None,
) -> MintObservation:
    return MintObservation(
        mint=mint,
        source="boards",
        t_ingest_unix=at,
        t_event_unix=last_trade,
        t_event_source="vendor:last_trade_timestamp",
        vsol_lamports=vsol,
        vtok_raw=vtok,
        usd_market_cap=45_000.0,
        ath_market_cap=180_000.0,
        drawdown_from_ath=drawdown,
        created_unix=at - 7200.0,
        last_trade_unix=last_trade if last_trade is not None else at - 20.0,
        complete=complete,
        board="market_cap",
        symbol="WEAVE",
        pool_label=pool_label,
    )


def make_operator(tmp_path: Path, *, bankroll: int = 5 * SOL) -> OperatorBook:
    return OperatorBook(
        Book.OPERATOR,
        policy=policy_for(Book.OPERATOR, explore_eps=0.05, seed=7),
        friction=Friction(),
        ledger=Ledger(tmp_path, run_id="test-operator"),
        bankroll_lamports=bankroll,
        max_positions=8,
        clip_lamports=100_000_000,
        decision_cooldown_s=120.0,
    )


def hunch_of(
    at: float = T0,
    *,
    mint: str = MINT,
    kind: str = "wiggle",
    utterance: str = "gonna wiggle for a bit",
    horizon: float | None = None,
    hunch_id: str | None = None,
) -> Hunch:
    return Hunch(
        hunch_id=hunch_id or new_hunch_id(mint, at),
        run_id="test",
        mint=mint,
        symbol="WEAVE",
        kind=kind,
        claim=KIND_CLAIMS[kind],
        utterance=utterance,
        confidence=0.65,
        horizon_s=horizon if horizon is not None else default_horizon_s(kind),
        size_lamports=100_000_000,
        t_gesture_unix=at,
        t_ingest_unix=at,
    )


def rows_of(tmp_path: Path, kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(tmp_path.glob("ledger-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                row = json.loads(line)
                if row.get("row") == kind:
                    out.append(row)
    return out


# ---------------------------------------------------------------------- the tape


def test_the_utterance_is_stored_verbatim_and_survives_a_round_trip(tmp_path: Path) -> None:
    """The parse is lossy; the words are the corpus. Nothing may normalise them."""
    said = '  IDK i think this "wiggles" for a bit?? ~~ 🤞  \tmaybe  '
    hunch = hunch_of(utterance=said)
    path = tmp_path / "hunches.jsonl"
    append_hunch(hunch, path=path)
    back = read_hunches(path)
    assert len(back) == 1
    assert back[0].utterance == said
    # And on the raw row, byte for byte.
    payload = json.loads(path.read_text().strip())
    assert payload["utterance"] == said


def test_the_row_is_expectation_shaped_for_the_joshi_import() -> None:
    """``design/domain-model.md`` §6: scope, claim, horizon, confidence, utterance, clocks."""
    payload = hunch_of(kind="down").to_json()
    assert payload["schema"] == "hunch.v1"
    assert payload["scope"] == {"kind": "mint", "mint": MINT, "symbol": "WEAVE"}
    assert payload["claim"] == {"kind": "drift_down"}
    assert payload["confidence"] == 0.65
    assert payload["horizon_s"] == default_horizon_s("down")
    # Two clocks, and the event clock on this row is a PERSON.
    assert payload["t_event_source"] == "operator:gesture"
    assert payload["t_event_unix"] == T0


def test_a_corrupt_line_does_not_stop_the_reader(tmp_path: Path) -> None:
    path = tmp_path / "hunches.jsonl"
    append_hunch(hunch_of(T0), path=path)
    with path.open("a") as fh:
        fh.write("{not json at all\n")
    append_hunch(hunch_of(T0 + 1, hunch_id="hn-second"), path=path)
    assert len(read_hunches(path)) == 2


def test_the_source_reads_from_the_start_and_dedupes_nothing_twice(tmp_path: Path) -> None:
    """Unlike every other feed: a desk restarted an hour later still sees the backlog."""
    path = tmp_path / "hunches.jsonl"
    append_hunch(hunch_of(T0, hunch_id="hn-a"), path=path)
    append_hunch(hunch_of(T0 + 1, hunch_id="hn-b"), path=path)
    source = HunchSource(path)
    first = source.poll(T0 + 2)
    assert [h.hunch_id for h in first] == ["hn-a", "hn-b"]
    assert source.poll(T0 + 3) == []
    append_hunch(hunch_of(T0 + 4, hunch_id="hn-c"), path=path)
    assert [h.hunch_id for h in source.poll(T0 + 5)] == ["hn-c"]


def test_the_source_buffers_a_half_written_final_line(tmp_path: Path) -> None:
    path = tmp_path / "hunches.jsonl"
    payload = json.dumps(hunch_of(T0, hunch_id="hn-a").to_json())
    path.write_text(payload[:40])
    source = HunchSource(path)
    assert source.poll(T0) == []
    with path.open("a") as fh:
        fh.write(payload[40:] + "\n")
    assert [h.hunch_id for h in source.poll(T0 + 1)] == ["hn-a"]
    assert source.bad_lines == 0


def test_a_quiet_hunch_tape_is_not_a_stale_source() -> None:
    """A sleeping operator is not a dead collector, and the desk must not conflate them."""
    from shitcoims_paperdesk.desk import Desk, DeskConfig

    desk = Desk(DeskConfig(minutes=0.0, tape_from_start=False))
    assert desk.hunches not in desk.sources
    assert not hasattr(desk.hunches, "opened_at_unix")


# ---------------------------------------------------------------------- resolution


def test_a_lowercased_address_is_not_a_mint() -> None:
    """base58 is case sensitive: the lowercased form names a different account, or none."""
    assert is_mint(MINT)
    assert not is_mint(MINT.lower())
    assert not is_mint(MINT[:20])
    assert not is_mint("0" * 44)  # '0' is not in the base58 alphabet


def _sources(*candidates: Candidate) -> dict[str, Any]:
    by_source: dict[str, dict[str, Candidate]] = {}
    for candidate in candidates:
        by_source.setdefault(candidate.source, {})[candidate.mint] = candidate
    return {name: (lambda found=found: found) for name, found in by_source.items()}


def test_two_coins_with_one_ticker_is_a_refusal_not_a_guess() -> None:
    found = resolve(
        "CALICO",
        now=T0,
        sources=_sources(
            Candidate(MINT, "CALICO", None, "boards", T0 - 10),
            Candidate(OTHER, "CALICO", None, "boards", T0 - 5),
        ),
    )
    assert not found.ok and found.mint is None
    assert {c.mint for c in found.candidates} == {MINT, OTHER}
    assert "2 different mints" in found.reason


def test_a_live_board_outranks_a_stale_launch_and_says_how_many_it_passed_over() -> None:
    """The tier picks between SOURCES; what it passed over is carried and printed."""
    found = resolve(
        "CALICO",
        now=T0,
        sources=_sources(
            Candidate(MINT, "CALICO", None, "boards", T0 - 10),
            Candidate(OTHER, "CALICO", "Calico Cat", "firehose", T0 - 9000),
        ),
    )
    assert found.mint == MINT
    assert [c.mint for c in found.suppressed] == [OTHER]
    assert found.to_json()["suppressed"] == 1


def test_an_ambiguous_prefix_is_a_refusal_with_no_tier_preference() -> None:
    """A prefix is typed to BE unique; two matches means the disambiguator did not work."""
    shared = MINT[:4]
    found = resolve(
        shared,
        now=T0,
        sources=_sources(
            Candidate(MINT, "A", None, "boards", T0),
            Candidate(MINT[:4] + OTHER[4:], "B", None, "firehose", T0),
        ),
    )
    assert found.mint is None and found.matched_on == "prefix"


def test_a_pasted_address_is_accepted_even_when_no_tape_has_seen_it() -> None:
    """Refusing an address the operator pasted would substitute our coverage for theirs."""
    found = resolve(MINT, now=T0, sources={})
    assert found.mint == MINT and found.matched_on == "mint"
    assert "no source has seen it" in found.reason


def test_an_unknown_ticker_refuses_and_says_where_it_looked() -> None:
    found = resolve("NOTACOIN", now=T0, sources={})
    assert found.mint is None
    assert "boards" in found.reason and "mint address" in found.reason


# ---------------------------------------------------------------------- the policy


def test_the_operator_policy_always_enters_at_propensity_one() -> None:
    """Their policy is exogenous. There is no nearby threshold to explore around."""
    policy = OperatorPolicy(seed=1)
    decision = policy.decide(
        key=MINT,
        # Features that would fail every leg of the wiggle rule.
        features={"drawdown_known": 0.0, "sol_in_curve": 0.1, "trade_recency_s": 1e9},
        now_unix=T0,
        decided_at="2026-08-15T00:00:00+00:00",
        size_lamports=100_000_000,
        actionable=False,
    )
    assert decision.action == "enter"
    assert decision.propensity == 1.0
    assert decision.explored is False
    assert decision.verdict_pass is False
    assert decision.size_lamports == 100_000_000
    # And the contract type accepts it: a propensity of 1.0 is inside (0, 1].
    assert decision.record().propensity == 1.0


def test_the_operator_policy_draws_the_wiggle_brackets_but_its_own_backstop() -> None:
    """Same brackets on both arms; the CLOCK is the one thing that must differ.

    The operator's exits are reactive -- the five minutes was where their exits landed, not
    a rule they follow -- so this book's horizon is a backstop and the exit is the zap.
    """
    drawn = OperatorPolicy(seed=3).draw()
    assert 0.03 <= drawn["take_profit"] <= 0.09
    assert 0.10 <= drawn["stop_loss"] <= 0.25
    assert 1_200.0 <= drawn["hold_seconds"] <= 2_400.0


def test_the_gate_legs_and_the_wiggle_rule_are_the_same_object() -> None:
    """``rule`` must be exactly ``all(legs)`` or the veto table describes a different rule."""
    policy = WigglePolicy(seed=0)
    thresholds = policy.draw()
    for features in (
        {"drawdown_known": 1.0, "drawdown_from_ath": 0.9, "sol_in_curve": 50.0,
         "trade_recency_s": 10.0, "own_exit_impact": 0.001, "wiggle_observations": 9.0,
         "wiggle_obs_per_min": 4.0, "wiggle_two_sided_frac": 0.9},
        {"drawdown_known": 1.0, "drawdown_from_ath": 0.9, "sol_in_curve": 0.5,
         "trade_recency_s": 10.0, "own_exit_impact": 0.001, "wiggle_observations": 9.0,
         "wiggle_obs_per_min": 4.0, "wiggle_two_sided_frac": 0.9},
        {"drawdown_known": 0.0, "drawdown_from_ath": -1.0, "sol_in_curve": 50.0,
         "trade_recency_s": 10.0, "own_exit_impact": 0.001, "wiggle_observations": 1.0},
    ):
        assert all(policy.legs(features, thresholds).values()) == policy.rule(features, thresholds)


def test_an_unmeasured_leg_is_absent_rather_than_passing() -> None:
    """Two-sidedness needs three sightings; below that it is unmeasured, not satisfied."""
    policy = WigglePolicy(seed=0)
    thresholds = policy.draw()
    thin = policy.legs({"wiggle_observations": 1.0, "drawdown_known": 1.0}, thresholds)
    assert "two_sided" not in thin and "markable_cadence" not in thin
    thick = policy.legs({"wiggle_observations": 5.0, "drawdown_known": 1.0}, thresholds)
    assert "two_sided" in thick and "markable_cadence" in thick


def test_every_book_including_the_fifth_has_a_policy() -> None:
    assert len(BOOKS) == 5
    for book in BOOKS:
        assert policy_for(book, seed=0).book is book


# ---------------------------------------------------------------------- the book


def test_a_hunch_becomes_a_position_on_the_observation_after_the_decision(tmp_path: Path) -> None:
    """The desk's first accounting rule, obeyed by the operator arm too: no lookahead."""
    book = make_operator(tmp_path)
    assert book.accept(hunch_of(T0), T0) == "accepted"
    assert not book.positions and MINT in book.waiting

    # First observation: the decision is logged and the entry becomes pending. NOT a fill.
    first = observation(T0 + 5)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    assert not book.positions and MINT in book.pending
    decision = rows_of(tmp_path, "decision")[-1]
    assert decision["action"] == "enter" and decision["propensity"] == 1.0
    assert decision["utterance"] == "gonna wiggle for a bit"

    # Second observation: the fill.
    book.observe(observation(T0 + 12), source_stale=False)
    assert len(book.positions) == 1
    position = next(iter(book.positions.values()))
    assert position.entry_unix == T0 + 12
    assert position.source == OPERATOR_SOURCE
    # The BACKSTOP, not a clock the operator trades to.
    assert 1_200.0 <= position.deadline_unix - (T0 + 5) <= 2_400.0


def test_the_feeds_cannot_enter_this_book(tmp_path: Path) -> None:
    """``consider`` is inert: a rule-chosen entry labelled ``operator`` destroys the study."""
    book = make_operator(tmp_path)
    for step in range(10):
        obs = observation(T0 + step * 10)
        book.observe(obs, source_stale=False)
        book.consider(obs)
    assert not book.positions and not book.pending
    assert not rows_of(tmp_path, "decision")


def test_a_failing_depth_gate_warns_and_tags_but_never_vetoes(tmp_path: Path) -> None:
    """The ghost-town exception: the operator outranks the gate and must hear it."""
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0), T0)
    # 2 SOL of depth is under every draw of ghost_min_pool_sol in [5, 25].
    thin = observation(T0 + 5, vsol=2 * SOL, vtok=900_000_000_000_000)
    book.observe(thin, source_stale=False)
    book.arm_waiting(thin)
    decision = rows_of(tmp_path, "decision")[-1]
    assert decision["gates"]["depth"] is False
    assert "depth" in decision["gates_would_veto"]
    assert decision["ghost_town"] is True
    assert decision["verdict_pass"] is False
    # ... and the entry happened anyway.
    assert decision["action"] == "enter" and decision["blocked"] is None
    assert MINT in book.pending
    assert book.pending[MINT]["ghost_town"] is True
    assert book.counters["ghost_town_entries"] == 1


def test_a_hunch_the_desk_was_not_around_to_see_is_censored_not_backfilled(tmp_path: Path) -> None:
    """A fill at a price the operator never saw is a fabricated fill, restart or no restart."""
    book = make_operator(tmp_path)
    stale = hunch_of(T0)
    assert book.accept(stale, T0 + HUNCH_ACTIONABLE_S + 60) == "expired"
    assert not book.waiting and not book.pending
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "expired_before_the_desk_saw_it"
    assert row["censor_reason"] == "OBSERVER_LOST"
    # The gesture is still on the ledger with its words and both clocks.
    assert row["utterance"] == "gonna wiggle for a bit"
    assert row["t_event_source"] == "operator:gesture"


def test_a_hunch_is_idempotent_in_its_id_across_a_restart(tmp_path: Path) -> None:
    """The tape replays from the start on every boot; acting twice would double the clip."""
    book = make_operator(tmp_path)
    hunch = hunch_of(T0)
    assert book.accept(hunch, T0) == "accepted"
    assert book.accept(hunch, T0 + 1) == "duplicate"

    restored = make_operator(tmp_path)
    restored.restore(book.state())
    assert restored.accept(hunch, T0 + 2) == "duplicate"
    assert MINT in restored.waiting


def test_a_gesture_the_desk_never_observes_is_recorded_not_invented(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0), T0)
    book.sweep(T0 + WAIT_TIMEOUT_S + 1, source_stale=False)
    assert not book.waiting and not book.positions
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "never_observed_no_position_opened"
    assert row["censor_reason"] == "DISPLACED"
    assert book.counters["hunches_expired"] == 1


def test_the_close_goes_through_the_one_shared_builder(tmp_path: Path) -> None:
    """The comparison rests on this: the exit MACHINERY is inherited, not rewritten.

    What differs from the wiggle book is which event ends the position (a zap, not a
    clock). Everything downstream of that -- the fill discipline, the marking, the
    censoring, the close row -- is the same code, which is what keeps the two arms'
    P&L comparable at all.
    """
    book = make_operator(tmp_path)
    assert isinstance(book, WiggleBook)
    book.accept(hunch_of(T0), T0)
    first = observation(T0 + 5)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    book.observe(observation(T0 + 12), source_stale=False)
    # The operator pulls out; the exit fills on the observation AFTER the gesture.
    book.zap(_zap(at=T0 + 100), T0 + 100)
    book.observe(observation(T0 + 110), source_stale=False)
    closes = rows_of(tmp_path, "close")
    assert len(closes) == 1
    close = closes[0]
    assert close["book"] == "operator"
    assert close["exit_reason"] == "zap"
    assert close["label"] == OPERATOR_SOURCE
    # Every field the one close-row builder guarantees, including on this new book.
    for key in ("spend_lamports", "proceeds_lamports", "pnl_lamports",
                "pnl_pessimistic_lamports", "net_return", "mark_source", "censored"):
        assert key in close


def test_a_pending_adopts_the_venue_it_is_first_observed_on(tmp_path: Path) -> None:
    """A gesture names no venue; the fill pins one, and marking stays single-basis after."""
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0), T0)
    first = observation(T0 + 5, pool_label="weave/SOL")
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    assert book.pending[MINT]["pool_label"] == "weave/SOL"
    book.observe(observation(T0 + 12, pool_label="weave/SOL"), source_stale=False)
    assert next(iter(book.positions.values())).label == "weave/SOL"


def test_the_any_basis_sentinel_is_replaced_before_the_fill_check(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0), T0)
    first = observation(T0 + 5)  # pool_label None -> the sentinel is stored
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    assert book.pending[MINT]["pool_label"] is ANY_BASIS
    book.observe(observation(T0 + 12), source_stale=False)
    assert len(book.positions) == 1


# ---------------------------------------------------------------------- expectations


def test_a_down_hunch_opens_no_position_and_gets_a_falsifier(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    assert book.accept(hunch_of(T0, kind="down", horizon=1800.0), T0) == "watching"
    assert not book.pending and not book.waiting and len(book.watches) == 1
    recorded = rows_of(tmp_path, "expectation")[-1]
    assert recorded["detail"] == "recorded" and recorded["claim"] == "drift_down"

    book.observe(observation(T0 + 5), source_stale=False)
    watch = next(iter(book.watches.values()))
    assert watch.entry_price is not None and watch.invalidation > watch.entry_price

    # A rise through the invalidation level is the belief's own stop firing.
    book.observe(observation(T0 + 10, vsol=80 * SOL), source_stale=False)
    tripped = [r for r in rows_of(tmp_path, "expectation") if r["detail"] == "falsifier_tripped"]
    assert len(tripped) == 1
    assert book.counters["falsified"] == 1


def test_a_claim_is_scored_at_its_horizon_with_ties_against_the_claim(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, kind="down", horizon=600.0), T0)
    book.observe(observation(T0 + 5), source_stale=False)
    # Unchanged price: "down" did not happen, so the claim is wrong. Pessimistic by design.
    book.observe(observation(T0 + 60), source_stale=False)
    book.resolve_watches(T0 + 700, source_stale=False)
    resolved = [r for r in rows_of(tmp_path, "expectation") if r["detail"] == "resolved"]
    assert len(resolved) == 1
    assert resolved[0]["outcome"] == 0
    assert resolved[0]["brier"] == pytest.approx(brier(0.65, 0))
    assert not book.watches


def test_a_claim_scores_right_when_the_price_actually_falls(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, kind="down", horizon=600.0), T0)
    book.observe(observation(T0 + 5, vsol=40 * SOL), source_stale=False)
    book.observe(observation(T0 + 60, vsol=20 * SOL), source_stale=False)
    book.resolve_watches(T0 + 700, source_stale=False)
    resolved = [r for r in rows_of(tmp_path, "expectation") if r["detail"] == "resolved"]
    assert resolved[0]["outcome"] == 1
    assert resolved[0]["change"] < 0


def test_an_unobservable_horizon_is_censored_and_counted(tmp_path: Path) -> None:
    """Censoring is data. A scorecard over only the observable claims is a biased one."""
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, kind="watch", horizon=600.0), T0)
    book.resolve_watches(T0 + 700, source_stale=True)
    row = rows_of(tmp_path, "expectation")[-1]
    assert row["detail"] == "censored"
    assert row["censor_reason"] == "OBSERVER_LOST"
    assert row["brier"] is None if "brier" in row else True
    assert book.counters["watches_censored"] == 1


def test_a_watch_claim_is_scored_direction_free(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, kind="watch", horizon=600.0), T0)
    book.observe(observation(T0 + 5, vsol=40 * SOL), source_stale=False)
    book.observe(observation(T0 + 60, vsol=48 * SOL), source_stale=False)
    book.resolve_watches(T0 + 700, source_stale=False)
    row = rows_of(tmp_path, "expectation")[-1]
    assert row["detail"] == "resolved"
    # No binary claim, so no Brier: there is nothing to be right or wrong about.
    assert row["outcome"] is None and row["brier"] is None
    assert row["realised_range"] is not None


def test_watches_survive_a_restart_mid_horizon(tmp_path: Path) -> None:
    """A scorecard that quietly loses its long claims is biased toward the short ones."""
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, kind="down", horizon=3600.0), T0)
    book.observe(observation(T0 + 5), source_stale=False)
    state = json.loads(json.dumps(book.state()))  # through JSON, as the desk does

    restored = make_operator(tmp_path)
    restored.restore(state)
    assert len(restored.watches) == 1
    watch = next(iter(restored.watches.values()))
    assert watch.entry_price is not None and watch.claim == "drift_down"
    restored.resolve_watches(T0 + 4000, source_stale=False)
    assert not restored.watches


def test_brier_is_lower_is_better_and_a_half_scores_a_quarter() -> None:
    assert brier(0.5, 1) == pytest.approx(0.25)
    assert brier(0.5, 0) == pytest.approx(0.25)
    assert brier(0.9, 1) < brier(0.5, 1)
    assert brier(0.9, 0) > brier(0.5, 0)


# ---------------------------------------------------------------------- the desk


def test_the_desk_carries_the_hunch_through_end_to_end(tmp_path: Path) -> None:
    """Tape -> source -> book -> decision -> fill -> close, on the desk's own wiring."""
    from shitcoims_paperdesk.desk import Desk, DeskConfig

    path = tmp_path / "hunches.jsonl"
    ledger = Ledger(tmp_path, run_id="test-e2e")
    desk = Desk(DeskConfig(minutes=0.0, seed=5, tape_from_start=False), ledger=ledger)
    desk.hunches = HunchSource(path)

    now = time.time()
    append_hunch(hunch_of(now, mint=MINT), path=path)
    for hunch in desk.hunches.poll(now):
        desk.operator.accept(hunch, now)
    assert MINT in desk.operator.waiting

    first = observation(now + 2)
    desk.operator.observe(first, source_stale=False)
    desk.operator.arm_waiting(first)
    desk.operator.observe(observation(now + 6), source_stale=False)
    assert len(desk.operator.positions) == 1

    desk.operator.zap(_zap(at=now + 100), now + 100)
    desk.operator.observe(observation(now + 110), source_stale=False)
    ledger.close()

    rows = read_ledger(tmp_path)
    closes = [c for c in rows.closes if c["book"] == "operator"]
    assert len(closes) == 1
    rendered = render(rows)
    assert "OPERATOR — the fifth book" in rendered
    assert "gesture(s) acknowledged" in rendered


def test_the_desk_keeps_watch_mints_observable_and_scalps_priority(tmp_path: Path) -> None:
    from shitcoims_paperdesk.desk import Desk, DeskConfig

    desk = Desk(DeskConfig(minutes=0.0, tape_from_start=False), ledger=Ledger(tmp_path))
    desk.operator.accept(hunch_of(T0, kind="down", horizon=3600.0), T0)
    desk.operator.accept(hunch_of(T0, mint=OTHER, hunch_id="hn-scalp"), T0)
    interest = desk.operator.mints_of_interest
    assert MINT in interest and OTHER in interest


def test_the_desk_state_round_trips_the_fifth_book(tmp_path: Path) -> None:
    from shitcoims_paperdesk.desk import Desk, DeskConfig

    ledger = Ledger(tmp_path, run_id="rt")
    desk = Desk(DeskConfig(minutes=0.0, tape_from_start=False), ledger=ledger)
    desk.operator.accept(hunch_of(T0, kind="down", horizon=3600.0), T0)
    desk.operator.accept(hunch_of(T0, mint=OTHER, hunch_id="hn-b"), T0)
    desk.save()

    revived = Desk(DeskConfig(minutes=0.0, tape_from_start=False), ledger=Ledger(tmp_path))
    revived.load()
    assert OTHER in revived.operator.waiting
    assert len(revived.operator.watches) == 1
    assert revived.operator.accept(hunch_of(T0, mint=OTHER, hunch_id="hn-b"), T0) == "duplicate"


# ---------------------------------------------------------------------- the report


def test_the_premium_refuses_to_print_an_interval_below_the_entity_floor(tmp_path: Path) -> None:
    from shitcoims_paperdesk.hunch_report import MIN_ENTITIES, render_hunch_report

    book = make_operator(tmp_path)
    book.accept(hunch_of(T0), T0)
    first = observation(T0 + 5)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    book.observe(observation(T0 + 12), source_stale=False)
    book.drain(T0 + 300)
    book.ledger.close()

    text = render_hunch_report(tmp_path)
    assert "THE INTUITION PREMIUM" in text
    assert f"{MIN_ENTITIES}-entity floor" in text or "No overlapping window" in text
    assert "95% CI" not in text


def test_the_report_renders_on_an_empty_ledger(tmp_path: Path) -> None:
    from shitcoims_paperdesk.hunch_report import render_hunch_report

    text = render_hunch_report(tmp_path)
    assert "THE INTUITION PREMIUM" in text
    assert "GATE VETOES" in text


def test_the_gate_veto_table_counts_both_arms(tmp_path: Path) -> None:
    from shitcoims_paperdesk.hunch_report import render_hunch_report

    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, hunch_id="hn-thin"), T0)
    thin = observation(T0 + 5, vsol=2 * SOL)
    book.observe(thin, source_stale=False)
    book.arm_waiting(thin)
    book.ledger.close()
    text = render_hunch_report(tmp_path)
    assert "GATE VETOES" in text
    assert "depth" in text
    assert "No model is fitted here" in text


# ---------------------------------------------------------------------- the API


def test_the_glass_api_refuses_a_bad_address_and_an_unknown_kind(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from shitcoims_paperdesk.glass import CoinIndex, build_app

    client = TestClient(build_app(CoinIndex()))
    assert client.post("/hunch", json={"mint": MINT.lower(), "kind": "wiggle"}).status_code == 400
    assert client.post("/hunch", json={"mint": MINT, "kind": "moon"}).status_code == 400
    assert client.post("/hunch", json={"mint": MINT, "kind": "wiggle", "confidence": 0}).status_code == 400
    assert client.get(f"/hunch/readout/{MINT.lower()}").status_code == 400


def test_the_glass_api_captures_and_never_claims_it_can_execute(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from shitcoims_paperdesk import glass
    from shitcoims_paperdesk import hunch as hunch_module

    path = tmp_path / "hunches.jsonl"
    monkeypatch.setattr(hunch_module, "HUNCH_PATH", path)

    client = TestClient(glass.build_app(glass.CoinIndex()))
    response = client.post(
        "/hunch",
        json={"mint": MINT, "kind": "wiggle", "note": "gonna wiggle", "surface": "explorer"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["hunch_id"]
    assert body["hunch"]["utterance"] == "gonna wiggle"
    assert body["hunch"]["evidence"]["surface"]["declared_by"] == "glass"
    assert read_hunches(path)[-1].mint == MINT
    assert client.get("/hunch/health").json()["can_execute"] is False


def test_a_click_with_no_words_stores_an_empty_utterance_not_a_fabricated_one(
    tmp_path: Path, monkeypatch
) -> None:
    """A click is a valid gesture. Reconstructing a sentence for it would poison the corpus."""
    from fastapi.testclient import TestClient

    from shitcoims_paperdesk import glass
    from shitcoims_paperdesk import hunch as hunch_module

    path = tmp_path / "hunches.jsonl"
    monkeypatch.setattr(hunch_module, "HUNCH_PATH", path)
    client = TestClient(glass.build_app(glass.CoinIndex()))
    client.post("/hunch", json={"mint": MINT, "kind": "wiggle"})
    assert read_hunches(path)[-1].utterance == ""


# ---------------------------------------------------------------------- retraction


def test_a_retraction_is_appended_and_the_original_row_stays_on_disk(tmp_path: Path) -> None:
    """Append-only means append-only. The correction sits BESIDE the mistake, forever."""
    from shitcoims_paperdesk.hunch import append_retraction, read_tape

    path = tmp_path / "hunches.jsonl"
    append_hunch(hunch_of(T0, hunch_id="hn-oops"), path=path)
    append_retraction("hn-oops", "misclick", path=path, now=T0 + 30)

    assert read_hunches(path) == []  # the reader's view applies it
    hunches, retractions, _ = read_tape(path)  # the auditor's view does not
    assert [h.hunch_id for h in hunches] == ["hn-oops"]
    assert retractions[0].retracts == "hn-oops" and retractions[0].reason == "misclick"
    assert path.read_text().count("\n") == 2


def test_a_retraction_withdraws_a_hunch_the_desk_has_not_acted_on_yet(tmp_path: Path) -> None:
    from shitcoims_paperdesk.hunch import Retraction

    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, hunch_id="hn-oops"), T0)
    assert MINT in book.waiting
    state = book.retract(
        Retraction(retracts="hn-oops", reason="not a gesture", t_event_unix=T0 + 5,
                   t_ingest_unix=T0 + 5),
        T0 + 5,
    )
    assert state == "withdrawn_before_entry"
    assert not book.waiting
    # And it cannot come back on the next replay of the tape.
    assert book.accept(hunch_of(T0, hunch_id="hn-oops"), T0 + 6) == "duplicate"
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "retracted:withdrawn_before_entry"
    assert row["t_event_source"] == "operator:retraction"


def test_a_retraction_cannot_unwind_a_fill_and_says_so(tmp_path: Path) -> None:
    """A paper position that opened is a thing that happened at a price."""
    from shitcoims_paperdesk.hunch import Retraction

    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, hunch_id="hn-late"), T0)
    first = observation(T0 + 5)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    book.observe(observation(T0 + 12), source_stale=False)
    assert len(book.positions) == 1

    book.retract(
        Retraction(retracts="hn-late", reason="changed my mind", t_event_unix=T0 + 20,
                   t_ingest_unix=T0 + 20),
        T0 + 20,
    )
    assert len(book.positions) == 1  # still open; the clock still owns it
    assert rows_of(tmp_path, "hunch")[-1]["detail"].startswith("retracted:retracted_after_position")


def test_the_source_hands_retractions_to_the_desk_in_tape_order(tmp_path: Path) -> None:
    from shitcoims_paperdesk.hunch import Retraction, append_retraction

    path = tmp_path / "hunches.jsonl"
    append_hunch(hunch_of(T0, hunch_id="hn-a"), path=path)
    append_retraction("hn-a", "oops", path=path, now=T0 + 1)
    events = HunchSource(path).poll(T0 + 2)
    assert isinstance(events[0], Hunch) and isinstance(events[1], Retraction)
    assert events[1].retracts == "hn-a"


def test_a_second_hunch_on_a_waiting_coin_is_recorded_not_silently_dropped(
    tmp_path: Path,
) -> None:
    """``waiting`` is keyed by mint, so an overwrite would lose the first gesture whole."""
    book = make_operator(tmp_path)
    assert book.accept(hunch_of(T0, hunch_id="hn-first"), T0) == "accepted"
    assert book.accept(hunch_of(T0 + 10, hunch_id="hn-second"), T0 + 10) == "already_waiting"
    # The FIRST one still owns the entry; the second is on the ledger with its own words.
    assert book.waiting[MINT]["hunch_id"] == "hn-first"
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "already_awaiting_on_this_mint"
    assert row["hunch_id"] == "hn-second" and row["awaiting"] == "hn-first"
    # And one gesture buys one clip, not two.
    first = observation(T0 + 20)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    book.observe(observation(T0 + 30), source_stale=False)
    assert len(book.positions) == 1


def test_a_wait_blocked_by_a_queued_entry_says_so_rather_than_timing_out(
    tmp_path: Path,
) -> None:
    """A wrong reason on a row reads as a measurement of the feed. Name the real one."""
    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, hunch_id="hn-a"), T0)
    first = observation(T0 + 5)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    assert MINT in book.pending

    book.waiting[MINT] = {
        "hunch_id": "hn-b", "recorded_unix": T0 + 6, "size_lamports": 100_000_000,
        "utterance": "again", "confidence": 0.6, "symbol": "WEAVE", "gesture_unix": T0 + 6,
    }
    book.arm_waiting(observation(T0 + 8))
    assert not book.waiting
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "entry_already_queued_for_this_mint"


# ---------------------------------------------------------------------- the zap


def _zap(mint: str = MINT, at: float = T0, **kw: Any):
    from shitcoims_paperdesk.hunch import Zap

    return Zap(
        zap_id=kw.pop("zap_id", f"zp-{int(at)}"),
        mint=mint,
        position_id=kw.pop("position_id", None),
        reason=kw.pop("reason", ""),
        t_event_unix=at,
        t_ingest_unix=at,
        state=kw.pop("state", {}),
    )


def _open_one(book: OperatorBook, at: float = T0) -> Any:
    book.accept(hunch_of(at), at)
    first = observation(at + 5)
    book.observe(first, source_stale=False)
    book.arm_waiting(first)
    book.observe(observation(at + 12), source_stale=False)
    return next(iter(book.positions.values()))


def test_the_clock_is_a_backstop_not_a_policy(tmp_path: Path) -> None:
    """The five minutes was an outcome distribution, not the operator's rule."""
    assert OperatorPolicy.ranges["hold_seconds"] == (1_200.0, 2_400.0)
    assert WigglePolicy.ranges["hold_seconds"] == (240.0, 420.0)
    # Every ENTRY threshold is still the wiggle rule's, or the veto table lies.
    for name, box in WigglePolicy.ranges.items():
        if name == "hold_seconds":
            continue
        assert OperatorPolicy.ranges[name] == box
    book = make_operator(tmp_path)
    position = _open_one(book)
    horizon = position.deadline_unix - (T0 + 5)
    assert 1_200.0 <= horizon <= 2_400.0
    assert OperatorBook.MAX_HOLD_S == 3_600.0


def test_the_backstop_closes_under_its_own_name(tmp_path: Path) -> None:
    """A zap-closed position and an abandoned one must be distinguishable in the ledger."""
    book = make_operator(tmp_path)
    position = _open_one(book)
    late = position.deadline_unix + 10
    book.observe(observation(late), source_stale=False)
    book.observe(observation(late + 5), source_stale=False)
    close = rows_of(tmp_path, "close")[-1]
    assert close["exit_reason"] == "backstop_expired"


def test_a_zap_arms_the_exit_and_it_fills_at_the_next_observation(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    position = _open_one(book)
    assert book.zap(_zap(at=T0 + 60), T0 + 60) == "armed"
    assert position.armed_reason == "zap"
    assert position.position_id in book.positions  # NOT closed yet: no lookahead here either
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "zap_armed"
    assert row["t_event_source"] == "operator:zap"
    assert row["held_s"] == pytest.approx(48.0)

    book.observe(observation(T0 + 70), source_stale=False)
    close = rows_of(tmp_path, "close")[-1]
    assert close["exit_reason"] == "zap"
    assert close["mark_source"] == "observed"
    assert close["book"] == "operator"


def test_a_zap_carries_the_instrument_state_that_provoked_it(tmp_path: Path) -> None:
    """``(state, exit)`` pairs are the training set. A zap without state is half a datum."""
    book = make_operator(tmp_path)
    _open_one(book)
    state = {"card": {"sol_in_curve": 40.0}, "path": [{"t": T0, "price": 1.0}]}
    book.zap(_zap(at=T0 + 60, state=state, reason="stopped moving"), T0 + 60)
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["state"] == state
    assert row["reason"] == "stopped moving"
    assert row["unrealised_return"] is not None
    assert row["observations"] >= 1


def test_a_zap_with_no_open_position_is_recorded_not_ignored(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    assert book.zap(_zap(at=T0), T0) == "no_position"
    assert rows_of(tmp_path, "hunch")[-1]["detail"] == "zap_no_open_position"
    assert book.counters["zaps_no_position"] == 1


def test_a_second_zap_on_an_armed_position_does_not_re_arm_it(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    _open_one(book)
    book.zap(_zap(at=T0 + 60), T0 + 60)
    assert book.zap(_zap(at=T0 + 61, zap_id="zp-2"), T0 + 61) == "already_armed"
    assert book.counters["zaps"] == 2
    assert rows_of(tmp_path, "hunch")[-1]["detail"] == "zap_already_armed"


def test_a_zap_targets_the_named_position_when_one_is_given(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    position = _open_one(book)
    assert book.zap(_zap(at=T0 + 60, position_id=position.position_id), T0 + 60) == "armed"
    assert position.armed_reason == "zap"


def test_the_zap_marks_at_the_last_observed_price_never_an_invented_one(tmp_path: Path) -> None:
    book = make_operator(tmp_path)
    position = _open_one(book)
    last = position.last_price
    book.zap(_zap(at=T0 + 60), T0 + 60)
    assert position.armed_price == last


def test_zaps_round_trip_through_the_tape_and_the_source(tmp_path: Path) -> None:
    from shitcoims_paperdesk.hunch import Zap, append_zap, read_tape, read_zaps

    path = tmp_path / "hunches.jsonl"
    append_hunch(hunch_of(T0, hunch_id="hn-a"), path=path)
    append_zap(_zap(at=T0 + 60, state={"card": {"x": 1}}), path=path)
    hunches, retractions, zaps = read_tape(path)
    assert [h.hunch_id for h in hunches] == ["hn-a"] and not retractions
    assert len(zaps) == 1 and zaps[0].state == {"card": {"x": 1}}
    assert read_zaps(path)[0].mint == MINT
    events = HunchSource(path).poll(T0 + 61)
    assert isinstance(events[0], Hunch) and isinstance(events[1], Zap)


def test_the_desk_routes_a_zap_to_the_operator_book(tmp_path: Path) -> None:
    from shitcoims_paperdesk.desk import Desk, DeskConfig
    from shitcoims_paperdesk.hunch import append_zap

    path = tmp_path / "hunches.jsonl"
    ledger = Ledger(tmp_path, run_id="zap-e2e")
    desk = Desk(DeskConfig(minutes=0.0, seed=5, tape_from_start=False), ledger=ledger)
    desk.hunches = HunchSource(path)
    now = time.time()

    append_hunch(hunch_of(now), path=path)
    append_zap(_zap(at=now + 1), path=path)
    desk.step(now + 2)  # both events, in tape order: accept then zap
    # The zap lands with no position open yet, and is RECORDED rather than dropped.
    assert desk.operator.counters["zaps_no_position"] == 1
    ledger.close()


def test_position_states_says_when_a_position_cannot_be_zapped_out_of(tmp_path: Path) -> None:
    """A zap fills against an observation. Unmarkable means unexitable, and it must show."""
    book = make_operator(tmp_path)
    _open_one(book)
    fresh = book.position_states(T0 + 20)
    assert fresh[0]["markable"] is True
    assert fresh[0]["unrealised_return"] is not None
    stale = book.position_states(T0 + 12 + book.departure_timeout_s + 1)
    assert stale[0]["markable"] is False


# ---------------------------------------------------------------------- the duel view


def test_a_cold_swarm_detector_is_not_an_empty_market(tmp_path: Path) -> None:
    """An empty duel list under live_only means one of two very different things."""
    from fastapi.testclient import TestClient

    from shitcoims_paperdesk import glass

    client = TestClient(glass.build_app(glass.CoinIndex()))
    body = client.get("/hunch/families?live_only=true").json()
    assert "absent" in body
    # Either the file is fresh (no absence) or the staleness is NAMED. Never silence.
    if body.get("families_age_s") and body["families_age_s"] > glass.FAMILY_STALE_S:
        assert "families" in body["absent"]
        assert "detector" in body["absent"]["families"]


def test_family_leaders_are_per_axis_and_never_summed(tmp_path: Path) -> None:
    """No composite score: there is no evidence in this repo for how to weight the axes."""
    from shitcoims_paperdesk.glass import _family_leaders

    live = [
        {"mint": MINT, "symbol": "A", "card": {"usd_market_cap": 100.0, "sol_in_curve": 5.0,
                                               "drawdown_from_ath": 0.9}},
        {"mint": OTHER, "symbol": "B", "card": {"usd_market_cap": 50.0, "sol_in_curve": 50.0,
                                                "drawdown_from_ath": 0.2}},
    ]
    leaders = _family_leaders(live)
    assert leaders["market_cap"]["symbol"] == "A"
    assert leaders["depth"]["symbol"] == "B"
    # Shallowest drawdown wins, i.e. SMALLER is better on that axis.
    assert leaders["shallowest_drawdown"]["symbol"] == "B"
    # An axis no member reports is None, not a zero-valued winner.
    assert leaders["flow"] is None
    assert "score" not in leaders and "winner" not in leaders


def test_a_family_with_one_live_member_is_not_a_duel(tmp_path: Path) -> None:
    """One live member is a family; a duel needs two sides that are both being traded."""
    from fastapi.testclient import TestClient

    from shitcoims_paperdesk import glass

    client = TestClient(glass.build_app(glass.CoinIndex()))
    strict = client.get("/hunch/families?live_only=true&limit=200").json()
    assert all(f["live_members"] >= 2 for f in strict["items"])
    loose = client.get("/hunch/families?live_only=false&limit=200").json()
    assert loose["n_families"] >= strict["n_families"]


def test_a_retracted_zap_leaves_the_exit_corpus(tmp_path: Path) -> None:
    """A zap that was not the operator's is a fabricated training pair. It must not fit."""
    from shitcoims_paperdesk.hunch import append_retraction, append_zap, read_tape, read_zaps

    path = tmp_path / "hunches.jsonl"
    append_zap(_zap(at=T0, zap_id="zp-real", state={"card": {}}), path=path)
    append_zap(_zap(at=T0 + 1, zap_id="zp-fake", state={"card": {}}), path=path)
    append_retraction("zp-fake", "not an operator gesture", path=path, now=T0 + 2)
    assert [z.zap_id for z in read_zaps(path)] == ["zp-real"]
    # ... and it is still on disk, for the auditor.
    assert len(read_tape(path)[2]) == 2


def test_a_zap_is_idempotent_across_a_restart(tmp_path: Path) -> None:
    """The tape replays from the START. A stale zap must not arm today's position."""
    book = make_operator(tmp_path)
    _open_one(book)
    assert book.zap(_zap(at=T0 + 60, zap_id="zp-once"), T0 + 60) == "armed"
    assert book.zap(_zap(at=T0 + 60, zap_id="zp-once"), T0 + 61) == "duplicate"

    revived = make_operator(tmp_path)
    revived.restore(book.state())
    assert revived.zap(_zap(at=T0 + 60, zap_id="zp-once"), T0 + 62) == "duplicate"


def test_a_zap_the_desk_was_not_around_for_does_not_close_todays_position(
    tmp_path: Path,
) -> None:
    """An exit at a price nobody chose is a fabricated exit, restart or no restart."""
    book = make_operator(tmp_path)
    position = _open_one(book)
    assert book.zap(_zap(at=T0, zap_id="zp-old"), T0 + HUNCH_ACTIONABLE_S + 60) == "expired"
    assert position.armed_reason is None
    row = rows_of(tmp_path, "hunch")[-1]
    assert row["detail"] == "zap_expired_before_the_desk_saw_it"
    assert row["censor_reason"] == "OBSERVER_LOST"


def test_a_retraction_is_idempotent_across_a_restart(tmp_path: Path) -> None:
    """Replaying the tape must not re-emit a retraction row on every boot."""
    from shitcoims_paperdesk.hunch import Retraction

    book = make_operator(tmp_path)
    book.accept(hunch_of(T0, hunch_id="hn-x"), T0)
    retraction = Retraction(retracts="hn-x", reason="oops", t_event_unix=T0 + 5, t_ingest_unix=T0 + 5)
    assert book.retract(retraction, T0 + 5) == "withdrawn_before_entry"
    assert book.retract(retraction, T0 + 6) == "duplicate"

    revived = make_operator(tmp_path)
    revived.restore(book.state())
    assert revived.retract(retraction, T0 + 7) == "duplicate"
    assert book.counters["retractions"] == 1
