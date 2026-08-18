use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_wave6_registry::{
    ProgramAuthorityV1, SemanticCeilingV1, ValidatedProgramRegistration,
    parse_program_registration_exact,
};

use crate::{
    ALL_CENSORING_DISPOSITIONS, AssignmentMechanismV1, CAMPAIGN_REGISTRATION_CONTRACT,
    CampaignArmV1, CampaignBudgetsV1, CampaignError, CampaignEstimandV1, CampaignMetricV1,
    CampaignRegistrationV1, CampaignStopRulesV1, CampaignUniverseV1, EnrollmentDispositionV1,
    FROZEN_ENROLLMENT_CONTRACT, FrozenEnrollmentV1, canonical_bytes, digest_bytes,
    parse_campaign_registration_exact, parse_frozen_enrollment_exact,
};

const PROGRAM_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/wave6/program_registration_v1.json");

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

fn digest(value: &str) -> ValueDigest {
    digest_bytes(value.as_bytes()).expect("digest")
}

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().expect("timestamp")
}

fn program() -> ValidatedProgramRegistration {
    parse_program_registration_exact(PROGRAM_FIXTURE).expect("checked N00 fixture")
}

fn universe() -> CampaignUniverseV1 {
    let mut universe = CampaignUniverseV1 {
        universe_id: stable("universe-fixture-001"),
        subject_ids: vec![stable("mint:a"), stable("mint:b"), stable("mint:c")],
        inclusion_rule: stable("exact_checked_fixture_subject_membership"),
        exclusion_reason_ids: vec![stable("coverage_gap"), stable("not_eligible")],
        universe_digest: digest("placeholder universe digest"),
    };
    universe.universe_digest = universe.computed_digest().expect("universe digest");
    universe
}

fn registration() -> CampaignRegistrationV1 {
    let program = program();
    let safety = digest("same frozen safety content");
    let mut registration = CampaignRegistrationV1 {
        contract: stable(CAMPAIGN_REGISTRATION_CONTRACT),
        program_id: program.value().program_id.clone(),
        program_registration_digest: program.value().registration_digest.clone(),
        campaign_id: stable("campaign-fixture-001"),
        campaign_family_id: stable("signed-flow-identification-probe"),
        semantic_version: stable("1.0.0"),
        object: stable("exact_signed_flow_candidate"),
        estimand: CampaignEstimandV1 {
            estimand_id: stable("signed-flow-exact-atom-mean"),
            numerator: stable("sum_exact_signed_flow_atoms"),
            denominator: stable("frozen_included_subject_count"),
            outcome: stable("exact_signed_flow_atoms"),
            unit: stable("native_atoms_per_subject"),
        },
        universe: universe(),
        assignment_mechanism: AssignmentMechanismV1::DeterministicFixtureOnly,
        arms: vec![
            CampaignArmV1 {
                arm_id: stable("arm:control"),
                probability_ppm: WireU64::new(500_000),
                arm_digest: digest("control arm exact content"),
                invariant_safety_digest: safety.clone(),
            },
            CampaignArmV1 {
                arm_id: stable("arm:probe"),
                probability_ppm: WireU64::new(500_000),
                arm_digest: digest("probe arm exact content"),
                invariant_safety_digest: safety,
            },
        ],
        metrics: vec![
            CampaignMetricV1 {
                metric_id: stable("metric:coverage"),
                numerator: stable("covered_subject_count"),
                denominator: stable("frozen_included_subject_count"),
                unit: stable("exact_ratio"),
                baseline_id: stable("registered_coverage_baseline"),
                multiplicity_family_id: stable("apparatus_metrics"),
            },
            CampaignMetricV1 {
                metric_id: stable("metric:signed-flow"),
                numerator: stable("sum_exact_signed_flow_atoms"),
                denominator: stable("frozen_included_subject_count"),
                unit: stable("native_atoms_per_subject"),
                baseline_id: stable("zero_signed_flow_baseline"),
                multiplicity_family_id: stable("descriptive_metrics"),
            },
        ],
        inference_method: stable("descriptive_fixture_exact_only"),
        censoring_dispositions: ALL_CENSORING_DISPOSITIONS.to_vec(),
        correction_contract: stable("append_only_new_campaign_registration"),
        contamination_contract: stable("record_and_censor_cross_arm_contamination"),
        budgets: CampaignBudgetsV1 {
            compute_units: WireU64::new(10_000),
            read_units: WireU64::new(1_000),
            attention_units: WireU64::new(10),
            provider_units: WireU64::new(0),
            external_mutation_units: WireU64::new(0),
            max_subjects: WireU64::new(3),
        },
        stop_rules: CampaignStopRulesV1 {
            apparatus_stop: stable("any_fixture_digest_or_cutoff_mismatch"),
            scientific_stop: stable("any_registered_adversary_not_rejected"),
            operator_stop: stable("any_nonzero_external_or_provider_action"),
        },
        registered_at: timestamp("2026-08-18T01:00:00.000000Z"),
        enrollment_cutoff: timestamp("2026-08-18T01:01:00.000000Z"),
        input_knowledge_cutoff: timestamp("2026-08-18T01:02:00.000000Z"),
        seal_deadline: timestamp("2026-08-18T01:03:00.000000Z"),
        maturity_deadline: timestamp("2026-08-18T01:04:00.000000Z"),
        outcome_knowledge_cutoff: timestamp("2026-08-18T01:05:00.000000Z"),
        adjudication_deadline: timestamp("2026-08-18T01:06:00.000000Z"),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
        campaign_registration_digest: digest("placeholder campaign registration digest"),
    };
    reclose_registration(&mut registration);
    registration
}

