from __future__ import annotations

from datetime import timedelta

import pyarrow as pa
import pytest

from joshi_analysis.errors import CoverageError, ManifestError, TemporalLeakageError
from joshi_analysis.wave6_response_atlas.contracts import (
    COMPETING_RISK_SURFACE_SCHEMA,
    RESPONSE_COMPONENT_OBSERVATION_SCHEMA,
    RESPONSE_SURFACE_SCHEMA,
    RISK_OUTCOME_SCHEMA,
)
from joshi_analysis.wave6_response_atlas.estimator import build_response_atlas
from joshi_analysis.wave6_response_atlas.synthetic import synthetic_response_atlas_inputs


def _table(rows: list[dict[str, object]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=RESPONSE_COMPONENT_OBSERVATION_SCHEMA)


def _risk_table(rows: list[dict[str, object]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=RISK_OUTCOME_SCHEMA)


def _wallet_a_short(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row["venue_id"] == "venue:pump-amm"
        and row["context_level"] == "wallet"
        and row["context_id"] == "wallet-a"
        and row["horizon_us"] == 60_000_000
    ]


def test_response_surface_is_conditioned_and_exactly_component_decomposed() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    atlas = build_response_atlas(observations, risks, cutoff)
    assert atlas.response_surfaces.schema.equals(RESPONSE_SURFACE_SCHEMA, check_metadata=True)
    assert atlas.competing_risks.schema.equals(COMPETING_RISK_SURFACE_SCHEMA, check_metadata=True)

    rows = _wallet_a_short(atlas.response_surfaces.to_pylist())
    estimates = {row["component_kind"]: row["response_estimate"] for row in rows}
    assert estimates == {
        "same_wallet": 11.5,
        "same_cluster_other_wallet": 21.5,
        "external": 31.5,
        "total": 64.5,
    }
    assert estimates["total"] == sum(
        estimates[component]
        for component in ("same_wallet", "same_cluster_other_wallet", "external")
    )
    assert all(row["support_anchor_count"] == 2 for row in rows)
    assert all("not_causal_or_strategy_claim" in row["claim_scope"] for row in rows)
    assert {row["context_level"] for row in atlas.response_surfaces.to_pylist()} == {
        "wallet",
        "cluster",
        "caller_class",
    }


def test_declared_gaps_do_not_become_zero_or_partial_total_imputation() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = build_response_atlas(observations, risks, cutoff).response_surfaces.to_pylist()
    wallet_b_long = [
        row
        for row in rows
        if row["context_level"] == "wallet"
        and row["context_id"] == "wallet-b"
        and row["horizon_us"] == 300_000_000
    ]
    total = next(row for row in wallet_b_long if row["component_kind"] == "total")
    external = next(row for row in wallet_b_long if row["component_kind"] == "external")
    assert total["support_anchor_count"] == 2
    assert total["complete_anchor_count"] == 1
    assert total["coverage_ratio_ppm"] == 500_000
    assert total["decomposition_status"] == "complete_support_with_declared_gaps"
    assert external["component_observed_count"] == 1
    assert external["component_gap_count"] == 1
    assert external["coverage_gap_ids"] == [
        "gap:atlas-component:atlas-event-004:300000000:external"
    ]


def test_competing_events_and_censoring_remain_distinct() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = _wallet_a_short(
        build_response_atlas(observations, risks, cutoff).competing_risks.to_pylist()
    )
    migration = next(row for row in rows if row["event_kind"] == "migration")
    liquidity = next(row for row in rows if row["event_kind"] == "liquidity_exhaustion")
    assert migration["risk_cohort_count"] == 2
    assert migration["event_count"] == 1
    assert migration["right_censored_count"] == 1
    assert migration["administrative_censored_count"] == 1
    assert migration["source_gap_censored_count"] == 0
    assert migration["observed_cause_fraction_ppm"] == 500_000
    assert liquidity["event_count"] == 0
    assert liquidity["other_competing_event_count"] == 1
    assert all("not_causal_probability_or_strategy_claim" in row["claim_scope"] for row in rows)


def test_future_responses_and_outcomes_are_excluded_from_as_known_fit() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    observation_rows = observations.to_pylist()
    for row in observation_rows:
        if row["event_id"] == "atlas-event-002" and row["horizon_us"] == 60_000_000:
            row["response_available_at"] = cutoff + timedelta(seconds=1)
    changed = build_response_atlas(_table(observation_rows), risks, cutoff)
    physically_absent_observations = [
        row
        for row in observations.to_pylist()
        if not (row["event_id"] == "atlas-event-002" and row["horizon_us"] == 60_000_000)
    ]
    physically_absent_risks = [
        row
        for row in risks.to_pylist()
        if not (row["event_id"] == "atlas-event-002" and row["horizon_us"] == 60_000_000)
    ]
    without_future_anchor = build_response_atlas(
        _table(physically_absent_observations),
        _risk_table(physically_absent_risks),
        cutoff,
    )
    assert (
        changed.response_surfaces.to_pylist()
        == without_future_anchor.response_surfaces.to_pylist()
    )
    assert changed.competing_risks.to_pylist() == without_future_anchor.competing_risks.to_pylist()
    total = next(
        row
        for row in _wallet_a_short(changed.response_surfaces.to_pylist())
        if row["component_kind"] == "total"
    )
    assert total["support_anchor_count"] == 1
    assert total["response_estimate"] == 63.0

    risk_rows = risks.to_pylist()
    for row in risk_rows:
        if row["event_id"] == "atlas-event-001" and row["horizon_us"] == 60_000_000:
            row["outcome_known_at"] = cutoff + timedelta(seconds=1)
    changed_risks = build_response_atlas(observations, _risk_table(risk_rows), cutoff)
    risk_cell = next(
        row
        for row in _wallet_a_short(changed_risks.competing_risks.to_pylist())
        if row["event_kind"] == "migration"
    )
    assert risk_cell["risk_cohort_count"] == 1
    assert risk_cell["event_count"] == 0


def test_future_context_version_fails_closed() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = observations.to_pylist()
    rows[0]["lifecycle_available_at"] = rows[0]["information_cutoff"] + timedelta(seconds=1)
    with pytest.raises(TemporalLeakageError, match="lifecycle version was unavailable"):
        build_response_atlas(_table(rows), risks, cutoff)


def test_incomplete_component_and_risk_coverage_fail_closed() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    with pytest.raises(CoverageError, match="incomplete component closure"):
        build_response_atlas(observations.slice(1), risks, cutoff)
    with pytest.raises(CoverageError, match="every response anchor"):
        build_response_atlas(observations, risks.slice(1), cutoff)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("response_unit", "quote_asset_atoms", "response.*base_asset_atoms"),
        ("topology_epoch", "topology-adversarial", "mixes.*topology"),
    ],
)
def test_mixed_units_or_topology_within_one_event_fail_closed(
    field: str, replacement: str, message: str
) -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = observations.to_pylist()
    rows[0][field] = replacement
    with pytest.raises(ManifestError, match=message):
        build_response_atlas(_table(rows), risks, cutoff)


