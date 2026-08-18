use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};

use crate::{
    ARTIFACT_DAG_CONTRACT, ArtifactDagV1, ArtifactDecisionKindV1, ArtifactDecisionV1,
    ArtifactOccurrenceV1, ArtifactRefV1, CAMPAIGN_LIFECYCLE_CONTRACT, CampaignLifecycleV1,
    CampaignStateV1, CampaignTransitionV1, ClaimCausalityV1, ClaimEconomicMeaningV1,
    ClaimIdentityMeaningV1, ClaimLanguageV1, ClaimRungV1, ClaimVerbV1,
    FIXTURE_DECISION_LEDGER_CONTRACT, FixtureDecisionLedgerV1, ProgramAuthorityV1, RegistryError,
    SemanticCeilingV1, Wave6ProgramRegistrationV1, canonical_bytes, digest_bytes,
    parse_artifact_dag_exact, parse_campaign_lifecycle_exact, parse_decision_ledger_exact,
    parse_evaluation_artifact_exact, parse_program_registration_exact, validate_claim_language,
};

const FIXTURE: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
const CAMPAIGN_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/wave6/schemas/campaign_registration_v1.json");
const KNOWN_TRUTH_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/wave6/schemas/known_truth_evaluation_v1.json");
const MARKET_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/wave6/schemas/market_atlas_snapshot_v1.json");
const PROTOCOL_TRUTH_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/wave6/schemas/protocol_known_truth_evaluation_v1.json");
const RESEARCH_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/wave6/schemas/research_proposal_v1.json");
const STRUCTURAL_TRUTH_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/wave6/schemas/structural_known_truth_evaluation_v1.json");
const KNOWN_TRUTH_EVALUATION: &[u8] =
    include_bytes!("../../../fixtures/wave6/artifacts/known_truth_evaluation_v1.json");
const PROTOCOL_TRUTH_EVALUATION: &[u8] =
    include_bytes!("../../../fixtures/wave6/artifacts/protocol_known_truth_evaluation_v1.json");
const STRUCTURAL_TRUTH_EVALUATION: &[u8] =
    include_bytes!("../../../fixtures/wave6/artifacts/structural_known_truth_evaluation_v1.json");

fn fixture() -> Wave6ProgramRegistrationV1 {
    serde_json::from_slice(FIXTURE).expect("checked-in registration fixture")
}

fn reclose(value: &mut Wave6ProgramRegistrationV1) {
    value.registration_digest =
        digest_bytes(&canonical_bytes(&value.digest_material()).expect("material bytes"))
            .expect("material digest");
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

fn digest(value: &str) -> ValueDigest {
    digest_bytes(value.as_bytes()).expect("digest")
}

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().expect("timestamp")
}

fn artifact_ref(id: &str, content: &str) -> ArtifactRefV1 {
    ArtifactRefV1 {
        artifact_id: stable(id),
        content_digest: digest(content),
    }
}

fn dag() -> ArtifactDagV1 {
    let mut value = ArtifactDagV1 {
        contract: stable(ARTIFACT_DAG_CONTRACT),
        program_id: stable("w6-program-fixture-001"),
        registration_digest: fixture().registration_digest,
        artifacts: vec![
            ArtifactOccurrenceV1 {
                artifact_id: stable("artifact-market-001"),
                kind_id: stable("market_atlas_fixture"),
                content_digest: digest("market atlas fixture bytes"),
                information_cutoff: timestamp("2026-08-18T00:00:01.000000Z"),
                produced_at: timestamp("2026-08-18T00:00:02.000000Z"),
                parents: vec![],
                authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
                semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
            },
            ArtifactOccurrenceV1 {
                artifact_id: stable("artifact-proposal-001"),
                kind_id: stable("research_proposal_fixture"),
                content_digest: digest("research proposal fixture bytes"),
                information_cutoff: timestamp("2026-08-18T00:00:02.000000Z"),
                produced_at: timestamp("2026-08-18T00:00:03.000000Z"),
                parents: vec![artifact_ref(
                    "artifact-market-001",
                    "market atlas fixture bytes",
                )],
                authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
                semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
            },
        ],
        dag_digest: digest("placeholder DAG digest"),
    };
    value.dag_digest =
        digest_bytes(&canonical_bytes(&value.digest_material()).expect("DAG material"))
            .expect("DAG digest");
    value
}

