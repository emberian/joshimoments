use joshi_attention::{AttentionDataset, ValidationCode};
use serde::Deserialize;
use serde_json::{Value, json};

const STUDY_READY: &[u8] = include_bytes!("../../../fixtures/attention/study-ready.valid.json");
const ADVERSARIAL: &[u8] =
    include_bytes!("../../../fixtures/attention/adversarial-mutations.v1.json");

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MutationFile {
    contract: String,
    base: String,
    cases: Vec<MutationCase>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MutationCase {
    id: String,
    pointer: String,
    value: Value,
    expected_code: String,
    meaning: String,
}

#[test]
fn study_ready_fixture_is_strict_and_valid() {
    let dataset: AttentionDataset = serde_json::from_slice(STUDY_READY).expect("strict fixture");
    dataset.validate().expect("valid point-in-time dataset");

    let encoded = serde_json::to_value(dataset).expect("encode fixture");
    assert_eq!(
        encoded["exact_inputs"][0]["payload"]["market_cap_lexeme"],
        "9007199254740993"
    );
    assert_eq!(
        encoded["audience_overlap_estimates"][0]["intersection_count"],
        "2"
    );
    assert_eq!(
        encoded["audience_overlap_estimates"][0]["left_denominator"],
        "5"
    );
    assert_eq!(
        encoded["audience_overlap_estimates"][0]["right_denominator"],
        "7"
    );
}

#[test]
fn checked_in_ambiguity_mutations_fail_closed() {
    let mutation_file: MutationFile =
        serde_json::from_slice(ADVERSARIAL).expect("mutation fixture");
    assert_eq!(
        mutation_file.contract,
        "joshi.attention.adversarial_mutations.v1"
    );
    assert_eq!(mutation_file.base, "study-ready.valid.json");
    assert!(mutation_file.cases.len() >= 9);

    for case in mutation_file.cases {
        assert!(!case.meaning.is_empty(), "{} needs a rationale", case.id);
        let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
        *value
            .pointer_mut(&case.pointer)
            .unwrap_or_else(|| panic!("{} pointer exists", case.id)) = case.value;
        let dataset: AttentionDataset = serde_json::from_value(value)
            .unwrap_or_else(|error| panic!("{} parses: {error}", case.id));
        let Err(error) = dataset.validate() else {
            panic!("{} must fail", case.id);
        };
        assert_eq!(
            format!("{:?}", error.code),
            case.expected_code,
            "{}",
            case.id
        );
    }
}

#[test]
fn strict_wire_rejects_unknown_fields_and_non_string_integers() {
    let mut unknown: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    unknown["kernel_events"][0]["caused_return"] = json!(true);
    assert!(serde_json::from_value::<AttentionDataset>(unknown).is_err());

    let mut numeric: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    numeric["kernel_events"][0]["amount_atoms"] = json!(9_007_199_254_740_993_u64);
    assert!(serde_json::from_value::<AttentionDataset>(numeric).is_err());
}

#[test]
fn follow_removal_needs_presence_and_comparable_gap_free_snapshots() {
    let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    let inputs = value["exact_inputs"].as_array_mut().expect("input array");
    inputs.push(follow_boundary(
        "attention-input:follow-snapshot:before",
        "follow-snapshot:before",
        "2026-08-16T10:00:01.000000Z",
        "2026-08-16T10:00:02.000000Z",
        "30",
    ));
    inputs.push(follow_member());
    inputs.push(follow_boundary(
        "attention-input:follow-snapshot:after",
        "follow-snapshot:after",
        "2026-08-16T11:00:01.000000Z",
        "2026-08-16T11:00:02.000000Z",
        "32",
    ));
    value["follow_edge_versions"] = json!([{
        "assertion_id": "follow-edge:root-member:v2",
        "root_subject_id": "pump-user:root",
        "member_subject_id": "pump-user:member",
        "direction": "root_follows_member",
        "state": "removed",
        "valid_time": {
            "lower": "2026-08-16T11:00:01.000000Z",
            "upper": null
        },
        "knowledge_time": {
            "known_from": "2026-08-16T11:00:02.000000Z",
            "known_until": null,
            "available_commit": "32"
        },
        "source_snapshot_input_ids": [
            "attention-input:follow-snapshot:before",
            "attention-input:follow-snapshot:after"
        ],
        "presence_member_input_id": "attention-input:follow-member:before",
        "comparable_scope": true,
        "intervening_gap_ids": [],
        "status": "supported"
    }]);
    let dataset: AttentionDataset = serde_json::from_value(value.clone()).expect("follow fixture");
    dataset.validate().expect("gap-free removal is admissible");

    value["follow_edge_versions"][0]["intervening_gap_ids"] = json!(["gap:follow-root:1030-1040"]);
    let invalid: AttentionDataset = serde_json::from_value(value).expect("invalid parses");
    assert_eq!(
        invalid.validate().expect_err("gap must reject").code,
        ValidationCode::InvalidFollowRemoval
    );
}

#[test]
fn content_deletion_retains_an_explicit_revision_chain() {
    let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    let inputs = value["exact_inputs"].as_array_mut().expect("input array");
    inputs.push(content_revision(
        "attention-input:comment:r1",
        "comment:001:r1",
        None,
        "created",
        Some("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        "40",
    ));
    inputs.push(content_revision(
        "attention-input:comment:r2",
        "comment:001:r2",
        Some("comment:001:r1"),
        "edited",
        Some("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        "41",
    ));
    inputs.push(content_revision(
        "attention-input:comment:r3",
        "comment:001:r3",
        Some("comment:001:r2"),
        "deleted",
        None,
        "42",
    ));
    let dataset: AttentionDataset =
        serde_json::from_value(value.clone()).expect("revision fixture");
    dataset
        .validate()
        .expect("explicit deletion chain is valid");

    value["exact_inputs"]
        .as_array_mut()
        .expect("input array")
        .last_mut()
        .expect("deletion")["payload"]["supersedes_revision_id"] = Value::Null;
    let invalid: AttentionDataset = serde_json::from_value(value).expect("invalid parses");
    assert_eq!(
        invalid
            .validate()
            .expect_err("orphan deletion rejects")
            .code,
        ValidationCode::InvalidRevision
    );
}

#[test]
fn identity_series_closes_knowledge_time_and_rejects_cycles() {
    let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    value["identity_versions"][0]["knowledge_time"]["known_until"] =
        json!("2026-08-16T12:20:00.000000Z");
    value["identity_versions"][1]["identity_series_id"] =
        json!("identity-series:pump-user:caller-001");
    value["identity_versions"][1]["subject_id"] = json!("pump-user:caller-001");
    value["identity_versions"][1]["supersedes"] = json!("identity:caller-001:v1");
    let valid: AttentionDataset = serde_json::from_value(value.clone()).expect("series parses");
    valid
        .validate()
        .expect("closed same-subject chain is valid");

    value["identity_versions"][0]["knowledge_time"]["known_until"] = Value::Null;
    let stale: AttentionDataset = serde_json::from_value(value.clone()).expect("stale parses");
    assert_eq!(
        stale
            .validate()
            .expect_err("open stale version rejects")
            .code,
        ValidationCode::InvalidRevision
    );

    value["identity_versions"][0]["knowledge_time"]["known_until"] =
        json!("2026-08-16T12:20:00.000000Z");
    value["identity_versions"][0]["supersedes"] = json!("identity:impostor:v1");
    let cycle: AttentionDataset = serde_json::from_value(value).expect("cycle parses");
    assert_eq!(
        cycle.validate().expect_err("cycle rejects").code,
        ValidationCode::InvalidRevision
    );
}

#[test]
fn bounded_event_intervals_are_nonempty_half_open_ranges() {
    let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    value["response_observations"][0]["event_time"]["upper"] =
        value["response_observations"][0]["event_time"]["lower"].clone();
    let invalid: AttentionDataset = serde_json::from_value(value).expect("empty interval parses");
    assert_eq!(
        invalid.validate().expect_err("empty interval rejects").code,
        ValidationCode::InvalidTime
    );
}

#[test]
fn one_attention_event_cannot_have_alternative_selected_cluster_contexts() {
    let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    let mut duplicate = value["selected_cluster_contexts"][0].clone();
    duplicate["cluster_context_id"] = json!("cluster-context:callout-001:alternative");
    value["selected_cluster_contexts"]
        .as_array_mut()
        .expect("contexts")
        .push(duplicate);
    let invalid: AttentionDataset = serde_json::from_value(value).expect("duplicate parses");
    assert_eq!(
        invalid
            .validate()
            .expect_err("two selected contexts reject")
            .code,
        ValidationCode::DuplicateIdentity
    );
}

#[test]
fn permissionless_sweeps_and_mintless_platform_claims_stay_distinct() {
    let mut value: Value = serde_json::from_slice(STUDY_READY).expect("base JSON");
    let mut sweep = value["exact_inputs"][1].clone();
    sweep["input_id"] = json!("attention-input:ordinary-fee-sweep");
    sweep["evidence"]["acquisition_id"] = json!("fixture-acq:ordinary-fee-sweep");
    sweep["evidence"]["observation_id"] = json!("fixture-obs:ordinary-fee-sweep");
    sweep["kind"] = json!("creator_relation_observed");
    sweep["payload"] = json!({
        "mint_id": "solana:mint:Coin111111111111111111111111111111111111",
        "relation": "ordinary_fee_sweep",
        "subject_wallet_id": null,
        "recipient_wallet_id": "solana:wallet:Creator1111111111111111111111111111111",
        "actor_wallet_id": "solana:wallet:ArbitraryCaller11111111111111111111111111",
        "permission_model": "permissionless",
        "chain_slot": "140"
    });
    let mut claim = value["exact_inputs"][1].clone();
    claim["input_id"] = json!("attention-input:social-fee-claim");
    claim["evidence"]["acquisition_id"] = json!("fixture-acq:social-fee-claim");
    claim["evidence"]["observation_id"] = json!("fixture-obs:social-fee-claim");
    claim["payload"] = json!({
        "transition": "social_fee_claim",
        "subject_id": "external-social-id:12345",
        "wallet_id": "solana:wallet:Recipient111111111111111111111111111111",
        "mint_id": null,
        "community_id": null,
        "authority": "platform_authorized"
    });
    value["exact_inputs"]
        .as_array_mut()
        .expect("inputs")
        .extend([sweep, claim]);
    let valid: AttentionDataset = serde_json::from_value(value.clone()).expect("semantic fixture");
    valid.validate().expect("distinct semantics are valid");

    let inputs = value["exact_inputs"].as_array_mut().expect("inputs");
    let sweep_index = inputs.len() - 2;
    inputs[sweep_index]["payload"]["permission_model"] = json!("subject_signature");
    let invalid: AttentionDataset = serde_json::from_value(value).expect("wrong sweep parses");
    assert_eq!(
        invalid.validate().expect_err("wrong sweep rejects").code,
        ValidationCode::InvalidJoin
    );
}

fn follow_boundary(
    input_id: &str,
    snapshot_id: &str,
    observed_at: &str,
    available_at: &str,
    commit: &str,
) -> Value {
    json!({
        "input_id": input_id,
        "evidence": evidence(input_id, observed_at, available_at, commit, "complete", []),
        "event_time": {"status": "not_applicable", "lower": null, "upper": null, "precision_us": null, "source_value": null},
        "kind": "follow_snapshot_observed",
        "payload": {
            "snapshot_id": snapshot_id,
            "direction": "root_follows_member",
            "root_subject_id": "pump-user:root",
            "reported_total": "1",
            "observed_member_count": "1",
            "pagination_complete": true
        }
    })
}

fn follow_member() -> Value {
    json!({
        "input_id": "attention-input:follow-member:before",
        "evidence": evidence(
            "attention-input:follow-member:before",
            "2026-08-16T10:00:01.000000Z",
            "2026-08-16T10:00:02.000000Z",
            "31",
            "complete",
            []
        ),
        "event_time": {"status": "source_missing", "lower": null, "upper": null, "precision_us": null, "source_value": "provider did not return follow time"},
        "kind": "follow_snapshot_member",
        "payload": {
            "snapshot_id": "follow-snapshot:before",
            "direction": "root_follows_member",
            "root_subject_id": "pump-user:root",
            "member_subject_id": "pump-user:member",
            "root_wallet_id": null,
            "member_wallet_id": null,
            "provider_follow_time": {"status": "source_missing", "lower": null, "upper": null, "precision_us": null, "source_value": "not provided"},
            "ordinal": "0"
        }
    })
}

fn content_revision(
    input_id: &str,
    revision_id: &str,
    supersedes: Option<&str>,
    state: &str,
    blob: Option<&str>,
    commit: &str,
) -> Value {
    json!({
        "input_id": input_id,
        "evidence": evidence(
            input_id,
            "2026-08-16T12:40:01.000000Z",
            "2026-08-16T12:40:02.000000Z",
            commit,
            "partial",
            []
        ),
        "event_time": {"status": "exact", "lower": "2026-08-16T12:40:00.000000Z", "upper": "2026-08-16T12:40:01.000000Z", "precision_us": "1000000", "source_value": "2026-08-16T12:40:00Z"},
        "kind": "social_content_observed",
        "payload": {
            "provider_object_id": "comment:001",
            "revision_id": revision_id,
            "supersedes_revision_id": supersedes,
            "content_kind": "comment",
            "state": state,
            "parent_object_id": null,
            "mint_id": "solana:mint:Coin111111111111111111111111111111111111",
            "community_id": "pump-community:coin-001",
            "author_subject_id": "pump-user:commenter",
            "author_wallet_id": null,
            "content_blob_id": blob
        }
    })
}

fn evidence(
    id: &str,
    observed_at: &str,
    available_at: &str,
    commit: &str,
    coverage_state: &str,
    gaps: [&str; 0],
) -> Value {
    json!({
        "acquisition_id": format!("fixture-acq:{id}"),
        "observation_id": format!("fixture-obs:{id}"),
        "source_id": "fixture.attention.v1",
        "source_variant": "offline_fixture",
        "observed_at": observed_at,
        "available_at": available_at,
        "available_commit": commit,
        "coverage": {
            "scope_id": format!("coverage:{id}"),
            "population": format!("fixture population {id}"),
            "state": coverage_state,
            "window_ids": [format!("window:{id}")],
            "gap_ids": gaps,
            "source_cursor": null
        },
        "protection_domain": "derived_restricted",
        "retention_class": "derived_research",
        "epistemic_class": "provider_assertion"
    })
}
