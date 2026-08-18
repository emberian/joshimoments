"""Pinned exact Pump/PumpSwap quote formulas used by the shadow study."""

from __future__ import annotations

from dataclasses import dataclass

from .arithmetic import (
    FEE_PRECISION,
    MAX_ATOMS,
    Q64,
    atoms,
    fee_ceil,
    mul_div_ceil,
    mul_div_floor,
)

BPS = 10_000
MAX_U64 = (1 << 64) - 1
MIN_I128 = -(1 << 127)
MAX_I128 = (1 << 127) - 1


class ProtocolQuoteRefusal(ValueError):
    """A protocol quote is unsupported or lacks real capacity."""


class DlmmMathRefusal(ValueError):
    """The pinned fixed-width DLMM operation graph refuses the input."""


def _u64(value: int, name: str) -> int:
    atoms(value, name=name)
    if value > MAX_U64:
        raise ProtocolQuoteRefusal(f"{name}_outside_u64")
    return value


def _checked_u128_product(left: int, right: int) -> int:
    result = left * right
    if result > MAX_ATOMS:
        raise DlmmMathRefusal("arithmetic_overflow")
    return result


def _i128(value: int, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_I128 <= value <= MAX_I128
    ):
        raise ProtocolQuoteRefusal(f"{name}_outside_i128")
    return value


@dataclass(frozen=True, slots=True)
class PumpFeeSchedule:
    lp_bps: int
    protocol_bps: int
    creator_bps: int | None

    def __post_init__(self) -> None:
        for name in ("lp_bps", "protocol_bps"):
            rate = getattr(self, name)
            if isinstance(rate, bool) or not isinstance(rate, int) or not 0 <= rate <= BPS:
                raise ValueError(f"{name} is outside basis-point precision")
        if self.creator_bps is not None and (
                isinstance(self.creator_bps, bool)
                or not isinstance(self.creator_bps, int)
                or not 0 <= self.creator_bps <= BPS
        ):
            raise ValueError("creator_bps is outside basis-point precision")

    def components(self, raw_quote_atoms: int) -> tuple[int, int, int]:
        if self.creator_bps is None:
            raise ProtocolQuoteRefusal("creator_fee_applicability_unknown")
        return (
            fee_ceil(raw_quote_atoms, self.lp_bps, BPS),
            fee_ceil(raw_quote_atoms, self.protocol_bps, BPS),
            fee_ceil(raw_quote_atoms, self.creator_bps, BPS),
        )


@dataclass(frozen=True, slots=True)
class ProtocolQuote:
    input_atoms: int
    output_atoms: int
    raw_quote_atoms: int
    lp_fee_atoms: int
    protocol_fee_atoms: int
    creator_fee_atoms: int


def dlmm_price_q64(bin_id: int, bin_step_bps: int) -> int:
    """Reproduce the pinned 19-bit, checked-u128 DLMM bin-price operation graph."""

    if isinstance(bin_id, bool) or not isinstance(bin_id, int):
        raise DlmmMathRefusal("bin_id_must_be_i32")
    if not -(1 << 31) <= bin_id < (1 << 31):
        raise DlmmMathRefusal("bin_id_must_be_i32")
    if isinstance(bin_step_bps, bool) or not isinstance(bin_step_bps, int):
        raise DlmmMathRefusal("bin_step_must_be_u16")
    if not 0 < bin_step_bps <= 65_535:
        raise DlmmMathRefusal("invalid_bin_step")
    step_q64 = (bin_step_bps * Q64) // 10_000
    base = Q64 + step_q64
    if base > MAX_ATOMS:
        raise DlmmMathRefusal("multiplication_overflow")
    exponent_abs = abs(bin_id)
    if exponent_abs >= 0x80_000:
        raise DlmmMathRefusal("exponent_out_of_range")
    if exponent_abs == 0:
        return Q64

    invert = bin_id < 0
    if base >= Q64:
        base = MAX_ATOMS // base
        invert = not invert
    result = Q64
    squared = base
    for bit in range(19):
        if exponent_abs & (1 << bit):
            product = result * squared
            if product > MAX_ATOMS:
                raise DlmmMathRefusal("multiplication_overflow")
            result = product >> 64
        if bit != 18:
            product = squared * squared
            if product > MAX_ATOMS:
                raise DlmmMathRefusal("multiplication_overflow")
            squared = product >> 64
    if result == 0:
        raise DlmmMathRefusal("zero_result")
    if invert:
        result = MAX_ATOMS // result
    return atoms(result, name="DLMM Q64.64 price")


