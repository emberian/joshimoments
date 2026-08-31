import dataclasses
from decimal import Decimal

from shitcoims_intelligence.helius import TokenBalanceDelta, WalletTransaction
from shitcoims_intelligence.pnl import (
    CostBasisQuality,
    ExecutableExitQuote,
    LedgerEventKind,
    PnlQualityFlag,
    WalletLedgerEvent,
    infer_event_from_wallet_transaction,
    reconstruct_position_pnl,
)

WALLET = "wallet"
MINT = "mint"


def event(
    signature: str,
    slot: int,
    kind: LedgerEventKind,
    quantity: int,
    *,
    gross: int | None = None,
    fee: int = 0,
    basis: Decimal | None = None,
    basis_quality: CostBasisQuality = CostBasisQuality.UNKNOWN,
) -> WalletLedgerEvent:
    return WalletLedgerEvent(
        wallet=WALLET,
        mint=MINT,
        signature=signature,
        slot=slot,
        transaction_index=0,
        kind=kind,
        quantity_raw=quantity,
        decimals=0,
        gross_sol_lamports=gross,
        fee_lamports=fee,
        supplied_cost_basis_sol=basis,
        supplied_basis_quality=basis_quality,
    )


def test_fifo_realized_and_executable_unrealized_pnl_include_fees() -> None:
    events = [
        event("buy-1", 1, LedgerEventKind.BUY, 100, gross=1_000_000_000, fee=5_000),
        event("buy-2", 2, LedgerEventKind.BUY, 100, gross=2_000_000_000, fee=5_000),
        event("sell", 3, LedgerEventKind.SELL, 150, gross=3_000_000_000, fee=10_000),
    ]
    quote = ExecutableExitQuote(MINT, 50, 1_500_000_000, 1_350_000_000, 4, 10_000)

    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=events,
        history_complete=True,
        observed_balance_raw=50,
        exit_quote=quote,
    )

    # FIFO sold the 1 SOL lot plus half of the 2 SOL lot. Buy and sell fees
    # remain in the respective basis/proceeds calculations.
    expected_sold_cost = Decimal("1.000005") + Decimal("1.0000025")
    assert result.realized_pnl_sol == Decimal("2.99999") - expected_sold_cost
    assert result.cost_basis_sol == Decimal("1.0000025")
    assert result.position_expected_pnl_sol == Decimal("1.49999") - Decimal("1.0000025")
    assert result.position_minimum_pnl_sol == Decimal("1.34999") - Decimal("1.0000025")
    assert result.pnl_actionable is True
    assert result.quality is CostBasisQuality.EXACT


def test_unknown_transfer_basis_is_never_assumed_zero() -> None:
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[event("gift", 1, LedgerEventKind.TRANSFER_IN, 100)],
        history_complete=True,
        exit_quote=ExecutableExitQuote(MINT, 100, 1_000_000_000, 900_000_000, 2),
    )

    assert result.known_cost_basis_sol == 0
    assert result.cost_basis_sol is None
    assert result.position_expected_pnl_sol is None
    assert result.pnl_actionable is False
    assert PnlQualityFlag.UNKNOWN_TRANSFER_BASIS in result.flags


def test_airdrop_can_only_be_zero_basis_when_caller_explicitly_supplies_it() -> None:
    explicit = event(
        "drop",
        1,
        LedgerEventKind.AIRDROP,
        100,
        basis=Decimal(0),
        basis_quality=CostBasisQuality.EXACT,
    )
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[explicit],
        history_complete=True,
        exit_quote=ExecutableExitQuote(MINT, 100, 500_000_000, 400_000_000, 2),
    )

    assert result.cost_basis_sol == 0
    assert result.position_expected_pnl_sol == Decimal("0.5")
    assert result.pnl_actionable is True


def test_missing_history_taints_an_otherwise_exact_position() -> None:
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[event("buy", 1, LedgerEventKind.BUY, 100, gross=1_000_000_000)],
        history_complete=False,
        exit_quote=ExecutableExitQuote(MINT, 100, 2_000_000_000, None, 2),
    )

    assert result.position_expected_pnl_sol == 1
    assert result.quality is CostBasisQuality.TAINTED
    assert result.pnl_actionable is False
    assert PnlQualityFlag.MISSING_HISTORY in result.flags