def test_nonfinite_and_boolean_numeric_columns_are_not_coerced() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    response_index = observations.schema.get_field_index("response_signed_flow_atoms")
    nonfinite_values = [float(value or 0) for value in observations[response_index].to_pylist()]
    nonfinite_values[0] = float("inf")
    nonfinite = observations.set_column(
        response_index,
        "response_signed_flow_atoms",
        pa.array(nonfinite_values, type=pa.float64()),
    )
    with pytest.raises(ManifestError, match="exact Arrow schema"):
        build_response_atlas(nonfinite, risks, cutoff)

    size_index = observations.schema.get_field_index("mark_size_atoms")
    boolean_numeric = observations.set_column(
        size_index,
        "mark_size_atoms",
        pa.array([True] * observations.num_rows, type=pa.bool_()),
    )
    with pytest.raises(ManifestError, match="exact Arrow schema"):
        build_response_atlas(boolean_numeric, risks, cutoff)


def test_duplicate_occurrence_and_semantic_component_identities_are_rejected() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = observations.to_pylist()
    rows.append(dict(rows[0]))
    with pytest.raises(ManifestError, match="duplicate occurrence identity"):
        build_response_atlas(_table(rows), risks, cutoff)

    rows = observations.to_pylist()
    duplicate_component = dict(rows[0])
    duplicate_component["component_observation_id"] = "atlas-component:semantic-duplicate"
    rows.append(duplicate_component)
    with pytest.raises(ManifestError, match="duplicates a decomposition component"):
        build_response_atlas(_table(rows), risks, cutoff)


def test_ids_and_row_order_are_deterministic_under_input_permutation() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    baseline = build_response_atlas(observations, risks, cutoff)
    reversed_observations = observations.take(
        pa.array(list(reversed(range(observations.num_rows))), type=pa.int64())
    )
    reversed_risks = risks.take(pa.array(list(reversed(range(risks.num_rows))), type=pa.int64()))
    permuted = build_response_atlas(reversed_observations, reversed_risks, cutoff)
    assert baseline.response_surfaces.to_pylist() == permuted.response_surfaces.to_pylist()
    assert baseline.competing_risks.to_pylist() == permuted.competing_risks.to_pylist()
    surface_ids = baseline.response_surfaces["surface_cell_id"].to_pylist()
    risk_ids = baseline.competing_risks["risk_cell_id"].to_pylist()
    assert len(surface_ids) == len(set(surface_ids))
    assert len(risk_ids) == len(set(risk_ids))
