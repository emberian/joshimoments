"""Fixture-only migration, ordering, and identity-revision known-truth battery.

The battery recomputes three structural adversaries from one exact checked-in fixture. It does not
resolve a real lifecycle, transaction order, wallet identity, source occurrence, market state, or
store receipt. In particular, an identity label here is a synthetic fixture symbol, never a claim
that two real accounts share a controller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import permutations
from typing import Any

from ..canonical import canonical_json_bytes, iso_utc, qualified_sha256_bytes
from ..errors import ManifestError

STRUCTURAL_FIXTURE_CONTRACT = "joshi.wave6.structural-known-truth-fixture.v1"
STRUCTURAL_BATTERY_SCHEMA = "joshi.analysis.wave6-structural-known-truth/v1"
STRUCTURAL_BATTERY_AUTHORITY = (
    "fixture_structural_transition_only_no_identity_market_causal_or_economic_claim"
)
STRUCTURAL_FIXTURE_DIGEST = (
    "sha256:806bf5668a0de0f113677f5aad6947074cb463aa1dc9776794e22a2b491be154"
)
_FIXTURE_AUTHORITY = "fixture_only_no_identity_market_causal_or_economic_claim"


class StructuralAdversaryKind(StrEnum):
    """Frozen structural transition/refusal families."""

    MIGRATION_SPLICE = "migration_splice"
    SAME_SLOT_REORDER = "same_slot_reorder"
    IDENTITY_REVISION = "identity_revision"


class StructuralValueKind(StrEnum):
    """Closed wire carriers used by a structural expected output."""

    DECIMAL_INTEGER = "decimal_integer"
    IDENTIFIER = "identifier"
    SHA256 = "sha256"
    DISPOSITION = "disposition"


def _stable(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _decimal(value: Any, field: str, *, signed: bool = False) -> int:
    if not isinstance(value, str) or not value.isascii():
        raise ManifestError(f"{field} must be a canonical decimal string")
    digits = value.removeprefix("-") if signed else value
    if (
        not digits
        or not digits.isdigit()
        or (len(digits) > 1 and digits.startswith("0"))
        or (not signed and value.startswith("-"))
        or value == "-0"
    ):
        raise ManifestError(f"{field} must be a canonical decimal string")
    parsed = int(value)
    if not signed and parsed < 0:
        raise ManifestError(f"{field} must be nonnegative")
    if parsed < -(2**127) or parsed > 2**128 - 1:
        raise ManifestError(f"{field} exceeds the fixture integer carrier")
    return parsed


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ManifestError(f"{field} must be canonical UTC") from error
    if parsed.tzinfo is None:
        raise ManifestError(f"{field} must be canonical UTC")
    normalized = parsed.astimezone(UTC)
    if iso_utc(normalized) != value:
        raise ManifestError(f"{field} must use exact microsecond UTC form")
    return normalized


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ManifestError(f"{field} fields differ from the exact fixture contract")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate structural fixture JSON key: {key}")
        result[key] = value
    return result


def _load_fixture(exact_bytes: bytes) -> dict[str, Any]:
    if qualified_sha256_bytes(exact_bytes) != STRUCTURAL_FIXTURE_DIGEST:
        raise ManifestError("structural fixture bytes differ from the frozen N01 digest")
    try:
        document = json.loads(exact_bytes, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError("structural fixture is not strict UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ManifestError("structural fixture must be one object")
    if canonical_json_bytes(document, newline=True) != exact_bytes:
        raise ManifestError("structural fixture is not exact canonical JSON")
    _exact_keys(document, {"authority", "contract", "scenarios"}, "structural fixture")
    if (
        document["contract"] != STRUCTURAL_FIXTURE_CONTRACT
        or document["authority"] != _FIXTURE_AUTHORITY
    ):
        raise ManifestError("structural fixture changed contract or authority")
    return document


def _scenario_by_id(document: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    scenarios = document["scenarios"]
    if not isinstance(scenarios, list) or any(not isinstance(row, dict) for row in scenarios):
        raise ManifestError("structural scenarios must be objects")
    ids = [row.get("id") for row in scenarios]
    if len(ids) != len(set(ids)) or set(ids) != {
        "identity-revision",
        "migration-splice",
        "same-slot-order",
    }:
        raise ManifestError("structural fixture must close each scenario exactly once")
    return next(row for row in scenarios if row["id"] == scenario_id)


def _output_material(output: StructuralOutput) -> dict[str, str]:
    return {"kind": output.kind.value, "name": output.name, "value": output.value}


@dataclass(frozen=True, slots=True)
class StructuralOutput:
    """One typed exact structural output."""

    name: str
    kind: StructuralValueKind
    value: str

    def __post_init__(self) -> None:
        _stable(self.name, "structural output name")
        if self.kind == StructuralValueKind.DECIMAL_INTEGER:
            _decimal(self.value, "structural decimal output", signed=True)
        elif self.kind in {StructuralValueKind.IDENTIFIER, StructuralValueKind.DISPOSITION}:
            _stable(self.value, "structural symbolic output")
        elif self.kind == StructuralValueKind.SHA256:
            if (
                not isinstance(self.value, str)
                or len(self.value) != 71
                or not self.value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in self.value[7:])
            ):
                raise ManifestError("structural digest output must be sha256:<64 lowercase hex>")
        else:  # pragma: no cover - defensive against an unsafe enum bypass
            raise ManifestError("unknown structural output carrier")


def _case_material(case: StructuralTruthCase) -> dict[str, Any]:
    return {
        "schema_id": STRUCTURAL_BATTERY_SCHEMA,
        "fixture_digest": STRUCTURAL_FIXTURE_DIGEST,
        "case_id": case.case_id,
        "adversary": case.adversary.value,
        "fixture_ids": list(case.fixture_ids),
        "exact_outputs": [_output_material(output) for output in case.exact_outputs],
        "negative_control_id": case.negative_control_id,
        "falsifier": case.falsifier,
        "authority": STRUCTURAL_BATTERY_AUTHORITY,
    }


@dataclass(frozen=True, slots=True)
class StructuralTruthCase:
    """One generated fixture truth with an exact typed output closure."""

    case_id: str
    adversary: StructuralAdversaryKind
    fixture_ids: tuple[str, ...]
    exact_outputs: tuple[StructuralOutput, ...]
    negative_control_id: str
    falsifier: str
    truth_digest: str

    def __post_init__(self) -> None:
        _stable(self.case_id, "structural case_id")
        _stable(self.negative_control_id, "structural negative control")
        _stable(self.falsifier, "structural falsifier")
        if self.fixture_ids != tuple(sorted(set(self.fixture_ids))) or not self.fixture_ids:
            raise ManifestError("structural fixture IDs must be sorted, unique, and nonempty")
        names = tuple(output.name for output in self.exact_outputs)
        if names != tuple(sorted(set(names))) or not names:
            raise ManifestError("structural outputs must be sorted, unique, and nonempty")
        if self.truth_digest != qualified_sha256_bytes(canonical_json_bytes(_case_material(self))):
            raise ManifestError("structural truth digest mismatch")

    @classmethod
    def build(
        cls,
        case_id: str,
        adversary: StructuralAdversaryKind,
        fixture_ids: tuple[str, ...],
        exact_outputs: tuple[StructuralOutput, ...],
        negative_control_id: str,
        falsifier: str,
    ) -> StructuralTruthCase:
        provisional = cls.__new__(cls)
        for field, value in (
            ("case_id", case_id),
            ("adversary", adversary),
            ("fixture_ids", fixture_ids),
            ("exact_outputs", exact_outputs),
            ("negative_control_id", negative_control_id),
            ("falsifier", falsifier),
        ):
            object.__setattr__(provisional, field, value)
        object.__setattr__(provisional, "truth_digest", "sha256:" + "0" * 64)
        digest = qualified_sha256_bytes(canonical_json_bytes(_case_material(provisional)))
        return cls(
            case_id,
            adversary,
            fixture_ids,
            exact_outputs,
            negative_control_id,
            falsifier,
            digest,
        )


@dataclass(frozen=True, slots=True)
class StructuralKnownTruthBattery:
    """Exact three-case structural N01 battery."""

    suite_id: str
    fixture_digest: str
    cases: tuple[StructuralTruthCase, ...]
    authority: str = STRUCTURAL_BATTERY_AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "structural suite_id")
        if (
            self.fixture_digest != STRUCTURAL_FIXTURE_DIGEST
            or self.authority != STRUCTURAL_BATTERY_AUTHORITY
        ):
            raise ManifestError("structural suite changed fixture or authority boundary")
        ids = tuple(case.case_id for case in self.cases)
        if (
            ids != tuple(sorted(set(ids)))
            or len(self.cases) != len(StructuralAdversaryKind)
            or {case.adversary for case in self.cases} != set(StructuralAdversaryKind)
        ):
            raise ManifestError("structural suite must close every adversary exactly once")

    @property
    def suite_digest(self) -> str:
        return qualified_sha256_bytes(
            canonical_json_bytes(
                {
                    "schema_id": STRUCTURAL_BATTERY_SCHEMA,
                    "suite_id": self.suite_id,
                    "fixture_digest": self.fixture_digest,
                    "truth_digests": [case.truth_digest for case in self.cases],
                    "authority": self.authority,
                }
            )
        )


def _candidate_material(result: StructuralCandidateResult) -> dict[str, Any]:
    return {
        "schema_id": STRUCTURAL_BATTERY_SCHEMA,
        "case_id": result.case_id,
        "truth_digest": result.truth_digest,
        "exact_outputs": [_output_material(output) for output in result.exact_outputs],
        "authority": result.authority,
    }


@dataclass(frozen=True, slots=True)
class StructuralCandidateResult:
    """One candidate's exact result for a structural fixture case."""

    case_id: str
    truth_digest: str
    exact_outputs: tuple[StructuralOutput, ...]
    authority: str
    result_digest: str

    def __post_init__(self) -> None:
        _stable(self.case_id, "structural candidate case_id")
        names = tuple(output.name for output in self.exact_outputs)
        if names != tuple(sorted(set(names))) or not names:
            raise ManifestError("structural candidate outputs must be sorted and unique")

    @classmethod
    def build(
        cls,
        case: StructuralTruthCase,
        *,
        exact_outputs: tuple[StructuralOutput, ...] | None = None,
    ) -> StructuralCandidateResult:
        outputs = case.exact_outputs if exact_outputs is None else exact_outputs
        provisional = cls(
            case.case_id,
            case.truth_digest,
            outputs,
            STRUCTURAL_BATTERY_AUTHORITY,
            "sha256:" + "0" * 64,
        )
        return cls(
            case.case_id,
            case.truth_digest,
            outputs,
            STRUCTURAL_BATTERY_AUTHORITY,
            qualified_sha256_bytes(canonical_json_bytes(_candidate_material(provisional))),
        )