def test_inventory_underflow_does_not_invent_realized_cost_basis() -> None:
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[event("sell", 2, LedgerEventKind.SELL, 10, gross=100_000_000)],
        history_complete=True,
    )

    disposition = result.dispositions[0]
    assert disposition.net_proceeds_sol == Decimal("0.1")
    assert disposition.pnl_sol is None
    assert result.realized_pnl_sol is None
    assert PnlQualityFlag.INVENTORY_UNDERFLOW in result.flags


def test_observed_chain_balance_gap_creates_unknown_lot() -> None:
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[event("buy", 1, LedgerEventKind.BUY, 40, gross=400_000_000)],
        history_complete=True,
        observed_balance_raw=100,
        exit_quote=ExecutableExitQuote(MINT, 100, 1_000_000_000, None, 2),
    )

    assert result.quantity_raw == 100
    assert result.unknown_basis_quantity_raw == 60
    assert result.position_expected_pnl_sol is None
    assert PnlQualityFlag.BALANCE_MISMATCH in result.flags


def wallet_transaction(
    *,
    token_deltas: tuple[TokenBalanceDelta, ...],
    sol_delta: int,
    fee: int | None = 5_000,
    exact: bool = True,
) -> WalletTransaction:
    return WalletTransaction(
        wallet=WALLET,
        signature="signature",
        slot=10,
        transaction_index=2,
        block_time=1,
        succeeded=True,
        fee_lamports=fee,
        fee_payer=WALLET,
        wallet_paid_fee=True,
        sol_delta_lamports=sol_delta,
        sol_delta_exact=exact,
        token_deltas=token_deltas,
        commitment="finalized",
    )


def test_exact_single_asset_helius_delta_infers_buy_without_double_counting_fee() -> None:
    transaction = wallet_transaction(
        token_deltas=(TokenBalanceDelta(MINT, 100, 0),),
        sol_delta=-1_000_005_000,
    )
    inferred = infer_event_from_wallet_transaction(transaction, mint=MINT, wallet_paid_fee=True)

    assert inferred is not None
    assert inferred.kind is LedgerEventKind.BUY
    assert inferred.gross_sol_lamports == 1_000_000_000
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[inferred],
        history_complete=True,
    )
    assert result.cost_basis_sol == Decimal("1.000005")


def test_multi_asset_transaction_fails_closed_as_unknown_transfer() -> None:
    transaction = wallet_transaction(
        token_deltas=(
            TokenBalanceDelta(MINT, 100, 0),
            TokenBalanceDelta("another-mint", -50, 0),
        ),
        sol_delta=-1_000_005_000,
    )
    inferred = infer_event_from_wallet_transaction(transaction, mint=MINT)

    assert inferred is not None
    assert inferred.kind is LedgerEventKind.TRANSFER_IN
    assert inferred.gross_sol_lamports is None
    assert PnlQualityFlag.MULTI_ACTION_AMBIGUITY in inferred.flags


def test_unknown_fee_payer_prevents_trade_inference() -> None:
    transaction = wallet_transaction(
        token_deltas=(TokenBalanceDelta(MINT, -100, 0),),
        sol_delta=999_995_000,
    )
    transaction = dataclasses.replace(transaction, fee_payer=None, wallet_paid_fee=None)

    inferred = infer_event_from_wallet_transaction(transaction, mint=MINT)

    assert inferred is not None
    assert inferred.kind is LedgerEventKind.TRANSFER_OUT
    assert PnlQualityFlag.FEE_ATTRIBUTION_UNKNOWN in inferred.flags


def test_partial_quote_is_not_used_to_mark_the_full_position() -> None:
    result = reconstruct_position_pnl(
        wallet=WALLET,
        mint=MINT,
        decimals=0,
        events=[event("buy", 1, LedgerEventKind.BUY, 100, gross=1_000_000_000)],
        history_complete=True,
        exit_quote=ExecutableExitQuote(MINT, 99, 2_000_000_000, None, 2),
    )

    assert result.expected_exit_value_sol is None
    assert result.position_expected_pnl_sol is None
    assert result.pnl_actionable is False
    assert PnlQualityFlag.QUOTE_AMOUNT_MISMATCH in result.flags
