from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .canonical import (
    canonical_json_bytes,
    iso_utc,
    logical_table_sha256,
    qualified_sha256_bytes,
    qualified_sha256_file,
    require_qualified_sha256,
    schema_descriptor,
    schema_sha256,
)
from .contracts import (
    CHART_FEATURE_SCHEMA,
    CHART_FEATURE_SCHEMA_ID,
    CHART_FEATURE_VERSION,
    DESCRIPTIVE_CLAIM_SCOPE,
)
from .errors import HashMismatchError, ImmutableOutputError, ManifestError, TemporalLeakageError
from .features import DESCRIPTIVE_CHART_SQL, descriptive_chart_features
from .job import _environment_manifest
from .snapshot import ValidatedSnapshot, validate_snapshot

DERIVED_ARTIFACT_VERSION = "joshi.analysis.derived-artifact/v1"
DERIVED_ARTIFACT_VERSION_V2 = "joshi.analysis.derived-artifact/v2"
DERIVED_AUTHORITY = "derived_analysis_read_only"
DERIVED_DISPLAY_CLASS = "descriptive_noncausal"
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidatedDerivedArtifact:
    root: Path
    manifest: dict[str, Any]
    manifest_digest: str
    table: pa.Table

    @property
    def artifact_id(self) -> str:
        return str(self.manifest["artifact_id"])


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ManifestError(f"duplicate JSON key in derived artifact manifest: {key!r}")
        value[key] = item
    return value


def _reject_nonfinite_json(value: str) -> None:
    raise ManifestError(f"non-finite JSON number is forbidden: {value}")