@dataclass(frozen=True, slots=True)
class StructuralBatteryEvaluation:
    """Exact all-cases evaluation at fixture-only authority."""

    suite_id: str
    suite_digest: str
    fixture_digest: str
    candidate_id: str
    passed_case_ids: tuple[str, ...]
    result_digests: tuple[str, ...]
    evaluation_digest: str
    authority: str = STRUCTURAL_BATTERY_AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "structural evaluation suite_id")
        _stable(self.candidate_id, "structural evaluation candidate_id")
        if self.passed_case_ids != tuple(sorted(set(self.passed_case_ids))) or not (
            self.passed_case_ids
        ):
            raise ManifestError("structural passed case IDs must be sorted, unique, and nonempty")
        for case_id in self.passed_case_ids:
            _stable(case_id, "structural passed case ID")
        if len(self.result_digests) != len(self.passed_case_ids):
            raise ManifestError("structural evaluation must bind one result digest per passed case")
        for field, digest in (
            ("structural suite digest", self.suite_digest),
            ("structural fixture digest", self.fixture_digest),
            ("structural evaluation digest", self.evaluation_digest),
        ):
            _qualified_digest(digest, field)
        for digest in self.result_digests:
            _qualified_digest(digest, "structural result digest")
        if (
            self.fixture_digest != STRUCTURAL_FIXTURE_DIGEST
            or self.authority != STRUCTURAL_BATTERY_AUTHORITY
        ):
            raise ManifestError("structural evaluation changed fixture or authority boundary")
        if self.evaluation_digest != qualified_sha256_bytes(
            canonical_json_bytes(_evaluation_material(self))
        ):
            raise ManifestError("structural evaluation self-digest mismatch")

    def as_dict(self) -> dict[str, Any]:
        """Return the exact registered structural-evaluation artifact fields."""

        return {
            "suite_id": self.suite_id,
            "suite_digest": self.suite_digest,
            "fixture_digest": self.fixture_digest,
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


def _evaluation_material(evaluation: StructuralBatteryEvaluation) -> dict[str, Any]:
    return {
        "schema_id": STRUCTURAL_BATTERY_SCHEMA,
        "suite_id": evaluation.suite_id,
        "suite_digest": evaluation.suite_digest,
        "fixture_digest": evaluation.fixture_digest,
        "candidate_id": evaluation.candidate_id,
        "passed_case_ids": list(evaluation.passed_case_ids),
        "result_digests": list(evaluation.result_digests),
        "authority": evaluation.authority,
    }


def validate_structural_candidate_result(
    case: StructuralTruthCase, result: StructuralCandidateResult
) -> None:
    """Require exact typed outputs, truth identity, authority, and result digest."""

    for output in result.exact_outputs:
        output.__post_init__()
    if (
        result.case_id != case.case_id
        or result.truth_digest != case.truth_digest
        or result.exact_outputs != case.exact_outputs
        or result.authority != STRUCTURAL_BATTERY_AUTHORITY
    ):
        raise ManifestError("structural candidate differs from exact generated truth")
    if result.result_digest != qualified_sha256_bytes(
        canonical_json_bytes(_candidate_material(result))
    ):
        raise ManifestError("structural candidate result digest mismatch")


def evaluate_structural_candidate(
    battery: StructuralKnownTruthBattery,
    candidate_id: str,
    results: tuple[StructuralCandidateResult, ...],
) -> StructuralBatteryEvaluation:
    """Require exactly one passing candidate result for every structural adversary."""

    _stable(candidate_id, "structural candidate_id")
    by_id = {result.case_id: result for result in results}
    if len(by_id) != len(results) or set(by_id) != {case.case_id for case in battery.cases}:
        raise ManifestError("structural candidate must report every case exactly once")
    for case in battery.cases:
        validate_structural_candidate_result(case, by_id[case.case_id])
    passed = tuple(case.case_id for case in battery.cases)
    result_digests = tuple(by_id[case_id].result_digest for case_id in passed)
    provisional = StructuralBatteryEvaluation.__new__(StructuralBatteryEvaluation)
    for field, value in (
        ("suite_id", battery.suite_id),
        ("suite_digest", battery.suite_digest),
        ("fixture_digest", battery.fixture_digest),
        ("candidate_id", candidate_id),
        ("passed_case_ids", passed),
        ("result_digests", result_digests),
        ("authority", STRUCTURAL_BATTERY_AUTHORITY),
    ):
        object.__setattr__(provisional, field, value)
    object.__setattr__(provisional, "evaluation_digest", "sha256:" + "0" * 64)
    digest = qualified_sha256_bytes(canonical_json_bytes(_evaluation_material(provisional)))
    return StructuralBatteryEvaluation(
        battery.suite_id,
        battery.suite_digest,
        battery.fixture_digest,
        candidate_id,
        passed,
        result_digests,
        digest,
    )


def _migration_case(scenario: dict[str, Any]) -> StructuralTruthCase:
    _exact_keys(
        scenario,
        {"checkpoints", "expected", "id", "lifecycle", "mint_id"},
        "migration scenario",
    )
    mint_id = _stable(scenario["mint_id"], "migration mint_id")
    checkpoints = scenario["checkpoints"]
    if not isinstance(checkpoints, list) or len(checkpoints) != 4:
        raise ManifestError("migration scenario needs four checkpoints")
    by_id: dict[str, tuple[int, int, int, str, str]] = {}
    for row in checkpoints:
        if not isinstance(row, dict):
            raise ManifestError("migration checkpoint must be an object")
        _exact_keys(
            row,
            {
                "cumulative_quote_atoms",
                "event_id",
                "gauge",
                "slot",
                "transaction_index",
                "venue_epoch",
            },
            "migration checkpoint",
        )
        event_id = _stable(row["event_id"], "migration event_id")
        if event_id in by_id:
            raise ManifestError("migration checkpoint IDs must be unique")
        by_id[event_id] = (
            _decimal(row["slot"], "migration slot"),
            _decimal(row["transaction_index"], "migration transaction_index"),
            _decimal(row["cumulative_quote_atoms"], "migration cumulative atoms"),
            _stable(row["gauge"], "migration gauge"),
            _stable(row["venue_epoch"], "migration venue epoch"),
        )
    if set(by_id) != {"curve-before", "curve-final", "pool-after", "pool-origin"}:
        raise ManifestError("migration checkpoint closure changed")

    lifecycle = scenario["lifecycle"]
    if not isinstance(lifecycle, list) or len(lifecycle) != 2:
        raise ManifestError("migration scenario needs active and migrated lifecycle events")
    lifecycle_rows: list[tuple[int, int, str, str | None, str]] = []
    for row in lifecycle:
        if not isinstance(row, dict):
            raise ManifestError("migration lifecycle row must be an object")
        _exact_keys(
            row,
            {"event_id", "from_venue", "slot", "to_venue", "transaction_index"},
            "migration lifecycle",
        )
        from_venue = row["from_venue"]
        if from_venue is not None:
            from_venue = _stable(from_venue, "migration from venue")
        lifecycle_rows.append(
            (
                _decimal(row["slot"], "migration lifecycle slot"),
                _decimal(row["transaction_index"], "migration lifecycle transaction_index"),
                _stable(row["event_id"], "migration lifecycle event_id"),
                from_venue,
                _stable(row["to_venue"], "migration to venue"),
            )
        )
    lifecycle_rows.sort()
    if lifecycle_rows != [
        (99, 3, "lifecycle-curve-active", None, "pump_curve"),
        (100, 2, "lifecycle-migrated", "pump_curve", "pumpswap"),
    ]:
        raise ManifestError("migration lifecycle transition changed")
    curve_before = by_id["curve-before"]
    curve_final = by_id["curve-final"]
    pool_origin = by_id["pool-origin"]
    pool_after = by_id["pool-after"]
    if (
        (curve_before[0], curve_before[1]) <= lifecycle_rows[0][:2]
        or not (
            (curve_final[0], curve_final[1])
            < lifecycle_rows[1][:2]
            < (pool_origin[0], pool_origin[1])
            < (pool_after[0], pool_after[1])
        )
        or curve_before[3:] != ("pump_curve_cumulative_quote_atoms", "curve-v1")
        or curve_final[3:] != curve_before[3:]
        or pool_origin[3:] != ("pumpswap_cumulative_quote_atoms", "pool-v1")
        or pool_after[3:] != pool_origin[3:]
    ):
        raise ManifestError("migration splice clocks, gauges, or epochs changed")
    curve_delta = curve_final[2] - curve_before[2]
    pool_delta = pool_after[2] - pool_origin[2]
    spliced = curve_delta + pool_delta
    naive = pool_after[2] - curve_before[2]
    expected = scenario["expected"]
    if not isinstance(expected, dict):
        raise ManifestError("migration expected must be an object")
    _exact_keys(
        expected,
        {
            "curve_delta_quote_atoms",
            "naive_cross_gauge_delta_quote_atoms",
            "pool_delta_quote_atoms",
            "spliced_delta_quote_atoms",
        },
        "migration expected",
    )
    computed = {
        "curve_delta_quote_atoms": curve_delta,
        "naive_cross_gauge_delta_quote_atoms": naive,
        "pool_delta_quote_atoms": pool_delta,
        "spliced_delta_quote_atoms": spliced,
    }
    if any(
        _decimal(expected[key], f"migration expected {key}", signed=True) != value
        for key, value in computed.items()
    ):
        raise ManifestError("migration fixture expected output differs from exact splice")
    outputs = tuple(
        StructuralOutput(key, StructuralValueKind.DECIMAL_INTEGER, str(value))
        for key, value in sorted(computed.items())
    )
    return StructuralTruthCase.build(
        "structural-case-01-migration-splice",
        StructuralAdversaryKind.MIGRATION_SPLICE,
        tuple(sorted((*by_id, *(row[2] for row in lifecycle_rows), mint_id))),
        outputs,
        "negative_subtract_cumulative_values_across_venue_gauges",
        "a migration window is differenced across incompatible cumulative gauges",
    )


def _cpmm_order(
    events: tuple[tuple[str, int], ...], base_reserve: int, quote_reserve: int
) -> tuple[dict[str, int], int]:
    outputs: dict[str, int] = {}
    base = base_reserve
    quote = quote_reserve
    for event_id, delta in events:
        next_base = base + delta
        next_quote = base * quote // next_base
        output = quote - next_quote
        if output <= 0:
            raise ManifestError("same-slot fixture swap must have positive exact output")
        outputs[event_id] = output
        base, quote = next_base, next_quote
    return outputs, quote


def _order_digest(order: tuple[str, ...], outputs: dict[str, int], final_quote: int) -> str:
    return qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "order": list(order),
                "outputs": [[event_id, str(outputs[event_id])] for event_id in order],
                "final_quote_reserve_atoms": str(final_quote),
            }
        )
    )


