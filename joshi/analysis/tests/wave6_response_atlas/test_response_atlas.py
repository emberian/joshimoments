from __future__ import annotations

from datetime import timedelta
from fractions import Fraction

import pyarrow as pa
import pytest

from joshi_analysis.errors import CoverageError, ManifestError, TemporalLeakageError
from joshi_analysis.wave6_response_atlas.contracts import (
    COMPETING_RISK_SURFACE_SCHEMA,
    RESPONSE_COMPONENT_OBSERVATION_SCHEMA,
    RESPONSE_SURFACE_SCHEMA,
    RISK_OUTCOME_SCHEMA,
    RISK_REFUSAL_SCHEMA,
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


def _exact_mean(row: dict[str, object]) -> Fraction | None:
    numerator = row["response_mean_numerator_atoms"]
    denominator = row["response_mean_denominator"]
    if numerator is None:
        assert denominator is None
        return None
    assert isinstance(numerator, str)
    assert isinstance(denominator, int)
    return Fraction(int(numerator), denominator)


def test_response_surface_is_conditioned_and_exactly_component_decomposed() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    atlas = build_response_atlas(observations, risks, cutoff)
    assert atlas.response_surfaces.schema.equals(RESPONSE_SURFACE_SCHEMA, check_metadata=True)
    assert atlas.competing_risks.schema.equals(COMPETING_RISK_SURFACE_SCHEMA, check_metadata=True)
    assert atlas.risk_refusals.schema.equals(RISK_REFUSAL_SCHEMA, check_metadata=True)
    assert atlas.risk_refusals.num_rows == 0

    rows = _wallet_a_short(atlas.response_surfaces.to_pylist())
    estimates = {row["component_kind"]: _exact_mean(row) for row in rows}
    assert estimates == {
        "same_wallet": Fraction(23, 2),
        "same_cluster_other_wallet": Fraction(43, 2),
        "external": Fraction(63, 2),
        "total": Fraction(129, 2),
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
            if row["component_kind"] == "same_wallet":
                row["response_unit"] = "future-invalid-unit"
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
    assert _exact_mean(total) == 63

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
    assert risk_cell["risk_cohort_count"] == 2
    assert risk_cell["terminal_known_count"] == 1
    assert risk_cell["pending_count"] == 1
    assert risk_cell["event_count"] == 0


def test_future_invalid_terminal_bytes_are_pending_and_do_not_poison_the_cut() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    risk_rows = risks.to_pylist()
    for row in risk_rows:
        if row["event_id"] == "atlas-event-001" and row["horizon_us"] == 60_000_000:
            row["outcome_known_at"] = cutoff + timedelta(seconds=1)
            row["event_kind"] = "future-invalid-event-kind"
    with_future = build_response_atlas(observations, _risk_table(risk_rows), cutoff)
    without_future = build_response_atlas(
        observations,
        _risk_table(
            [
                row
                for row in risks.to_pylist()
                if not (
                    row["event_id"] == "atlas-event-001"
                    and row["horizon_us"] == 60_000_000
                )
            ]
        ),
        cutoff,
    )
    assert with_future.response_surfaces.to_pylist() == without_future.response_surfaces.to_pylist()
    assert with_future.competing_risks.to_pylist() == without_future.competing_risks.to_pylist()


def test_future_only_anchor_cannot_change_risk_membership_or_refusal_until_admitted() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    future_event_id = "atlas-event-future-only"
    future_rows = []
    for row in observations.to_pylist():
        if row["event_id"] == "atlas-event-001" and row["horizon_us"] == 60_000_000:
            future = dict(row)
            future["event_id"] = future_event_id
            future["component_observation_id"] = (
                f"atlas-component:{future_event_id}:60000000:{row['component_kind']}"
            )
            future["coverage_window_id"] = f"coverage:{future_event_id}:60000000"
            future["response_available_at"] = cutoff + timedelta(minutes=1)
            future_rows.append(future)

    risk_rows = risks.to_pylist()
    future_risk = next(
        dict(row)
        for row in risk_rows
        if row["event_id"] == "atlas-event-001" and row["horizon_us"] == 60_000_000
    )
    future_risk["risk_outcome_id"] = f"atlas-risk:{future_event_id}:60000000"
    future_risk["event_id"] = future_event_id
    future_risk["event_kind"] = "invalid-until-response-anchor-is-admitted"
    risk_rows.append(future_risk)

    same_risks = _risk_table(risk_rows)
    physically_absent = build_response_atlas(observations, same_risks, cutoff)
    future_present = build_response_atlas(
        _table([*observations.to_pylist(), *future_rows]), same_risks, cutoff
    )
    assert (
        future_present.response_surfaces.to_pylist()
        == physically_absent.response_surfaces.to_pylist()
    )
    assert (
        future_present.competing_risks.to_pylist()
        == physically_absent.competing_risks.to_pylist()
    )
    assert future_present.risk_refusals.to_pylist() == physically_absent.risk_refusals.to_pylist()
    assert future_present.risk_refusals.num_rows == 0

    refusing_rows = [dict(row) for row in risk_rows]
    admitted_invalid = next(
        row
        for row in refusing_rows
        if row["event_id"] == "atlas-event-002" and row["horizon_us"] == 60_000_000
    )
    admitted_invalid["censoring_kind"] = "invalid-known-censoring-kind"
    refusing_risks = _risk_table(refusing_rows)
    absent_refused = build_response_atlas(observations, refusing_risks, cutoff)
    present_refused = build_response_atlas(
        _table([*observations.to_pylist(), *future_rows]), refusing_risks, cutoff
    )
    assert (
        present_refused.response_surfaces.to_pylist()
        == absent_refused.response_surfaces.to_pylist()
    )
    assert present_refused.competing_risks.to_pylist() == absent_refused.competing_risks.to_pylist()
    assert present_refused.risk_refusals.to_pylist() == absent_refused.risk_refusals.to_pylist()
    assert present_refused.risk_refusals.num_rows == 1

    later = build_response_atlas(
        _table([*observations.to_pylist(), *future_rows]),
        same_risks,
        cutoff + timedelta(minutes=2),
    )
    later_total = next(
        row
        for row in _wallet_a_short(later.response_surfaces.to_pylist())
        if row["component_kind"] == "total"
    )
    assert later_total["support_anchor_count"] == 3
    assert later.competing_risks.num_rows == 0
    assert later.risk_refusals.num_rows == 1
    assert later.risk_refusals.to_pylist()[0]["reason_code"] == (
        "unregistered_competing_event_kind"
    )


def test_outcome_label_changes_cannot_change_response_artifact_identity() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    baseline = build_response_atlas(observations, risks, cutoff)
    changed_rows = risks.to_pylist()
    target = next(
        row
        for row in changed_rows
        if row["event_id"] == "atlas-event-001" and row["horizon_us"] == 60_000_000
    )
    target["event_kind"] = "venue_exit"
    changed = build_response_atlas(observations, _risk_table(changed_rows), cutoff)
    assert baseline.response_surfaces.to_pylist() == changed.response_surfaces.to_pylist()
    assert baseline.competing_risks.to_pylist() != changed.competing_risks.to_pylist()


def test_invalid_known_risk_refuses_only_risk_artifact_and_preserves_response() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    baseline = build_response_atlas(observations, risks, cutoff)
    invalid_rows = risks.to_pylist()
    target = next(
        row
        for row in invalid_rows
        if row["event_id"] == "atlas-event-001" and row["horizon_us"] == 60_000_000
    )
    target["event_kind"] = "invalid-known-event-kind"
    refused = build_response_atlas(observations, _risk_table(invalid_rows), cutoff)
    assert refused.response_surfaces.to_pylist() == baseline.response_surfaces.to_pylist()
    assert refused.competing_risks.num_rows == 0
    assert refused.risk_refusals.num_rows == 1
    refusal = refused.risk_refusals.to_pylist()[0]
    assert refusal["refusal_kind"] == "risk_artifact_refused_response_artifact_preserved"
    assert refusal["reason_code"] == "unregistered_competing_event_kind"
    assert refusal["admitted_risk_row_count"] == risks.num_rows
    assert refusal["refused_risk_input_logical_digest"].startswith("sha256:")
    assert refusal["response_input_logical_digest"] == baseline.response_surfaces.to_pylist()[0][
        "input_logical_digest"
    ]


def test_all_pending_subjects_remain_in_risk_denominator_and_cells() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    risk_rows = risks.to_pylist()
    for row in risk_rows:
        if row["event_id"] in {"atlas-event-001", "atlas-event-002"}:
            row["outcome_known_at"] = cutoff + timedelta(seconds=1)
    atlas = build_response_atlas(observations, _risk_table(risk_rows), cutoff)
    response_total = next(
        row
        for row in _wallet_a_short(atlas.response_surfaces.to_pylist())
        if row["component_kind"] == "total"
    )
    risk_cells = _wallet_a_short(atlas.competing_risks.to_pylist())
    assert response_total["support_anchor_count"] == 2
    assert len(risk_cells) == 3
    assert all(row["risk_cohort_count"] == 2 for row in risk_cells)
    assert all(row["terminal_known_count"] == 0 for row in risk_cells)
    assert all(row["pending_count"] == 2 for row in risk_cells)
    assert all(row["event_count"] == 0 for row in risk_cells)
    assert all(row["coverage_ratio_ppm"] == 0 for row in risk_cells)


def test_exact_atom_means_above_binary_float_integer_range_remain_rational() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = observations.to_pylist()
    exact_values = {
        "atlas-event-001": 2**53,
        "atlas-event-002": 2**53 + 1,
    }
    for row in rows:
        if (
            row["event_id"] in exact_values
            and row["horizon_us"] == 60_000_000
            and row["component_kind"] == "same_wallet"
        ):
            row["response_signed_flow_atoms"] = exact_values[row["event_id"]]
    atlas = build_response_atlas(_table(rows), risks, cutoff)
    exact = next(
        row
        for row in _wallet_a_short(atlas.response_surfaces.to_pylist())
        if row["component_kind"] == "same_wallet"
    )
    assert exact["response_sum_atoms"] == str(2**54 + 1)
    assert exact["response_mean_numerator_atoms"] == str(2**54 + 1)
    assert exact["response_mean_denominator"] == 2
    assert _exact_mean(exact) == Fraction(2**54 + 1, 2)


def test_future_context_version_fails_closed() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    rows = observations.to_pylist()
    rows[0]["lifecycle_available_at"] = rows[0]["information_cutoff"] + timedelta(seconds=1)
    with pytest.raises(TemporalLeakageError, match="lifecycle version was unavailable"):
        build_response_atlas(_table(rows), risks, cutoff)


def test_incomplete_components_fail_but_missing_terminal_outcome_stays_pending() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    with pytest.raises(CoverageError, match="incomplete component closure"):
        build_response_atlas(observations.slice(1), risks, cutoff)
    atlas = build_response_atlas(observations, risks.slice(1), cutoff)
    pending = next(
        row
        for row in _wallet_a_short(atlas.competing_risks.to_pylist())
        if row["event_kind"] == "migration"
    )
    assert pending["risk_cohort_count"] == 2
    assert pending["terminal_known_count"] == 1
    assert pending["pending_count"] == 1
    assert pending["pending_subject_ids"] == ["atlas-event-001:60000000"]


def test_future_row_presence_cannot_turn_incomplete_current_anchor_into_exclusion() -> None:
    observations, risks, cutoff = synthetic_response_atlas_inputs()
    original_rows = observations.to_pylist()
    incomplete_rows = [
        row
        for row in original_rows
        if not (
            row["event_id"] == "atlas-event-001"
            and row["horizon_us"] == 60_000_000
            and row["component_kind"] == "external"
        )
    ]
    with pytest.raises(CoverageError, match="incomplete component closure"):
        build_response_atlas(_table(incomplete_rows), risks, cutoff)

    later_row = next(
        dict(row)
        for row in original_rows
        if row["event_id"] == "atlas-event-001"
        and row["horizon_us"] == 60_000_000
        and row["component_kind"] == "external"
    )
    later_row["response_available_at"] = cutoff + timedelta(seconds=1)
    later_row["response_unit"] = "future-invalid-unit"
    with pytest.raises(CoverageError, match="incomplete component closure"):
        build_response_atlas(_table([*incomplete_rows, later_row]), risks, cutoff)


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
