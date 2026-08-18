from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
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
    SNAPSHOT_MANIFEST_VERSION,
    SNAPSHOT_MANIFEST_VERSION_V2,
    TABLE_CONTRACTS,
    TableContract,
)
from .errors import (
    CoverageError,
    HashMismatchError,
    ManifestError,
    SchemaMismatchError,
    TemporalLeakageError,
)

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidatedSnapshot:
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    manifest_digest: str
    tables: dict[str, pa.Table]

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest["snapshot_id"])

    @property
    def chart_samples(self) -> pa.Table:
        return self.tables["chart_samples"]


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{context} must be an object")
    return value


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key in manifest: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ManifestError(f"non-finite JSON number is forbidden: {value}")


def _require_exact_keys(value: dict[str, Any], keys: set[str], context: str) -> None:
    actual = set(value)
    if actual != keys:
        raise ManifestError(
            f"{context} keys differ: missing={sorted(keys - actual)}, extra={sorted(actual - keys)}"
        )


def _digest(value: Any, context: str) -> str:
    try:
        return require_qualified_sha256(value, context)
    except ValueError as error:
        raise ManifestError(str(error)) from error


def _parse_utc(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        raise ManifestError(f"{context} must be canonical microsecond UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ManifestError(f"{context} is not a valid timestamp") from error
    return parsed.astimezone(UTC)


def _parse_commit(value: Any, context: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ManifestError(f"{context} must be a canonical decimal string")
    if value != "0" and value.startswith("0"):
        raise ManifestError(f"{context} is not canonical")
    parsed = int(value)
    if parsed > 9_223_372_036_854_775_807:
        raise ManifestError(f"{context} exceeds the catalog's signed storage bound")
    return parsed


def _safe_table_path(snapshot_root: Path, relative: Any) -> Path:
    if not isinstance(relative, str):
        raise ManifestError("table.path must be a string")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts or "." in posix.parts:
        raise ManifestError(f"unsafe table path: {relative!r}")
    candidate = snapshot_root.joinpath(*posix.parts)
    resolved_root = snapshot_root.resolve()
    resolved = candidate.resolve()
    if resolved.parent != resolved_root or candidate.is_symlink():
        raise ManifestError(
            f"table path must be a direct, non-symlink snapshot child: {relative!r}"
        )
    if not resolved.is_file():
        raise ManifestError(f"manifested table is missing: {relative!r}")
    return resolved


def _validate_as_of(catalog: dict[str, Any], producer: dict[str, Any]) -> None:
    as_of = _require_dict(catalog["as_of"], "catalog.as_of")
    _require_exact_keys(
        as_of,
        {"catalog_commit", "sources", "chain", "projections", "rendered_at"},
        "catalog.as_of",
    )
    catalog_commit = _parse_commit(as_of["catalog_commit"], "catalog.as_of.catalog_commit")
    if catalog_commit != _parse_commit(catalog["through_commit_seq"], "through_commit_seq"):
        raise ManifestError("as_of.catalog_commit must equal catalog.through_commit_seq")
    _parse_utc(as_of["rendered_at"], "catalog.as_of.rendered_at")

    sources = as_of["sources"]
    if not isinstance(sources, list) or not sources:
        raise ManifestError("catalog.as_of.sources must be a non-empty array")
    source_ids: list[str] = []
    for index, raw_source in enumerate(sources):
        source = _require_dict(raw_source, f"catalog.as_of.sources[{index}]")
        _require_exact_keys(
            source,
            {"source_id", "delivered_through", "scoped_cursors", "received_through"},
            f"catalog.as_of.sources[{index}]",
        )
        if not isinstance(source["source_id"], str) or not source["source_id"]:
            raise ManifestError("source_id must be non-empty")
        source_ids.append(source["source_id"])
        delivered = _parse_commit(source["delivered_through"], "source.delivered_through")
        if delivered > catalog_commit:
            raise ManifestError("source delivery exceeds catalog cutoff")
        if source["received_through"] is not None:
            _parse_utc(source["received_through"], "source.received_through")
        cursors = source["scoped_cursors"]
        if not isinstance(cursors, list):
            raise ManifestError("scoped_cursors must be an array")
        cursor_keys: list[tuple[str, str, str]] = []
        for raw_cursor in cursors:
            cursor = _require_dict(raw_cursor, "scoped cursor")
            _require_exact_keys(
                cursor,
                {"family", "subject", "cursor_kind", "value", "advanced_through"},
                "scoped cursor",
            )
            key = (cursor["family"], cursor["subject"] or "", cursor["cursor_kind"])
            if not all(isinstance(item, str) for item in key):
                raise ManifestError("cursor scope fields must be strings or null subject")
            cursor_keys.append(key)
            if _parse_commit(cursor["advanced_through"], "cursor.advanced_through") > delivered:
                raise ManifestError("cursor advancement exceeds source delivery")
        if cursor_keys != sorted(cursor_keys) or len(cursor_keys) != len(set(cursor_keys)):
            raise ManifestError("scoped cursors must be strictly canonical and unique")
    if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
        raise ManifestError("sources must be strictly sorted and unique")

    chain = as_of["chain"]
    if chain is not None:
        chain = _require_dict(chain, "catalog.as_of.chain")
        _require_exact_keys(chain, {"cluster", "slot", "finality"}, "catalog.as_of.chain")
        _parse_commit(chain["slot"], "catalog.as_of.chain.slot")
        if not all(isinstance(chain[key], str) and chain[key] for key in ("cluster", "finality")):
            raise ManifestError("chain cluster/finality must be non-empty strings")

    projections = as_of["projections"]
    if not isinstance(projections, list) or not projections:
        raise ManifestError("catalog.as_of.projections must be a non-empty array")
    projection_names: list[str] = []
    for raw_projection in projections:
        projection = _require_dict(raw_projection, "projection watermark")
        _require_exact_keys(
            projection,
            {"name", "version", "state_digest", "delivered_through"},
            "projection watermark",
        )
        projection_names.append(projection["name"])
        _digest(projection["state_digest"], "projection.state_digest")
        if (
            _parse_commit(projection["delivered_through"], "projection.delivered_through")
            > catalog_commit
        ):
            raise ManifestError("projection delivery exceeds catalog cutoff")
    if projection_names != sorted(projection_names) or len(projection_names) != len(
        set(projection_names)
    ):
        raise ManifestError("projection watermarks must be strictly sorted and unique")

    matches = [
        item
        for item in projections
        if item["name"] == producer["projection_name"]
        and item["version"] == producer["projection_version"]
    ]
    if len(matches) != 1 or matches[0]["state_digest"] != producer["projection_state_digest"]:
        raise ManifestError("producer projection is not closed by the as-of projection vector")


def _validate_manifest_shape(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    base_keys = {
        "manifest_version",
        "snapshot_id",
        "created_at",
        "producer",
        "catalog",
        "knowledge_mode",
        "maximum_decision_available_at",
        "tables",
    }
    version = manifest.get("manifest_version")
    if version == SNAPSHOT_MANIFEST_VERSION:
        accepted_keys = (base_keys, base_keys | {"scene"})
    elif version == SNAPSHOT_MANIFEST_VERSION_V2:
        v2_keys = base_keys | {"origin", "publications", "truth_fingerprint"}
        accepted_keys = (v2_keys, v2_keys | {"scene"})
    else:
        raise ManifestError(f"unsupported manifest version: {manifest['manifest_version']!r}")
    if set(manifest) not in accepted_keys:
        _require_exact_keys(manifest, accepted_keys[0], "snapshot manifest")
    if manifest["knowledge_mode"] != "as_known":
        raise ManifestError("the workbench accepts only as_known snapshots")
    _digest(manifest["snapshot_id"], "snapshot_id")
    created_at = _parse_utc(manifest["created_at"], "created_at")
    maximum_decision = _parse_utc(
        manifest["maximum_decision_available_at"], "maximum_decision_available_at"
    )
    if maximum_decision > created_at:
        raise TemporalLeakageError("maximum decision availability exceeds snapshot creation")

    producer = _require_dict(manifest["producer"], "producer")
    _require_exact_keys(
        producer,
        {"build", "projection_name", "projection_version", "projection_state_digest"},
        "producer",
    )
    for key in ("build", "projection_name", "projection_version"):
        if not isinstance(producer[key], str) or not producer[key]:
            raise ManifestError(f"producer.{key} must be non-empty")
    _digest(producer["projection_state_digest"], "producer.projection_state_digest")

    catalog = _require_dict(manifest["catalog"], "catalog")
    _require_exact_keys(
        catalog,
        {"catalog_id", "catalog_schema", "from_commit_seq", "through_commit_seq", "as_of"},
        "catalog",
    )
    start = _parse_commit(catalog["from_commit_seq"], "catalog.from_commit_seq")
    through = _parse_commit(catalog["through_commit_seq"], "catalog.through_commit_seq")
    if not all(
        isinstance(catalog[key], str) and catalog[key] for key in ("catalog_id", "catalog_schema")
    ):
        raise ManifestError("catalog identity/schema must be non-empty")
    if start > through:
        raise ManifestError("catalog commit range is not closed")
    _validate_as_of(catalog, producer)

    if version == SNAPSHOT_MANIFEST_VERSION_V2:
        _validate_operational_v2(manifest, catalog, producer)

    if "scene" in manifest:
        scene = _require_dict(manifest["scene"], "scene")
        _require_exact_keys(scene, {"scene_id", "mode", "view_digest"}, "scene")
        if not all(isinstance(scene[key], str) and scene[key] for key in ("scene_id", "mode")):
            raise ManifestError("scene identity/mode must be non-empty")
        _digest(scene["view_digest"], "scene.view_digest")

    tables = manifest["tables"]
    if not isinstance(tables, list) or not tables:
        raise ManifestError("tables must be a non-empty array")
    by_name: dict[str, dict[str, Any]] = {}
    for index, raw_table in enumerate(tables):
        table = _require_dict(raw_table, f"tables[{index}]")
        _require_exact_keys(
            table,
            {
                "export_manifest_id",
                "name",
                "path",
                "schema_id",
                "schema",
                "schema_digest",
                "physical_digest",
                "logical_digest",
                "byte_length",
                "row_count",
                "primary_key",
                "commit_bounds",
                "event_bounds",
                "chain_bounds",
                "coverage",
            },
            f"tables[{index}]",
        )
        name = table["name"]
        if name not in TABLE_CONTRACTS or name in by_name:
            raise ManifestError(f"unsupported or duplicate snapshot table: {name!r}")
        if not isinstance(table["export_manifest_id"], str) or not table["export_manifest_id"]:
            raise ManifestError(f"{name}.export_manifest_id must be non-empty")
        contract = TABLE_CONTRACTS[name]
        if table["schema_id"] != contract.schema_id or table["primary_key"] != list(
            contract.primary_key
        ):
            raise ManifestError(f"{name} schema identity or primary key is not its v1 contract")
        for key in ("schema_digest", "physical_digest", "logical_digest"):
            _digest(table[key], f"{name}.{key}")
        if type(table["row_count"]) is not int or table["row_count"] < 0:
            raise ManifestError(f"{name}.row_count must be nonnegative")
        if type(table["byte_length"]) is not int or table["byte_length"] < 1:
            raise ManifestError(f"{name}.byte_length must be positive")
        bounds = _require_dict(table["commit_bounds"], f"{name}.commit_bounds")
        _require_exact_keys(bounds, {"from_commit_seq", "through_commit_seq"}, "commit_bounds")
        table_start = _parse_commit(bounds["from_commit_seq"], f"{name}.from_commit_seq")
        table_through = _parse_commit(bounds["through_commit_seq"], f"{name}.through_commit_seq")
        if table_start < start or table_start > table_through or table_through > through:
            raise ManifestError(f"{name} commit bounds escape catalog closure")
        by_name[name] = table
    if set(by_name) != set(TABLE_CONTRACTS):
        raise ManifestError(
            f"snapshot table closure differs: missing={sorted(set(TABLE_CONTRACTS) - set(by_name))}"
        )
    return by_name


def _validate_operational_v2(
    manifest: dict[str, Any], catalog: dict[str, Any], producer: dict[str, Any]
) -> None:
    origin = _require_dict(manifest["origin"], "origin")
    _require_exact_keys(
        origin,
        {
            "kind",
            "export_request_id",
            "catalog_snapshot_digest",
            "catalog_snapshot_byte_length",
        },
        "origin",
    )
    if origin["kind"] != "operational_store":
        raise ManifestError("snapshot V2 origin must be operational_store")
    if not isinstance(origin["export_request_id"], str) or not origin["export_request_id"]:
        raise ManifestError("origin.export_request_id must be non-empty")
    _digest(origin["catalog_snapshot_digest"], "origin.catalog_snapshot_digest")
    _parse_commit(origin["catalog_snapshot_byte_length"], "origin.catalog_snapshot_byte_length")

    truth = _require_dict(manifest["truth_fingerprint"], "truth_fingerprint")
    _require_exact_keys(
        truth,
        {
            "evidence_digest",
            "projection_digest",
            "observation_count",
            "assertion_count",
            "financial_effect_count",
        },
        "truth_fingerprint",
    )
    _digest(truth["evidence_digest"], "truth_fingerprint.evidence_digest")
    _digest(truth["projection_digest"], "truth_fingerprint.projection_digest")
    for key in ("observation_count", "assertion_count", "financial_effect_count"):
        _parse_commit(truth[key], f"truth_fingerprint.{key}")

    publications = manifest["publications"]
    if not isinstance(publications, list) or not publications:
        raise ManifestError("snapshot V2 requires a non-empty publication closure")
    publication_ids: list[str] = []
    catalog_cutoff = _parse_commit(catalog["through_commit_seq"], "catalog cutoff")
    projection_vector = {
        (item["name"], item["version"]): item
        for item in catalog["as_of"]["projections"]
    }
    projection_publications: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(publications):
        publication = _require_dict(raw, f"publications[{index}]")
        kind = publication.get("kind")
        common = {
            "kind",
            "publication_id",
            "publication_contract",
            "publication_digest",
            "published_commit_seq",
            "authority",
        }
        if kind == "projection":
            _require_exact_keys(
                publication,
                common
                | {
                    "projection_id",
                    "projection_name",
                    "projection_version",
                    "result_digest",
                    "artifact_digest",
                    "input_closure_digest",
                    "publication_bytes_digest",
                    "through_commit_seq",
                },
                f"publications[{index}]",
            )
            required_strings = (
                "publication_id",
                "publication_contract",
                "projection_id",
                "projection_name",
                "projection_version",
            )
        elif kind == "cockpit":
            _require_exact_keys(
                publication,
                common
                | {
                    "scene_id",
                    "projection_publication_id",
                    "projection_publication_digest",
                    "result_digest",
                    "artifact_digest",
                    "manifest_digest",
                    "query_policy",
                },
                f"publications[{index}]",
            )
            required_strings = (
                "publication_id",
                "publication_contract",
                "scene_id",
                "projection_publication_id",
                "query_policy",
            )
        else:
            raise ManifestError("publication.kind must be projection or cockpit")
        for key in required_strings:
            if not isinstance(publication[key], str) or not publication[key]:
                raise ManifestError(f"publication.{key} must be non-empty")
        publication_ids.append(publication["publication_id"])
        digest_keys = ["publication_digest", "result_digest", "artifact_digest"]
        if kind == "projection":
            digest_keys.extend(("input_closure_digest", "publication_bytes_digest"))
        else:
            digest_keys.extend(("manifest_digest", "projection_publication_digest"))
        for key in digest_keys:
            _digest(publication[key], f"publication.{key}")
        published = _parse_commit(
            publication["published_commit_seq"], "publication.published_commit_seq"
        )
        if published > catalog_cutoff:
            raise ManifestError("publication commit closure escapes the catalog cutoff")
        if publication["authority"] != "read_only_no_execution":
            raise ManifestError("publication exceeds read_only_no_execution")
        if kind == "projection":
            through = _parse_commit(publication["through_commit_seq"], "publication.through")
            if through >= published:
                raise ManifestError("projection publication must follow its input cutoff")
            watermark = projection_vector.get(
                (publication["projection_name"], publication["projection_version"])
            )
            if (
                watermark is None
                or watermark["state_digest"] != publication["result_digest"]
                or _parse_commit(watermark["delivered_through"], "projection delivery") != through
            ):
                raise ManifestError(
                    "publication is not closed by the exact as-of projection vector"
                )
            projection_publications[publication["publication_id"]] = publication
    if publication_ids != sorted(publication_ids) or len(publication_ids) != len(
        set(publication_ids)
    ):
        raise ManifestError("publication IDs must be strictly sorted and unique")
    for publication in publications:
        if publication["kind"] == "cockpit":
            projection = projection_publications.get(publication["projection_publication_id"])
            if (
                projection is None
                or projection["publication_digest"]
                != publication["projection_publication_digest"]
                or projection["result_digest"] != publication["result_digest"]
                or projection["artifact_digest"] != publication["artifact_digest"]
                or _parse_commit(projection["published_commit_seq"], "projection publication")
                >= _parse_commit(publication["published_commit_seq"], "cockpit publication")
            ):
                raise ManifestError("cockpit publication lacks its prior exact projection closure")
    if not any(
        item["kind"] == "projection"
        and
        item["projection_name"] == producer["projection_name"]
        and item["projection_version"] == producer["projection_version"]
        and item["result_digest"] == producer["projection_state_digest"]
        for item in publications
    ):
        raise ManifestError("producer is absent from the exact publication closure")


def _validate_snapshot_id(manifest: dict[str, Any]) -> None:
    preimage = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    actual = qualified_sha256_bytes(canonical_json_bytes(preimage))
    if manifest["snapshot_id"] != actual:
        raise HashMismatchError(
            f"snapshot_id mismatch: expected {manifest['snapshot_id']}, computed {actual}"
        )


def _validate_schema(
    table: pa.Table, table_manifest: dict[str, Any], contract: TableContract
) -> None:
    if table_manifest["schema"] != schema_descriptor(contract.schema):
        raise SchemaMismatchError(f"manifested {table_manifest['name']} schema is not accepted v1")
    if table_manifest["schema_digest"] != schema_sha256(contract.schema):
        raise SchemaMismatchError(f"manifested {table_manifest['name']} schema digest is invalid")
    if not table.schema.equals(contract.schema, check_metadata=True):
        raise SchemaMismatchError(f"Parquet schema differs for {table_manifest['name']}")


def _validate_keys(table: pa.Table, name: str, primary_key: tuple[str, ...]) -> None:
    rows = table.to_pylist()
    keys = [tuple(row[key] for key in primary_key) for row in rows]
    if len(keys) != len(set(keys)):
        raise ManifestError(f"{name} contains duplicate primary keys")


def _coverage_from_table(table: pa.Table) -> dict[str, Any]:
    names = set(table.column_names)
    if "coverage_status" in names:
        statuses = table.column("coverage_status").to_pylist()
        observed = statuses.count("observed")
        gaps = statuses.count("gap")
    else:
        observed = table.num_rows
        gaps = 0
    scopes = (
        sorted(set(table.column("coverage_scope_id").to_pylist()))
        if "coverage_scope_id" in names
        else []
    )
    windows = (
        sorted(set(table.column("coverage_window_id").to_pylist()))
        if "coverage_window_id" in names
        else []
    )
    gap_ids = (
        sorted(
            value for value in set(table.column("coverage_gap_id").to_pylist()) if value is not None
        )
        if "coverage_gap_id" in names
        else []
    )
    return {
        "expected_rows": table.num_rows,
        "observed_rows": observed,
        "explicit_gap_rows": gaps,
        "coverage_ratio_ppm": (observed * 1_000_000 // table.num_rows if table.num_rows else None),
        "coverage_scope_ids": scopes,
        "coverage_window_ids": windows,
        "coverage_gap_ids": gap_ids,
    }


def _validate_bounds_and_coverage(
    table: pa.Table, table_manifest: dict[str, Any], contract: TableContract
) -> None:
    commits = table.column("available_commit_seq").to_pylist()
    bounds = table_manifest["commit_bounds"]
    lower_commit = _parse_commit(bounds["from_commit_seq"], "table commit lower")
    upper_commit = _parse_commit(bounds["through_commit_seq"], "table commit upper")
    if commits and (min(commits) < lower_commit or max(commits) > upper_commit):
        raise ManifestError(f"{table_manifest['name']} row commit escapes its part bounds")

    event_bounds = table_manifest["event_bounds"]
    values = []
    if contract.event_time_field is not None:
        values = [
            value
            for value in table.column(contract.event_time_field).to_pylist()
            if value is not None
        ]
    if values:
        expected = {
            "lower_inclusive": iso_utc(min(values)),
            "upper_inclusive": iso_utc(max(values)),
        }
        if event_bounds != expected:
            raise ManifestError(f"{table_manifest['name']} event bounds are false")
    elif event_bounds is not None:
        raise ManifestError(f"{table_manifest['name']} event bounds must be null")
    if table_manifest["chain_bounds"] is not None:
        raise ManifestError("fixture tables carry no row-level chain-slot column")

    coverage = _require_dict(table_manifest["coverage"], "coverage")
    _require_exact_keys(
        coverage,
        {
            "expected_rows",
            "observed_rows",
            "explicit_gap_rows",
            "coverage_ratio_ppm",
            "coverage_scope_ids",
            "coverage_window_ids",
            "coverage_gap_ids",
        },
        "coverage",
    )
    for field in ("expected_rows", "observed_rows", "explicit_gap_rows"):
        if type(coverage[field]) is not int or coverage[field] < 0:
            raise CoverageError(f"coverage.{field} must be a nonnegative integer")
    ratio = coverage["coverage_ratio_ppm"]
    if ratio is not None and (type(ratio) is not int or not 0 <= ratio <= 1_000_000):
        raise CoverageError("coverage.coverage_ratio_ppm must be null or integer ppm")
    if any(
        not isinstance(coverage[field], list)
        or any(not isinstance(value, str) or not value for value in coverage[field])
        for field in ("coverage_scope_ids", "coverage_window_ids", "coverage_gap_ids")
    ):
        raise CoverageError("coverage identities must be arrays of non-empty strings")
    actual = _coverage_from_table(table)
    if coverage != actual:
        name = table_manifest["name"]
        raise CoverageError(
            f"coverage mismatch for {name}: expected {coverage!r}, computed {actual!r}"
        )


def _rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def _validate_semantics(tables: dict[str, pa.Table], manifest: dict[str, Any]) -> None:
    scenes = {row["scene_id"]: row for row in _rows(tables["scenes"])}
    territories = {row["territory_id"]: row for row in _rows(tables["territories"])}
    candidates = {row["candidate_id"]: row for row in _rows(tables["candidates"])}
    decisions = {row["decision_id"]: row for row in _rows(tables["decisions"])}
    episodes = {row["episode_id"]: row for row in _rows(tables["episodes"])}
    provenance_ids = {
        (row["source_assertion_id"], row["source_observation_id"])
        for row in _rows(tables["provenance_assertions"])
    }
    provenance_available: dict[tuple[str, str], datetime] = {}
    provenance_commit: dict[tuple[str, str], int] = {}
    source_ids = {source["source_id"] for source in manifest["catalog"]["as_of"]["sources"]}
    for row in _rows(tables["provenance_assertions"]):
        key = (row["source_assertion_id"], row["source_observation_id"])
        previous = provenance_available.get(key)
        if previous is None or row["available_at"] < previous:
            provenance_available[key] = row["available_at"]
            provenance_commit[key] = row["available_commit_seq"]
        if row["observed_at"] > row["available_at"]:
            raise TemporalLeakageError("provenance assertion became available before observation")
        if row["source_id"] not in source_ids:
            raise ManifestError("provenance source is absent from the as-of vector")
        _digest(row["value_digest"], "provenance value_digest")

    for row in candidates.values():
        if row["territory_id"] not in territories:
            raise ManifestError("candidate refers to an unknown territory")
        provenance_key = (row["source_assertion_id"], row["source_observation_id"])
        if provenance_key not in provenance_ids:
            raise ManifestError("candidate provenance is not closed by the export")
    for row in territories.values():
        provenance_key = (row["source_assertion_id"], row["source_observation_id"])
        if provenance_key not in provenance_ids:
            raise ManifestError("territory provenance is not closed by the export")

    for row in _rows(tables["candidate_social_assertions"]):
        provenance_key = (row["source_assertion_id"], row["source_observation_id"])
        if row["candidate_id"] not in candidates or provenance_key not in provenance_ids:
            raise ManifestError("social assertion lacks candidate or provenance closure")
        if not (row["event_time"] <= row["observed_at"] <= row["available_at"]):
            raise TemporalLeakageError("social assertion clocks are not ordered")

    choice_by_decision: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(tables["choice_members"]):
        decision = decisions.get(row["decision_id"])
        if decision is None or row["candidate_id"] not in candidates:
            raise ManifestError("choice member lacks decision/candidate closure")
        if (
            row["scene_id"] != decision["scene_id"]
            or row["choice_set_id"] != decision["choice_set_id"]
        ):
            raise ManifestError("choice member disagrees with its decision scene/set")
        if row["available_at"] > decision["decision_available_at"]:
            raise TemporalLeakageError("choice membership became available after its decision")
        scene = scenes[decision["scene_id"]]
        candidate = candidates[row["candidate_id"]]
        if (
            row["available_commit_seq"] > scene["knowledge_commit_seq"]
            or candidate["available_commit_seq"] > scene["knowledge_commit_seq"]
            or candidate["first_available_at"] > decision["decision_available_at"]
        ):
            raise TemporalLeakageError("choice candidate was not known at the witnessed scene cut")
        assertion = row["evidence_assertion_id"]
        if assertion is not None:
            observation = row["evidence_observation_id"]
            if observation is None or (assertion, observation) not in provenance_ids:
                raise ManifestError("choice evidence is not closed by the export")
            if provenance_available[(assertion, observation)] > decision["decision_available_at"]:
                raise TemporalLeakageError("choice evidence was unavailable at decision time")
            if provenance_commit[(assertion, observation)] > scene["knowledge_commit_seq"]:
                raise TemporalLeakageError("choice evidence commit exceeds witnessed scene cut")
        elif row["evidence_observation_id"] is not None:
            raise ManifestError("choice evidence observation cannot exist without its assertion")
        choice_by_decision.setdefault(row["decision_id"], []).append(row)

    for decision in decisions.values():
        scene = scenes.get(decision["scene_id"])
        if scene is None:
            raise ManifestError("decision refers to an unknown scene")
        if decision["decision_available_at"] != scene["decision_available_at"]:
            raise ManifestError("decision cutoff differs from witnessed scene cutoff")
        eligible = {
            row["candidate_id"]
            for row in choice_by_decision.get(decision["decision_id"], [])
            if row["set_kind"] == "eligible"
        }
        if not eligible:
            raise ManifestError("every decision requires a non-empty eligible choice set")
        selected = decision["selected_candidate_id"]
        if selected is not None and selected not in eligible:
            raise ManifestError("selected candidate was not in the witnessed eligible universe")
        episode_id = decision["episode_id"]
        if episode_id is not None:
            episode = episodes.get(episode_id)
            if episode is None or episode["decision_id"] != decision["decision_id"]:
                raise ManifestError("decision episode is not closed")

    for episode in episodes.values():
        candidate = candidates.get(episode["candidate_id"])
        if candidate is None or episode["territory_id"] != candidate["territory_id"]:
            raise ManifestError("episode candidate/territory join is inconsistent")
        if episode["closed_at"] is not None and episode["closed_at"] < episode["opened_at"]:
            raise ManifestError("episode closes before opening")
        reentry = episode["reentry_of_episode_id"]
        if reentry is not None and reentry not in episodes:
            raise ManifestError("re-entry episode predecessor is absent")

    windows = {row["coverage_window_id"]: row for row in _rows(tables["coverage_windows"])}
    gaps = {row["coverage_gap_id"]: row for row in _rows(tables["coverage_gaps"])}
    for gap in gaps.values():
        window = windows.get(gap["coverage_window_id"])
        if window is None or window["coverage_scope_id"] != gap["coverage_scope_id"]:
            raise CoverageError("coverage gap lacks its exact window/scope")
        if not (gap["opened_at"] <= gap["detected_at"] <= gap["available_at"]):
            raise CoverageError("coverage gap clocks are not ordered")
    if any(window["source_id"] not in source_ids for window in windows.values()):
        raise ManifestError("coverage window source is absent from the as-of vector")

    maximum_decision = _parse_utc(
        manifest["maximum_decision_available_at"], "maximum_decision_available_at"
    )
    if any(decision["decision_available_at"] > maximum_decision for decision in decisions.values()):
        raise TemporalLeakageError("decision exceeds the snapshot's maximum decision cut")
    chart_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in _rows(tables["chart_samples"]):
        key = (row["scene_id"], row["episode_id"])
        chart_groups.setdefault(key, []).append(row)
        decision = decisions.get(row["decision_id"])
        scene = scenes.get(row["scene_id"])
        episode = episodes.get(row["episode_id"])
        candidate = candidates.get(row["candidate_id"])
        if decision is None or scene is None or episode is None or candidate is None:
            raise ManifestError("chart sample lacks scene/decision/episode/candidate closure")
        if (
            decision["scene_id"] != row["scene_id"]
            or decision["episode_id"] != row["episode_id"]
            or episode["candidate_id"] != row["candidate_id"]
            or candidate["territory_id"] != row["territory_id"]
            or candidate["mint_asset_id"] != row["base_asset_id"]
            or scene["scene_mode"] != row["scene_mode"]
            or scene["view_digest"] != row["scene_view_digest"]
            or decision["decision_available_at"] != row["decision_available_at"]
        ):
            raise ManifestError("chart sample disagrees with its joined witnessed identities")
        if not (
            row["event_time"]
            <= row["observed_at"]
            <= row["available_at"]
            <= row["decision_available_at"]
            <= maximum_decision
        ):
            raise TemporalLeakageError("chart sample exceeds its as-known decision cut")
        if row["available_commit_seq"] > scene["knowledge_commit_seq"]:
            raise TemporalLeakageError("chart sample commit exceeds its witnessed scene cut")
        window = windows.get(row["coverage_window_id"])
        if window is None:
            raise CoverageError("chart sample coverage window is absent")
        if window["coverage_scope_id"] != row["coverage_scope_id"]:
            raise CoverageError("chart sample coverage scope differs from its window")
        measured = (
            row["price_base_atoms"],
            row["price_quote_atoms"],
            row["buy_volume_base_atoms"],
            row["sell_volume_base_atoms"],
        )
        if row["coverage_status"] == "observed":
            if any(value is None for value in measured) or any(value < 0 for value in measured):
                raise CoverageError("observed chart rows require nonnegative exact atom values")
            if any(value > 18_446_744_073_709_551_615 for value in measured):
                raise ManifestError("chart atom value exceeds the frozen u64 boundary")
            if row["price_base_atoms"] <= 0 or row["price_quote_atoms"] <= 0:
                raise CoverageError("observed exact price ratios must be positive")
            assertion = row["source_assertion_id"]
            observation = row["source_observation_id"]
            if (
                assertion is None
                or observation is None
                or (assertion, observation) not in provenance_ids
            ):
                raise ManifestError("observed chart provenance is not closed")
            if provenance_available[(assertion, observation)] > row["decision_available_at"]:
                raise TemporalLeakageError("chart source assertion was not available at decision")
            if provenance_commit[(assertion, observation)] > scene["knowledge_commit_seq"]:
                raise TemporalLeakageError("chart source assertion commit exceeds witnessed cut")
            if row["coverage_gap_id"] is not None:
                raise CoverageError("observed chart row cannot cite a gap")
        elif row["coverage_status"] == "gap":
            if any(value is not None for value in measured):
                raise CoverageError("gap rows cannot manufacture chart measurements")
            if (
                row["position_state"] != "unknown"
                or row["source_assertion_id"] is not None
                or row["source_observation_id"] is not None
            ):
                raise CoverageError("gap row must keep position/provenance unknown")
            gap_id = row["coverage_gap_id"]
            if (
                gap_id not in gaps
                or gaps[gap_id]["coverage_window_id"] != row["coverage_window_id"]
            ):
                raise CoverageError("gap row lacks its durable exact gap record")
        else:
            raise CoverageError("unsupported chart coverage status")

    for (scene_id, episode_id), rows in chart_groups.items():
        rows.sort(key=lambda row: row["sample_index"])
        expected = {row["expected_sample_count"] for row in rows}
        if len(expected) != 1:
            raise CoverageError("chart series changes expected sample count")
        count = expected.pop()
        if count != len(rows) or [row["sample_index"] for row in rows] != list(range(count)):
            raise CoverageError(f"{scene_id}/{episode_id} does not represent every expected sample")
        if [row["event_time"] for row in rows] != sorted(row["event_time"] for row in rows):
            raise ManifestError("chart sample order does not follow event time")

    gestures = {row["gesture_id"]: row for row in _rows(tables["operator_gestures"])}
    for row in gestures.values():
        decision = decisions.get(row["decision_id"])
        scene = scenes.get(row["scene_id"])
        if decision is None or scene is None or row["candidate_id"] not in candidates:
            raise ManifestError("operator gesture lacks witnessed join closure")
        if row["scene_view_digest"] != scene["view_digest"]:
            raise ManifestError("gesture view digest differs from its witnessed scene")
        if not row["issued_at"] <= row["received_at"] <= row["available_at"]:
            raise TemporalLeakageError("operator gesture clocks are not ordered")
        _digest(row["command_payload_digest"], "gesture command_payload_digest")
    for decision in decisions.values():
        selection = decision["selection_gesture_id"]
        if selection is not None and selection not in gestures:
            raise ManifestError("decision selection gesture is absent")
        if selection is not None:
            gesture = gestures[selection]
            if (
                gesture["candidate_id"] != decision["selected_candidate_id"]
                or gesture["decision_id"] != decision["decision_id"]
                or gesture["available_at"] > decision["decision_available_at"]
            ):
                raise TemporalLeakageError("selection gesture is not witnessed at its decision cut")

    for row in _rows(tables["operator_interviews"]):
        if row["decision_id"] not in decisions or row["scene_id"] not in scenes:
            raise ManifestError("operator interview lacks scene/decision closure")
        if row["elicited_at"] > row["available_at"]:
            raise TemporalLeakageError("interview became available before elicitation")
        _digest(row["transcript_blob_id"], "interview transcript_blob_id")

    allowed_risks = {"profit_target", "drawdown_stop", "liquidity_exit"}
    for row in _rows(tables["outcomes"]):
        decision = decisions.get(row["decision_id"])
        if decision is None or decision["selected_candidate_id"] != row["candidate_id"]:
            raise ManifestError("outcome is not keyed to the selected decision candidate")
        if row["is_censored"]:
            if row["event_kind"] is not None or row["event_time"] is not None:
                raise ManifestError("right-censored outcome cannot manufacture a no-event label")
            if row["censoring_reason"] is None:
                raise ManifestError("right-censored outcome requires a reason")
            if (
                not decision["decision_available_at"]
                <= row["outcome_known_at"]
                <= row["horizon_end"]
            ):
                raise TemporalLeakageError("censoring time escapes the registered risk horizon")
            gap_prefix = "coverage_gap:"
            if row["censoring_reason"].startswith(gap_prefix):
                gap_id = row["censoring_reason"].removeprefix(gap_prefix)
                if gap_id not in gaps:
                    raise CoverageError("outcome censoring cites an unknown coverage gap")
        else:
            if row["event_kind"] not in allowed_risks or row["event_time"] is None:
                raise ManifestError("observed outcome must retain its competing-risk event kind")
            if not (
                decision["decision_available_at"] <= row["event_time"] <= row["horizon_end"]
                and row["event_time"] <= row["outcome_known_at"]
            ):
                raise TemporalLeakageError("outcome clocks do not support the label horizon")

    if "scene" in manifest:
        binding = manifest["scene"]
        scene = scenes.get(binding["scene_id"])
        if (
            scene is None
            or scene["scene_mode"] != binding["mode"]
            or scene["view_digest"] != binding["view_digest"]
        ):
            raise ManifestError("top-level scene binding differs from exported scene DTO identity")


def validate_snapshot(snapshot_root: str | Path) -> ValidatedSnapshot:
    root = Path(snapshot_root).resolve()
    manifest_path = root / "manifest.json"
    if not root.is_dir() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise ManifestError(f"snapshot directory or manifest is missing: {root}")
    if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ManifestError("manifest.json exceeds the bounded v1 size")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_text = manifest_bytes.decode("utf-8")
        manifest = _require_dict(
            json.loads(
                manifest_text,
                object_pairs_hook=_reject_duplicate_object_keys,
                parse_constant=_reject_nonfinite_json,
            ),
            "snapshot manifest",
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError("manifest.json is not valid UTF-8 JSON") from error

    table_manifests = _validate_manifest_shape(manifest)
    _validate_snapshot_id(manifest)
    tables: dict[str, pa.Table] = {}
    for name, contract in TABLE_CONTRACTS.items():
        table_manifest = table_manifests[name]
        table_path = _safe_table_path(root, table_manifest["path"])
        if table_manifest["physical_digest"] != qualified_sha256_file(table_path):
            raise HashMismatchError(f"physical hash mismatch for {table_path.name}")
        if table_manifest["byte_length"] != table_path.stat().st_size:
            raise HashMismatchError(f"byte length mismatch for {table_path.name}")
        table = pq.read_table(table_path)
        _validate_schema(table, table_manifest, contract)
        if table.num_rows != table_manifest["row_count"]:
            raise ManifestError(f"row_count mismatch for {name}")
        _validate_keys(table, name, contract.primary_key)
        if table_manifest["logical_digest"] != logical_table_sha256(table, contract.primary_key):
            raise HashMismatchError(f"logical table hash mismatch for {name}")
        _validate_bounds_and_coverage(table, table_manifest, contract)
        for field in contract.schema:
            if not field.nullable and pc.any(pc.is_null(table[field.name])).as_py():
                raise SchemaMismatchError(f"non-null field contains null: {name}.{field.name}")
        tables[name] = table
    _validate_semantics(tables, manifest)

    return ValidatedSnapshot(
        root=root,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_digest=qualified_sha256_bytes(manifest_bytes),
        tables=tables,
    )


def make_snapshot_manifest(
    table_paths: dict[str, Path],
    tables: dict[str, pa.Table],
    *,
    created_at: datetime,
    producer: dict[str, Any],
    catalog: dict[str, Any],
    maximum_decision_available_at: datetime,
    scene: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the exact v1 fixture manifest; production exporters must independently encode it."""

    entries: list[dict[str, Any]] = []
    for name, contract in TABLE_CONTRACTS.items():
        table = tables[name]
        path = table_paths[name]
        if not table.schema.equals(contract.schema, check_metadata=True):
            raise SchemaMismatchError(f"fixture writer received the wrong schema for {name}")
        values = []
        if contract.event_time_field is not None:
            values = [
                value
                for value in table.column(contract.event_time_field).to_pylist()
                if value is not None
            ]
        event_bounds = (
            {"lower_inclusive": iso_utc(min(values)), "upper_inclusive": iso_utc(max(values))}
            if values
            else None
        )
        commits = table.column("available_commit_seq").to_pylist()
        catalog_start = catalog["from_commit_seq"]
        catalog_through = catalog["through_commit_seq"]
        entries.append(
            {
                "export_manifest_id": f"export-manifest:{name}:fixture-v1",
                "name": name,
                "path": path.name,
                "schema_id": contract.schema_id,
                "schema": schema_descriptor(table.schema),
                "schema_digest": schema_sha256(table.schema),
                "physical_digest": qualified_sha256_file(path),
                "logical_digest": logical_table_sha256(table, contract.primary_key),
                "byte_length": path.stat().st_size,
                "row_count": table.num_rows,
                "primary_key": list(contract.primary_key),
                "commit_bounds": {
                    "from_commit_seq": str(min(commits)) if commits else catalog_start,
                    "through_commit_seq": str(max(commits)) if commits else catalog_through,
                },
                "event_bounds": event_bounds,
                "chain_bounds": None,
                "coverage": _coverage_from_table(table),
            }
        )
    preimage: dict[str, Any] = {
        "manifest_version": SNAPSHOT_MANIFEST_VERSION,
        "created_at": iso_utc(created_at),
        "producer": producer,
        "catalog": catalog,
        "knowledge_mode": "as_known",
        "maximum_decision_available_at": iso_utc(maximum_decision_available_at),
        "tables": entries,
    }
    if scene is not None:
        preimage["scene"] = scene
    return {**preimage, "snapshot_id": qualified_sha256_bytes(canonical_json_bytes(preimage))}
