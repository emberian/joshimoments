from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from joshi_analysis.canonical import qualified_sha256_bytes
from joshi_analysis.cli import main
from joshi_analysis.contracts import PREDICTION_CLAIM_SCOPE, PREDICTION_SCHEMA
from joshi_analysis.errors import ManifestError, TemporalLeakageError
from joshi_analysis.exocortex import (
    descriptive_analog_job,
    materialize_dataset_job,
    validate_dataset_run,
)
from joshi_analysis.predictions import evaluate_prediction_artifact

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "snapshot_v1"
DATASET_SPEC = ROOT / "specs" / "datasets" / "operator_choices_v1.json"
FEATURE_SPEC = ROOT / "specs" / "features" / "chart_shape_v1.json"
LABEL_SPEC = ROOT / "specs" / "labels" / "competing_risk_20m_v1.json"


def _materialize(tmp_path: Path, name: str = "datasets") -> Path:
    return materialize_dataset_job(
        FIXTURE,
        DATASET_SPEC,
        FEATURE_SPEC,
        LABEL_SPEC,
        tmp_path / name,
    )


def _prediction_rows(dataset_run: Path) -> list[dict[str, object]]:
    dataset = validate_dataset_run(dataset_run)
    rows: list[dict[str, object]] = []
    for dataset_row in dataset.rows.to_pylist():
        rank = dataset_row["source_rank"] or dataset_row["choice_set_size"]
        score = 1.0 / rank
        rows.append(
            {
                "prediction_id": (
                    f"prediction:{dataset_row['decision_id']}:{dataset_row['candidate_id']}"
                ),
                "model_id": "fixture-contract-model",
                "model_version": "1",
                "ensemble_id": "fixture-ensemble",
                "dataset_id": dataset.dataset_id,
                "decision_id": dataset_row["decision_id"],
                "candidate_id": dataset_row["candidate_id"],
                "universe_digest": dataset_row["universe_digest"],
                "information_cutoff": dataset_row["decision_available_at"],
                "score_name": "fixture_contract_score",
                "score_value": score,
                "uncertainty_lower": score - 0.1,
                "uncertainty_upper": score + 0.1,
                "uncertainty_level_ppm": 900_000,
                "calibration_method": "fixture_only_identity_calibration",
                "calibration_artifact_id": "calibration:fixture:v1",
                "calibration_artifact_digest": qualified_sha256_bytes(b"fixture-calibration"),
                "ensemble_member_count": 2,
                "missing_feature_policy": "explicit_missingness_state",
                "claim_scope": PREDICTION_CLAIM_SCOPE,
            }
        )
    return rows


def test_dataset_materialization_is_deterministic_and_point_in_time(tmp_path: Path) -> None:
    first = _materialize(tmp_path, "a")
    second = _materialize(tmp_path, "b")
    assert first.name == second.name
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "dataset_rows.parquet").read_bytes() == (
        second / "dataset_rows.parquet"
    ).read_bytes()

    dataset = validate_dataset_run(first)
    rows = dataset.rows.to_pylist()
    by_key = {(row["decision_id"], row["candidate_id"]): row for row in rows}

    # This identity's event predates decision-004, but it was observed/available afterward.
    assert by_key[("decision-004", "candidate-d")]["creator_identity_as_known"] is None
    assert by_key[("decision-001", "candidate-a")]["creator_identity_as_known"] == (
        "fixture-creator-a"
    )
    assert by_key[("decision-004", "candidate-d")]["label_status"] == ("right_censored_unknown")
    assert by_key[("decision-004", "candidate-d")]["label_event_kind"] is None
    assert by_key[("decision-001", "candidate-a")]["label_event_kind"] == "profit_target"
    assert by_key[("decision-002", "candidate-c")]["label_event_kind"] == "drawdown_stop"
    assert by_key[("decision-003", "candidate-b")]["label_event_kind"] == "liquidity_exit"

    universes = {}
    for row in rows:
        universes.setdefault(row["decision_id"], set()).add(row["candidate_id"])
    assert universes == {
        "decision-001": {"candidate-a", "candidate-b"},
        "decision-002": {"candidate-a", "candidate-c", "candidate-d"},
        "decision-003": {"candidate-b", "candidate-c"},
        "decision-004": {"candidate-a", "candidate-d", "candidate-e"},
    }
    assert {row["partition"] for row in rows} == {"train", "validation", "excluded_embargo"}


