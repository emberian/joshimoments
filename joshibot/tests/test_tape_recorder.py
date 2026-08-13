"""Tests for the tape recorder.

Events are Borsh-encoded against the *pinned production layouts* rather than hand-written
dicts, so these exercise the real decoder and would catch a layout drift as well as a
recorder bug.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from shitcoims_intelligence.pump_layouts import (
    PUMP_AMM_EVENT_LAYOUTS,
    PUMP_EVENT_LAYOUTS,
    PUMP_PROGRAM_ID,
    EventLayout,
)
from shitcoims_tape import EventKind, Reserves, Side, TapeEvent, Trade, WatchClose
from shitcoims_tape.recorder import (
    WRAPPED_SOL_MINT,
    CreditBudget,
    CreditBudgetExceeded,
    TapeRecorder,
    attribute_program_data,
)
from shitcoims_tape.watch import WatchRegistry

T0 = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
SIG = "5" * 88
OTHER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"

_LAYOUTS: dict[str, EventLayout] = {
    layout.event_name: layout for layout in (*PUMP_EVENT_LAYOUTS, *PUMP_AMM_EVENT_LAYOUTS)
}
_ZERO_KEY = str(Pubkey.default())


def _mint() -> str:
    return str(Keypair().pubkey())


# --- Borsh encoder driven by the pinned layouts ------------------------------------


def _encode(spec: Any, value: Any) -> bytes:
    if spec == "u8":
        return int(value).to_bytes(1, "little")
    if spec == "u16":
        return int(value).to_bytes(2, "little")
    if spec == "u32":
        return int(value).to_bytes(4, "little")
    if spec == "u64":
        return int(value).to_bytes(8, "little")
    if spec == "i64":
        return int(value).to_bytes(8, "little", signed=True)
    if spec == "i128":
        return int(value).to_bytes(16, "little", signed=True)
    if spec == "bool":
        return (1 if value else 0).to_bytes(1, "little")
    if spec == "pubkey":
        return bytes(Pubkey.from_string(str(value)))
    if spec == "string":
        raw = str(value).encode("utf-8")
        return len(raw).to_bytes(4, "little") + raw
    if isinstance(spec, tuple) and spec[0] == "vec":
        items = list(value or [])
        out = len(items).to_bytes(4, "little")
        for item in items:
            for name, sub in spec[1]:
                out += _encode(sub, item[name])
        return out
    raise AssertionError(f"unsupported spec {spec!r}")


def _default(spec: Any) -> Any:
    if spec == "pubkey":
        return _ZERO_KEY
    if spec == "string":
        return ""
    if spec == "bool":
        return False
    if isinstance(spec, tuple):
        return []
    return 0


def encode_event(name: str, values: Mapping[str, Any]) -> tuple[str, str]:
    """Return ``(program_id, base64 payload)`` for one pinned event layout."""

    layout = _LAYOUTS[name]
    body = b"".join(
        _encode(spec, values.get(field, _default(spec))) for field, spec in layout.fields
    )
    return layout.program_id, base64.b64encode(layout.discriminator + body).decode("ascii")


def program_data(name: str, values: Mapping[str, Any]) -> tuple[str, str]:
    program_id, payload = encode_event(name, values)
    return program_id, f"Program data: {payload}"


def pump_logs(*events: tuple[str, Mapping[str, Any]], depth: int = 1) -> list[str]:
    """Bracket the events inside a well-formed invoke/success stack at ``depth``."""

    logs: list[str] = []
    outer = [f"Program {OTHER_PROGRAM} invoke [{level}]" for level in range(1, depth)]
    logs.extend(outer)
    for name, values in events:
        program_id, line = program_data(name, values)
        logs.append(f"Program {program_id} invoke [{depth}]")
        logs.append(line)
        logs.append(f"Program {program_id} success")
    logs.extend(f"Program {OTHER_PROGRAM} success" for _ in outer)
    return logs


def transaction(
    logs: Sequence[str],
    *,
    slot: int = 1000,
    signature: str = SIG,
    block_time: int = 1786000000,
    err: Any = None,
    tx_index: int = 3,
) -> dict[str, Any]:
    return {
        "slot": slot,
        "blockTime": block_time,
        "transactionIndex": tx_index,
        "transaction": {"signatures": [signature], "message": {"accountKeys": []}},
        "meta": {"err": err, "logMessages": list(logs)},
    }


class Sink:
    def __init__(self) -> None:
        self.events: list[TapeEvent] = []

    def __call__(self, event: TapeEvent) -> bool:
        self.events.append(event)
        return True

    def of(self, kind: EventKind) -> list[TapeEvent]:
        return [event for event in self.events if event.kind is kind]


def build(**kwargs: Any) -> tuple[Sink, TapeRecorder]:
    sink = Sink()
    registry = WatchRegistry(sink, clock=lambda: T0, **kwargs.pop("watch", {}))
    return sink, TapeRecorder(sink, registry, clock=lambda: T0, **kwargs)


def _trade_values(mint: str, wallet: str, *, is_buy: bool, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "mint": mint,
        "sol_amount": 500_000_000,
        "token_amount": 1_000_000_000_000,
        "is_buy": is_buy,
        "user": wallet,
        "timestamp": 1786000000,
        "virtual_sol_reserves": 30_000_000_000,
        "virtual_token_reserves": 1_073_000_000_000_000,
        "real_sol_reserves": 500_000_000,
        "real_token_reserves": 793_100_000_000_000,
        "fee": 5_000_000,
        "creator_fee": 1_500_000,
        "buyback_fee": 250_000,
        "cashback": 999_999,
        "ix_name": "buy" if is_buy else "sell",
        "quote_mint": WRAPPED_SOL_MINT,
    }
    values.update(overrides)
    return values


def _create_values(mint: str, creator: str, curve: str, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "name": "Sully",
        "symbol": "SULLY",
        "uri": "https://example.invalid/x.json",
        "mint": mint,
        "bonding_curve": curve,
        "user": creator,
        "creator": creator,
        "timestamp": 1786000000,
        "virtual_token_reserves": 1_073_000_000_000_000,
        "virtual_sol_reserves": 30_000_000_000,
        "real_token_reserves": 793_100_000_000_000,
        "token_total_supply": 1_000_000_000_000_000,
        "quote_mint": WRAPPED_SOL_MINT,
    }
    values.update(overrides)
    return values


# --- attribution -------------------------------------------------------------------


def test_a_foreign_program_cannot_forge_a_pump_event_into_the_tape() -> None:
    """Attribution comes from the invoke stack. A discriminator is eight bytes anyone can emit."""

    mint, wallet = _mint(), _mint()
    _program_id, line = program_data("TradeEvent", _trade_values(mint, wallet, is_buy=True))
    forged = [
        f"Program {OTHER_PROGRAM} invoke [1]",
        line,  # a genuine pump payload, emitted by somebody else
        f"Program {OTHER_PROGRAM} success",
    ]
    sink, recorder = build()

    assert recorder.record_transaction(transaction(forged)) == 0
    assert sink.of(EventKind.TRADE) == []
    assert recorder.counters.events_foreign_program == 1
    assert recorder.counters.events_decoded == 0


def test_a_cpi_nested_event_is_attributed_to_the_program_that_emitted_it() -> None:
    mint, wallet = _mint(), _mint()
    logs = pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True)), depth=2)
    attributed = attribute_program_data(logs)
    assert [entry.program_id for entry in attributed.entries] == [PUMP_PROGRAM_ID]
    assert attributed.entries[0].depth == 2
    assert attributed.unbalanced is False


def test_a_truncated_log_is_reported_because_events_are_missing_from_it() -> None:
    mint, wallet = _mint(), _mint()
    logs = [*pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))), "Log truncated"]
    _sink, recorder = build()
    recorder.record_transaction(transaction(logs))
    assert recorder.counters.transactions_truncated_logs == 1


def test_an_unbalanced_invoke_stack_is_reported_rather_than_guessed_through() -> None:
    attributed = attribute_program_data(
        [f"Program {PUMP_PROGRAM_ID} invoke [1]", "Program data: AAAA"]
    )
    assert attributed.unbalanced is True


# --- launches ----------------------------------------------------------------------


def test_a_launch_records_its_curve_reserves_and_opens_a_clock_watch() -> None:
    mint, creator, curve = _mint(), _mint(), _mint()
    logs = pump_logs(("CreateEvent", _create_values(mint, creator, curve)))
    sink, recorder = build()

    recorder.record_transaction(transaction(logs))

    launches = sink.of(EventKind.LAUNCH)
    assert len(launches) == 1
    launch = launches[0]
    assert launch.body.mint == mint
    assert launch.body.creator == creator
    assert launch.body.symbol == "SULLY"
    assert launch.body.initial_virtual_sol == 30_000_000_000
    assert launch.chain is not None
    assert launch.chain.slot == 1000

    reserves = sink.of(EventKind.RESERVE)[0].body
    assert isinstance(reserves, Reserves)
    assert reserves.pool == curve
    assert reserves.virtual_sol == 30_000_000_000
    assert reserves.real_sol == 0  # a curve holds no real SOL before its first buy

    assert mint in recorder.watches
    window = recorder.watches.window(mint)
    assert window is not None
    assert datetime.fromisoformat(window.deadline) - datetime.fromisoformat(
        window.opened_at
    ) == timedelta(hours=24)


def test_a_dev_buy_in_the_create_transaction_is_joined_to_its_launch() -> None:
    """98.7% of launches carry one; its size is only unambiguous at t=0."""

    mint, creator, curve = _mint(), _mint(), _mint()
    logs = pump_logs(
        ("CreateEvent", _create_values(mint, creator, curve)),
        ("TradeEvent", _trade_values(mint, creator, is_buy=True, token_amount=42_000_000)),
    )
    sink, recorder = build()
    recorder.record_transaction(transaction(logs))
    assert sink.of(EventKind.LAUNCH)[0].body.dev_buy_raw == 42_000_000


def test_a_launch_without_a_dev_buy_records_zero_rather_than_inventing_one() -> None:
    mint, creator, curve = _mint(), _mint(), _mint()
    logs = pump_logs(("CreateEvent", _create_values(mint, creator, curve)))
    sink, recorder = build()
    recorder.record_transaction(transaction(logs))
    assert sink.of(EventKind.LAUNCH)[0].body.dev_buy_raw == 0


# --- trades ------------------------------------------------------------------------


def test_a_buy_spends_sol_and_a_sell_receives_it() -> None:
    """A sign error here is the unit bug that costs real money on the exit path."""

    mint, curve, wallet = _mint(), _mint(), _mint()
    sink, recorder = build()
    recorder.record_transaction(
        transaction(pump_logs(("CreateEvent", _create_values(mint, _mint(), curve))))
    )
    recorder.record_transaction(
        transaction(
            pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))),
            slot=1001,
            signature="4" * 88,
        )
    )
    recorder.record_transaction(
        transaction(
            pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=False))),
            slot=1002,
            signature="3" * 88,
        )
    )

    trades = [event.body for event in sink.of(EventKind.TRADE)]
    assert all(isinstance(trade, Trade) for trade in trades)
    buy, sell = trades[0], trades[1]
    assert (buy.side, buy.sol_delta_lamports, buy.token_delta_raw) == (
        Side.BUY,
        -500_000_000,
        1_000_000_000_000,
    )
    assert (sell.side, sell.sol_delta_lamports, sell.token_delta_raw) == (
        Side.SELL,
        500_000_000,
        -1_000_000_000_000,
    )
    assert buy.pool == curve


def test_the_recorded_fee_is_protocol_plus_creator_plus_buyback_and_excludes_the_rebate() -> None:
    """Stated once so a replay can reconcile: cashback is a rebate, not a fee."""

    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    recorder.record_transaction(
        transaction(pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))))
    )
    trade = sink.of(EventKind.TRADE)[0].body
    assert isinstance(trade, Trade)
    assert trade.fee_lamports == 5_000_000 + 1_500_000 + 250_000


def test_a_trade_quoted_in_something_other_than_sol_is_dropped_not_coerced() -> None:
    """quote_amount in a non-SOL mint is not lamports; writing it as such is a unit error."""

    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    values = _trade_values(mint, wallet, is_buy=True, quote_mint=_mint())
    recorder.record_transaction(transaction(pump_logs(("TradeEvent", values))))
    assert sink.of(EventKind.TRADE) == []
    assert recorder.counters.non_sol_quote_skipped == 1


def test_a_reserve_reading_is_dropped_when_the_curve_address_is_unknown() -> None:
    """Two tokens' depth under one key is worse than a missing reading."""

    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    recorder.record_transaction(
        transaction(pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))))
    )
    assert len(sink.of(EventKind.TRADE)) == 1
    assert sink.of(EventKind.RESERVE) == []
    assert recorder.counters.unattributed_pool_skipped == 1


