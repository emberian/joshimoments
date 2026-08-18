from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from joshi_analysis.errors import ManifestError, TemporalLeakageError
from joshi_analysis.response_kernels.contracts import KERNEL_OBSERVATION_SCHEMA
from joshi_analysis.response_kernels.estimator import (
    estimate_response_kernels,
    screen_candidate_models,
)
from joshi_analysis.response_kernels.job import run_kernel_prototype_job
from joshi_analysis.response_kernels.synthetic import synthetic_kernel_inputs


def _known_kernel(rows: list[dict[str, object]]) -> dict[str, object]:
    return next(
        row
        for row in rows
        if row["regime_epoch"] == "regime-1"
        and row["caller_class"] == "ecology_wallet"
        and row["mark_direction"] == "buy"
        and row["mark_size_bucket"] == "small"
        and row["observable_kind"] == "price_response"
        and row["horizon_us"] == 60_000_000
        and "territory-trend" in str(row["context_key"])
    )


def test_synthetic_kernel_recovers_known_wallet_cluster_response() -> None:
    observations, choices, risks, cutoff = synthetic_kernel_inputs()
    row = _known_kernel(estimate_response_kernels(observations, choices, risks, cutoff).to_pylist())
    assert row["estimate"] == 43_000.0
    assert row["wallet_count"] == 2
    assert row["coverage_ratio_ppm"] == 1_000_000
    assert row["claim_scope"] == "descriptive_conditional_response_not_causal_or_strategy_claim"


def test_future_response_is_excluded_and_choice_universe_fails_closed() -> None:
    observations, choices, risks, cutoff = synthetic_kernel_inputs()
    rows = observations.to_pylist()
    target = next(
        row
        for row in rows
        if row["event_id"] == "synthetic-event-001"
        and row["horizon_us"] == 60_000_000
        and row["observable_kind"] == "price_response"
    )
    target["response_available_at"] = cutoff + timedelta(seconds=1)
    changed = pa.Table.from_pylist(rows, schema=KERNEL_OBSERVATION_SCHEMA)
    row = _known_kernel(estimate_response_kernels(changed, choices, risks, cutoff).to_pylist())
    assert row["observed_count"] == 1

    incomplete = choices.slice(1)
    with pytest.raises(ManifestError, match="universe digest"):
        estimate_response_kernels(observations, incomplete, risks, cutoff)


def test_later_unavailable_rows_do_not_change_eligible_input_identity() -> None:
    observations, choices, risks, cutoff = synthetic_kernel_inputs()
    baseline = estimate_response_kernels(observations, choices, risks, cutoff)
    rows = observations.to_pylist()
    future = dict(rows[0])
    future["kernel_observation_id"] = "kernel-observation:future-unavailable"
    future["response_available_at"] = cutoff + timedelta(seconds=1)
    rows.append(future)
    changed = estimate_response_kernels(
        pa.Table.from_pylist(rows, schema=KERNEL_OBSERVATION_SCHEMA), choices, risks, cutoff
    )
    assert baseline.to_pylist() == changed.to_pylist()


def test_context_versions_are_bitemporal_and_sparse_marks_are_not_sentinels() -> None:
    observations, choices, risks, cutoff = synthetic_kernel_inputs()
    rows = observations.to_pylist()
    rows[0]["context_available_at"] = rows[0]["information_cutoff"] + timedelta(seconds=1)
    with pytest.raises(TemporalLeakageError, match="context version was unavailable"):
        estimate_response_kernels(
            pa.Table.from_pylist(rows, schema=KERNEL_OBSERVATION_SCHEMA), choices, risks, cutoff
        )

    rows = observations.to_pylist()
    for row in rows:
        if row["event_id"] == "synthetic-event-001":
            row.update(
                caller_attribution_status="unknown",
                caller_identity_version_id=None,
                caller_wallet_id=None,
                caller_class=None,
                mark_size_status="unknown",
                mark_size_bucket=None,
                mark_size_atoms=None,
                mark_asset_id=None,
                context_status="unknown",
                territory_id=None,
                territory_version_id=None,
                community_id=None,
                community_version_id=None,
                venue_id=None,
                lifecycle_state=None,
                lifecycle_version_id=None,
            )
    result = estimate_response_kernels(
        pa.Table.from_pylist(rows, schema=KERNEL_OBSERVATION_SCHEMA), choices, risks, cutoff
    )
    assert any(row["caller_class"] is None for row in result.to_pylist())


def test_candidate_diagnostics_preserve_censoring_and_claim_boundary() -> None:
    observations, choices, risks, cutoff = synthetic_kernel_inputs()
    rows = screen_candidate_models(observations, choices, risks, cutoff).to_pylist()
    assert {row["diagnostic_family"] for row in rows} == {
        "hawkes_window_excitation_candidate",
        "competing_risk_cumulative_incidence_candidate",
    }
    assert any(row["censored_count"] > 0 for row in rows)
    assert all(
        row["claim_scope"] == "candidate_model_diagnostic_not_causal_or_strategy_claim"
        for row in rows
    )


def test_kernel_job_is_byte_deterministic(tmp_path: Path) -> None:
    first = run_kernel_prototype_job(tmp_path / "a")
    second = run_kernel_prototype_job(tmp_path / "b")
    assert first.name == second.name
    for filename in ("manifest.json", "kernel_estimates.parquet", "candidate_diagnostics.parquet"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
