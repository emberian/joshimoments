"""Exact Pump/PumpSwap/DLMM fixture battery for the Wave 6 N01 gate.

The battery independently recomputes a bounded set of arithmetic boundaries from the exact
checked protocol fixtures already consumed by the Rust kernels. It performs no source query,
store read, quote request, liquidity action, market inference, or economic evaluation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes
from ..errors import ManifestError

PROTOCOL_BATTERY_SCHEMA = "joshi.analysis.wave6-protocol-known-truth/v1"
PROTOCOL_BATTERY_AUTHORITY = "fixture_protocol_arithmetic_only_no_market_or_economic_claim"
PUMP_FIXTURE_DIGEST = "sha256:47837451236ec38eaffa78521d4fc6aa8ffb44d69136a19a0b532d1ad20c29df"
DLMM_FIXTURE_DIGEST = "sha256:a84a22100cfa790aaf37b649bd7db359b3f21afd2a82d2c0074a9cf3cc11e1c8"


class ProtocolAdversaryKind(StrEnum):
    """Frozen protocol arithmetic/refusal boundaries."""

    PUMP_LITERAL_FLOOR_PLUS_ONE = "pump_literal_floor_plus_one"
    PUMP_SEPARATE_FEE_ROUNDING = "pump_separate_fee_rounding"
    PUMPSWAP_REAL_CAPACITY = "pumpswap_real_capacity"
    PUMPSWAP_LP_RETENTION = "pumpswap_lp_retention"
    DLMM_POSITION_SHARE_FLOOR = "dlmm_position_share_floor"
    DLMM_DEPOSIT_SHARE_FLOOR = "dlmm_deposit_share_floor"
    DLMM_REMOVAL_AND_CLAIMS = "dlmm_removal_and_claims"


class ProtocolCaseDisposition(StrEnum):
    EXACT_RECOVERY = "exact_recovery"
    TYPED_REFUSAL = "typed_refusal"


def _stable(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _strict_int(value: Any, field: str, *, bits: int, signed: bool = False) -> int:
    if not isinstance(value, str) or not value.isascii():
        raise ManifestError(f"{field} must be a canonical decimal string")
    if value == "0":
        parsed = 0
    else:
        digits = value.removeprefix("-") if signed else value
        if (
            not digits
            or digits.startswith("0")
            or not digits.isdigit()
            or (not signed and value.startswith("-"))
            or value == "-0"
        ):
            raise ManifestError(f"{field} must be a canonical decimal string")
        parsed = int(value)
    lower = -(2 ** (bits - 1)) if signed else 0
    upper = 2 ** (bits - int(signed)) - 1
    if not lower <= parsed <= upper:
        raise ManifestError(f"{field} exceeds its exact {bits}-bit carrier")
    return parsed


def _strict_python_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{field} must be an exact integer")
    return value


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ManifestError(
            "ceil division requires a nonnegative numerator and positive denominator"
        )
    return (numerator + denominator - 1) // denominator


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate fixture JSON key: {key}")
        result[key] = value
    return result


def _load_pinned_fixture(exact_bytes: bytes, expected_digest: str, contract: str) -> dict[str, Any]:
    if qualified_sha256_bytes(exact_bytes) != expected_digest:
        raise ManifestError("protocol fixture bytes differ from the frozen N01 digest")
    try:
        document = json.loads(exact_bytes, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError("protocol fixture is not strict UTF-8 JSON") from error
    if not isinstance(document, dict) or document.get("contract") != contract:
        raise ManifestError("protocol fixture contract differs from the frozen N01 family")
    return document


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ManifestError(f"{field} fields differ from the exact fixture contract")


def _vector_by_id(vectors: Any, vector_id: str, field: str) -> dict[str, Any]:
    if not isinstance(vectors, list) or any(not isinstance(row, dict) for row in vectors):
        raise ManifestError(f"{field} must be a list of objects")
    ids = [row.get("id") for row in vectors]
    if len(ids) != len(set(ids)):
        raise ManifestError(f"{field} contains duplicate vector IDs")
    matches = [row for row in vectors if row.get("id") == vector_id]
    if len(matches) != 1:
        raise ManifestError(f"{field} does not contain exactly one {vector_id}")
    return matches[0]


_PUMP_INPUT_KEYS = {
    "id",
    "provenance",
    "venue",
    "virtual_base_reserves",
    "virtual_quote_reserves",
    "real_base_reserves",
    "real_quote_reserves",
    "base_mint_supply",
    "raw_quote_reserves",
    "virtual_quote_reserves_signed",
    "lp_bps",
    "protocol_bps",
    "creator_mode",
    "creator_bps",
    "size_kind",
    "size_atoms",
}
_PUMP_EXPECTED_KEYS = {
    "raw_quote_atoms",
    "lp_fee_atoms",
    "protocol_fee_atoms",
    "creator_fee_atoms",
    "input_atoms",
    "output_atoms",
}
_DLMM_POSITION_KEYS = {
    "id",
    "provenance",
    "bin_id",
    "bin_step",
    "price_q64",
    "pool_x_atoms",
    "pool_y_atoms",
    "liquidity_supply",
    "position_share",
    "expected_position_x_atoms",
    "expected_position_y_atoms",
    "deposit_x_atoms",
    "deposit_y_atoms",
    "expected_deposit_share",
    "remove_bps",
    "expected_removed_share",
    "expected_removed_x_atoms",
    "expected_removed_y_atoms",
    "pending_fee_x_atoms",
    "pending_fee_y_atoms",
    "pending_reward_atoms",
}


def _pump_success(row: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    _exact_keys(row, _PUMP_INPUT_KEYS | {"expected"}, f"Pump vector {row.get('id')}")
    if row.get("provenance") != "synthetic_boundary":
        raise ManifestError("N01 Pump vector must be an explicit synthetic boundary")
    expected = row["expected"]
    if not isinstance(expected, dict):
        raise ManifestError("Pump expected output must be one object")
    _exact_keys(expected, _PUMP_EXPECTED_KEYS, "Pump expected output")
    inputs = {
        key: _strict_int(
            row[key],
            f"Pump {key}",
            bits=128 if key == "virtual_quote_reserves_signed" else 64,
            signed=key == "virtual_quote_reserves_signed",
        )
        for key in (
            "virtual_base_reserves",
            "virtual_quote_reserves",
            "real_base_reserves",
            "real_quote_reserves",
            "raw_quote_reserves",
            "virtual_quote_reserves_signed",
            "lp_bps",
            "protocol_bps",
            "creator_bps",
            "size_atoms",
        )
    }
    outputs = {
        key: _strict_int(value, f"Pump expected {key}", bits=64)
        for key, value in expected.items()
    }
    return inputs, outputs


def _pump_refusal(row: dict[str, Any]) -> tuple[dict[str, int], str]:
    _exact_keys(row, _PUMP_INPUT_KEYS | {"refusal"}, f"Pump vector {row.get('id')}")
    if row.get("provenance") != "synthetic_boundary":
        raise ManifestError("N01 Pump vector must be an explicit synthetic boundary")
    inputs = {
        key: _strict_int(
            row[key],
            f"Pump {key}",
            bits=128 if key == "virtual_quote_reserves_signed" else 64,
            signed=key == "virtual_quote_reserves_signed",
        )
        for key in (
            "real_base_reserves",
            "raw_quote_reserves",
            "virtual_quote_reserves_signed",
            "lp_bps",
            "protocol_bps",
            "creator_bps",
            "size_atoms",
        )
    }
    return inputs, _stable(row["refusal"], "Pump refusal")


def _case_digest_material(case: ProtocolTruthCase) -> dict[str, Any]:
    return {
        "schema_id": PROTOCOL_BATTERY_SCHEMA,
        "case_id": case.case_id,
        "adversary": case.adversary.value,
        "fixture_ids": list(case.fixture_ids),
        "disposition": case.disposition.value,
        "exact_outputs": [[key, str(value)] for key, value in case.exact_outputs],
        "refusal_reason": case.refusal_reason,
        "negative_control_id": case.negative_control_id,
        "falsifier": case.falsifier,
        "authority": PROTOCOL_BATTERY_AUTHORITY,
    }


@dataclass(frozen=True, slots=True)
class ProtocolTruthCase:
    case_id: str
    adversary: ProtocolAdversaryKind
    fixture_ids: tuple[str, ...]
    disposition: ProtocolCaseDisposition
    exact_outputs: tuple[tuple[str, int], ...]
    refusal_reason: str | None
    negative_control_id: str
    falsifier: str
    truth_digest: str

    def __post_init__(self) -> None:
        for field, value in (
            ("case_id", self.case_id),
            ("negative_control_id", self.negative_control_id),
            ("falsifier", self.falsifier),
        ):
            _stable(value, field)
        if self.fixture_ids != tuple(sorted(set(self.fixture_ids))) or not self.fixture_ids:
            raise ManifestError("protocol fixture IDs must be sorted, unique, and nonempty")
        output_keys = tuple(key for key, _ in self.exact_outputs)
        if output_keys != tuple(sorted(set(output_keys))):
            raise ManifestError("protocol output keys must be sorted and unique")
        for key, value in self.exact_outputs:
            _stable(key, "protocol output key")
            _strict_python_int(value, "protocol output value")
        if (self.disposition == ProtocolCaseDisposition.TYPED_REFUSAL) != (
            self.refusal_reason is not None
        ):
            raise ManifestError("protocol refusal disposition and reason must agree")
        if self.refusal_reason is not None:
            _stable(self.refusal_reason, "protocol refusal")
        expected = qualified_sha256_bytes(canonical_json_bytes(_case_digest_material(self)))
        if self.truth_digest != expected:
            raise ManifestError("protocol truth case digest mismatch")

    @classmethod
    def build(
        cls,
        case_id: str,
        adversary: ProtocolAdversaryKind,
        fixture_ids: tuple[str, ...],
        disposition: ProtocolCaseDisposition,
        exact_outputs: tuple[tuple[str, int], ...],
        refusal_reason: str | None,
        negative_control_id: str,
        falsifier: str,
    ) -> ProtocolTruthCase:
        provisional = cls.__new__(cls)
        for field, value in (
            ("case_id", case_id),
            ("adversary", adversary),
            ("fixture_ids", fixture_ids),
            ("disposition", disposition),
            ("exact_outputs", exact_outputs),
            ("refusal_reason", refusal_reason),
            ("negative_control_id", negative_control_id),
            ("falsifier", falsifier),
        ):
            object.__setattr__(provisional, field, value)
        object.__setattr__(provisional, "truth_digest", "sha256:" + "0" * 64)
        truth_digest = qualified_sha256_bytes(
            canonical_json_bytes(_case_digest_material(provisional))
        )
        return cls(
            case_id,
            adversary,
            fixture_ids,
            disposition,
            exact_outputs,
            refusal_reason,
            negative_control_id,
            falsifier,
            truth_digest,
        )


@dataclass(frozen=True, slots=True)
class ProtocolKnownTruthBattery:
    suite_id: str
    pump_fixture_digest: str
    dlmm_fixture_digest: str
    cases: tuple[ProtocolTruthCase, ...]
    authority: str = PROTOCOL_BATTERY_AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "protocol suite_id")
        if (
            self.pump_fixture_digest != PUMP_FIXTURE_DIGEST
            or self.dlmm_fixture_digest != DLMM_FIXTURE_DIGEST
            or self.authority != PROTOCOL_BATTERY_AUTHORITY
        ):
            raise ManifestError("protocol suite changed fixture or authority boundary")
        if tuple(case.case_id for case in self.cases) != tuple(
            sorted({case.case_id for case in self.cases})
        ) or len(self.cases) != len(ProtocolAdversaryKind) or {
            case.adversary for case in self.cases
        } != set(ProtocolAdversaryKind):
            raise ManifestError("protocol suite must close every adversary exactly once")

    @property
    def suite_digest(self) -> str:
        return qualified_sha256_bytes(
            canonical_json_bytes(
                {
                    "schema_id": PROTOCOL_BATTERY_SCHEMA,
                    "suite_id": self.suite_id,
                    "pump_fixture_digest": self.pump_fixture_digest,
                    "dlmm_fixture_digest": self.dlmm_fixture_digest,
                    "truth_digests": [case.truth_digest for case in self.cases],
                    "authority": self.authority,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ProtocolCandidateResult:
    case_id: str
    truth_digest: str
    disposition: ProtocolCaseDisposition
    exact_outputs: tuple[tuple[str, int], ...]
    refusal_reason: str | None
    authority: str
    result_digest: str

    def __post_init__(self) -> None:
        _stable(self.case_id, "protocol candidate case_id")
        _stable(self.authority, "protocol candidate authority")
        output_keys = tuple(key for key, _ in self.exact_outputs)
        if output_keys != tuple(sorted(set(output_keys))):
            raise ManifestError("protocol candidate output keys must be sorted and unique")
        for key, value in self.exact_outputs:
            _stable(key, "protocol candidate output key")
            _strict_python_int(value, "protocol candidate output value")
        if (self.disposition == ProtocolCaseDisposition.TYPED_REFUSAL) != (
            self.refusal_reason is not None
        ):
            raise ManifestError("protocol candidate refusal disposition and reason must agree")
        if self.refusal_reason is not None:
            _stable(self.refusal_reason, "protocol candidate refusal")

    @classmethod
    def build(
        cls,
        case: ProtocolTruthCase,
        *,
        exact_outputs: tuple[tuple[str, int], ...] | None = None,
        refusal_reason: str | object | None = ...,
    ) -> ProtocolCandidateResult:
        outputs = case.exact_outputs if exact_outputs is None else exact_outputs
        refusal = case.refusal_reason if refusal_reason is ... else refusal_reason
        material = {
            "schema_id": PROTOCOL_BATTERY_SCHEMA,
            "case_id": case.case_id,
            "truth_digest": case.truth_digest,
            "disposition": case.disposition.value,
            "exact_outputs": [[key, str(value)] for key, value in outputs],
            "refusal_reason": refusal,
            "authority": PROTOCOL_BATTERY_AUTHORITY,
        }
        return cls(
            case.case_id,
            case.truth_digest,
            case.disposition,
            outputs,
            refusal,
            PROTOCOL_BATTERY_AUTHORITY,
            qualified_sha256_bytes(canonical_json_bytes(material)),
        )


@dataclass(frozen=True, slots=True)
class ProtocolBatteryEvaluation:
    suite_id: str
    suite_digest: str
    pump_fixture_digest: str
    dlmm_fixture_digest: str
    candidate_id: str
    passed_case_ids: tuple[str, ...]
    result_digests: tuple[str, ...]
    evaluation_digest: str
    authority: str = PROTOCOL_BATTERY_AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "protocol evaluation suite_id")
        _stable(self.candidate_id, "protocol evaluation candidate_id")
        if self.passed_case_ids != tuple(sorted(set(self.passed_case_ids))) or not (
            self.passed_case_ids
        ):
            raise ManifestError("protocol passed case IDs must be sorted, unique, and nonempty")
        for case_id in self.passed_case_ids:
            _stable(case_id, "protocol passed case ID")
        if len(self.result_digests) != len(self.passed_case_ids):
            raise ManifestError("protocol evaluation must bind one result digest per passed case")
        for field, digest in (
            ("protocol suite digest", self.suite_digest),
            ("protocol Pump fixture digest", self.pump_fixture_digest),
            ("protocol DLMM fixture digest", self.dlmm_fixture_digest),
            ("protocol evaluation digest", self.evaluation_digest),
        ):
            _qualified_digest(digest, field)
        for digest in self.result_digests:
            _qualified_digest(digest, "protocol result digest")
        if (
            self.pump_fixture_digest != PUMP_FIXTURE_DIGEST
            or self.dlmm_fixture_digest != DLMM_FIXTURE_DIGEST
            or self.authority != PROTOCOL_BATTERY_AUTHORITY
        ):
            raise ManifestError("protocol evaluation changed fixture or authority boundary")
        if self.evaluation_digest != qualified_sha256_bytes(
            canonical_json_bytes(_evaluation_material(self))
        ):
            raise ManifestError("protocol evaluation self-digest mismatch")

    def as_dict(self) -> dict[str, Any]:
        """Return the exact registered protocol-evaluation artifact fields."""

        return {
            "suite_id": self.suite_id,
            "suite_digest": self.suite_digest,
            "pump_fixture_digest": self.pump_fixture_digest,
            "dlmm_fixture_digest": self.dlmm_fixture_digest,
            "candidate_id": self.candidate_id,
            "passed_case_ids": list(self.passed_case_ids),
            "result_digests": list(self.result_digests),
            "evaluation_digest": self.evaluation_digest,
            "authority": self.authority,
        }

    def exact_bytes(self) -> bytes:
        """Serialize the exact canonical checked-artifact representation."""

        return canonical_json_bytes(self.as_dict(), newline=True)


def _qualified_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ManifestError(f"{field} must be sha256:<64 lowercase hex>")
    return value


def _evaluation_material(evaluation: ProtocolBatteryEvaluation) -> dict[str, Any]:
    return {
        "schema_id": PROTOCOL_BATTERY_SCHEMA,
        "suite_id": evaluation.suite_id,
        "suite_digest": evaluation.suite_digest,
        "pump_fixture_digest": evaluation.pump_fixture_digest,
        "dlmm_fixture_digest": evaluation.dlmm_fixture_digest,
        "candidate_id": evaluation.candidate_id,
        "passed_case_ids": list(evaluation.passed_case_ids),
        "result_digests": list(evaluation.result_digests),
        "authority": evaluation.authority,
    }


def _candidate_material(result: ProtocolCandidateResult) -> dict[str, Any]:
    return {
        "schema_id": PROTOCOL_BATTERY_SCHEMA,
        "case_id": result.case_id,
        "truth_digest": result.truth_digest,
        "disposition": result.disposition.value,
        "exact_outputs": [[key, str(value)] for key, value in result.exact_outputs],
        "refusal_reason": result.refusal_reason,
        "authority": result.authority,
    }


def validate_protocol_candidate_result(
    case: ProtocolTruthCase, result: ProtocolCandidateResult
) -> None:
    """Require exact identity, arithmetic/refusal content, authority, and result digest."""

    # Revalidate exact carriers before equality because Python booleans compare equal to 0/1.
    for key, value in result.exact_outputs:
        _stable(key, "protocol candidate output key")
        _strict_python_int(value, "protocol candidate output value")
    if (
        result.case_id != case.case_id
        or result.truth_digest != case.truth_digest
        or result.disposition != case.disposition
        or result.exact_outputs != case.exact_outputs
        or result.refusal_reason != case.refusal_reason
        or result.authority != PROTOCOL_BATTERY_AUTHORITY
    ):
        raise ManifestError("protocol candidate differs from exact generated truth")
    if result.result_digest != qualified_sha256_bytes(
        canonical_json_bytes(_candidate_material(result))
    ):
        raise ManifestError("protocol candidate result digest mismatch")


def evaluate_protocol_candidate(
    battery: ProtocolKnownTruthBattery,
    candidate_id: str,
    results: tuple[ProtocolCandidateResult, ...],
) -> ProtocolBatteryEvaluation:
    """Require one exact passing candidate row for every protocol adversary."""

    _stable(candidate_id, "protocol candidate_id")
    by_id = {result.case_id: result for result in results}
    if len(by_id) != len(results) or set(by_id) != {case.case_id for case in battery.cases}:
        raise ManifestError("protocol candidate must report every case exactly once")
    for case in battery.cases:
        validate_protocol_candidate_result(case, by_id[case.case_id])
    passed = tuple(case.case_id for case in battery.cases)
    result_digests = tuple(by_id[case_id].result_digest for case_id in passed)
    provisional = ProtocolBatteryEvaluation.__new__(ProtocolBatteryEvaluation)
    for field, value in (
        ("suite_id", battery.suite_id),
        ("suite_digest", battery.suite_digest),
        ("pump_fixture_digest", battery.pump_fixture_digest),
        ("dlmm_fixture_digest", battery.dlmm_fixture_digest),
        ("candidate_id", candidate_id),
        ("passed_case_ids", passed),
        ("result_digests", result_digests),
        ("authority", PROTOCOL_BATTERY_AUTHORITY),
    ):
        object.__setattr__(provisional, field, value)
    object.__setattr__(provisional, "evaluation_digest", "sha256:" + "0" * 64)
    digest = qualified_sha256_bytes(canonical_json_bytes(_evaluation_material(provisional)))
    return ProtocolBatteryEvaluation(
        battery.suite_id,
        battery.suite_digest,
        battery.pump_fixture_digest,
        battery.dlmm_fixture_digest,
        candidate_id,
        passed,
        result_digests,
        digest,
    )


def build_protocol_known_truth_battery(
    pump_fixture_bytes: bytes, dlmm_fixture_bytes: bytes
) -> ProtocolKnownTruthBattery:
    """Recompute the frozen Pump/PumpSwap/DLMM boundary truths."""

    pump = _load_pinned_fixture(
        pump_fixture_bytes, PUMP_FIXTURE_DIGEST, "joshi.protocol-fixtures.pump.v1"
    )
    dlmm = _load_pinned_fixture(
        dlmm_fixture_bytes, DLMM_FIXTURE_DIGEST, "joshi.protocol-fixtures.dlmm.v1"
    )
    quote_vectors = pump.get("quote_vectors")
    literal = _vector_by_id(
        quote_vectors, "curve_buy_exact_division_still_adds_one", "Pump quote vectors"
    )
    literal_inputs, literal_expected = _pump_success(literal)
    if literal.get("venue") != "pump_curve" or literal.get("size_kind") != "exact_base_out_buy":
        raise ManifestError("literal-plus-one vector changed venue or size kind")
    numerator = literal_inputs["size_atoms"] * literal_inputs["virtual_quote_reserves"]
    denominator = literal_inputs["virtual_base_reserves"] - literal_inputs["size_atoms"]
    floor_quotient = numerator // denominator
    mathematical_ceil = _ceil_div(numerator, denominator)
    literal_raw = floor_quotient + 1
    if literal_raw != literal_expected["raw_quote_atoms"] or mathematical_ceil == literal_raw:
        raise ManifestError("Pump literal floor-plus-one truth changed")

    component_fees = {
        "creator_fee_atoms": _ceil_div(
            literal_raw * literal_inputs["creator_bps"], 10_000
        ),
        "lp_fee_atoms": _ceil_div(literal_raw * literal_inputs["lp_bps"], 10_000),
        "protocol_fee_atoms": _ceil_div(
            literal_raw * literal_inputs["protocol_bps"], 10_000
        ),
    }
    combined_fee = _ceil_div(
        literal_raw
        * (
            literal_inputs["lp_bps"]
            + literal_inputs["protocol_bps"]
            + literal_inputs["creator_bps"]
        ),
        10_000,
    )
    if any(literal_expected[key] != value for key, value in component_fees.items()) or sum(
        component_fees.values()
    ) == combined_fee:
        raise ManifestError("Pump independently rounded component-fee truth changed")
    if literal_expected["input_atoms"] != literal_raw + sum(component_fees.values()):
        raise ManifestError("Pump exact input closure changed")

    capacity = _vector_by_id(
        quote_vectors,
        "positive_virtual_reserve_cannot_fake_payout_capacity",
        "Pump quote vectors",
    )
    capacity_inputs, capacity_refusal = _pump_refusal(capacity)
    if capacity.get("venue") != "pumpswap_canonical" or capacity.get("size_kind") != (
        "exact_base_in_sell"
    ):
        raise ManifestError("PumpSwap capacity vector changed venue or size kind")
    capacity_effective = (
        capacity_inputs["raw_quote_reserves"]
        + capacity_inputs["virtual_quote_reserves_signed"]
    )
    capacity_raw = (
        capacity_effective
        * capacity_inputs["size_atoms"]
        // (capacity_inputs["real_base_reserves"] + capacity_inputs["size_atoms"])
    )
    capacity_lp = _ceil_div(capacity_raw * capacity_inputs["lp_bps"], 10_000)
    capacity_vault_debit = capacity_raw - capacity_lp
    if (
        capacity_effective <= 0
        or capacity_vault_debit <= capacity_inputs["raw_quote_reserves"]
        or capacity_refusal != "insufficient_real_quote"
    ):
        raise ManifestError("PumpSwap real-capacity refusal truth changed")

    retention = _vector_by_id(
        quote_vectors, "pumpswap_real_capacity_retains_lp_fee", "Pump quote vectors"
    )
    retention_inputs, retention_expected = _pump_success(retention)
    retention_effective = (
        retention_inputs["raw_quote_reserves"]
        + retention_inputs["virtual_quote_reserves_signed"]
    )
    retention_raw = (
        retention_effective
        * retention_inputs["size_atoms"]
        // (retention_inputs["real_base_reserves"] + retention_inputs["size_atoms"])
    )
    retention_lp = _ceil_div(retention_raw * retention_inputs["lp_bps"], 10_000)
    retention_vault_debit = retention_raw - retention_lp
    if (
        retention_raw != retention_expected["raw_quote_atoms"]
        or retention_lp != retention_expected["lp_fee_atoms"]
        or retention_vault_debit > retention_inputs["raw_quote_reserves"]
        or retention_expected["output_atoms"] != retention_vault_debit
    ):
        raise ManifestError("PumpSwap LP-retained capacity truth changed")

    position = _vector_by_id(
        dlmm.get("position_vectors"), "single_bin_quarter_share", "DLMM position vectors"
    )
    _exact_keys(position, _DLMM_POSITION_KEYS, "DLMM position vector")
    if position.get("provenance") != "synthetic_boundary":
        raise ManifestError("N01 DLMM vector must be an explicit synthetic boundary")
    values = {
        key: _strict_int(value, f"DLMM {key}", bits=128)
        for key, value in position.items()
        if key not in {"id", "provenance", "bin_id"}
    }
    _strict_int(position["bin_id"], "DLMM bin_id", bits=32, signed=True)
    supply = values["liquidity_supply"]
    share = values["position_share"]
    position_x = values["pool_x_atoms"] * share // supply
    position_y = values["pool_y_atoms"] * share // supply
    if (
        position_x != values["expected_position_x_atoms"]
        or position_y != values["expected_position_y_atoms"]
    ):
        raise ManifestError("DLMM position share floor truth changed")

    q64 = 1 << 64
    existing_liquidity = (
        values["price_q64"] * values["pool_x_atoms"] + values["pool_y_atoms"] * q64
    )
    incoming_liquidity = (
        values["price_q64"] * values["deposit_x_atoms"] + values["deposit_y_atoms"] * q64
    )
    deposit_share = incoming_liquidity * supply // existing_liquidity
    if deposit_share != values["expected_deposit_share"]:
        raise ManifestError("DLMM deposit share floor truth changed")

    removed_share = share * values["remove_bps"] // 10_000
    removed_x = values["pool_x_atoms"] * removed_share // supply
    removed_y = values["pool_y_atoms"] * removed_share // supply
    if (
        removed_share != values["expected_removed_share"]
        or removed_x != values["expected_removed_x_atoms"]
        or removed_y != values["expected_removed_y_atoms"]
    ):
        raise ManifestError("DLMM removal share truth changed")

    cases = (
        ProtocolTruthCase.build(
            "protocol-case-01-pump-literal-plus-one",
            ProtocolAdversaryKind.PUMP_LITERAL_FLOOR_PLUS_ONE,
            (literal["id"],),
            ProtocolCaseDisposition.EXACT_RECOVERY,
            (
                ("floor_quotient", floor_quotient),
                ("literal_floor_plus_one", literal_raw),
                ("mathematical_ceil", mathematical_ceil),
            ),
            None,
            "negative_replace_literal_plus_one_with_ceil",
            "an exact quotient no longer receives the protocol literal plus one",
        ),
        ProtocolTruthCase.build(
            "protocol-case-02-pump-separate-fees",
            ProtocolAdversaryKind.PUMP_SEPARATE_FEE_ROUNDING,
            (literal["id"],),
            ProtocolCaseDisposition.EXACT_RECOVERY,
            (
                ("combined_fee_shortcut", combined_fee),
                ("creator_fee_atoms", component_fees["creator_fee_atoms"]),
                ("independent_fee_total", sum(component_fees.values())),
                ("lp_fee_atoms", component_fees["lp_fee_atoms"]),
                ("protocol_fee_atoms", component_fees["protocol_fee_atoms"]),
            ),
            None,
            "negative_round_combined_fee_once",
            "separately rounded fee components collapse into one combined rounding",
        ),
        ProtocolTruthCase.build(
            "protocol-case-03-pumpswap-real-capacity",
            ProtocolAdversaryKind.PUMPSWAP_REAL_CAPACITY,
            (capacity["id"],),
            ProtocolCaseDisposition.TYPED_REFUSAL,
            (
                ("effective_quote_reserves", capacity_effective),
                ("raw_quote_atoms", capacity_raw),
                ("real_quote_reserves", capacity_inputs["raw_quote_reserves"]),
                ("vault_debit_atoms", capacity_vault_debit),
            ),
            capacity_refusal,
            "negative_treat_virtual_reserve_as_payout_capacity",
            "positive virtual reserve permits payout beyond the real quote vault",
        ),
        ProtocolTruthCase.build(
            "protocol-case-04-pumpswap-lp-retention",
            ProtocolAdversaryKind.PUMPSWAP_LP_RETENTION,
            (retention["id"],),
            ProtocolCaseDisposition.EXACT_RECOVERY,
            (
                ("lp_fee_atoms", retention_lp),
                ("raw_quote_atoms", retention_raw),
                ("real_quote_reserves", retention_inputs["raw_quote_reserves"]),
                ("vault_debit_atoms", retention_vault_debit),
            ),
            None,
            "negative_compare_raw_payout_to_real_vault",
            "a valid quote is refused before accounting for the retained LP fee",
        ),
        ProtocolTruthCase.build(
            "protocol-case-05-dlmm-position-share",
            ProtocolAdversaryKind.DLMM_POSITION_SHARE_FLOOR,
            (position["id"],),
            ProtocolCaseDisposition.EXACT_RECOVERY,
            (("position_x_atoms", position_x), ("position_y_atoms", position_y)),
            None,
            "negative_float_or_round_up_position_share",
            "per-bin position inventory differs from exact floor allocation",
        ),
        ProtocolTruthCase.build(
            "protocol-case-06-dlmm-deposit-share",
            ProtocolAdversaryKind.DLMM_DEPOSIT_SHARE_FLOOR,
            (position["id"],),
            ProtocolCaseDisposition.EXACT_RECOVERY,
            (
                ("deposit_share", deposit_share),
                ("existing_liquidity_q64", existing_liquidity),
                ("incoming_liquidity_q64", incoming_liquidity),
            ),
            None,
            "negative_narrow_q64_before_share_projection",
            "wide Q64 liquidity or floor division narrows before deposit-share projection",
        ),
        ProtocolTruthCase.build(
            "protocol-case-07-dlmm-removal-claims",
            ProtocolAdversaryKind.DLMM_REMOVAL_AND_CLAIMS,
            (position["id"],),
            ProtocolCaseDisposition.EXACT_RECOVERY,
            (
                ("pending_fee_x_atoms_separate", values["pending_fee_x_atoms"]),
                ("pending_fee_y_atoms_separate", values["pending_fee_y_atoms"]),
                ("pending_reward_atoms_separate", values["pending_reward_atoms"]),
                ("removed_share", removed_share),
                ("removed_x_atoms", removed_x),
                ("removed_y_atoms", removed_y),
            ),
            None,
            "negative_add_claims_to_principal_or_round_removal_up",
            "pending claims enter principal or removal share stops using exact floor arithmetic",
        ),
    )
    return ProtocolKnownTruthBattery(
        "wave6-protocol-known-truth-pump-dlmm-v1",
        PUMP_FIXTURE_DIGEST,
        DLMM_FIXTURE_DIGEST,
        cases,
    )
