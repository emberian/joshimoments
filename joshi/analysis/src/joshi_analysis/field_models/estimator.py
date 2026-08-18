from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import pyarrow as pa

from ..canonical import canonical_json_bytes, iso_utc, logical_table_sha256, qualified_sha256_bytes
from ..errors import CoverageError, ManifestError, TemporalLeakageError
from .contracts import (
    FIELD_CLAIM_SCOPE,
    FIELD_OBSERVABLE_SCHEMA,
    GRAPH_EDGE_SCHEMA,
    VENUE_RESPONSE_SCHEMA,
)

ESTIMATOR_ID = "bitemporal_multilayer_graph_and_reserve_geometry"
ESTIMATOR_VERSION = "1"
CONFIGURATION = {
    "graph": "oriented_incidence_hodge_with_declared_cycle_basis",
    "venue": "local_reserve_susceptibility_realized_impact_and_recovery",
    "missingness": "explicit_gap_no_zero_imputation",
    "topology": "fit_each_epoch_independently",
}
CONFIGURATION_DIGEST = qualified_sha256_bytes(canonical_json_bytes(CONFIGURATION))


def field_input_identity(edges: pa.Table, venues: pa.Table) -> tuple[str, str]:
    components = {
        "edges": logical_table_sha256(edges, ["edge_observation_id"]),
        "venues": logical_table_sha256(venues, ["venue_response_id"]),
    }
    logical = qualified_sha256_bytes(canonical_json_bytes(components))
    return qualified_sha256_bytes(
        canonical_json_bytes(
            {"fixture_contract": "joshi.analysis.field-synthetic-input/v1", "logical": logical}
        )
    ), logical


def _validate_temporal(row: dict[str, Any], fit_cutoff: datetime) -> bool:
    if not row["valid_lower"] <= row["observed_at"] < row["valid_upper"]:
        raise ManifestError("field observation is outside its valid-time interval")
    if not row["topology_valid_lower"] <= row["observed_at"] < row["topology_valid_upper"]:
        raise TemporalLeakageError("selected topology version is not valid at observation time")
    if row["topology_available_at"] > row["information_cutoff"]:
        raise TemporalLeakageError("selected topology version was unavailable at information cut")
    if (
        row["topology_retracted_at"] is not None
        and row["topology_retracted_at"] <= row["information_cutoff"]
    ):
        raise TemporalLeakageError("selected topology version was retracted by information cut")
    if row["available_at"] < row["observed_at"]:
        raise TemporalLeakageError("field value became available before observation")
    if row["topology_version_id"] == "":
        raise ManifestError("field observation lacks selected topology version identity")
    return row["available_at"] <= fit_cutoff


