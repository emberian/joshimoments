"""Deterministic tape replay with exact fills and structurally impossible lookahead.

This is the instrument every strategy claim will rest on, so its two properties matter more
than its features.

**Fills are exact, not modelled.** In equities a backtest must guess what its order would have
done to the book, and that guess is where fidelity dies. Against an AMM the answer is
arithmetic: given the reserves recorded on the tape, the payout for a size is computable to
the lamport. This replay therefore does not *estimate* a fill — it computes one, through
``shitcoims_kernel``, which is held to exact agreement with the Lean artifact that the fill
theorems are about.

**And a fill moves the pool it fills against.** This was missing in the first version and an
adversarial audit reduced the harness to a money printer with it: because reserves were only
ever written by tape events, a policy could buy 900,000 tokens out of a 1,000,000-token pool
a hundred times over and sell 90x the entire pool back, realising 989 SOL from a pool holding
1,000 lamports. Own fills now debit the simulated reserves until the next observed reserve
reading replaces them with ground truth. A backtest that lets a policy trade without impact is
not high-fidelity, it is unbounded.

**And there is a hard participation cap, because beyond it a replay CANNOT be faithful.**
Own-fill impact alone does not save the harness: the next recorded reserve reading overwrites
it, and that reading comes from a world in which we did not trade. So a policy sized to move
the pool is being replayed against a counterfactual that no longer describes it. The audit's
money printer survived impact modelling for exactly this reason — it bought 90% of the pool
each slot and the tape kept resetting the curve underneath it.

The only honest response is to refuse the regime rather than to simulate it badly. Orders above
``max_participation_bps`` of the observed token reserve are rejected and counted. The default
is 200bps, matching PROGRAM.md's entry rule, and it is the *same* constraint a live desk faces
— so the cap is not a simulator artefact, it is the tradeable envelope.

Two residual limitations, stated rather than hidden: there is still no fee (pump.fun takes
100bps on the sell side, Raydium 25bps), so round trips remain optimistic; and the policy is
consulted after a slot's events are folded in, so it decides on a bar and fills at that bar's
close, with no latency model behind it.

**Lookahead is structurally impossible, not merely avoided.** A policy is never handed the
tape. It is handed a :class:`Snapshot` holding the prefix of events at or before the current
slot, mirroring ``View t`` in ``kernel/Joshi/History.lean`` — where the no-lookahead property
is a theorem quantified over every strategy. That discipline is worth importing because
lookahead is the most consequential bug in this literature and it is almost never visible in
the code that commits it: the same model family scored recall 0.778 under a random split and
0.234 under a temporal one, and one published "purged" cross-validation had a purge parameter
that was a literal no-op. Every one of those ran fine and produced a number.

The engine is intentionally small. It does not choose sizes, rank strategies, or score
anything — those belong to the search layer, which sits on top and is separately accountable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from shitcoims_kernel import Reserves as KernelReserves
from shitcoims_kernel import sell_out
from shitcoims_tape import EventKind, Reserves, Side, TapeEvent, Trade


class ReplayError(ValueError):
    """The tape or a policy violated the replay contract. Always fail closed."""


@dataclass(frozen=True, slots=True)
class PoolState:
    """The last observed reserves for a mint, and the slot they were observed at.

    ``slot`` is carried so a fill can never be priced against reserves the market had not
    reached yet — the single most seductive form of lookahead in an AMM backtest.
    """

    mint: str
    reserves: KernelReserves
    slot: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything a policy may see at ``slot``. The Python analogue of Lean's ``View t``.

    Construction is the guarantee: this object is built from a prefix, so a policy holding it
    cannot reach a later event even by accident.
    """

    slot: int
    pools: dict[str, PoolState]
    holdings: dict[str, int]
    lamports: int

    def reserves_for(self, mint: str) -> KernelReserves | None:
        state = self.pools.get(mint)
        return None if state is None else state.reserves


@dataclass(frozen=True, slots=True)
class Order:
    """A policy's decision. Sizes are raw base units; the engine never rounds them."""

    mint: str
    side: Side
    amount_raw: int

    def __post_init__(self) -> None:
        if isinstance(self.amount_raw, bool) or not isinstance(self.amount_raw, int):
            raise ReplayError("amount_raw must be an integer")
        if self.amount_raw <= 0:
            raise ReplayError("amount_raw must be positive")


@dataclass(frozen=True, slots=True)
class Fill:
    """What actually happened, priced from the reserves on the tape."""

    slot: int
    mint: str
    side: Side
    amount_raw: int
    lamports: int


@dataclass(slots=True)
class Ledger:
    """Realised outcome. Deliberately the only thing the engine reports.

    There is no mark-to-market. A position's value is whatever it last *sold* for, because a
    self-marked bag is the same self-referential reward that made a fabricated cost basis look
    profitable — the desk's own logs showed a machine reporting healthy PnL while losing 7.47
    SOL, and the mark was the reason.
    """

    fills: list[Fill] = field(default_factory=list)
    lamports_spent: int = 0
    lamports_received: int = 0
    rejected_orders: int = 0
    #: Orders refused because they would have moved the pool beyond the faithful range. A
    #: non-zero count means the policy WANTED a size this tape cannot honestly price.
    rejected_for_participation: int = 0

    @property
    def realised_lamports(self) -> int:
        return self.lamports_received - self.lamports_spent


Policy = Callable[[Snapshot], Order | None]


def _reserves_from(body: Reserves) -> KernelReserves:
    """Total depth, virtual plus real.

    Both halves matter: a pump.fun bonding curve carries virtual reserves that vanish at
    migration, so pricing a pre-graduation fill from the real side alone understates depth
    on exactly the events where the dumps concentrate.
    """
    return KernelReserves(
        token_raw=body.real_tokens + body.virtual_tokens,
        sol_lamports=body.real_sol + body.virtual_sol,
    )


