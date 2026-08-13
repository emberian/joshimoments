"""Tests for mint-indexed panel collection.

The properties under test are the ones that decide whether the collected panel can be
believed: a mint the budget never reached must be *on the tape* as censored rather than
absent, a mint we truncated must not read as a quiet token, a terminal outcome the chain
supplied must survive the collector's own bookkeeping, and the signal-#1 feasibility gate
must reproduce the arithmetic PROGRAM.md 4.1 states.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from solders.keypair import Keypair

from shitcoims_tape import EventKind, WatchClose
from shitcoims_tape.panel import (
    FrameMint,
    collect_panel,
    feasible_universe,
    read_frame,
    refusal_window,
    wallet_activity,
    write_frame,
)
from shitcoims_tape.recorder import WRAPPED_SOL_MINT, CreditBudget
from shitcoims_tape.writer import TapeWriter
from tests.test_tape_recorder import (
    Sink,
    _create_values,
    _trade_values,
    pump_logs,
    transaction,
)


def _key() -> str:
    return str(Keypair().pubkey())


class FakePagedClient:
    """Pages keyed by address; cursors are page indices, ``None`` means exhausted."""

    def __init__(self, pages: dict[str, Sequence[Sequence[dict[str, Any]]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str | None]] = []

    async def address_history_page(
        self,
        address: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        sort_order: str = "asc",
        succeeded_only: bool = True,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        self.calls.append((address, cursor))
        pages = self.pages.get(address, ())
        index = 0 if cursor is None else int(cursor)
        if index >= len(pages):
            return (), None
        return tuple(pages[index]), str(index + 1)


def _launch_and_trade(mint: str, wallet: str, *, slot: int, signature: str) -> dict[str, Any]:
    return transaction(
        pump_logs(
            ("CreateEvent", _create_values(mint, wallet, _key())),
            ("TradeEvent", _trade_values(mint, wallet, is_buy=True)),
        ),
        slot=slot,
        signature=signature,
    )


def _trade_only(mint: str, wallet: str, *, slot: int, signature: str) -> dict[str, Any]:
    return transaction(
        pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))),
        slot=slot,
        signature=signature,
    )


async def test_a_mint_the_budget_never_reached_is_on_the_tape_as_displaced() -> None:
    """Frame truncation must be a counted row, not a smaller n nobody can see."""

    reached, skipped = _key(), _key()
    wallet = _key()
    client = FakePagedClient(
        {reached: [[_launch_and_trade(reached, wallet, slot=10, signature="5" * 88)]]}
    )
    sink = Sink()
    frame = [FrameMint(reached, "cohort"), FrameMint(skipped, "cohort")]
    # Exactly two pages: one of data and one to prove the cursor ran out. Nothing left.
    budget = CreditBudget(limit=20)

    report = await collect_panel(client, sink, frame, budget=budget)

    assert report.mints_reached == 1
    assert report.mints_displaced == 1
    assert budget.spent <= budget.limit
    windows = [event.body for event in sink.of(EventKind.WATCH)]
    displaced = [w for w in windows if w.close_reason is WatchClose.DISPLACED]
    assert [w.mint for w in displaced] == [skipped]
    assert displaced[0].closed_at == displaced[0].opened_at  # nothing was ever observed
    assert "credit_budget_exhausted" in report.gaps


async def test_a_truncated_mint_closes_informatively_rather_than_reading_as_a_quiet_token() -> None:
    mint, wallet = _key(), _key()
    client = FakePagedClient(
        {
            mint: [
                [_launch_and_trade(mint, wallet, slot=10, signature="5" * 88)],
                [_trade_only(mint, wallet, slot=11, signature="4" * 88)],
                [_trade_only(mint, wallet, slot=12, signature="3" * 88)],
            ]
        }
    )
    sink = Sink()
    budget = CreditBudget(limit=10_000)

    report = await collect_panel(
        client, sink, [FrameMint(mint, "cohort")], budget=budget, page_cap=1
    )

    assert report.mints_truncated == 1
    outcome = report.outcomes[0]
    assert outcome.history is not None and outcome.history.stopped_by == "page_cap"
    assert outcome.close_reason == str(WatchClose.OBSERVER_LOST)
    closed = [
        event.body
        for event in sink.of(EventKind.WATCH)
        if event.body.close_reason is not None
    ]
    assert [w.close_reason for w in closed] == [WatchClose.OBSERVER_LOST]
    assert closed[0].is_informatively_censored


async def test_a_complete_read_closes_on_the_clock_and_is_not_counted_as_censoring() -> None:
    mint, wallet = _key(), _key()
    client = FakePagedClient(
        {mint: [[_launch_and_trade(mint, wallet, slot=10, signature="5" * 88)]]}
    )
    sink = Sink()

    report = await collect_panel(
        client, sink, [FrameMint(mint, "cohort")], budget=CreditBudget(limit=10_000)
    )

    assert report.mints_truncated == 0
    assert report.outcomes[0].close_reason == str(WatchClose.DEADLINE)
    closed = [
        event.body
        for event in sink.of(EventKind.WATCH)
        if event.body.close_reason is not None
    ]
    assert not any(w.is_informatively_censored for w in closed)


async def test_a_graduation_the_chain_supplied_is_not_overwritten_by_our_clock() -> None:
    """The terminal close carries chainstamps; a second clock-based window would hide them."""

    mint, wallet = _key(), _key()
    graduation = transaction(
        pump_logs(
            (
                "CompleteEvent",
                {
                    "user": wallet,
                    "mint": mint,
                    "bonding_curve": _key(),
                    "timestamp": 1786000264,
                    "quote_mint": WRAPPED_SOL_MINT,
                },
            )
        ),
        slot=11,
        signature="4" * 88,
    )
    client = FakePagedClient(
        {mint: [[_launch_and_trade(mint, wallet, slot=10, signature="5" * 88), graduation]]}
    )
    sink = Sink()

    report = await collect_panel(
        client, sink, [FrameMint(mint, "cohort")], budget=CreditBudget(limit=10_000)
    )

    assert report.outcomes[0].close_reason == str(WatchClose.GRADUATED)
    closed = [
        event
        for event in sink.of(EventKind.WATCH)
        if event.body.close_reason is not None
    ]
    assert [event.body.close_reason for event in closed] == [WatchClose.GRADUATED]
    # Both ends chain-stamped is what makes a time-to-graduation measurable at all.
    opened = [event for event in sink.of(EventKind.WATCH) if event.body.close_reason is None]
    assert opened[0].chain is not None and closed[0].chain is not None


async def test_the_frame_round_trips_through_disk_before_a_credit_is_spent(
    tmp_path: Path,
) -> None:
    frame = [
        FrameMint(_key(), "cohort", launched_at="2026-08-13T18:00:00+00:00", listed_complete=False),
        FrameMint(_key(), "graduated", listed_complete=True, listed_market_cap_usd=41000.5),
    ]
    path = tmp_path / "frame.jsonl"

    assert write_frame(path, frame) == 2
    assert read_frame(path) == tuple(frame)


async def test_wallet_activity_counts_distinct_mints_per_wallet(tmp_path: Path) -> None:
    mint_a, mint_b, tourist, regular = _key(), _key(), _key(), _key()
    client = FakePagedClient(
        {
            mint_a: [
                [
                    _launch_and_trade(mint_a, regular, slot=10, signature="5" * 88),
                    # A SECOND trade by the same wallet on the same mint: the number that
                    # decides signal #1 is distinct TOKENS per wallet, and a panel that
                    # counts trades instead would report this wallet at 3 and be wrong.
                    _trade_only(mint_a, regular, slot=10, signature="2" * 88),
                    _trade_only(mint_a, tourist, slot=10, signature="4" * 88),
                ]
            ],
            mint_b: [[_launch_and_trade(mint_b, regular, slot=20, signature="3" * 88)]],
        }
    )
    writer = TapeWriter(tmp_path, prefix="panel")
    try:
        await collect_panel(
            client,
            writer.write,
            [FrameMint(mint_a, "cohort"), FrameMint(mint_b, "cohort")],
            budget=CreditBudget(limit=10_000),
        )
    finally:
        writer.close()

    activity = wallet_activity(writer.segments())
    assert len(activity[regular]) == 2  # three trades, two tokens
    assert len(activity[tourist]) == 1


def test_the_refusal_window_is_zero_length_and_informative() -> None:
    now = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)
    event = refusal_window(_key(), now=now, horizon=timedelta(hours=1), source="panel")
    assert event.body.close_reason is WatchClose.DISPLACED
    assert event.body.is_informatively_censored
    assert event.body.opened_at == event.body.closed_at
    assert event.chain is None  # a refusal is an observer fact; no transaction produced it


def test_the_feasibility_gate_reproduces_the_documented_universe_caps() -> None:
    """PROGRAM.md 4.1: at T=300 the cap is ~10 wallets at a floor of 2 and ~6,597 at 5."""

    assert feasible_universe(300, 2) == 10
    assert feasible_universe(300, 5) == 6_597
    assert feasible_universe(300, 8) > 1_000_000
    # A pair on ONE token carries no information at all, whatever n is: C(300,1)=300 cannot
    # clear a Bonferroni threshold over even a single pair's nine tests.
    assert feasible_universe(300, 1) == 0
    assert feasible_universe(300, 0) == 0
    # More tokens is monotonically more headroom at a fixed floor.
    assert feasible_universe(600, 5) > feasible_universe(300, 5)


def test_frame_coverage_reports_no_unobserved_mass_only_when_there_are_no_singletons() -> None:
    """Chao1, not Lincoln-Petersen: the sweeps are not independent draws.

    Measured over twelve sweeps of pump.fun's listing, capture counts were UNDER-dispersed —
    every mint seen 6 to 10 times out of 12, none seen 11 or 12 and none fewer than 6 — which
    is a rotating slice, not independent sampling. Lincoln-Petersen assumes independence and
    is biased UP under negative dependence; it duly reported 525 against a 12-sweep union of
    469, a shortfall no amount of further sweeping could ever close.
    """

    from shitcoims_tape.panel import frame_coverage

    # Two sweeps of the real listing: 597 mints seen once, and it is nowhere near complete.
    thin = frame_coverage([1] * 597 + [2] * 424)
    assert thin.observed == 1021
    assert round(thin.chao1) == 1441
    assert 0.70 < thin.coverage < 0.71

    # Four sweeps: no mint seen only once, so the lower bound meets the observed count.
    thick = frame_coverage([2] * 441 + [3] * 300 + [4] * 172)
    assert thick.singletons == 0
    assert thick.chao1 == float(thick.observed)
    assert thick.coverage == 1.0
    assert thick.good_turing == 1.0

    # A singleton with no doubletons still has to raise the estimate; the f2=0 branch is the
    # one a bimodal capture distribution actually lands on.
    assert frame_coverage([1, 1, 1, 5, 5]).chao1 == 5 + 3.0
    assert frame_coverage([]).coverage == 0.0
