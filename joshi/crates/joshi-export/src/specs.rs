use arrow_schema::{DataType, Field, Schema, TimeUnit};

/// Frozen table contract required as one complete snapshot closure.
pub(crate) struct TableSpec {
    pub(crate) name: &'static str,
    pub(crate) schema_id: &'static str,
    pub(crate) primary_key: &'static [&'static str],
}

impl TableSpec {
    pub(crate) fn schema(&self) -> Schema {
        schema(self.name)
    }
}

fn text(name: &str, nullable: bool) -> Field {
    Field::new(name, DataType::Utf8, nullable)
}
fn int32(name: &str, nullable: bool) -> Field {
    Field::new(name, DataType::Int32, nullable)
}
fn int64(name: &str, nullable: bool) -> Field {
    Field::new(name, DataType::Int64, nullable)
}
fn boolean(name: &str, nullable: bool) -> Field {
    Field::new(name, DataType::Boolean, nullable)
}
fn instant(name: &str, nullable: bool) -> Field {
    Field::new(
        name,
        DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into())),
        nullable,
    )
}
fn atoms(name: &str, nullable: bool) -> Field {
    Field::new(name, DataType::Decimal128(20, 0), nullable)
}

#[allow(clippy::too_many_lines)]
fn schema(name: &str) -> Schema {
    let fields = match name {
        "scenes" => vec![
            text("scene_id", false),
            text("scene_mode", false),
            text("view_contract", false),
            text("view_contract_version", false),
            text("view_digest", false),
            text("source_mode", false),
            instant("rendered_at", false),
            instant("decision_available_at", false),
            int64("knowledge_commit_seq", false),
            int64("available_commit_seq", false),
        ],
        "territories" => vec![
            text("territory_id", false),
            text("territory_kind", false),
            text("description", false),
            instant("first_available_at", false),
            int64("available_commit_seq", false),
            text("source_assertion_id", false),
            text("source_observation_id", false),
        ],
        "candidates" => vec![
            text("candidate_id", false),
            text("mint_asset_id", false),
            text("territory_id", false),
            instant("created_at", false),
            instant("first_available_at", false),
            int64("available_commit_seq", false),
            text("source_assertion_id", false),
            text("source_observation_id", false),
        ],
        "candidate_social_assertions" => vec![
            text("social_assertion_id", false),
            text("candidate_id", false),
            text("identity_kind", false),
            text("identity_key", false),
            instant("event_time", false),
            instant("observed_at", false),
            instant("available_at", false),
            int64("available_commit_seq", false),
            text("source_assertion_id", false),
            text("source_observation_id", false),
        ],
        "decisions" => vec![
            text("decision_id", false),
            text("scene_id", false),
            text("choice_set_id", false),
            text("selected_candidate_id", true),
            text("episode_id", true),
            text("operator_action", false),
            text("selection_gesture_id", true),
            instant("decision_available_at", false),
            int64("available_commit_seq", false),
        ],
        "choice_members" => vec![
            text("choice_set_id", false),
            text("decision_id", false),
            text("scene_id", false),
            text("candidate_id", false),
            text("set_kind", false),
            int32("source_rank", true),
            int32("rendered_ordinal", true),
            boolean("in_viewport", false),
            boolean("interacted", false),
            text("evidence_assertion_id", true),
            text("evidence_observation_id", true),
            instant("available_at", false),
            int64("available_commit_seq", false),
        ],
        "episodes" => vec![
            text("episode_id", false),
            text("decision_id", false),
            text("candidate_id", false),
            text("territory_id", false),
            instant("opened_at", false),
            instant("closed_at", true),
            text("status", false),
            text("reentry_of_episode_id", true),
            text("operator_disposition", false),
            int64("available_commit_seq", false),
        ],
        "chart_samples" => vec![
            text("scene_id", false),
            text("scene_mode", false),
            text("scene_view_digest", false),
            text("decision_id", false),
            text("episode_id", false),
            text("candidate_id", false),
            text("territory_id", false),
            text("base_asset_id", false),
            text("quote_asset_id", false),
            int32("sample_index", false),
            int32("expected_sample_count", false),
            instant("event_time", false),
            instant("observed_at", false),
            instant("available_at", false),
            instant("decision_available_at", false),
            atoms("price_base_atoms", true),
            atoms("price_quote_atoms", true),
            atoms("buy_volume_base_atoms", true),
            atoms("sell_volume_base_atoms", true),
            text("position_state", false),
            text("coverage_status", false),
            text("coverage_scope_id", false),
            text("coverage_window_id", false),
            text("coverage_gap_id", true),
            text("source_assertion_id", true),
            text("source_observation_id", true),
            int64("available_commit_seq", false),
        ],
        "operator_gestures" => vec![
            text("gesture_id", false),
            text("decision_id", false),
            text("scene_id", false),
            text("scene_view_digest", false),
            text("candidate_id", false),
            text("episode_id", true),
            text("gesture_kind", false),
            instant("issued_at", false),
            instant("received_at", false),
            instant("available_at", false),
            text("command_payload_digest", false),
            int64("available_commit_seq", false),
        ],
        "operator_interviews" => vec![
            text("interview_id", false),
            text("decision_id", false),
            text("scene_id", false),
            text("episode_id", true),
            instant("elicited_at", false),
            instant("available_at", false),
            text("prompt_version", false),
            text("transcript_blob_id", false),
            text("operator_disposition", true),
            text("crackle_type", true),
            int32("confidence_ppm", true),
            boolean("outcome_visible_before_elicitation", false),
            int64("available_commit_seq", false),
        ],
        "outcomes" => vec![
            text("decision_id", false),
            text("candidate_id", false),
            text("episode_id", false),
            text("event_kind", true),
            instant("event_time", true),
            instant("outcome_known_at", false),
            instant("horizon_end", false),
            boolean("is_censored", false),
            text("censoring_reason", true),
            text("competing_risk_set", false),
            int64("available_commit_seq", false),
        ],
        "provenance_assertions" => vec![
            text("source_assertion_id", false),
            text("source_observation_id", false),
            text("source_id", false),
            text("semantic_key", false),
            text("value_digest", false),
            instant("observed_at", false),
            instant("available_at", false),
            int64("available_commit_seq", false),
        ],
        "coverage_windows" => vec![
            text("coverage_window_id", false),
            text("coverage_scope_id", false),
            text("source_id", false),
            instant("lower_time", false),
            instant("upper_time", false),
            text("coverage_kind", false),
            int64("available_commit_seq", false),
        ],
        "coverage_gaps" => vec![
            text("coverage_gap_id", false),
            text("coverage_window_id", false),
            text("coverage_scope_id", false),
            text("gap_class", false),
            instant("opened_at", false),
            instant("detected_at", false),
            instant("available_at", false),
            instant("recovered_at", true),
            instant("recovery_known_at", true),
            int64("available_commit_seq", false),
        ],
        _ => unreachable!("frozen table name"),
    };
    Schema::new(fields)
}

