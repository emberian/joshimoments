"""Meteora DAMM v2 (``cp_amm``): the measured full-range, cadence-None arm.

Decodes ``EvtSwap2`` events from retained transaction bodies and folds them into the
unattended-LP yield the attention frontier needs. Layout provenance: the ``cp_amm`` 0.2.3
IDL retained at ``analysis/fixtures/lpdesk/cp_amm_idl_4638e72.json`` (MeteoraAg/damm-v2-sdk
@ ``4638e72``), event discriminator recomputed as ``sha256("event:EvtSwap2")[..8]`` and
checked against the IDL's declaration; the mechanism source (dynamic fee with the DLMM's
volatility-accumulator family) is retained beside it.

Field semantics were bound to retained mainnet bytes before being trusted: every decoded
event's ``current_timestamp`` equals its transaction's block time; ``included - excluded``
input equals the four fee fields' sum when fees ride the input, and is zero when they ride
the output; the in/out ratio reproduces the price implied by ``next_sqrt_price``; and the
event's reserves track the vault balances less uncollected fees.

A position in a cp-amm pool is a share of the whole curve: the yield computed here is what
one deployed dollar earns with NO recentering, NO rent, and NO attention — no kappa needed,
because full-range pro-rata capture is the pool's own arithmetic, not a model.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

__all__ = ["DammSwap", "DammYieldPanel", "damm_yield", "decode_damm_swaps"]

CP_AMM_PROGRAM_ID = "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG"

_EVENT_IX_TAG = bytes(reversed(hashlib.sha256(b"anchor:event").digest()[:8]))
_EVT_SWAP2 = hashlib.sha256(b"event:EvtSwap2").digest()[:8]

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58decode(text: str) -> bytes:
    value = 0
    for char in text:
        value = value * 58 + _B58_INDEX[char]
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    pad = len(text) - len(text.lstrip(_B58_ALPHABET[0]))
    return b"\x00" * pad + raw


def _b58encode(raw: bytes) -> str:
    value = int.from_bytes(raw, "big")
    out = []
    while value:
        value, rem = divmod(value, 58)
        out.append(_B58_ALPHABET[rem])
    for byte in raw:
        if byte != 0:
            break
        out.append(_B58_ALPHABET[0])
    return "".join(reversed(out))


@dataclass(frozen=True)
class DammSwap:
    """One cp-amm swap as its own event states it."""

    block_time: int
    slot: int
    trade_direction: int  # 0: token A in, B out; 1: B in, A out (bound to bytes, above)
    included_fee_input: int
    output_amount: int
    sqrt_price_q64: int  # post-swap
    lp_fee_atoms: int  # claiming + compounding: the LP's take
    protocol_fee_atoms: int
    referral_fee_atoms: int
    fee_on_input: bool  # True when included-excluded input equals the fee sum
    reserve_a_atoms: int
    reserve_b_atoms: int


def decode_damm_swaps(transactions: list[dict], pool: str) -> list[DammSwap]:
    """Every ``EvtSwap2`` of one pool across retained bodies, bytes-checked.

    An event whose ``current_timestamp`` is not within 120 s of its transaction's block
    time is refused rather than trusted — that binding is what proved the offsets.
    """
    swaps: list[DammSwap] = []
    for transaction in transactions:
        meta = transaction.get("meta") or {}
        if meta.get("err") is not None:
            continue
        block_time = transaction.get("blockTime") or 0
        for group in meta.get("innerInstructions") or []:
            for inner in group.get("instructions") or []:
                data = inner.get("data")
                if not isinstance(data, str):
                    continue
                try:
                    raw = _b58decode(data)
                except KeyError:
                    continue
                if len(raw) < 196 or raw[:8] != _EVENT_IX_TAG or raw[8:16] != _EVT_SWAP2:
                    continue
                body = raw[16:]
                if len(body) != 180 or _b58encode(body[:32]) != pool:
                    continue

                def u64(offset: int, body: bytes = body) -> int:
                    return int.from_bytes(body[offset : offset + 8], "little")

                timestamp = u64(156)
                if abs(timestamp - block_time) > 120:
                    continue  # refused: the binding that proved this layout fails here
                included = u64(52)
                excluded = u64(60)
                claiming = u64(100)
                protocol = u64(108)
                compounding = u64(116)
                referral = u64(124)
                fee_sum = claiming + protocol + compounding + referral
                swaps.append(
                    DammSwap(
                        block_time=block_time,
                        slot=transaction["slot"],
                        trade_direction=body[32],
                        included_fee_input=included,
                        output_amount=u64(76),
                        sqrt_price_q64=int.from_bytes(body[84:100], "little"),
                        lp_fee_atoms=claiming + compounding,
                        protocol_fee_atoms=protocol,
                        referral_fee_atoms=referral,
                        fee_on_input=included - excluded == fee_sum and fee_sum > 0,
                        reserve_a_atoms=u64(164),
                        reserve_b_atoms=u64(172),
                    )
                )
    swaps.sort(key=lambda s: (s.block_time, s.slot))
    return swaps


@dataclass
class DammYieldPanel:
    """The unattended arm's measured numbers, windows attached."""

    pool: str
    window_start_unix: int
    window_end_unix: int
    swap_count: int
    lp_fee_flow_quote_per_day: Decimal
    volume_quote_per_day: Decimal
    tvl_quote_from_events: Decimal  # mean of per-swap reserves, valued at each swap's price
    tvl_quote_from_vaults: Decimal | None  # one account read; includes uncollected fees
    yield_per_day: Decimal  # lp fee flow / event TVL: per deployed dollar, no kappa
    mean_fee_rate_bps: Decimal  # lp+protocol+referral fee over trade size
    fee_rate_bps_by_minute: list[dict]  # how the dynamic fee actually moved
    sigma2_per_day: float  # realized, from the sqrt-price path of this window

    def as_dict(self) -> dict:
        out = {}
        for key, value in self.__dict__.items():
            out[key] = str(value) if isinstance(value, Decimal) else value
        return out


