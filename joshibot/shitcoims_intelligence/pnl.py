"""Conservative, wallet-relative PnL reconstruction from chain observations.

This module is deliberately pure and advisory.  It does not import the sentinel
executor, read a keypair, or submit transactions.  A number is only exposed as
actionable when the complete FIFO cost basis and a full-balance executable exit
quote are known.  Unknown transfers, incomplete history, and ambiguous
multi-asset transactions stay unknown rather than silently becoming zero-cost
tokens.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from typing import Any

LAMPORTS_PER_SOL = Decimal(1_000_000_000)
WSOL_MINT = "So11111111111111111111111111111111111111112"


def _sol(lamports: int) -> Decimal:
    return Decimal(lamports) / LAMPORTS_PER_SOL


class LedgerEventKind(StrEnum):
    BUY = "buy"
    SELL = "sell"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    AIRDROP = "airdrop"


class CostBasisQuality(StrEnum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"
    TAINTED = "tainted"


class PnlQualityFlag(StrEnum):
    MISSING_HISTORY = "missing_history"
    UNKNOWN_TRANSFER_BASIS = "unknown_transfer_basis"
    UNKNOWN_AIRDROP_BASIS = "unknown_airdrop_basis"
    INVENTORY_UNDERFLOW = "inventory_underflow"
    BALANCE_MISMATCH = "balance_mismatch"
    MULTI_ACTION_AMBIGUITY = "multi_action_ambiguity"
    INEXACT_SOL_DELTA = "inexact_sol_delta"
    MISSING_FEE = "missing_fee"
    FEE_ATTRIBUTION_UNKNOWN = "fee_attribution_unknown"
    SAME_SLOT_ORDER_AMBIGUITY = "same_slot_order_ambiguity"
    QUOTE_AMOUNT_MISMATCH = "quote_amount_mismatch"


@dataclasses.dataclass(frozen=True, slots=True)
class WalletLedgerEvent:
    """One wallet-local token acquisition or disposition.

    ``quantity_raw`` is always positive.  For trades, ``gross_sol_lamports`` is
    the SOL exchanged before the transaction fee.  Buy fees increase basis and
    sell fees reduce proceeds.  A transfer or airdrop may carry an externally
    established basis; absent one, its basis is intentionally unknown.
    """

    wallet: str
    mint: str
    signature: str
    slot: int
    kind: LedgerEventKind
    quantity_raw: int
    decimals: int
    gross_sol_lamports: int | None = None
    fee_lamports: int = 0
    supplied_cost_basis_sol: Decimal | None = None
    supplied_basis_quality: CostBasisQuality = CostBasisQuality.UNKNOWN
    transaction_index: int | None = None
    event_index: int = 0
    flags: frozenset[PnlQualityFlag] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "flags", frozenset(self.flags))
        if not self.wallet or not self.mint or not self.signature:
            raise ValueError("wallet, mint, and signature are required")
        if self.slot < 0 or self.quantity_raw <= 0 or self.decimals < 0:
            raise ValueError("slot/decimals must be non-negative and quantity_raw must be positive")
        if self.fee_lamports < 0 or self.event_index < 0:
            raise ValueError("fee_lamports and event_index cannot be negative")
        if self.transaction_index is not None and self.transaction_index < 0:
            raise ValueError("transaction_index cannot be negative")
        if self.kind in {LedgerEventKind.BUY, LedgerEventKind.SELL}:
            if self.gross_sol_lamports is None or self.gross_sol_lamports < 0:
                raise ValueError("trade events require non-negative gross_sol_lamports")
            if self.supplied_cost_basis_sol is not None:
                raise ValueError("trades cannot have a supplied transfer cost basis")
        elif self.gross_sol_lamports is not None:
            raise ValueError("non-trade events cannot have gross_sol_lamports")
        if self.supplied_cost_basis_sol is not None:
            if not self.supplied_cost_basis_sol.is_finite() or self.supplied_cost_basis_sol < 0:
                raise ValueError("supplied_cost_basis_sol must be finite and non-negative")
            if self.kind not in {LedgerEventKind.TRANSFER_IN, LedgerEventKind.AIRDROP}:
                raise ValueError("only incoming transfers and airdrops can have supplied basis")
            if self.supplied_basis_quality is CostBasisQuality.UNKNOWN:
                raise ValueError("a supplied cost basis must declare exact or estimated quality")


@dataclasses.dataclass(frozen=True, slots=True)
class InventoryLot:
    acquisition_signature: str
    acquisition_kind: LedgerEventKind
    remaining_quantity_raw: int
    unit_cost_sol: Decimal | None
    quality: CostBasisQuality

    @property
    def cost_basis_sol(self) -> Decimal | None:
        if self.unit_cost_sol is None:
            return None
        return self.unit_cost_sol * self.remaining_quantity_raw


@dataclasses.dataclass(frozen=True, slots=True)
class RealizedDisposition:
    signature: str
    kind: LedgerEventKind
    quantity_raw: int
    net_proceeds_sol: Decimal | None
    known_quantity_raw: int
    known_cost_basis_sol: Decimal
    known_net_proceeds_sol: Decimal | None
    known_pnl_sol: Decimal | None
    pnl_sol: Decimal | None
    quality: CostBasisQuality


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutableExitQuote:
    """Full-position token-to-SOL quote used to mark liquidation value.

    Jupiter's output already reflects route/platform economics.  Only costs not
    included in that output belong in ``additional_fee_lamports`` (for example,
    the estimated base and priority transaction fees).
    """

    mint: str
    input_amount_raw: int
    expected_out_lamports: int
    minimum_out_lamports: int | None
    quote_slot: int
    additional_fee_lamports: int = 0

    def __post_init__(self) -> None:
        if not self.mint or self.input_amount_raw <= 0 or self.quote_slot < 0:
            raise ValueError("quote mint, positive input amount, and non-negative slot are required")
        if self.expected_out_lamports < 0 or self.additional_fee_lamports < 0:
            raise ValueError("quote amounts and fees cannot be negative")
        if self.minimum_out_lamports is not None:
            if self.minimum_out_lamports < 0:
                raise ValueError("minimum_out_lamports cannot be negative")
            if self.minimum_out_lamports > self.expected_out_lamports:
                raise ValueError("minimum output cannot exceed expected output")

    @property
    def expected_net_sol(self) -> Decimal:
        return _sol(self.expected_out_lamports - self.additional_fee_lamports)

    @property
    def minimum_net_sol(self) -> Decimal | None:
        if self.minimum_out_lamports is None:
            return None
        return _sol(self.minimum_out_lamports - self.additional_fee_lamports)


@dataclasses.dataclass(frozen=True, slots=True)
class PositionPnl:
    wallet: str
    mint: str
    decimals: int
    quantity_raw: int
    lots: tuple[InventoryLot, ...]
    dispositions: tuple[RealizedDisposition, ...]
    known_cost_basis_sol: Decimal
    cost_basis_sol: Decimal | None
    unknown_basis_quantity_raw: int
    known_realized_pnl_sol: Decimal
    realized_pnl_sol: Decimal | None
    expected_exit_value_sol: Decimal | None
    minimum_exit_value_sol: Decimal | None
    position_expected_pnl_sol: Decimal | None
    position_minimum_pnl_sol: Decimal | None
    lifetime_expected_pnl_sol: Decimal | None
    lifetime_minimum_pnl_sol: Decimal | None
    quality: CostBasisQuality
    flags: frozenset[PnlQualityFlag]
    quote_slot: int | None
    pnl_actionable: bool

    @property
    def ui_quantity(self) -> Decimal:
        return Decimal(self.quantity_raw) / (Decimal(10) ** self.decimals)


def _basis_for_acquisition(event: WalletLedgerEvent) -> tuple[Decimal | None, CostBasisQuality]:
    if event.kind is LedgerEventKind.BUY:
        assert event.gross_sol_lamports is not None
        cost = _sol(event.gross_sol_lamports + event.fee_lamports)
        quality = CostBasisQuality.EXACT
    elif event.supplied_cost_basis_sol is not None:
        cost = event.supplied_cost_basis_sol
        quality = event.supplied_basis_quality
    else:
        return None, CostBasisQuality.UNKNOWN
    if event.flags:
        quality = CostBasisQuality.TAINTED
    return cost, quality


def _worst_quality(qualities: Iterable[CostBasisQuality]) -> CostBasisQuality:
    ranking = {
        CostBasisQuality.EXACT: 0,
        CostBasisQuality.ESTIMATED: 1,
        CostBasisQuality.UNKNOWN: 2,
        CostBasisQuality.TAINTED: 3,
    }
    values = tuple(qualities)
    return max(values, key=ranking.__getitem__) if values else CostBasisQuality.UNKNOWN


def _event_sort_key(event: WalletLedgerEvent) -> tuple[int, int, int, str]:
    # A missing transaction index sorts last, but the result is also explicitly
    # tainted below when ordering within a slot cannot be proven.
    index = event.transaction_index if event.transaction_index is not None else 2**63 - 1
    return event.slot, index, event.event_index, event.signature


def reconstruct_position_pnl(
    *,
    wallet: str,
    mint: str,
    decimals: int,
    events: Iterable[WalletLedgerEvent],
    history_complete: bool,
    observed_balance_raw: int | None = None,
    exit_quote: ExecutableExitQuote | None = None,
) -> PositionPnl:
    """Reconstruct FIFO lots and conservative realized/unrealized PnL.

    ``history_complete`` must be an explicit caller assertion.  If false, PnL
    remains useful for inspection but is never marked actionable.
    """

    if not wallet or not mint or decimals < 0:
        raise ValueError("wallet/mint are required and decimals cannot be negative")
    if observed_balance_raw is not None and observed_balance_raw < 0:
        raise ValueError("observed_balance_raw cannot be negative")

    ordered = sorted(events, key=_event_sort_key)
    identities: set[tuple[str, int]] = set()
    flags: set[PnlQualityFlag] = set()
    if not history_complete:
        flags.add(PnlQualityFlag.MISSING_HISTORY)
    for event in ordered:
        if event.wallet != wallet or event.mint != mint or event.decimals != decimals:
            raise ValueError("every event must match wallet, mint, and decimals")
        identity = (event.signature, event.event_index)
        if identity in identities:
            raise ValueError("duplicate event identity")
        identities.add(identity)
        flags.update(event.flags)

    by_slot: dict[int, list[WalletLedgerEvent]] = defaultdict(list)
    for event in ordered:
        by_slot[event.slot].append(event)
    for same_slot in by_slot.values():
        if len(same_slot) > 1 and any(event.transaction_index is None for event in same_slot):
            flags.add(PnlQualityFlag.SAME_SLOT_ORDER_AMBIGUITY)

    lots: list[InventoryLot] = []
    dispositions: list[RealizedDisposition] = []

    for event in ordered:
        if event.kind in {
            LedgerEventKind.BUY,
            LedgerEventKind.TRANSFER_IN,
            LedgerEventKind.AIRDROP,
        }:
            total_cost, quality = _basis_for_acquisition(event)
            if event.kind is LedgerEventKind.TRANSFER_IN and total_cost is None:
                flags.add(PnlQualityFlag.UNKNOWN_TRANSFER_BASIS)
            if event.kind is LedgerEventKind.AIRDROP and total_cost is None:
                flags.add(PnlQualityFlag.UNKNOWN_AIRDROP_BASIS)
            lots.append(
                InventoryLot(
                    acquisition_signature=event.signature,
                    acquisition_kind=event.kind,
                    remaining_quantity_raw=event.quantity_raw,
                    unit_cost_sol=(total_cost / event.quantity_raw if total_cost is not None else None),
                    quality=quality,
                )
            )
            continue

        quantity_to_consume = event.quantity_raw
        consumed: list[tuple[int, Decimal | None, CostBasisQuality]] = []
        while quantity_to_consume and lots:
            lot = lots[0]
            amount = min(quantity_to_consume, lot.remaining_quantity_raw)
            consumed.append((amount, lot.unit_cost_sol, lot.quality))
            quantity_to_consume -= amount
            remaining = lot.remaining_quantity_raw - amount
            if remaining:
                lots[0] = dataclasses.replace(lot, remaining_quantity_raw=remaining)
            else:
                lots.pop(0)
        if quantity_to_consume:
            flags.add(PnlQualityFlag.INVENTORY_UNDERFLOW)
            consumed.append((quantity_to_consume, None, CostBasisQuality.TAINTED))

        if event.kind is LedgerEventKind.TRANSFER_OUT:
            continue

        assert event.kind is LedgerEventKind.SELL
        assert event.gross_sol_lamports is not None
        net_proceeds = _sol(event.gross_sol_lamports - event.fee_lamports)
        known_quantity = sum(amount for amount, unit_cost, _ in consumed if unit_cost is not None)
        known_cost = sum(
            (unit_cost * amount for amount, unit_cost, _ in consumed if unit_cost is not None),
            Decimal(0),
        )
        known_net_proceeds = (
            net_proceeds * Decimal(known_quantity) / Decimal(event.quantity_raw)
            if known_quantity
            else None
        )
        known_pnl = known_net_proceeds - known_cost if known_net_proceeds is not None else None
        consumed_quality = _worst_quality(quality for _, _, quality in consumed)
        all_known = known_quantity == event.quantity_raw
        disposition_quality = consumed_quality if all_known else CostBasisQuality.UNKNOWN
        if event.flags:
            disposition_quality = CostBasisQuality.TAINTED
        pnl = known_pnl if all_known and disposition_quality is not CostBasisQuality.TAINTED else None
        dispositions.append(
            RealizedDisposition(
                signature=event.signature,
                kind=event.kind,
                quantity_raw=event.quantity_raw,
                net_proceeds_sol=net_proceeds,
                known_quantity_raw=known_quantity,
                known_cost_basis_sol=known_cost,
                known_net_proceeds_sol=known_net_proceeds,
                known_pnl_sol=known_pnl,
                pnl_sol=pnl,
                quality=disposition_quality,
            )
        )

    ledger_quantity = sum(lot.remaining_quantity_raw for lot in lots)
    if observed_balance_raw is not None and observed_balance_raw != ledger_quantity:
        flags.add(PnlQualityFlag.BALANCE_MISMATCH)
        if observed_balance_raw > ledger_quantity:
            lots.append(
                InventoryLot(
                    acquisition_signature="observed-balance-gap",
                    acquisition_kind=LedgerEventKind.TRANSFER_IN,
                    remaining_quantity_raw=observed_balance_raw - ledger_quantity,
                    unit_cost_sol=None,
                    quality=CostBasisQuality.TAINTED,
                )
            )
        else:
            quantity_to_remove = ledger_quantity - observed_balance_raw
            while quantity_to_remove and lots:
                lot = lots[-1]
                removed = min(quantity_to_remove, lot.remaining_quantity_raw)
                quantity_to_remove -= removed
                remaining = lot.remaining_quantity_raw - removed
                if remaining:
                    lots[-1] = dataclasses.replace(lot, remaining_quantity_raw=remaining)
                else:
                    lots.pop()

    quantity = sum(lot.remaining_quantity_raw for lot in lots)
    known_cost = sum((lot.cost_basis_sol or Decimal(0) for lot in lots), Decimal(0))
    unknown_quantity = sum(lot.remaining_quantity_raw for lot in lots if lot.unit_cost_sol is None)
    all_basis_known = unknown_quantity == 0
    cost_basis = known_cost if all_basis_known else None

    known_realized = sum(
        (disposition.known_pnl_sol or Decimal(0) for disposition in dispositions), Decimal(0)
    )
    realized_known = all(disposition.pnl_sol is not None for disposition in dispositions)
    realized = (
        sum((disposition.pnl_sol or Decimal(0) for disposition in dispositions), Decimal(0))
        if realized_known
        else None
    )

    expected_exit: Decimal | None = None
    minimum_exit: Decimal | None = None
    quote_slot: int | None = None
    if exit_quote is not None:
        quote_slot = exit_quote.quote_slot
        if exit_quote.mint != mint or exit_quote.input_amount_raw != quantity:
            flags.add(PnlQualityFlag.QUOTE_AMOUNT_MISMATCH)
        elif quantity > 0:
            expected_exit = exit_quote.expected_net_sol
            minimum_exit = exit_quote.minimum_net_sol

    position_expected = (
        expected_exit - cost_basis if expected_exit is not None and cost_basis is not None else None
    )
    position_minimum = (
        minimum_exit - cost_basis if minimum_exit is not None and cost_basis is not None else None
    )
    lifetime_expected = (
        realized + position_expected
        if realized is not None and position_expected is not None
        else None
    )
    lifetime_minimum = (
        realized + position_minimum
        if realized is not None and position_minimum is not None
        else None
    )

    qualities = [lot.quality for lot in lots]
    qualities.extend(disposition.quality for disposition in dispositions)
    quality = _worst_quality(qualities)
    if flags & {
        PnlQualityFlag.MISSING_HISTORY,
        PnlQualityFlag.INVENTORY_UNDERFLOW,
        PnlQualityFlag.BALANCE_MISMATCH,
        PnlQualityFlag.MULTI_ACTION_AMBIGUITY,
        PnlQualityFlag.INEXACT_SOL_DELTA,
        PnlQualityFlag.MISSING_FEE,
        PnlQualityFlag.FEE_ATTRIBUTION_UNKNOWN,
        PnlQualityFlag.SAME_SLOT_ORDER_AMBIGUITY,
    }:
        quality = CostBasisQuality.TAINTED

    actionable = (
        history_complete
        and quantity > 0
        and position_expected is not None
        and quality is CostBasisQuality.EXACT
        and not flags
    )
    return PositionPnl(
        wallet=wallet,
        mint=mint,
        decimals=decimals,
        quantity_raw=quantity,
        lots=tuple(lots),
        dispositions=tuple(dispositions),
        known_cost_basis_sol=known_cost,
        cost_basis_sol=cost_basis,
        unknown_basis_quantity_raw=unknown_quantity,
        known_realized_pnl_sol=known_realized,
        realized_pnl_sol=realized,
        expected_exit_value_sol=expected_exit,
        minimum_exit_value_sol=minimum_exit,
        position_expected_pnl_sol=position_expected,
        position_minimum_pnl_sol=position_minimum,
        lifetime_expected_pnl_sol=lifetime_expected,
        lifetime_minimum_pnl_sol=lifetime_minimum,
        quality=quality,
        flags=frozenset(flags),
        quote_slot=quote_slot,
        pnl_actionable=actionable,
    )


def infer_event_from_wallet_transaction(
    transaction: Any,
    *,
    mint: str,
    wsol_mint: str = WSOL_MINT,
    wallet_paid_fee: bool | None = None,
) -> WalletLedgerEvent | None:
    """Fail-closed inference from a normalized Helius ``WalletTransaction``.

    Only a single-token, exact native-SOL exchange is classified as a trade.
    Multi-token routes cannot safely allocate wallet SOL economics to one mint,
    so they become unknown-basis transfers with an ambiguity flag.  A production
    swap decoder can instead emit an explicit ``WalletLedgerEvent`` once it has
    established the route economics.
    """

    if not getattr(transaction, "succeeded", False):
        return None
    target_deltas = [delta for delta in transaction.token_deltas if delta.mint == mint]
    raw_delta = sum(delta.raw_delta for delta in target_deltas)
    if not raw_delta:
        return None
    decimals_set = {delta.decimals for delta in target_deltas}
    if len(decimals_set) != 1:
        raise ValueError("target token deltas disagree on decimals")

    flags: set[PnlQualityFlag] = set()
    other_deltas = [
        delta for delta in transaction.token_deltas if delta.mint not in {mint, wsol_mint}
    ]
    if any(delta.raw_delta for delta in other_deltas):
        flags.add(PnlQualityFlag.MULTI_ACTION_AMBIGUITY)
    sol_delta = transaction.sol_delta_lamports
    if not transaction.sol_delta_exact or sol_delta is None:
        flags.add(PnlQualityFlag.INEXACT_SOL_DELTA)
    transaction_fee = transaction.fee_lamports
    if transaction_fee is None:
        flags.add(PnlQualityFlag.MISSING_FEE)
        transaction_fee = 0
    if wallet_paid_fee is None:
        wallet_paid_fee = getattr(transaction, "wallet_paid_fee", None)
    if wallet_paid_fee is None:
        flags.add(PnlQualityFlag.FEE_ATTRIBUTION_UNKNOWN)
    fee = transaction_fee if wallet_paid_fee is True else 0

    kind = LedgerEventKind.TRANSFER_IN if raw_delta > 0 else LedgerEventKind.TRANSFER_OUT
    gross: int | None = None
    can_classify_trade = not flags and sol_delta is not None
    if can_classify_trade and raw_delta > 0 and sol_delta < -fee:
        kind = LedgerEventKind.BUY
        # wallet delta = -trade spend - network fee
        gross = -sol_delta - fee
    elif can_classify_trade and raw_delta < 0 and sol_delta + fee > 0:
        kind = LedgerEventKind.SELL
        # wallet delta = trade proceeds - network fee
        gross = sol_delta + fee

    return WalletLedgerEvent(
        wallet=transaction.wallet,
        mint=mint,
        signature=transaction.signature,
        slot=transaction.slot,
        transaction_index=transaction.transaction_index,
        kind=kind,
        quantity_raw=abs(raw_delta),
        decimals=decimals_set.pop(),
        gross_sol_lamports=gross,
        fee_lamports=fee,
        flags=frozenset(flags),
    )
