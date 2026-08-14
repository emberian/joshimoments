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
    Callout,
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


def test_a_sell_actually_happens_and_is_priced_by_the_kernel() -> None:
    """A REAL sell, with the ledger asserted numerically.

    The previous version of this test contained no sell at all: its policy returned None
    while holdings were zero, and its only numeric assertion called the kernel directly
    without touching the ledger. An adversarial audit showed four mutations surviving it —
    including `proceeds = 0` and `proceeds = 2 * sell_out(...)`, a literal money printer.
    """
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000), (20, 1_000_000, 500_000)])

    def policy(snap: Snapshot) -> Order | None:
        if snap.slot == 10:
            return Order(mint=mint, side=Side.BUY, amount_raw=10_000)
        held = snap.holdings.get(mint, 0)
        return Order(mint=mint, side=Side.SELL, amount_raw=held) if held else None

    ledger = replay(events, policy, starting_lamports=10**9)
    buys = [f for f in ledger.fills if f.side is Side.BUY]
    sells = [f for f in ledger.fills if f.side is Side.SELL]
    assert len(buys) == 1 and len(sells) == 1

    # Slot 20 carries a fresh reserve reading, and RECORDED GROUND TRUTH WINS over our own
    # simulated impact — so the sell prices against the tape, not against the curve our buy
    # moved. That is the honest semantic and the reason a participation cap is needed: the
    # tape comes from a world in which we did not trade, so beyond a small size the replay
    # cannot be faithful no matter how carefully the fill is computed.
    observed = KernelReserves(token_raw=1_000_000, sol_lamports=500_000)
    assert sells[0].lamports == sell_out(observed, 10_000)
    assert ledger.lamports_received == sells[0].lamports
    assert ledger.lamports_spent == buys[0].lamports
    # A round trip against an unchanged pool must LOSE. Anything else is a printer.
    assert ledger.realised_lamports < 0


def test_the_ledger_totals_are_exact_lamport_counts() -> None:
    """`realised_lamports` is the only number this module asks anyone to believe.

    Every other ledger assertion in this file checks the totals against the engine's own
    fills, which is self-consistency rather than correctness: a run that mis-prices both in
    the same direction still agrees with itself. These are hand-computed from the constant
    product and the rounding rule, so the totals are pinned to arithmetic, not to the engine.
    """
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000), (20, 1_000_000, 500_000)])

    def policy(snap: Snapshot) -> Order | None:
        if snap.slot == 10:
            return Order(mint=mint, side=Side.BUY, amount_raw=10_000)
        held = snap.holdings.get(mint, 0)
        return Order(mint=mint, side=Side.SELL, amount_raw=held) if held else None

    ledger = replay(events, policy, starting_lamports=10**9)

    # Buy:  ceil(500_000 * 10_000 / (1_000_000 - 10_000)) = ceil(5050.505...) = 5_051.
    # Sell: floor(500_000 * 10_000 / (1_000_000 + 10_000)) = floor(4950.495...) = 4_950,
    #       priced against the fresh slot-20 reading, which is unchanged from slot 10.
    assert ledger.lamports_spent == 5_051
    assert ledger.lamports_received == 4_950
    assert ledger.realised_lamports == -101
    assert [f.lamports for f in ledger.fills] == [5_051, 4_950]
    assert [f.slot for f in ledger.fills] == [10, 20]
    assert ledger.rejected_orders == 0
    assert ledger.rejected_for_participation == 0


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

        bought = replay(events, policy, starting_lamports=10**18, max_participation_bps=10_000)
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

    ledger = replay(events, policy, starting_lamports=1, max_participation_bps=10_000)
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


def test_a_chainless_event_is_skipped_rather_than_placed_at_slot_zero() -> None:
    """A callout has no chainstamp by design; it must be skipped, not mis-sequenced.

    The previous version of this test ran a policy of ``lambda s: None`` and asserted the
    ledger was empty — true of every possible implementation, including one that dumps every
    unstamped event at slot 0 and hands the policy a phantom decision point before the market
    exists. The policy here decides on every call and the slots it sees are pinned, so a
    fabricated slot is visible.
    """
    mint, pool, wallet = _addr(), _addr(), _addr()
    tape = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000), (20, 1_000_000, 500_000)])
    callout = TapeEvent(
        kind=EventKind.CALLOUT,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        body=Callout(
            mint=mint,
            platform="x",
            author="a",
            resolved_from="pumpfun-url",
            text_sha256="a" * 64,
        ),
    )

    slots: list[int] = []

    def policy(snap: Snapshot) -> Order | None:
        slots.append(snap.slot)
        return Order(mint=mint, side=Side.BUY, amount_raw=1_000) if snap.slot == 10 else None

    ledger = replay([callout, *tape], policy, starting_lamports=10**9)
    assert slots == [10, 20], "the unstamped callout created a decision point of its own"
    assert len(ledger.fills) == 1
    assert ledger.rejected_orders == 0