def damm_yield(
    swaps: list[DammSwap],
    *,
    pool: str,
    a_decimals: int,
    b_decimals: int,
    quote_is_b: bool,
    vault_a_atoms: int | None = None,
    vault_b_atoms: int | None = None,
) -> DammYieldPanel:
    """Folds one pool's swaps into the measured yield panel. Quote units throughout."""
    if len(swaps) < 2:
        raise ValueError("a yield needs at least two swaps to have a window")
    span_s = max(swaps[-1].block_time - swaps[0].block_time, 1)
    per_day = Decimal(86_400) / Decimal(span_s)

    def price(swap: DammSwap) -> Decimal:
        # B atoms per A atom from sqrt_price, scaled to display quote per base.
        ratio = (Decimal(swap.sqrt_price_q64) / Decimal(2**64)) ** 2
        scale = Decimal(10) ** (a_decimals - b_decimals)
        return ratio * scale if quote_is_b else 1 / (ratio * scale)

    def atoms_to_quote(atoms: int, token_is_a: bool, swap: DammSwap) -> Decimal:
        decimals = a_decimals if token_is_a else b_decimals
        display = Decimal(atoms) / Decimal(10) ** decimals
        base_side = token_is_a == quote_is_b  # the non-quote side
        return display * price(swap) if base_side else display

    lp_fees = Decimal(0)
    volume = Decimal(0)
    tvl_sum = Decimal(0)
    fee_rates: list[tuple[int, Decimal]] = []
    for swap in swaps:
        input_is_a = swap.trade_direction == 0
        fee_token_is_a = input_is_a if swap.fee_on_input else not input_is_a
        lp_fees += atoms_to_quote(swap.lp_fee_atoms, fee_token_is_a, swap)
        trade_quote = atoms_to_quote(swap.included_fee_input, input_is_a, swap)
        volume += trade_quote
        tvl_sum += atoms_to_quote(swap.reserve_a_atoms, True, swap) + atoms_to_quote(
            swap.reserve_b_atoms, False, swap
        )
        total_fee = swap.lp_fee_atoms + swap.protocol_fee_atoms + swap.referral_fee_atoms
        if trade_quote > 0:
            rate = (
                atoms_to_quote(total_fee, fee_token_is_a, swap) / trade_quote * 10_000
            )
            fee_rates.append((swap.block_time, rate))
    tvl_events = tvl_sum / len(swaps)
    tvl_vaults = None
    if vault_a_atoms is not None and vault_b_atoms is not None:
        last = swaps[-1]
        tvl_vaults = atoms_to_quote(vault_a_atoms, True, last) + atoms_to_quote(
            vault_b_atoms, False, last
        )
    by_minute: dict[int, list[Decimal]] = {}
    for at, rate in fee_rates:
        by_minute.setdefault(at // 60, []).append(rate)
    rate_rows = [
        {
            "minute_unix": minute * 60,
            "mean_fee_bps": str(sum(rates) / len(rates)),
            "swaps": len(rates),
        }
        for minute, rates in sorted(by_minute.items())
    ]
    # realized variance from the sqrt-price path
    logs = [math.log(float(price(swap))) for swap in swaps]
    sigma2 = sum((b - a) ** 2 for a, b in pairwise(logs)) * 86_400 / span_s
    mean_rate = (
        sum((r for _, r in fee_rates), Decimal(0)) / len(fee_rates)
        if fee_rates
        else Decimal(0)
    )
    return DammYieldPanel(
        pool=pool,
        window_start_unix=swaps[0].block_time,
        window_end_unix=swaps[-1].block_time,
        swap_count=len(swaps),
        lp_fee_flow_quote_per_day=lp_fees * per_day,
        volume_quote_per_day=volume * per_day,
        tvl_quote_from_events=tvl_events,
        tvl_quote_from_vaults=tvl_vaults,
        yield_per_day=(lp_fees * per_day) / tvl_events if tvl_events > 0 else Decimal(0),
        mean_fee_rate_bps=mean_rate,
        fee_rate_bps_by_minute=rate_rows,
        sigma2_per_day=sigma2,
    )