def test_a_route_through_another_program_is_marked_not_frontend_and_a_direct_call_stays_unknown() -> None:
    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    recorder.record_transaction(
        transaction(pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True)), depth=2))
    )
    recorder.record_transaction(
        transaction(
            pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))),
            slot=1001,
            signature="4" * 88,
        )
    )
    routed, direct = (event.body for event in sink.of(EventKind.TRADE))
    assert isinstance(routed, Trade) and isinstance(direct, Trade)
    assert routed.routed_via_frontend is False
    assert direct.routed_via_frontend is None  # ambiguous at depth 1; never guessed True


# --- failed and malformed transactions ---------------------------------------------


def test_a_failed_transaction_is_counted_and_recorded_nowhere() -> None:
    """It changed no reserves and moved no tokens; recording it inflates every intensity."""

    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    logs = pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True)))
    assert recorder.record_transaction(transaction(logs, err={"InstructionError": []})) == 0
    assert sink.events == []
    assert recorder.counters.transactions_failed == 1


def test_a_transaction_without_a_signature_cannot_be_ordered_and_is_skipped() -> None:
    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    payload = transaction(pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))))
    payload["transaction"] = {"message": {"accountKeys": []}}
    assert recorder.record_transaction(payload) == 0
    assert sink.events == []


def test_a_corrupt_payload_is_quarantined_rather_than_partially_decoded() -> None:
    sink, recorder = build()
    logs = [
        f"Program {PUMP_PROGRAM_ID} invoke [1]",
        "Program data: " + base64.b64encode(b"\x00" * 40).decode("ascii"),
        f"Program {PUMP_PROGRAM_ID} success",
    ]
    assert recorder.record_transaction(transaction(logs)) == 0
    assert sink.events == []
    assert recorder.counters.events_quarantined == 1


