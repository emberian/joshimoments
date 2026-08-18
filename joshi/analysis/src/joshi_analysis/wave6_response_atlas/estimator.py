from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean
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
    CONTEXT_LEVELS,
    RESPONSE_COMPONENT_OBSERVATION_SCHEMA,
    RESPONSE_COMPONENTS,
    RESPONSE_SURFACE_SCHEMA,
    RISK_CLAIM_SCOPE,
    RISK_OUTCOME_SCHEMA,
)

ESTIMATOR_ID = "wave6_point_in_time_signed_flow_response_atlas"
ESTIMATOR_VERSION = "1"
CONFIGURATION = {
    "aggregation": "arithmetic_mean_over_complete_anchor_decompositions",
    "components": list(RESPONSE_COMPONENTS),
    "contexts": list(CONTEXT_LEVELS),
    "competing_event_kinds": list(COMPETING_EVENT_KINDS),
    "missingness": "declared_gap_no_zero_or_partial_total_imputation",
    "risk_summary": "observed_cause_fraction_with_typed_right_censoring",
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


def response_atlas_input_identity(
    observations: pa.Table, risk_outcomes: pa.Table
) -> tuple[str, str]:
    components = {
        "observations": logical_table_sha256(observations, ["component_observation_id"]),
        "risk_outcomes": logical_table_sha256(risk_outcomes, ["risk_outcome_id"]),
    }
    logical_digest = qualified_sha256_bytes(canonical_json_bytes(components))
    snapshot_id = qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "input_contract": "joshi.analysis.wave6-response-atlas-input/v1",
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
]:
    if fit_cutoff.tzinfo is None:
        raise ManifestError("fit cutoff must be timezone-aware")
    if not observations.schema.equals(RESPONSE_COMPONENT_OBSERVATION_SCHEMA, check_metadata=True):
        raise ManifestError("response component observations violate their exact Arrow schema")
    if not risk_outcomes.schema.equals(RISK_OUTCOME_SCHEMA, check_metadata=True):
        raise ManifestError("risk outcomes violate their exact Arrow schema")

    rows = observations.to_pylist()
    observation_ids = [row["component_observation_id"] for row in rows]
    if len(observation_ids) != len(set(observation_ids)):
        raise ManifestError("response components duplicate occurrence identity")
    anchors: dict[tuple[str, int], dict[str, Any]] = {}
    event_invariants: dict[str, tuple[Any, ...]] = {}
    for row in rows:
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
    required_components = set(RESPONSE_COMPONENTS)
    for anchor in anchors.values():
        if set(anchor["components"]) != required_components:
            raise CoverageError(
                "response anchor has incomplete component closure; use an explicit gap row"
            )

    risk_rows = risk_outcomes.to_pylist()
    risk_ids = [row["risk_outcome_id"] for row in risk_rows]
    if len(risk_ids) != len(set(risk_ids)):
        raise ManifestError("risk outcomes duplicate occurrence identity")
    risks_by_anchor: dict[tuple[str, int], dict[str, Any]] = {}
    for row in risk_rows:
        anchor_key = (row["event_id"], row["horizon_us"])
        anchor = anchors.get(anchor_key)
        if anchor is None:
            raise ManifestError("risk outcome cites an unknown response anchor")
        if anchor_key in risks_by_anchor:
            raise ManifestError("response anchor duplicates its competing-risk outcome")
        _validate_risk(row, anchor["representative"])
        risks_by_anchor[anchor_key] = row
    if set(risks_by_anchor) != set(anchors):
        raise CoverageError("every response anchor requires an explicit event or censoring outcome")

    eligible_anchors = {
        key: anchor
        for key, anchor in anchors.items()
        if max(row["response_available_at"] for row in anchor["rows"]) <= fit_cutoff
    }
    if not eligible_anchors:
        raise ManifestError("fit cutoff leaves no complete point-in-time response anchors")
    eligible_observations = [
        row
        for key in sorted(eligible_anchors)
        for row in eligible_anchors[key]["rows"]
    ]
    eligible_risks = [
        row
        for key, row in sorted(risks_by_anchor.items())
        if key in eligible_anchors and row["outcome_known_at"] <= fit_cutoff
    ]
    return eligible_anchors, eligible_observations, eligible_risks


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