def test_analog_retrieval_is_earlier_and_non_predictive(tmp_path: Path) -> None:
    dataset_run = _materialize(tmp_path)
    first = descriptive_analog_job(dataset_run, tmp_path / "analogs-a", limit=2)
    second = descriptive_analog_job(dataset_run, tmp_path / "analogs-b", limit=2)
    assert first.name == second.name
    assert (first / "analog_results.parquet").read_bytes() == (
        second / "analog_results.parquet"
    ).read_bytes()
    rows = pq.read_table(first / "analog_results.parquet").to_pylist()
    assert [(row["query_decision_id"], row["analog_rank"]) for row in rows] == [
        ("decision-004", 1),
        ("decision-004", 2),
    ]
    assert all(row["analog_decision_id"] in {"decision-001", "decision-002"} for row in rows)
    assert all(
        row["claim_scope"] == "retrieval_only_not_prediction_or_strategy_claim" for row in rows
    )
    assert not ({"event_kind", "label_status", "score"} & set(rows[0]))


def test_prediction_evaluation_requires_the_complete_witnessed_universe(
    tmp_path: Path,
) -> None:
    dataset_run = _materialize(tmp_path)
    dataset = validate_dataset_run(dataset_run)
    prediction_rows = _prediction_rows(dataset_run)
    predictions = pa.Table.from_pylist(prediction_rows, schema=PREDICTION_SCHEMA)
    evaluation = evaluate_prediction_artifact(predictions, dataset.rows).to_pylist()
    assert len(evaluation) == 4
    decision_004 = next(row for row in evaluation if row["decision_id"] == "decision-004")
    assert decision_004["candidate_count"] == 3
    assert decision_004["label_status"] == "right_censored_unknown"
    assert decision_004["is_censored"] is True
    assert decision_004["event_kind"] is None

    stale_universe = pa.Table.from_pylist(prediction_rows[:-1], schema=PREDICTION_SCHEMA)
    with pytest.raises(ManifestError, match="universe differs"):
        evaluate_prediction_artifact(stale_universe, dataset.rows)


def test_prediction_information_cut_is_fail_closed(tmp_path: Path) -> None:
    dataset_run = _materialize(tmp_path)
    dataset = validate_dataset_run(dataset_run)
    prediction_rows = _prediction_rows(dataset_run)
    prediction_rows[0]["information_cutoff"] = prediction_rows[-1]["information_cutoff"]
    predictions = pa.Table.from_pylist(prediction_rows, schema=PREDICTION_SCHEMA)
    with pytest.raises(TemporalLeakageError, match="information cutoff"):
        evaluate_prediction_artifact(predictions, dataset.rows)


def test_cli_materialize_and_retrieve(tmp_path: Path, capsys: object) -> None:
    assert (
        main(
            [
                "materialize",
                "--snapshot",
                str(FIXTURE),
                "--dataset-spec",
                str(DATASET_SPEC),
                "--feature-spec",
                str(FEATURE_SPEC),
                "--label-spec",
                str(LABEL_SPEC),
                "--output-root",
                str(tmp_path / "datasets"),
            ]
        )
        == 0
    )
    materialize_payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    dataset_run = Path(materialize_payload["dataset_run_dir"])
    assert dataset_run.is_dir()
    assert (
        main(
            [
                "retrieve-analogs",
                "--dataset-run",
                str(dataset_run),
                "--output-root",
                str(tmp_path / "analogs"),
            ]
        )
        == 0
    )
    analog_payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert Path(analog_payload["analog_run_dir"]).is_dir()
