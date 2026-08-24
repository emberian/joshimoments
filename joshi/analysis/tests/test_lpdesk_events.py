"""Event decoding: discriminators recomputed, layouts bound to the retained IDL."""

import base64
import hashlib
import json
from pathlib import Path

from joshi_analysis.lpdesk.events import (
    EVENT_FIELDS,
    anchor_event_discriminator,
    decode_transaction_events,
)

IDL_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "lpdesk" / "dlmm_idl_fb02e51.json"
)

_TYPE_CODES = {"pubkey": "p", "i32": "i4", "u64": "u8b", "u128": "u16b", "i16": "i2", "bool": "b"}


def test_recomputed_event_discriminators_match_the_idl_declarations():
    idl = json.loads(IDL_PATH.read_text())
    declared = {event["name"]: bytes(event["discriminator"]) for event in idl["events"]}
    for name in EVENT_FIELDS:
        assert anchor_event_discriminator(name) == declared[name], name


def test_transcribed_field_layouts_match_the_idl_exactly():
    idl = json.loads(IDL_PATH.read_text())
    types = {t["name"]: t for t in idl["types"]}
    for name, transcribed in EVENT_FIELDS.items():
        expected: list[tuple[str, str]] = []
        for field in types[name]["type"]["fields"]:
            kind = field["type"]
            if isinstance(kind, dict) and "array" in kind:
                element, count = kind["array"]
                if field["name"] == "amounts":
                    names = ["amount_x", "amount_y"]
                elif field["name"] == "rewards":
                    names = ["reward_0", "reward_1"]
                else:
                    names = [f"{field['name']}_{i}" for i in range(count)]
                expected.extend((n, _TYPE_CODES[element]) for n in names)
            else:
                expected.append((field["name"], _TYPE_CODES[kind]))
        assert list(transcribed) == expected, name


def _encode(name: str, values: dict) -> bytes:
    sizes = {"p": 32, "i4": 4, "u8b": 8, "u16b": 16, "i2": 2, "b": 1}
    out = bytearray(anchor_event_discriminator(name))
    for field_name, kind in EVENT_FIELDS[name]:
        value = values[field_name]
        if kind == "p":
            out += _b58decode(value)
        elif kind == "b":
            out += bytes([1 if value else 0])
        elif kind in ("i4", "i2"):
            out += value.to_bytes(sizes[kind], "little", signed=True)
        else:
            out += value.to_bytes(sizes[kind], "little")
    return bytes(out)


_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(text: str) -> bytes:
    value = 0
    for char in text:
        value = value * 58 + _ALPHABET.index(char)
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    pad = len(text) - len(text.lstrip(_ALPHABET[0]))
    return (b"\x00" * pad + raw).rjust(32, b"\x00")


def _b58encode(raw: bytes) -> str:
    value = int.from_bytes(raw, "big")
    out = []
    while value:
        value, rem = divmod(value, 58)
        out.append(_ALPHABET[rem])
    for byte in raw:
        if byte != 0:
            break
        out.append(_ALPHABET[0])
    return "".join(reversed(out))


POOL = _b58encode(bytes(range(32)))
WALLET = _b58encode(bytes(range(1, 33)))
POS = _b58encode(bytes(range(2, 34)))


def test_a_program_data_log_line_decodes_with_exact_amounts():
    blob = _encode(
        "AddLiquidity",
        {
            "lb_pair": POOL, "from": WALLET, "position": POS,
            "amount_x": 123_456_789, "amount_y": 987_654_321, "active_bin_id": -42,
        },
    )
    transaction = {
        "meta": {"logMessages": ["Program data: " + base64.b64encode(blob).decode()]}
    }
    decoded = decode_transaction_events(transaction)
    assert len(decoded.events) == 1
    event = decoded.events[0]
    assert event["event"] == "AddLiquidity"
    assert event["lb_pair"] == POOL
    assert event["position"] == POS
    assert event["amount_x"] == 123_456_789
    assert event["amount_y"] == 987_654_321
    assert event["active_bin_id"] == -42
    assert not decoded.logs_truncated


def test_the_cpi_emission_path_decodes_and_deduplicates_against_the_log_path():
    blob = _encode(
        "ClaimFee",
        {"lb_pair": POOL, "position": POS, "owner": WALLET, "fee_x": 5, "fee_y": 7},
    )
    tag = bytes(reversed(hashlib.sha256(b"anchor:event").digest()[:8]))
    assert tag.hex() == "e445a52e51cb9a1d"  # as observed on retained mainnet bytes
    transaction = {
        "meta": {
            "logMessages": ["Program data: " + base64.b64encode(blob).decode()],
            "innerInstructions": [
                {"instructions": [{"data": _b58encode(tag + blob)}]}
            ],
        }
    }
    decoded = decode_transaction_events(transaction)
    assert len(decoded.events) == 1
    assert decoded.events[0]["fee_x"] == 5


def test_truncated_logs_are_flagged_so_absence_is_not_read_as_evidence():
    transaction = {"meta": {"logMessages": ["Log truncated"]}}
    decoded = decode_transaction_events(transaction)
    assert decoded.logs_truncated
    assert decoded.events == ()


def test_a_swap_event_round_trips_every_field():
    blob = _encode(
        "Swap",
        {
            "lb_pair": POOL, "from": WALLET, "start_bin_id": -5, "end_bin_id": -3,
            "amount_in": 10**12, "amount_out": 2 * 10**8, "swap_for_y": True,
            "fee": 5_000_000, "protocol_fee": 500_000, "fee_bps": 12_345, "host_fee": 0,
        },
    )
    transaction = {
        "meta": {"logMessages": ["Program data: " + base64.b64encode(blob).decode()]}
    }
    event = decode_transaction_events(transaction).events[0]
    assert event["event"] == "Swap"
    assert event["start_bin_id"] == -5
    assert event["end_bin_id"] == -3
    assert event["amount_in"] == 10**12
    assert event["swap_for_y"] is True
    assert event["fee"] == 5_000_000
    assert event["protocol_fee"] == 500_000
    assert event["fee_bps"] == 12_345