def build_response_atlas(
    observations: pa.Table,
    risk_outcomes: pa.Table,
    fit_cutoff: datetime,
) -> ResponseAtlas:
    eligible_anchors, eligible_observations, eligible_risks = _validate_inputs(
        observations, risk_outcomes, fit_cutoff
    )
    observation_table = pa.Table.from_pylist(
        eligible_observations, schema=RESPONSE_COMPONENT_OBSERVATION_SCHEMA
    )
    risk_table = pa.Table.from_pylist(eligible_risks, schema=RISK_OUTCOME_SCHEMA)
    input_snapshot_id, input_logical_digest = response_atlas_input_identity(
        observation_table, risk_table
    )
    availability = [row["response_available_at"] for row in eligible_observations]
    availability.extend(row["outcome_known_at"] for row in eligible_risks)
    maximum_available_at = max(availability)
    commits = [row["available_commit_seq"] for row in eligible_observations]
    commits.extend(row["available_commit_seq"] for row in eligible_risks)
    as_of_commit_seq = max(commits)

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
            row = {
                "estimator_id": ESTIMATOR_ID,
                "estimator_version": ESTIMATOR_VERSION,
                "estimator_configuration_digest": CONFIGURATION_DIGEST,
                "input_snapshot_id": input_snapshot_id,
                "input_logical_digest": input_logical_digest,
                "fit_cutoff": fit_cutoff,
                "maximum_input_available_at": maximum_available_at,
                "as_of_commit_seq": as_of_commit_seq,
                **dimensions,
                "component_kind": component,
                "response_estimate": fmean(values) if values else None,
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
                    "schema": "joshi.analysis.wave6-response-surface-cell/v1",
                    "input_logical_digest": input_logical_digest,
                    "fit_cutoff": fit_cutoff,
                    "dimensions": dimensions,
                    "component_kind": component,
                },
            )
            row["surface_cell_digest"] = _record_digest(
                row, "surface_cell_id", "surface_cell_digest"
            )
            surface_rows.append(row)

    anchor_by_key = eligible_anchors
    risk_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for risk in eligible_risks:
        anchor = anchor_by_key[(risk["event_id"], risk["horizon_us"])]
        representative = anchor["representative"]
        for level in CONTEXT_LEVELS:
            risk_groups[_cell_key(representative, level)].append(risk)

    risk_surface_rows: list[dict[str, Any]] = []
    for key, risks in sorted(risk_groups.items(), key=lambda item: item[0]):
        dimensions = _key_fields(key)
        right_censored_count = sum(
            row["censoring_kind"] != "exact_event" for row in risks
        )
        administrative_count = sum(
            row["censoring_kind"] == "right_administrative" for row in risks
        )
        source_gap_count = sum(row["censoring_kind"] == "right_source_gap" for row in risks)
        coverage_windows = sorted({row["coverage_window_id"] for row in risks})
        coverage_gaps = sorted(
            row["coverage_gap_id"] for row in risks if row["coverage_gap_id"] is not None
        )
        for event_kind in COMPETING_EVENT_KINDS:
            event_count = sum(
                row["censoring_kind"] == "exact_event" and row["event_kind"] == event_kind
                for row in risks
            )
            other_event_count = sum(
                row["censoring_kind"] == "exact_event" and row["event_kind"] != event_kind
                for row in risks
            )
            row = {
                "estimator_id": ESTIMATOR_ID,
                "estimator_version": ESTIMATOR_VERSION,
                "estimator_configuration_digest": CONFIGURATION_DIGEST,
                "input_snapshot_id": input_snapshot_id,
                "input_logical_digest": input_logical_digest,
                "fit_cutoff": fit_cutoff,
                "maximum_input_available_at": maximum_available_at,
                "as_of_commit_seq": as_of_commit_seq,
                **dimensions,
                "event_kind": event_kind,
                "risk_cohort_count": len(risks),
                "event_count": event_count,
                "other_competing_event_count": other_event_count,
                "right_censored_count": right_censored_count,
                "administrative_censored_count": administrative_count,
                "source_gap_censored_count": source_gap_count,
                "observed_cause_fraction_ppm": event_count * 1_000_000 // len(risks),
                "coverage_ratio_ppm": (len(risks) - source_gap_count) * 1_000_000 // len(risks),
                "coverage_window_ids": coverage_windows,
                "coverage_gap_ids": coverage_gaps,
                "claim_scope": RISK_CLAIM_SCOPE,
            }
            row["risk_cell_id"] = _stable_id(
                "competing-risk-surface",
                {
                    "schema": "joshi.analysis.wave6-competing-risk-surface-cell/v1",
                    "input_logical_digest": input_logical_digest,
                    "fit_cutoff": fit_cutoff,
                    "dimensions": dimensions,
                    "event_kind": event_kind,
                },
            )
            row["risk_cell_digest"] = _record_digest(
                row, "risk_cell_id", "risk_cell_digest"
            )
            risk_surface_rows.append(row)

    surface_rows.sort(key=lambda row: row["surface_cell_id"])
    risk_surface_rows.sort(key=lambda row: row["risk_cell_id"])
    return ResponseAtlas(
        response_surfaces=pa.Table.from_pylist(surface_rows, schema=RESPONSE_SURFACE_SCHEMA),
        competing_risks=pa.Table.from_pylist(
            risk_surface_rows, schema=COMPETING_RISK_SURFACE_SCHEMA
        ),
    )