def _same_slot_case(scenario: dict[str, Any]) -> StructuralTruthCase:
    _exact_keys(
        scenario,
        {
            "events",
            "expected",
            "id",
            "initial_base_reserve_atoms",
            "initial_quote_reserve_atoms",
            "pool_id",
        },
        "same-slot scenario",
    )
    pool_id = _stable(scenario["pool_id"], "same-slot pool_id")
    base = _decimal(scenario["initial_base_reserve_atoms"], "same-slot base reserve")
    quote = _decimal(scenario["initial_quote_reserve_atoms"], "same-slot quote reserve")
    if base == 0 or quote == 0:
        raise ManifestError("same-slot reserves must be positive")
    rows = scenario["events"]
    if not isinstance(rows, list) or len(rows) != 2:
        raise ManifestError("same-slot scenario needs exactly two events")
    parsed: list[tuple[int, int, str, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ManifestError("same-slot event must be an object")
        _exact_keys(
            row,
            {"delta_base_atoms", "event_id", "slot", "transaction_index"},
            "same-slot event",
        )
        parsed.append(
            (
                _decimal(row["slot"], "same-slot slot"),
                _decimal(row["transaction_index"], "same-slot transaction_index"),
                _stable(row["event_id"], "same-slot event_id"),
                _decimal(row["delta_base_atoms"], "same-slot delta"),
            )
        )
    if len({row[2] for row in parsed}) != 2 or len({row[1] for row in parsed}) != 2:
        raise ManifestError("same-slot event IDs and transaction indices must be unique")
    if len({row[0] for row in parsed}) != 1:
        raise ManifestError("same-slot adversary events must share one slot")
    observed_rows = tuple(sorted(parsed))
    observed_order = tuple((row[2], row[3]) for row in observed_rows)
    if tuple(event_id for event_id, _ in observed_order) == tuple(
        sorted(event_id for event_id, _ in observed_order)
    ):
        raise ManifestError("same-slot negative control requires lexical and chain order to differ")
    observed_outputs, observed_final = _cpmm_order(observed_order, base, quote)
    reverse_order = tuple(reversed(observed_order))
    reverse_outputs, reverse_final = _cpmm_order(reverse_order, base, quote)
    compatible = []
    for order in permutations(observed_order):
        outputs, final_quote = _cpmm_order(order, base, quote)
        compatible.append(
            _order_digest(tuple(event_id for event_id, _ in order), outputs, final_quote)
        )
    compatible = sorted(set(compatible))
    if len(compatible) != 2:
        raise ManifestError("unindexed same-slot fixture must retain two distinct outcomes")

    expected = scenario["expected"]
    if not isinstance(expected, dict):
        raise ManifestError("same-slot expected must be an object")
    _exact_keys(expected, {"observed", "reverse", "unindexed_outcome_count"}, "same-slot expected")
    for label, actual_outputs, actual_final in (
        ("observed", observed_outputs, observed_final),
        ("reverse", reverse_outputs, reverse_final),
    ):
        expected_branch = expected[label]
        if not isinstance(expected_branch, dict):
            raise ManifestError("same-slot expected branch must be an object")
        _exact_keys(
            expected_branch,
            {"a-competing", "final_quote_reserve_atoms", "z-focal"},
            f"same-slot {label} expected",
        )
        for event_id, output in actual_outputs.items():
            if _decimal(expected_branch[event_id], f"same-slot {label} output") != output:
                raise ManifestError("same-slot expected event output changed")
        if (
            _decimal(
                expected_branch["final_quote_reserve_atoms"], f"same-slot {label} final reserve"
            )
            != actual_final
        ):
            raise ManifestError("same-slot expected final reserve changed")
    if _decimal(expected["unindexed_outcome_count"], "same-slot outcome count") != len(compatible):
        raise ManifestError("same-slot compatible outcome count changed")

    values = {
        "compatible_order_1_digest": (StructuralValueKind.SHA256, compatible[0]),
        "compatible_order_2_digest": (StructuralValueKind.SHA256, compatible[1]),
        "observed_a_competing_output_atoms": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(observed_outputs["a-competing"]),
        ),
        "observed_final_quote_reserve_atoms": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(observed_final),
        ),
        "observed_first_event_id": (
            StructuralValueKind.IDENTIFIER,
            observed_order[0][0],
        ),
        "observed_z_focal_output_atoms": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(observed_outputs["z-focal"]),
        ),
        "reverse_a_competing_output_atoms": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(reverse_outputs["a-competing"]),
        ),
        "reverse_final_quote_reserve_atoms": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(reverse_final),
        ),
        "reverse_z_focal_output_atoms": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(reverse_outputs["z-focal"]),
        ),
        "unindexed_disposition": (StructuralValueKind.DISPOSITION, "compatible_set"),
        "unindexed_outcome_count": (
            StructuralValueKind.DECIMAL_INTEGER,
            str(len(compatible)),
        ),
    }
    outputs = tuple(
        StructuralOutput(name, kind, value) for name, (kind, value) in sorted(values.items())
    )
    return StructuralTruthCase.build(
        "structural-case-02-same-slot-reorder",
        StructuralAdversaryKind.SAME_SLOT_REORDER,
        tuple(sorted((pool_id, *(row[2] for row in parsed)))),
        outputs,
        "negative_sort_same_slot_events_by_display_id_or_assume_one_order",
        "transaction order is replaced by lexical order or unindexed events collapse to one path",
    )


