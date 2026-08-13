"""Tests for the tape contract.

Each test pins a decision that a published study got wrong, and is named for the failure it
prevents rather than for the function it calls.
"""

from __future__ import annotations

import json

import pytest
from solders.keypair import Keypair

from shitcoims_tape import (
    Callout,
    Chainstamp,
    EntityLink,
    EventKind,
    Launch,
    PropensityRecord,
    Provenance,
    Reserves,
    Side,
    TapeError,
    TapeEvent,
    Trade,
    WatchClose,
    WatchWindow,
    event_from_json,
    tape_health,
)

SIG = "5" * 88
HASH = "a" * 64


def _mint() -> str:
    return str(Keypair().pubkey())


def _prov() -> Provenance:
    return Provenance(source="helius.getTransactionsForAddress", fetched_at="2026-08-13T00:00:00Z")


def _chain(slot: int = 1000) -> Chainstamp:
    return Chainstamp(slot=slot, signature=SIG, block_time=1786000000)


def _trade(**kw) -> Trade:
    base = dict(
        mint=_mint(),
        wallet=_mint(),
        side=Side.BUY,
        sol_delta_lamports=-500_000_000,
        token_delta_raw=1_000_000_000_000,
    )
    base.update(kw)
    return Trade(**base)  # type: ignore[arg-type]


# --- the f64 cliff -----------------------------------------------------------------


def test_a_raw_amount_past_the_float_cliff_round_trips_exactly() -> None:
    """A 1e9-supply 6-decimal memecoin is 1e15 raw units; f64 is exact only to ~9.0e15.

    Serialising raw amounts as JSON numbers silently corrupts exactly the biggest bags, so
    they must cross the wire as strings and return bit-identical.
    """
    huge = 9_007_199_254_740_993  # 2**53 + 1: the first integer f64 cannot represent
    assert float(huge) == float(huge - 1)  # the corruption this test exists to prevent

    event = TapeEvent(
        kind=EventKind.RESERVE,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        chain=_chain(),
        body=Reserves(
            pool=_mint(),
            virtual_sol=huge,
            virtual_tokens=huge + 2,
            real_sol=1,
            real_tokens=2,
        ),
    )
    line = event.to_jsonl()
    assert f'"{huge}"' in line  # a string on the wire, not a number
    restored = event_from_json(json.loads(line))
    assert restored.body.virtual_sol == huge
    assert restored.body.virtual_tokens == huge + 2


def test_a_float_amount_is_refused_rather_than_silently_truncated() -> None:
    with pytest.raises(TapeError, match="never a float"):
        Reserves(pool=_mint(), virtual_sol=1.5, virtual_tokens=1, real_sol=1, real_tokens=1)


# --- clocks and censoring ----------------------------------------------------------


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc() -> None:
    with pytest.raises(TapeError, match="timezone"):
        Provenance(source="helius", fetched_at="2026-08-13T00:00:00")


def test_displacement_and_observer_loss_are_flagged_as_informative_censoring() -> None:
    """A watch that ended because attention moved on cannot support a survival estimate."""
    displaced = WatchWindow(
        mint=_mint(),
        opened_at="2026-08-13T00:00:00Z",
        deadline="2026-08-14T00:00:00Z",
        closed_at="2026-08-13T00:02:46Z",
        close_reason=WatchClose.DISPLACED,
    )
    lost = WatchWindow(
        mint=_mint(),
        opened_at="2026-08-13T00:00:00Z",
        deadline="2026-08-14T00:00:00Z",
        closed_at="2026-08-13T00:05:00Z",
        close_reason=WatchClose.OBSERVER_LOST,
    )
    benign = WatchWindow(
        mint=_mint(),
        opened_at="2026-08-13T00:00:00Z",
        deadline="2026-08-14T00:00:00Z",
        closed_at="2026-08-14T00:00:00Z",
        close_reason=WatchClose.DEADLINE,
    )
    assert displaced.is_informatively_censored
    assert lost.is_informatively_censored
    assert not benign.is_informatively_censored


def test_a_closed_watch_must_say_why_it_closed() -> None:
    with pytest.raises(TapeError, match="why it closed"):
        WatchWindow(
            mint=_mint(),
            opened_at="2026-08-13T00:00:00Z",
            deadline="2026-08-14T00:00:00Z",
            closed_at="2026-08-13T01:00:00Z",
        )


def test_a_deadline_before_the_open_is_refused() -> None:
    with pytest.raises(TapeError, match="after opened_at"):
        WatchWindow(
            mint=_mint(),
            opened_at="2026-08-13T02:00:00Z",
            deadline="2026-08-13T01:00:00Z",
        )


def test_any_informative_censoring_makes_the_tape_incomplete() -> None:
    """Coverage alone is not health: a fully-covered tape can still be truncated."""
    mint = _mint()
    watches = [
        WatchWindow(
            mint=mint,
            opened_at="2026-08-13T00:00:00Z",
            deadline="2026-08-14T00:00:00Z",
            closed_at="2026-08-14T00:00:00Z",
            close_reason=WatchClose.DEADLINE,
        ),
        WatchWindow(
            mint=mint,
            opened_at="2026-08-13T00:00:00Z",
            deadline="2026-08-14T00:00:00Z",
            closed_at="2026-08-13T00:02:46Z",
            close_reason=WatchClose.DISPLACED,
        ),
    ]
    health = tape_health(observed_trades=1000, reference_trades=1000, watches=watches)
    assert health.coverage == 1.0
    assert health.censoring_rate == 0.5
    assert health.complete is False

    clean = tape_health(observed_trades=1000, reference_trades=1000, watches=watches[:1])
    assert clean.complete is True


