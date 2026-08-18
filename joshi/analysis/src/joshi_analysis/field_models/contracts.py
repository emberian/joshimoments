from __future__ import annotations

import pyarrow as pa

from ..contracts import DECIMAL_U64

GRAPH_EDGE_SCHEMA_ID = "joshi.analysis.dynamic-field-edge-input/v1"
GRAPH_EDGE_SCHEMA = pa.schema(
    [
        pa.field("edge_observation_id", pa.string(), nullable=False),
        pa.field("layer_kind", pa.string(), nullable=False),
        pa.field("topology_epoch", pa.string(), nullable=False),
        pa.field("topology_version_id", pa.string(), nullable=False),
        pa.field("edge_id", pa.string(), nullable=False),
        pa.field("source_node_id", pa.string(), nullable=False),
        pa.field("target_node_id", pa.string(), nullable=False),
        pa.field("flow_value", pa.int64(), nullable=True),
        pa.field("flow_unit", pa.string(), nullable=False),
        pa.field("carrier_kind", pa.string(), nullable=False),
        pa.field("carrier_id", pa.string(), nullable=False),
        pa.field("cycle_id", pa.string(), nullable=True),
        pa.field("cycle_orientation", pa.int8(), nullable=True),
        pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("information_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("coverage_status", pa.string(), nullable=False),
        pa.field("coverage_window_id", pa.string(), nullable=False),
        pa.field("coverage_gap_id", pa.string(), nullable=True),
        pa.field("available_commit_seq", pa.int64(), nullable=False),
    ]
)

VENUE_RESPONSE_SCHEMA_ID = "joshi.analysis.venue-reserve-response-input/v1"
VENUE_RESPONSE_SCHEMA = pa.schema(
    [
        pa.field("venue_response_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("candidate_id", pa.string(), nullable=False),
        pa.field("topology_epoch", pa.string(), nullable=False),
        pa.field("topology_version_id", pa.string(), nullable=False),
        pa.field("liquidity_model", pa.string(), nullable=False),
        pa.field("formula_version", pa.string(), nullable=False),
        pa.field("reserve_state_digest", pa.string(), nullable=False),
        pa.field("base_asset_id", pa.string(), nullable=False),
        pa.field("quote_asset_id", pa.string(), nullable=False),
        pa.field("baseline_base_atoms", DECIMAL_U64, nullable=False),
        pa.field("baseline_quote_atoms", DECIMAL_U64, nullable=False),
        pa.field("shock_base_atoms", DECIMAL_U64, nullable=False),
        pa.field("shock_quote_atoms", DECIMAL_U64, nullable=False),
        pa.field("recovery_base_atoms", DECIMAL_U64, nullable=False),
        pa.field("recovery_quote_atoms", DECIMAL_U64, nullable=False),
        pa.field("signed_flow_base_atoms", pa.int64(), nullable=False),
        pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("information_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("coverage_status", pa.string(), nullable=False),
        pa.field("coverage_window_id", pa.string(), nullable=False),
        pa.field("coverage_gap_id", pa.string(), nullable=True),
        pa.field("available_commit_seq", pa.int64(), nullable=False),
    ]
)

FIELD_OBSERVABLE_SCHEMA_ID = "joshi.analysis.dynamic-field-observable/v1"
FIELD_OBSERVABLE_SCHEMA = pa.schema(
    [
        pa.field("field_observable_occurrence_id", pa.string(), nullable=False),
        pa.field("field_observable_digest", pa.string(), nullable=False),
        pa.field("estimator_id", pa.string(), nullable=False),
        pa.field("estimator_version", pa.string(), nullable=False),
        pa.field("estimator_configuration_digest", pa.string(), nullable=False),
        pa.field("input_snapshot_id", pa.string(), nullable=False),
        pa.field("input_logical_digest", pa.string(), nullable=False),
        pa.field("fit_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("maximum_input_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("as_of_commit_seq", pa.int64(), nullable=False),
        pa.field("layer_kind", pa.string(), nullable=False),
        pa.field("carrier_kind", pa.string(), nullable=False),
        pa.field("carrier_id", pa.string(), nullable=False),
        pa.field("topology_epoch", pa.string(), nullable=False),
        pa.field("topology_version_id", pa.string(), nullable=False),
        pa.field("entity_kind", pa.string(), nullable=False),
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("candidate_id", pa.string(), nullable=True),
        pa.field("venue_id", pa.string(), nullable=True),
        pa.field("observable_kind", pa.string(), nullable=False),
        pa.field("value", pa.float64(), nullable=True),
        pa.field("value_unit", pa.string(), nullable=False),
        pa.field("uncertainty_lower", pa.float64(), nullable=True),
        pa.field("uncertainty_upper", pa.float64(), nullable=True),
        pa.field("uncertainty_method", pa.string(), nullable=False),
        pa.field("gap_sensitivity_lower", pa.float64(), nullable=True),
        pa.field("gap_sensitivity_upper", pa.float64(), nullable=True),
        pa.field("gap_sensitivity_method", pa.string(), nullable=False),
        pa.field("support_count", pa.int64(), nullable=False),
        pa.field("observed_count", pa.int64(), nullable=False),
        pa.field("gap_count", pa.int64(), nullable=False),
        pa.field("coverage_ratio_ppm", pa.int64(), nullable=False),
        pa.field("coverage_window_ids", pa.list_(pa.string()), nullable=False),
        pa.field("coverage_gap_ids", pa.list_(pa.string()), nullable=False),
        pa.field("topology_boundary_status", pa.string(), nullable=False),
        pa.field("claim_scope", pa.string(), nullable=False),
    ]
)

FIELD_CLAIM_SCOPE = "machine_descriptive_field_estimate_not_operator_perception_or_strategy_claim"
