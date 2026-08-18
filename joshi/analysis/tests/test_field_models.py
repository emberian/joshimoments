from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from joshi_analysis.errors import TemporalLeakageError
from joshi_analysis.field_models.contracts import GRAPH_EDGE_SCHEMA
from joshi_analysis.field_models.estimator import estimate_dynamic_fields
from joshi_analysis.field_models.job import run_field_prototype_job
from joshi_analysis.field_models.synthetic import synthetic_field_inputs


def test_triangle_recovers_divergence_circulation_and_hodge_components() -> None:
    edges, venues, cutoff = synthetic_field_inputs()
    rows = estimate_dynamic_fields(edges, venues, cutoff).to_pylist()
    wallet = [
        row
        for row in rows
        if row["layer_kind"] == "wallet_flow" and row["topology_epoch"] == "topology-1"
    ]
    assert {row["value"] for row in wallet if row["observable_kind"] == "graph_divergence"} == {0.0}
    assert (
        next(row for row in wallet if row["observable_kind"] == "cycle_circulation")["value"]
        == 90.0
    )
    assert (
        next(row for row in wallet if row["observable_kind"] == "hodge_curl_squared_norm")["value"]
        == 2_700.0
    )
    assert (
        next(row for row in wallet if row["observable_kind"] == "hodge_harmonic_squared_norm")[
            "value"
        ]
        == 0.0
    )
    attention_divergence = {
        row["entity_id"]: row["value"]
        for row in rows
        if row["layer_kind"] == "attention_flow"
        and row["topology_epoch"] == "topology-1"
        and row["observable_kind"] == "graph_divergence"
    }
    assert attention_divergence == {"A": -10.0, "B": 10.0, "C": 0.0}


def test_topology_epochs_and_layers_never_collapse_to_pressure() -> None:
    edges, venues, cutoff = synthetic_field_inputs()
    rows = estimate_dynamic_fields(edges, venues, cutoff).to_pylist()
    assert {row["layer_kind"] for row in rows} >= {
        "wallet_flow",
        "attention_flow",
        "venue_reserve_geometry",
    }
    assert not any("pressure" in row["observable_kind"] for row in rows)
    assert all(
        row["topology_boundary_status"] == "changed_topology_no_cross_epoch_fit"
        for row in rows
        if row["topology_epoch"] == "topology-2"
    )
    gap_rows = [
        row
        for row in rows
        if row["layer_kind"] == "attention_flow" and row["topology_epoch"] == "topology-2"
    ]
    assert gap_rows and all(row["coverage_ratio_ppm"] == 0 for row in gap_rows)
    assert all(row["value"] is None for row in gap_rows if row["support_count"] == 1)


def test_topology_version_must_be_available_as_known() -> None:
    edges, venues, cutoff = synthetic_field_inputs()
    rows = edges.to_pylist()
    rows[0]["topology_available_at"] = rows[0]["information_cutoff"] + timedelta(seconds=1)
    with pytest.raises(TemporalLeakageError, match="topology version was unavailable"):
        estimate_dynamic_fields(
            pa.Table.from_pylist(rows, schema=GRAPH_EDGE_SCHEMA), venues, cutoff
        )


def test_future_edge_does_not_change_eligible_field_identity() -> None:
    edges, venues, cutoff = synthetic_field_inputs()
    baseline = estimate_dynamic_fields(edges, venues, cutoff)
    rows = edges.to_pylist()
    future = dict(rows[0])
    future["edge_observation_id"] = "field-edge:future-unavailable"
    future["available_at"] = cutoff + timedelta(seconds=1)
    rows.append(future)
    changed = estimate_dynamic_fields(
        pa.Table.from_pylist(rows, schema=GRAPH_EDGE_SCHEMA), venues, cutoff
    )
    assert baseline.to_pylist() == changed.to_pylist()


def test_venue_susceptibility_impact_and_resilience_are_explicit() -> None:
    edges, venues, cutoff = synthetic_field_inputs()
    rows = estimate_dynamic_fields(edges, venues, cutoff).to_pylist()
    venue = [row for row in rows if row["entity_id"] == "venue-response:1"]
    by_kind = {row["observable_kind"]: row["value"] for row in venue}
    assert by_kind["synthetic_cpmm_local_price_susceptibility"] == pytest.approx(0.002)
    assert by_kind["observed_price_response_per_flow"] == pytest.approx(2_222.22222222)
    assert by_kind["recovery_resilience"] == pytest.approx(862_244.897959)


def test_field_job_is_byte_deterministic(tmp_path: Path) -> None:
    first = run_field_prototype_job(tmp_path / "a")
    second = run_field_prototype_job(tmp_path / "b")
    assert first.name == second.name
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "field_observables.parquet").read_bytes() == (
        second / "field_observables.parquet"
    ).read_bytes()
