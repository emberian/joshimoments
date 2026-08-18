from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from joshi_analysis.cli import main
from joshi_analysis.contracts import CHART_SAMPLE_SCHEMA, DESCRIPTIVE_CLAIM_SCOPE
from joshi_analysis.errors import ManifestError
from joshi_analysis.features import descriptive_chart_features
from joshi_analysis.job import run_descriptive_chart_job

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "snapshot_v1"


def test_job_is_deterministic_and_preserves_snapshot(tmp_path: Path) -> None:
    before = {path.name: path.read_bytes() for path in FIXTURE.iterdir()}
    first = run_descriptive_chart_job(FIXTURE, tmp_path / "runs-a")
    second = run_descriptive_chart_job(FIXTURE, tmp_path / "runs-b")

    assert first.name == second.name
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "row_results.parquet").read_bytes() == (
        second / "row_results.parquet"
    ).read_bytes()
    assert before == {path.name: path.read_bytes() for path in FIXTURE.iterdir()}

    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["claim_scope"] == DESCRIPTIVE_CLAIM_SCOPE
    assert manifest["determinism"] == {
        "canonical_row_order": ["scene_id", "episode_id"],
        "network_required": False,
        "operational_store_writes": False,
        "wall_clock_excluded": True,
    }

    rows = pq.read_table(first / "row_results.parquet").to_pylist()
    assert [row["scene_id"] for row in rows] == [
        "scene-001",
        "scene-002",
        "scene-003",
        "scene-004",
    ]
    assert all(row["claim_scope"] == DESCRIPTIVE_CLAIM_SCOPE for row in rows)
    assert rows[0]["path_signature"] == "+-++"
    assert rows[1]["signed_change_ppm"] == -80_000
    assert rows[2]["gap_samples"] == 1
    assert rows[3]["gap_samples"] == 1


def test_same_output_root_is_idempotent(tmp_path: Path) -> None:
    first = run_descriptive_chart_job(FIXTURE, tmp_path / "runs")
    second = run_descriptive_chart_job(FIXTURE, tmp_path / "runs")
    assert first == second


def test_cli_validate_and_run(tmp_path: Path, capsys: object) -> None:
    assert main(["validate", "--snapshot", str(FIXTURE)]) == 0
    validate_payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert validate_payload["status"] == "valid"

    assert (
        main(
            [
                "run",
                "--snapshot",
                str(FIXTURE),
                "--output-root",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    run_payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert run_payload["status"] == "complete"
    assert Path(run_payload["run_dir"]).is_dir()


def test_exact_atom_ratios_do_not_collapse_above_javascript_integer_width() -> None:
    rows = pq.read_table(FIXTURE / "chart_samples.parquet").slice(0, 2).to_pylist()
    adjacent = 2**53
    for index, row in enumerate(rows):
        row["sample_index"] = index
        row["expected_sample_count"] = 2
        row["price_base_atoms"] = Decimal(1)
        row["price_quote_atoms"] = Decimal(adjacent + index)
    table = pa.Table.from_pylist(rows, schema=CHART_SAMPLE_SCHEMA)
    result = descriptive_chart_features(table).to_pylist()[0]
    assert result["path_signature"] == "+"
    assert result["signed_change_ppm"] == 0


def test_atom_width_beyond_u64_refuses_before_analysis() -> None:
    rows = pq.read_table(FIXTURE / "chart_samples.parquet").slice(0, 2).to_pylist()
    rows[0]["price_quote_atoms"] = Decimal(2**64)
    table = pa.Table.from_pylist(rows, schema=CHART_SAMPLE_SCHEMA)
    with pytest.raises(ManifestError, match="u64 atom boundary"):
        descriptive_chart_features(table)
