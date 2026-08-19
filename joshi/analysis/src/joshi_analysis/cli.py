from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .canonical import canonical_json_bytes
from .derived_artifacts import (
    publish_restricted_descriptive_artifact,
    validate_derived_artifact,
)
from .exocortex import descriptive_analog_job, materialize_dataset_job
from .field_models import run_field_prototype_job
from .job import run_descriptive_chart_job
from .response_kernels import run_kernel_prototype_job
from .snapshot import validate_snapshot
from .wave6_operator_model import validate_store_operator_evidence_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="joshi-analysis",
        description="Validate immutable Joshi snapshots and run offline descriptive jobs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="validate hashes, schema, coverage and time cuts"
    )
    validate.add_argument("--snapshot", required=True, type=Path)
    run = commands.add_parser("run", help="emit a deterministic descriptive chart-shape run")
    run.add_argument("--snapshot", required=True, type=Path)
    run.add_argument("--output-root", required=True, type=Path)
    materialize = commands.add_parser(
        "materialize", help="build a point-in-time decision-candidate dataset"
    )
    materialize.add_argument("--snapshot", required=True, type=Path)
    materialize.add_argument("--dataset-spec", required=True, type=Path)
    materialize.add_argument("--feature-spec", required=True, type=Path)
    materialize.add_argument("--label-spec", required=True, type=Path)
    materialize.add_argument("--output-root", required=True, type=Path)
    analog = commands.add_parser(
        "retrieve-analogs", help="retrieve earlier descriptive chart-shape analogs"
    )
    analog.add_argument("--dataset-run", required=True, type=Path)
    analog.add_argument("--output-root", required=True, type=Path)
    analog.add_argument("--limit", type=int, default=2)
    kernel = commands.add_parser(
        "kernel-prototype", help="run the deterministic synthetic response-kernel probe"
    )
    kernel.add_argument("--output-root", required=True, type=Path)
    field = commands.add_parser(
        "field-prototype", help="run the deterministic synthetic dynamic-field probe"
    )
    field.add_argument("--output-root", required=True, type=Path)
    publish_derived = commands.add_parser(
        "publish-derived",
        help="publish a restricted deterministic descriptive artifact from a snapshot",
    )
    publish_derived.add_argument("--snapshot", required=True, type=Path)
    publish_derived.add_argument("--output-root", required=True, type=Path)
    publish_derived.add_argument("--analysis-run-id")
    validate_derived = commands.add_parser(
        "validate-derived", help="validate a restricted derived artifact and exact Parquet bytes"
    )
    validate_derived.add_argument("--artifact", required=True, type=Path)
    validate_operator_evidence = commands.add_parser(
        "validate-operator-evidence",
        help="validate an exact V22 operator-evidence report without model promotion",
    )
    validate_operator_evidence.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        snapshot = validate_snapshot(args.snapshot)
        payload = {
            "contract": "joshi.analysis.snapshot-validation-receipt/v1",
            "status": "valid",
            "snapshot_id": snapshot.snapshot_id,
            "manifest_digest": snapshot.manifest_digest,
            "manifest_version": snapshot.manifest["manifest_version"],
            "table_count": len(snapshot.tables),
            "total_row_count": sum(table.num_rows for table in snapshot.tables.values()),
            "knowledge_mode": snapshot.manifest["knowledge_mode"],
        }
    elif args.command == "run":
        run_dir = run_descriptive_chart_job(args.snapshot, args.output_root)
        payload = {"status": "complete", "run_dir": str(run_dir)}
    elif args.command == "materialize":
        run_dir = materialize_dataset_job(
            args.snapshot,
            args.dataset_spec,
            args.feature_spec,
            args.label_spec,
            args.output_root,
        )
        payload = {"status": "complete", "dataset_run_dir": str(run_dir)}
    elif args.command == "retrieve-analogs":
        run_dir = descriptive_analog_job(args.dataset_run, args.output_root, limit=args.limit)
        payload = {"status": "complete", "analog_run_dir": str(run_dir)}
    elif args.command == "kernel-prototype":
        run_dir = run_kernel_prototype_job(args.output_root)
        payload = {"status": "complete", "kernel_run_dir": str(run_dir)}
    elif args.command == "field-prototype":
        run_dir = run_field_prototype_job(args.output_root)
        payload = {"status": "complete", "field_run_dir": str(run_dir)}
    elif args.command == "publish-derived":
        run_dir = publish_restricted_descriptive_artifact(
            args.snapshot, args.output_root, analysis_run_id=args.analysis_run_id
        )
        payload = {"status": "complete", "derived_artifact_dir": str(run_dir)}
    elif args.command == "validate-derived":
        artifact = validate_derived_artifact(args.artifact)
        payload = {
            "status": "valid",
            "artifact_id": artifact.artifact_id,
            "row_count": artifact.table.num_rows,
        }
    else:
        operator_input = validate_store_operator_evidence_report(args.report)
        payload = operator_input.validation_receipt()
    print(canonical_json_bytes(payload).decode("utf-8"))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
