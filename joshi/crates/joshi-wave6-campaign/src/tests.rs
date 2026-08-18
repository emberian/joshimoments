use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_wave6_registry::{
    ProgramAuthorityV1, SemanticCeilingV1, ValidatedProgramRegistration,
    Wave6ProgramRegistrationV1, canonical_bytes as registry_canonical_bytes,
    digest_bytes as registry_digest_bytes, parse_program_registration_exact,
};

use crate::{
    ALL_CENSORING_DISPOSITIONS, AssignmentMechanismV1, CAMPAIGN_ADJUDICATION_CONTRACT,
    CAMPAIGN_ASSIGNMENT_CONTRACT, CAMPAIGN_REGISTRATION_CONTRACT, CAMPAIGN_SEAL_CONTRACT,
    CampaignAdjudicationV1, CampaignArmV1, CampaignAssignmentRowV1, CampaignAssignmentV1,
    CampaignBudgetsV1, CampaignError, CampaignEstimandV1, CampaignEvidenceRefV1, CampaignMetricV1,
    CampaignOutcomeV1, CampaignRegistrationV1, CampaignSealV1, CampaignStopRulesV1,
    CampaignUniverseV1, CensoringDispositionV1, EnrollmentDispositionV1,
    FROZEN_ENROLLMENT_CONTRACT, FixtureAdjudicationClaimV1, FrozenEnrollmentV1, canonical_bytes,
    digest_bytes, parse_campaign_adjudication_exact, parse_campaign_assignment_exact,
    parse_campaign_registration_exact, parse_campaign_seal_exact, parse_frozen_enrollment_exact,
};

const PROGRAM_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
const CAMPAIGN_REGISTRATION_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/registration_v1.json");
const ENROLLMENT_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/enrollment_v1.json");
const ASSIGNMENT_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/assignment_v1.json");
const SEAL_FIXTURE: &[u8] = include_bytes!("../../../fixtures/wave6/campaign/seal_v1.json");
const ADJUDICATION_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/adjudication_v1.json");

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

