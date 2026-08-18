from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from joshi_analysis.canonical import (
    canonical_json_bytes,
    logical_table_sha256,
    qualified_sha256_bytes,
    qualified_sha256_file,
    sha256_bytes,
)
from joshi_analysis.contracts import TABLE_CONTRACTS
from joshi_analysis.errors import (
    CoverageError,
    HashMismatchError,
    ManifestError,
    SchemaMismatchError,
    TemporalLeakageError,
)
from joshi_analysis.fixture import fixture_rows, fixture_tables, write_fixture_snapshot
from joshi_analysis.snapshot import validate_snapshot

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "snapshot_v1"
G0_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "export"
    / "operational_snapshot_v10"
)


def _rehash_manifest(manifest: dict[str, object]) -> None:
    preimage = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    manifest["snapshot_id"] = "sha256:" + sha256_bytes(canonical_json_bytes(preimage))


def _replace_g0_table(destination: Path, name: str, table: pa.Table) -> None:
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    table_manifest = next(item for item in manifest["tables"] if item["name"] == name)
    table_path = destination / table_manifest["path"]
    pq.write_table(table, table_path, compression="zstd", use_dictionary=False)
    table_manifest["physical_digest"] = qualified_sha256_file(table_path)
    table_manifest["logical_digest"] = logical_table_sha256(
        table, table_manifest["primary_key"]
    )
    table_manifest["byte_length"] = table_path.stat().st_size
    table_manifest["row_count"] = table.num_rows
    _rehash_manifest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest, newline=True))


def test_manifested_fixture_validates() -> None:
    snapshot = validate_snapshot(FIXTURE)
    assert snapshot.manifest["knowledge_mode"] == "as_known"
    assert snapshot.chart_samples.num_rows == 20
    chart_manifest = next(
        table for table in snapshot.manifest["tables"] if table["name"] == "chart_samples"
    )
    coverage = chart_manifest["coverage"]
    assert coverage == {
        "expected_rows": 20,
        "observed_rows": 18,
        "explicit_gap_rows": 2,
        "coverage_ratio_ppm": 900_000,
        "coverage_scope_ids": [
            "scope:chart:candidate-a",
            "scope:chart:candidate-b",
            "scope:chart:candidate-c",
            "scope:chart:candidate-d",
        ],
        "coverage_window_ids": [
            "coverage-window:scene-001",
            "coverage-window:scene-002",
            "coverage-window:scene-003",
            "coverage-window:scene-004",
        ],
        "coverage_gap_ids": ["coverage-gap:scene-003", "coverage-gap:scene-004"],
    }
    assert chart_manifest["primary_key"] == ["scene_id", "episode_id", "sample_index"]
    assert all(
        table[field].startswith("sha256:")
        for table in snapshot.manifest["tables"]
        for field in ("schema_digest", "physical_digest", "logical_digest")
    )
    assert snapshot.manifest["catalog"]["as_of"]["catalog_commit"] == "120"


def test_rust_produced_g0_fixture_reopens_exact_24_relation_semantics() -> None:
    snapshot = validate_snapshot(G0_FIXTURE)
    assert snapshot.manifest["catalog"]["catalog_schema"] == "joshi.sqlite.v10"
    assert len(snapshot.tables) == 24
    assert snapshot.tables["source_fact_occurrences"].num_rows == 1
    assert snapshot.tables["act_occurrences"]["logical_start_tick"].to_pylist() == [
        "9007199254740993"
    ]


def test_g0_rehashed_malformed_source_bytes_are_semantically_refused(tmp_path: Path) -> None:
    destination = tmp_path / "g0-source-tamper"
    shutil.copytree(G0_FIXTURE, destination)
    table = pq.read_table(destination / "source_fact_occurrences.parquet")
    rows = table.to_pylist()
    rows[0]["descriptor_bytes"] = b"{}"
    rows[0]["descriptor_digest"] = qualified_sha256_bytes(b"{}")
    rows[0]["descriptor_byte_length"] = 2
    _replace_g0_table(
        destination,
        "source_fact_occurrences",
        pa.Table.from_pylist(rows, schema=table.schema),
    )
    with pytest.raises(ManifestError, match="source descriptor"):
        validate_snapshot(destination)