fn ledger(dag: &ArtifactDagV1) -> FixtureDecisionLedgerV1 {
    let market = artifact_ref("artifact-market-001", "market atlas fixture bytes");
    let proposal = artifact_ref("artifact-proposal-001", "research proposal fixture bytes");
    let mut value = FixtureDecisionLedgerV1 {
        contract: stable(FIXTURE_DECISION_LEDGER_CONTRACT),
        program_id: stable("w6-program-fixture-001"),
        registration_digest: fixture().registration_digest,
        artifact_dag_digest: dag.dag_digest.clone(),
        decisions: vec![
            ArtifactDecisionV1 {
                decision_id: stable("decision-market-roundtrip-001"),
                artifact: market.clone(),
                predecessor_decision_id: None,
                decision: ArtifactDecisionKindV1::PromoteFixtureRoundtrip,
                decided_at: timestamp("2026-08-18T00:00:04.000000Z"),
                evidence: vec![market],
                reason: stable("deterministic_fixture_roundtrip_revalidated"),
                authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
                semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
            },
            ArtifactDecisionV1 {
                decision_id: stable("decision-proposal-park-001"),
                artifact: proposal.clone(),
                predecessor_decision_id: None,
                decision: ArtifactDecisionKindV1::Park,
                decided_at: timestamp("2026-08-18T00:00:05.000000Z"),
                evidence: vec![proposal],
                reason: stable("awaits_store_resolved_wave5_gates"),
                authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
                semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
            },
        ],
        ledger_digest: digest("placeholder ledger digest"),
    };
    value.ledger_digest =
        digest_bytes(&canonical_bytes(&value.digest_material()).expect("ledger material"))
            .expect("ledger digest");
    value
}

fn lifecycle_transition(
    ordinal: usize,
    from_state: Option<CampaignStateV1>,
    to_state: CampaignStateV1,
    frozen: Option<&ValueDigest>,
) -> CampaignTransitionV1 {
    CampaignTransitionV1 {
        transition_id: stable(&format!("campaign-transition-{ordinal:02}")),
        predecessor_transition_id: ordinal
            .checked_sub(1)
            .filter(|prior| *prior > 0)
            .map(|prior| stable(&format!("campaign-transition-{prior:02}"))),
        from_state,
        to_state,
        campaign_definition_digest: digest("campaign definition fixture bytes"),
        frozen_commitment_digest: frozen.cloned(),
        recorded_at: timestamp(&format!("2026-08-18T00:01:{ordinal:02}.000000Z")),
        reason: stable(&format!("fixture_transition_{ordinal:02}")),
        successor_campaign_id: (to_state == CampaignStateV1::ReviseAsNewCampaign)
            .then(|| stable("campaign-fixture-successor-002")),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    }
}

fn campaign_lifecycle() -> CampaignLifecycleV1 {
    let commitment = digest("frozen campaign commitment fixture bytes");
    let states = [
        CampaignStateV1::DraftExploratory,
        CampaignStateV1::Preregistered,
        CampaignStateV1::EnrollmentFrozen,
        CampaignStateV1::Running,
        CampaignStateV1::Sealed,
        CampaignStateV1::Censored,
        CampaignStateV1::Adjudicated,
        CampaignStateV1::Park,
    ];
    let transitions = states
        .iter()
        .enumerate()
        .map(|(index, state)| {
            let ordinal = index + 1;
            lifecycle_transition(
                ordinal,
                index.checked_sub(1).map(|prior| states[prior]),
                *state,
                (ordinal >= 3).then_some(&commitment),
            )
        })
        .collect();
    let mut value = CampaignLifecycleV1 {
        contract: stable(CAMPAIGN_LIFECYCLE_CONTRACT),
        program_id: stable("w6-program-fixture-001"),
        registration_digest: fixture().registration_digest,
        campaign_id: stable("campaign-fixture-001"),
        transitions,
        lifecycle_digest: digest("placeholder lifecycle digest"),
    };
    value.lifecycle_digest =
        digest_bytes(&canonical_bytes(&value.digest_material()).expect("lifecycle material"))
            .expect("lifecycle digest");
    value
}