def derive_identity_revision_at_cut(
    revisions: list[dict[str, Any]],
    wallet_id: str,
    available_at: str,
    commit_seq: str,
) -> tuple[str, str, str]:
    """Resolve one synthetic identity revision at a fixture cut.

    Availability and commit eligibility are evaluated before identity payload fields. This is a
    fixture leakage rule, not an identity resolver or authority-bearing occurrence.
    """

    wallet = _stable(wallet_id, "identity wallet_id")
    cutoff_time = _utc(available_at, "identity cutoff available_at")
    cutoff_commit = _decimal(commit_seq, "identity cutoff commit_seq")
    eligible: list[tuple[datetime, int, dict[str, Any]]] = []
    for row in revisions:
        if not isinstance(row, dict):
            raise ManifestError("identity revision must be an object")
        _exact_keys(
            row,
            {
                "available_at",
                "commit_seq",
                "entity_id",
                "revision_id",
                "supersedes_revision_id",
                "wallet_id",
            },
            "identity revision",
        )
        row_time = _utc(row["available_at"], "identity revision available_at")
        row_commit = _decimal(row["commit_seq"], "identity revision commit_seq")
        if row_time <= cutoff_time and row_commit <= cutoff_commit:
            eligible.append((row_time, row_commit, row))
    if not eligible:
        raise ManifestError("identity revision cut has no known assertion")
    eligible.sort(key=lambda item: (item[0], item[1], item[2].get("revision_id", "")))
    previous: str | None = None
    for _, _, row in eligible:
        revision_id = _stable(row["revision_id"], "identity revision_id")
        if _stable(row["wallet_id"], "identity revision wallet_id") != wallet:
            raise ManifestError("identity revision changed wallet subject")
        _stable(row["entity_id"], "identity entity_id")
        supersedes = row["supersedes_revision_id"]
        if supersedes is not None:
            supersedes = _stable(supersedes, "identity supersedes_revision_id")
        if supersedes != previous:
            raise ManifestError("identity revision predecessor chain is not exact")
        previous = revision_id
    latest = eligible[-1][2]
    input_digest = qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "wallet_id": wallet,
                "available_at": available_at,
                "commit_seq": commit_seq,
                "eligible_revisions": [row for _, _, row in eligible],
                "authority": STRUCTURAL_BATTERY_AUTHORITY,
            }
        )
    )
    return latest["revision_id"], latest["entity_id"], input_digest