def test_coverage_below_the_threshold_makes_the_tape_incomplete() -> None:
    health = tape_health(observed_trades=970, reference_trades=1000, watches=[])
    assert health.coverage == 0.97
    assert health.complete is False


# --- ordering and sign consistency -------------------------------------------------


def test_a_trade_without_a_chainstamp_is_refused() -> None:
    """Unordered events silently corrupt every downstream rolling statistic."""
    with pytest.raises(TapeError, match="requires a chainstamp"):
        TapeEvent(
            kind=EventKind.TRADE,
            observed_at="2026-08-13T00:00:00Z",
            provenance=_prov(),
            body=_trade(),
        )


def test_a_buy_that_decreases_the_token_balance_is_refused() -> None:
    with pytest.raises(TapeError, match="must not decrease"):
        _trade(side=Side.BUY, token_delta_raw=-5)


def test_a_sell_that_increases_the_token_balance_is_refused() -> None:
    with pytest.raises(TapeError, match="must not increase"):
        _trade(side=Side.SELL, token_delta_raw=5)


# --- identity ----------------------------------------------------------------------


def test_event_id_is_a_content_hash_so_sources_dedupe() -> None:
    """The same fill seen twice through two sources must collapse to one row."""
    mint, wallet = _mint(), _mint()
    kw = dict(
        kind=EventKind.TRADE,
        observed_at="2026-08-13T00:00:00Z",
        chain=_chain(),
        body=Trade(
            mint=mint,
            wallet=wallet,
            side=Side.BUY,
            sol_delta_lamports=-1,
            token_delta_raw=2,
        ),
    )
    a = TapeEvent(provenance=_prov(), **kw)  # type: ignore[arg-type]
    b = TapeEvent(provenance=_prov(), **kw)  # type: ignore[arg-type]
    assert a.event_id == b.event_id

    different = TapeEvent(
        provenance=_prov(),
        kind=EventKind.TRADE,
        observed_at="2026-08-13T00:00:00Z",
        chain=_chain(slot=1001),
        body=kw["body"],  # type: ignore[arg-type]
    )
    assert different.event_id != a.event_id


def test_a_tape_line_holds_no_newline_so_jsonl_stays_one_record_per_line() -> None:
    """Memecoin names contain commas, quotes and newlines by design — hence JSONL, not CSV."""
    event = TapeEvent(
        kind=EventKind.LAUNCH,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        body=Launch(mint=_mint(), creator=_mint(), name='ha\nha,"x"', symbol="A,B"),
    )
    line = event.to_jsonl()
    assert "\n" not in line
    assert json.loads(line)["body"]["name"] == 'ha\nha,"x"'


# --- counterfactual readiness ------------------------------------------------------


def test_a_zero_propensity_is_refused_because_no_estimator_can_use_it() -> None:
    """An action the logging policy could never take breaks importance weighting."""
    with pytest.raises(TapeError, match="propensity"):
        PropensityRecord(
            decision_id="d1",
            decided_at="2026-08-13T00:00:00Z",
            policy_id="p1",
            action="buy",
            propensity=0.0,
            features_sha256=HASH,
            envelope_verdict="admitted",
        )


def test_a_propensity_record_round_trips_its_decision_time_fields() -> None:
    rec = PropensityRecord(
        decision_id="d1",
        decided_at="2026-08-13T00:00:00+00:00",
        policy_id="elite.42",
        action="buy",
        propensity=0.25,
        features_sha256=HASH,
        envelope_verdict="admitted",
        mint=_mint(),
    )
    out = rec.to_json()
    assert out["propensity"] == 0.25
    assert out["policy_id"] == "elite.42"
    assert out["envelope_verdict"] == "admitted"


def test_entity_confidence_is_bounded_and_method_is_recorded() -> None:
    """Which heuristic merged two wallets matters as much as the merge."""
    link = EntityLink(
        wallet=_mint(), entity_id="e-1", method="shared-funder", confidence=0.8,
        evidence=("funder:abc",),
    )
    assert link.to_json()["method"] == "shared-funder"
    with pytest.raises(TapeError, match="confidence"):
        EntityLink(wallet=_mint(), entity_id="e-1", method="co-sign", confidence=1.5)


# --- reading a corrupt tape --------------------------------------------------------


def test_an_unknown_schema_version_is_refused_on_read() -> None:
    with pytest.raises(TapeError, match="schema_version"):
        event_from_json({"schema_version": 999, "kind": "trade"})


def test_a_callout_records_how_the_mint_was_resolved() -> None:
    """A cashtag is a claim; a pump/dexscreener URL is an identifier. Pooling them corrupts."""
    event = TapeEvent(
        kind=EventKind.CALLOUT,
        observed_at="2026-08-13T00:00:00Z",
        provenance=Provenance(source="apify.x", fetched_at="2026-08-13T00:00:00Z"),
        body=Callout(
            mint=_mint(),
            platform="x",
            author="someone",
            resolved_from="pumpfun-url",
            text_sha256=HASH,
            author_followers=1234,
        ),
    )
    restored = event_from_json(json.loads(event.to_jsonl()))
    assert restored.body.resolved_from == "pumpfun-url"
    assert restored.body.author_followers == 1234
    assert "text" not in restored.body.to_json()  # the prose itself is never stored
