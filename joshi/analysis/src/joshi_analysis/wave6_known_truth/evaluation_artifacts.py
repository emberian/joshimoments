"""Strict canonical wire adapters for the three registered N01 evaluation artifacts.

The semantic batteries generate the values. These adapters only freeze and reparse their exact
checked bytes. They confer no store receipt, source authority, market truth, or performance claim.
"""

from __future__ import annotations

import json
from typing import Any

from ..canonical import canonical_json_bytes
from ..errors import ManifestError
from .domain_battery import DomainBatteryEvaluation
from .lab import KnownTruthEvaluation
from .protocol_battery import ProtocolBatteryEvaluation
from .structural_battery import StructuralBatteryEvaluation

_GENERIC_FIELDS = {
    "suite_id",
    "suite_digest",
    "candidate_id",
    "passed_case_ids",
    "result_digests",
    "evaluation_digest",
    "authority",
}
_PROTOCOL_FIELDS = _GENERIC_FIELDS | {"pump_fixture_digest", "dlmm_fixture_digest"}
_STRUCTURAL_FIELDS = _GENERIC_FIELDS | {"fixture_digest"}


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate evaluation artifact JSON key: {key}")
        result[key] = value
    return result


def _document(exact_bytes: bytes, fields: set[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(exact_bytes, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict) or set(value) != fields:
        raise ManifestError(f"{label} fields differ from the exact evaluation schema")
    if canonical_json_bytes(value, newline=True) != exact_bytes:
        raise ManifestError(f"{label} bytes are not exact canonical JSON")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManifestError(f"{field} must be an exact string list")
    return tuple(value)


def _construct(label: str, constructor: type[Any], *values: Any) -> Any:
    try:
        return constructor(*values)
    except (TypeError, ValueError) as error:
        raise ManifestError(f"{label} has an invalid typed field") from error


def parse_known_truth_evaluation_exact(exact_bytes: bytes) -> KnownTruthEvaluation:
    """Reparse one exact generic known-truth evaluation artifact."""

    value = _document(exact_bytes, _GENERIC_FIELDS, "known-truth evaluation artifact")
    return _construct(
        "known-truth evaluation artifact",
        KnownTruthEvaluation,
        value["suite_id"],
        value["suite_digest"],
        value["candidate_id"],
        _string_tuple(value["passed_case_ids"], "passed_case_ids"),
        _string_tuple(value["result_digests"], "result_digests"),
        value["evaluation_digest"],
        value["authority"],
    )


def parse_domain_evaluation_exact(exact_bytes: bytes) -> DomainBatteryEvaluation:
    """Reparse one exact, registered-but-fixture-only domain evaluation artifact."""

    value = _document(exact_bytes, _GENERIC_FIELDS, "domain evaluation artifact")
    return _construct(
        "domain evaluation artifact",
        DomainBatteryEvaluation,
        value["suite_id"],
        value["suite_digest"],
        value["candidate_id"],
        _string_tuple(value["passed_case_ids"], "passed_case_ids"),
        _string_tuple(value["result_digests"], "result_digests"),
        value["evaluation_digest"],
        value["authority"],
    )


def parse_protocol_evaluation_exact(exact_bytes: bytes) -> ProtocolBatteryEvaluation:
    """Reparse one exact protocol known-truth evaluation artifact."""

    value = _document(exact_bytes, _PROTOCOL_FIELDS, "protocol evaluation artifact")
    return _construct(
        "protocol evaluation artifact",
        ProtocolBatteryEvaluation,
        value["suite_id"],
        value["suite_digest"],
        value["pump_fixture_digest"],
        value["dlmm_fixture_digest"],
        value["candidate_id"],
        _string_tuple(value["passed_case_ids"], "passed_case_ids"),
        _string_tuple(value["result_digests"], "result_digests"),
        value["evaluation_digest"],
        value["authority"],
    )


def parse_structural_evaluation_exact(exact_bytes: bytes) -> StructuralBatteryEvaluation:
    """Reparse one exact structural known-truth evaluation artifact."""

    value = _document(exact_bytes, _STRUCTURAL_FIELDS, "structural evaluation artifact")
    return _construct(
        "structural evaluation artifact",
        StructuralBatteryEvaluation,
        value["suite_id"],
        value["suite_digest"],
        value["fixture_digest"],
        value["candidate_id"],
        _string_tuple(value["passed_case_ids"], "passed_case_ids"),
        _string_tuple(value["result_digests"], "result_digests"),
        value["evaluation_digest"],
        value["authority"],
    )
