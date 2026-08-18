from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pyarrow
import pyarrow.parquet as pq

from . import __version__
from .canonical import (
    canonical_json_bytes,
    logical_table_sha256,
    qualified_sha256_bytes,
    qualified_sha256_file,
    schema_descriptor,
    schema_sha256,
    sha256_bytes,
)
from .contracts import (
    CHART_FEATURE_SCHEMA,
    CHART_FEATURE_SCHEMA_ID,
    CHART_FEATURE_VERSION,
    DESCRIPTIVE_CLAIM_SCOPE,
    RUN_MANIFEST_VERSION,
)
from .errors import ImmutableOutputError
from .features import DESCRIPTIVE_CHART_SQL, descriptive_chart_features
from .snapshot import ValidatedSnapshot, validate_snapshot


def _analysis_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_tree_sha256() -> str:
    package_root = Path(__file__).resolve().parent
    digest_parts: list[bytes] = []
    for path in sorted(package_root.glob("*.py")):
        digest_parts.append(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return sha256_bytes(b"".join(digest_parts))


def _environment_manifest() -> dict[str, Any]:
    lock_path = _analysis_root() / "uv.lock"
    if not lock_path.is_file():
        raise ImmutableOutputError("uv.lock is required for a reproducible analysis run")
    return {
        "package_version": __version__,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "duckdb": duckdb.__version__,
        "pyarrow": pyarrow.__version__,
        "uv_lock_digest": qualified_sha256_file(lock_path),
        "source_tree_digest": "sha256:" + _source_tree_sha256(),
    }


def _summary(result: pyarrow.Table) -> dict[str, Any]:
    rows = result.to_pylist()
    return {
        "scene_count": len(rows),
        "scenes_with_explicit_gaps": sum(row["gap_samples"] > 0 for row in rows),
        "observed_samples": sum(row["observed_samples"] for row in rows),
        "explicit_gap_samples": sum(row["gap_samples"] for row in rows),
        "feature_version": CHART_FEATURE_VERSION,
        "claim_scope": DESCRIPTIVE_CLAIM_SCOPE,
    }


def _run_preimage(
    snapshot: ValidatedSnapshot,
    result: pyarrow.Table,
    result_path: Path,
) -> dict[str, Any]:
    result_artifact = {
        "path": "row_results.parquet",
        "schema_id": CHART_FEATURE_SCHEMA_ID,
        "schema": schema_descriptor(CHART_FEATURE_SCHEMA),
        "schema_digest": schema_sha256(CHART_FEATURE_SCHEMA),
        "physical_digest": qualified_sha256_file(result_path),
        "logical_digest": logical_table_sha256(result, ["scene_id", "episode_id"]),
        "row_count": result.num_rows,
        "primary_key": ["scene_id", "episode_id"],
    }
    return {
        "manifest_version": RUN_MANIFEST_VERSION,
        "designation": "exploratory_descriptive",
        "job": {
            "id": "descriptive_chart_shape",
            "version": CHART_FEATURE_VERSION,
            "sql_digest": qualified_sha256_bytes(DESCRIPTIVE_CHART_SQL.encode("utf-8")),
        },
        "claim_scope": DESCRIPTIVE_CLAIM_SCOPE,
        "input": {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_manifest_digest": snapshot.manifest_digest,
            "knowledge_mode": snapshot.manifest["knowledge_mode"],
        },
        "environment": _environment_manifest(),
        "artifacts": [result_artifact],
        "summary": _summary(result),
        "determinism": {
            "wall_clock_excluded": True,
            "canonical_row_order": ["scene_id", "episode_id"],
            "network_required": False,
            "operational_store_writes": False,
        },
    }


def _existing_run_matches(run_dir: Path, expected_manifest: bytes, result_path: Path) -> bool:
    manifest_path = run_dir / "manifest.json"
    existing_result = run_dir / "row_results.parquet"
    return (
        manifest_path.is_file()
        and existing_result.is_file()
        and manifest_path.read_bytes() == expected_manifest
        and qualified_sha256_file(existing_result) == qualified_sha256_file(result_path)
    )


def run_descriptive_chart_job(snapshot_root: str | Path, output_root: str | Path) -> Path:
    snapshot = validate_snapshot(snapshot_root)
    result = descriptive_chart_features(snapshot.chart_samples)
    if not result.schema.equals(CHART_FEATURE_SCHEMA, check_metadata=True):
        raise RuntimeError("descriptive feature result violated its exact Arrow schema")

    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".joshi-run-", dir=output))
    try:
        temporary_result = temporary_root / "row_results.parquet"
        pq.write_table(
            result,
            temporary_result,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
            data_page_version="1.0",
            version="2.6",
            row_group_size=max(1, result.num_rows),
        )
        preimage = _run_preimage(snapshot, result, temporary_result)
        run_id = "sha256:" + sha256_bytes(canonical_json_bytes(preimage))
        manifest = {**preimage, "run_id": run_id}
        manifest_bytes = canonical_json_bytes(manifest, newline=True)
        (temporary_root / "manifest.json").write_bytes(manifest_bytes)

        run_dir = output / f"run-{run_id.removeprefix('sha256:')}"
        if run_dir.exists():
            if _existing_run_matches(run_dir, manifest_bytes, temporary_result):
                return run_dir
            raise ImmutableOutputError(f"run id collision or mutated run directory: {run_dir}")
        os.replace(temporary_root, run_dir)
        return run_dir
    finally:
        if temporary_root.exists():
            for child in temporary_root.iterdir():
                child.unlink()
            temporary_root.rmdir()