#[test]
fn exact_fixture_roundtrips_at_unverified_ceiling() {
    let parsed = parse_program_registration_exact(FIXTURE).expect("valid exact fixture");
    assert_eq!(parsed.exact_bytes(), FIXTURE);
    assert_eq!(
        parsed.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(parsed.value().consumed_wave5_gates.len(), 0);
    assert_eq!(parsed.value().artifact_kinds.len(), 6);
    assert_eq!(
        parsed.value().artifact_kinds[0].schema_digest,
        digest_bytes(CAMPAIGN_SCHEMA).expect("campaign schema digest")
    );
    assert_eq!(
        parsed.value().artifact_kinds[1].schema_digest,
        digest_bytes(KNOWN_TRUTH_SCHEMA).expect("known-truth schema digest")
    );
    assert_eq!(
        parsed.value().artifact_kinds[2].schema_digest,
        digest_bytes(MARKET_SCHEMA).expect("market schema digest")
    );
    assert_eq!(
        parsed.value().artifact_kinds[3].schema_digest,
        digest_bytes(PROTOCOL_TRUTH_SCHEMA).expect("protocol-truth schema digest")
    );
    assert_eq!(
        parsed.value().artifact_kinds[4].schema_digest,
        digest_bytes(RESEARCH_SCHEMA).expect("research schema digest")
    );
    assert_eq!(
        parsed.value().artifact_kinds[5].schema_digest,
        digest_bytes(STRUCTURAL_TRUTH_SCHEMA).expect("structural-truth schema digest")
    );
    assert_eq!(parsed.value().budgets.provider_units, WireU64::new(0));
}

#[test]
fn unknown_and_noncanonical_json_refuse() {
    let mut document: serde_json::Value = serde_json::from_slice(FIXTURE).expect("json");
    document["durableReceipt"] = serde_json::json!({"commitSeq": "99"});
    let mut unknown = serde_json::to_vec(&document).expect("encode");
    unknown.push(b'\n');
    assert!(matches!(
        parse_program_registration_exact(&unknown),
        Err(RegistryError::Json(_))
    ));

    let pretty = serde_json::to_vec_pretty(&fixture()).expect("pretty");
    assert!(matches!(
        parse_program_registration_exact(&pretty),
        Err(RegistryError::NonCanonical)
    ));
}

#[test]
fn digest_and_collection_substitution_refuse() {
    let mut changed = fixture();
    changed.program_family_id = StableString::new("substituted-family").expect("stable");
    let bytes = canonical_bytes(&changed).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::DigestMismatch)
    ));

    let mut reordered = fixture();
    reordered.artifact_kinds.reverse();
    reclose(&mut reordered);
    let bytes = canonical_bytes(&reordered).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::Collection("artifactKinds"))
    ));
}

#[test]
fn provider_budget_and_missing_prohibition_refuse_even_when_reclosed() {
    let mut provider = fixture();
    provider.budgets.provider_units = WireU64::new(1);
    reclose(&mut provider);
    let bytes = canonical_bytes(&provider).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::Policy("budget"))
    ));

    let mut widened = fixture();
    widened
        .prohibited_side_effects
        .retain(|value| value.as_str() != "asset_reservation");
    reclose(&mut widened);
    let bytes = canonical_bytes(&widened).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::MissingProhibition("asset_reservation"))
    ));
}

