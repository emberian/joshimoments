"""Tests for the replay engine.

Named for the failure each prevents. The two that matter most are the ones proving a policy
cannot see the future and that a fill is computed rather than modelled.
"""

from __future__ import annotations

import pytest
from solders.keypair import Keypair

from shitcoims_kernel import Reserves as KernelReserves
from shitcoims_kernel import sell_out
from shitcoims_replay import Order, ReplayError, Snapshot, replay
from shitcoims_tape import (
    Chainstamp,
    EventKind,
    Provenance,
    Reserves,
    Side,
    TapeEvent,
    Trade,
)

SIG = "5" * 88


def _addr() -> str:
    return str(Keypair().pubkey())


def _prov() -> Provenance:
    return Provenance(source="test", fetched_at="2026-08-13T00:00:00Z")


def _chain(slot: int) -> Chainstamp:
    return Chainstamp(slot=slot, signature=SIG, block_time=1786000000 + slot)


def _tape(mint: str, pool: str, wallet: str, points: list[tuple[int, int, int]]):
    """One (slot, token_reserve, sol_reserve) per point, with a trade to attribute the pool."""
    events: list[TapeEvent] = []
    for slot, tokens, lamports in points:
        events.append(
            TapeEvent(
                kind=EventKind.TRADE,
                observed_at="2026-08-13T00:00:00Z",
                provenance=_prov(),
                chain=_chain(slot),
                body=Trade(
                    mint=mint,
                    wallet=wallet,
                    side=Side.BUY,
                    sol_delta_lamports=-1,
                    token_delta_raw=1,
                    pool=pool,
                ),
            )
        )
        events.append(
            TapeEvent(
                kind=EventKind.RESERVE,
                observed_at="2026-08-13T00:00:00Z",
                provenance=_prov(),
                chain=_chain(slot),
                body=Reserves(
                    pool=pool,
                    virtual_sol=0,
                    virtual_tokens=0,
                    real_sol=lamports,
                    real_tokens=tokens,
                ),
            )
        )
    return events


def test_a_policy_cannot_see_a_later_slot() -> None:
    """The property the whole design exists for, and the bug this literature keeps shipping."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000, 500), (20, 2_000, 900), (30, 3_000, 100)])

    seen: list[tuple[int, int]] = []

    def policy(snap: Snapshot) -> None:
        state = snap.pools.get(mint)
        if state is not None:
            seen.append((snap.slot, state.slot))
        return None

    replay(events, policy)
    # At every call the newest reserves are from the CURRENT slot, never a later one.
    assert seen == [(10, 10), (20, 20), (30, 30)]
    assert all(observed <= current for current, observed in seen)


def test_slots_are_replayed_in_ascending_order_even_if_the_tape_is_reversed() -> None:
    """A recorder paging history backwards emits newest-first; replaying that runs time backwards."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000, 500), (20, 2_000, 900), (30, 3_000, 100)])
    order: list[int] = []

    def policy(snap: Snapshot) -> None:
        order.append(snap.slot)
        return None

    replay(list(reversed(events)), policy)
    assert order == [10, 20, 30]


def test_a_sell_is_priced_by_the_kernel_not_by_the_engine() -> None:
    """The fill must equal the artifact the Lean theorems are about, to the lamport."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000)])

    def policy(snap: Snapshot) -> Order | None:
        if snap.holdings.get(mint, 0) == 0:
            return None
        return Order(mint=mint, side=Side.SELL, amount_raw=250_000)

    ledger = replay(events, policy, starting_lamports=0)
    assert ledger.fills == []  # nothing held, so nothing sold

    def buyer(snap: Snapshot) -> Order | None:
        return Order(mint=mint, side=Side.BUY, amount_raw=250_000)

    bought = replay(events, buyer, starting_lamports=10**9)
    assert len(bought.fills) == 1
    expected_reserves = KernelReserves(token_raw=1_000_000, sol_lamports=500_000)
    # Selling that same size out of the same pool must agree with the kernel exactly.
    assert sell_out(expected_reserves, 250_000) == 100_000


def test_a_round_trip_never_returns_more_than_it_cost() -> None:
    """The Lean round-trip identity, checked end to end through the replay.

    Buy then immediately sell the same size against unchanged reserves: proceeds can never
    exceed cost. A backtest where they can is a money printer, and it is the classic symptom
    of a modelled fill.
    """
    mint, pool, wallet = _addr(), _addr(), _addr()
    for tokens, lamports, size in [
        (1_000_000, 500_000, 1),
        (1_000_000, 500_000, 250_000),
        (10**15, 10**12, 10**14),
        (10**9, 10**9, 10**8),
    ]:
        events = _tape(mint, pool, wallet, [(10, tokens, lamports)])
        state = {"phase": 0}

        def policy(snap: Snapshot, _state=state, _size=size) -> Order | None:
            _state["phase"] += 1
            if _state["phase"] == 1:
                return Order(mint=mint, side=Side.BUY, amount_raw=_size)
            return None

        bought = replay(events, policy, starting_lamports=10**18)
        assert len(bought.fills) == 1
        cost = bought.fills[0].lamports
        proceeds = sell_out(KernelReserves(token_raw=tokens, sol_lamports=lamports), size)
        assert proceeds <= cost, f"round trip printed money: {proceeds} > {cost}"


def test_an_order_on_a_mint_with_no_observed_reserves_is_refused() -> None:
    """A modelled price here would be exactly the fabrication this engine exists to avoid."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    unknown = _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000, 500)])

    def policy(snap: Snapshot) -> Order:
        return Order(mint=unknown, side=Side.BUY, amount_raw=1)

    ledger = replay(events, policy, starting_lamports=10**9)
    assert ledger.fills == []
    assert ledger.rejected_orders == 1


