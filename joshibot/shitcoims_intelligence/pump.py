"""Strict, advisory-only Pump and PumpSwap event decoding.

The decoder accepts only events attributed by the caller to one of the two pinned
official program ids.  It never infers attribution from a discriminator and never
returns a partially decoded event.  Unknown, malformed, or drifted data produces a
small quarantine record suitable for an intelligence ingest dead-letter queue.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias

from solders.pubkey import Pubkey

from shitcoims_intelligence.pump_layouts import (
    LAYOUTS_BY_PROGRAM,
    MAX_BORSH_STRING_BYTES,
    MAX_EVENT_BYTES,
    PROGRAM_FOR_DISCRIMINATOR,
    SCHEMA_COMMIT,
    SCHEMA_REPOSITORY,
    STRING_BYTE_LIMITS,
    EventLayout,
    FieldLayout,
    TypeSpec,
)


@dataclasses.dataclass(frozen=True, slots=True)
class PumpShareholder:
    address: str
    share_bps: int


PumpValue: TypeAlias = str | int | bool | PumpShareholder | tuple["PumpValue", ...] | None


@dataclasses.dataclass(frozen=True, slots=True)
class PumpSchemaProvenance:
    repository: str
    commit: str
    idl_path: str
    idl_sha256: str
    discriminator_hex: str


@dataclasses.dataclass(frozen=True, slots=True)
class AdvisoryPumpEvent:
    """A decoded observation with deliberately no execution/action fields."""

    program_id: str
    event_name: str
    fields: Mapping[str, PumpValue]
    provenance: PumpSchemaProvenance

    def __post_init__(self) -> None:
        # Prevent callers from mutating a decoded observation after validation.
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def field(self, name: str) -> PumpValue:
        return self.fields[name]


class PumpQuarantineReason(StrEnum):
    INVALID_INPUT_TYPE = "invalid_input_type"
    INVALID_LOG_PREFIX = "invalid_log_prefix"
    INVALID_BASE64 = "invalid_base64"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_PROGRAM = "unsupported_program"
    TRUNCATED = "truncated"
    UNKNOWN_DISCRIMINATOR = "unknown_discriminator"
    PROGRAM_MISMATCH = "program_mismatch"
    INVALID_BOOL = "invalid_bool"
    INVALID_UTF8 = "invalid_utf8"
    LIMIT_EXCEEDED = "limit_exceeded"
    INVALID_OPTION = "invalid_option"
    TRAILING_BYTES = "trailing_bytes"
    SCHEMA_DRIFT = "schema_drift"


@dataclasses.dataclass(frozen=True, slots=True)
class QuarantinedPumpEvent:
    """Non-executable metadata about rejected input; raw bytes are not retained."""

    program_id: str
    reason: PumpQuarantineReason
    detail: str
    input_length: int
    input_sha256: str
    discriminator_hex: str | None
    schema_commit: str = SCHEMA_COMMIT


PumpDecodeResult: TypeAlias = AdvisoryPumpEvent | QuarantinedPumpEvent


class _DecodeError(ValueError):
    def __init__(self, reason: PumpQuarantineReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _BorshReader:
    __slots__ = ("_data", "_offset")

    def __init__(self, data: bytes) -> None:
        self._data = memoryview(data)
        self._offset = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset

    def read_fields(self, fields: tuple[FieldLayout, ...]) -> dict[str, PumpValue]:
        return {name: self.read_value(spec, field=name) for name, spec in fields}

    def read_value(self, spec: TypeSpec, *, field: str) -> PumpValue:
        if spec == "u8":
            return self._read_int(1, signed=False, field=field)
        if spec == "u16":
            return self._read_int(2, signed=False, field=field)
        if spec == "u32":
            return self._read_int(4, signed=False, field=field)
        if spec == "u64":
            return self._read_int(8, signed=False, field=field)
        if spec == "i64":
            return self._read_int(8, signed=True, field=field)
        if spec == "i128":
            return self._read_int(16, signed=True, field=field)
        if spec == "bool":
            value = self._read_int(1, signed=False, field=field)
            if value not in (0, 1):
                raise _DecodeError(
                    PumpQuarantineReason.INVALID_BOOL,
                    f"{field}: Borsh bool tag must be 0 or 1",
                )
            return bool(value)
        if spec == "pubkey":
            return str(Pubkey.from_bytes(self._read_exact(32, field=field)))
        if spec == "string":
            return self._read_string(field)

        if not isinstance(spec, tuple) or not spec:
            raise _DecodeError(PumpQuarantineReason.SCHEMA_DRIFT, f"{field}: unsupported type")

        if spec[0] == "option" and len(spec) == 2:
            tag = self._read_int(1, signed=False, field=f"{field}.option")
            if tag == 0:
                return None
            if tag != 1:
                raise _DecodeError(
                    PumpQuarantineReason.INVALID_OPTION,
                    f"{field}: Borsh option tag must be 0 or 1",
                )
            return self.read_value(spec[1], field=field)  # type: ignore[arg-type]

        if spec[0] == "vec" and len(spec) == 3:
            element_layout = spec[1]
            maximum = spec[2]
            if not isinstance(element_layout, tuple) or not isinstance(maximum, int):
                raise _DecodeError(PumpQuarantineReason.SCHEMA_DRIFT, f"{field}: invalid vector layout")
            count = self._read_int(4, signed=False, field=f"{field}.length")
            if count > maximum:
                raise _DecodeError(
                    PumpQuarantineReason.LIMIT_EXCEEDED,
                    f"{field}: vector length {count} exceeds {maximum}",
                )
            minimum_bytes = _minimum_struct_bytes(element_layout)
            if count * minimum_bytes > self.remaining:
                raise _DecodeError(
                    PumpQuarantineReason.TRUNCATED,
                    f"{field}: vector contents exceed remaining payload",
                )
            values: list[PumpValue] = []
            for index in range(count):
                item = self.read_fields(element_layout)
                if set(item) == {"address", "share_bps"}:
                    values.append(
                        PumpShareholder(address=str(item["address"]), share_bps=int(item["share_bps"]))
                    )
                else:
                    # No current production layout reaches this branch.  Keeping it
                    # fail closed prevents a newly added struct from silently gaining
                    # a mutable/untyped representation.
                    raise _DecodeError(
                        PumpQuarantineReason.SCHEMA_DRIFT,
                        f"{field}[{index}]: unsupported vector element",
                    )
            return tuple(values)

        raise _DecodeError(PumpQuarantineReason.SCHEMA_DRIFT, f"{field}: unsupported type")

    def finish(self) -> None:
        if self.remaining:
            raise _DecodeError(
                PumpQuarantineReason.TRAILING_BYTES,
                f"decoded event has {self.remaining} trailing byte(s)",
            )

    def _read_exact(self, length: int, *, field: str) -> bytes:
        if length < 0 or length > self.remaining:
            raise _DecodeError(
                PumpQuarantineReason.TRUNCATED,
                f"{field}: needs {length} byte(s), only {self.remaining} remain",
            )
        start = self._offset
        self._offset += length
        return self._data[start : start + length].tobytes()

    def _read_int(self, length: int, *, signed: bool, field: str) -> int:
        return int.from_bytes(self._read_exact(length, field=field), "little", signed=signed)

    def _read_string(self, field: str) -> str:
        length = self._read_int(4, signed=False, field=f"{field}.length")
        limit = STRING_BYTE_LIMITS.get(field, MAX_BORSH_STRING_BYTES)
        if length > limit:
            raise _DecodeError(
                PumpQuarantineReason.LIMIT_EXCEEDED,
                f"{field}: string length {length} exceeds {limit}",
            )
        raw = self._read_exact(length, field=field)
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _DecodeError(
                PumpQuarantineReason.INVALID_UTF8,
                f"{field}: string is not valid UTF-8",
            ) from exc


def decode_pump_event(*, program_id: str, data: bytes | bytearray | memoryview | str) -> PumpDecodeResult:
    """Decode one attributed event payload or return a fail-closed quarantine record.

    ``data`` may be raw bytes or a strictly encoded base64 string.  The raw payload
    starts with the 8-byte Anchor event discriminator.  The supplied ``program_id``
    must come from trusted transaction/invocation context; it is never inferred.
    """

    raw_or_error = _coerce_payload(program_id, data)
    if isinstance(raw_or_error, QuarantinedPumpEvent):
        return raw_or_error
    raw = raw_or_error
    discriminator = raw[:8] if len(raw) >= 8 else None

    if program_id not in LAYOUTS_BY_PROGRAM:
        return _quarantine(
            program_id,
            PumpQuarantineReason.UNSUPPORTED_PROGRAM,
            "event is not attributed to a pinned Pump program",
            raw,
            discriminator,
        )
    if discriminator is None:
        return _quarantine(
            program_id,
            PumpQuarantineReason.TRUNCATED,
            "payload does not contain an 8-byte event discriminator",
            raw,
            None,
        )

    layout = LAYOUTS_BY_PROGRAM[program_id].get(discriminator)
    if layout is None:
        other_program = PROGRAM_FOR_DISCRIMINATOR.get(discriminator)
        if other_program is not None:
            return _quarantine(
                program_id,
                PumpQuarantineReason.PROGRAM_MISMATCH,
                "discriminator belongs to the other pinned Pump program",
                raw,
                discriminator,
            )
        return _quarantine(
            program_id,
            PumpQuarantineReason.UNKNOWN_DISCRIMINATOR,
            "discriminator is not supported by the pinned schema",
            raw,
            discriminator,
        )

    try:
        event = _decode_layout(layout, raw[8:])
    except _DecodeError as exc:
        return _quarantine(program_id, exc.reason, exc.detail, raw, discriminator)
    return event


def decode_pump_log(*, program_id: str, log_line: str) -> PumpDecodeResult:
    """Decode one exact Anchor ``Program data:`` log line.

    Invocation-stack tracking belongs to the collector.  This helper still requires
    explicit program attribution so an attacker cannot smuggle a valid discriminator
    through another program's logs.
    """

    prefix = "Program data: "
    if not isinstance(log_line, str) or not log_line.startswith(prefix):
        raw = log_line.encode("utf-8", errors="replace") if isinstance(log_line, str) else b""
        return _quarantine(
            program_id,
            PumpQuarantineReason.INVALID_LOG_PREFIX,
            "expected an exact 'Program data: ' log prefix",
            raw,
            None,
        )
    return decode_pump_event(program_id=program_id, data=log_line[len(prefix) :])


def _decode_layout(layout: EventLayout, payload: bytes) -> AdvisoryPumpEvent:
    reader = _BorshReader(payload)
    fields = reader.read_fields(layout.fields)
    reader.finish()
    _validate_event_semantics(layout.event_name, fields)
    return AdvisoryPumpEvent(
        program_id=layout.program_id,
        event_name=layout.event_name,
        fields=fields,
        provenance=PumpSchemaProvenance(
            repository=SCHEMA_REPOSITORY,
            commit=SCHEMA_COMMIT,
            idl_path=layout.idl_path,
            idl_sha256=layout.idl_sha256,
            discriminator_hex=layout.discriminator.hex(),
        ),
    )


def _validate_event_semantics(event_name: str, fields: Mapping[str, PumpValue]) -> None:
    if event_name == "TradeEvent":
        allowed = {"buy", "sell", "buy_exact_sol_in"}
        ix_name = fields["ix_name"]
        if ix_name not in allowed:
            raise _DecodeError(
                PumpQuarantineReason.SCHEMA_DRIFT,
                "TradeEvent.ix_name is outside the pinned schema",
            )
        if bool(fields["is_buy"]) != (ix_name != "sell"):
            raise _DecodeError(
                PumpQuarantineReason.SCHEMA_DRIFT,
                "TradeEvent direction fields are inconsistent",
            )
    elif event_name == "BuyEvent" and fields["ix_name"] not in {"buy", "buy_exact_quote_in"}:
        raise _DecodeError(
            PumpQuarantineReason.SCHEMA_DRIFT,
            "BuyEvent.ix_name is outside the pinned schema",
        )


def _coerce_payload(
    program_id: str, data: bytes | bytearray | memoryview | str
) -> bytes | QuarantinedPumpEvent:
    if isinstance(data, str):
        encoded = data.encode("ascii", errors="ignore")
        if len(encoded) != len(data):
            return _quarantine(
                program_id,
                PumpQuarantineReason.INVALID_BASE64,
                "base64 payload must contain ASCII only",
                data.encode("utf-8", errors="replace"),
                None,
            )
        # Bound the textual input before asking the base64 decoder to allocate.
        maximum_encoded = ((MAX_EVENT_BYTES + 2) // 3) * 4
        if len(encoded) > maximum_encoded:
            return _quarantine(
                program_id,
                PumpQuarantineReason.PAYLOAD_TOO_LARGE,
                f"encoded payload exceeds the {MAX_EVENT_BYTES}-byte boundary",
                encoded,
                None,
            )
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return _quarantine(
                program_id,
                PumpQuarantineReason.INVALID_BASE64,
                "payload is not canonical base64",
                encoded,
                None,
            )
        if base64.b64encode(raw) != encoded:
            return _quarantine(
                program_id,
                PumpQuarantineReason.INVALID_BASE64,
                "payload is not canonical base64",
                encoded,
                None,
            )
    elif isinstance(data, (bytes, bytearray, memoryview)):
        if len(data) > MAX_EVENT_BYTES:
            return _quarantine(
                program_id,
                PumpQuarantineReason.PAYLOAD_TOO_LARGE,
                f"payload exceeds the {MAX_EVENT_BYTES}-byte boundary",
                data,
                None,
                input_length=len(data),
            )
        raw = bytes(data)
    else:
        return _quarantine(
            program_id,
            PumpQuarantineReason.INVALID_INPUT_TYPE,
            "payload must be bytes-like or a base64 string",
            b"",
            None,
        )

    if len(raw) > MAX_EVENT_BYTES:
        return _quarantine(
            program_id,
            PumpQuarantineReason.PAYLOAD_TOO_LARGE,
            f"decoded payload exceeds the {MAX_EVENT_BYTES}-byte boundary",
            raw[:MAX_EVENT_BYTES],
            None,
            input_length=len(raw),
        )
    return raw


def _minimum_struct_bytes(fields: tuple[FieldLayout, ...]) -> int:
    return sum(_minimum_value_bytes(spec) for _, spec in fields)


def _minimum_value_bytes(spec: TypeSpec) -> int:
    widths = {"u8": 1, "bool": 1, "u16": 2, "u32": 4, "u64": 8, "i64": 8, "i128": 16}
    if isinstance(spec, str):
        if spec == "pubkey":
            return 32
        if spec == "string":
            return 4
        return widths.get(spec, 0)
    if isinstance(spec, tuple) and spec and spec[0] == "option":
        return 1
    if isinstance(spec, tuple) and spec and spec[0] == "vec":
        return 4
    return 0


def _quarantine(
    program_id: str,
    reason: PumpQuarantineReason,
    detail: str,
    raw: bytes | bytearray | memoryview,
    discriminator: bytes | None,
    *,
    input_length: int | None = None,
) -> QuarantinedPumpEvent:
    return QuarantinedPumpEvent(
        program_id=program_id,
        reason=reason,
        detail=detail,
        input_length=len(raw) if input_length is None else input_length,
        input_sha256=hashlib.sha256(raw).hexdigest(),
        discriminator_hex=discriminator.hex() if discriminator is not None else None,
    )


def event_as_record(event: AdvisoryPumpEvent) -> dict[str, Any]:
    """Return a JSON-ready advisory record without adding any action semantics."""

    fields: dict[str, Any] = {}
    for name, value in event.fields.items():
        if isinstance(value, tuple):
            fields[name] = [
                dataclasses.asdict(item) if dataclasses.is_dataclass(item) else item for item in value
            ]
        else:
            fields[name] = value
    return {
        "program_id": event.program_id,
        "event_name": event.event_name,
        "fields": fields,
        "schema": dataclasses.asdict(event.provenance),
    }