# --- graduation and death ----------------------------------------------------------


def test_a_complete_event_closes_the_watch_as_graduated() -> None:
    mint, creator, curve = _mint(), _mint(), _mint()
    sink, recorder = build()
    recorder.record_transaction(
        transaction(pump_logs(("CreateEvent", _create_values(mint, creator, curve))))
    )
    recorder.record_transaction(
        transaction(
            pump_logs(
                (
                    "CompleteEvent",
                    {
                        "user": creator,
                        "mint": mint,
                        "bonding_curve": curve,
                        "timestamp": 1786000264,
                        "quote_mint": WRAPPED_SOL_MINT,
                    },
                )
            ),
            slot=1500,
            signature="4" * 88,
        )
    )
    closes = [
        event.body
        for event in sink.of(EventKind.WATCH)
        if getattr(event.body, "closed_at", None) is not None
    ]
    assert len(closes) == 1
    assert closes[0].close_reason is WatchClose.GRADUATED
    assert recorder.counters.graduations == 1
    assert mint not in recorder.watches


def test_a_pumpswap_trade_is_unattributable_until_its_pool_is_known() -> None:
    pool, base_mint, wallet = _mint(), _mint(), _mint()
    buy = {
        "timestamp": 1786000000,
        "base_amount_out": 7_000_000,
        "quote_amount_in": 2_000_000_000,
        "pool_base_token_reserves": 400_000_000_000,
        "pool_quote_token_reserves": 85_000_000_000,
        "pool": pool,
        "user": wallet,
        "lp_fee": 1_000,
        "protocol_fee": 2_000,
        "coin_creator_fee": 3_000,
        "buyback_fee": 4_000,
        "ix_name": "buy",
    }
    sink, recorder = build()
    recorder.record_transaction(transaction(pump_logs(("BuyEvent", buy))))
    assert sink.of(EventKind.TRADE) == []
    assert recorder.counters.unattributed_pool_skipped == 1

    recorder.record_transaction(
        transaction(
            pump_logs(
                (
                    "CreatePoolEvent",
                    {
                        "timestamp": 1786000000,
                        "creator": _mint(),
                        "base_mint": base_mint,
                        "quote_mint": WRAPPED_SOL_MINT,
                        "pool_base_amount": 400_000_000_000,
                        "pool_quote_amount": 85_000_000_000,
                        "pool": pool,
                        "lp_mint": _mint(),
                        "coin_creator": _mint(),
                    },
                )
            ),
            slot=1600,
            signature="4" * 88,
        )
    )
    recorder.record_transaction(
        transaction(pump_logs(("BuyEvent", buy)), slot=1601, signature="3" * 88)
    )
    trades = [event.body for event in sink.of(EventKind.TRADE)]
    assert len(trades) == 1
    trade = trades[0]
    assert isinstance(trade, Trade)
    assert trade.mint == base_mint
    assert trade.pool == pool
    assert trade.sol_delta_lamports == -2_000_000_000
    assert trade.fee_lamports == 1_000 + 2_000 + 3_000 + 4_000

    # A migrated pool has no virtual reserves: that is why total depth drops 115 -> 85 SOL
    # while price stays continuous.
    amm_reserves = [
        event.body
        for event in sink.of(EventKind.RESERVE)
        if isinstance(event.body, Reserves) and event.body.pool == pool
    ]
    assert amm_reserves[-1].virtual_sol == 0
    assert amm_reserves[-1].real_sol == 85_000_000_000


