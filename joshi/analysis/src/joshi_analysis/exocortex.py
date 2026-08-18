from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .canonical import (
    canonical_json_bytes,
    logical_table_sha256,
    qualified_sha256_bytes,
    qualified_sha256_file,
    require_qualified_sha256,
    schema_descriptor,
    schema_sha256,
)
from .contracts import (
    ANALOG_CLAIM_SCOPE,
    ANALOG_RESULT_SCHEMA,
    ANALOG_RESULT_SCHEMA_ID,
    ANALOG_RUN_MANIFEST_VERSION,
    DATASET_ROW_SCHEMA,
    DATASET_ROW_SCHEMA_ID,
    DATASET_RUN_MANIFEST_VERSION,
    DESCRIPTIVE_CLAIM_SCOPE,
)
from .errors import HashMismatchError, ImmutableOutputError, ManifestError, TemporalLeakageError
from .features import descriptive_chart_features
from .job import _environment_manifest
from .snapshot import ValidatedSnapshot, validate_snapshot
from .specs import SpecBundle, _timestamp, load_spec_bundle

DATASET_JOB_VERSION = "decision-choice-materialization/v1"
ANALOG_RETRIEVAL_VERSION = "descriptive-shape-analog/v1"


@dataclass(frozen=True, slots=True)
class ValidatedDataset:
    run_dir: Path
    manifest: dict[str, Any]
    rows: pa.Table

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])


def _index(table: pa.Table, key: str) -> dict[Any, dict[str, Any]]:
    return {row[key]: row for row in table.to_pylist()}


def _partition(decision_time: datetime, specs: SpecBundle) -> str:
    train_before = _timestamp(specs.dataset["train_before"], "train_before")
    validation_start = _timestamp(specs.dataset["validation_start"], "validation_start")
    validation_end = _timestamp(specs.dataset["validation_end"], "validation_end")
    if decision_time < train_before:
        return "train"
    if validation_start <= decision_time < validation_end:
        return "validation"
    return "excluded_embargo"