fn program_with_campaign_claim(permitted_claim: &str) -> ValidatedProgramRegistration {
    let mut value: Wave6ProgramRegistrationV1 =
        serde_json::from_slice(PROGRAM_FIXTURE).expect("program fixture");
    value.artifact_kinds[0].permitted_claim = stable(permitted_claim);
    value.registration_digest = registry_digest_bytes(
        &registry_canonical_bytes(&value.digest_material()).expect("program material"),
    )
    .expect("program digest");
    parse_program_registration_exact(&registry_canonical_bytes(&value).expect("program bytes"))
        .expect("valid altered N00 contract")
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
            value_contract: stable("canonical_signed_i128_decimal"),
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

fn parsed_enrollment() -> (
    crate::UnverifiedSemantic<CampaignRegistrationV1>,
    crate::UnverifiedSemantic<FrozenEnrollmentV1>,
) {
    let registration = parsed_registration();
    let enrollment = enrollment(registration.value());
    let parsed_enrollment = parse_frozen_enrollment_exact(
        &canonical_bytes(&enrollment).expect("enrollment bytes"),
        &registration,
    )
    .expect("valid enrollment");
    (registration, parsed_enrollment)
}

fn assignment(
    registration: &CampaignRegistrationV1,
    enrollment: &FrozenEnrollmentV1,
) -> CampaignAssignmentV1 {
    let mut assignment = CampaignAssignmentV1 {
        contract: stable(CAMPAIGN_ASSIGNMENT_CONTRACT),
        campaign_id: registration.campaign_id.clone(),
        campaign_registration_digest: registration.campaign_registration_digest.clone(),
        enrollment_id: enrollment.enrollment_id.clone(),
        enrollment_digest: enrollment.enrollment_digest.clone(),
        assignment_id: stable("assignment-fixture-001"),
        assignment_basis_digest: digest("deterministic fixture assignment basis"),
        assignments: vec![
            CampaignAssignmentRowV1 {
                subject_id: stable("mint:a"),
                arm_id: stable("arm:control"),
                probability_ppm: WireU64::new(500_000),
            },
            CampaignAssignmentRowV1 {
                subject_id: stable("mint:c"),
                arm_id: stable("arm:probe"),
                probability_ppm: WireU64::new(500_000),
            },
        ],
        assigned_at: timestamp("2026-08-18T01:01:30.000000Z"),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
        assignment_digest: digest("placeholder assignment digest"),
    };
    reclose_assignment(&mut assignment);
    assignment
}

fn reclose_assignment(assignment: &mut CampaignAssignmentV1) {
    assignment.assignment_digest =
        digest_bytes(&canonical_bytes(&assignment.digest_material()).expect("assignment material"))
            .expect("assignment digest");
}

fn parsed_assignment(
    registration: &crate::UnverifiedSemantic<CampaignRegistrationV1>,
    enrollment: &crate::UnverifiedSemantic<FrozenEnrollmentV1>,
) -> crate::UnverifiedSemantic<CampaignAssignmentV1> {
    let assignment = assignment(registration.value(), enrollment.value());
    parse_campaign_assignment_exact(
        &canonical_bytes(&assignment).expect("assignment bytes"),
        registration,
        enrollment,
    )
    .expect("valid assignment")
}

fn evidence(
    artifact_id: &str,
    content: &str,
    available_at: &str,
    alleged_commit_seq: u64,
) -> CampaignEvidenceRefV1 {
    CampaignEvidenceRefV1 {
        artifact_id: stable(artifact_id),
        artifact_contract: stable("joshi.wave6.fixture-evidence.v1"),
        content_digest: digest(content),
        available_at: timestamp(available_at),
        alleged_commit_seq: WireU64::new(alleged_commit_seq),
    }
}

fn seal(
    registration: &CampaignRegistrationV1,
    enrollment: &FrozenEnrollmentV1,
    assignment: &CampaignAssignmentV1,
) -> CampaignSealV1 {
    let mut seal = CampaignSealV1 {
        contract: stable(CAMPAIGN_SEAL_CONTRACT),
        campaign_id: registration.campaign_id.clone(),
        campaign_registration_digest: registration.campaign_registration_digest.clone(),
        enrollment_id: enrollment.enrollment_id.clone(),
        enrollment_digest: enrollment.enrollment_digest.clone(),
        assignment_id: assignment.assignment_id.clone(),
        assignment_digest: assignment.assignment_digest.clone(),
        seal_id: stable("seal-fixture-001"),
        input_knowledge_cutoff: registration.input_knowledge_cutoff,
        as_of_commit_seq: WireU64::new(11),
        evidence: vec![
            evidence(
                "evidence:input-a",
                "input evidence A",
                "2026-08-18T01:01:40.000000Z",
                10,
            ),
            evidence(
                "evidence:input-b",
                "input evidence B",
                "2026-08-18T01:01:50.000000Z",
                11,
            ),
        ],
        sealed_at: timestamp("2026-08-18T01:02:30.000000Z"),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
        seal_digest: digest("placeholder seal digest"),
    };
    reclose_seal(&mut seal);
    seal
}

fn reclose_seal(seal: &mut CampaignSealV1) {
    seal.seal_digest =
        digest_bytes(&canonical_bytes(&seal.digest_material()).expect("seal material"))
            .expect("seal digest");
}

fn parsed_seal(
    registration: &crate::UnverifiedSemantic<CampaignRegistrationV1>,
    enrollment: &crate::UnverifiedSemantic<FrozenEnrollmentV1>,
    assignment: &crate::UnverifiedSemantic<CampaignAssignmentV1>,
) -> crate::UnverifiedSemantic<CampaignSealV1> {
    let seal = seal(registration.value(), enrollment.value(), assignment.value());
    parse_campaign_seal_exact(
        &canonical_bytes(&seal).expect("seal bytes"),
        registration,
        enrollment,
        assignment,
    )
    .expect("valid seal")
}

fn adjudication(
    registration: &CampaignRegistrationV1,
    enrollment: &FrozenEnrollmentV1,
    seal: &CampaignSealV1,
) -> CampaignAdjudicationV1 {
    let mut adjudication = CampaignAdjudicationV1 {
        contract: stable(CAMPAIGN_ADJUDICATION_CONTRACT),
        campaign_id: registration.campaign_id.clone(),
        campaign_registration_digest: registration.campaign_registration_digest.clone(),
        enrollment_id: enrollment.enrollment_id.clone(),
        enrollment_digest: enrollment.enrollment_digest.clone(),
        seal_id: seal.seal_id.clone(),
        seal_digest: seal.seal_digest.clone(),
        adjudication_id: stable("adjudication-fixture-001"),
        outcome_knowledge_cutoff: registration.outcome_knowledge_cutoff,
        as_of_commit_seq: WireU64::new(21),
        outcomes: vec![
            CampaignOutcomeV1 {
                subject_id: stable("mint:a"),
                disposition: CensoringDispositionV1::ResolvedObserved,
                observed_value: Some(stable("-25")),
                observed_unit: Some(registration.estimand.unit.clone()),
                evidence: vec![evidence(
                    "evidence:outcome-a",
                    "outcome evidence A",
                    "2026-08-18T01:04:20.000000Z",
                    20,
                )],
                gap_ids: vec![],
                known_at: timestamp("2026-08-18T01:04:30.000000Z"),
            },
            CampaignOutcomeV1 {
                subject_id: stable("mint:c"),
                disposition: CensoringDispositionV1::SourceLossCensored,
                observed_value: None,
                observed_unit: None,
                evidence: vec![],
                gap_ids: vec![stable("gap:source-loss-c")],
                known_at: timestamp("2026-08-18T01:05:00.000000Z"),
            },
        ],
        claim: FixtureAdjudicationClaimV1::DescriptiveFixtureDispositionOnly,
        adjudicated_at: timestamp("2026-08-18T01:05:30.000000Z"),
        authority: ProgramAuthorityV1::ReadRecordReplayProposeShadowOnly,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
        adjudication_digest: digest("placeholder adjudication digest"),
    };
    reclose_adjudication(&mut adjudication);
    adjudication
}

fn reclose_adjudication(adjudication: &mut CampaignAdjudicationV1) {
    adjudication.adjudication_digest = digest_bytes(
        &canonical_bytes(&adjudication.digest_material()).expect("adjudication material"),
    )
    .expect("adjudication digest");
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
fn checked_campaign_chain_exactly_matches_the_fixture_builders() {
    let program = program();
    let built_registration = registration();
    assert_eq!(
        canonical_bytes(&built_registration).expect("registration bytes"),
        CAMPAIGN_REGISTRATION_FIXTURE
    );
    let parsed_registration =
        parse_campaign_registration_exact(CAMPAIGN_REGISTRATION_FIXTURE, &program)
            .expect("checked registration");
    let built_enrollment = enrollment(parsed_registration.value());
    assert_eq!(
        canonical_bytes(&built_enrollment).expect("enrollment bytes"),
        ENROLLMENT_FIXTURE
    );
    let parsed_enrollment = parse_frozen_enrollment_exact(ENROLLMENT_FIXTURE, &parsed_registration)
        .expect("checked enrollment");
    let built_assignment = assignment(parsed_registration.value(), parsed_enrollment.value());
    assert_eq!(
        canonical_bytes(&built_assignment).expect("assignment bytes"),
        ASSIGNMENT_FIXTURE
    );
    let parsed_assignment = parse_campaign_assignment_exact(
        ASSIGNMENT_FIXTURE,
        &parsed_registration,
        &parsed_enrollment,
    )
    .expect("checked assignment");
    let built_seal = seal(
        parsed_registration.value(),
        parsed_enrollment.value(),
        parsed_assignment.value(),
    );
    assert_eq!(
        canonical_bytes(&built_seal).expect("seal bytes"),
        SEAL_FIXTURE
    );
    let parsed_seal = parse_campaign_seal_exact(
        SEAL_FIXTURE,
        &parsed_registration,
        &parsed_enrollment,
        &parsed_assignment,
    )
    .expect("checked seal");
    let built_adjudication = adjudication(
        parsed_registration.value(),
        parsed_enrollment.value(),
        parsed_seal.value(),
    );
    assert_eq!(
        canonical_bytes(&built_adjudication).expect("adjudication bytes"),
        ADJUDICATION_FIXTURE
    );
    let parsed_adjudication = parse_campaign_adjudication_exact(
        ADJUDICATION_FIXTURE,
        &parsed_registration,
        &parsed_enrollment,
        &parsed_seal,
    )
    .expect("checked adjudication");
    for (parsed, expected) in [
        (
            parsed_registration.document_digest().as_str(),
            "sha256:031aaf113ba5f9040c5a93a7676d270d560ee9292e4b4999fcc9794f77eda758",
        ),
        (
            parsed_enrollment.document_digest().as_str(),
            "sha256:9148f4f55b50547522e51630f4adac9ea87fa56de108673daa5c94d76957d328",
        ),
        (
            parsed_assignment.document_digest().as_str(),
            "sha256:83531d5e40452fe6ef66f178f53282cbaf245e3a4fa740671d5449487ebe5f11",
        ),
        (
            parsed_seal.document_digest().as_str(),
            "sha256:350aa570de39c56b60ad1a4561f7cbfcb25f87794e2ca63c0f7c9fa03771dabe",
        ),
        (
            parsed_adjudication.document_digest().as_str(),
            "sha256:6f4f10f7f6329e350d65ce1af13ffa2521f2496973bcf8ed6b56adc0c49f220b",
        ),
    ] {
        assert_eq!(parsed, expected);
    }
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
fn campaign_requires_the_exact_n00_artifact_claim_boundary() {
    let widened_program = program_with_campaign_claim("fixture_campaign_and_result");
    let mut value = registration();
    value.program_registration_digest = widened_program.value().registration_digest.clone();
    reclose_registration(&mut value);
    assert!(matches!(
        parse_campaign_registration_exact(
            &canonical_bytes(&value).expect("campaign bytes"),
            &widened_program
        ),
        Err(CampaignError::Program)
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

#[test]
fn exact_assignment_seal_and_adjudication_chain_stays_fixture_only() {
    let (registration, enrollment) = parsed_enrollment();
    let assignment = parsed_assignment(&registration, &enrollment);
    let seal = parsed_seal(&registration, &enrollment, &assignment);
    let adjudication = adjudication(registration.value(), enrollment.value(), seal.value());
    let parsed = parse_campaign_adjudication_exact(
        &canonical_bytes(&adjudication).expect("adjudication bytes"),
        &registration,
        &enrollment,
        &seal,
    )
    .expect("valid adjudication");
    assert_eq!(
        assignment.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(
        seal.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(
        parsed.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(parsed.value().outcomes.len(), 2);
    assert_eq!(
        parsed.value().outcomes[1].disposition,
        CensoringDispositionV1::SourceLossCensored
    );
}

#[test]
fn assignment_closes_exact_included_subject_arm_probability_and_clock() {
    let (registration, enrollment) = parsed_enrollment();

    let mut missing = assignment(registration.value(), enrollment.value());
    missing.assignments.pop();
    reclose_assignment(&mut missing);
    assert!(matches!(
        parse_campaign_assignment_exact(
            &canonical_bytes(&missing).expect("bytes"),
            &registration,
            &enrollment
        ),
        Err(CampaignError::Assignment("subject closure"))
    ));

    let mut simultaneous = assignment(registration.value(), enrollment.value());
    simultaneous.assigned_at = enrollment.value().frozen_at;
    reclose_assignment(&mut simultaneous);
    assert!(matches!(
        parse_campaign_assignment_exact(
            &canonical_bytes(&simultaneous).expect("bytes"),
            &registration,
            &enrollment
        ),
        Err(CampaignError::Assignment("chain binding"))
    ));

    let mut unknown_arm = assignment(registration.value(), enrollment.value());
    unknown_arm.assignments[0].arm_id = stable("arm:invented");
    reclose_assignment(&mut unknown_arm);
    assert!(matches!(
        parse_campaign_assignment_exact(
            &canonical_bytes(&unknown_arm).expect("bytes"),
            &registration,
            &enrollment
        ),
        Err(CampaignError::Assignment("unknown arm"))
    ));

    let mut wrong_probability = assignment(registration.value(), enrollment.value());
    wrong_probability.assignments[0].probability_ppm = WireU64::new(499_999);
    reclose_assignment(&mut wrong_probability);
    assert!(matches!(
        parse_campaign_assignment_exact(
            &canonical_bytes(&wrong_probability).expect("bytes"),
            &registration,
            &enrollment
        ),
        Err(CampaignError::Assignment("subject or probability"))
    ));

    let mut late = assignment(registration.value(), enrollment.value());
    late.assigned_at = timestamp("2026-08-18T01:02:00.000001Z");
    reclose_assignment(&mut late);
    assert!(matches!(
        parse_campaign_assignment_exact(
            &canonical_bytes(&late).expect("bytes"),
            &registration,
            &enrollment
        ),
        Err(CampaignError::Assignment("chain binding"))
    ));
}

#[test]
fn seal_refuses_future_duplicate_uncommitted_or_rebound_evidence() {
    let (registration, enrollment) = parsed_enrollment();
    let assignment = parsed_assignment(&registration, &enrollment);

    let mut future = seal(registration.value(), enrollment.value(), assignment.value());
    future.evidence[1].available_at = timestamp("2026-08-18T01:02:00.000001Z");
    reclose_seal(&mut future);
    assert!(matches!(
        parse_campaign_seal_exact(
            &canonical_bytes(&future).expect("bytes"),
            &registration,
            &enrollment,
            &assignment
        ),
        Err(CampaignError::Seal("evidence cutoff"))
    ));

    let mut duplicate = seal(registration.value(), enrollment.value(), assignment.value());
    duplicate.evidence[1].artifact_id = duplicate.evidence[0].artifact_id.clone();
    reclose_seal(&mut duplicate);
    assert!(matches!(
        parse_campaign_seal_exact(
            &canonical_bytes(&duplicate).expect("bytes"),
            &registration,
            &enrollment,
            &assignment
        ),
        Err(CampaignError::Seal(
            "chain, chronology, or evidence closure"
        ))
    ));

    let mut uncommitted = seal(registration.value(), enrollment.value(), assignment.value());
    uncommitted.evidence[1].alleged_commit_seq = WireU64::new(12);
    reclose_seal(&mut uncommitted);
    assert!(matches!(
        parse_campaign_seal_exact(
            &canonical_bytes(&uncommitted).expect("bytes"),
            &registration,
            &enrollment,
            &assignment
        ),
        Err(CampaignError::Seal("evidence cutoff"))
    ));

    let mut rebound = seal(registration.value(), enrollment.value(), assignment.value());
    rebound.assignment_digest = digest("foreign assignment");
    reclose_seal(&mut rebound);
    assert!(matches!(
        parse_campaign_seal_exact(
            &canonical_bytes(&rebound).expect("bytes"),
            &registration,
            &enrollment,
            &assignment
        ),
        Err(CampaignError::Seal(
            "chain, chronology, or evidence closure"
        ))
    ));
}

#[test]
fn adjudication_requires_exact_subjects_maturity_units_and_typed_gaps() {
    let (registration, enrollment) = parsed_enrollment();
    let assignment = parsed_assignment(&registration, &enrollment);
    let seal = parsed_seal(&registration, &enrollment, &assignment);

    let mut missing = adjudication(registration.value(), enrollment.value(), seal.value());
    missing.outcomes.pop();
    reclose_adjudication(&mut missing);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&missing).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("subject closure"))
    ));

    let mut malformed_value = adjudication(registration.value(), enrollment.value(), seal.value());
    malformed_value.outcomes[0].observed_value = Some(stable("-025"));
    reclose_adjudication(&mut malformed_value);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&malformed_value).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("outcome value/unit"))
    ));

    let mut early = adjudication(registration.value(), enrollment.value(), seal.value());
    early.outcomes[0].known_at = timestamp("2026-08-18T01:03:59.999999Z");
    reclose_adjudication(&mut early);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&early).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("outcome cutoff or ordering"))
    ));

    let mut wrong_unit = adjudication(registration.value(), enrollment.value(), seal.value());
    wrong_unit.outcomes[0].observed_unit = Some(stable("ui_float"));
    reclose_adjudication(&mut wrong_unit);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&wrong_unit).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("outcome value/unit"))
    ));

    let mut missing_gap = adjudication(registration.value(), enrollment.value(), seal.value());
    missing_gap.outcomes[1].gap_ids.clear();
    reclose_adjudication(&mut missing_gap);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&missing_gap).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("disposition evidence shape"))
    ));

    let mut future_evidence = adjudication(registration.value(), enrollment.value(), seal.value());
    future_evidence.outcomes[0].evidence[0].available_at = timestamp("2026-08-18T01:04:30.000001Z");
    reclose_adjudication(&mut future_evidence);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&future_evidence).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("outcome evidence cutoff"))
    ));
}

#[test]
fn conflicting_outcome_needs_two_exact_evidence_items() {
    let (registration, enrollment) = parsed_enrollment();
    let assignment = parsed_assignment(&registration, &enrollment);
    let seal = parsed_seal(&registration, &enrollment, &assignment);
    let mut adjudication = adjudication(registration.value(), enrollment.value(), seal.value());
    adjudication.outcomes[0].disposition = CensoringDispositionV1::Conflicting;
    adjudication.outcomes[0].observed_value = None;
    adjudication.outcomes[0].observed_unit = None;
    reclose_adjudication(&mut adjudication);
    assert!(matches!(
        parse_campaign_adjudication_exact(
            &canonical_bytes(&adjudication).expect("bytes"),
            &registration,
            &enrollment,
            &seal
        ),
        Err(CampaignError::Adjudication("disposition evidence shape"))
    ));
}
