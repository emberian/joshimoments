"""Anchor event decoding for ``lb_clmm`` from retained transaction bytes.

The program emits events two ways and this module reads both: ``emit!`` writes a
``Program data: <base64>`` log line, and ``emit_cpi!`` writes the same bytes as a self-CPI
inner instruction prefixed by Anchor's event-instruction tag. Either way the payload is an
8-byte event discriminator followed by the Borsh-encoded fields.

Discriminators are **recomputed** here as ``sha256("event:<Name>")[..8]`` — the retained IDL
(``analysis/fixtures/lpdesk/dlmm_idl_fb02e51.json``) declares them literally and the test
suite checks recomputation and declaration agree, the same stance ``meteora.rs`` takes for
account discriminators.

Field layouts are transcribed from that IDL's event definitions. The binding to the chain is
not the transcription but the reconciliation the reconstruction performs: decoded amounts
must equal the same transaction's own pre/post token-balance deltas on the pool's reserve
accounts, and a transaction whose events and balances disagree is carried as refused, never
averaged.

**What logs cannot promise.** Solana truncates long log buffers; a truncated log stream can
silently drop ``Program data`` lines. Truncation is detected and carried on the decode
result so a consumer knows when absence-of-event is not evidence-of-absence.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

__all__ = [
    "EVENT_FIELDS",
    "DecodedEvents",
    "anchor_event_discriminator",
    "decode_transaction_events",
]

#: Anchor's event-instruction tag, the prefix emit_cpi uses. Anchor defines it as the u64
#: whose big-endian digits are sha256("anchor:event")[..8] and serializes it little-endian,
#: so the wire bytes are that digest prefix REVERSED — verified against retained mainnet
#: inner instructions (e445a52e51cb9a1d).
_EVENT_IX_TAG = bytes(reversed(hashlib.sha256(b"anchor:event").digest()[:8]))

# Field layouts, transcribed from the retained IDL's event definitions.
# type codes: p = pubkey(32), i4/u4 = 32-bit, u8b = u64, u16b = u128, i2 = i16, b = bool(1)
EVENT_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "Swap": (
        ("lb_pair", "p"),
        ("from", "p"),
        ("start_bin_id", "i4"),
        ("end_bin_id", "i4"),
        ("amount_in", "u8b"),
        ("amount_out", "u8b"),
        ("swap_for_y", "b"),
        ("fee", "u8b"),
        ("protocol_fee", "u8b"),
        ("fee_bps", "u16b"),
        ("host_fee", "u8b"),
    ),
    "Swap2Evt": (
        ("lb_pair", "p"),
        ("from", "p"),
        ("start_bin_id", "i4"),
        ("end_bin_id", "i4"),
        ("swap_for_y", "b"),
        ("fee_bps", "u16b"),
        ("amount_in", "u8b"),
        ("amount_left", "u8b"),
        ("amount_out", "u8b"),
        ("mm_fee", "u8b"),
        ("protocol_fee", "u8b"),
        ("limit_order_fee", "u8b"),
        ("host_fee", "u8b"),
        ("fees_on_input", "b"),
        ("fees_on_token_x", "b"),
    ),
    "AddLiquidity": (
        ("lb_pair", "p"),
        ("from", "p"),
        ("position", "p"),
        ("amount_x", "u8b"),
        ("amount_y", "u8b"),
        ("active_bin_id", "i4"),
    ),
    "RemoveLiquidity": (
        ("lb_pair", "p"),
        ("from", "p"),
        ("position", "p"),
        ("amount_x", "u8b"),
        ("amount_y", "u8b"),
        ("active_bin_id", "i4"),
    ),
    "ClaimFee": (
        ("lb_pair", "p"),
        ("position", "p"),
        ("owner", "p"),
        ("fee_x", "u8b"),
        ("fee_y", "u8b"),
    ),
    "ClaimFee2": (
        ("lb_pair", "p"),
        ("position", "p"),
        ("owner", "p"),
        ("fee_x", "u8b"),
        ("fee_y", "u8b"),
        ("active_bin_id", "i4"),
    ),
    "PositionCreate": (("lb_pair", "p"), ("position", "p"), ("owner", "p")),
    "PositionClose": (("position", "p"), ("owner", "p")),
    "CompositionFee": (
        ("from", "p"),
        ("bin_id", "i2"),
        ("token_x_fee_amount", "u8b"),
        ("token_y_fee_amount", "u8b"),
        ("protocol_token_x_fee_amount", "u8b"),
        ("protocol_token_y_fee_amount", "u8b"),
    ),
    "Rebalancing": (
        ("lb_pair", "p"),
        ("position", "p"),
        ("owner", "p"),
        ("active_bin_id", "i4"),
        ("x_withdrawn_amount", "u8b"),
        ("x_added_amount", "u8b"),
        ("y_withdrawn_amount", "u8b"),
        ("y_added_amount", "u8b"),
        ("x_fee_amount", "u8b"),
        ("y_fee_amount", "u8b"),
        ("old_min_id", "i4"),
        ("old_max_id", "i4"),
        ("new_min_id", "i4"),
        ("new_max_id", "i4"),
        ("reward_0", "u8b"),
        ("reward_1", "u8b"),
    ),
}

_SIZES = {"p": 32, "i4": 4, "u4": 4, "u8b": 8, "u16b": 16, "i2": 2, "b": 1}

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def anchor_event_discriminator(name: str) -> bytes:
    """``sha256("event:<Name>")[..8]`` — recomputed, never transcribed."""
    return hashlib.sha256(f"event:{name}".encode()).digest()[:8]


_DISCRIMINATORS = {anchor_event_discriminator(name): name for name in EVENT_FIELDS}


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


def _b58decode(text: str) -> bytes:
    value = 0
    for char in text:
        value = value * 58 + _B58_INDEX[char]
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    pad = len(text) - len(text.lstrip(_B58_ALPHABET[0]))
    return b"\x00" * pad + raw


def _decode_fields(name: str, payload: bytes) -> dict | None:
    fields = EVENT_FIELDS[name]
    needed = sum(_SIZES[kind] for _, kind in fields)
    if len(payload) < needed:
        return None
    out: dict = {"event": name}
    offset = 0
    for field_name, kind in fields:
        size = _SIZES[kind]
        chunk = payload[offset : offset + size]
        if kind == "p":
            out[field_name] = _b58encode(chunk)
        elif kind in ("i4", "i2"):
            out[field_name] = int.from_bytes(chunk, "little", signed=True)
        elif kind == "b":
            out[field_name] = chunk[0] != 0
        else:
            out[field_name] = int.from_bytes(chunk, "little")
        offset += size
    return out


def _decode_blob(blob: bytes) -> dict | None:
    if len(blob) < 8:
        return None
    name = _DISCRIMINATORS.get(blob[:8])
    if name is None:
        return None
    return _decode_fields(name, blob[8:])


@dataclass(frozen=True)
class DecodedEvents:
    """Events one transaction emitted, with the honesty flags a consumer needs."""

    events: tuple[dict, ...]
    logs_truncated: bool
    #: True when at least one event came from the log path; log-path events are lost when
    #: logs truncate, so ``logs_truncated and not cpi_events`` means the set may be a floor.
    from_logs: bool


def decode_transaction_events(transaction: dict) -> DecodedEvents:
    """Decodes every recognized lb_clmm event a retained ``getTransaction`` result carries.

    Reads both emission paths and deduplicates: when the same event bytes appear in the log
    stream and as a self-CPI record, one copy is kept. Unrecognized events are skipped, not
    errors — this desk reads the events it has provenance for and no more.
    """
    meta = transaction.get("meta") or {}
    events: list[dict] = []
    seen: set[bytes] = set()
    from_logs = False
    logs_truncated = False
    for line in meta.get("logMessages") or []:
        if line == "Log truncated":
            logs_truncated = True
        prefix = "Program data: "
        if not line.startswith(prefix):
            continue
        try:
            blob = base64.b64decode(line[len(prefix) :])
        except ValueError:
            continue
        decoded = _decode_blob(blob)
        if decoded is not None and blob not in seen:
            seen.add(blob)
            events.append(decoded)
            from_logs = True
    for group in meta.get("innerInstructions") or []:
        for inner in group.get("instructions") or []:
            data_field = inner.get("data")
            if not isinstance(data_field, str):
                continue
            try:
                raw = _b58decode(data_field)
            except KeyError:
                continue
            if len(raw) < 16 or raw[:8] != _EVENT_IX_TAG:
                continue
            blob = raw[8:]
            decoded = _decode_blob(blob)
            if decoded is not None and blob not in seen:
                seen.add(blob)
                events.append(decoded)
    return DecodedEvents(
        events=tuple(events), logs_truncated=logs_truncated, from_logs=from_logs
    )
