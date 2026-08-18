from __future__ import annotations

from pathlib import Path

from ..canonical import canonical_json_bytes, iso_utc, qualified_sha256_bytes
from ..response_kernels.artifacts import environment_manifest, publish_bundle
from .contracts import FIELD_OBSERVABLE_SCHEMA_ID
from .estimator import (
    CONFIGURATION,
    CONFIGURATION_DIGEST,
    ESTIMATOR_ID,
    ESTIMATOR_VERSION,
    estimate_dynamic_fields,
    field_input_identity,
)
from .synthetic import synthetic_field_inputs


def run_field_prototype_job(output_root: str | Path) -> Path:
    edges, venues, fit_cutoff = synthetic_field_inputs()
    estimates = estimate_dynamic_fields(edges, venues, fit_cutoff)
    input_snapshot_id, input_logical_digest = field_input_identity(edges, venues)
    rows = estimates.to_pylist()
    preimage = {
        "manifest_version": "joshi.analysis.dynamic-field-prototype-run/v1",
        "artifact_occurrence_id": "field-prototype:synthetic-v1",
        "job": "offline_synthetic_dynamic_field_contract_probe",
        "estimator_configuration": CONFIGURATION,
        "estimator_configuration_digest": CONFIGURATION_DIGEST,
        "estimator_id": ESTIMATOR_ID,
        "estimator_version": ESTIMATOR_VERSION,
        "fit_cutoff": iso_utc(fit_cutoff),
        "training_policy": "input_available_at_not_after_fit_cutoff_and_selected_topology_as_known",
        "input_contract": "joshi.analysis.field-synthetic-input/v1",
        "input_snapshot_id": input_snapshot_id,
        "input_logical_digest": input_logical_digest,
        "maximum_input_available_at": iso_utc(
            max(row["maximum_input_available_at"] for row in rows)
        ),
        "as_of_commit_seq": max(row["as_of_commit_seq"] for row in rows),
        "coverage_window_ids": sorted(
            {item for row in rows for item in row["coverage_window_ids"]}
        ),
        "coverage_gap_ids": sorted({item for row in rows for item in row["coverage_gap_ids"]}),
        "support": {
            "observable_rows": len(rows),
            "observed_inputs": sum(row["observed_count"] for row in rows),
            "gap_inputs": sum(row["gap_count"] for row in rows),
        },
        "environment": environment_manifest(),
        "claim_scope": "machine_descriptive_field_estimates_only",
    }
    preimage["run_content_digest"] = qualified_sha256_bytes(canonical_json_bytes(preimage))
    return publish_bundle(
        output_root,
        prefix="field",
        id_field="field_run_id",
        preimage=preimage,
        artifacts=[
            (
                "field_observables.parquet",
                FIELD_OBSERVABLE_SCHEMA_ID,
                estimates,
                ["field_observable_occurrence_id"],
            )
        ],
    )