#[test]
fn digest_wire_form_is_strict_lowercase_sha256() {
    let mut malformed = fixture();
    malformed.source_tree_digest =
        ValueDigest::new(format!("sha256:{}", "A".repeat(64))).expect("stable malformed digest");
    reclose(&mut malformed);
    let bytes = canonical_bytes(&malformed).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::DigestFormat {
            field: "sourceTreeDigest"
        })
    ));
}

#[test]
fn exact_artifact_dag_closes_topology_and_time() {
    let registration = parse_program_registration_exact(FIXTURE).expect("registration");
    let value = dag();
    let bytes = canonical_bytes(&value).expect("DAG bytes");
    let parsed = parse_artifact_dag_exact(&bytes, &registration).expect("exact DAG");
    assert_eq!(parsed.value(), &value);
    assert_eq!(
        parsed.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );

    let mut future_parent = dag();
    future_parent.artifacts[0].produced_at = timestamp("2026-08-18T00:00:04.000000Z");
    future_parent.dag_digest =
        digest_bytes(&canonical_bytes(&future_parent.digest_material()).expect("material"))
            .expect("digest");
    let bytes = canonical_bytes(&future_parent).expect("bytes");
    assert!(matches!(
        parse_artifact_dag_exact(&bytes, &registration),
        Err(RegistryError::Dag("parent closure"))
    ));
}

#[test]
fn artifact_identity_content_and_kind_substitution_refuse() {
    let registration = parse_program_registration_exact(FIXTURE).expect("registration");
    let mut duplicate = dag();
    duplicate.artifacts[1].content_digest = duplicate.artifacts[0].content_digest.clone();
    duplicate.dag_digest =
        digest_bytes(&canonical_bytes(&duplicate.digest_material()).expect("material"))
            .expect("digest");
    assert!(matches!(
        parse_artifact_dag_exact(&canonical_bytes(&duplicate).expect("bytes"), &registration),
        Err(RegistryError::Dag("artifact occurrence"))
    ));

    let mut unknown_kind = dag();
    unknown_kind.artifacts[0].kind_id = stable("unregistered_result");
    unknown_kind.dag_digest =
        digest_bytes(&canonical_bytes(&unknown_kind.digest_material()).expect("material"))
            .expect("digest");
    assert!(matches!(
        parse_artifact_dag_exact(
            &canonical_bytes(&unknown_kind).expect("bytes"),
            &registration
        ),
        Err(RegistryError::Dag("artifact occurrence"))
    ));
}

#[test]
fn claim_grammar_is_exactly_rung_and_kind_bound() {
    let registration = fixture();
    let claim = ClaimLanguageV1 {
        claim_id: stable("claim-market-fixture-001"),
        artifact_id: stable("artifact-market-001"),
        artifact_kind_id: stable("market_atlas_fixture"),
        statement: stable("fixture_point_in_time_description"),
        rung: ClaimRungV1::H2Descriptive,
        verb: ClaimVerbV1::ObservationPolicyScopedDescription,
        causality: ClaimCausalityV1::NotClaimed,
        identity_meaning: ClaimIdentityMeaningV1::NotClaimed,
        economic_meaning: ClaimEconomicMeaningV1::NoEconomicAuthorityOrProfitClaim,
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    };
    let validated = validate_claim_language(&registration, claim.clone()).expect("claim grammar");
    assert_eq!(validated.value(), &claim);

    let mut causal_laundering = claim.clone();
    causal_laundering.verb = ClaimVerbV1::CalibratedConditionalEstimate;
    assert!(matches!(
        validate_claim_language(&registration, causal_laundering),
        Err(RegistryError::ClaimLanguage)
    ));

    let mut arbitrary_wording = claim;
    arbitrary_wording.statement = stable("profitable_market_pressure");
    assert!(matches!(
        validate_claim_language(&registration, arbitrary_wording),
        Err(RegistryError::ClaimLanguage)
    ));
}