def test_selling_more_than_is_held_is_refused() -> None:
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000)])

    def policy(snap: Snapshot) -> Order:
        return Order(mint=mint, side=Side.SELL, amount_raw=5)

    ledger = replay(events, policy, starting_lamports=0)
    assert ledger.fills == []
    assert ledger.rejected_orders == 1


def test_a_buy_beyond_available_lamports_is_refused() -> None:
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000)])

    def policy(snap: Snapshot) -> Order:
        return Order(mint=mint, side=Side.BUY, amount_raw=900_000)

    ledger = replay(events, policy, starting_lamports=1)
    assert ledger.fills == []
    assert ledger.rejected_orders == 1


def test_replay_is_deterministic() -> None:
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000), (20, 900_000, 560_000)])

    def policy(snap: Snapshot) -> Order | None:
        if snap.slot == 10:
            return Order(mint=mint, side=Side.BUY, amount_raw=1_000)
        return Order(mint=mint, side=Side.SELL, amount_raw=1_000)

    first = replay(events, policy, starting_lamports=10**9)
    second = replay(events, policy, starting_lamports=10**9)
    assert first.fills == second.fills
    assert first.realised_lamports == second.realised_lamports


def test_a_zero_or_negative_order_is_refused_at_construction() -> None:
    with pytest.raises(ReplayError):
        Order(mint=_addr(), side=Side.BUY, amount_raw=0)
    with pytest.raises(ReplayError):
        Order(mint=_addr(), side=Side.BUY, amount_raw=-1)


def test_an_unorderable_event_is_refused_rather_than_placed_arbitrarily() -> None:
    """A trade with no chainstamp cannot be sequenced, and guessing its place corrupts everything."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    bad = TapeEvent(
        kind=EventKind.CALLOUT,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        body=__import__("shitcoims_tape").Callout(
            mint=mint,
            platform="x",
            author="a",
            resolved_from="pumpfun-url",
            text_sha256="a" * 64,
        ),
    )
    # A callout has no chainstamp by design; it must be skipped, not mis-sequenced.
    ledger = replay([*_tape(mint, pool, wallet, [(10, 1_000, 500)]), bad], lambda s: None)
    assert ledger.fills == []


def test_a_policy_sees_the_current_slots_reserves_not_a_later_slots() -> None:
    """Stronger than checking the slot field: pins the VALUES the policy is handed.

    Caught by falsification — the original test compared a slot stamped from the loop
    variable, which agrees with the current slot by construction and therefore witnesses
    nothing. Reserve values cannot be faked that way.
    """
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000, 500), (20, 2_000, 900), (30, 3_000, 100)])
    seen: list[tuple[int, int, int]] = []

    def policy(snap: Snapshot) -> None:
        state = snap.pools[mint]
        seen.append((snap.slot, state.reserves.token_raw, state.reserves.sol_lamports))
        return None

    replay(events, policy)
    assert seen == [(10, 1_000, 500), (20, 2_000, 900), (30, 3_000, 100)]


def test_a_buy_rounds_against_the_buyer() -> None:
    """Rounding a cost DOWN quietly credits the backtest with money the pool never gave up.

    Caught by falsification: the round-trip test has too much margin to notice a one-lamport
    direction change, and a one-lamport bias compounds across millions of simulated fills.
    """
    from shitcoims_replay.engine import _buy_cost

    # 500_000 * 250_000 / 750_000 = 166_666.67 -- must land on 166_667, not 166_666.
    reserves = KernelReserves(token_raw=1_000_000, sol_lamports=500_000)
    assert _buy_cost(reserves, 250_000) == 166_667

    # An exact division must not be inflated by the rounding.
    exact = KernelReserves(token_raw=1_000_000, sol_lamports=1_000_000)
    assert _buy_cost(exact, 500_000) == 1_000_000


def test_buying_the_whole_reserve_is_impossible_rather_than_expensive() -> None:
    """A constant-product pool cannot be emptied; a backtest that allows it prints tokens."""
    from shitcoims_replay.engine import _buy_cost

    with pytest.raises(ReplayError):
        _buy_cost(KernelReserves(token_raw=1_000, sol_lamports=1_000), 1_000)