def _require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ManifestError(
            f"{context} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_digest(value: Any, context: str) -> str:
    try:
        return require_qualified_sha256(value, context)
    except ValueError as error:
        raise ManifestError(str(error)) from error


def _require_decimal(value: Any, context: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ManifestError(f"{context} must be a canonical unsigned decimal string")
    if value != "0" and value.startswith("0"):
        raise ManifestError(f"{context} is not canonical")
    return int(value)


def _require_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or len(value) != 27 or not value.endswith("Z"):
        raise ManifestError(f"{context} must be canonical microsecond UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ManifestError(f"{context} is not a timestamp") from error
    if iso_utc(parsed) != value:
        raise ManifestError(f"{context} is not canonical microsecond UTC")
    return parsed


def _publication_ids(snapshot: ValidatedSnapshot) -> list[str]:
    raw = snapshot.manifest.get("publications", [])
    if not isinstance(raw, list):
        raise ManifestError("snapshot publications must be an array")
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("publication_id"), str):
            raise ManifestError("snapshot publication identity is malformed")
        ids.append(item["publication_id"])
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ManifestError("snapshot publication identities must be sorted and unique")
    return ids


def _input_source(snapshot: ValidatedSnapshot) -> str:
    origin = snapshot.manifest.get("origin")
    if origin is None:
        return "frozen_fixture"
    if not isinstance(origin, dict) or origin.get("kind") != "operational_store":
        raise ManifestError("snapshot origin is not an accepted operational-store closure")
    return "operational_store"


def _coverage(snapshot: ValidatedSnapshot) -> dict[str, Any]:
    rows = snapshot.chart_samples.to_pylist()
    return {
        "window_ids": sorted({row["coverage_window_id"] for row in rows}),
        "gap_ids": sorted(
            {row["coverage_gap_id"] for row in rows if row["coverage_gap_id"] is not None}
        ),
        "observed_inputs": str(sum(row["coverage_status"] == "observed" for row in rows)),
        "gap_inputs": str(sum(row["coverage_status"] == "gap" for row in rows)),
    }


def _write_table(table: pa.Table, path: Path) -> None:
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=max(1, table.num_rows),
    )


def publish_restricted_descriptive_artifact(
    snapshot_root: str | Path,
    output_root: str | Path,
    *,
    analysis_run_id: str | None = None,
) -> Path:
    """Publish a deterministic, non-authoritative chart-shape artifact.

    The artifact is useful for readback and display. Its literal restrictions prohibit census
    ranking, hot-scope activation, truth mutation, and every economic action.
    """

    snapshot = validate_snapshot(snapshot_root)
    source_class = _input_source(snapshot)
    if source_class == "operational_store" and not analysis_run_id:
        raise ManifestError("operational publication requires a reserved analysis_run_id")
    if analysis_run_id is not None and (not analysis_run_id.isascii() or not analysis_run_id):
        raise ManifestError("analysis_run_id must be a non-empty ASCII occurrence identity")
    fit_cutoff = _require_timestamp(
        snapshot.manifest["maximum_decision_available_at"], "maximum decision cutoff"
    )
    available_values = [
        row["available_at"] for row in snapshot.chart_samples.to_pylist()
    ]
    maximum_available = max(available_values, default=fit_cutoff)
    if maximum_available > fit_cutoff:
        raise TemporalLeakageError("descriptive input became available after the fit cutoff")
    result = descriptive_chart_features(snapshot.chart_samples)
    if not result.schema.equals(CHART_FEATURE_SCHEMA, check_metadata=True):
        raise ManifestError("descriptive result violated its exact Arrow schema")

    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".joshi-derived-", dir=output))
    try:
        result_path = temporary / "descriptive_chart_shapes.parquet"
        _write_table(result, result_path)
        environment = _environment_manifest()
        part = {
            "path": result_path.name,
            "schema_id": CHART_FEATURE_SCHEMA_ID,
            "schema": schema_descriptor(result.schema),
            "schema_digest": schema_sha256(result.schema),
            "physical_digest": qualified_sha256_file(result_path),
            "logical_digest": logical_table_sha256(result, ["scene_id", "episode_id"]),
            "byte_length": str(result_path.stat().st_size),
            "row_count": str(result.num_rows),
            "primary_key": ["scene_id", "episode_id"],
        }
        coverage = _coverage(snapshot)
        snapshot_manifest_digest = qualified_sha256_file(snapshot.manifest_path)
        preimage = {
            "manifest_version": (
                DERIVED_ARTIFACT_VERSION_V2
                if source_class == "operational_store"
                else DERIVED_ARTIFACT_VERSION
            ),
            "artifact_family": "descriptive_chart_shape",
            "authority": DERIVED_AUTHORITY,
            "display_class": DERIVED_DISPLAY_CLASS,
            "claim_scope": DESCRIPTIVE_CLAIM_SCOPE,
            "producer": {
                "id": "joshi-analysis.descriptive-chart-shape",
                "version": CHART_FEATURE_VERSION,
                "build_digest": environment["source_tree_digest"],
                "configuration_digest": qualified_sha256_bytes(
                    DESCRIPTIVE_CHART_SQL.encode("utf-8")
                ),
                "lock_digest": environment["uv_lock_digest"],
            },
            "input": {
                "source_class": source_class,
                "snapshot_contract": snapshot.manifest["manifest_version"],
                "snapshot_id": snapshot.snapshot_id,
                "snapshot_manifest_digest": snapshot_manifest_digest,
                "catalog_commit_seq": snapshot.manifest["catalog"]["through_commit_seq"],
                "publication_ids": _publication_ids(snapshot),
            },
            "fit": {
                "fit_cutoff": iso_utc(fit_cutoff),
                "maximum_input_available_at": iso_utc(maximum_available),
                "policy": "input_available_at_not_after_fit_cutoff",
            },
            "support": {
                "output_rows": str(result.num_rows),
                "input_rows": str(snapshot.chart_samples.num_rows),
                **coverage,
            },
            "uncertainty": {
                "status": "not_estimated",
                "reason": "deterministic_descriptive_transform",
            },
            "restrictions": {
                "may_rank_census": False,
                "may_activate_hot_scope": False,
                "may_mutate_observations": False,
                "may_mutate_facts": False,
                "may_mutate_financial_truth": False,
                "economic_authority": "none",
            },
            "artifacts": [part],
            "determinism": {
                "canonical_row_order": ["scene_id", "episode_id"],
                "wall_clock_excluded": True,
                "network_required": False,
                "operational_store_writes": False,
            },
        }
        if source_class == "operational_store":
            preimage["analysis_run_id"] = analysis_run_id
        identity = qualified_sha256_bytes(canonical_json_bytes(preimage))
        manifest = {**preimage, "artifact_id": identity}
        manifest_bytes = canonical_json_bytes(manifest, newline=True)
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        final = output / f"derived-{identity.removeprefix('sha256:')}"
        if final.exists():
            if (final / "manifest.json").read_bytes() != manifest_bytes:
                raise ImmutableOutputError(f"derived artifact identity collision: {final}")
            if qualified_sha256_file(final / result_path.name) != part["physical_digest"]:
                raise ImmutableOutputError("existing derived artifact bytes differ")
            return final
        os.replace(temporary, final)
        return final
    finally:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()