#[test]
fn fixture_decisions_are_append_only_and_never_store_promotion() {
    let registration = parse_program_registration_exact(FIXTURE).expect("registration");
    let dag_value = dag();
    let dag_bytes = canonical_bytes(&dag_value).expect("DAG bytes");
    let parsed_dag = parse_artifact_dag_exact(&dag_bytes, &registration).expect("DAG");
    let value = ledger(&dag_value);
    let bytes = canonical_bytes(&value).expect("ledger bytes");
    let parsed =
        parse_decision_ledger_exact(&bytes, &registration, &parsed_dag).expect("ledger closure");
    assert_eq!(parsed.value(), &value);

    let mut branched = ledger(&dag_value);
    branched.decisions.push(ArtifactDecisionV1 {
        decision_id: stable("decision-market-branch-002"),
        artifact: artifact_ref("artifact-market-001", "market atlas fixture bytes"),
        predecessor_decision_id: None,
        decision: ArtifactDecisionKindV1::Park,
        decided_at: timestamp("2026-08-18T00:00:06.000000Z"),
        evidence: vec![artifact_ref(
            "artifact-market-001",
            "market atlas fixture bytes",
        )],
        reason: stable("branch_attempt"),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    });
    branched.ledger_digest =
        digest_bytes(&canonical_bytes(&branched.digest_material()).expect("material"))
            .expect("digest");
    assert!(matches!(
        parse_decision_ledger_exact(
            &canonical_bytes(&branched).expect("bytes"),
            &registration,
            &parsed_dag
        ),
        Err(RegistryError::Decision("branch or clock rollback"))
    ));
}