fn reclose_registration(registration: &mut CampaignRegistrationV1) {
    registration.campaign_registration_digest = digest_bytes(
        &canonical_bytes(&registration.digest_material()).expect("registration material"),
    )
    .expect("registration digest");
}

fn parsed_registration() -> crate::UnverifiedSemantic<CampaignRegistrationV1> {
    let registration = registration();
    parse_campaign_registration_exact(
        &canonical_bytes(&registration).expect("registration bytes"),
        &program(),
    )
    .expect("valid registration")
}

fn enrollment(registration: &CampaignRegistrationV1) -> FrozenEnrollmentV1 {
    let mut enrollment = FrozenEnrollmentV1 {
        contract: stable(FROZEN_ENROLLMENT_CONTRACT),
        campaign_id: registration.campaign_id.clone(),
        campaign_registration_digest: registration.campaign_registration_digest.clone(),
        enrollment_id: stable("enrollment-fixture-001"),
        dispositions: vec![
            EnrollmentDispositionV1 {
                subject_id: stable("mint:a"),
                included: true,
                exclusion_reason_id: None,
            },
            EnrollmentDispositionV1 {
                subject_id: stable("mint:b"),
                included: false,
                exclusion_reason_id: Some(stable("coverage_gap")),
            },
            EnrollmentDispositionV1 {
                subject_id: stable("mint:c"),
                included: true,
                exclusion_reason_id: None,
            },
        ],
        frozen_at: timestamp("2026-08-18T01:00:30.000000Z"),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
        enrollment_digest: digest("placeholder enrollment digest"),
    };
    reclose_enrollment(&mut enrollment);
    enrollment
}

fn reclose_enrollment(enrollment: &mut FrozenEnrollmentV1) {
    enrollment.enrollment_digest =
        digest_bytes(&canonical_bytes(&enrollment.digest_material()).expect("enrollment material"))
            .expect("enrollment digest");
}

#[test]
fn exact_registration_and_enrollment_roundtrip_at_fixture_ceiling() {
    let program = program();
    let registration = registration();
    let registration_bytes = canonical_bytes(&registration).expect("registration bytes");
    let parsed =
        parse_campaign_registration_exact(&registration_bytes, &program).expect("registration");
    assert_eq!(parsed.exact_bytes(), registration_bytes);
    assert_eq!(
        parsed.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );

    let enrollment = enrollment(parsed.value());
    let enrollment_bytes = canonical_bytes(&enrollment).expect("enrollment bytes");
    let parsed_enrollment =
        parse_frozen_enrollment_exact(&enrollment_bytes, &parsed).expect("enrollment");
    assert_eq!(parsed_enrollment.exact_bytes(), enrollment_bytes);
    assert_eq!(
        parsed_enrollment.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(
        parsed_enrollment
            .value()
            .dispositions
            .iter()
            .filter(|row| row.included)
            .count(),
        2
    );
}

#[test]
fn arm_probability_safety_content_and_order_substitution_refuse() {
    let program = program();

    let mut probability = registration();
    probability.arms[0].probability_ppm = WireU64::new(499_999);
    reclose_registration(&mut probability);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&probability).expect("bytes"), &program),
        Err(CampaignError::Registration("allocation probability"))
    ));

    let mut safety = registration();
    safety.arms[1].invariant_safety_digest = digest("substituted safety");
    reclose_registration(&mut safety);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&safety).expect("bytes"), &program),
        Err(CampaignError::Registration("arm safety/content"))
    ));

    let mut duplicate_content = registration();
    duplicate_content.arms[1].arm_digest = duplicate_content.arms[0].arm_digest.clone();
    reclose_registration(&mut duplicate_content);
    assert!(matches!(
        parse_campaign_registration_exact(
            &canonical_bytes(&duplicate_content).expect("bytes"),
            &program
        ),
        Err(CampaignError::Registration("arm safety/content"))
    ));

    let mut reordered = registration();
    reordered.arms.reverse();
    reclose_registration(&mut reordered);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&reordered).expect("bytes"), &program),
        Err(CampaignError::Registration("arms or metrics"))
    ));
}