def test_an_lp_withdrawal_that_empties_the_pool_is_a_terminal_death() -> None:
    """The only inferred terminal outcome, and it is inferred from a positive fact."""

    pool, base_mint = _mint(), _mint()
    sink, recorder = build()
    recorder.record_transaction(
        transaction(
            pump_logs(
                (
                    "CreatePoolEvent",
                    {
                        "timestamp": 1786000000,
                        "creator": _mint(),
                        "base_mint": base_mint,
                        "quote_mint": WRAPPED_SOL_MINT,
                        "pool_base_amount": 400_000_000_000,
                        "pool_quote_amount": 85_000_000_000,
                        "pool": pool,
                        "lp_mint": _mint(),
                        "coin_creator": _mint(),
                    },
                )
            )
        )
    )
    recorder.watches.open(base_mint, now=T0)
    recorder.record_transaction(
        transaction(
            pump_logs(
                (
                    "WithdrawEvent",
                    {
                        "timestamp": 1786000600,
                        "pool_base_token_reserves": 0,
                        "pool_quote_token_reserves": 0,
                        "pool": pool,
                        "user": _mint(),
                    },
                )
            ),
            slot=1700,
            signature="4" * 88,
        )
    )
    closed = [
        event.body
        for event in sink.of(EventKind.WATCH)
        if getattr(event.body, "closed_at", None) is not None
    ]
    assert [window.close_reason for window in closed] == [WatchClose.DIED]


