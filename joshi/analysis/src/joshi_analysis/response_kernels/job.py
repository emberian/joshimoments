from __future__ import annotations

from pathlib import Path

from ..canonical import canonical_json_bytes, iso_utc, qualified_sha256_bytes
from .artifacts import environment_manifest, publish_bundle
from .contracts import CANDIDATE_DIAGNOSTIC_SCHEMA_ID, KERNEL_ESTIMATE_SCHEMA_ID
from .estimator import (
    CONFIGURATION,
    CONFIGURATION_DIGEST,
    ESTIMATOR_ID,
    ESTIMATOR_VERSION,
    estimate_response_kernels,
    kernel_input_identity,
    screen_candidate_models,
)
from .synthetic import synthetic_kernel_inputs


def run_kernel_prototype_job(output_root: str | Path) -> Path:
    observations, choices, risks, fit_cutoff = synthetic_kernel_inputs()
    kernels = estimate_response_kernels(observations, choices, risks, fit_cutoff)
    diagnostics = screen_candidate_models(observations, choices, risks, fit_cutoff)
    input_snapshot_id, input_logical_digest = kernel_input_identity(observations, choices, risks)
    kernel_rows = kernels.to_pylist()
    occurrence_id = "kernel-prototype:synthetic-v1"
    preimage = {
        "manifest_version": "joshi.analysis.kernel-prototype-run/v1",
        "artifact_occurrence_id": occurrence_id,
        "job": "offline_synthetic_response_kernel_contract_probe",
        "estimator_configuration": CONFIGURATION,
        "estimator_configuration_digest": CONFIGURATION_DIGEST,
        "estimator_id": ESTIMATOR_ID,
        "estimator_version": ESTIMATOR_VERSION,
        "fit_cutoff": iso_utc(fit_cutoff),
        "training_policy": "response_or_outcome_available_at_not_after_fit_cutoff",
        "input_contract": "joshi.analysis.kernel-synthetic-input/v1",
        "input_snapshot_id": input_snapshot_id,
        "input_logical_digest": input_logical_digest,
        "training_lower_available_at": iso_utc(
            min(row["training_lower_available_at"] for row in kernel_rows)
        ),
        "maximum_training_available_at": iso_utc(
            max(row["maximum_training_available_at"] for row in kernel_rows)
        ),
        "as_of_commit_seq": max(row["as_of_commit_seq"] for row in kernel_rows),
        "coverage_window_ids": sorted(
            {item for row in kernel_rows for item in row["coverage_window_ids"]}
        ),
        "coverage_gap_ids": sorted(
            {item for row in kernel_rows for item in row["coverage_gap_ids"]}
        ),
        "support": {
            "kernel_cells": len(kernel_rows),
            "observed_responses": sum(row["observed_count"] for row in kernel_rows),
            "gap_responses": sum(row["gap_count"] for row in kernel_rows),
        },
        "environment": environment_manifest(),
        "claim_scope": "descriptive_and_candidate_diagnostics_only",
    }
    preimage["run_content_digest"] = qualified_sha256_bytes(canonical_json_bytes(preimage))
    return publish_bundle(
        output_root,
        prefix="kernel",
        id_field="kernel_run_id",
        preimage=preimage,
        artifacts=[
            (
                "kernel_estimates.parquet",
                KERNEL_ESTIMATE_SCHEMA_ID,
                kernels,
                ["kernel_estimate_occurrence_id"],
            ),
            (
                "candidate_diagnostics.parquet",
                CANDIDATE_DIAGNOSTIC_SCHEMA_ID,
                diagnostics,
                ["diagnostic_occurrence_id"],
            ),
        ],
    )
