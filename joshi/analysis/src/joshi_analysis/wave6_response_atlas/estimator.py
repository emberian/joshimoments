from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import gcd
from typing import Any

import pyarrow as pa

from ..canonical import (
    canonical_json_bytes,
    iso_utc,
    logical_table_sha256,
    qualified_sha256_bytes,
)
from ..errors import CoverageError, ManifestError, TemporalLeakageError
from .contracts import (
    ATLAS_CLAIM_SCOPE,
    COMPETING_EVENT_KINDS,
    COMPETING_RISK_SURFACE_SCHEMA,
    COMPETING_RISK_SURFACE_SCHEMA_ID,
    CONTEXT_LEVELS,
    RESPONSE_COMPONENT_OBSERVATION_SCHEMA,
    RESPONSE_COMPONENTS,
    RESPONSE_SURFACE_SCHEMA,
    RESPONSE_SURFACE_SCHEMA_ID,
    RISK_CLAIM_SCOPE,
    RISK_OUTCOME_SCHEMA,
    RISK_REFUSAL_SCHEMA,
    RISK_REFUSAL_SCHEMA_ID,
)

ESTIMATOR_ID = "wave6_point_in_time_signed_flow_response_atlas"
ESTIMATOR_VERSION = "2"
CONFIGURATION = {
    "aggregation": "reduced_exact_rational_mean_over_complete_anchor_decompositions",
    "components": list(RESPONSE_COMPONENTS),
    "contexts": list(CONTEXT_LEVELS),
    "competing_event_kinds": list(COMPETING_EVENT_KINDS),
    "missingness": "declared_gap_no_zero_or_partial_total_imputation",
    "risk_summary": "issued_anchor_denominator_with_pending_and_typed_terminal_states",
    "topology": "separate_exact_epoch_and_version_cells",
}
CONFIGURATION_DIGEST = qualified_sha256_bytes(canonical_json_bytes(CONFIGURATION))

_ANCHOR_INVARIANTS = (
    "event_id",
    "base_asset_id",
    "venue_id",
    "lifecycle_state",
    "lifecycle_version_id",
    "lifecycle_valid_lower",
    "lifecycle_valid_upper",
    "lifecycle_available_at",
    "lifecycle_retracted_at",
    "wallet_id",
    "wallet_identity_version_id",
    "cluster_id",
    "cluster_version_id",
    "caller_class",
    "caller_class_version_id",
    "caller_context_valid_lower",
    "caller_context_valid_upper",
    "caller_context_available_at",
    "caller_context_retracted_at",
    "mark_direction",
    "mark_size_bucket",
    "mark_size_atoms",
    "mark_size_lower_atoms",
    "mark_size_upper_atoms",
    "mark_size_unit",
    "topology_epoch",
    "topology_version_id",
    "topology_valid_lower",
    "topology_valid_upper",
    "topology_available_at",
    "topology_retracted_at",
    "event_time",
    "event_available_at",
    "information_cutoff",
    "horizon_us",
    "response_time",
    "response_unit",
)
_EVENT_INVARIANTS = tuple(
    field for field in _ANCHOR_INVARIANTS if field not in {"horizon_us", "response_time"}
)


@dataclass(frozen=True)
class ResponseAtlas:
    response_surfaces: pa.Table
    competing_risks: pa.Table
    risk_refusals: pa.Table


def response_atlas_input_identity(
    observations: pa.Table, risk_outcomes: pa.Table | None = None
) -> tuple[str, str]:
    """Identify the response-feature closure without outcome-label coupling.

    ``risk_outcomes`` remains accepted for compatibility but is intentionally ignored. Risk output
    uses a separate private identity that includes only terminal rows known by the fit cutoff.
    """

    components = {
        "observations": logical_table_sha256(observations, ["component_observation_id"]),
    }
    logical_digest = qualified_sha256_bytes(canonical_json_bytes(components))
    snapshot_id = qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "input_contract": "joshi.analysis.wave6-response-surface-input/v2",
                "logical_digest": logical_digest,
            }
        )
    )
    return snapshot_id, logical_digest


