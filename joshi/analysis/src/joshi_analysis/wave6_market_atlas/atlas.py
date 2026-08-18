"""Pure, point-in-time reducer for the deliberately stratified market atlas."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from ..canonical import canonical_json_bytes, iso_utc, logical_table_sha256, qualified_sha256_bytes
from ..errors import ManifestError, TemporalLeakageError
from .contracts import (
    ATLAS_CLAIM_SCOPE,
    ATLAS_SNAPSHOT_SCHEMA,
    ATLAS_TRAJECTORY_SCHEMA,
    CALLER_ATTENTION_SCHEMA,
    CANONICAL_VENUE_STATE_SCHEMA,
    COMPONENT_KINDS,
    COVERAGE_STATUSES,
    LIQUIDITY_TOPOLOGY_SCHEMA,
    MINT_LIFECYCLE_SCHEMA,
    PORTFOLIO_WATCH_SCHEMA,
    SEMANTIC_CEILING,
    WALLET_CLUSTER_FLOW_SCHEMA,
    AtlasCut,
    MarketAtlasInputs,
)

_SOURCES: tuple[tuple[str, str, pa.Schema], ...] = (
    ("mint_lifecycle", "mint_lifecycle", MINT_LIFECYCLE_SCHEMA),
    ("canonical_venue_state", "canonical_venue_state", CANONICAL_VENUE_STATE_SCHEMA),
    ("liquidity_topology", "liquidity_topology", LIQUIDITY_TOPOLOGY_SCHEMA),
    ("wallet_cluster_flow", "wallet_cluster_flow", WALLET_CLUSTER_FLOW_SCHEMA),
    ("caller_attention", "caller_attention", CALLER_ATTENTION_SCHEMA),
    ("portfolio_watch", "portfolio_watch", PORTFOLIO_WATCH_SCHEMA),
)
_COMMON = {
    "record_id",
    "source_id",
    "source_version_id",
    "native_event_id",
    "subject_id",
    "component_id",
    "component_version_id",
    "valid_lower",
    "valid_upper",
    "available_at",
    "retracted_at",
    "available_commit_seq",
    "coverage_status",
    "coverage_window_id",
    "coverage_gap_id",
}
_OBSERVED_FIELDS = {
    "mint_lifecycle": (
        "mint_id",
        "lifecycle_version_id",
        "lifecycle_state",
        "lifecycle_transition_kind",
    ),
    "canonical_venue_state": (
        "venue_id",
        "venue_state_version_id",
        "venue_state_kind",
        "base_asset_id",
        "quote_asset_id",
    ),
    "liquidity_topology": (
        "topology_epoch",
        "topology_version_id",
        "topology_element_id",
        "topology_element_kind",
    ),
    "wallet_cluster_flow": (
        "wallet_id",
        "wallet_identity_version_id",
        "flow_direction",
        "signed_flow_atoms",
        "flow_unit",
    ),
    "caller_attention": (
        "caller_id",
        "caller_identity_version_id",
        "attention_stage",
        "attention_count",
        "attention_unit",
    ),
    "portfolio_watch": (
        "episode_id",
        "portfolio_watch_version_id",
        "portfolio_state",
        "watch_state",
    ),
}
_NATIVE_COMPONENT_FIELDS = {
    "mint_lifecycle": ("mint_id", "lifecycle_version_id"),
    "canonical_venue_state": ("venue_id", "venue_state_version_id"),
    "liquidity_topology": ("topology_element_id", "topology_version_id"),
    "wallet_cluster_flow": ("wallet_id", "wallet_identity_version_id"),
    "caller_attention": ("caller_id", "caller_identity_version_id"),
    "portfolio_watch": ("episode_id", "portfolio_watch_version_id"),
}


@dataclass(frozen=True)
class MarketAtlas:
    """Materialized snapshots plus their explicit, non-interpolated trajectories."""

    snapshots: pa.Table
    trajectories: pa.Table


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _digest(material: Any) -> str:
    return qualified_sha256_bytes(canonical_json_bytes(_canonical(material)))


def _stable_id(prefix: str, material: Any) -> str:
    return f"{prefix}:{_digest(material).removeprefix('sha256:')}"


def _require_string(row: dict[str, Any], field: str, kind: str) -> None:
    if not isinstance(row[field], str) or not row[field]:
        raise ManifestError(f"{kind} field {field} must be a nonempty string")


def _require_aware(value: Any, context: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ManifestError(f"{context} must be an aware UTC timestamp")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ManifestError(f"{context} must use UTC")
    return value


def _validate_row(kind: str, row: dict[str, Any]) -> None:
    for field in (
        "record_id",
        "source_id",
        "source_version_id",
        "native_event_id",
        "subject_id",
        "component_id",
        "component_version_id",
    ):
        _require_string(row, field, kind)
    _validate_validity_index(kind, row)
    _require_aware(row["available_at"], f"{kind}.available_at")
    retracted = row["retracted_at"]
    if retracted is not None:
        _require_aware(retracted, f"{kind}.retracted_at")
    if (
        not isinstance(row["available_commit_seq"], int)
        or isinstance(row["available_commit_seq"], bool)
        or row["available_commit_seq"] < 0
    ):
        raise ManifestError(f"{kind}.available_commit_seq must be a nonnegative int64")
    status = row["coverage_status"]
    if status not in COVERAGE_STATUSES:
        raise ManifestError(f"{kind} has unsupported coverage status")
    window, gap = row["coverage_window_id"], row["coverage_gap_id"]
    if status == "observed":
        if not isinstance(window, str) or not window:
            raise ManifestError(f"{kind} observed row requires coverage_window_id")
        if gap is not None:
            raise ManifestError(f"{kind} observed row cannot carry coverage_gap_id")
        for field in _OBSERVED_FIELDS[kind]:
            if row[field] is None or row[field] == "":
                raise ManifestError(f"{kind} observed row requires {field}")
        _validate_native_component_binding(kind, row)
    elif status in {"gap", "unknown"}:
        if not isinstance(gap, str) or not gap:
            raise ManifestError(f"{kind} {status} row requires coverage_gap_id")
    elif gap is not None:
        raise ManifestError(f"{kind} not_applicable row cannot carry coverage_gap_id")
    if kind == "canonical_venue_state":
        _validate_price(row)
        if status == "observed" and row["base_asset_id"] != row["subject_id"]:
            raise ManifestError("canonical venue base asset must bind to the atlas subject")
    elif kind == "liquidity_topology" and status == "observed":
        if row["liquidity_atoms"] is not None:
            _require_atom_unit(row["liquidity_unit"], "liquidity")
    elif kind == "wallet_cluster_flow" and status == "observed":
        _require_atom_unit(row["flow_unit"], "flow")
        if row["signed_flow_atoms"] is None:
            raise ManifestError("wallet_cluster_flow observed row requires signed flow atoms")
        if row["cluster_id"] is not None and row["cluster_version_id"] is None:
            raise ManifestError("wallet cluster identity requires its exact version")
    elif kind == "caller_attention" and status == "observed" and row["attention_unit"] != "events":
        raise ManifestError("caller attention count must use events")
    elif kind == "portfolio_watch" and status == "observed" and row["base_asset_atoms"] is not None:
        _require_atom_unit(row["base_asset_unit"], "portfolio base asset")


def _validate_validity_index(kind: str, row: dict[str, Any]) -> tuple[datetime, datetime]:
    """Validate only the semantic clock fields needed after a row is known by the cut."""

    lower = _require_aware(row["valid_lower"], f"{kind}.valid_lower")
    upper = _require_aware(row["valid_upper"], f"{kind}.valid_upper")
    if not lower < upper:
        raise ManifestError(f"{kind} validity interval must be nonempty and half-open")
    return lower, upper


def _require_atom_unit(value: Any, context: str) -> None:
    if value != "base_asset_atoms":
        raise ManifestError(f"{context} must use base_asset_atoms; mixed units are not comparable")


def _validate_native_component_binding(kind: str, row: dict[str, Any]) -> None:
    native_id_field, native_version_field = _NATIVE_COMPONENT_FIELDS[kind]
    if row["component_id"] != row[native_id_field]:
        raise ManifestError(f"{kind} component identity diverges from its native {native_id_field}")
    if row["component_version_id"] != row[native_version_field]:
        raise ManifestError(
            f"{kind} component version diverges from its native {native_version_field}"
        )


def _validate_price(row: dict[str, Any]) -> None:
    price_fields = (
        "price_carrier_kind",
        "price_numerator_atoms",
        "price_denominator_atoms",
        "price_numerator_unit",
        "price_denominator_unit",
    )
    present = [row[field] is not None for field in price_fields]
    if any(present) and not all(present):
        raise ManifestError("canonical venue price requires a complete typed price carrier")
    if not any(present):
        return
    if row["price_carrier_kind"] != "quote_atoms_per_base_atom":
        raise ManifestError("canonical venue price carrier must be quote_atoms_per_base_atom")
    if (
        row["price_numerator_unit"] != "quote_asset_atoms"
        or row["price_denominator_unit"] != "base_asset_atoms"
    ):
        raise ManifestError("canonical venue price uses mixed or unsupported price units")
    denominator = row["price_denominator_atoms"]
    numerator = row["price_numerator_atoms"]
    if (
        isinstance(denominator, bool)
        or isinstance(numerator, bool)
        or denominator <= 0
        or numerator < 0
    ):
        raise ManifestError(
            "canonical venue price atoms require nonnegative numerator and positive denominator"
        )


def _read_input_rows(inputs: MarketAtlasInputs) -> dict[str, list[dict[str, Any]]]:
    rows_by_kind: dict[str, list[dict[str, Any]]] = {}
    for attribute, kind, schema in _SOURCES:
        table = getattr(inputs, attribute)
        if not isinstance(table, pa.Table) or not table.schema.equals(schema, check_metadata=True):
            raise ManifestError(f"{kind} must use its exact Arrow schema without coercion")
        rows_by_kind[kind] = table.to_pylist()
    return rows_by_kind


def _validate_selected_rows(selected: dict[str, list[dict[str, Any]]]) -> None:
    record_ids: set[str] = set()
    semantic_ids: set[tuple[str, str, str, str, datetime, datetime]] = set()
    source_semantics: set[tuple[str, str, str, str]] = set()
    for kind, rows in selected.items():
        for row in rows:
            _validate_row(kind, row)
            if row["record_id"] in record_ids:
                raise ManifestError("duplicate occurrence identity across market-atlas inputs")
            record_ids.add(row["record_id"])
            semantic = (
                kind,
                row["subject_id"],
                row["component_id"],
                row["component_version_id"],
                row["valid_lower"],
                row["valid_upper"],
            )
            if semantic in semantic_ids:
                raise ManifestError("duplicate semantic component identity")
            semantic_ids.add(semantic)
            source_semantic = (
                kind,
                row["source_id"],
                row["native_event_id"],
                row["source_version_id"],
            )
            if source_semantic in source_semantics:
                raise ManifestError("duplicate native event/source-version semantics")
            source_semantics.add(source_semantic)


def _validate_cuts(cuts: tuple[AtlasCut, ...]) -> None:
    if not cuts:
        raise ManifestError("market atlas requires at least one point-in-time cut")
    ids: set[str] = set()
    for cut in cuts:
        if not isinstance(cut.cut_id, str) or not cut.cut_id or cut.cut_id in ids:
            raise ManifestError("atlas cuts require unique nonempty identities")
        ids.add(cut.cut_id)
        state_time = _require_aware(cut.state_time, "cut state_time")
        knowledge_cutoff = _require_aware(cut.knowledge_cutoff, "cut knowledge_cutoff")
        if state_time > knowledge_cutoff:
            raise TemporalLeakageError("state time cannot be after its knowledge cutoff")
        if (
            not isinstance(cut.as_of_commit_seq, int)
            or isinstance(cut.as_of_commit_seq, bool)
            or cut.as_of_commit_seq < 0
        ):
            raise ManifestError("cut as_of_commit_seq must be a nonnegative integer")


def _known_by_cut(row: dict[str, Any], cut: AtlasCut) -> bool:
    """Use only raw availability/commit metadata before semantic payload validation."""

    return (
        row["available_at"] <= cut.knowledge_cutoff
        and row["available_commit_seq"] <= cut.as_of_commit_seq
        and (row["retracted_at"] is None or row["retracted_at"] > cut.knowledge_cutoff)
    )


def _select_at_cut(
    rows_by_kind: dict[str, list[dict[str, Any]]], cut: AtlasCut
) -> dict[str, list[dict[str, Any]]]:
    """Gate on nonnullable knowledge metadata before touching nullable semantic fields."""

    selected: dict[str, list[dict[str, Any]]] = {}
    for kind, rows in rows_by_kind.items():
        at_cut: list[dict[str, Any]] = []
        for row in rows:
            if not _known_by_cut(row, cut):
                continue
            lower, upper = _validate_validity_index(kind, row)
            if lower <= cut.state_time < upper:
                at_cut.append(row)
        selected[kind] = at_cut
    return selected


def _cut_input_identity(selected: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    source_digests: dict[str, str] = {}
    for _attribute, kind, schema in _SOURCES:
        table = pa.Table.from_pylist(selected[kind], schema=schema)
        source_digests[kind] = logical_table_sha256(table, ["record_id"])
    logical_digest = _digest(source_digests)
    return (
        _stable_id(
            "market-atlas-input",
            {
                "contract": "joshi.analysis.wave6-market-atlas-input/v1",
                "logical_digest": logical_digest,
            },
        ),
        logical_digest,
    )


def _native_payload_digest(kind: str, row: dict[str, Any]) -> str:
    return _digest(
        {
            "component_kind": kind,
            "payload": {key: value for key, value in row.items() if key not in _COMMON},
        }
    )


def build_market_atlas(
    inputs: MarketAtlasInputs, cuts: tuple[AtlasCut, ...] | list[AtlasCut]
) -> MarketAtlas:
    """Build as-known snapshots without interpolation, inference, or cross-stratum scalarization."""

    cut_tuple = tuple(cuts)
    _validate_cuts(cut_tuple)
    rows_by_kind = _read_input_rows(inputs)
    snapshot_rows: list[dict[str, Any]] = []
    for cut in cut_tuple:
        selected = _select_at_cut(rows_by_kind, cut)
        _validate_selected_rows(selected)
        for kind, rows in selected.items():
            selected_components: set[tuple[str, str]] = set()
            for row in rows:
                key = (row["subject_id"], row["component_id"])
                if key in selected_components:
                    raise ManifestError(
                        f"point-in-time cut selects conflicting {kind} component versions"
                    )
                selected_components.add(key)
        input_snapshot_id, logical_digest = _cut_input_identity(selected)
        snapshot_material = {
            "input_snapshot_id": input_snapshot_id,
            "cut_id": cut.cut_id,
            "state_time": cut.state_time,
            "knowledge_cutoff": cut.knowledge_cutoff,
            "as_of_commit_seq": cut.as_of_commit_seq,
        }
        snapshot_digest = _digest(snapshot_material)
        snapshot_id = _stable_id("market-atlas-snapshot", snapshot_material)
        for kind in COMPONENT_KINDS:
            for row in selected[kind]:
                snapshot_rows.append(
                    {
                        "atlas_snapshot_id": snapshot_id,
                        "atlas_snapshot_digest": snapshot_digest,
                        "input_snapshot_id": input_snapshot_id,
                        "input_logical_digest": logical_digest,
                        "cut_id": cut.cut_id,
                        "state_time": cut.state_time,
                        "knowledge_cutoff": cut.knowledge_cutoff,
                        "as_of_commit_seq": cut.as_of_commit_seq,
                        "semantic_ceiling": SEMANTIC_CEILING,
                        "subject_id": row["subject_id"],
                        "component_kind": kind,
                        "record_id": row["record_id"],
                        "source_id": row["source_id"],
                        "source_version_id": row["source_version_id"],
                        "native_event_id": row["native_event_id"],
                        "component_id": row["component_id"],
                        "component_version_id": row["component_version_id"],
                        "valid_lower": row["valid_lower"],
                        "valid_upper": row["valid_upper"],
                        "available_at": row["available_at"],
                        "retracted_at": row["retracted_at"],
                        "coverage_status": row["coverage_status"],
                        "coverage_window_id": row["coverage_window_id"],
                        "coverage_gap_id": row["coverage_gap_id"],
                        "native_payload_digest": _native_payload_digest(kind, row),
                        "claim_scope": ATLAS_CLAIM_SCOPE,
                    }
                )
    snapshot_rows.sort(
        key=lambda row: (
            row["state_time"],
            row["knowledge_cutoff"],
            row["cut_id"],
            row["subject_id"],
            row["component_kind"],
            row["component_id"],
            row["record_id"],
        )
    )
    trajectories = _trajectory_rows(snapshot_rows)
    return MarketAtlas(
        snapshots=pa.Table.from_pylist(snapshot_rows, schema=ATLAS_SNAPSHOT_SCHEMA),
        trajectories=pa.Table.from_pylist(trajectories, schema=ATLAS_TRAJECTORY_SCHEMA),
    )


def _trajectory_rows(snapshot_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        groups[(row["subject_id"], row["component_kind"], row["component_id"])].append(row)
    rows: list[dict[str, Any]] = []
    for (subject_id, component_kind, component_id), members in groups.items():
        members.sort(
            key=lambda row: (
                row["state_time"],
                row["knowledge_cutoff"],
                row["cut_id"],
                row["record_id"],
            )
        )
        statuses = [member["coverage_status"] for member in members]
        status = (
            "observed_path"
            if all(item == "observed" for item in statuses)
            else "path_with_declared_nonobservation"
        )
        material = {
            "subject_id": subject_id,
            "component_kind": component_kind,
            "component_id": component_id,
            "cut_ids": [member["cut_id"] for member in members],
            "atlas_snapshot_ids": [member["atlas_snapshot_id"] for member in members],
            "record_ids": [member["record_id"] for member in members],
            "coverage_statuses": statuses,
            "coverage_gap_ids": [
                member["coverage_gap_id"]
                for member in members
                if member["coverage_gap_id"] is not None
            ],
        }
        digest = _digest(material)
        rows.append(
            {
                "trajectory_id": _stable_id("market-atlas-trajectory", material),
                "trajectory_digest": digest,
                "subject_id": subject_id,
                "component_kind": component_kind,
                "component_id": component_id,
                "semantic_ceiling": SEMANTIC_CEILING,
                "trajectory_status": status,
                "cut_ids": material["cut_ids"],
                "atlas_snapshot_ids": material["atlas_snapshot_ids"],
                "record_ids": material["record_ids"],
                "coverage_statuses": statuses,
                "coverage_gap_ids": material["coverage_gap_ids"],
                "claim_scope": ATLAS_CLAIM_SCOPE,
            }
        )
    rows.sort(key=lambda row: (row["subject_id"], row["component_kind"], row["component_id"]))
    return rows
