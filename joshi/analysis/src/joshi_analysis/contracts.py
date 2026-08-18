from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

SNAPSHOT_MANIFEST_VERSION = "joshi.analysis.snapshot/v1"
SNAPSHOT_MANIFEST_VERSION_V2 = "joshi.analysis.snapshot/v2"
RUN_MANIFEST_VERSION = "joshi.analysis.run/v1"
DATASET_RUN_MANIFEST_VERSION = "joshi.analysis.dataset_run/v1"
ANALOG_RUN_MANIFEST_VERSION = "joshi.analysis.analog_run/v1"

DECIMAL_U64 = pa.decimal128(20, 0)


def _schema(*fields: pa.Field) -> pa.Schema:
    return pa.schema(list(fields))


SCENE_SCHEMA = _schema(
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("scene_mode", pa.string(), nullable=False),
    pa.field("view_contract", pa.string(), nullable=False),
    pa.field("view_contract_version", pa.string(), nullable=False),
    pa.field("view_digest", pa.string(), nullable=False),
    pa.field("source_mode", pa.string(), nullable=False),
    pa.field("rendered_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("decision_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("knowledge_commit_seq", pa.int64(), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

TERRITORY_SCHEMA = _schema(
    pa.field("territory_id", pa.string(), nullable=False),
    pa.field("territory_kind", pa.string(), nullable=False),
    pa.field("description", pa.string(), nullable=False),
    pa.field("first_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
    pa.field("source_assertion_id", pa.string(), nullable=False),
    pa.field("source_observation_id", pa.string(), nullable=False),
)

CANDIDATE_SCHEMA = _schema(
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("mint_asset_id", pa.string(), nullable=False),
    pa.field("territory_id", pa.string(), nullable=False),
    pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("first_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
    pa.field("source_assertion_id", pa.string(), nullable=False),
    pa.field("source_observation_id", pa.string(), nullable=False),
)

CANDIDATE_SOCIAL_ASSERTION_SCHEMA = _schema(
    pa.field("social_assertion_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("identity_kind", pa.string(), nullable=False),
    pa.field("identity_key", pa.string(), nullable=False),
    pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
    pa.field("source_assertion_id", pa.string(), nullable=False),
    pa.field("source_observation_id", pa.string(), nullable=False),
)

DECISION_SCHEMA = _schema(
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("choice_set_id", pa.string(), nullable=False),
    pa.field("selected_candidate_id", pa.string(), nullable=True),
    pa.field("episode_id", pa.string(), nullable=True),
    pa.field("operator_action", pa.string(), nullable=False),
    pa.field("selection_gesture_id", pa.string(), nullable=True),
    pa.field("decision_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

CHOICE_MEMBER_SCHEMA = _schema(
    pa.field("choice_set_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("set_kind", pa.string(), nullable=False),
    pa.field("source_rank", pa.int32(), nullable=True),
    pa.field("rendered_ordinal", pa.int32(), nullable=True),
    pa.field("in_viewport", pa.bool_(), nullable=False),
    pa.field("interacted", pa.bool_(), nullable=False),
    pa.field("evidence_assertion_id", pa.string(), nullable=True),
    pa.field("evidence_observation_id", pa.string(), nullable=True),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

EPISODE_SCHEMA = _schema(
    pa.field("episode_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("territory_id", pa.string(), nullable=False),
    pa.field("opened_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("closed_at", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("status", pa.string(), nullable=False),
    pa.field("reentry_of_episode_id", pa.string(), nullable=True),
    pa.field("operator_disposition", pa.string(), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

CHART_SAMPLE_SCHEMA_ID = "joshi.analysis.chart-sample/v1"
CHART_SAMPLE_SCHEMA = _schema(
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("scene_mode", pa.string(), nullable=False),
    pa.field("scene_view_digest", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("episode_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("territory_id", pa.string(), nullable=False),
    pa.field("base_asset_id", pa.string(), nullable=False),
    pa.field("quote_asset_id", pa.string(), nullable=False),
    pa.field("sample_index", pa.int32(), nullable=False),
    pa.field("expected_sample_count", pa.int32(), nullable=False),
    pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("decision_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("price_base_atoms", DECIMAL_U64, nullable=True),
    pa.field("price_quote_atoms", DECIMAL_U64, nullable=True),
    pa.field("buy_volume_base_atoms", DECIMAL_U64, nullable=True),
    pa.field("sell_volume_base_atoms", DECIMAL_U64, nullable=True),
    pa.field("position_state", pa.string(), nullable=False),
    pa.field("coverage_status", pa.string(), nullable=False),
    pa.field("coverage_scope_id", pa.string(), nullable=False),
    pa.field("coverage_window_id", pa.string(), nullable=False),
    pa.field("coverage_gap_id", pa.string(), nullable=True),
    pa.field("source_assertion_id", pa.string(), nullable=True),
    pa.field("source_observation_id", pa.string(), nullable=True),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

GESTURE_SCHEMA = _schema(
    pa.field("gesture_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("scene_view_digest", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("episode_id", pa.string(), nullable=True),
    pa.field("gesture_kind", pa.string(), nullable=False),
    pa.field("issued_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("received_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("command_payload_digest", pa.string(), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

INTERVIEW_SCHEMA = _schema(
    pa.field("interview_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("episode_id", pa.string(), nullable=True),
    pa.field("elicited_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("prompt_version", pa.string(), nullable=False),
    pa.field("transcript_blob_id", pa.string(), nullable=False),
    pa.field("operator_disposition", pa.string(), nullable=True),
    pa.field("crackle_type", pa.string(), nullable=True),
    pa.field("confidence_ppm", pa.int32(), nullable=True),
    pa.field("outcome_visible_before_elicitation", pa.bool_(), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

OUTCOME_SCHEMA = _schema(
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("episode_id", pa.string(), nullable=False),
    pa.field("event_kind", pa.string(), nullable=True),
    pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("outcome_known_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("horizon_end", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("is_censored", pa.bool_(), nullable=False),
    pa.field("censoring_reason", pa.string(), nullable=True),
    pa.field("competing_risk_set", pa.string(), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

PROVENANCE_ASSERTION_SCHEMA = _schema(
    pa.field("source_assertion_id", pa.string(), nullable=False),
    pa.field("source_observation_id", pa.string(), nullable=False),
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("semantic_key", pa.string(), nullable=False),
    pa.field("value_digest", pa.string(), nullable=False),
    pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

COVERAGE_WINDOW_SCHEMA = _schema(
    pa.field("coverage_window_id", pa.string(), nullable=False),
    pa.field("coverage_scope_id", pa.string(), nullable=False),
    pa.field("source_id", pa.string(), nullable=False),
    pa.field("lower_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("upper_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("coverage_kind", pa.string(), nullable=False),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)

COVERAGE_GAP_SCHEMA = _schema(
    pa.field("coverage_gap_id", pa.string(), nullable=False),
    pa.field("coverage_window_id", pa.string(), nullable=False),
    pa.field("coverage_scope_id", pa.string(), nullable=False),
    pa.field("gap_class", pa.string(), nullable=False),
    pa.field("opened_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("detected_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("recovered_at", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("recovery_known_at", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("available_commit_seq", pa.int64(), nullable=False),
)


@dataclass(frozen=True, slots=True)
class TableContract:
    schema_id: str
    schema: pa.Schema
    primary_key: tuple[str, ...]
    event_time_field: str | None


TABLE_CONTRACTS = {
    "scenes": TableContract("joshi.analysis.scene/v1", SCENE_SCHEMA, ("scene_id",), "rendered_at"),
    "territories": TableContract(
        "joshi.analysis.territory/v1", TERRITORY_SCHEMA, ("territory_id",), "first_available_at"
    ),
    "candidates": TableContract(
        "joshi.analysis.candidate/v1", CANDIDATE_SCHEMA, ("candidate_id",), "created_at"
    ),
    "candidate_social_assertions": TableContract(
        "joshi.analysis.candidate-social-assertion/v1",
        CANDIDATE_SOCIAL_ASSERTION_SCHEMA,
        ("social_assertion_id",),
        "event_time",
    ),
    "decisions": TableContract(
        "joshi.analysis.decision/v1", DECISION_SCHEMA, ("decision_id",), "decision_available_at"
    ),
    "choice_members": TableContract(
        "joshi.analysis.choice-member/v1",
        CHOICE_MEMBER_SCHEMA,
        ("decision_id", "candidate_id", "set_kind"),
        "available_at",
    ),
    "episodes": TableContract(
        "joshi.analysis.episode/v1", EPISODE_SCHEMA, ("episode_id",), "opened_at"
    ),
    "chart_samples": TableContract(
        CHART_SAMPLE_SCHEMA_ID,
        CHART_SAMPLE_SCHEMA,
        ("scene_id", "episode_id", "sample_index"),
        "event_time",
    ),
    "operator_gestures": TableContract(
        "joshi.analysis.operator-gesture/v1", GESTURE_SCHEMA, ("gesture_id",), "issued_at"
    ),
    "operator_interviews": TableContract(
        "joshi.analysis.operator-interview/v1", INTERVIEW_SCHEMA, ("interview_id",), "elicited_at"
    ),
    "outcomes": TableContract(
        "joshi.analysis.competing-risk-outcome/v1",
        OUTCOME_SCHEMA,
        ("decision_id", "candidate_id"),
        "event_time",
    ),
    "provenance_assertions": TableContract(
        "joshi.analysis.provenance-assertion/v1",
        PROVENANCE_ASSERTION_SCHEMA,
        ("source_assertion_id", "source_observation_id"),
        "observed_at",
    ),
    "coverage_windows": TableContract(
        "joshi.analysis.coverage-window/v1",
        COVERAGE_WINDOW_SCHEMA,
        ("coverage_window_id",),
        "lower_time",
    ),
    "coverage_gaps": TableContract(
        "joshi.analysis.coverage-gap/v1",
        COVERAGE_GAP_SCHEMA,
        ("coverage_gap_id",),
        "opened_at",
    ),
}


def _g0_text(name: str, *, nullable: bool = False) -> pa.Field:
    return pa.field(name, pa.string(), nullable=nullable)


def _g0_int(name: str, *, nullable: bool = False) -> pa.Field:
    return pa.field(name, pa.int64(), nullable=nullable)


def _g0_bytes(name: str, *, nullable: bool = False) -> pa.Field:
    return pa.field(name, pa.binary(), nullable=nullable)


def _g0_time(name: str) -> pa.Field:
    return pa.field(name, pa.timestamp("us", tz="UTC"), nullable=False)


G0_TABLE_CONTRACTS = {
    "source_fact_occurrences": TableContract(
        "joshi.analysis.source-fact-occurrence/v1",
        _schema(
            _g0_text("source_occurrence_id"),
            _g0_text("run_registration_id"),
            _g0_text("catalog_admission_id"),
            _g0_text("source_id"),
            _g0_text("receipt_digest"),
            _g0_text("descriptor_contract"),
            _g0_text("descriptor_digest"),
            _g0_bytes("descriptor_bytes"),
            _g0_int("descriptor_byte_length"),
            _g0_text("surface_profile_digest"),
            _g0_int("fact_count"),
            _g0_int("eligible_subject_count"),
            _g0_int("membership_count"),
            _g0_int("coverage_count"),
            _g0_int("gap_count"),
            _g0_int("rendered_subject_count"),
            _g0_int("omission_count"),
            _g0_int("hot_subject_count"),
            _g0_int("cold_control_subject_count"),
            _g0_int("known_through_commit_seq"),
            _g0_time("maximum_input_available_at"),
            _g0_text("protection_class"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("source_occurrence_id",),
        "maximum_input_available_at",
    ),
    "publication_occurrences": TableContract(
        "joshi.analysis.publication-occurrence/v1",
        _schema(
            _g0_text("publication_id"),
            _g0_text("preparation_id"),
            _g0_text("source_occurrence_id"),
            _g0_text("publication_contract"),
            _g0_text("publication_digest"),
            _g0_text("publication_bytes_digest"),
            _g0_bytes("publication_bytes"),
            _g0_int("publication_byte_length"),
            _g0_text("semantic_digest"),
            _g0_text("container_digest"),
            _g0_text("checkpoint_digest"),
            _g0_int("through_commit_seq"),
            _g0_text("supersedes_publication_id", nullable=True),
            _g0_text("head_digest"),
            _g0_bytes("head_bytes"),
            _g0_int("head_byte_length"),
            _g0_text("supersedes_head_publication_id", nullable=True),
            _g0_text("authority"),
            _g0_int("publication_commit_seq"),
            _g0_int("available_commit_seq"),
        ),
        ("publication_id",),
        None,
    ),
    "scene_occurrences": TableContract(
        "joshi.analysis.scene-occurrence/v1",
        _schema(
            _g0_text("scene_publication_id"),
            _g0_text("source_occurrence_id"),
            _g0_text("publication_digest"),
            _g0_bytes("publication_bytes"),
            _g0_text("head_digest"),
            _g0_bytes("head_bytes"),
            _g0_text("supersedes_scene_publication_id", nullable=True),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("scene_publication_id",),
        None,
    ),
    "act_occurrences": TableContract(
        "joshi.analysis.act-occurrence/v1",
        _schema(
            _g0_text("act_id"),
            _g0_text("session_id"),
            _g0_text("scene_publication_id"),
            _g0_text("occurrence_digest"),
            _g0_bytes("occurrence_bytes"),
            _g0_int("occurrence_byte_length"),
            _g0_text("logical_start_tick"),
            _g0_text("logical_end_tick", nullable=True),
            _g0_int("queue_generation"),
            _g0_text("qualification"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("act_id",),
        None,
    ),
    "episode_occurrences": TableContract(
        "joshi.analysis.episode-occurrence/v1",
        _schema(
            _g0_text("episode_id"),
            _g0_text("session_id"),
            _g0_text("scene_publication_id"),
            _g0_text("opening_act_id"),
            _g0_text("closing_act_id", nullable=True),
            _g0_text("occurrence_digest"),
            _g0_bytes("occurrence_bytes"),
            _g0_int("occurrence_byte_length"),
            _g0_text("logical_start_tick"),
            _g0_text("logical_end_tick", nullable=True),
            _g0_int("queue_generation"),
            _g0_text("qualification"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("episode_id",),
        None,
    ),
    "run_occurrences": TableContract(
        "joshi.analysis.run-occurrence/v1",
        _schema(
            _g0_text("run_registration_id"),
            _g0_text("registration_digest"),
            _g0_int("registration_byte_length"),
            _g0_text("build_digest"),
            _g0_text("source_tree_digest"),
            _g0_text("configuration_digest"),
            _g0_text("budget_digest"),
            _g0_text("privacy_digest"),
            _g0_text("daily_surface_profile_digest"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("run_registration_id",),
        None,
    ),
    "spool_catalog_occurrences": TableContract(
        "joshi.analysis.spool-catalog-occurrence/v1",
        _schema(
            _g0_text("catalog_admission_id"),
            _g0_text("run_registration_id"),
            _g0_text("segment_id"),
            _g0_text("batch_id"),
            _g0_int("store_commit_seq"),
            _g0_text("binding_digest"),
            _g0_int("binding_byte_length"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("catalog_admission_id",),
        None,
    ),
    "status_occurrences": TableContract(
        "joshi.analysis.status-occurrence/v1",
        _schema(
            _g0_text("record_id"),
            _g0_text("run_registration_id"),
            _g0_text("component"),
            _g0_text("record_kind"),
            _g0_text("state"),
            _g0_text("cause", nullable=True),
            _g0_text("predecessor_record_id", nullable=True),
            _g0_int("evidence_commit_seq", nullable=True),
            _g0_time("observed_at"),
            _g0_text("detail_digest", nullable=True),
            _g0_text("record_digest"),
            _g0_int("record_byte_length"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("record_id",),
        "observed_at",
    ),
    "export_occurrences": TableContract(
        "joshi.analysis.export-occurrence/v1",
        _schema(
            _g0_text("export_binding_id"),
            _g0_text("run_registration_id"),
            _g0_text("export_request_id"),
            _g0_text("validation_id"),
            _g0_text("snapshot_id"),
            _g0_text("truth_fingerprint_digest"),
            _g0_text("binding_digest"),
            _g0_int("binding_byte_length"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("export_binding_id",),
        None,
    ),
    "import_occurrences": TableContract(
        "joshi.analysis.import-occurrence/v1",
        _schema(
            _g0_text("import_id"),
            _g0_text("run_registration_id"),
            _g0_text("export_binding_id"),
            _g0_text("export_request_id"),
            _g0_text("analysis_run_id"),
            _g0_text("artifact_id"),
            _g0_text("artifact_contract"),
            _g0_text("manifest_digest"),
            _g0_bytes("manifest_bytes"),
            _g0_int("manifest_byte_length"),
            _g0_text("snapshot_id"),
            _g0_text("claim_scope"),
            _g0_text("truth_fingerprint_digest"),
            _g0_time("maximum_input_available_at"),
            _g0_text("registration_digest"),
            _g0_int("registration_byte_length"),
            _g0_text("cas_physical_digest"),
            _g0_int("cas_byte_length"),
            _g0_text("authority"),
            _g0_int("available_commit_seq"),
        ),
        ("import_id",),
        "maximum_input_available_at",
    ),
}

CHART_FEATURE_SCHEMA_ID = "joshi.analysis.descriptive-chart-shape/v2"
CHART_FEATURE_VERSION = "descriptive-chart-shape/v2"
DESCRIPTIVE_CLAIM_SCOPE = "descriptive_only_not_predictive_or_strategy_claim"
ANALOG_CLAIM_SCOPE = "retrieval_only_not_prediction_or_strategy_claim"
PREDICTION_CLAIM_SCOPE = "offline_model_output_not_strategy_or_execution_claim"

CHART_FEATURE_SCHEMA = _schema(
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("episode_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("territory_id", pa.string(), nullable=False),
    pa.field("base_asset_id", pa.string(), nullable=False),
    pa.field("quote_asset_id", pa.string(), nullable=False),
    pa.field("decision_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("first_event_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("last_event_time", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("expected_samples", pa.int64(), nullable=False),
    pa.field("observed_samples", pa.int64(), nullable=False),
    pa.field("gap_samples", pa.int64(), nullable=False),
    pa.field("coverage_ratio_ppm", pa.int64(), nullable=False),
    pa.field("start_price_base_atoms", DECIMAL_U64, nullable=False),
    pa.field("start_price_quote_atoms", DECIMAL_U64, nullable=False),
    pa.field("end_price_base_atoms", DECIMAL_U64, nullable=False),
    pa.field("end_price_quote_atoms", DECIMAL_U64, nullable=False),
    pa.field("signed_change_ppm", pa.int64(), nullable=False),
    pa.field("range_ppm", pa.int64(), nullable=False),
    pa.field("max_drawdown_ppm", pa.int64(), nullable=False),
    pa.field("direction_changes", pa.int64(), nullable=False),
    pa.field("path_signature", pa.string(), nullable=False),
    pa.field("exposed_samples", pa.int64(), nullable=False),
    pa.field("flat_watch_samples", pa.int64(), nullable=False),
    pa.field("runner_samples", pa.int64(), nullable=False),
    pa.field("feature_version", pa.string(), nullable=False),
    pa.field("claim_scope", pa.string(), nullable=False),
)

DATASET_ROW_SCHEMA_ID = "joshi.analysis.decision-candidate-dataset/v1"
DATASET_ROW_SCHEMA = _schema(
    pa.field("dataset_row_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("choice_set_id", pa.string(), nullable=False),
    pa.field("scene_id", pa.string(), nullable=False),
    pa.field("scene_view_digest", pa.string(), nullable=False),
    pa.field("decision_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("partition", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("territory_id", pa.string(), nullable=False),
    pa.field("episode_id", pa.string(), nullable=True),
    pa.field("is_operator_selected", pa.bool_(), nullable=False),
    pa.field("source_rank", pa.int32(), nullable=True),
    pa.field("rendered_ordinal", pa.int32(), nullable=True),
    pa.field("in_viewport", pa.bool_(), nullable=False),
    pa.field("interacted", pa.bool_(), nullable=False),
    pa.field("choice_set_size", pa.int64(), nullable=False),
    pa.field("universe_digest", pa.string(), nullable=False),
    pa.field("creator_identity_as_known", pa.string(), nullable=True),
    pa.field("creator_identity_assertion_id", pa.string(), nullable=True),
    pa.field("chart_feature_status", pa.string(), nullable=False),
    pa.field("chart_coverage_ratio_ppm", pa.int64(), nullable=True),
    pa.field("chart_signed_change_ppm", pa.int64(), nullable=True),
    pa.field("chart_range_ppm", pa.int64(), nullable=True),
    pa.field("chart_max_drawdown_ppm", pa.int64(), nullable=True),
    pa.field("chart_direction_changes", pa.int64(), nullable=True),
    pa.field("chart_path_signature", pa.string(), nullable=True),
    pa.field("predecision_gesture_count", pa.int64(), nullable=False),
    pa.field("label_status", pa.string(), nullable=False),
    pa.field("label_event_kind", pa.string(), nullable=True),
    pa.field("label_event_time", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("label_known_at", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("label_is_censored", pa.bool_(), nullable=True),
    pa.field("label_censoring_reason", pa.string(), nullable=True),
    pa.field("feature_spec_id", pa.string(), nullable=False),
    pa.field("feature_spec_digest", pa.string(), nullable=False),
    pa.field("label_spec_id", pa.string(), nullable=False),
    pa.field("label_spec_digest", pa.string(), nullable=False),
    pa.field("dataset_spec_id", pa.string(), nullable=False),
    pa.field("dataset_spec_digest", pa.string(), nullable=False),
    pa.field("input_snapshot_id", pa.string(), nullable=False),
    pa.field("claim_scope", pa.string(), nullable=False),
)

ANALOG_RESULT_SCHEMA_ID = "joshi.analysis.descriptive-analog-retrieval/v1"
ANALOG_RESULT_SCHEMA = _schema(
    pa.field("query_decision_id", pa.string(), nullable=False),
    pa.field("query_candidate_id", pa.string(), nullable=False),
    pa.field("query_episode_id", pa.string(), nullable=False),
    pa.field("analog_rank", pa.int32(), nullable=False),
    pa.field("analog_decision_id", pa.string(), nullable=False),
    pa.field("analog_candidate_id", pa.string(), nullable=False),
    pa.field("analog_episode_id", pa.string(), nullable=False),
    pa.field("analog_decision_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("same_territory", pa.bool_(), nullable=False),
    pa.field("shape_distance_ppm", pa.int64(), nullable=False),
    pa.field("query_path_signature", pa.string(), nullable=False),
    pa.field("analog_path_signature", pa.string(), nullable=False),
    pa.field("retrieval_version", pa.string(), nullable=False),
    pa.field("claim_scope", pa.string(), nullable=False),
)

PREDICTION_SCHEMA_ID = "joshi.analysis.decision-choice-prediction/v1"
PREDICTION_SCHEMA = _schema(
    pa.field("prediction_id", pa.string(), nullable=False),
    pa.field("model_id", pa.string(), nullable=False),
    pa.field("model_version", pa.string(), nullable=False),
    pa.field("ensemble_id", pa.string(), nullable=True),
    pa.field("dataset_id", pa.string(), nullable=False),
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("candidate_id", pa.string(), nullable=False),
    pa.field("universe_digest", pa.string(), nullable=False),
    pa.field("information_cutoff", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("score_name", pa.string(), nullable=False),
    pa.field("score_value", pa.float64(), nullable=False),
    pa.field("uncertainty_lower", pa.float64(), nullable=False),
    pa.field("uncertainty_upper", pa.float64(), nullable=False),
    pa.field("uncertainty_level_ppm", pa.int32(), nullable=False),
    pa.field("calibration_method", pa.string(), nullable=False),
    pa.field("calibration_artifact_id", pa.string(), nullable=False),
    pa.field("calibration_artifact_digest", pa.string(), nullable=False),
    pa.field("ensemble_member_count", pa.int32(), nullable=False),
    pa.field("missing_feature_policy", pa.string(), nullable=False),
    pa.field("claim_scope", pa.string(), nullable=False),
)

DECISION_EVALUATION_SCHEMA_ID = "joshi.analysis.decision-evaluation/v1"
DECISION_EVALUATION_SCHEMA = _schema(
    pa.field("decision_id", pa.string(), nullable=False),
    pa.field("universe_digest", pa.string(), nullable=False),
    pa.field("candidate_count", pa.int64(), nullable=False),
    pa.field("prediction_count", pa.int64(), nullable=False),
    pa.field("selected_candidate_id", pa.string(), nullable=True),
    pa.field("selected_score", pa.float64(), nullable=True),
    pa.field("selected_score_rank", pa.int64(), nullable=True),
    pa.field("label_status", pa.string(), nullable=False),
    pa.field("event_kind", pa.string(), nullable=True),
    pa.field("is_censored", pa.bool_(), nullable=True),
    pa.field("evaluation_version", pa.string(), nullable=False),
)