# --- credits -----------------------------------------------------------------------


def test_a_credit_budget_refuses_the_request_that_would_overspend() -> None:
    """10 credits per 100-transaction page; the charge happens before the request."""

    budget = CreditBudget(limit=25)
    assert budget.charge(10) == 10
    assert budget.charge(10) == 20
    assert budget.remaining == 5
    assert budget.can_afford(10) is False
    try:
        budget.charge(10)
    except CreditBudgetExceeded as exc:
        assert "exhausted" in str(exc)
    else:  # pragma: no cover - the assertion above is the point of the test
        raise AssertionError("an exhausted budget must refuse, not overspend")
    assert budget.spent == 20


# --- callouts: the mint-scoped join the callout->flow study needs -------------------


def test_a_callout_opens_a_watch_on_the_called_out_mint() -> None:
    """The store collects trades for a few WALLETS, so a called-out mint's own flow was never
    collected and the spike came back UNRESOLVABLE rather than null. This is that join."""

    from shitcoims_tape.schema import Callout

    mint = _mint()
    sink, recorder = build()
    posted = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)

    written = recorder.record_callout(
        Callout(
            mint=mint,
            platform="x",
            author="someone",
            resolved_from="pumpfun-url",
            text_sha256="a" * 64,
            author_followers=1234,
        ),
        posted_at=posted,
        source="intelligence.social",
        observed_at=datetime(2026, 8, 13, 10, 4, 30, tzinfo=UTC),
    )

    assert written == 1
    assert recorder.counters.callouts == 1
    callout_event = sink.of(EventKind.CALLOUT)[0]
    # observed_at keeps its single contract-wide meaning: when WE saw it, not when it happened.
    assert callout_event.observed_at == "2026-08-13T10:04:30+00:00"
    assert callout_event.chain is None
    # The causal origin survives, in a typed field and in the provenance cursor.
    assert "posted_at=2026-08-13T10:00:00+00:00" in (callout_event.provenance.cursor or "")

    assert mint in recorder.watches
    window = recorder.watches.window(mint)
    assert window is not None
    assert window.opened_at == "2026-08-13T10:00:00+00:00"  # the watch starts at the POST