def test_g0_rehashed_memory_tick_above_u64_is_refused(tmp_path: Path) -> None:
    destination = tmp_path / "g0-tick-tamper"
    shutil.copytree(G0_FIXTURE, destination)
    table = pq.read_table(destination / "act_occurrences.parquet")
    rows = table.to_pylist()
    occurrence = json.loads(rows[0]["occurrence_bytes"])
    occurrence["value"]["occurredAt"] = "18446744073709551616"
    forged = json.dumps(
        occurrence, ensure_ascii=False, sort_keys=False, separators=(",", ":")
    ).encode()
    rows[0]["occurrence_bytes"] = forged
    rows[0]["occurrence_digest"] = qualified_sha256_bytes(forged)
    rows[0]["occurrence_byte_length"] = len(forged)
    rows[0]["logical_start_tick"] = "18446744073709551616"
    _replace_g0_table(
        destination,
        "act_occurrences",
        pa.Table.from_pylist(rows, schema=table.schema),
    )
    with pytest.raises(ManifestError, match="exceeds u64"):
        validate_snapshot(destination)


def test_physical_hash_tampering_is_rejected(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, destination)
    table_path = destination / "chart_samples.parquet"
    table_path.write_bytes(table_path.read_bytes() + b"tampered")
    with pytest.raises(HashMismatchError, match="physical hash mismatch"):
        validate_snapshot(destination)


def test_future_available_information_is_rejected(tmp_path: Path) -> None:
    rows = fixture_rows()
    rows[0]["available_at"] = rows[0]["decision_available_at"] + timedelta(microseconds=1)
    destination = write_fixture_snapshot(tmp_path / "future-snapshot", rows=rows)

    # The fixture writer rehashes both table and manifest, so this reaches the temporal gate rather
    # than merely failing an integrity check.
    with pytest.raises(TemporalLeakageError, match="exceeds its as-known decision cut"):
        validate_snapshot(destination)


def test_manifest_self_hash_tampering_is_rejected(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["maximum_decision_available_at"] = "2026-08-16T15:00:00.000000Z"
    manifest_path.write_bytes(canonical_json_bytes(manifest, newline=True))
    with pytest.raises(HashMismatchError, match="snapshot_id mismatch"):
        validate_snapshot(destination)


def test_manifested_schema_contract_is_enforced(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["tables"][0]["schema"]["fields"][0]["name"] = "renamed_scene_id"
    _rehash_manifest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest, newline=True))

    # Rehashing the outer manifest proves this reaches schema validation instead of the
    # manifest-integrity gate.
    with pytest.raises(SchemaMismatchError, match="not accepted v1"):
        validate_snapshot(destination)


def test_manifested_coverage_contract_is_enforced(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    chart_manifest = next(table for table in manifest["tables"] if table["name"] == "chart_samples")
    chart_manifest["coverage"]["observed_rows"] = 17
    _rehash_manifest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest, newline=True))

    with pytest.raises(CoverageError, match="coverage mismatch"):
        validate_snapshot(destination)


def test_fixture_builder_is_byte_reproducible(tmp_path: Path) -> None:
    rebuilt = write_fixture_snapshot(tmp_path / "rebuilt")
    expected = {path.name: path.read_bytes() for path in FIXTURE.iterdir()}
    actual = {path.name: path.read_bytes() for path in rebuilt.iterdir()}
    assert actual == expected


