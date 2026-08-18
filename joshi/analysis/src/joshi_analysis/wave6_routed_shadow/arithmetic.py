"""Exact integer and canonicalization helpers for the routed-liquidity shadow study."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from fractions import Fraction
from typing import Any

MAX_ATOMS = (1 << 128) - 1
Q64 = 1 << 64
FEE_PRECISION = 1_000_000_000


class ExactArithmeticError(ValueError):
    """An amount or operation cannot be represented by the study contract."""


def atoms(value: int, *, name: str = "atoms") -> int:
    """Validate a non-negative unsigned 128-bit atomic amount.

    ``bool`` is refused even though it is an ``int`` subclass. Binary floats and
    display decimals never enter the financial path.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ExactArithmeticError(f"{name} must be an integer atom amount")
    if value < 0 or value > MAX_ATOMS:
        raise ExactArithmeticError(f"{name} is outside the unsigned 128-bit envelope")
    return value


def decimal_atoms(value: str, *, name: str = "atoms") -> int:
    """Parse the wire representation used by this study: canonical decimal text."""

    if not isinstance(value, str) or not value:
        raise ExactArithmeticError(f"{name} must be canonical decimal text")
    if value != "0" and value.startswith("0"):
        raise ExactArithmeticError(f"{name} must not contain leading zeroes")
    if not value.isascii() or not value.isdecimal():
        raise ExactArithmeticError(f"{name} must contain ASCII decimal digits only")
    return atoms(int(value), name=name)


def ceil_div(numerator: int, denominator: int) -> int:
    """Return exact integer ceiling division for non-negative operands."""

    if numerator < 0 or denominator <= 0:
        raise ExactArithmeticError(
            "ceil_div requires a non-negative numerator and positive divisor"
        )
    return (numerator + denominator - 1) // denominator


def mul_div_floor(left: int, right: int, denominator: int) -> int:
    """Multiply in Python's wide integer domain, divide down, then check the result."""

    atoms(left, name="left")
    atoms(right, name="right")
    if denominator <= 0:
        raise ExactArithmeticError("denominator must be positive")
    return atoms((left * right) // denominator, name="mul_div result")


def mul_div_ceil(left: int, right: int, denominator: int) -> int:
    """Multiply in Python's wide integer domain, divide up, then check the result."""

    atoms(left, name="left")
    atoms(right, name="right")
    if denominator <= 0:
        raise ExactArithmeticError("denominator must be positive")
    return atoms(ceil_div(left * right, denominator), name="mul_div result")


def fee_ceil(amount: int, rate: int, precision: int) -> int:
    """Calculate one separately rounded fee component."""

    atoms(amount, name="fee base")
    if (
        isinstance(rate, bool)
        or not isinstance(rate, int)
        or isinstance(precision, bool)
        or not isinstance(precision, int)
        or rate < 0
        or rate > precision
        or precision <= 0
    ):
        raise ExactArithmeticError("fee rate is outside its declared precision")
    return atoms(ceil_div(amount * rate, precision), name="fee")


def _canonical(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Fraction):
        return {"numerator": str(value.numerator), "denominator": str(value.denominator)}
    if isinstance(value, dict):
        ordered = sorted(value.items(), key=lambda item: str(item[0]))
        return {str(key): _canonical(item) for key, item in ordered}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise ExactArithmeticError("binary floats are forbidden in canonical study artifacts")
    raise ExactArithmeticError(f"unsupported canonical value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Serialize deterministically with every integer encoded as decimal text."""

    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def digest(value: Any) -> str:
    """Return the SHA-256 identity of the canonical study representation."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()
