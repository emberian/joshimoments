"""Typed, deliberately non-scalar inputs and outputs for the Wave 6 market atlas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pyarrow as pa

COMPONENT_KINDS = (
    "mint_lifecycle",
    "canonical_venue_state",
    "liquidity_topology",
    "wallet_cluster_flow",
    "caller_attention",
    "portfolio_watch",
)
COVERAGE_STATUSES = ("observed", "gap", "unknown", "not_applicable")
SEMANTIC_CEILING = "caller_fed_unverified_semantic_fixture_only"


def _timed_fields() -> list[pa.Field]:
    return [
        # Validity and coverage are caller-fed semantic payload, not transport eligibility.
        pa.field("valid_lower", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("valid_upper", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("available_commit_seq", pa.int64(), nullable=False),
        pa.field("coverage_status", pa.string(), nullable=True),
        pa.field("coverage_window_id", pa.string(), nullable=True),
        pa.field("coverage_gap_id", pa.string(), nullable=True),
    ]


def _common_fields() -> list[pa.Field]:
    return [
        pa.field("record_id", pa.string(), nullable=True),
        pa.field("source_id", pa.string(), nullable=True),
        pa.field("source_version_id", pa.string(), nullable=True),
        pa.field("native_event_id", pa.string(), nullable=True),
        pa.field("subject_id", pa.string(), nullable=True),
        pa.field("component_id", pa.string(), nullable=True),
        pa.field("component_version_id", pa.string(), nullable=True),
        *_timed_fields(),
    ]


MINT_LIFECYCLE_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-mint-lifecycle/v1"
MINT_LIFECYCLE_SCHEMA = pa.schema(
    [
        *_common_fields(),
        pa.field("mint_id", pa.string(), nullable=True),
        pa.field("lifecycle_version_id", pa.string(), nullable=True),
        pa.field("lifecycle_state", pa.string(), nullable=True),
        pa.field("canonical_venue_id", pa.string(), nullable=True),
        pa.field("lifecycle_transition_kind", pa.string(), nullable=True),
    ]
)

CANONICAL_VENUE_STATE_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-canonical-venue-state/v1"
CANONICAL_VENUE_STATE_SCHEMA = pa.schema(
    [
        *_common_fields(),
        pa.field("venue_id", pa.string(), nullable=True),
        pa.field("venue_profile_id", pa.string(), nullable=True),
        pa.field("venue_state_version_id", pa.string(), nullable=True),
        pa.field("venue_state_kind", pa.string(), nullable=True),
        pa.field("base_asset_id", pa.string(), nullable=True),
        pa.field("quote_asset_id", pa.string(), nullable=True),
        pa.field("price_carrier_kind", pa.string(), nullable=True),
        pa.field("price_numerator_atoms", pa.int64(), nullable=True),
        pa.field("price_denominator_atoms", pa.int64(), nullable=True),
        pa.field("price_numerator_unit", pa.string(), nullable=True),
        pa.field("price_denominator_unit", pa.string(), nullable=True),
    ]
)

LIQUIDITY_TOPOLOGY_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-liquidity-topology/v1"
LIQUIDITY_TOPOLOGY_SCHEMA = pa.schema(
    [
        *_common_fields(),
        pa.field("venue_id", pa.string(), nullable=True),
        pa.field("topology_epoch", pa.string(), nullable=True),
        pa.field("topology_version_id", pa.string(), nullable=True),
        pa.field("topology_element_id", pa.string(), nullable=True),
        pa.field("topology_element_kind", pa.string(), nullable=True),
        pa.field("liquidity_measure_kind", pa.string(), nullable=True),
        pa.field("liquidity_atoms", pa.int64(), nullable=True),
        pa.field("liquidity_unit", pa.string(), nullable=True),
    ]
)

WALLET_CLUSTER_FLOW_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-wallet-cluster-flow/v1"
WALLET_CLUSTER_FLOW_SCHEMA = pa.schema(
    [
        *_common_fields(),
        pa.field("wallet_id", pa.string(), nullable=True),
        pa.field("wallet_identity_version_id", pa.string(), nullable=True),
        pa.field("cluster_id", pa.string(), nullable=True),
        pa.field("cluster_version_id", pa.string(), nullable=True),
        pa.field("flow_direction", pa.string(), nullable=True),
        pa.field("signed_flow_atoms", pa.int64(), nullable=True),
        pa.field("flow_unit", pa.string(), nullable=True),
    ]
)

CALLER_ATTENTION_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-caller-attention/v1"
CALLER_ATTENTION_SCHEMA = pa.schema(
    [
        *_common_fields(),
        pa.field("caller_id", pa.string(), nullable=True),
        pa.field("caller_identity_version_id", pa.string(), nullable=True),
        pa.field("attention_stage", pa.string(), nullable=True),
        pa.field("attention_count", pa.int64(), nullable=True),
        pa.field("attention_unit", pa.string(), nullable=True),
        pa.field("surface_version_id", pa.string(), nullable=True),
    ]
)

PORTFOLIO_WATCH_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-portfolio-watch/v1"
PORTFOLIO_WATCH_SCHEMA = pa.schema(
    [
        *_common_fields(),
        pa.field("episode_id", pa.string(), nullable=True),
        pa.field("inventory_epoch_id", pa.string(), nullable=True),
        pa.field("portfolio_watch_version_id", pa.string(), nullable=True),
        pa.field("portfolio_state", pa.string(), nullable=True),
        pa.field("watch_state", pa.string(), nullable=True),
        pa.field("base_asset_atoms", pa.int64(), nullable=True),
        pa.field("base_asset_unit", pa.string(), nullable=True),
    ]
)

ATLAS_SNAPSHOT_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-snapshot/v1"
ATLAS_SNAPSHOT_SCHEMA = pa.schema(
    [
        pa.field("atlas_snapshot_id", pa.string(), nullable=False),
        pa.field("atlas_snapshot_digest", pa.string(), nullable=False),
        pa.field("input_snapshot_id", pa.string(), nullable=False),
        pa.field("input_logical_digest", pa.string(), nullable=False),
        pa.field("cut_id", pa.string(), nullable=False),
        pa.field("state_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("knowledge_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("as_of_commit_seq", pa.int64(), nullable=False),
        pa.field("semantic_ceiling", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("component_kind", pa.string(), nullable=False),
        pa.field("record_id", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("source_version_id", pa.string(), nullable=False),
        pa.field("native_event_id", pa.string(), nullable=False),
        pa.field("component_id", pa.string(), nullable=False),
        pa.field("component_version_id", pa.string(), nullable=False),
        pa.field("valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("coverage_status", pa.string(), nullable=False),
        pa.field("coverage_window_id", pa.string(), nullable=True),
        pa.field("coverage_gap_id", pa.string(), nullable=True),
        pa.field("native_payload_digest", pa.string(), nullable=False),
        pa.field("claim_scope", pa.string(), nullable=False),
    ]
)

ATLAS_TRAJECTORY_SCHEMA_ID = "joshi.analysis.wave6-market-atlas-trajectory/v1"
ATLAS_TRAJECTORY_SCHEMA = pa.schema(
    [
        pa.field("trajectory_id", pa.string(), nullable=False),
        pa.field("trajectory_digest", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("component_kind", pa.string(), nullable=False),
        pa.field("component_id", pa.string(), nullable=False),
        pa.field("semantic_ceiling", pa.string(), nullable=False),
        pa.field("trajectory_status", pa.string(), nullable=False),
        pa.field("cut_ids", pa.list_(pa.string()), nullable=False),
        pa.field("atlas_snapshot_ids", pa.list_(pa.string()), nullable=False),
        pa.field("record_ids", pa.list_(pa.string()), nullable=False),
        pa.field("coverage_statuses", pa.list_(pa.string()), nullable=False),
        pa.field("coverage_gap_ids", pa.list_(pa.string()), nullable=False),
        pa.field("claim_scope", pa.string(), nullable=False),
    ]
)

ATLAS_CLAIM_SCOPE = (
    "descriptive_point_in_time_typed_market_atlas_not_scalar_pressure_causal_or_strategy_claim"
)


@dataclass(frozen=True)
class AtlasCut:
    """One state-time and knowledge-time query; both clocks are mandatory."""

    cut_id: str
    state_time: datetime
    knowledge_cutoff: datetime
    as_of_commit_seq: int


@dataclass(frozen=True)
class MarketAtlasInputs:
    mint_lifecycle: pa.Table
    canonical_venue_state: pa.Table
    liquidity_topology: pa.Table
    wallet_cluster_flow: pa.Table
    caller_attention: pa.Table
    portfolio_watch: pa.Table
