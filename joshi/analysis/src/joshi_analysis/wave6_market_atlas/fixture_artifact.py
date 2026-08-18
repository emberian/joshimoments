"""Exact caller-fed market-atlas fixture artifact shared with the Rust registry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa

from ..canonical import canonical_json_bytes, iso_utc, qualified_sha256_bytes
from .atlas import build_market_atlas
from .contracts import (
    ATLAS_CLAIM_SCOPE,
    ATLAS_SNAPSHOT_SCHEMA_ID,
    CALLER_ATTENTION_SCHEMA,
    CANONICAL_VENUE_STATE_SCHEMA,
    LIQUIDITY_TOPOLOGY_SCHEMA,
    MINT_LIFECYCLE_SCHEMA,
    PORTFOLIO_WATCH_SCHEMA,
    SEMANTIC_CEILING,
    WALLET_CLUSTER_FLOW_SCHEMA,
    AtlasCut,
    MarketAtlasInputs,
)

FIXTURE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _common(record_id: str, component_id: str, component_version_id: str) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "source_id": "source:fixture",
        "source_version_id": "source:v1",
        "native_event_id": f"event:{record_id}",
        "subject_id": "mint:one",
        "component_id": component_id,
        "component_version_id": component_version_id,
        "valid_lower": FIXTURE_TIME,
        "valid_upper": FIXTURE_TIME + timedelta(hours=1),
        "available_at": FIXTURE_TIME,
        "retracted_at": None,
        "available_commit_seq": 4,
        "coverage_status": "observed",
        "coverage_window_id": "coverage:healthy",
        "coverage_gap_id": None,
    }


def market_atlas_fixture_inputs() -> MarketAtlasInputs:
    """Return the exact six-stratum fixture input without store or market authority."""

    lifecycle = _common("life:1", "mint:one", "life:v1") | {
        "mint_id": "mint:one",
        "lifecycle_version_id": "life:v1",
        "lifecycle_state": "bonding_curve",
        "canonical_venue_id": "venue:curve",
        "lifecycle_transition_kind": "launch",
    }
    venue = _common("venue:original", "venue:curve", "venue:v1") | {
        "venue_id": "venue:curve",
        "venue_profile_id": "profile:curve-v1",
        "venue_state_version_id": "venue:v1",
        "venue_state_kind": "reserve_state",
        "base_asset_id": "mint:one",
        "quote_asset_id": "asset:sol",
        "price_carrier_kind": "quote_atoms_per_base_atom",
        "price_numerator_atoms": 10,
        "price_denominator_atoms": 2,
        "price_numerator_unit": "quote_asset_atoms",
        "price_denominator_unit": "base_asset_atoms",
    }
    liquidity = _common("topology:1", "bin:12", "topology:v1") | {
        "venue_id": "venue:curve",
        "topology_epoch": "topology:curve",
        "topology_version_id": "topology:v1",
        "topology_element_id": "bin:12",
        "topology_element_kind": "reserve",
        "liquidity_measure_kind": "base_reserve",
        "liquidity_atoms": 500,
        "liquidity_unit": "base_asset_atoms",
    }
    wallet = _common("flow:1", "wallet:alice", "wallet:v1") | {
        "wallet_id": "wallet:alice",
        "wallet_identity_version_id": "wallet:v1",
        "cluster_id": "cluster:one",
        "cluster_version_id": "cluster:v1",
        "flow_direction": "buy",
        "signed_flow_atoms": 13,
        "flow_unit": "base_asset_atoms",
    }
    attention = _common("attention:1", "caller:one", "caller:v1") | {
        "caller_id": "caller:one",
        "caller_identity_version_id": "caller:v1",
        "attention_stage": "rendered",
        "attention_count": 2,
        "attention_unit": "events",
        "surface_version_id": "surface:v1",
    }
    portfolio = _common("watch:1", "episode:one", "watch:v1") | {
        "episode_id": "episode:one",
        "inventory_epoch_id": None,
        "portfolio_watch_version_id": "watch:v1",
        "portfolio_state": "flat",
        "watch_state": "watching_flat",
        "base_asset_atoms": 0,
        "base_asset_unit": "base_asset_atoms",
    }
    return MarketAtlasInputs(
        mint_lifecycle=pa.Table.from_pylist([lifecycle], schema=MINT_LIFECYCLE_SCHEMA),
        canonical_venue_state=pa.Table.from_pylist(
            [venue], schema=CANONICAL_VENUE_STATE_SCHEMA
        ),
        liquidity_topology=pa.Table.from_pylist([liquidity], schema=LIQUIDITY_TOPOLOGY_SCHEMA),
        wallet_cluster_flow=pa.Table.from_pylist([wallet], schema=WALLET_CLUSTER_FLOW_SCHEMA),
        caller_attention=pa.Table.from_pylist([attention], schema=CALLER_ATTENTION_SCHEMA),
        portfolio_watch=pa.Table.from_pylist([portfolio], schema=PORTFOLIO_WATCH_SCHEMA),
    )


def _canonical_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            iso_utc(value)
            if isinstance(value, datetime)
            else str(value)
            if key == "as_of_commit_seq"
            else value
        )
        for key, value in row.items()
    }


def market_atlas_fixture_document() -> dict[str, Any]:
    """Build the exact snapshot artifact with a self-digest and hard fixture-only ceiling."""

    cut = AtlasCut(
        "cut:fixture-one",
        FIXTURE_TIME + timedelta(minutes=10),
        FIXTURE_TIME + timedelta(minutes=20),
        4,
    )
    snapshot = build_market_atlas(market_atlas_fixture_inputs(), [cut]).snapshots
    rows = [_canonical_row(row) for row in snapshot.to_pylist()]
    if len(rows) != 6:
        raise AssertionError("market-atlas fixture must retain all six strata")
    snapshot_ids = {row["atlas_snapshot_id"] for row in rows}
    snapshot_digests = {row["atlas_snapshot_digest"] for row in rows}
    input_ids = {row["input_snapshot_id"] for row in rows}
    input_digests = {row["input_logical_digest"] for row in rows}
    identities = (snapshot_ids, snapshot_digests, input_ids, input_digests)
    if any(len(values) != 1 for values in identities):
        raise AssertionError("market-atlas fixture rows do not share one exact cut")
    material = {
        "as_of_commit_seq": "4",
        "atlas_snapshot_digest": snapshot_digests.pop(),
        "atlas_snapshot_id": snapshot_ids.pop(),
        "authority": SEMANTIC_CEILING,
        "claim_scope": ATLAS_CLAIM_SCOPE,
        "cut_id": cut.cut_id,
        "input_logical_digest": input_digests.pop(),
        "input_snapshot_id": input_ids.pop(),
        "knowledge_cutoff": iso_utc(cut.knowledge_cutoff),
        "row_count": "6",
        "rows": rows,
        "schema_id": ATLAS_SNAPSHOT_SCHEMA_ID,
        "state_time": iso_utc(cut.state_time),
    }
    return {
        "artifact_digest": qualified_sha256_bytes(canonical_json_bytes(material)),
        **material,
    }


def market_atlas_fixture_bytes() -> bytes:
    """Return canonical compact JSON with the repository-wide one trailing newline."""

    return canonical_json_bytes(market_atlas_fixture_document(), newline=True)