def _risk_surface_input_identity(
    observations: pa.Table, risk_outcomes: pa.Table
) -> tuple[str, str]:
    components = {
        "risk_subjects": logical_table_sha256(observations, ["component_observation_id"]),
        "known_terminal_outcomes": logical_table_sha256(risk_outcomes, ["risk_outcome_id"]),
    }
    logical_digest = qualified_sha256_bytes(canonical_json_bytes(components))
    snapshot_id = qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "input_contract": "joshi.analysis.wave6-response-risk-surface-input/v2",
                "logical_digest": logical_digest,
            }
        )
    )
    return snapshot_id, logical_digest


def _canonical_output(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, list):
        return [_canonical_output(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_output(item) for key, item in value.items()}
    return value


def _stable_id(prefix: str, material: dict[str, Any]) -> str:
    digest = qualified_sha256_bytes(canonical_json_bytes(_canonical_output(material)))
    return f"{prefix}:{digest.removeprefix('sha256:')}"


def _record_digest(row: dict[str, Any], *excluded: str) -> str:
    material = {key: value for key, value in row.items() if key not in excluded}
    return qualified_sha256_bytes(canonical_json_bytes(_canonical_output(material)))


def _require_nonempty(row: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if row[field] == "":
            raise ManifestError(f"response atlas field {field} cannot be empty")


def _validate_version_time(
    row: dict[str, Any],
    *,
    prefix: str,
    event_time: datetime,
    information_cutoff: datetime,
) -> None:
    lower = row[f"{prefix}_valid_lower"]
    upper = row[f"{prefix}_valid_upper"]
    available = row[f"{prefix}_available_at"]
    retracted = row[f"{prefix}_retracted_at"]
    if not lower <= event_time < upper:
        raise TemporalLeakageError(
            f"selected {prefix.replace('_', ' ')} version is not valid at the event"
        )
    if available > information_cutoff:
        raise TemporalLeakageError(
            f"selected {prefix.replace('_', ' ')} version was unavailable at information cut"
        )
    if retracted is not None and retracted <= information_cutoff:
        raise TemporalLeakageError(
            f"selected {prefix.replace('_', ' ')} version was retracted by information cut"
        )


def _validate_observation(row: dict[str, Any]) -> None:
    _require_nonempty(
        row,
        (
            "component_observation_id",
            "event_id",
            "base_asset_id",
            "venue_id",
            "lifecycle_state",
            "lifecycle_version_id",
            "wallet_id",
            "wallet_identity_version_id",
            "cluster_id",
            "cluster_version_id",
            "caller_class",
            "caller_class_version_id",
            "mark_size_bucket",
            "topology_epoch",
            "topology_version_id",
            "coverage_window_id",
        ),
    )
    if row["mark_direction"] not in {"buy", "sell"}:
        raise ManifestError("mark direction must be buy or sell")
    if row["mark_size_unit"] != "base_asset_atoms":
        raise ManifestError("response atlas requires mark size in base_asset_atoms")
    if row["response_unit"] != "base_asset_atoms":
        raise ManifestError("response atlas requires signed response in base_asset_atoms")
    if row["horizon_us"] <= 0:
        raise ManifestError("response horizon must be positive")
    if not (
        0 <= row["mark_size_lower_atoms"]
        < row["mark_size_upper_atoms"]
        and row["mark_size_lower_atoms"]
        <= row["mark_size_atoms"]
        < row["mark_size_upper_atoms"]
    ):
        raise ManifestError("mark size must lie in its nonempty half-open atom bucket")
    if not row["event_time"] <= row["event_available_at"] <= row["information_cutoff"]:
        raise TemporalLeakageError("marked event was not available at its information cut")
    expected_response_time = row["event_time"] + timedelta(microseconds=row["horizon_us"])
    if row["response_time"] != expected_response_time:
        raise ManifestError("response time differs from event time plus registered horizon")
    if row["response_available_at"] < row["response_time"]:
        raise TemporalLeakageError("response became available before its response time")
    if row["information_cutoff"] >= row["response_time"]:
        raise TemporalLeakageError("information cut reaches into the response horizon")
    _validate_version_time(
        row,
        prefix="lifecycle",
        event_time=row["event_time"],
        information_cutoff=row["information_cutoff"],
    )
    _validate_version_time(
        row,
        prefix="caller_context",
        event_time=row["event_time"],
        information_cutoff=row["information_cutoff"],
    )
    _validate_version_time(
        row,
        prefix="topology",
        event_time=row["event_time"],
        information_cutoff=row["information_cutoff"],
    )
    if row["component_kind"] not in RESPONSE_COMPONENTS:
        raise ManifestError("response atlas received an unregistered decomposition component")
    if row["coverage_status"] == "observed":
        if row["response_signed_flow_atoms"] is None or row["coverage_gap_id"] is not None:
            raise CoverageError("observed response component lacks a value or cites a gap")
    elif row["coverage_status"] == "gap":
        if row["response_signed_flow_atoms"] is not None or not row["coverage_gap_id"]:
            raise CoverageError("response gap must retain a null value and exact gap identity")
    else:
        raise CoverageError("unknown response component coverage status")
    if row["available_commit_seq"] < 0:
        raise ManifestError("available commit sequence cannot be negative")


def _validate_risk(row: dict[str, Any], anchor: dict[str, Any]) -> None:
    _require_nonempty(row, ("risk_outcome_id", "event_id", "coverage_window_id"))
    if row["risk_entry_time"] != anchor["event_time"]:
        raise ManifestError("risk entry must equal its anchor event time")
    if row["risk_horizon_end"] != anchor["response_time"]:
        raise ManifestError("risk horizon end must equal its registered response horizon")
    if not row["risk_entry_time"] <= row["outcome_time"] <= row["risk_horizon_end"]:
        raise ManifestError("risk outcome or censoring time escapes its horizon")
    if row["outcome_known_at"] < row["outcome_time"]:
        raise TemporalLeakageError("risk outcome became known before its event or censoring time")
    if row["censoring_kind"] == "exact_event":
        if row["event_kind"] not in COMPETING_EVENT_KINDS:
            raise ManifestError("exact risk event has an unregistered competing event kind")
        if row["event_time"] != row["outcome_time"]:
            raise ManifestError("exact competing event time must equal outcome time")
        if row["coverage_status"] != "observed" or row["coverage_gap_id"] is not None:
            raise CoverageError("exact competing event must be observed without a gap")
    elif row["censoring_kind"] == "right_administrative":
        if row["event_kind"] is not None or row["event_time"] is not None:
            raise ManifestError("administrative censoring cannot manufacture a no-event label")
        if row["outcome_time"] != row["risk_horizon_end"]:
            raise ManifestError("administrative censoring must close at the registered horizon")
        if row["coverage_status"] != "observed" or row["coverage_gap_id"] is not None:
            raise CoverageError("administrative censoring represents a covered horizon")
    elif row["censoring_kind"] == "right_source_gap":
        if row["event_kind"] is not None or row["event_time"] is not None:
            raise ManifestError("source-gap censoring cannot manufacture a no-event label")
        if row["coverage_status"] != "gap" or not row["coverage_gap_id"]:
            raise CoverageError("source-gap censoring requires exact gap identity")
    else:
        raise ManifestError("unsupported competing-risk censoring kind")
    if row["available_commit_seq"] < 0:
        raise ManifestError("available commit sequence cannot be negative")


def _validate_inputs(
    observations: pa.Table,
    risk_outcomes: pa.Table,
    fit_cutoff: datetime,
) -> tuple[
    dict[tuple[str, int], dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
]:
    if fit_cutoff.tzinfo is None:
        raise ManifestError("fit cutoff must be timezone-aware")
    if not observations.schema.equals(RESPONSE_COMPONENT_OBSERVATION_SCHEMA, check_metadata=True):
        raise ManifestError("response component observations violate their exact Arrow schema")

    rows = observations.to_pylist()
    available_by_anchor: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["response_available_at"] <= fit_cutoff:
            available_by_anchor[(row["event_id"], row["horizon_us"])].append(row)

    required_components = set(RESPONSE_COMPONENTS)
    candidate_rows: list[dict[str, Any]] = []
    for available_rows in available_by_anchor.values():
        available_components = {row["component_kind"] for row in available_rows}
        if available_components != required_components:
            raise CoverageError(
                "response anchor has incomplete component closure; use an explicit gap row"
            )
        candidate_rows.extend(available_rows)

    observation_ids = [row["component_observation_id"] for row in candidate_rows]
    if len(observation_ids) != len(set(observation_ids)):
        raise ManifestError("response components duplicate occurrence identity")
    anchors: dict[tuple[str, int], dict[str, Any]] = {}
    event_invariants: dict[str, tuple[Any, ...]] = {}
    for row in candidate_rows:
        _validate_observation(row)
        event_material = tuple(row[field] for field in _EVENT_INVARIANTS)
        previous_event = event_invariants.setdefault(row["event_id"], event_material)
        if previous_event != event_material:
            raise ManifestError("one event mixes context, unit, lifecycle, or topology identity")
        anchor_key = (row["event_id"], row["horizon_us"])
        anchor = anchors.setdefault(
            anchor_key,
            {"representative": row, "components": {}, "rows": []},
        )
        representative = anchor["representative"]
        if tuple(row[field] for field in _ANCHOR_INVARIANTS) != tuple(
            representative[field] for field in _ANCHOR_INVARIANTS
        ):
            raise ManifestError("one response anchor mixes context, unit, lifecycle, or topology")
        if row["component_kind"] in anchor["components"]:
            raise ManifestError("response anchor duplicates a decomposition component")
        anchor["components"][row["component_kind"]] = row
        anchor["rows"].append(row)
    if not anchors:
        raise ManifestError("response atlas requires at least one response anchor")
    for anchor in anchors.values():
        if set(anchor["components"]) != required_components:
            raise CoverageError(
                "response anchor has incomplete component closure; use an explicit gap row"
            )

    eligible_observations = [
        row
        for key in sorted(anchors)
        for row in anchors[key]["rows"]
    ]
    admitted_known_risk_table: pa.Table | None = None
    try:
        if not risk_outcomes.schema.equals(RISK_OUTCOME_SCHEMA, check_metadata=True):
            raise ManifestError("risk outcomes violate their exact Arrow schema")
        risk_rows = risk_outcomes.to_pylist()
        member_risk_rows = [
            row
            for row in risk_rows
            if (row["event_id"], row["horizon_us"]) in anchors
        ]
        known_risk_rows = [
            row
            for row in member_risk_rows
            if row["outcome_known_at"] <= fit_cutoff
        ]
        admitted_known_risk_table = pa.Table.from_pylist(
            known_risk_rows, schema=RISK_OUTCOME_SCHEMA
        )
        risk_ids = [row["risk_outcome_id"] for row in known_risk_rows]
        if len(risk_ids) != len(set(risk_ids)):
            raise ManifestError("risk outcomes duplicate occurrence identity")
        risks_by_anchor: dict[tuple[str, int], dict[str, Any]] = {}
        for row in known_risk_rows:
            anchor_key = (row["event_id"], row["horizon_us"])
            if anchor_key in risks_by_anchor:
                raise ManifestError("response anchor duplicates its competing-risk outcome")
            _validate_risk(row, anchors[anchor_key]["representative"])
            risks_by_anchor[anchor_key] = row
    except ManifestError as error:
        reason_code = (
            "unregistered_competing_event_kind"
            if "unregistered competing event kind" in str(error)
            else "risk_coverage_contract_invalid"
            if isinstance(error, CoverageError)
            else "risk_temporal_contract_invalid"
            if isinstance(error, TemporalLeakageError)
            else "risk_manifest_contract_invalid"
        )
        return (
            anchors,
            eligible_observations,
            [],
            {
                "reason_code": reason_code,
                "reason_detail": str(error),
                "admitted_risk_row_count": (
                    admitted_known_risk_table.num_rows
                    if admitted_known_risk_table is not None
                    else 0
                ),
                "refused_risk_input_logical_digest": (
                    logical_table_sha256(admitted_known_risk_table, ["risk_outcome_id"])
                    if admitted_known_risk_table is not None
                    else None
                ),
            },
        )
    eligible_risks = [row for _, row in sorted(risks_by_anchor.items())]
    return anchors, eligible_observations, eligible_risks, None


def _context(row: dict[str, Any], level: str) -> tuple[str, str]:
    if level == "wallet":
        return row["wallet_id"], row["wallet_identity_version_id"]
    if level == "cluster":
        return row["cluster_id"], row["cluster_version_id"]
    if level == "caller_class":
        return row["caller_class"], row["caller_class_version_id"]
    raise AssertionError(f"unknown response-atlas context level: {level}")


def _cell_key(row: dict[str, Any], context_level: str) -> tuple[Any, ...]:
    context_id, context_version = _context(row, context_level)
    return (
        row["base_asset_id"],
        row["venue_id"],
        row["lifecycle_state"],
        row["lifecycle_version_id"],
        context_level,
        context_id,
        context_version,
        row["mark_direction"],
        row["mark_size_bucket"],
        row["mark_size_lower_atoms"],
        row["mark_size_upper_atoms"],
        row["mark_size_unit"],
        row["topology_epoch"],
        row["topology_version_id"],
        row["horizon_us"],
    )


def _key_fields(key: tuple[Any, ...]) -> dict[str, Any]:
    names = (
        "base_asset_id",
        "venue_id",
        "lifecycle_state",
        "lifecycle_version_id",
        "context_level",
        "context_id",
        "context_version_id",
        "mark_direction",
        "mark_size_bucket",
        "mark_size_lower_atoms",
        "mark_size_upper_atoms",
        "mark_size_unit",
        "topology_epoch",
        "topology_version_id",
        "horizon_us",
    )
    return dict(zip(names, key, strict=True))


def _exact_mean(values: list[int]) -> tuple[str | None, str | None, int | None]:
    if not values:
        return None, None, None
    total = sum(values)
    divisor = len(values)
    common_divisor = gcd(abs(total), divisor)
    return str(total), str(total // common_divisor), divisor // common_divisor


def build_response_atlas(
    observations: pa.Table,
    risk_outcomes: pa.Table,
    fit_cutoff: datetime,
) -> ResponseAtlas:
    eligible_anchors, eligible_observations, eligible_risks, risk_refusal = _validate_inputs(
        observations, risk_outcomes, fit_cutoff
    )
    observation_table = pa.Table.from_pylist(
        eligible_observations, schema=RESPONSE_COMPONENT_OBSERVATION_SCHEMA
    )
    risk_table = pa.Table.from_pylist(eligible_risks, schema=RISK_OUTCOME_SCHEMA)
    response_snapshot_id, response_logical_digest = response_atlas_input_identity(
        observation_table
    )
    response_maximum_available_at = max(
        row["response_available_at"] for row in eligible_observations
    )
    response_as_of_commit_seq = max(
        row["available_commit_seq"] for row in eligible_observations
    )

    surface_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for anchor in eligible_anchors.values():
        representative = anchor["representative"]
        for level in CONTEXT_LEVELS:
            surface_groups[_cell_key(representative, level)].append(anchor)

    surface_rows: list[dict[str, Any]] = []
    for key, anchors in sorted(surface_groups.items(), key=lambda item: item[0]):
        dimensions = _key_fields(key)
        complete = [
            anchor
            for anchor in anchors
            if all(
                anchor["components"][component]["coverage_status"] == "observed"
                for component in RESPONSE_COMPONENTS
            )
        ]
        for component in (*RESPONSE_COMPONENTS, "total"):
            if component == "total":
                values = [
                    sum(
                        anchor["components"][part]["response_signed_flow_atoms"]
                        for part in RESPONSE_COMPONENTS
                    )
                    for anchor in complete
                ]
                observed_count = len(complete)
                gap_count = len(anchors) - len(complete)
                coverage_windows = sorted(
                    {
                        row["coverage_window_id"]
                        for anchor in anchors
                        for row in anchor["rows"]
                    }
                )
                coverage_gaps = sorted(
                    {
                        row["coverage_gap_id"]
                        for anchor in anchors
                        for row in anchor["rows"]
                        if row["coverage_gap_id"] is not None
                    }
                )
            else:
                values = [
                    anchor["components"][component]["response_signed_flow_atoms"]
                    for anchor in complete
                ]
                component_rows = [anchor["components"][component] for anchor in anchors]
                observed_count = sum(row["coverage_status"] == "observed" for row in component_rows)
                gap_count = len(component_rows) - observed_count
                coverage_windows = sorted({row["coverage_window_id"] for row in component_rows})
                coverage_gaps = sorted(
                    row["coverage_gap_id"]
                    for row in component_rows
                    if row["coverage_gap_id"] is not None
                )
            decomposition_status = (
                "no_complete_anchor_support"
                if not complete
                else "complete_no_gaps"
                if len(complete) == len(anchors)
                else "complete_support_with_declared_gaps"
            )
            response_sum, response_numerator, response_denominator = _exact_mean(values)
            row = {
                "estimator_id": ESTIMATOR_ID,
                "estimator_version": ESTIMATOR_VERSION,
                "estimator_configuration_digest": CONFIGURATION_DIGEST,
                "input_snapshot_id": response_snapshot_id,
                "input_logical_digest": response_logical_digest,
                "fit_cutoff": fit_cutoff,
                "maximum_input_available_at": response_maximum_available_at,
                "as_of_commit_seq": response_as_of_commit_seq,
                **dimensions,
                "component_kind": component,
                "response_sum_atoms": response_sum,
                "response_mean_numerator_atoms": response_numerator,
                "response_mean_denominator": response_denominator,
                "response_unit": "base_asset_atoms",
                "support_anchor_count": len(anchors),
                "complete_anchor_count": len(complete),
                "component_observed_count": observed_count,
                "component_gap_count": gap_count,
                "coverage_ratio_ppm": observed_count * 1_000_000 // len(anchors),
                "coverage_window_ids": coverage_windows,
                "coverage_gap_ids": coverage_gaps,
                "decomposition_status": decomposition_status,
                "claim_scope": ATLAS_CLAIM_SCOPE,
            }
            row["surface_cell_id"] = _stable_id(
                "response-surface",
                {
                    "schema": RESPONSE_SURFACE_SCHEMA_ID,
                    "input_logical_digest": response_logical_digest,
                    "fit_cutoff": fit_cutoff,
                    "dimensions": dimensions,
                    "component_kind": component,
                },
            )
            row["surface_cell_digest"] = _record_digest(
                row, "surface_cell_id", "surface_cell_digest"
            )
            surface_rows.append(row)

    surface_rows.sort(key=lambda row: row["surface_cell_id"])
    response_surface_table = pa.Table.from_pylist(surface_rows, schema=RESPONSE_SURFACE_SCHEMA)
    if risk_refusal is not None:
        refusal_row = {
            "estimator_id": ESTIMATOR_ID,
            "estimator_version": ESTIMATOR_VERSION,
            "estimator_configuration_digest": CONFIGURATION_DIGEST,
            "response_input_snapshot_id": response_snapshot_id,
            "response_input_logical_digest": response_logical_digest,
            "fit_cutoff": fit_cutoff,
            "refusal_kind": "risk_artifact_refused_response_artifact_preserved",
            "reason_code": risk_refusal["reason_code"],
            "reason_detail": risk_refusal["reason_detail"],
            "admitted_risk_row_count": risk_refusal["admitted_risk_row_count"],
            "refused_risk_input_logical_digest": risk_refusal[
                "refused_risk_input_logical_digest"
            ],
            "claim_scope": RISK_CLAIM_SCOPE,
        }
        refusal_row["risk_refusal_id"] = _stable_id(
            "response-risk-refusal",
            {
                "schema": RISK_REFUSAL_SCHEMA_ID,
                "response_input_logical_digest": response_logical_digest,
                "fit_cutoff": fit_cutoff,
                "reason_code": risk_refusal["reason_code"],
                "reason_detail": risk_refusal["reason_detail"],
                "admitted_risk_row_count": risk_refusal["admitted_risk_row_count"],
                "refused_risk_input_logical_digest": risk_refusal[
                    "refused_risk_input_logical_digest"
                ],
            },
        )
        refusal_row["risk_refusal_digest"] = _record_digest(
            refusal_row, "risk_refusal_id", "risk_refusal_digest"
        )
        return ResponseAtlas(
            response_surfaces=response_surface_table,
            competing_risks=pa.Table.from_pylist([], schema=COMPETING_RISK_SURFACE_SCHEMA),
            risk_refusals=pa.Table.from_pylist([refusal_row], schema=RISK_REFUSAL_SCHEMA),
        )

    risk_snapshot_id, risk_logical_digest = _risk_surface_input_identity(
        observation_table, risk_table
    )
    risk_availability = [row["response_available_at"] for row in eligible_observations]
    risk_availability.extend(row["outcome_known_at"] for row in eligible_risks)
    risk_maximum_available_at = max(risk_availability)
    risk_commits = [row["available_commit_seq"] for row in eligible_observations]
    risk_commits.extend(row["available_commit_seq"] for row in eligible_risks)
    risk_as_of_commit_seq = max(risk_commits)

    known_risks = {
        (risk["event_id"], risk["horizon_us"]): risk for risk in eligible_risks
    }
    risk_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for anchor_key, anchor in eligible_anchors.items():
        representative = anchor["representative"]
        subject = {
            "subject_id": f"{anchor_key[0]}:{anchor_key[1]}",
            "outcome": known_risks.get(anchor_key),
        }
        for level in CONTEXT_LEVELS:
            risk_groups[_cell_key(representative, level)].append(subject)

    risk_surface_rows: list[dict[str, Any]] = []
    for key, subjects in sorted(risk_groups.items(), key=lambda item: item[0]):
        dimensions = _key_fields(key)
        known_outcomes = [
            subject["outcome"] for subject in subjects if subject["outcome"] is not None
        ]
        pending_subject_ids = sorted(
            subject["subject_id"] for subject in subjects if subject["outcome"] is None
        )
        risk_subject_ids = sorted(subject["subject_id"] for subject in subjects)
        right_censored_count = sum(
            row["censoring_kind"] != "exact_event" for row in known_outcomes
        )
        administrative_count = sum(
            row["censoring_kind"] == "right_administrative" for row in known_outcomes
        )
        source_gap_count = sum(
            row["censoring_kind"] == "right_source_gap" for row in known_outcomes
        )
        coverage_windows = sorted({row["coverage_window_id"] for row in known_outcomes})
        coverage_gaps = sorted(
            row["coverage_gap_id"]
            for row in known_outcomes
            if row["coverage_gap_id"] is not None
        )
        for event_kind in COMPETING_EVENT_KINDS:
            event_count = sum(
                row["censoring_kind"] == "exact_event" and row["event_kind"] == event_kind
                for row in known_outcomes
            )
            other_event_count = sum(
                row["censoring_kind"] == "exact_event" and row["event_kind"] != event_kind
                for row in known_outcomes
            )
            row = {
                "estimator_id": ESTIMATOR_ID,
                "estimator_version": ESTIMATOR_VERSION,
                "estimator_configuration_digest": CONFIGURATION_DIGEST,
                "input_snapshot_id": risk_snapshot_id,
                "input_logical_digest": risk_logical_digest,
                "fit_cutoff": fit_cutoff,
                "maximum_input_available_at": risk_maximum_available_at,
                "as_of_commit_seq": risk_as_of_commit_seq,
                **dimensions,
                "event_kind": event_kind,
                "risk_cohort_count": len(subjects),
                "terminal_known_count": len(known_outcomes),
                "pending_count": len(pending_subject_ids),
                "event_count": event_count,
                "other_competing_event_count": other_event_count,
                "right_censored_count": right_censored_count,
                "administrative_censored_count": administrative_count,
                "source_gap_censored_count": source_gap_count,
                "observed_cause_fraction_ppm": event_count * 1_000_000 // len(subjects),
                "coverage_ratio_ppm": (
                    (len(known_outcomes) - source_gap_count) * 1_000_000 // len(subjects)
                ),
                "coverage_window_ids": coverage_windows,
                "coverage_gap_ids": coverage_gaps,
                "risk_subject_ids": risk_subject_ids,
                "pending_subject_ids": pending_subject_ids,
                "claim_scope": RISK_CLAIM_SCOPE,
            }
            row["risk_cell_id"] = _stable_id(
                "competing-risk-surface",
                {
                    "schema": COMPETING_RISK_SURFACE_SCHEMA_ID,
                    "input_logical_digest": risk_logical_digest,
                    "fit_cutoff": fit_cutoff,
                    "dimensions": dimensions,
                    "event_kind": event_kind,
                },
            )
            row["risk_cell_digest"] = _record_digest(
                row, "risk_cell_id", "risk_cell_digest"
            )
            risk_surface_rows.append(row)

    risk_surface_rows.sort(key=lambda row: row["risk_cell_id"])
    return ResponseAtlas(
        response_surfaces=response_surface_table,
        competing_risks=pa.Table.from_pylist(
            risk_surface_rows, schema=COMPETING_RISK_SURFACE_SCHEMA
        ),
        risk_refusals=pa.Table.from_pylist([], schema=RISK_REFUSAL_SCHEMA),
    )