def test_duplicate_manifest_keys_are_rejected_before_hash_validation(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, destination)
    manifest_path = destination / "manifest.json"
    raw = manifest_path.read_bytes()
    duplicate = raw.replace(
        b'"knowledge_mode":"as_known"',
        b'"knowledge_mode":"as_known","knowledge_mode":"as_known"',
        1,
    )
    manifest_path.write_bytes(duplicate)
    with pytest.raises(ManifestError, match="duplicate JSON key"):
        validate_snapshot(destination)


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        (b'"coverage_ratio_ppm":900000', b'"coverage_ratio_ppm":NaN'),
        (b'"nullable":false', b'"nullable":Infinity'),
    ],
)
def test_nested_nonfinite_json_is_rejected_before_hash_validation(
    tmp_path: Path, needle: bytes, replacement: bytes
) -> None:
    destination = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, destination)
    manifest_path = destination / "manifest.json"
    raw = manifest_path.read_bytes()
    assert needle in raw
    manifest_path.write_bytes(raw.replace(needle, replacement, 1))
    with pytest.raises(ManifestError, match="non-finite JSON number"):
        validate_snapshot(destination)


@pytest.mark.parametrize("field", ["row_count", "coverage.expected_rows"])
def test_boolean_cannot_impersonate_an_integer_count(tmp_path: Path, field: str) -> None:
    tables = fixture_tables()
    one_outcome = tables["outcomes"].slice(0, 1)
    destination = write_fixture_snapshot(
        tmp_path / field.replace(".", "-"),
        table_overrides={"outcomes": one_outcome},
    )
    # Prove the one-row source snapshot is otherwise semantically valid.
    validate_snapshot(destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    outcome_manifest = next(table for table in manifest["tables"] if table["name"] == "outcomes")
    if field == "row_count":
        outcome_manifest["row_count"] = True
    else:
        outcome_manifest["coverage"]["expected_rows"] = True
    _rehash_manifest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest, newline=True))
    with pytest.raises((ManifestError, CoverageError), match=r"integer|nonnegative"):
        validate_snapshot(destination)


def test_provenance_join_uses_assertion_and_observation_identity(tmp_path: Path) -> None:
    rows = fixture_rows()
    rows[0]["source_observation_id"] = "observation:wrong-occurrence"
    destination = write_fixture_snapshot(tmp_path / "ambiguous-provenance", rows=rows)
    with pytest.raises(ManifestError, match="provenance is not closed"):
        validate_snapshot(destination)


def test_one_assertion_can_have_multiple_evidence_occurrences(tmp_path: Path) -> None:
    tables = fixture_tables()
    provenance = tables["provenance_assertions"].to_pylist()
    additional = dict(provenance[0])
    additional["source_observation_id"] = "observation:alternate-occurrence"
    provenance.append(additional)
    override = pa.Table.from_pylist(
        provenance,
        schema=TABLE_CONTRACTS["provenance_assertions"].schema,
    )
    destination = write_fixture_snapshot(
        tmp_path / "two-evidence-occurrences",
        table_overrides={"provenance_assertions": override},
    )
    snapshot = validate_snapshot(destination)
    assertion_ids = (
        snapshot.tables["provenance_assertions"].column("source_assertion_id").to_pylist()
    )
    assert len(set(assertion_ids)) < len(assertion_ids)


def test_optional_empty_relations_are_truthful_not_fabricated(tmp_path: Path) -> None:
    overrides = {
        name: pa.Table.from_pylist([], schema=TABLE_CONTRACTS[name].schema)
        for name in (
            "candidate_social_assertions",
            "operator_interviews",
            "outcomes",
        )
    }
    destination = write_fixture_snapshot(tmp_path / "no-optional-rows", table_overrides=overrides)
    snapshot = validate_snapshot(destination)
    for name in overrides:
        assert snapshot.tables[name].num_rows == 0
        table_manifest = next(
            table for table in snapshot.manifest["tables"] if table["name"] == name
        )
        assert table_manifest["coverage"]["coverage_ratio_ppm"] is None


def test_source_assertion_may_support_multiple_rows() -> None:
    snapshot = validate_snapshot(FIXTURE)
    assertion_ids = [
        value
        for value in snapshot.chart_samples.column("source_assertion_id").to_pylist()
        if value is not None
    ]
    assert len(set(assertion_ids)) < len(assertion_ids)