#[test]
fn campaign_lifecycle_closes_censoring_and_parking_without_promotion() {
    let registration = parse_program_registration_exact(FIXTURE).expect("registration");
    let value = campaign_lifecycle();
    let bytes = canonical_bytes(&value).expect("lifecycle bytes");
    let parsed = parse_campaign_lifecycle_exact(&bytes, &registration).expect("lifecycle");
    assert_eq!(parsed.value(), &value);
    assert_eq!(
        parsed.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(
        parsed
            .value()
            .transitions
            .last()
            .map(|value| value.to_state),
        Some(CampaignStateV1::Park)
    );
}

#[test]
fn campaign_skip_branch_and_commitment_mutation_refuse() {
    let registration = parse_program_registration_exact(FIXTURE).expect("registration");

    let mut skipped = campaign_lifecycle();
    skipped.transitions[3].from_state = Some(CampaignStateV1::Preregistered);
    skipped.lifecycle_digest =
        digest_bytes(&canonical_bytes(&skipped.digest_material()).expect("material"))
            .expect("digest");
    assert!(matches!(
        parse_campaign_lifecycle_exact(&canonical_bytes(&skipped).expect("bytes"), &registration),
        Err(RegistryError::Campaign("transition order"))
    ));

    let mut branched = campaign_lifecycle();
    branched.transitions[5].predecessor_transition_id = Some(stable("campaign-transition-03"));
    branched.lifecycle_digest =
        digest_bytes(&canonical_bytes(&branched.digest_material()).expect("material"))
            .expect("digest");
    assert!(matches!(
        parse_campaign_lifecycle_exact(&canonical_bytes(&branched).expect("bytes"), &registration),
        Err(RegistryError::Campaign("transition order"))
    ));

    let mut changed = campaign_lifecycle();
    changed.transitions[6].frozen_commitment_digest = Some(digest("changed frozen commitment"));
    changed.lifecycle_digest =
        digest_bytes(&canonical_bytes(&changed.digest_material()).expect("material"))
            .expect("digest");
    assert!(matches!(
        parse_campaign_lifecycle_exact(&canonical_bytes(&changed).expect("bytes"), &registration),
        Err(RegistryError::Campaign("frozen commitment mutation"))
    ));
}

#[test]
fn exact_python_evaluation_artifacts_cross_parse_without_promotion() {
    let cases = [
        (
            "known_truth_evaluation_fixture",
            "joshi.analysis.wave6-known-truth/v1",
            KNOWN_TRUTH_EVALUATION,
            8,
            "sha256:57c0d7ff101b9b14e8be2976223a194bf851f1e6e064ae7f7fe7674e8ca0e021",
        ),
        (
            "protocol_known_truth_evaluation_fixture",
            "joshi.analysis.wave6-protocol-known-truth/v1",
            PROTOCOL_TRUTH_EVALUATION,
            7,
            "sha256:94b44aea3ab6cfddce2ee3b1b15e570fd0e26f6e56e4ee2ef129aea9f4552fb4",
        ),
        (
            "structural_known_truth_evaluation_fixture",
            "joshi.analysis.wave6-structural-known-truth/v1",
            STRUCTURAL_TRUTH_EVALUATION,
            3,
            "sha256:f5c5f9d41a8dd686425a145b77c7b90f27a9154f07a607d562fa1596f3e71705",
        ),
    ];
    for (kind, schema, bytes, count, semantic_digest) in cases {
        let parsed = parse_evaluation_artifact_exact(&stable(kind), &stable(schema), bytes)
            .unwrap_or_else(|error| panic!("parse {kind}: {error}"));
        assert_eq!(parsed.exact_bytes(), bytes);
        assert_eq!(
            parsed.content_digest(),
            &digest_bytes(bytes).expect("content digest")
        );
        assert_eq!(parsed.value().result_count(), count);
        assert_eq!(parsed.evaluation_digest().as_str(), semantic_digest);
        assert_eq!(
            parsed.semantic_ceiling(),
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
    }
}

#[test]
fn evaluation_mapping_canonicality_denominator_and_self_digest_substitution_refuse() {
    assert!(matches!(
        parse_evaluation_artifact_exact(
            &stable("known_truth_evaluation_fixture"),
            &stable("joshi.analysis.wave6-protocol-known-truth/v1"),
            KNOWN_TRUTH_EVALUATION,
        ),
        Err(RegistryError::Evaluation(
            "unsupported registered evaluation kind/schema mapping"
        ))
    ));

    let mut noncanonical = KNOWN_TRUTH_EVALUATION.to_vec();
    noncanonical.insert(1, b' ');
    assert!(matches!(
        parse_evaluation_artifact_exact(
            &stable("known_truth_evaluation_fixture"),
            &stable("joshi.analysis.wave6-known-truth/v1"),
            &noncanonical,
        ),
        Err(RegistryError::NonCanonical)
    ));

    let mut changed: serde_json::Value =
        serde_json::from_slice(KNOWN_TRUTH_EVALUATION).expect("evaluation JSON");
    changed["evaluation_digest"] = serde_json::Value::String(format!("sha256:{}", "0".repeat(64)));
    let mut changed_bytes = serde_json::to_vec(&changed).expect("changed evaluation");
    changed_bytes.push(b'\n');
    assert!(matches!(
        parse_evaluation_artifact_exact(
            &stable("known_truth_evaluation_fixture"),
            &stable("joshi.analysis.wave6-known-truth/v1"),
            &changed_bytes,
        ),
        Err(RegistryError::Evaluation("semantic self-digest"))
    ));

    changed["passed_case_ids"] = serde_json::Value::Array(vec![]);
    changed["result_digests"] = serde_json::Value::Array(vec![]);
    let mut empty_bytes = serde_json::to_vec(&changed).expect("empty evaluation");
    empty_bytes.push(b'\n');
    assert!(matches!(
        parse_evaluation_artifact_exact(
            &stable("known_truth_evaluation_fixture"),
            &stable("joshi.analysis.wave6-known-truth/v1"),
            &empty_bytes,
        ),
        Err(RegistryError::Evaluation("exact result denominator"))
    ));
}