def materialize_dataset_rows(snapshot: ValidatedSnapshot, specs: SpecBundle) -> pa.Table:
    scenes = _index(snapshot.tables["scenes"], "scene_id")
    candidates = _index(snapshot.tables["candidates"], "candidate_id")
    decisions = _index(snapshot.tables["decisions"], "decision_id")
    episodes = _index(snapshot.tables["episodes"], "episode_id")
    chart = {
        (row["decision_id"], row["candidate_id"]): row
        for row in descriptive_chart_features(snapshot.chart_samples).to_pylist()
    }
    choice_rows = [
        row
        for row in snapshot.tables["choice_members"].to_pylist()
        if row["set_kind"] == specs.dataset["choice_set_kind"]
    ]
    by_decision: dict[str, list[dict[str, Any]]] = {}
    for row in choice_rows:
        by_decision.setdefault(row["decision_id"], []).append(row)
    social_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.tables["candidate_social_assertions"].to_pylist():
        social_by_candidate.setdefault(row["candidate_id"], []).append(row)
    gestures_by_decision: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.tables["operator_gestures"].to_pylist():
        gestures_by_decision.setdefault(row["decision_id"], []).append(row)
    outcomes = {
        (row["decision_id"], row["candidate_id"]): row
        for row in snapshot.tables["outcomes"].to_pylist()
    }
    label_cutoff = _timestamp(specs.label["label_observation_cutoff"], "label cutoff")

    output: list[dict[str, Any]] = []
    for decision_id in sorted(by_decision):
        decision = decisions[decision_id]
        scene = scenes[decision["scene_id"]]
        members = sorted(by_decision[decision_id], key=lambda row: row["candidate_id"])
        universe_digest = qualified_sha256_bytes(
            canonical_json_bytes([row["candidate_id"] for row in members])
        )
        for member in members:
            candidate_id = member["candidate_id"]
            candidate = candidates[candidate_id]
            selected = candidate_id == decision["selected_candidate_id"]
            episode_id = decision["episode_id"] if selected else None
            if episode_id is not None:
                episode = episodes[episode_id]
                if episode["candidate_id"] != candidate_id:
                    raise ManifestError("dataset episode/candidate join is inconsistent")
            social_candidates = [
                row
                for row in social_by_candidate.get(candidate_id, [])
                if row["available_at"] <= decision["decision_available_at"]
                and row["available_commit_seq"] <= scene["knowledge_commit_seq"]
            ]
            social_candidates.sort(
                key=lambda row: (row["available_at"], row["social_assertion_id"]), reverse=True
            )
            identity = social_candidates[0] if social_candidates else None
            chart_row = chart.get((decision_id, candidate_id))
            if chart_row is None:
                chart_status = "not_observed"
            elif chart_row["gap_samples"]:
                chart_status = "explicit_gap"
            else:
                chart_status = "observed"
            predecision_gestures = sum(
                gesture["candidate_id"] == candidate_id
                and gesture["available_at"] <= decision["decision_available_at"]
                and gesture["available_commit_seq"] <= scene["knowledge_commit_seq"]
                for gesture in gestures_by_decision.get(decision_id, [])
            )
            outcome = outcomes.get((decision_id, candidate_id)) if selected else None
            if not selected:
                label_status = "not_selected_not_at_risk"
            elif outcome is None or outcome["outcome_known_at"] > label_cutoff:
                label_status = "label_not_yet_observed"
                outcome = None
            elif outcome["is_censored"]:
                label_status = "right_censored_unknown"
            else:
                label_status = "observed_competing_event"
            row_identity = {
                "snapshot_id": snapshot.snapshot_id,
                "dataset_spec_digest": specs.dataset_digest,
                "decision_id": decision_id,
                "candidate_id": candidate_id,
            }
            output.append(
                {
                    "dataset_row_id": qualified_sha256_bytes(canonical_json_bytes(row_identity)),
                    "decision_id": decision_id,
                    "choice_set_id": decision["choice_set_id"],
                    "scene_id": scene["scene_id"],
                    "scene_view_digest": scene["view_digest"],
                    "decision_available_at": decision["decision_available_at"],
                    "partition": _partition(decision["decision_available_at"], specs),
                    "candidate_id": candidate_id,
                    "territory_id": candidate["territory_id"],
                    "episode_id": episode_id,
                    "is_operator_selected": selected,
                    "source_rank": member["source_rank"],
                    "rendered_ordinal": member["rendered_ordinal"],
                    "in_viewport": member["in_viewport"],
                    "interacted": member["interacted"],
                    "choice_set_size": len(members),
                    "universe_digest": universe_digest,
                    "creator_identity_as_known": identity["identity_key"] if identity else None,
                    "creator_identity_assertion_id": (
                        identity["social_assertion_id"] if identity else None
                    ),
                    "chart_feature_status": chart_status,
                    "chart_coverage_ratio_ppm": (
                        chart_row["coverage_ratio_ppm"] if chart_row else None
                    ),
                    "chart_signed_change_ppm": (
                        chart_row["signed_change_ppm"] if chart_row else None
                    ),
                    "chart_range_ppm": chart_row["range_ppm"] if chart_row else None,
                    "chart_max_drawdown_ppm": (
                        chart_row["max_drawdown_ppm"] if chart_row else None
                    ),
                    "chart_direction_changes": (
                        chart_row["direction_changes"] if chart_row else None
                    ),
                    "chart_path_signature": chart_row["path_signature"] if chart_row else None,
                    "predecision_gesture_count": predecision_gestures,
                    "label_status": label_status,
                    "label_event_kind": outcome["event_kind"] if outcome else None,
                    "label_event_time": outcome["event_time"] if outcome else None,
                    "label_known_at": outcome["outcome_known_at"] if outcome else None,
                    "label_is_censored": outcome["is_censored"] if outcome else None,
                    "label_censoring_reason": outcome["censoring_reason"] if outcome else None,
                    "feature_spec_id": specs.feature["spec_id"],
                    "feature_spec_digest": specs.feature_digest,
                    "label_spec_id": specs.label["spec_id"],
                    "label_spec_digest": specs.label_digest,
                    "dataset_spec_id": specs.dataset["spec_id"],
                    "dataset_spec_digest": specs.dataset_digest,
                    "input_snapshot_id": snapshot.snapshot_id,
                    "claim_scope": DESCRIPTIVE_CLAIM_SCOPE,
                }
            )
    table = pa.Table.from_pylist(output, schema=DATASET_ROW_SCHEMA)
    _validate_dataset_rows(table)
    return table


