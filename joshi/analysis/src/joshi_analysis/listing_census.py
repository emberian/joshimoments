"""One model-free descriptive reading of an installed Snapshot V2 directory.

This is the second runtime for the Pillar 7 S8 estimand. It shares no code with the Rust
exporter and no code with :mod:`joshi_analysis.snapshot`: the manifest is read with the standard
library, the Parquet parts are read with DuckDB, and the counting is done in SQL. Agreement
between the two runtimes is therefore agreement between two independent readers of the same
installed bytes, not two printings of one computation.

Nothing here estimates, scores, ranks, or forecasts. It counts rows and reports the coverage,
the gaps and the cutoff the snapshot itself carries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

LANDED_ERROR_FAMILY = "solana.finalized_listing_entry.landed_error"
LANDED_NO_ERROR_FAMILY = "solana.finalized_listing_entry.landed_no_error"

CONTRACT = "joshi.export.listing-error-census/v1"


class ListingCensusError(RuntimeError):
    """The snapshot cannot support a listing census reading."""


@dataclass(frozen=True, slots=True)
class ListingCensus:
    payload: dict[str, Any]


def _manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / "manifest.json"
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise ListingCensusError("manifest exceeds the bounded input")
    manifest = json.loads(raw.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ListingCensusError("manifest is not an object")
    return manifest, "sha256:" + hashlib.sha256(raw).hexdigest()


def _part(root: Path, name: str) -> Path:
    path = root / f"{name}.parquet"
    if not path.is_file() or path.is_symlink():
        raise ListingCensusError(f"snapshot part is missing or unsafe: {name}")
    return path


def _split_key(key: str) -> tuple[str, str, str] | None:
    parts = key.split("/")
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[0], parts[1], parts[2]


def read_listing_census(root: Path) -> ListingCensus:
    """Count the listing census an installed snapshot carries.

    Raises:
        ListingCensusError: when the manifest or a part cannot be read, or when one listed
            transaction is claimed by both outcome families.
    """

    root = Path(root)
    manifest, manifest_digest = _manifest(root)
    catalog = manifest.get("catalog")
    if not isinstance(catalog, dict):
        raise ListingCensusError("manifest carries no catalog closure")
    as_of = catalog.get("as_of")
    if not isinstance(as_of, dict):
        raise ListingCensusError("manifest carries no as-of vector")

    connection = duckdb.connect()
    try:
        provenance = connection.execute(
            "SELECT source_assertion_id, semantic_key, source_id FROM read_parquet(?)",
            [str(_part(root, "provenance_assertions"))],
        ).fetchall()
        windows = connection.execute(
            "SELECT coverage_window_id, coverage_scope_id, source_id, coverage_kind,"
            " epoch_us(lower_time), epoch_us(upper_time)"
            " FROM read_parquet(?) ORDER BY coverage_window_id",
            [str(_part(root, "coverage_windows"))],
        ).fetchall()
        gaps = connection.execute(
            "SELECT coverage_gap_id, coverage_window_id, gap_class,"
            " epoch_us(opened_at), epoch_us(detected_at), recovered_at IS NOT NULL"
            " FROM read_parquet(?) ORDER BY coverage_gap_id",
            [str(_part(root, "coverage_gaps"))],
        ).fetchall()
    finally:
        connection.close()

    by_signature: dict[tuple[str, str], str] = {}
    edges_by_assertion: dict[str, int] = {}
    source_ids: set[str] = set()
    for assertion_id, semantic_key, source_id in provenance:
        source_ids.add(source_id)
        edges_by_assertion[assertion_id] = edges_by_assertion.get(assertion_id, 0) + 1
        split = _split_key(semantic_key)
        if split is None:
            continue
        family, subject, signature = split
        if family == LANDED_ERROR_FAMILY:
            outcome = "error"
        elif family == LANDED_NO_ERROR_FAMILY:
            outcome = "no_error"
        else:
            continue
        previous = by_signature.setdefault((subject, signature), outcome)
        if previous != outcome:
            raise ListingCensusError(
                f"listed transaction {signature} carries both outcome families"
            )

    landed_error = sum(1 for value in by_signature.values() if value == "error")
    landed_no_error = sum(1 for value in by_signature.values() if value == "no_error")
    payload = {
        "contract": CONTRACT,
        "snapshot_id": manifest["snapshot_id"],
        "manifest_digest": manifest_digest,
        "catalog_id": catalog["catalog_id"],
        "catalog_schema": catalog["catalog_schema"],
        "from_commit_seq": catalog["from_commit_seq"],
        "through_commit_seq": catalog["through_commit_seq"],
        "as_of_rendered_at": as_of["rendered_at"],
        "source_ids": sorted(source_ids),
        "subject_addresses": sorted({subject for subject, _ in by_signature}),
        "landed_error_count": str(landed_error),
        "landed_no_error_count": str(landed_no_error),
        "enumerated_count": str(landed_error + landed_no_error),
        "provenance_edge_count": str(len(provenance)),
        "corroborated_count": str(
            sum(1 for count in edges_by_assertion.values() if count > 1)
        ),
        "coverage_windows": [
            {
                "coverage_window_id": row[0],
                "coverage_scope_id": row[1],
                "source_id": row[2],
                "coverage_kind": row[3],
                "lower_time_us": str(row[4]),
                "upper_time_us": str(row[5]),
            }
            for row in windows
        ],
        "coverage_gaps": [
            {
                "coverage_gap_id": row[0],
                "coverage_window_id": row[1],
                "gap_class": row[2],
                "opened_at_us": str(row[3]),
                "detected_at_us": str(row[4]),
                "recovered": bool(row[5]),
            }
            for row in gaps
        ],
    }
    return ListingCensus(payload=payload)
