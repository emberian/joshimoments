from __future__ import annotations

import base64
import hashlib
import struct
from collections.abc import Mapping

import pytest
from solders.pubkey import Pubkey

from shitcoims_intelligence.pump import (
    AdvisoryPumpEvent,
    PumpQuarantineReason,
    PumpShareholder,
    QuarantinedPumpEvent,
    _BorshReader,
    _DecodeError,
    decode_pump_event,
    decode_pump_log,
    event_as_record,
)
from shitcoims_intelligence.pump_layouts import (
    MAX_EVENT_BYTES,
    PUMP_AMM_EVENT_LAYOUTS,
    PUMP_AMM_IDL_SHA256,
    PUMP_AMM_PROGRAM_ID,
    PUMP_EVENT_LAYOUTS,
    PUMP_IDL_SHA256,
    PUMP_PROGRAM_ID,
    SCHEMA_COMMIT,
    EventLayout,
    TypeSpec,
)


def _pubkey(seed: int) -> bytes:
    return bytes((seed,)) * 32


def _sample_values(layout: EventLayout) -> dict[str, object]:
    values: dict[str, object] = {}
    for index, (name, spec) in enumerate(layout.fields, start=1):
        if spec == "pubkey":
            values[name] = _pubkey(index)
        elif spec == "string":
            values[name] = "buy" if name == "ix_name" else f"{name}-{index}"
        elif spec == "bool":
            values[name] = True
        elif spec == "i128":
            values[name] = -index
        elif isinstance(spec, tuple) and spec[0] == "vec":
            values[name] = [{"address": _pubkey(index), "share_bps": 10_000}]
        else:
            values[name] = index
    return values


def _encode_value(spec: TypeSpec, value: object) -> bytes:
    if spec == "u8":
        return struct.pack("<B", int(value))
    if spec == "u16":
        return struct.pack("<H", int(value))
    if spec == "u32":
        return struct.pack("<I", int(value))
    if spec == "u64":
        return struct.pack("<Q", int(value))
    if spec == "i64":
        return struct.pack("<q", int(value))
    if spec == "i128":
        return int(value).to_bytes(16, "little", signed=True)
    if spec == "bool":
        return bytes((int(value),))
    if spec == "pubkey":
        assert isinstance(value, bytes) and len(value) == 32
        return value
    if spec == "string":
        encoded = str(value).encode()
        return struct.pack("<I", len(encoded)) + encoded
    if isinstance(spec, tuple) and spec[0] == "option":
        return b"\x00" if value is None else b"\x01" + _encode_value(spec[1], value)  # type: ignore[arg-type]
    if isinstance(spec, tuple) and spec[0] == "vec":
        assert isinstance(value, list)
        element_layout = spec[1]
        output = struct.pack("<I", len(value))
        for item in value:
            assert isinstance(item, Mapping) and isinstance(element_layout, tuple)
            output += b"".join(
                _encode_value(element_spec, item[name]) for name, element_spec in element_layout
            )
        return output
    raise AssertionError(f"unsupported test type {spec!r}")


def _encode_event(layout: EventLayout, values: Mapping[str, object]) -> bytes:
    return layout.discriminator + b"".join(
        _encode_value(spec, values[name]) for name, spec in layout.fields
    )


@pytest.mark.parametrize("layout", PUMP_EVENT_LAYOUTS + PUMP_AMM_EVENT_LAYOUTS, ids=lambda x: x.event_name)
def test_all_pinned_event_layouts_decode_exactly(layout: EventLayout) -> None:
    values = _sample_values(layout)
    raw = _encode_event(layout, values)

    decoded = decode_pump_event(program_id=layout.program_id, data=raw)

    assert isinstance(decoded, AdvisoryPumpEvent)
    assert decoded.event_name == layout.event_name
    assert tuple(decoded.fields) == tuple(name for name, _ in layout.fields)
    assert decoded.provenance.commit == SCHEMA_COMMIT
    assert decoded.provenance.idl_sha256 == layout.idl_sha256
    assert decoded.provenance.discriminator_hex == layout.discriminator.hex()
    for name, spec in layout.fields:
        if spec == "pubkey":
            assert decoded.fields[name] == str(Pubkey.from_bytes(values[name]))  # type: ignore[arg-type]
        elif isinstance(spec, tuple) and spec[0] == "vec":
            shareholder = decoded.fields[name]
            assert shareholder == (
                PumpShareholder(str(Pubkey.from_bytes(values[name][0]["address"])), 10_000),  # type: ignore[index]
            )
        else:
            assert decoded.fields[name] == values[name]