def dlmm_dynamic_fee_rate(
    *,
    base_factor: int,
    bin_step: int,
    base_fee_power_factor: int,
    variable_fee_control: int,
    volatility_accumulator: int,
) -> int:
    """Compute the current capped DLMM dynamic fee in 1e9 units."""

    for name, value, maximum in (
        ("base_factor", base_factor, (1 << 16) - 1),
        ("bin_step", bin_step, (1 << 16) - 1),
        ("base_fee_power_factor", base_fee_power_factor, (1 << 8) - 1),
        ("variable_fee_control", variable_fee_control, (1 << 32) - 1),
        ("volatility_accumulator", volatility_accumulator, (1 << 32) - 1),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise DlmmMathRefusal(f"{name}_outside_profile_width")
    power = 10**base_fee_power_factor
    if power > MAX_ATOMS:
        raise DlmmMathRefusal("arithmetic_overflow")
    base_rate = _checked_u128_product(base_factor, bin_step)
    base_rate = _checked_u128_product(base_rate, 10)
    base_rate = _checked_u128_product(base_rate, power)
    volatility_step = _checked_u128_product(volatility_accumulator, bin_step)
    volatility_squared = _checked_u128_product(volatility_step, volatility_step)
    variable_numerator = variable_fee_control * volatility_squared
    variable_rate = (variable_numerator + 99_999_999_999) // 100_000_000_000
    if variable_rate > MAX_ATOMS or base_rate + variable_rate > MAX_ATOMS:
        raise DlmmMathRefusal("arithmetic_overflow")
    return min(base_rate + variable_rate, 100_000_000)


def dlmm_fee_from_net(net_amount: int, rate_1e9: int) -> int:
    """Fee added to requested net input: ceil(net*rate/(1e9-rate))."""

    _u64(net_amount, "DLMM_net_amount")
    if not 0 <= rate_1e9 <= 100_000_000:
        raise DlmmMathRefusal("rate_above_protocol_maximum")
    return _u64(
        mul_div_ceil(net_amount, rate_1e9, FEE_PRECISION - rate_1e9),
        "DLMM_net_fee",
    )


def dlmm_fee_from_gross(gross_amount: int, rate_1e9: int) -> int:
    """Fee contained in a gross input: ceil(gross*rate/1e9)."""

    _u64(gross_amount, "DLMM_gross_amount")
    if not 0 <= rate_1e9 <= 100_000_000:
        raise DlmmMathRefusal("rate_above_protocol_maximum")
    return _u64(
        mul_div_ceil(gross_amount, rate_1e9, FEE_PRECISION),
        "DLMM_gross_fee",
    )


def dlmm_protocol_fee(fee_amount: int, protocol_share_bps: int) -> int:
    """Floor the protocol share of a realized DLMM fee in bps."""

    _u64(fee_amount, "DLMM_fee_amount")
    if not 0 <= protocol_share_bps <= BPS:
        raise DlmmMathRefusal("protocol_share_above_one_hundred_percent")
    return _u64(
        mul_div_floor(fee_amount, protocol_share_bps, BPS),
        "DLMM_protocol_fee",
    )


def pump_curve_buy_exact_base_out(
    *,
    base_out: int,
    virtual_base: int,
    virtual_quote: int,
    real_base: int,
    fees: PumpFeeSchedule,
) -> ProtocolQuote:
    """Pump buy: literal floor-plus-one, then separately rounded fee components."""

    for name, value in (
        ("base_out", base_out),
        ("virtual_base", virtual_base),
        ("virtual_quote", virtual_quote),
        ("real_base", real_base),
    ):
        _u64(value, name)
    if base_out == 0:
        raise ProtocolQuoteRefusal("zero_size")
    if base_out > real_base:
        raise ProtocolQuoteRefusal("insufficient_real_base")
    if base_out >= virtual_base:
        raise ProtocolQuoteRefusal("invalid_reserve_state")
    raw = _u64(
        mul_div_floor(base_out, virtual_quote, virtual_base - base_out) + 1,
        "raw_quote",
    )
    lp_fee, protocol_fee, creator_fee = fees.components(raw)
    return ProtocolQuote(
        input_atoms=_u64(raw + lp_fee + protocol_fee + creator_fee, "user_input"),
        output_atoms=base_out,
        raw_quote_atoms=raw,
        lp_fee_atoms=lp_fee,
        protocol_fee_atoms=protocol_fee,
        creator_fee_atoms=creator_fee,
    )


def pump_curve_sell_exact_base_in(
    *,
    base_in: int,
    virtual_base: int,
    virtual_quote: int,
    real_quote: int,
    fees: PumpFeeSchedule,
) -> ProtocolQuote:
    """Pump sell: floor raw output, enforce real payout, then subtract fees."""

    for name, value in (
        ("base_in", base_in),
        ("virtual_base", virtual_base),
        ("virtual_quote", virtual_quote),
        ("real_quote", real_quote),
    ):
        _u64(value, name)
    if base_in == 0:
        raise ProtocolQuoteRefusal("zero_size")
    raw = _u64(mul_div_floor(base_in, virtual_quote, virtual_base + base_in), "raw_quote")
    if raw > real_quote:
        raise ProtocolQuoteRefusal("insufficient_real_quote")
    lp_fee, protocol_fee, creator_fee = fees.components(raw)
    output = raw - lp_fee - protocol_fee - creator_fee
    if output < 0:
        raise ProtocolQuoteRefusal("fees_exceed_raw_output")
    return ProtocolQuote(
        input_atoms=base_in,
        output_atoms=output,
        raw_quote_atoms=raw,
        lp_fee_atoms=lp_fee,
        protocol_fee_atoms=protocol_fee,
        creator_fee_atoms=creator_fee,
    )


def pumpswap_buy_exact_base_out(
    *,
    base_out: int,
    base_reserve: int,
    raw_quote_reserve: int,
    virtual_quote_reserve: int,
    fees: PumpFeeSchedule,
) -> ProtocolQuote:
    """PumpSwap buy using the signed-virtual-adjusted quote reserve."""

    for name, value in (
        ("base_out", base_out),
        ("base_reserve", base_reserve),
        ("raw_quote_reserve", raw_quote_reserve),
    ):
        _u64(value, name)
    _i128(virtual_quote_reserve, "virtual_quote_reserve")
    effective_quote = raw_quote_reserve + virtual_quote_reserve
    if effective_quote <= 0:
        raise ProtocolQuoteRefusal("nonpositive_effective_quote_reserve")
    atoms(effective_quote, name="effective quote reserve")
    if base_out == 0:
        raise ProtocolQuoteRefusal("zero_size")
    if base_out >= base_reserve:
        raise ProtocolQuoteRefusal("insufficient_real_base")
    raw = _u64(
        mul_div_ceil(effective_quote, base_out, base_reserve - base_out),
        "raw_quote",
    )
    lp_fee, protocol_fee, creator_fee = fees.components(raw)
    return ProtocolQuote(
        input_atoms=_u64(raw + lp_fee + protocol_fee + creator_fee, "user_input"),
        output_atoms=base_out,
        raw_quote_atoms=raw,
        lp_fee_atoms=lp_fee,
        protocol_fee_atoms=protocol_fee,
        creator_fee_atoms=creator_fee,
    )


def pumpswap_sell_exact_base_in(
    *,
    base_in: int,
    base_reserve: int,
    raw_quote_reserve: int,
    virtual_quote_reserve: int,
    fees: PumpFeeSchedule,
) -> ProtocolQuote:
    """PumpSwap sell with the SDK's LP-retained real-vault capacity boundary."""

    for name, value in (
        ("base_in", base_in),
        ("base_reserve", base_reserve),
        ("raw_quote_reserve", raw_quote_reserve),
    ):
        _u64(value, name)
    _i128(virtual_quote_reserve, "virtual_quote_reserve")
    effective_quote = raw_quote_reserve + virtual_quote_reserve
    if effective_quote <= 0:
        raise ProtocolQuoteRefusal("nonpositive_effective_quote_reserve")
    atoms(effective_quote, name="effective quote reserve")
    if base_in == 0:
        raise ProtocolQuoteRefusal("zero_size")
    raw = _u64(mul_div_floor(effective_quote, base_in, base_reserve + base_in), "raw_quote")
    lp_fee, protocol_fee, creator_fee = fees.components(raw)
    if raw - lp_fee > raw_quote_reserve:
        raise ProtocolQuoteRefusal("insufficient_real_quote")
    output = raw - lp_fee - protocol_fee - creator_fee
    if output < 0:
        raise ProtocolQuoteRefusal("fees_exceed_raw_output")
    return ProtocolQuote(
        input_atoms=base_in,
        output_atoms=output,
        raw_quote_atoms=raw,
        lp_fee_atoms=lp_fee,
        protocol_fee_atoms=protocol_fee,
        creator_fee_atoms=creator_fee,
    )