def test_an_orderable_event_without_a_chainstamp_is_refused_rather_than_guessed() -> None:
    """A trade cannot be sequenced without a chainstamp, and guessing corrupts everything.

    The schema already refuses to build one, so this reaches past the constructor to make the
    engine's own guard testable. That the guard is unreachable through the front door is the
    point: it is the second lock, and a second lock nobody has ever turned is not a lock.
    """
    from shitcoims_replay.engine import _slot_of

    mint, pool, wallet = _addr(), _addr(), _addr()
    orphan = TapeEvent(
        kind=EventKind.TRADE,
        observed_at="2026-08-13T00:00:00Z",
        provenance=_prov(),
        chain=_chain(15),
        body=Trade(
            mint=mint, wallet=wallet, side=Side.BUY,
            sol_delta_lamports=-1, token_delta_raw=1, pool=pool,
        ),
    )
    object.__setattr__(orphan, "chain", None)

    with pytest.raises(ReplayError, match="cannot be ordered"):
        _slot_of(orphan)
    with pytest.raises(ReplayError, match="cannot be ordered"):
        replay([*_tape(mint, pool, wallet, [(10, 1_000, 500)]), orphan], lambda s: None)


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


def test_the_replay_is_not_a_money_printer() -> None:
    """The regression for the worst defect an adversarial audit found in this harness.

    With reserves written only by tape events and no participation cap, a policy could buy
    90% of a pool every slot and sell back 90x the entire pool — realising 989 SOL from a
    pool holding 1,000 lamports, reported as `realised_lamports`, the one number this module
    claims is trustworthy.

    Two things stop it now, and this pins both: own fills move the simulated curve, and
    orders beyond the faithful range are refused rather than priced.
    """
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(s, 1_000_000, 1_000) for s in range(10, 110)])
    events += _tape(mint, pool, wallet, [(200, 1_000_000, 10**12)])

    def hog(snap: Snapshot) -> Order | None:
        if snap.slot < 200:
            return Order(mint=mint, side=Side.BUY, amount_raw=900_000)
        held = snap.holdings.get(mint, 0)
        return Order(mint=mint, side=Side.SELL, amount_raw=held) if held else None

    ledger = replay(events, hog, starting_lamports=10**18)
    assert ledger.fills == []
    assert ledger.rejected_for_participation > 0
    assert ledger.realised_lamports == 0


def test_an_own_fill_moves_the_pool_it_fills_against() -> None:
    """Reserves must be debited by our own trade, not only by tape events."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000)])
    seen: list[tuple[int, int]] = []

    def policy(snap: Snapshot) -> Order | None:
        state = snap.pools.get(mint)
        if state is not None:
            seen.append((state.reserves.token_raw, state.reserves.sol_lamports))
        return Order(mint=mint, side=Side.BUY, amount_raw=10_000) if snap.slot == 10 else None

    replay(events, policy, starting_lamports=10**12)
    # Only one slot, so we observe the pre-fill state; assert the post-fill state directly.
    assert seen == [(1_000_000, 500_000)]

    two_slots = _tape(mint, pool, wallet, [(10, 1_000_000, 500_000)])
    # A second decision point with NO new reserve event: the policy must see our own impact.
    two_slots += [
        TapeEvent(
            kind=EventKind.TRADE,
            observed_at="2026-08-13T00:00:00Z",
            provenance=_prov(),
            chain=_chain(20),
            body=Trade(
                mint=mint, wallet=wallet, side=Side.BUY,
                sol_delta_lamports=-1, token_delta_raw=1, pool=pool,
            ),
        )
    ]
    later: list[tuple[int, int]] = []

    def watcher(snap: Snapshot) -> Order | None:
        state = snap.pools.get(mint)
        if state is not None:
            later.append((state.reserves.token_raw, state.reserves.sol_lamports))
        return Order(mint=mint, side=Side.BUY, amount_raw=10_000) if snap.slot == 10 else None

    replay(two_slots, watcher, starting_lamports=10**12)
    assert later[0] == (1_000_000, 500_000)
    assert later[1][0] == 990_000, "our purchase did not remove tokens from the pool"
    assert later[1][1] > 500_000, "our purchase did not add lamports to the pool"


def test_an_oversized_buy_rejects_rather_than_aborting_the_whole_replay() -> None:
    """One unfillable order must not destroy a run that may have taken hours."""
    mint, pool, wallet = _addr(), _addr(), _addr()
    events = _tape(mint, pool, wallet, [(10, 1_000, 500_000)])

    def policy(snap: Snapshot) -> Order:
        return Order(mint=mint, side=Side.BUY, amount_raw=5_000)

    ledger = replay(events, policy, starting_lamports=10**18, max_participation_bps=10_000)
    assert ledger.fills == []
    assert ledger.rejected_orders == 1