def test_pinned_source_provenance_values_are_exact() -> None:
    assert SCHEMA_COMMIT == "9c82f61cb711b044a17f770ab8ce9f9bdf78f333"
    assert PUMP_IDL_SHA256 == "b90bc471327f671449271d5d1d42354d1fae6f5a06502f5834459a3108138e49"
    assert PUMP_AMM_IDL_SHA256 == "6b5c7ec4e5ef9742fa99dc57b0d75b1031b379bba02a7e1b3c5a4cad68d77e56"
    assert {layout.event_name: layout.discriminator.hex() for layout in PUMP_EVENT_LAYOUTS} == {
        "CreateEvent": "1b72a94ddeeb6376",
        "TradeEvent": "bddb7fd34ee661ee",
        "CompleteEvent": "5f72619cd42e9808",
        "CompletePumpAmmMigrationEvent": "bde95db95c94ea94",
    }
    assert {layout.event_name: layout.discriminator.hex() for layout in PUMP_AMM_EVENT_LAYOUTS} == {
        "CreatePoolEvent": "b1310cd2a076a774",
        "BuyEvent": "67f4521f2cf57777",
        "SellEvent": "3e2f370aa503dc2a",
        "DepositEvent": "78f83d531f8e6b90",
        "WithdrawEvent": "1609851aa02c47c0",
    }


def test_create_event_manual_borsh_fixture() -> None:
    """A manually ordered fixture guards against self-referential layout encoding."""

    layout = PUMP_EVENT_LAYOUTS[0]
    raw = layout.discriminator
    raw += struct.pack("<I", 4) + b"Good"
    raw += struct.pack("<I", 2) + b"GS"
    raw += struct.pack("<I", 17) + b"https://good.test"
    raw += _pubkey(1) + _pubkey(2) + _pubkey(3) + _pubkey(4)
    raw += struct.pack("<qQQQQ", 1_700_000_000, 10, 20, 30, 40)
    raw += _pubkey(5) + b"\x01\x00" + _pubkey(6) + struct.pack("<Q", 50)

    decoded = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=raw)

    assert isinstance(decoded, AdvisoryPumpEvent)
    assert decoded.event_name == "CreateEvent"
    assert decoded.fields["name"] == "Good"
    assert decoded.fields["symbol"] == "GS"
    assert decoded.fields["is_mayhem_mode"] is True
    assert decoded.fields["is_cashback_enabled"] is False
    assert decoded.fields["virtual_quote_reserves"] == 50


def test_base64_log_decoding_and_json_record_are_advisory_only() -> None:
    layout = PUMP_EVENT_LAYOUTS[2]
    raw = _encode_event(layout, _sample_values(layout))
    decoded = decode_pump_log(
        program_id=PUMP_PROGRAM_ID,
        log_line="Program data: " + base64.b64encode(raw).decode(),
    )

    assert isinstance(decoded, AdvisoryPumpEvent)
    record = event_as_record(decoded)
    assert record["event_name"] == "CompleteEvent"
    assert "action" not in record
    assert "execute" not in record
    with pytest.raises(TypeError):
        decoded.fields["mint"] = "attacker"  # type: ignore[index]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ("%%%", PumpQuarantineReason.INVALID_BASE64),
        ("AB==", PumpQuarantineReason.INVALID_BASE64),
        (b"\x01\x02", PumpQuarantineReason.TRUNCATED),
        (b"\xff" * (MAX_EVENT_BYTES + 1), PumpQuarantineReason.PAYLOAD_TOO_LARGE),
    ],
)
def test_input_envelope_failures_are_quarantined(
    data: str | bytes, reason: PumpQuarantineReason
) -> None:
    result = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=data)
    assert isinstance(result, QuarantinedPumpEvent)
    assert result.reason == reason
    assert result.input_length == len(data)


def test_oversize_quarantine_hashes_the_complete_input() -> None:
    raw = b"x" * (MAX_EVENT_BYTES + 1)
    result = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=raw)
    assert isinstance(result, QuarantinedPumpEvent)
    assert result.input_sha256 == hashlib.sha256(raw).hexdigest()


def test_wrong_program_and_unknown_discriminators_are_never_inferred() -> None:
    amm_layout = PUMP_AMM_EVENT_LAYOUTS[3]
    amm_raw = _encode_event(amm_layout, _sample_values(amm_layout))
    mismatch = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=amm_raw)
    unknown = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=b"unknown!payload")
    unsupported = decode_pump_event(program_id=str(Pubkey.new_unique()), data=amm_raw)

    assert isinstance(mismatch, QuarantinedPumpEvent)
    assert mismatch.reason == PumpQuarantineReason.PROGRAM_MISMATCH
    assert isinstance(unknown, QuarantinedPumpEvent)
    assert unknown.reason == PumpQuarantineReason.UNKNOWN_DISCRIMINATOR
    assert isinstance(unsupported, QuarantinedPumpEvent)
    assert unsupported.reason == PumpQuarantineReason.UNSUPPORTED_PROGRAM


