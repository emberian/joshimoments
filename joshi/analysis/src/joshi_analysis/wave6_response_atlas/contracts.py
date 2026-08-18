from __future__ import annotations

import pyarrow as pa

RESPONSE_COMPONENTS = (
    "same_wallet",
    "same_cluster_other_wallet",
    "external",
)
CONTEXT_LEVELS = ("wallet", "cluster", "caller_class")
COMPETING_EVENT_KINDS = (
    "liquidity_exhaustion",
    "migration",
    "venue_exit",
)

RESPONSE_COMPONENT_OBSERVATION_SCHEMA_ID = (
    "joshi.analysis.wave6-response-component-observation/v1"
)
RESPONSE_COMPONENT_OBSERVATION_SCHEMA = pa.schema(
    [
        pa.field("component_observation_id", pa.string(), nullable=False),
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("base_asset_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("lifecycle_state", pa.string(), nullable=False),
        pa.field("lifecycle_version_id", pa.string(), nullable=False),
        pa.field("lifecycle_valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("lifecycle_valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("lifecycle_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("lifecycle_retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("wallet_id", pa.string(), nullable=False),
        pa.field("wallet_identity_version_id", pa.string(), nullable=False),
        pa.field("cluster_id", pa.string(), nullable=False),
        pa.field("cluster_version_id", pa.string(), nullable=False),
        pa.field("caller_class", pa.string(), nullable=False),
        pa.field("caller_class_version_id", pa.string(), nullable=False),
        pa.field("caller_context_valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("caller_context_valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("caller_context_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("caller_context_retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("mark_direction", pa.string(), nullable=False),
        pa.field("mark_size_bucket", pa.string(), nullable=False),
        pa.field("mark_size_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_lower_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_upper_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_unit", pa.string(), nullable=False),
        pa.field("topology_epoch", pa.string(), nullable=False),
        pa.field("topology_version_id", pa.string(), nullable=False),
        pa.field("topology_valid_lower", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_valid_upper", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("topology_retracted_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("event_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("information_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("horizon_us", pa.int64(), nullable=False),
        pa.field("response_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("response_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("component_kind", pa.string(), nullable=False),
        pa.field("response_signed_flow_atoms", pa.int64(), nullable=True),
        pa.field("response_unit", pa.string(), nullable=False),
        pa.field("coverage_status", pa.string(), nullable=False),
        pa.field("coverage_window_id", pa.string(), nullable=False),
        pa.field("coverage_gap_id", pa.string(), nullable=True),
        pa.field("available_commit_seq", pa.int64(), nullable=False),
    ]
)

RISK_OUTCOME_SCHEMA_ID = "joshi.analysis.wave6-response-risk-outcome/v1"
RISK_OUTCOME_SCHEMA = pa.schema(
    [
        pa.field("risk_outcome_id", pa.string(), nullable=False),
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("horizon_us", pa.int64(), nullable=False),
        pa.field("risk_entry_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("risk_horizon_end", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("outcome_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("event_kind", pa.string(), nullable=True),
        pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("outcome_known_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("censoring_kind", pa.string(), nullable=False),
        pa.field("coverage_status", pa.string(), nullable=False),
        pa.field("coverage_window_id", pa.string(), nullable=False),
        pa.field("coverage_gap_id", pa.string(), nullable=True),
        pa.field("available_commit_seq", pa.int64(), nullable=False),
    ]
)

RESPONSE_SURFACE_SCHEMA_ID = "joshi.analysis.wave6-response-surface-cell/v1"
RESPONSE_SURFACE_SCHEMA = pa.schema(
    [
        pa.field("surface_cell_id", pa.string(), nullable=False),
        pa.field("surface_cell_digest", pa.string(), nullable=False),
        pa.field("estimator_id", pa.string(), nullable=False),
        pa.field("estimator_version", pa.string(), nullable=False),
        pa.field("estimator_configuration_digest", pa.string(), nullable=False),
        pa.field("input_snapshot_id", pa.string(), nullable=False),
        pa.field("input_logical_digest", pa.string(), nullable=False),
        pa.field("fit_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("maximum_input_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("as_of_commit_seq", pa.int64(), nullable=False),
        pa.field("base_asset_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("lifecycle_state", pa.string(), nullable=False),
        pa.field("lifecycle_version_id", pa.string(), nullable=False),
        pa.field("context_level", pa.string(), nullable=False),
        pa.field("context_id", pa.string(), nullable=False),
        pa.field("context_version_id", pa.string(), nullable=False),
        pa.field("mark_direction", pa.string(), nullable=False),
        pa.field("mark_size_bucket", pa.string(), nullable=False),
        pa.field("mark_size_lower_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_upper_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_unit", pa.string(), nullable=False),
        pa.field("topology_epoch", pa.string(), nullable=False),
        pa.field("topology_version_id", pa.string(), nullable=False),
        pa.field("horizon_us", pa.int64(), nullable=False),
        pa.field("component_kind", pa.string(), nullable=False),
        pa.field("response_estimate", pa.float64(), nullable=True),
        pa.field("response_unit", pa.string(), nullable=False),
        pa.field("support_anchor_count", pa.int64(), nullable=False),
        pa.field("complete_anchor_count", pa.int64(), nullable=False),
        pa.field("component_observed_count", pa.int64(), nullable=False),
        pa.field("component_gap_count", pa.int64(), nullable=False),
        pa.field("coverage_ratio_ppm", pa.int64(), nullable=False),
        pa.field("coverage_window_ids", pa.list_(pa.string()), nullable=False),
        pa.field("coverage_gap_ids", pa.list_(pa.string()), nullable=False),
        pa.field("decomposition_status", pa.string(), nullable=False),
        pa.field("claim_scope", pa.string(), nullable=False),
    ]
)

COMPETING_RISK_SURFACE_SCHEMA_ID = "joshi.analysis.wave6-competing-risk-surface-cell/v1"
COMPETING_RISK_SURFACE_SCHEMA = pa.schema(
    [
        pa.field("risk_cell_id", pa.string(), nullable=False),
        pa.field("risk_cell_digest", pa.string(), nullable=False),
        pa.field("estimator_id", pa.string(), nullable=False),
        pa.field("estimator_version", pa.string(), nullable=False),
        pa.field("estimator_configuration_digest", pa.string(), nullable=False),
        pa.field("input_snapshot_id", pa.string(), nullable=False),
        pa.field("input_logical_digest", pa.string(), nullable=False),
        pa.field("fit_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("maximum_input_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("as_of_commit_seq", pa.int64(), nullable=False),
        pa.field("base_asset_id", pa.string(), nullable=False),
        pa.field("venue_id", pa.string(), nullable=False),
        pa.field("lifecycle_state", pa.string(), nullable=False),
        pa.field("lifecycle_version_id", pa.string(), nullable=False),
        pa.field("context_level", pa.string(), nullable=False),
        pa.field("context_id", pa.string(), nullable=False),
        pa.field("context_version_id", pa.string(), nullable=False),
        pa.field("mark_direction", pa.string(), nullable=False),
        pa.field("mark_size_bucket", pa.string(), nullable=False),
        pa.field("mark_size_lower_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_upper_atoms", pa.int64(), nullable=False),
        pa.field("mark_size_unit", pa.string(), nullable=False),
        pa.field("topology_epoch", pa.string(), nullable=False),
        pa.field("topology_version_id", pa.string(), nullable=False),
        pa.field("horizon_us", pa.int64(), nullable=False),
        pa.field("event_kind", pa.string(), nullable=False),
        pa.field("risk_cohort_count", pa.int64(), nullable=False),
        pa.field("event_count", pa.int64(), nullable=False),
        pa.field("other_competing_event_count", pa.int64(), nullable=False),
        pa.field("right_censored_count", pa.int64(), nullable=False),
        pa.field("administrative_censored_count", pa.int64(), nullable=False),
        pa.field("source_gap_censored_count", pa.int64(), nullable=False),
        pa.field("observed_cause_fraction_ppm", pa.int64(), nullable=False),
        pa.field("coverage_ratio_ppm", pa.int64(), nullable=False),
        pa.field("coverage_window_ids", pa.list_(pa.string()), nullable=False),
        pa.field("coverage_gap_ids", pa.list_(pa.string()), nullable=False),
        pa.field("claim_scope", pa.string(), nullable=False),
    ]
)

ATLAS_CLAIM_SCOPE = (
    "descriptive_point_in_time_signed_flow_association_not_causal_or_strategy_claim"
)
RISK_CLAIM_SCOPE = (
    "descriptive_observed_competing_risk_fraction_not_causal_probability_or_strategy_claim"
)