def _validate_dataset_rows(table: pa.Table) -> None:
    if not table.schema.equals(DATASET_ROW_SCHEMA, check_metadata=True):
        raise ManifestError("dataset rows violate the exact schema")
    rows = table.to_pylist()
    keys = [(row["decision_id"], row["candidate_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ManifestError("dataset duplicates a decision candidate")
    by_decision: dict[str, list[dict[str, Any]]] = {}
    episode_partitions: dict[str, set[str]] = {}
    for row in rows:
        by_decision.setdefault(row["decision_id"], []).append(row)
        try:
            for field in (
                "dataset_row_id",
                "universe_digest",
                "feature_spec_digest",
                "label_spec_digest",
                "dataset_spec_digest",
                "input_snapshot_id",
                "scene_view_digest",
            ):
                require_qualified_sha256(row[field], field)
        except ValueError as error:
            raise ManifestError(str(error)) from error
        if row["episode_id"] is not None:
            episode_partitions.setdefault(row["episode_id"], set()).add(row["partition"])
        if row["label_status"] == "right_censored_unknown" and (
            row["label_event_kind"] is not None or row["label_is_censored"] is not True
        ):
            raise ManifestError("censored dataset row was collapsed into a no-event label")
        if row["label_status"] == "observed_competing_event" and (
            row["label_event_kind"] not in {"drawdown_stop", "liquidity_exit", "profit_target"}
            or row["label_is_censored"] is not False
        ):
            raise ManifestError("dataset collapsed or invented a competing-risk event")
        if not row["is_operator_selected"] and row["label_status"] != "not_selected_not_at_risk":
            raise ManifestError("nonselected candidate was incorrectly placed at risk")
        if row["chart_feature_status"] == "not_observed" and any(
            row[field] is not None
            for field in (
                "chart_coverage_ratio_ppm",
                "chart_signed_change_ppm",
                "chart_range_ppm",
                "chart_max_drawdown_ppm",
                "chart_direction_changes",
                "chart_path_signature",
            )
        ):
            raise ManifestError("missing chart observation contains manufactured features")
    for decision_id, decision_rows in by_decision.items():
        digests = {row["universe_digest"] for row in decision_rows}
        sizes = {row["choice_set_size"] for row in decision_rows}
        actual_digest = qualified_sha256_bytes(
            canonical_json_bytes(sorted(row["candidate_id"] for row in decision_rows))
        )
        if digests != {actual_digest} or sizes != {len(decision_rows)}:
            raise ManifestError(
                f"dataset does not preserve the exact choice universe: {decision_id}"
            )
        if sum(row["is_operator_selected"] for row in decision_rows) > 1:
            raise ManifestError("a decision has multiple operator selections")
    if any(len(partitions) > 1 for partitions in episode_partitions.values()):
        raise ManifestError("one episode appears in multiple temporal partitions")


def _artifact(
    table: pa.Table, path: Path, schema_id: str, primary_key: list[str]
) -> dict[str, Any]:
    return {
        "path": path.name,
        "schema_id": schema_id,
        "schema": schema_descriptor(table.schema),
        "schema_digest": schema_sha256(table.schema),
        "physical_digest": qualified_sha256_file(path),
        "logical_digest": logical_table_sha256(table, primary_key),
        "row_count": table.num_rows,
        "primary_key": primary_key,
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


def _publish(
    output_root: str | Path,
    prefix: str,
    id_field: str,
    table: pa.Table,
    artifact_name: str,
    schema_id: str,
    primary_key: list[str],
    preimage_without_artifact: dict[str, Any],
) -> Path:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".joshi-{prefix}-", dir=output))
    try:
        result_path = temporary_root / artifact_name
        _write_table(table, result_path)
        preimage = {
            **preimage_without_artifact,
            "artifacts": [_artifact(table, result_path, schema_id, primary_key)],
        }
        identity = qualified_sha256_bytes(canonical_json_bytes(preimage))
        manifest = {**preimage, id_field: identity}
        manifest_bytes = canonical_json_bytes(manifest, newline=True)
        (temporary_root / "manifest.json").write_bytes(manifest_bytes)
        run_dir = output / f"{prefix}-{identity.removeprefix('sha256:')}"
        if run_dir.exists():
            existing_manifest = run_dir / "manifest.json"
            existing_artifact = run_dir / artifact_name
            if (
                existing_manifest.is_file()
                and existing_artifact.is_file()
                and existing_manifest.read_bytes() == manifest_bytes
                and qualified_sha256_file(existing_artifact) == qualified_sha256_file(result_path)
            ):
                return run_dir
            raise ImmutableOutputError(f"immutable artifact collision or mutation: {run_dir}")
        os.replace(temporary_root, run_dir)
        return run_dir
    finally:
        if temporary_root.exists():
            for child in temporary_root.iterdir():
                child.unlink()
            temporary_root.rmdir()


def materialize_dataset_job(
    snapshot_root: str | Path,
    dataset_spec: str | Path,
    feature_spec: str | Path,
    label_spec: str | Path,
    output_root: str | Path,
) -> Path:
    snapshot = validate_snapshot(snapshot_root)
    specs = load_spec_bundle(dataset_spec, feature_spec, label_spec)
    result = materialize_dataset_rows(snapshot, specs)
    partition_counts: dict[str, int] = {}
    for partition in result.column("partition").to_pylist():
        partition_counts[partition] = partition_counts.get(partition, 0) + 1
    preimage = {
        "manifest_version": DATASET_RUN_MANIFEST_VERSION,
        "designation": "point_in_time_decision_dataset",
        "job": {"id": "decision_choice_materialization", "version": DATASET_JOB_VERSION},
        "input": {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_manifest_digest": snapshot.manifest_digest,
            "catalog_as_of": snapshot.manifest["catalog"]["as_of"],
        },
        "specs": {
            "dataset": {"id": specs.dataset["spec_id"], "digest": specs.dataset_digest},
            "feature": {"id": specs.feature["spec_id"], "digest": specs.feature_digest},
            "label": {"id": specs.label["spec_id"], "digest": specs.label_digest},
        },
        "environment": _environment_manifest(),
        "partitions": dict(sorted(partition_counts.items())),
        "claim_scope": DESCRIPTIVE_CLAIM_SCOPE,
        "determinism": {
            "canonical_row_order": ["decision_id", "candidate_id"],
            "network_required": False,
            "operational_store_writes": False,
            "wall_clock_excluded": True,
        },
    }
    return _publish(
        output_root,
        "dataset",
        "dataset_id",
        result,
        "dataset_rows.parquet",
        DATASET_ROW_SCHEMA_ID,
        ["decision_id", "candidate_id"],
        preimage,
    )


def validate_dataset_run(run_dir: str | Path) -> ValidatedDataset:
    root = Path(run_dir).resolve()
    manifest_path = root / "manifest.json"
    artifact_path = root / "dataset_rows.parquet"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024:
        raise ManifestError("dataset run manifest is missing or oversized")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ManifestError(f"duplicate JSON key in dataset manifest: {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ManifestError(f"non-finite JSON number in dataset manifest: {value}")

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError("dataset run manifest is unavailable or invalid") from error
    expected_keys = {
        "manifest_version",
        "designation",
        "job",
        "input",
        "specs",
        "environment",
        "partitions",
        "claim_scope",
        "determinism",
        "artifacts",
        "dataset_id",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise ManifestError("dataset run manifest has a noncanonical shape")
    if manifest["manifest_version"] != DATASET_RUN_MANIFEST_VERSION:
        raise ManifestError("dataset run manifest version is unsupported")
    identity = manifest.get("dataset_id")
    try:
        require_qualified_sha256(identity, "dataset_id")
    except ValueError as error:
        raise ManifestError(str(error)) from error
    preimage = {key: value for key, value in manifest.items() if key != "dataset_id"}
    if identity != qualified_sha256_bytes(canonical_json_bytes(preimage)):
        raise HashMismatchError("dataset_id does not hash its canonical run preimage")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise ManifestError("dataset run must contain exactly one row artifact")
    artifact = artifacts[0]
    artifact_keys = {
        "path",
        "schema_id",
        "schema",
        "schema_digest",
        "physical_digest",
        "logical_digest",
        "row_count",
        "primary_key",
    }
    if not isinstance(artifact, dict) or set(artifact) != artifact_keys:
        raise ManifestError("dataset artifact manifest has a noncanonical shape")
    if artifact.get("path") != "dataset_rows.parquet":
        raise ManifestError("dataset artifact path is not its v1 direct child")
    if artifact.get("schema_id") != DATASET_ROW_SCHEMA_ID:
        raise ManifestError("dataset artifact schema identity is unsupported")
    if (
        artifact.get("schema") != schema_descriptor(DATASET_ROW_SCHEMA)
        or artifact.get("schema_digest") != schema_sha256(DATASET_ROW_SCHEMA)
        or artifact.get("primary_key") != ["decision_id", "candidate_id"]
    ):
        raise ManifestError("dataset artifact schema/key contract differs")
    if artifact.get("physical_digest") != qualified_sha256_file(artifact_path):
        raise HashMismatchError("dataset physical artifact digest differs")
    table = pq.read_table(artifact_path)
    if not table.schema.equals(DATASET_ROW_SCHEMA, check_metadata=True):
        raise ManifestError("dataset artifact Arrow schema differs")
    if type(artifact.get("row_count")) is not int or artifact.get("row_count") != table.num_rows:
        raise ManifestError("dataset artifact row count differs")
    if not isinstance(manifest["partitions"], dict) or any(
        type(count) is not int or count < 0 for count in manifest["partitions"].values()
    ):
        raise ManifestError("dataset partition counts must be nonnegative integers")
    if artifact.get("logical_digest") != logical_table_sha256(
        table, ["decision_id", "candidate_id"]
    ):
        raise HashMismatchError("dataset logical artifact digest differs")
    _validate_dataset_rows(table)
    return ValidatedDataset(root, manifest, table)


def descriptive_analog_rows(dataset: ValidatedDataset, *, limit: int = 2) -> pa.Table:
    if limit < 1:
        raise ValueError("analog limit must be positive")
    rows = dataset.rows.to_pylist()
    queries = [
        row
        for row in rows
        if row["partition"] == "validation"
        and row["is_operator_selected"]
        and row["episode_id"] is not None
        and row["chart_feature_status"] != "not_observed"
    ]
    candidates = [
        row
        for row in rows
        if row["partition"] == "train"
        and row["is_operator_selected"]
        and row["episode_id"] is not None
        and row["chart_feature_status"] != "not_observed"
    ]
    output: list[dict[str, Any]] = []
    for query in sorted(queries, key=lambda row: row["decision_id"]):
        analogs: list[tuple[int, dict[str, Any]]] = []
        for candidate in candidates:
            if candidate["decision_available_at"] >= query["decision_available_at"]:
                raise TemporalLeakageError("analog candidate is not strictly earlier than query")
            distance = (
                abs(query["chart_signed_change_ppm"] - candidate["chart_signed_change_ppm"])
                + abs(query["chart_range_ppm"] - candidate["chart_range_ppm"])
                + abs(query["chart_max_drawdown_ppm"] - candidate["chart_max_drawdown_ppm"])
                + 100_000
                * abs(query["chart_direction_changes"] - candidate["chart_direction_changes"])
            )
            analogs.append((distance, candidate))
        analogs.sort(
            key=lambda item: (
                item[0],
                item[1]["territory_id"] != query["territory_id"],
                item[1]["decision_id"],
                item[1]["candidate_id"],
            )
        )
        for rank, (distance, analog) in enumerate(analogs[:limit], start=1):
            output.append(
                {
                    "query_decision_id": query["decision_id"],
                    "query_candidate_id": query["candidate_id"],
                    "query_episode_id": query["episode_id"],
                    "analog_rank": rank,
                    "analog_decision_id": analog["decision_id"],
                    "analog_candidate_id": analog["candidate_id"],
                    "analog_episode_id": analog["episode_id"],
                    "analog_decision_available_at": analog["decision_available_at"],
                    "same_territory": analog["territory_id"] == query["territory_id"],
                    "shape_distance_ppm": distance,
                    "query_path_signature": query["chart_path_signature"],
                    "analog_path_signature": analog["chart_path_signature"],
                    "retrieval_version": ANALOG_RETRIEVAL_VERSION,
                    "claim_scope": ANALOG_CLAIM_SCOPE,
                }
            )
    return pa.Table.from_pylist(output, schema=ANALOG_RESULT_SCHEMA)


def descriptive_analog_job(
    dataset_run: str | Path, output_root: str | Path, *, limit: int = 2
) -> Path:
    dataset = validate_dataset_run(dataset_run)
    result = descriptive_analog_rows(dataset, limit=limit)
    preimage = {
        "manifest_version": ANALOG_RUN_MANIFEST_VERSION,
        "designation": "non_predictive_analog_retrieval",
        "job": {"id": "descriptive_shape_analog", "version": ANALOG_RETRIEVAL_VERSION},
        "input": {
            "dataset_id": dataset.dataset_id,
            "dataset_manifest_digest": qualified_sha256_file(dataset.run_dir / "manifest.json"),
        },
        "configuration": {"limit": str(limit), "query_partition": "validation"},
        "environment": _environment_manifest(),
        "claim_scope": ANALOG_CLAIM_SCOPE,
        "determinism": {
            "canonical_row_order": ["query_decision_id", "analog_rank"],
            "network_required": False,
            "operational_store_writes": False,
            "wall_clock_excluded": True,
        },
    }
    return _publish(
        output_root,
        "analog",
        "analog_run_id",
        result,
        "analog_results.parquet",
        ANALOG_RESULT_SCHEMA_ID,
        ["query_decision_id", "analog_rank"],
        preimage,
    )