def validate_derived_artifact(root: str | Path) -> ValidatedDerivedArtifact:
    """Independently validate exact bytes and restrictive semantics of one derived artifact."""

    directory = Path(root).resolve()
    manifest_path = directory / "manifest.json"
    if (
        not directory.is_dir()
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
        or manifest_path.stat().st_size > _MAX_MANIFEST_BYTES
    ):
        raise ManifestError("derived artifact manifest is missing, symlinked, or oversized")
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError("derived artifact manifest is not strict UTF-8 JSON") from error
    if not isinstance(manifest, dict) or raw != canonical_json_bytes(manifest, newline=True):
        raise ManifestError("derived artifact manifest is not canonical JSON plus one newline")
    common_keys = {
            "manifest_version",
            "artifact_id",
            "artifact_family",
            "authority",
            "display_class",
            "claim_scope",
            "producer",
            "input",
            "fit",
            "support",
            "uncertainty",
            "restrictions",
            "artifacts",
            "determinism",
        }
    version = manifest.get("manifest_version")
    if version == DERIVED_ARTIFACT_VERSION:
        _require_exact_keys(manifest, common_keys, "derived artifact manifest")
    elif version == DERIVED_ARTIFACT_VERSION_V2:
        _require_exact_keys(
            manifest, common_keys | {"analysis_run_id"}, "derived artifact manifest"
        )
        if not isinstance(manifest["analysis_run_id"], str) or not manifest["analysis_run_id"]:
            raise ManifestError("analysis_run_id must be a non-empty occurrence identity")
    else:
        raise ManifestError("derived artifact contract version is unsupported")
    if (
        manifest["artifact_family"] != "descriptive_chart_shape"
        or manifest["authority"] != DERIVED_AUTHORITY
        or manifest["display_class"] != DERIVED_DISPLAY_CLASS
        or manifest["claim_scope"] != DESCRIPTIVE_CLAIM_SCOPE
    ):
        raise ManifestError("derived artifact contract, family, authority, or claim is unsupported")
    expected_id = _require_digest(manifest["artifact_id"], "artifact_id")
    preimage = {key: value for key, value in manifest.items() if key != "artifact_id"}
    computed_id = qualified_sha256_bytes(canonical_json_bytes(preimage))
    if expected_id != computed_id:
        raise HashMismatchError("derived artifact self-identity does not match its preimage")

    producer = manifest["producer"]
    if not isinstance(producer, dict):
        raise ManifestError("producer must be an object")
    _require_exact_keys(
        producer,
        {"id", "version", "build_digest", "configuration_digest", "lock_digest"},
        "producer",
    )
    for key in ("build_digest", "configuration_digest", "lock_digest"):
        _require_digest(producer[key], f"producer.{key}")

    input_value = manifest["input"]
    if not isinstance(input_value, dict):
        raise ManifestError("input must be an object")
    _require_exact_keys(
        input_value,
        {
            "source_class",
            "snapshot_contract",
            "snapshot_id",
            "snapshot_manifest_digest",
            "catalog_commit_seq",
            "publication_ids",
        },
        "input",
    )
    if input_value["source_class"] not in {"operational_store", "frozen_fixture"}:
        raise ManifestError("input.source_class is unsupported")
    _require_digest(input_value["snapshot_id"], "input.snapshot_id")
    _require_digest(input_value["snapshot_manifest_digest"], "input.snapshot_manifest_digest")
    _require_decimal(input_value["catalog_commit_seq"], "input.catalog_commit_seq")
    publication_ids = input_value["publication_ids"]
    if (
        not isinstance(publication_ids, list)
        or any(not isinstance(item, str) or not item for item in publication_ids)
        or publication_ids != sorted(publication_ids)
        or len(publication_ids) != len(set(publication_ids))
    ):
        raise ManifestError("publication_ids must be a sorted unique string array")
    if input_value["source_class"] == "operational_store" and not publication_ids:
        raise ManifestError("operational artifact requires a non-empty publication closure")
    if (
        input_value["source_class"] == "operational_store"
        and version != DERIVED_ARTIFACT_VERSION_V2
    ):
        raise ManifestError("operational artifact requires occurrence-bound derived V2")
    if input_value["source_class"] == "frozen_fixture" and version != DERIVED_ARTIFACT_VERSION:
        raise ManifestError("frozen fixture artifact must remain derived V1")
    expected_snapshot_contract = (
        "joshi.analysis.snapshot/v2"
        if input_value["source_class"] == "operational_store"
        else "joshi.analysis.snapshot/v1"
    )
    if input_value["snapshot_contract"] != expected_snapshot_contract:
        raise ManifestError("derived artifact snapshot contract disagrees with its source class")

    fit = manifest["fit"]
    if not isinstance(fit, dict):
        raise ManifestError("fit must be an object")
    _require_exact_keys(fit, {"fit_cutoff", "maximum_input_available_at", "policy"}, "fit")
    fit_cutoff = _require_timestamp(fit["fit_cutoff"], "fit.fit_cutoff")
    maximum_available = _require_timestamp(
        fit["maximum_input_available_at"], "fit.maximum_input_available_at"
    )
    if maximum_available > fit_cutoff or fit["policy"] != "input_available_at_not_after_fit_cutoff":
        raise TemporalLeakageError("derived artifact fit closure admits future-known input")

    restrictions = manifest["restrictions"]
    expected_restrictions = {
        "may_rank_census": False,
        "may_activate_hot_scope": False,
        "may_mutate_observations": False,
        "may_mutate_facts": False,
        "may_mutate_financial_truth": False,
        "economic_authority": "none",
    }
    if restrictions != expected_restrictions:
        raise ManifestError("derived artifact restrictions are not the exact no-authority ceiling")
    uncertainty = manifest["uncertainty"]
    if uncertainty != {
        "status": "not_estimated",
        "reason": "deterministic_descriptive_transform",
    }:
        raise ManifestError("descriptive artifact uncertainty must remain explicitly unestimated")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise ManifestError("descriptive artifact requires exactly one Parquet part")
    part = artifacts[0]
    if not isinstance(part, dict):
        raise ManifestError("artifact part must be an object")
    _require_exact_keys(
        part,
        {
            "path",
            "schema_id",
            "schema",
            "schema_digest",
            "physical_digest",
            "logical_digest",
            "byte_length",
            "row_count",
            "primary_key",
        },
        "artifact part",
    )
    path_value = part["path"]
    posix = PurePosixPath(path_value) if isinstance(path_value, str) else PurePosixPath(".")
    if posix.is_absolute() or len(posix.parts) != 1 or posix.name != path_value:
        raise ManifestError("artifact part path must be one safe direct child")
    path = directory / path_value
    if not path.is_file() or path.is_symlink():
        raise ManifestError("artifact part is missing or symlinked")
    if {child.name for child in directory.iterdir()} != {"manifest.json", path_value}:
        raise ManifestError("derived artifact directory contains unmanifested files")
    if part["schema_id"] != CHART_FEATURE_SCHEMA_ID or part["primary_key"] != [
        "scene_id",
        "episode_id",
    ]:
        raise ManifestError("artifact schema identity or primary key is unsupported")
    if part["schema"] != schema_descriptor(CHART_FEATURE_SCHEMA):
        raise ManifestError("artifact manifested schema differs from the accepted schema")
    if _require_digest(part["schema_digest"], "schema_digest") != schema_sha256(
        CHART_FEATURE_SCHEMA
    ):
        raise HashMismatchError("artifact schema digest differs")
    if _require_digest(part["physical_digest"], "physical_digest") != qualified_sha256_file(path):
        raise HashMismatchError("artifact physical bytes differ")
    if _require_decimal(part["byte_length"], "byte_length") != path.stat().st_size:
        raise HashMismatchError("artifact byte length differs")
    table = pq.read_table(path)
    if not table.schema.equals(CHART_FEATURE_SCHEMA, check_metadata=True):
        raise ManifestError("artifact Parquet schema differs")
    if _require_decimal(part["row_count"], "row_count") != table.num_rows:
        raise HashMismatchError("artifact row count differs")
    logical = logical_table_sha256(table, ["scene_id", "episode_id"])
    if _require_digest(part["logical_digest"], "logical_digest") != logical:
        raise HashMismatchError("artifact logical relation differs")
    if any(row["claim_scope"] != DESCRIPTIVE_CLAIM_SCOPE for row in table.to_pylist()):
        raise ManifestError("artifact rows escaped the descriptive claim scope")

    return ValidatedDerivedArtifact(
        root=directory,
        manifest=manifest,
        manifest_digest=qualified_sha256_bytes(raw),
        table=table,
    )