pub(crate) const TABLE_SPECS: &[TableSpec] = &[
    TableSpec {
        name: "scenes",
        schema_id: "joshi.analysis.scene/v1",
        primary_key: &["scene_id"],
    },
    TableSpec {
        name: "territories",
        schema_id: "joshi.analysis.territory/v1",
        primary_key: &["territory_id"],
    },
    TableSpec {
        name: "candidates",
        schema_id: "joshi.analysis.candidate/v1",
        primary_key: &["candidate_id"],
    },
    TableSpec {
        name: "candidate_social_assertions",
        schema_id: "joshi.analysis.candidate-social-assertion/v1",
        primary_key: &["social_assertion_id"],
    },
    TableSpec {
        name: "decisions",
        schema_id: "joshi.analysis.decision/v1",
        primary_key: &["decision_id"],
    },
    TableSpec {
        name: "choice_members",
        schema_id: "joshi.analysis.choice-member/v1",
        primary_key: &["decision_id", "candidate_id", "set_kind"],
    },
    TableSpec {
        name: "episodes",
        schema_id: "joshi.analysis.episode/v1",
        primary_key: &["episode_id"],
    },
    TableSpec {
        name: "chart_samples",
        schema_id: "joshi.analysis.chart-sample/v1",
        primary_key: &["scene_id", "episode_id", "sample_index"],
    },
    TableSpec {
        name: "operator_gestures",
        schema_id: "joshi.analysis.operator-gesture/v1",
        primary_key: &["gesture_id"],
    },
    TableSpec {
        name: "operator_interviews",
        schema_id: "joshi.analysis.operator-interview/v1",
        primary_key: &["interview_id"],
    },
    TableSpec {
        name: "outcomes",
        schema_id: "joshi.analysis.competing-risk-outcome/v1",
        primary_key: &["decision_id", "candidate_id"],
    },
    TableSpec {
        name: "provenance_assertions",
        schema_id: "joshi.analysis.provenance-assertion/v1",
        primary_key: &["source_assertion_id", "source_observation_id"],
    },
    TableSpec {
        name: "coverage_windows",
        schema_id: "joshi.analysis.coverage-window/v1",
        primary_key: &["coverage_window_id"],
    },
    TableSpec {
        name: "coverage_gaps",
        schema_id: "joshi.analysis.coverage-gap/v1",
        primary_key: &["coverage_gap_id"],
    },
];
