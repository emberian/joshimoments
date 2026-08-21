from __future__ import annotations

import json
from pathlib import Path

import pytest

from joshi_analysis.canonical import canonical_json_bytes, qualified_sha256_bytes
from joshi_analysis.derived_artifacts import (
    publish_restricted_descriptive_artifact,
    validate_derived_artifact,
)
from joshi_analysis.errors import HashMismatchError, ManifestError, TemporalLeakageError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "snapshot_v1"
OPERATIONAL_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "export" / "operational_snapshot_v2"
)


def test_restricted_descriptive_artifact_is_byte_reproducible(tmp_path: Path) -> None:
    first = publish_restricted_descriptive_artifact(FIXTURE, tmp_path / "a")
    second = publish_restricted_descriptive_artifact(FIXTURE, tmp_path / "b")
    assert first.name == second.name
    for filename in ("manifest.json", "descriptive_chart_shapes.parquet"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    artifact = validate_derived_artifact(first)
    assert artifact.table.num_rows == 4
    assert artifact.manifest["restrictions"] == {
        "economic_authority": "none",
        "may_activate_hot_scope": False,
        "may_mutate_facts": False,
        "may_mutate_financial_truth": False,
        "may_mutate_observations": False,
        "may_rank_census": False,
    }


def test_altered_output_bytes_fail_readback(tmp_path: Path) -> None:
    artifact = publish_restricted_descriptive_artifact(FIXTURE, tmp_path / "runs")
    path = artifact / "descriptive_chart_shapes.parquet"
    path.write_bytes(path.read_bytes() + b"altered")
    with pytest.raises(HashMismatchError, match="physical bytes"):
        validate_derived_artifact(artifact)


def test_future_known_manifest_is_rejected_even_when_self_hash_would_be_recomputed(
    tmp_path: Path,
) -> None:
    artifact = publish_restricted_descriptive_artifact(FIXTURE, tmp_path / "runs")
    manifest_path = artifact / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["fit"]["maximum_input_available_at"] = "2099-01-01T00:00:00.000000Z"
    preimage = {key: value for key, value in manifest.items() if key != "artifact_id"}
    manifest["artifact_id"] = qualified_sha256_bytes(canonical_json_bytes(preimage))
    manifest_path.write_bytes(canonical_json_bytes(manifest, newline=True))
    # A producer cannot convert later-known data into fit-time data by recomputing every hash.
    with pytest.raises(TemporalLeakageError, match="future-known"):
        validate_derived_artifact(artifact)


def test_operational_v2_artifact_is_reproducible_and_publication_closed(
    tmp_path: Path,
) -> None:
    first = publish_restricted_descriptive_artifact(
        OPERATIONAL_FIXTURE,
        tmp_path / "a",
        analysis_run_id="analysis-run-production-fixture-001",
    )
    second = publish_restricted_descriptive_artifact(
        OPERATIONAL_FIXTURE,
        tmp_path / "b",
        analysis_run_id="analysis-run-production-fixture-001",
    )
    assert first.name == second.name
    for filename in ("manifest.json", "descriptive_chart_shapes.parquet"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    artifact = validate_derived_artifact(first)
    assert artifact.manifest["analysis_run_id"] == "analysis-run-production-fixture-001"
    assert artifact.manifest["input"] == {
        "catalog_commit_seq": "13",
        "publication_ids": ["publication-001"],
        "snapshot_contract": "joshi.analysis.snapshot/v2",
        "snapshot_id": "sha256:667934d19480a9d6e88181e0b374aff07d5dc58864037630699becbb43938fe6",
        "snapshot_manifest_digest": (
            "sha256:0d6642232bba99d330ca1328f597f93"
            "0808a0e90c75c56e5e26e7123c4b55cbe"
        ),
        "source_class": "operational_store",
    }


def test_operational_artifact_requires_reserved_analysis_run_occurrence(
    tmp_path: Path,
) -> None:
    with pytest.raises(ManifestError, match="analysis_run_id"):
        publish_restricted_descriptive_artifact(OPERATIONAL_FIXTURE, tmp_path / "missing")