def _validate_inputs(
    edges: pa.Table, venues: pa.Table, fit_cutoff: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not edges.schema.equals(GRAPH_EDGE_SCHEMA, check_metadata=True):
        raise ManifestError("graph field inputs violate their exact Arrow schema")
    if not venues.schema.equals(VENUE_RESPONSE_SCHEMA, check_metadata=True):
        raise ManifestError("venue field inputs violate their exact Arrow schema")
    edge_rows = edges.to_pylist()
    venue_rows = venues.to_pylist()
    for rows, key in ((edge_rows, "edge_observation_id"), (venue_rows, "venue_response_id")):
        ids = [row[key] for row in rows]
        if len(ids) != len(set(ids)):
            raise ManifestError(f"field inputs duplicate {key}")
    eligible_edges = []
    for row in edge_rows:
        if row["source_node_id"] == row["target_node_id"]:
            raise ManifestError("self loops are outside the prototype field contract")
        if (row["cycle_id"] is None) != (row["cycle_orientation"] is None):
            raise ManifestError("cycle identity and orientation must occur together")
        if row["cycle_orientation"] not in {None, -1, 1}:
            raise ManifestError("cycle orientation must be -1 or 1")
        if row["coverage_status"] == "observed":
            if row["flow_value"] is None or row["coverage_gap_id"] is not None:
                raise CoverageError("observed field edge lacks flow or cites a gap")
        elif row["coverage_status"] == "gap":
            if row["flow_value"] is not None or row["coverage_gap_id"] is None:
                raise CoverageError("field gap must retain null flow and exact gap identity")
        else:
            raise CoverageError("unknown field edge coverage status")
        if _validate_temporal(row, fit_cutoff):
            eligible_edges.append(row)
    eligible_venues = []
    for row in venue_rows:
        if row["coverage_status"] != "observed" or row["coverage_gap_id"] is not None:
            raise CoverageError("venue response prototype requires witnessed reserve states")
        reserves = (
            "baseline_base_atoms",
            "baseline_quote_atoms",
            "shock_base_atoms",
            "shock_quote_atoms",
            "recovery_base_atoms",
            "recovery_quote_atoms",
        )
        if any(row[field] <= 0 for field in reserves):
            raise ManifestError("venue reserve geometry requires positive exact atom counts")
        if row["signed_flow_base_atoms"] == 0:
            raise ManifestError("venue impact denominator cannot be fabricated zero")
        if _validate_temporal(row, fit_cutoff):
            eligible_venues.append(row)
    if not eligible_edges and not eligible_venues:
        raise ManifestError("fit cutoff leaves no point-in-time field observations")
    return eligible_edges, eligible_venues


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [[*row, value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(len(vector)):
        pivot = max(range(column, len(vector)), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            continue
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(len(vector)):
            if row == column:
                continue
            scale = augmented[row][column]
            augmented[row] = [
                left - scale * right
                for left, right in zip(augmented[row], augmented[column], strict=True)
            ]
    return [row[-1] if abs(row[index]) > 1e-12 else 0.0 for index, row in enumerate(augmented)]


def _hodge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row for row in rows if row["coverage_status"] == "observed"]
    nodes = sorted({row[key] for row in observed for key in ("source_node_id", "target_node_id")})
    node_index = {node: index for index, node in enumerate(nodes)}
    flows = [float(row["flow_value"]) for row in observed]
    incidence = [[0.0 for _ in observed] for _ in nodes]
    for edge_index, row in enumerate(observed):
        incidence[node_index[row["source_node_id"]]][edge_index] = -1.0
        incidence[node_index[row["target_node_id"]]][edge_index] = 1.0
    divergence = [
        sum(value * flow for value, flow in zip(line, flows, strict=True)) for line in incidence
    ]
    if len(nodes) > 1:
        reduced = incidence[:-1]
        laplacian = [
            [sum(left * right for left, right in zip(a, b, strict=True)) for b in reduced]
            for a in reduced
        ]
        potential = [*_solve(laplacian, divergence[:-1]), 0.0]
    else:
        potential = [0.0]
    gradient = [
        potential[node_index[row["target_node_id"]]] - potential[node_index[row["source_node_id"]]]
        for row in observed
    ]
    residual = [flow - component for flow, component in zip(flows, gradient, strict=True)]
    cycle_ids = sorted({row["cycle_id"] for row in observed if row["cycle_id"] is not None})
    basis = [
        [
            float(row["cycle_orientation"] or 0) if row["cycle_id"] == cycle_id else 0.0
            for row in observed
        ]
        for cycle_id in cycle_ids
    ]
    if basis:
        gram = [[sum(x * y for x, y in zip(a, b, strict=True)) for b in basis] for a in basis]
        rhs = [sum(x * y for x, y in zip(a, residual, strict=True)) for a in basis]
        coefficients = _solve(gram, rhs)
        curl = [
            sum(c * vector[i] for c, vector in zip(coefficients, basis, strict=True))
            for i in range(len(observed))
        ]
    else:
        curl = [0.0 for _ in observed]
    harmonic = [value - curl_value for value, curl_value in zip(residual, curl, strict=True)]
    circulation = {
        cycle_id: sum(
            float(row["flow_value"]) * float(row["cycle_orientation"])
            for row in observed
            if row["cycle_id"] == cycle_id
        )
        for cycle_id in cycle_ids
    }
    return {
        "observed": observed,
        "nodes": nodes,
        "divergence": divergence,
        "gradient": gradient,
        "curl": curl,
        "harmonic": harmonic,
        "circulation": circulation,
    }


def estimate_dynamic_fields(edges: pa.Table, venues: pa.Table, fit_cutoff: datetime) -> pa.Table:
    edge_rows, venue_rows = _validate_inputs(edges, venues, fit_cutoff)
    eligible_edge_table = pa.Table.from_pylist(edge_rows, schema=GRAPH_EDGE_SCHEMA)
    eligible_venue_table = pa.Table.from_pylist(venue_rows, schema=VENUE_RESPONSE_SCHEMA)
    snapshot_id, logical_digest = field_input_identity(eligible_edge_table, eligible_venue_table)
    maximum_available = max(row["available_at"] for row in [*edge_rows, *venue_rows])
    maximum_commit = max(row["available_commit_seq"] for row in [*edge_rows, *venue_rows])
    outputs: list[dict[str, Any]] = []

    def emit(
        *,
        layer: str,
        topology: str,
        topology_version: str,
        entity_kind: str,
        entity_id: str,
        observable: str,
        value: float | None,
        unit: str,
        support_rows: list[dict[str, Any]],
        carrier_kind: str,
        carrier_id: str,
        candidate_id: str | None = None,
        venue_id: str | None = None,
    ) -> None:
        gaps = [row for row in support_rows if row["coverage_status"] == "gap"]
        observed = [row for row in support_rows if row["coverage_status"] == "observed"]
        ratio = len(observed) * 1_000_000 // len(support_rows)
        radius = abs(value or 0.0) * len(gaps) / max(1, len(observed))
        row = {
            "field_observable_occurrence_id": f"field-observable:{len(outputs) + 1:04d}",
            "estimator_id": ESTIMATOR_ID,
            "estimator_version": ESTIMATOR_VERSION,
            "estimator_configuration_digest": CONFIGURATION_DIGEST,
            "input_snapshot_id": snapshot_id,
            "input_logical_digest": logical_digest,
            "fit_cutoff": fit_cutoff,
            "maximum_input_available_at": maximum_available,
            "as_of_commit_seq": maximum_commit,
            "layer_kind": layer,
            "carrier_kind": carrier_kind,
            "carrier_id": carrier_id,
            "topology_epoch": topology,
            "topology_version_id": topology_version,
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "candidate_id": candidate_id,
            "venue_id": venue_id,
            "observable_kind": observable,
            "value": value,
            "value_unit": unit,
            "uncertainty_lower": None,
            "uncertainty_upper": None,
            "uncertainty_method": "not_estimated_by_deterministic_prototype",
            "gap_sensitivity_lower": None if value is None else value - radius,
            "gap_sensitivity_upper": None if value is None else value + radius,
            "gap_sensitivity_method": "zero_to_observed_magnitude_bound_not_uncertainty_interval",
            "support_count": len(support_rows),
            "observed_count": len(observed),
            "gap_count": len(gaps),
            "coverage_ratio_ppm": ratio,
            "coverage_window_ids": sorted({row["coverage_window_id"] for row in support_rows}),
            "coverage_gap_ids": sorted(row["coverage_gap_id"] for row in gaps),
            "topology_boundary_status": (
                "initial_epoch"
                if topology == "topology-1"
                else "changed_topology_no_cross_epoch_fit"
            ),
            "claim_scope": FIELD_CLAIM_SCOPE,
        }
        row["field_observable_digest"] = qualified_sha256_bytes(
            canonical_json_bytes(
                {
                    key: iso_utc(value) if isinstance(value, datetime) else value
                    for key, value in row.items()
                    if key != "field_observable_occurrence_id"
                }
            )
        )
        outputs.append(row)

    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in edge_rows:
        groups[
            (
                row["layer_kind"],
                row["topology_epoch"],
                row["topology_version_id"],
                row["carrier_kind"],
                row["carrier_id"],
                row["flow_unit"],
            )
        ].append(row)
    for (layer, topology, version, carrier_kind, carrier_id, _flow_unit), rows in sorted(
        groups.items()
    ):
        decomposition = _hodge(rows)
        if not decomposition["observed"]:
            emit(
                layer=layer,
                topology=topology,
                topology_version=version,
                entity_kind="topology_epoch",
                entity_id=topology,
                observable="insufficient_observed_support",
                value=None,
                unit=rows[0]["flow_unit"],
                support_rows=rows,
                carrier_kind=carrier_kind,
                carrier_id=carrier_id,
            )
            continue
        for node, value in zip(decomposition["nodes"], decomposition["divergence"], strict=True):
            emit(
                layer=layer,
                topology=topology,
                topology_version=version,
                entity_kind="node",
                entity_id=node,
                observable="graph_divergence",
                value=value,
                unit=rows[0]["flow_unit"],
                support_rows=rows,
                carrier_kind=carrier_kind,
                carrier_id=carrier_id,
            )
        for cycle, value in decomposition["circulation"].items():
            emit(
                layer=layer,
                topology=topology,
                topology_version=version,
                entity_kind="cycle",
                entity_id=cycle,
                observable="cycle_circulation",
                value=value,
                unit=rows[0]["flow_unit"],
                support_rows=rows,
                carrier_kind=carrier_kind,
                carrier_id=carrier_id,
            )
        for component in ("gradient", "curl", "harmonic"):
            for edge, value in zip(
                decomposition["observed"], decomposition[component], strict=True
            ):
                emit(
                    layer=layer,
                    topology=topology,
                    topology_version=version,
                    entity_kind="edge",
                    entity_id=edge["edge_id"],
                    observable=f"hodge_{component}_component",
                    value=value,
                    unit=rows[0]["flow_unit"],
                    support_rows=rows,
                    carrier_kind=carrier_kind,
                    carrier_id=carrier_id,
                )
            energy = sum(value * value for value in decomposition[component])
            emit(
                layer=layer,
                topology=topology,
                topology_version=version,
                entity_kind="topology_epoch",
                entity_id=topology,
                observable=f"hodge_{component}_squared_norm",
                value=energy,
                unit=f"{rows[0]['flow_unit']}^2",
                support_rows=rows,
                carrier_kind=carrier_kind,
                carrier_id=carrier_id,
            )

    for row in venue_rows:
        baseline_price = float(row["baseline_quote_atoms"] / row["baseline_base_atoms"])
        shock_price = float(row["shock_quote_atoms"] / row["shock_base_atoms"])
        recovery_price = float(row["recovery_quote_atoms"] / row["recovery_base_atoms"])
        if (
            row["liquidity_model"] != "synthetic_constant_product_xy_eq_k"
            or row["formula_version"] != "synthetic_cpmm/v1"
        ):
            raise ManifestError(
                "prototype susceptibility is scoped only to its synthetic CPMM profile"
            )
        susceptibility = 2.0 / float(row["baseline_base_atoms"])
        impact = (
            (shock_price / baseline_price - 1.0) * 1_000_000 / abs(row["signed_flow_base_atoms"])
        )
        shock_distance = abs(shock_price - baseline_price)
        resilience = (
            1_000_000.0
            if shock_distance == 0
            else (1.0 - abs(recovery_price - baseline_price) / shock_distance) * 1_000_000
        )
        for observable, value, unit in (
            ("synthetic_cpmm_local_price_susceptibility", susceptibility, "inverse_base_atoms"),
            ("observed_price_response_per_flow", impact, "return_ppm_per_base_atom"),
            ("recovery_resilience", resilience, "ppm"),
        ):
            emit(
                layer="venue_reserve_geometry",
                topology=row["topology_epoch"],
                topology_version=row["topology_version_id"],
                entity_kind="venue_candidate",
                entity_id=row["venue_response_id"],
                observable=observable,
                value=value,
                unit=unit,
                support_rows=[row],
                carrier_kind="asset_pair",
                carrier_id=f"{row['base_asset_id']}/{row['quote_asset_id']}",
                candidate_id=row["candidate_id"],
                venue_id=row["venue_id"],
            )
    return pa.Table.from_pylist(outputs, schema=FIELD_OBSERVABLE_SCHEMA)
