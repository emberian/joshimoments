use joshi_domain::{StableString, UtcTimestamp, WireU64};
use joshi_operational_status::{
    DEGRADATION_POLICY_CONTRACT, DegradationPolicyV1, DegradationStage, DrainAssessment,
    HEALTH_CONTRACT, OperationalStatusQueryResultV1, OperationalStatusQueryV1, QUERY_CONTRACT,
    QUERY_RESULT_CONTRACT, QueryTargetV1, RecoveryDrainWindowV1, ResourceKind,
    assess_recovery_drain, decode_health_v1, decode_query_result_for_query_v1,
    decode_query_result_v1, decode_query_v1, evaluate_degradation,
};
use std::str::FromStr;

fn timestamp(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("fixture timestamp")
}

fn policy() -> DegradationPolicyV1 {
    DegradationPolicyV1 {
        contract: DEGRADATION_POLICY_CONTRACT.to_owned(),
        policy_id: StableString::new("degradation-policy:test").expect("policy ID"),
        optional_media_at_ppm: WireU64::new(500_000),
        slow_social_at_ppm: WireU64::new(700_000),
        reduce_hot_scopes_at_ppm: WireU64::new(800_000),
        census_only_at_ppm: WireU64::new(900_000),
        stop_before_reserve_at_ppm: WireU64::new(990_000),
        recovery_drain_to_arrival_ppm: WireU64::new(2_000_000),
    }
}

#[test]
fn pressure_uses_both_record_and_byte_capacity_and_stops_at_disk_floor() {
    let mut health = decode_health_v1(include_bytes!(
        "../../../fixtures/operational-status/health_degraded.json"
    ))
    .expect("health fixture");
    health.evidence_queue.bytes.used = WireU64::new(62_000_000);
    let decision =
        evaluate_degradation(&policy(), &health, HEALTH_CONTRACT).expect("pressure decision");
    assert_eq!(decision.stage, DegradationStage::CensusOnly);

    let disk = health
        .resources
        .iter_mut()
        .find(|value| value.kind == ResourceKind::DiskFreeBytes)
        .expect("disk resource");
    disk.observed = WireU64::new(1);
    let decision =
        evaluate_degradation(&policy(), &health, HEALTH_CONTRACT).expect("disk decision");
    assert_eq!(decision.stage, DegradationStage::StopBeforeControlReserve);
}

#[test]
fn drain_target_is_recovery_window_only_and_conserves_backlog() {
    let window = RecoveryDrainWindowV1 {
        recovery_window_id: StableString::new("recovery-window:test").expect("window ID"),
        started_at: timestamp("2026-08-17T12:00:00.000000Z"),
        ended_at: timestamp("2026-08-17T12:01:00.000000Z"),
        backlog_start_records: WireU64::new(10),
        admitted_arrival_records: WireU64::new(2),
        durably_drained_records: WireU64::new(4),
        backlog_end_records: WireU64::new(8),
        backlog_start_bytes: WireU64::new(1_000),
        admitted_arrival_bytes: WireU64::new(200),
        durably_drained_bytes: WireU64::new(400),
        backlog_end_bytes: WireU64::new(800),
    };
    assert_eq!(
        assess_recovery_drain(&window, WireU64::new(2_000_000)).expect("drain assessment"),
        DrainAssessment::MeetsTarget
    );
    let mut inconsistent = window;
    inconsistent.backlog_end_bytes = WireU64::new(801);
    assert!(assess_recovery_drain(&inconsistent, WireU64::new(2_000_000)).is_err());
}

#[test]
fn query_is_strict_bounded_and_contains_no_free_form_search() {
    let valid = br#"{
      "contract":"joshi.operational.status_query/v1",
      "queryId":"query:1",
      "target":{"kind":"health"},
      "pageSize":"100",
      "after":null
    }"#;
    let parsed = decode_query_v1(valid).expect("strict query");
    assert_eq!(parsed.contract, QUERY_CONTRACT);

    let unknown = br#"{
      "contract":"joshi.operational.status_query/v1",
      "queryId":"query:1",
      "target":{"kind":"health","mint":"forbidden"},
      "pageSize":"100",
      "after":null
    }"#;
    assert!(decode_query_v1(unknown).is_err());

    let unbounded = OperationalStatusQueryV1 {
        page_size: WireU64::new(101),
        ..parsed
    };
    assert!(unbounded.validate().is_err());
}

#[test]
fn query_result_decoder_enforces_requested_page_and_read_only_authority() {
    let result = OperationalStatusQueryResultV1 {
        contract: QUERY_RESULT_CONTRACT.to_owned(),
        query_id: StableString::new("query:1").expect("query ID"),
        target: QueryTargetV1::Health {},
        authority: joshi_operational_status::AUTHORITY_CEILING.to_owned(),
        generated_at: timestamp("2026-08-17T12:00:00.000000Z"),
        catalog_through: None,
        items: Vec::new(),
        next_cursor: None,
        complete: true,
    };
    let bytes = serde_json::to_vec(&result).expect("result JSON");
    let decoded = decode_query_result_v1(&bytes, WireU64::new(1)).expect("bounded result");
    assert_eq!(decoded.query_id, result.query_id);

    let query: OperationalStatusQueryV1 = serde_json::from_slice(
        br#"{
      "contract":"joshi.operational.status_query/v1",
      "queryId":"query:1",
      "target":{"kind":"health"},
      "pageSize":"1",
      "after":null
    }"#,
    )
    .expect("query");
    decode_query_result_for_query_v1(&bytes, &query).expect("bound query result");
    let mut wrong_query = query;
    wrong_query.query_id = StableString::new("query:other").expect("query ID");
    assert!(decode_query_result_for_query_v1(&bytes, &wrong_query).is_err());

    let mut forbidden = result;
    forbidden.authority = "operator_execution".to_owned();
    let bytes = serde_json::to_vec(&forbidden).expect("forbidden JSON");
    assert!(decode_query_result_v1(&bytes, WireU64::new(1)).is_err());
    assert!(decode_query_result_v1(&bytes, WireU64::new(0)).is_err());
}
