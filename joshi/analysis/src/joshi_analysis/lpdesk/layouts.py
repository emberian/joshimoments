"""Exact account decoders for the Meteora DLMM (``lb_clmm``) program, in Python.

A port of the byte layouts in ``crates/joshi-sources/src/meteora.rs`` (LbPair, PositionV2)
plus the two layouts that crate does not carry (Oracle, BinArray). The same properties hold:
identity is proved from bytes, not asserted — owner, recomputed Anchor discriminator, and
exact length are all checked before a single field is read.

**Layout provenance.** LbPair and PositionV2 offsets are transcribed from ``meteora.rs``,
whose provenance chain is documented there (published ``lb_clmm`` 0.12.0 IDL, discriminators
recomputed, sizes reconciled against retained mainnet accounts, decoded values cross-checked
against independent observations). BinArray field order comes from the same IDL, retained at
``analysis/fixtures/lpdesk/dlmm_idl_fb02e51.json`` (MeteoraAg/dlmm-sdk @ ``fb02e51``, the
revision ``fixtures/protocol/dlmm.json`` already names as this repo's official source).
The Oracle observation record (16-byte cumulative active bin id, two i64 timestamps; ring
buffer after an 8+24 byte head) is NOT declared by the IDL; it is transcribed from the same
revision's ``ts-client/src/dlmm/helpers/oracle/wrapper.ts``, retained beside the IDL, and
every decode here re-checks the arithmetic the layout implies (whole 32-byte records, ring
indices inside the declared length) before trusting a single observation.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from decimal import Decimal, localcontext
from itertools import pairwise

__all__ = [
    "BASIS_POINT_MAX",
    "LB_PAIR_ACCOUNT_LEN",
    "METEORA_DLMM_PROGRAM_ID",
    "LayoutError",
    "LbPair",
    "OracleObservation",
    "PositionV2",
    "anchor_account_discriminator",
    "bin_price_ratio",
    "decode_bin_array_liquidity",
    "decode_lb_pair",
    "decode_oracle",
    "decode_position_v2",
    "position_composition",
]

METEORA_DLMM_PROGRAM_ID = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
LB_PAIR_ACCOUNT_LEN = 904
POSITION_V2_FIXED_LEN = 8120
POSITION_V2_FIXED_BIN_SLOTS = 70
POSITION_V2_BIN_RECORD_LEN = 112
BASIS_POINT_MAX = 10_000
ORACLE_HEAD_LEN = 8 + 24
ORACLE_OBSERVATION_LEN = 32
BIN_ARRAY_BINS = 70
BIN_ARRAY_HEAD_LEN = 8 + 8 + 1 + 7 + 32  # discriminator, index i64, version, padding, lb_pair
# Bin struct size per the retained IDL field list: 8+8+16+16 + 8*4 + 16*2 + 8*3 + 4+1+3.
# The pre-limit-order layout also summed to 144, with amount_x/amount_y/price/
# liquidity_supply at the same leading offsets, so this decode reads either version.
BIN_RECORD_LEN = 144

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_PRICE_PRECISION = 50


class LayoutError(Exception):
    """Bytes this module refuses to misread."""


def anchor_account_discriminator(name: str) -> bytes:
    """``sha256("account:<Name>")[..8]`` — recomputed, never transcribed."""
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


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


def _pubkey(data: bytes, offset: int) -> str:
    return _b58encode(data[offset : offset + 32])


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _i32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def _u64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def _i64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little", signed=True)


def _u128(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 16], "little")


def _i128(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 16], "little", signed=True)


def account_bytes(account_info_value: dict) -> tuple[bytes, str]:
    """Extracts ``(data, owner)`` from a ``getAccountInfo``-shaped value dict."""
    data_field = account_info_value["data"]
    if not (isinstance(data_field, list) and data_field[1] == "base64"):
        raise LayoutError("account data is not base64; this reader takes no other encoding")
    return base64.b64decode(data_field[0]), account_info_value["owner"]


def _require(data: bytes, owner: str, name: str, address: str) -> None:
    if owner != METEORA_DLMM_PROGRAM_ID:
        raise LayoutError(f"account {address} is owned by {owner}, not the DLMM program")
    if len(data) < 8 or data[:8] != anchor_account_discriminator(name):
        raise LayoutError(f"account {address} does not carry the recomputed {name} discriminator")


@dataclass(frozen=True)
class LbPair:
    """The LbPair fields this desk reads, at the offsets ``meteora.rs`` established."""

    address: str
    base_factor: int
    base_fee_power_factor: int
    variable_fee_control: int
    max_volatility_accumulator: int
    protocol_share: int
    volatility_accumulator: int
    volatility_last_update_unix_s: int
    active_id: int
    bin_step: int
    status: int
    token_x_mint: str
    token_y_mint: str
    reserve_x: str
    reserve_y: str
    protocol_fee_x_atoms: int
    protocol_fee_y_atoms: int
    oracle: str

    def base_fee_rate_per_1e9(self) -> int:
        return self.base_factor * self.bin_step * 10 * 10**self.base_fee_power_factor

    def max_variable_fee_rate_per_1e9(self) -> int:
        if self.variable_fee_control == 0:
            return 0
        vfa_bin = self.max_volatility_accumulator * self.bin_step
        scaled = self.variable_fee_control * vfa_bin * vfa_bin
        return -(-scaled // 100_000_000_000)


def decode_lb_pair(account_info_value: dict, address: str) -> LbPair:
    data, owner = account_bytes(account_info_value)
    _require(data, owner, "LbPair", address)
    if len(data) != LB_PAIR_ACCOUNT_LEN:
        raise LayoutError(f"LbPair {address} is {len(data)} bytes, not {LB_PAIR_ACCOUNT_LEN}")
    return LbPair(
        address=address,
        base_factor=_u16(data, 8),
        base_fee_power_factor=data[34],
        variable_fee_control=_u32(data, 16),
        max_volatility_accumulator=_u32(data, 20),
        protocol_share=_u16(data, 32),
        volatility_accumulator=_u32(data, 40),
        volatility_last_update_unix_s=_i64(data, 56),
        active_id=_i32(data, 76),
        bin_step=_u16(data, 80),
        status=data[82],
        token_x_mint=_pubkey(data, 88),
        token_y_mint=_pubkey(data, 120),
        reserve_x=_pubkey(data, 152),
        reserve_y=_pubkey(data, 184),
        protocol_fee_x_atoms=_u64(data, 216),
        protocol_fee_y_atoms=_u64(data, 224),
        oracle=_pubkey(data, 552),
    )


@dataclass(frozen=True)
class PositionV2:
    """The PositionV2 fields this desk reads. Extended positions keep the ``meteora.rs``
    reading: fixed struct first, whole per-bin records appended, one per bin past seventy."""

    address: str
    lb_pair: str
    owner: str
    lower_bin_id: int
    upper_bin_id: int
    last_updated_at: int
    total_claimed_fee_x_atoms: int
    total_claimed_fee_y_atoms: int
    liquidity_shares: tuple[int, ...]
    pending_fee_x_atoms_fixed_slots: int
    pending_fee_y_atoms_fixed_slots: int
    extension_records: int

    def bin_count(self) -> int:
        return self.upper_bin_id - self.lower_bin_id + 1


def decode_position_v2(account_info_value: dict, address: str) -> PositionV2:
    data, owner = account_bytes(account_info_value)
    _require(data, owner, "PositionV2", address)
    if len(data) < POSITION_V2_FIXED_LEN:
        raise LayoutError(f"PositionV2 {address} is {len(data)} bytes, under the fixed layout")
    extension_len = len(data) - POSITION_V2_FIXED_LEN
    if extension_len % POSITION_V2_BIN_RECORD_LEN:
        raise LayoutError(f"PositionV2 {address} extension is not whole per-bin records")
    extension_records = extension_len // POSITION_V2_BIN_RECORD_LEN
    lower_bin_id = _i32(data, 7912)
    upper_bin_id = _i32(data, 7916)
    bin_count = upper_bin_id - lower_bin_id + 1
    slots = POSITION_V2_FIXED_BIN_SLOTS + extension_records
    reconciles = (1 <= bin_count <= slots) if extension_records == 0 else (bin_count == slots)
    if not reconciles:
        raise LayoutError(
            f"PositionV2 {address} spans {bin_count} bins but carries {slots} slots; refused"
        )
    pending_x = 0
    pending_y = 0
    for slot in range(POSITION_V2_FIXED_BIN_SLOTS):
        record = 4552 + 48 * slot
        pending_x += _u64(data, record + 32)
        pending_y += _u64(data, record + 40)
    return PositionV2(
        address=address,
        lb_pair=_pubkey(data, 8),
        owner=_pubkey(data, 40),
        lower_bin_id=lower_bin_id,
        upper_bin_id=upper_bin_id,
        last_updated_at=_i64(data, 7920),
        total_claimed_fee_x_atoms=_u64(data, 7928),
        total_claimed_fee_y_atoms=_u64(data, 7936),
        liquidity_shares=tuple(_u128(data, 72 + 16 * slot) for slot in range(70)),
        pending_fee_x_atoms_fixed_slots=pending_x,
        pending_fee_y_atoms_fixed_slots=pending_y,
        extension_records=extension_records,
    )


@dataclass(frozen=True)
class OracleObservation:
    """One initialized oracle ring entry, in ring order (oldest first)."""

    cumulative_active_bin_id: int  # i128; divide differences by elapsed for a TWA bin id
    created_at: int
    last_updated_at: int


def decode_oracle(account_info_value: dict, address: str) -> list[OracleObservation]:
    """Decodes the oracle ring into initialized observations, oldest first.

    The record layout is sdk-transcribed (see module docstring); what the bytes themselves
    are held to: whole 32-byte records, the declared ``length`` matching the allocation, the
    declared ``idx`` inside it, and nondecreasing ``last_updated_at`` once unrolled. Any
    violation refuses the account rather than returning a partially trusted history.
    """
    data, owner = account_bytes(account_info_value)
    if owner != METEORA_DLMM_PROGRAM_ID:
        raise LayoutError(f"oracle {address} is owned by {owner}, not the DLMM program")
    # The Oracle account's Anchor discriminator is checked like every other account.
    if data[:8] != anchor_account_discriminator("Oracle"):
        raise LayoutError(f"account {address} does not carry the recomputed Oracle discriminator")
    idx = _u64(data, 8)
    length = _u64(data, 24)
    body = len(data) - ORACLE_HEAD_LEN
    if body != length * ORACLE_OBSERVATION_LEN:
        raise LayoutError(
            f"oracle {address} declares {length} slots but allocates {body} record bytes"
        )
    if length == 0 or idx >= length:
        raise LayoutError(f"oracle {address} ring index {idx} outside declared length {length}")
    unrolled: list[OracleObservation] = []
    # idx is the most recently written slot; the oldest initialized entry follows it.
    for step in range(1, length + 1):
        slot = (idx + step) % length
        offset = ORACLE_HEAD_LEN + slot * ORACLE_OBSERVATION_LEN
        created_at = _i64(data, offset + 16)
        last_updated_at = _i64(data, offset + 24)
        if created_at == 0 and last_updated_at == 0:
            continue  # uninitialized slot
        unrolled.append(
            OracleObservation(
                cumulative_active_bin_id=_i128(data, offset),
                created_at=created_at,
                last_updated_at=last_updated_at,
            )
        )
    for earlier, later in pairwise(unrolled):
        if later.last_updated_at < earlier.last_updated_at:
            raise LayoutError(
                f"oracle {address} ring does not unroll to nondecreasing time; refused"
            )
    return unrolled


def decode_bin_array_liquidity(
    account_info_value: dict, address: str
) -> tuple[int, list[tuple[int, int, int, int]]]:
    """Decodes a BinArray to ``(lower_bin_id, [(bin_id, amount_x, amount_y, supply), ...])``.

    Reads each bin's two reserve amounts and its ``liquidity_supply`` (the denominator of
    every position's per-bin share); the rest of the 112-byte Bin record is skipped by
    size, with the allocation length re-checked first.
    """
    data, owner = account_bytes(account_info_value)
    _require(data, owner, "BinArray", address)
    if len(data) != BIN_ARRAY_HEAD_LEN + BIN_ARRAY_BINS * BIN_RECORD_LEN:
        raise LayoutError(f"BinArray {address} is {len(data)} bytes, not the declared layout")
    index = _i64(data, 8)
    lower_bin_id = index * BIN_ARRAY_BINS
    bins = []
    for slot in range(BIN_ARRAY_BINS):
        offset = BIN_ARRAY_HEAD_LEN + slot * BIN_RECORD_LEN
        bins.append(
            (
                lower_bin_id + slot,
                _u64(data, offset),
                _u64(data, offset + 8),
                _u128(data, offset + 32),
            )
        )
    return lower_bin_id, bins


def position_composition(
    position: PositionV2, bin_arrays: list[tuple[int, list[tuple[int, int, int, int]]]]
) -> tuple[int, int]:
    """The position's current (x_atoms, y_atoms) from its shares and the bins' state.

    Exact integer arithmetic with floor division per bin — the program's own direction of
    rounding for withdrawals, so this is a floor, never an overstatement. Bins the caller
    did not supply arrays for are refused rather than skipped: a partial NAV is not a NAV.
    """
    supply_by_bin: dict[int, tuple[int, int, int]] = {}
    for _, bins in bin_arrays:
        for bin_id, amount_x, amount_y, supply in bins:
            supply_by_bin[bin_id] = (amount_x, amount_y, supply)
    if position.extension_records:
        raise LayoutError(
            f"position {position.address} carries extension bins; per-bin shares past "
            "seventy are located, not attributed, and this NAV refuses to guess"
        )
    total_x = 0
    total_y = 0
    for slot, share in enumerate(position.liquidity_shares):
        if share == 0:
            continue
        bin_id = position.lower_bin_id + slot
        if bin_id > position.upper_bin_id:
            break
        if bin_id not in supply_by_bin:
            raise LayoutError(f"bin {bin_id} of position {position.address} was not supplied")
        amount_x, amount_y, supply = supply_by_bin[bin_id]
        if supply == 0:
            continue
        total_x += amount_x * share // supply
        total_y += amount_y * share // supply
    return total_x, total_y


def bin_price_ratio(bin_step: int, bin_id: int) -> Decimal:
    """``(1 + bin_step/10_000)^bin_id`` as a Decimal, Y atoms per X atom.

    Exact rational arithmetic rounded once at 50 digits; a ratio of atoms, not display
    units — the caller brings the mints' decimals, which these bytes never state.
    """
    with localcontext() as ctx:
        ctx.prec = _PRICE_PRECISION
        base = Decimal(BASIS_POINT_MAX + bin_step) / Decimal(BASIS_POINT_MAX)
        return base**bin_id