def test_a_callout_can_record_without_watching_when_the_caller_says_so() -> None:
    from shitcoims_tape.schema import Callout

    mint = _mint()
    sink, recorder = build()
    recorder.record_callout(
        Callout(
            mint=mint,
            platform="x",
            author="someone",
            resolved_from="cashtag",
            text_sha256="b" * 64,
        ),
        posted_at=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
        source="intelligence.social",
        watch=False,
    )
    assert sink.of(EventKind.CALLOUT)
    assert mint not in recorder.watches


def test_an_explicit_mint_set_can_be_watched_without_waiting_for_a_launch() -> None:
    sink, recorder = build()
    mints = [_mint(), _mint(), _mint()]
    assert recorder.watch(mints, now=T0) == 3
    assert all(mint in recorder.watches for mint in mints)
    assert len(sink.of(EventKind.WATCH)) == 3


def test_a_transaction_without_a_block_time_is_kept_and_counted_not_dropped() -> None:
    """~11% of the existing store's chain rows are like this; slot still orders them exactly."""

    mint, wallet = _mint(), _mint()
    sink, recorder = build()
    payload = transaction(pump_logs(("TradeEvent", _trade_values(mint, wallet, is_buy=True))))
    payload["blockTime"] = None

    assert recorder.record_transaction(payload) == 1
    assert recorder.counters.chain_without_block_time == 1
    event = sink.of(EventKind.TRADE)[0]
    assert event.chain is not None
    assert event.chain.block_time is None  # never guessed from the observer clock
    assert event.chain.slot == 1000


def test_a_recorded_trade_carries_the_signer_set_and_fee_payer() -> None:
    """Entity resolution needs custody evidence, and it has to come off the tape.

    Without this the strongest linkage available (a shared signer set, which requires the
    private key) is simply absent, and the resolver is left with fee sponsorship — which
    merges unrelated actors.
    """
    from shitcoims_tape.recorder import extract_custody

    signer, cosigner, other = "S" * 32, "C" * 32, "O" * 32
    custody = extract_custody(
        {
            "transaction": {
                "message": {
                    "accountKeys": [
                        {"pubkey": signer, "signer": True},
                        {"pubkey": cosigner, "signer": True},
                        {"pubkey": other, "signer": False},
                    ]
                }
            }
        }
    )
    assert custody.signers == (signer, cosigner)
    assert custody.fee_payer == signer
    assert other not in custody.signers


def test_custody_extraction_returns_empty_rather_than_guessing() -> None:
    """A wrong signer set is worse than none: it would be treated as strong evidence."""
    from shitcoims_tape.recorder import Custody, extract_custody

    assert extract_custody({}) == Custody()
    assert extract_custody({"transaction": {"message": {"accountKeys": []}}}) == Custody()
    assert extract_custody({"transaction": {"message": {}}}) == Custody()


def test_a_sponsor_who_did_not_sign_is_not_in_the_signer_set() -> None:
    """The exact merge that would fuse our own sentinel with a third-party KOL."""
    from shitcoims_tape.recorder import extract_custody

    sponsor, actor = "P" * 32, "A" * 32
    custody = extract_custody(
        {
            "transaction": {
                "message": {
                    "accountKeys": [
                        {"pubkey": sponsor, "signer": True},
                        {"pubkey": actor, "signer": False},
                    ]
                }
            }
        }
    )
    assert custody.fee_payer == sponsor
    assert actor not in custody.signers