def _identity_case(scenario: dict[str, Any]) -> StructuralTruthCase:
    _exact_keys(
        scenario,
        {"cuts", "expected", "id", "revisions", "wallet_id"},
        "identity scenario",
    )
    wallet_id = _stable(scenario["wallet_id"], "identity wallet_id")
    cuts = scenario["cuts"]
    if not isinstance(cuts, dict):
        raise ManifestError("identity cuts must be an object")
    _exact_keys(cuts, {"early", "late"}, "identity cuts")
    for name in ("early", "late"):
        if not isinstance(cuts[name], dict):
            raise ManifestError("identity cut must be an object")
        _exact_keys(cuts[name], {"available_at", "commit_seq"}, f"identity {name} cut")
    early_time = _utc(cuts["early"]["available_at"], "identity early cutoff")
    late_time = _utc(cuts["late"]["available_at"], "identity late cutoff")
    early_commit = _decimal(cuts["early"]["commit_seq"], "identity early commit")
    late_commit = _decimal(cuts["late"]["commit_seq"], "identity late commit")
    if early_time >= late_time or early_commit >= late_commit:
        raise ManifestError("identity fixture cuts must advance together")
    revisions = scenario["revisions"]
    if not isinstance(revisions, list) or len(revisions) != 2:
        raise ManifestError("identity scenario needs exactly two revisions")
    early = derive_identity_revision_at_cut(
        revisions,
        wallet_id,
        cuts["early"]["available_at"],
        cuts["early"]["commit_seq"],
    )
    early_without_future = derive_identity_revision_at_cut(
        revisions[:1],
        wallet_id,
        cuts["early"]["available_at"],
        cuts["early"]["commit_seq"],
    )
    if early != early_without_future:
        raise ManifestError("future identity revision changed the earlier as-known artifact")
    late = derive_identity_revision_at_cut(
        revisions,
        wallet_id,
        cuts["late"]["available_at"],
        cuts["late"]["commit_seq"],
    )
    expected = scenario["expected"]
    if not isinstance(expected, dict):
        raise ManifestError("identity expected must be an object")
    _exact_keys(
        expected,
        {"early_entity_id", "early_revision_id", "late_entity_id", "late_revision_id"},
        "identity expected",
    )
    if early[:2] != (expected["early_revision_id"], expected["early_entity_id"]) or late[:2] != (
        expected["late_revision_id"],
        expected["late_entity_id"],
    ):
        raise ManifestError("identity fixture expected revision changed")
    values = {
        "early_entity_id": (StructuralValueKind.IDENTIFIER, early[1]),
        "early_input_digest": (StructuralValueKind.SHA256, early[2]),
        "early_revision_id": (StructuralValueKind.IDENTIFIER, early[0]),
        "late_entity_id": (StructuralValueKind.IDENTIFIER, late[1]),
        "late_input_digest": (StructuralValueKind.SHA256, late[2]),
        "late_revision_id": (StructuralValueKind.IDENTIFIER, late[0]),
    }
    outputs = tuple(
        StructuralOutput(name, kind, value) for name, (kind, value) in sorted(values.items())
    )
    revision_ids = tuple(
        _stable(row.get("revision_id"), "identity revision_id") for row in revisions
    )
    return StructuralTruthCase.build(
        "structural-case-03-identity-revision",
        StructuralAdversaryKind.IDENTITY_REVISION,
        tuple(sorted((wallet_id, *revision_ids))),
        outputs,
        "negative_apply_later_identity_revision_to_earlier_cut",
        (
            "later identity knowledge rewrites an earlier artifact or silently asserts "
            "controller truth"
        ),
    )


def build_structural_known_truth_battery(
    fixture_bytes: bytes,
) -> StructuralKnownTruthBattery:
    """Recompute the exact migration, same-slot, and identity-revision fixture truths."""

    document = _load_fixture(fixture_bytes)
    cases = (
        _migration_case(_scenario_by_id(document, "migration-splice")),
        _same_slot_case(_scenario_by_id(document, "same-slot-order")),
        _identity_case(_scenario_by_id(document, "identity-revision")),
    )
    return StructuralKnownTruthBattery(
        "structural-known-truth-fixture-v1",
        STRUCTURAL_FIXTURE_DIGEST,
        cases,
    )