#[test]
fn authority_censoring_budget_and_chronology_widening_refuse() {
    let program = program();

    let mut provider = registration();
    provider.budgets.provider_units = WireU64::new(1);
    reclose_registration(&mut provider);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&provider).expect("bytes"), &program),
        Err(CampaignError::Registration("authority or budget boundary"))
    ));

    let mut censoring = registration();
    censoring.censoring_dispositions.pop();
    reclose_registration(&mut censoring);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&censoring).expect("bytes"), &program),
        Err(CampaignError::Registration("authority or budget boundary"))
    ));

    let mut chronology = registration();
    chronology.seal_deadline = chronology.input_knowledge_cutoff;
    reclose_registration(&mut chronology);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&chronology).expect("bytes"), &program),
        Err(CampaignError::Registration("deadline chronology"))
    ));

    let mut capacity = registration();
    capacity.budgets.max_subjects = WireU64::new(2);
    reclose_registration(&mut capacity);
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&capacity).expect("bytes"), &program),
        Err(CampaignError::Registration("authority or budget boundary"))
    ));
}

#[test]
fn enrollment_is_exact_complete_registered_and_timely() {
    let registration = parsed_registration();

    let mut missing = enrollment(registration.value());
    missing.dispositions.pop();
    reclose_enrollment(&mut missing);
    assert!(matches!(
        parse_frozen_enrollment_exact(&canonical_bytes(&missing).expect("bytes"), &registration),
        Err(CampaignError::Enrollment("registration binding"))
    ));

    let mut reordered = enrollment(registration.value());
    reordered.dispositions.swap(0, 1);
    reclose_enrollment(&mut reordered);
    assert!(matches!(
        parse_frozen_enrollment_exact(&canonical_bytes(&reordered).expect("bytes"), &registration),
        Err(CampaignError::Enrollment("subject disposition"))
    ));

    let mut invented_reason = enrollment(registration.value());
    invented_reason.dispositions[1].exclusion_reason_id = Some(stable("invented_reason"));
    reclose_enrollment(&mut invented_reason);
    assert!(matches!(
        parse_frozen_enrollment_exact(
            &canonical_bytes(&invented_reason).expect("bytes"),
            &registration
        ),
        Err(CampaignError::Enrollment("subject disposition"))
    ));

    let mut all_excluded = enrollment(registration.value());
    for disposition in &mut all_excluded.dispositions {
        disposition.included = false;
        disposition.exclusion_reason_id = Some(stable("coverage_gap"));
    }
    reclose_enrollment(&mut all_excluded);
    assert!(matches!(
        parse_frozen_enrollment_exact(
            &canonical_bytes(&all_excluded).expect("bytes"),
            &registration
        ),
        Err(CampaignError::Enrollment("empty enrollment"))
    ));

    let mut late = enrollment(registration.value());
    late.frozen_at = timestamp("2026-08-18T01:01:00.000001Z");
    reclose_enrollment(&mut late);
    assert!(matches!(
        parse_frozen_enrollment_exact(&canonical_bytes(&late).expect("bytes"), &registration),
        Err(CampaignError::Enrollment("registration binding"))
    ));
}

#[test]
fn exact_parsers_reject_unknown_noncanonical_and_stale_digest_bytes() {
    let program = program();
    let mut stale = registration();
    stale.object = stable("changed_without_reclosing");
    assert!(matches!(
        parse_campaign_registration_exact(&canonical_bytes(&stale).expect("bytes"), &program),
        Err(CampaignError::Digest("campaignRegistrationDigest"))
    ));

    let mut document = serde_json::to_value(registration()).expect("json");
    document["durableReceipt"] = serde_json::json!({"commitSeq": "99"});
    let mut unknown = serde_json::to_vec(&document).expect("bytes");
    unknown.push(b'\n');
    assert!(matches!(
        parse_campaign_registration_exact(&unknown, &program),
        Err(CampaignError::Json(_))
    ));

    let pretty = serde_json::to_vec_pretty(&registration()).expect("pretty");
    assert!(matches!(
        parse_campaign_registration_exact(&pretty, &program),
        Err(CampaignError::NonCanonical)
    ));
}