def test_truncation_and_trailing_schema_drift_never_partially_decode() -> None:
    layout = PUMP_EVENT_LAYOUTS[2]
    raw = _encode_event(layout, _sample_values(layout))

    truncated = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=raw[:-1])
    trailing = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=raw + b"\x00")

    assert isinstance(truncated, QuarantinedPumpEvent)
    assert truncated.reason == PumpQuarantineReason.TRUNCATED
    assert isinstance(trailing, QuarantinedPumpEvent)
    assert trailing.reason == PumpQuarantineReason.TRAILING_BYTES


def test_string_length_utf8_and_bool_are_strict() -> None:
    create = PUMP_EVENT_LAYOUTS[0]
    too_long = create.discriminator + struct.pack("<I", 257)
    invalid_utf8 = create.discriminator + struct.pack("<I", 1) + b"\xff"
    values = _sample_values(create)
    values["is_mayhem_mode"] = 2
    invalid_bool = _encode_event(create, values)

    results = [
        decode_pump_event(program_id=PUMP_PROGRAM_ID, data=too_long),
        decode_pump_event(program_id=PUMP_PROGRAM_ID, data=invalid_utf8),
        decode_pump_event(program_id=PUMP_PROGRAM_ID, data=invalid_bool),
    ]
    assert [result.reason for result in results if isinstance(result, QuarantinedPumpEvent)] == [
        PumpQuarantineReason.LIMIT_EXCEEDED,
        PumpQuarantineReason.INVALID_UTF8,
        PumpQuarantineReason.INVALID_BOOL,
    ]


def test_shareholder_vector_is_bounded_before_allocation() -> None:
    trade = PUMP_EVENT_LAYOUTS[1]
    values = _sample_values(trade)
    prefix_fields = trade.fields[:27]
    raw = trade.discriminator + b"".join(
        _encode_value(spec, values[name]) for name, spec in prefix_fields
    )
    too_many = decode_pump_event(
        program_id=PUMP_PROGRAM_ID,
        data=raw + struct.pack("<I", 11),
    )
    truncated = decode_pump_event(
        program_id=PUMP_PROGRAM_ID,
        data=raw + struct.pack("<I", 1),
    )

    assert isinstance(too_many, QuarantinedPumpEvent)
    assert too_many.reason == PumpQuarantineReason.LIMIT_EXCEEDED
    assert isinstance(truncated, QuarantinedPumpEvent)
    assert truncated.reason == PumpQuarantineReason.TRUNCATED


def test_borsh_option_tags_are_strict_and_bounded() -> None:
    none_reader = _BorshReader(b"\x00")
    assert none_reader.read_value(("option", "u64"), field="example") is None
    none_reader.finish()

    some_reader = _BorshReader(b"\x01" + struct.pack("<Q", 42))
    assert some_reader.read_value(("option", "u64"), field="example") == 42
    some_reader.finish()

    with pytest.raises(_DecodeError) as invalid:
        _BorshReader(b"\x02").read_value(("option", "u64"), field="example")
    assert invalid.value.reason == PumpQuarantineReason.INVALID_OPTION
    with pytest.raises(_DecodeError) as truncated:
        _BorshReader(b"\x01").read_value(("option", "u64"), field="example")
    assert truncated.value.reason == PumpQuarantineReason.TRUNCATED


def test_direction_and_ix_name_schema_drift_is_quarantined() -> None:
    trade = PUMP_EVENT_LAYOUTS[1]
    direction = _sample_values(trade)
    direction["is_buy"] = False
    drift = _sample_values(trade)
    drift["ix_name"] = "future_buy_v99"
    buy = PUMP_AMM_EVENT_LAYOUTS[1]
    amm_drift = _sample_values(buy)
    amm_drift["ix_name"] = "future_buy_v99"

    results = (
        decode_pump_event(program_id=PUMP_PROGRAM_ID, data=_encode_event(trade, direction)),
        decode_pump_event(program_id=PUMP_PROGRAM_ID, data=_encode_event(trade, drift)),
        decode_pump_event(program_id=PUMP_AMM_PROGRAM_ID, data=_encode_event(buy, amm_drift)),
    )
    assert all(
        isinstance(result, QuarantinedPumpEvent)
        and result.reason == PumpQuarantineReason.SCHEMA_DRIFT
        for result in results
    )


def test_log_prefix_must_be_exact() -> None:
    result = decode_pump_log(program_id=PUMP_PROGRAM_ID, log_line="Program log: harmless")
    assert isinstance(result, QuarantinedPumpEvent)
    assert result.reason == PumpQuarantineReason.INVALID_LOG_PREFIX