def _slot_of(event: TapeEvent) -> int:
    if event.chain is None:
        raise ReplayError(f"{event.kind} carries no chainstamp and cannot be ordered")
    return event.chain.slot


def replay(
    events: Iterable[TapeEvent],
    policy: Policy,
    *,
    starting_lamports: int = 0,
    max_participation_bps: int = 200,
) -> Ledger:
    """Run ``policy`` over ``events`` in chain order, filling from recorded reserves.

    The policy is consulted once per slot, after that slot's events have been folded in, and
    is given only the state implied by events at or before it.
    """
    ordered = _ordered(events)
    ledger = Ledger()
    pools: dict[str, PoolState] = {}
    holdings: dict[str, int] = {}
    lamports = starting_lamports

    for slot, batch in ordered:
        for event in batch:
            # isinstance, not just `kind`: the schema guarantees the correspondence, but a
            # kind check narrows nothing for a reader or a checker, and the failure mode of
            # getting it wrong is an attribute error deep inside a replay of millions of fills.
            if event.kind is EventKind.RESERVE and isinstance(event.body, Reserves):
                body = event.body
                mint = _mint_for_pool(body.pool, batch)
                if mint is not None:
                    # Stamped from the EVENT's own chainstamp, never from the loop variable.
                    # Taking it from the loop makes the field agree with the current slot by
                    # construction, so it witnesses nothing and cannot catch a reading that
                    # arrived from the future.
                    pools[mint] = PoolState(
                        mint=mint, reserves=_reserves_from(body), slot=_slot_of(event)
                    )

        order = policy(
            Snapshot(
                slot=slot,
                pools=dict(pools),
                holdings=dict(holdings),
                lamports=lamports,
            )
        )
        if order is None:
            continue

        state = pools.get(order.mint)
        if state is not None and max_participation_bps < 10_000:
            cap = state.reserves.token_raw * max_participation_bps // 10_000
            if order.amount_raw > cap:
                ledger.rejected_for_participation += 1
                continue
        if state is None:
            # No observed reserves means no computable fill. Refusing is the only honest
            # option: a modelled price here would be exactly the fabrication this engine
            # exists to avoid.
            ledger.rejected_orders += 1
            continue

        if order.side is Side.SELL:
            held = holdings.get(order.mint, 0)
            if order.amount_raw > held:
                ledger.rejected_orders += 1
                continue
            proceeds = sell_out(state.reserves, order.amount_raw)
            holdings[order.mint] = held - order.amount_raw
            lamports += proceeds
            ledger.lamports_received += proceeds
            # The sale moves the curve: tokens in, lamports out.
            pools[order.mint] = PoolState(
                mint=order.mint,
                reserves=KernelReserves(
                    token_raw=state.reserves.token_raw + order.amount_raw,
                    sol_lamports=state.reserves.sol_lamports - proceeds,
                ),
                slot=state.slot,
            )
            ledger.fills.append(
                Fill(slot, order.mint, Side.SELL, order.amount_raw, proceeds)
            )
        else:
            try:
                cost = _buy_cost(state.reserves, order.amount_raw)
            except ReplayError:
                # An order larger than the pool is unfillable, not fatal. Aborting the whole
                # replay on one bad order would destroy a run over a single thin pool.
                ledger.rejected_orders += 1
                continue
            if cost > lamports:
                ledger.rejected_orders += 1
                continue
            holdings[order.mint] = holdings.get(order.mint, 0) + order.amount_raw
            lamports -= cost
            ledger.lamports_spent += cost
            # The purchase moves the curve the other way: tokens out, lamports in.
            pools[order.mint] = PoolState(
                mint=order.mint,
                reserves=KernelReserves(
                    token_raw=state.reserves.token_raw - order.amount_raw,
                    sol_lamports=state.reserves.sol_lamports + cost,
                ),
                slot=state.slot,
            )
            ledger.fills.append(Fill(slot, order.mint, Side.BUY, order.amount_raw, cost))

    return ledger


def _buy_cost(reserves: KernelReserves, amount_raw: int) -> int:
    """Lamports needed to take ``amount_raw`` tokens out of a constant-product pool.

    The mirror of ``sell_out``: ``x*y=k`` gives ``cost = ceil(Y*a / (X-a))``. Rounding is
    UP, against the buyer, matching how a pool never sells for less than the curve says.
    A buy larger than the pool is impossible rather than expensive.
    """
    if amount_raw >= reserves.token_raw:
        raise ReplayError("cannot buy the entire token reserve")
    numerator = reserves.sol_lamports * amount_raw
    denominator = reserves.token_raw - amount_raw
    return -(-numerator // denominator)


def _mint_for_pool(pool: str | None, batch: Sequence[TapeEvent]) -> str | None:
    """Attribute a reserve reading to a mint using only events in the same slot."""
    for event in batch:
        body = event.body
        if isinstance(body, Trade) and body.pool == pool:
            return str(body.mint)
    return None


def _ordered(events: Iterable[TapeEvent]) -> list[tuple[int, list[TapeEvent]]]:
    """Group events by slot in ascending order, refusing anything unorderable.

    Sorting here rather than trusting the tape is deliberate: a recorder that pages history
    backwards emits newest-first, and replaying in arrival order would run the market in
    reverse — which is not a subtle error but it is a silent one.
    """
    batches: dict[int, list[TapeEvent]] = {}
    for event in events:
        if event.kind in {EventKind.TRADE, EventKind.RESERVE}:
            batches.setdefault(_slot_of(event), []).append(event)
        elif event.chain is not None:
            batches.setdefault(event.chain.slot, []).append(event)
    return [(slot, batches[slot]) for slot in sorted(batches)]
