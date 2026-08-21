from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from joshi_analysis.contracts import (
    COVERAGE_GAP_SCHEMA,
    COVERAGE_WINDOW_SCHEMA,
    PROVENANCE_ASSERTION_SCHEMA,
)
from joshi_analysis.listing_census import (
    LANDED_ERROR_FAMILY,
    LANDED_NO_ERROR_FAMILY,
    ListingCensusError,
    read_listing_census,
)

SUBJECT = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh"
SOURCE = "helius.http.solana.v1"


def _instant(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def _provenance(rows: list[tuple[str, str, str]]) -> pa.Table:
    return pa.table(
        {
            "source_assertion_id": [row[0] for row in rows],
            "source_observation_id": [row[1] for row in rows],
            "source_id": [SOURCE for _ in rows],
            "semantic_key": [row[2] for row in rows],
            "value_digest": ["sha256:" + "0" * 64 for _ in rows],
            "observed_at": [_instant(1787175921) for _ in rows],
            "available_at": [_instant(1787175936) for _ in rows],
            "available_commit_seq": [4 for _ in rows],
        },
        schema=PROVENANCE_ASSERTION_SCHEMA,
    )


def _snapshot(root: Path, provenance: pa.Table) -> Path:
    root.mkdir(parents=True)
    pq.write_table(provenance, root / "provenance_assertions.parquet")
    pq.write_table(
        pa.table(
            {
                "coverage_window_id": ["cov-page0"],
                "coverage_scope_id": ["sha256:" + "1" * 64],
                "source_id": [SOURCE],
                "lower_time": [_instant(1787175921)],
                "upper_time": [_instant(1787175936)],
                "coverage_kind": ["market_census"],
                "available_commit_seq": [4],
            },
            schema=COVERAGE_WINDOW_SCHEMA,
        ),
        root / "coverage_windows.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "coverage_gap_id": ["gap-page0-truncated"],
                "coverage_window_id": ["cov-page0"],
                "coverage_scope_id": ["sha256:" + "1" * 64],
                "gap_class": ["listing_limit_truncated"],
                "opened_at": [_instant(1787175921)],
                "detected_at": [_instant(1787175936)],
                "available_at": [_instant(1787175936)],
                "recovered_at": [None],
                "recovery_known_at": [None],
                "available_commit_seq": [4],
            },
            schema=COVERAGE_GAP_SCHEMA,
        ),
        root / "coverage_gaps.parquet",
    )
    (root / "manifest.json").write_bytes(
        json.dumps(
            {
                "manifest_version": "joshi.analysis.snapshot/v2",
                "snapshot_id": "sha256:" + "2" * 64,
                "catalog": {
                    "catalog_id": "joshi-collector-live",
                    "catalog_schema": "joshi.sqlite.v24",
                    "from_commit_seq": "1",
                    "through_commit_seq": "7",
                    "as_of": {"rendered_at": "2026-08-19T18:00:00.000000Z"},
                },
            }
        ).encode("utf-8")
    )
    return root


def test_counts_partition_the_enumerated_denominator(tmp_path: Path) -> None:
    root = _snapshot(
        tmp_path / "snapshot",
        _provenance(
            [
                ("a-1", "obs-page", f"{LANDED_ERROR_FAMILY}/{SUBJECT}/sig-1"),
                ("a-1", "obs-tx", f"{LANDED_ERROR_FAMILY}/{SUBJECT}/sig-1"),
                ("a-2", "obs-page", f"{LANDED_ERROR_FAMILY}/{SUBJECT}/sig-2"),
                ("a-3", "obs-page", f"{LANDED_NO_ERROR_FAMILY}/{SUBJECT}/sig-3"),
            ]
        ),
    )
    payload = read_listing_census(root).payload
    assert payload["landed_error_count"] == "2"
    assert payload["landed_no_error_count"] == "1"
    assert payload["enumerated_count"] == "3"
    # Four exported rows are four evidence edges, not four transactions. The denominator counts
    # transactions; the edge count is reported beside it so the difference is never invisible.
    assert payload["provenance_edge_count"] == "4"
    assert payload["corroborated_count"] == "1"
    assert payload["subject_addresses"] == [SUBJECT]
    assert payload["source_ids"] == [SOURCE]
    assert payload["through_commit_seq"] == "7"
    assert payload["catalog_schema"] == "joshi.sqlite.v24"


def test_coverage_and_gaps_travel_with_the_count(tmp_path: Path) -> None:
    root = _snapshot(
        tmp_path / "snapshot",
        _provenance([("a-1", "obs-page", f"{LANDED_ERROR_FAMILY}/{SUBJECT}/sig-1")]),
    )
    payload = read_listing_census(root).payload
    assert [window["coverage_window_id"] for window in payload["coverage_windows"]] == [
        "cov-page0"
    ]
    assert payload["coverage_windows"][0]["lower_time_us"] == "1787175921000000"
    assert [gap["gap_class"] for gap in payload["coverage_gaps"]] == [
        "listing_limit_truncated"
    ]
    assert payload["coverage_gaps"][0]["recovered"] is False


def test_one_transaction_cannot_hold_both_outcome_families(tmp_path: Path) -> None:
    root = _snapshot(
        tmp_path / "snapshot",
        _provenance(
            [
                ("a-1", "obs-page", f"{LANDED_ERROR_FAMILY}/{SUBJECT}/sig-1"),
                ("a-2", "obs-other", f"{LANDED_NO_ERROR_FAMILY}/{SUBJECT}/sig-1"),
            ]
        ),
    )
    with pytest.raises(ListingCensusError):
        read_listing_census(root)


def test_unrelated_semantic_keys_do_not_enter_the_denominator(tmp_path: Path) -> None:
    root = _snapshot(
        tmp_path / "snapshot",
        _provenance(
            [
                ("a-1", "obs-page", f"{LANDED_ERROR_FAMILY}/{SUBJECT}/sig-1"),
                ("a-2", "obs-other", "some.other.family/subject/key"),
                ("a-3", "obs-third", "malformed-key-without-parts"),
            ]
        ),
    )
    payload = read_listing_census(root).payload
    assert payload["enumerated_count"] == "1"
    assert payload["provenance_edge_count"] == "3"
