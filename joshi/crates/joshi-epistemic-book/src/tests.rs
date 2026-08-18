use crate::*;
use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64, WireU128};
use std::str::FromStr;

fn text(value: &str) -> StableString {
    StableString::new(value).expect("test stable string")
}

fn time(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("test timestamp")
}

fn digest(seed: &str) -> ValueDigest {
    digest_bytes(seed.as_bytes()).expect("test digest")
}

fn artifact(id: &str, seed: &str) -> ArtifactRefV1 {
    ArtifactRefV1 {
        occurrence_id: text(id),
        semantic_digest: digest(seed),
    }
}

fn requirements() -> Vec<CapabilityRequirementV1> {
    vec![
        CapabilityRequirementV1 {
            kind: CapabilityKindV1::CoherentVenueState,
            profile_id: text("pump:curve:v1"),
            required_maturity: CapabilityMaturityV1::CoherentRealState,
        },
        CapabilityRequirementV1 {
            kind: CapabilityKindV1::DirectionBySizeQuote,
            profile_id: text("pump:curve:v1"),
            required_maturity: CapabilityMaturityV1::ExactQuote,
        },
        CapabilityRequirementV1 {
            kind: CapabilityKindV1::FeeModel,
            profile_id: text("pump:curve:v1"),
            required_maturity: CapabilityMaturityV1::ExactQuote,
        },
        CapabilityRequirementV1 {
            kind: CapabilityKindV1::QuoteFreshness,
            profile_id: text("pump:curve:v1"),
            required_maturity: CapabilityMaturityV1::ExactQuote,
        },
    ]
}

fn claim_value() -> ClaimDefinitionV1 {
    ClaimDefinitionV1 {
        contract: text(CLAIM_DEFINITION_CONTRACT),
        schema_version: WireU64::new(1),
        claim_definition_id: text("claim-definition:spot-competing-risk:v1"),
        definition_version: WireU64::new(1),
        supersedes: None,
        producer_build_digest: digest("book-build-v1"),
        family: ClaimFamilyV1::SpotCompetingRisk {
            quote_profile_id: text("pump:curve:v1"),
            net_profit_threshold_atoms: WireU128::new(10_000),
            drawdown_threshold_atoms: WireU128::new(20_000),
            quote_freshness_us: WireU64::new(2_000_000),
            observation_cadence_us: WireU64::new(1_000_000),
            tie_rule: TieRuleV1::ConflictUnlessSourceOrdered,
            interval_gap_rule: IntervalGapRuleV1::IntervalCensored,
        },
        outcome_space: vec![
            OutcomeStateV1 {
                outcome_id: text("drawdown_first"),
                meaning: text("registered executable drawdown crossed first"),
            },
            OutcomeStateV1 {
                outcome_id: text("healthy_survival"),
                meaning: text("no registered event through horizon"),
            },
            OutcomeStateV1 {
                outcome_id: text("lifecycle_boundary_first"),
                meaning: text("registered lifecycle boundary occurred first"),
            },
            OutcomeStateV1 {
                outcome_id: text("profit_first"),
                meaning: text("registered net executable profit crossed first"),
            },
            OutcomeStateV1 {
                outcome_id: text("route_loss_first"),
                meaning: text("eligible route or liquidity predicate failed first"),
            },
        ],
        adjudication: AdjudicationContractV1 {
            resolver_version: text("resolver:spot-competing-risk:v1"),
            eligible_observation_contracts: vec![text("joshi.outcome.executable_quote/v1")],
            maturity_rule: text("knowledge_deadline_cut"),
            correction_policy: text("append_exact_supersession"),
            unresolved_treatment: text("retain_unscored_denominator"),
        },
        scoring: ScoringContractV1 {
            rule: ProperScoreRuleV1::BrierCategorical,
            probability_floor_ppm: None,
            baseline_definition_id: text("baseline:lifecycle-horizon:v1"),
            permits_resolved_observed: true,
            permits_healthy_no_event: true,
            permits_frozen_replay: false,
            abstention_is_unscored: true,
        },
        support: SupportContractV1 {
            eligible_population: text("witnessed_operator_nomination"),
            required_coverage: vec![text("exact_quote_cadence")],
            prohibited_inputs: vec![text("post_cutoff_identity_or_outcome")],
            transfer_limit: text("operator_selected_pump_curve_profile_only"),
        },
        required_capabilities: requirements(),
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    }
}

fn definition() -> ValidatedArtifact<ClaimDefinitionV1> {
    validate_claim_definition(claim_value()).expect("valid claim definition")
}

fn capabilities() -> Vec<CapabilityAttestationV1> {
    vec![
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::CoherentVenueState,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::CoherentRealState,
            artifact: artifact("capability:state", "state-capability"),
        },
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::DirectionBySizeQuote,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::ExactQuote,
            artifact: artifact("capability:quote", "quote-capability"),
        },
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::FeeModel,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::ExactQuote,
            artifact: artifact("capability:fee", "fee-capability"),
        },
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::QuoteFreshness,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::ExactQuote,
            artifact: artifact("capability:freshness", "freshness-capability"),
        },
    ]
}

fn occurrence(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
) -> (
    ValidatedArtifact<ClaimOccurrenceV1>,
    ResolvedOccurrencePortV1,
) {
    let scene = artifact("scene:001", "scene-001");
    let universe = artifact("universe:001", "universe-001");
    let capabilities = capabilities();
    let port = ResolvedOccurrencePortV1 {
        scene: scene.clone(),
        instrumented_universe: universe.clone(),
        capabilities: capabilities.clone(),
    };
    let value = ClaimOccurrenceV1 {
        contract: text(CLAIM_OCCURRENCE_CONTRACT),
        schema_version: WireU64::new(1),
        claim_occurrence_id: text("claim-occurrence:001"),
        claim_definition: ArtifactRefV1 {
            occurrence_id: definition.value().claim_definition_id.clone(),
            semantic_digest: definition.semantic_digest().clone(),
        },
        occurrence_kind: OccurrenceKindV1::Initial,
        scene,
        instrumented_universe: universe,
        subject_id: text("mint:subject-a"),
        portfolio_domain_id: None,
        occurrence_information_cutoff: time("2026-08-18T00:00:02.000000Z"),
        occurrence_commit_at: time("2026-08-18T00:00:03.000000Z"),
        issue_deadline: time("2026-08-18T00:00:05.000000Z"),
        target_window_origin: time("2026-08-18T00:00:06.000000Z"),
        horizon_at: time("2026-08-18T00:00:16.000000Z"),
        knowledge_deadline: time("2026-08-18T00:00:26.000000Z"),
        sealed_forecast_journal: SealedForecastJournalV1 {
            namespace_id: text("sealed-journal:claim-occurrence:001"),
            eligible_first_round_forecaster_ids: vec![
                text("submission:a"),
                text("submission:b"),
                text("submission:baseline"),
                text("submission:c"),
                text("submission:candidate"),
                text("submission:prior"),
            ],
            required_first_round_count: WireU64::new(2),
            reveal_not_before: time("2026-08-18T00:00:26.000000Z"),
        },
        frozen_input: FrozenInputManifestV1 {
            evidence: vec![
                EvidenceInputV1 {
                    artifact: artifact("evidence:market", "market-evidence"),
                    available_at: time("2026-08-18T00:00:01.000000Z"),
                    valid_from: time("2026-08-18T00:00:00.000000Z"),
                    valid_through: time("2026-08-18T00:00:02.000000Z"),
                    authority: EvidenceAuthorityV1::H2Descriptive,
                    domain: text("pump-market"),
                    carrier: text("mint:subject-a"),
                    unit: text("typed-event"),
                    topology_version: None,
                },
                EvidenceInputV1 {
                    artifact: artifact("evidence:scene", "scene-evidence"),
                    available_at: time("2026-08-18T00:00:02.000000Z"),
                    valid_from: time("2026-08-18T00:00:02.000000Z"),
                    valid_through: time("2026-08-18T00:00:02.000000Z"),
                    authority: EvidenceAuthorityV1::H2Descriptive,
                    domain: text("operator-scene"),
                    carrier: text("scene:001"),
                    unit: text("semantic-scene"),
                    topology_version: None,
                },
            ],
            coverage_ids: vec![text("coverage:quotes")],
            gap_ids: vec![],
            maximum_input_availability: time("2026-08-18T00:00:02.000000Z"),
        },
        conditioning: OccurrenceConditioningV1 {
            decision_kind: text("operator_nomination"),
            lifecycle_or_regime: text("pump_curve_pre_migration"),
            direction: DirectionV1::NumeraireToAsset,
            exact_size_atoms: WireU128::new(100_000_000),
            asset_id: text("mint:subject-a"),
            numeraire_asset_id: text("sol"),
            downstream_policy_id: text("none_observational"),
            support_state: text("operator_selected"),
        },
        capability_closure: capabilities,
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    };
    (
        validate_claim_occurrence(value, definition, &port).expect("valid occurrence"),
        port,
    )
}

fn forecast(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    id: &str,
    lineage: &str,
    values: [u64; 5],
) -> ValidatedArtifact<ForecastSubmissionV1> {
    let frozen_input_manifest_digest =
        digest_bytes(&canonical_bytes(&occurrence.value().frozen_input).expect("frozen bytes"))
            .expect("frozen digest");
    validate_forecast_submission(
        ForecastSubmissionV1 {
            contract: text(FORECAST_SUBMISSION_CONTRACT),
            schema_version: WireU64::new(1),
            submission_id: text(id),
            claim_occurrence: ArtifactRefV1 {
                occurrence_id: occurrence.value().claim_occurrence_id.clone(),
                semantic_digest: occurrence.semantic_digest().clone(),
            },
            phase: SubmissionPhaseV1::FirstRound,
            lineage: ProducerLineageV1 {
                forecaster_id: text(id),
                producer_kind: text("simple_baseline"),
                provider: text("local"),
                checkpoint: text("fixed:v1"),
                prompt_template_digest: digest(&format!("prompt:{id}")),
                training_snapshot_digest: digest("training:prior-only"),
                calibration_snapshot_digest: None,
                lineage_groups: vec![text(lineage)],
                primary_lineage_group: text(lineage),
            },
            frozen_input_manifest_digest,
            maximum_input_availability: occurrence.value().frozen_input.maximum_input_availability,
            submission_input_cutoff: occurrence.value().occurrence_information_cutoff,
            submission_production_time: time("2026-08-18T00:00:04.000000Z"),
            payload: ForecastPayloadV1::Categorical {
                probabilities: definition
                    .value()
                    .outcome_space
                    .iter()
                    .zip(values)
                    .map(|(outcome, probability_ppm)| OutcomeProbabilityV1 {
                        outcome_id: outcome.outcome_id.clone(),
                        probability_ppm: WireU64::new(probability_ppm),
                    })
                    .collect(),
            },
            support_statement: text("registered operator-selected support only"),
            uncertainty_statement: text("categorical aleatoric and coverage uncertainty retained"),
            authority: EpistemicAuthorityV1::READ_ONLY_H3,
        },
        definition,
        occurrence,
    )
    .expect("valid forecast")
}

fn adjudication(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
) -> ValidatedArtifact<AdjudicationV1> {
    let evidence = vec![OutcomeEvidenceV1 {
        artifact: artifact("outcome-evidence:001", "outcome-evidence"),
        available_at: time("2026-08-18T00:00:20.000000Z"),
        observation_contract: text("joshi.outcome.executable_quote/v1"),
    }];
    let coverage = OutcomeCoverageV1 {
        status: OutcomeCoverageStatusV1::Complete,
        coverage_ids: vec![text("coverage:outcome")],
        gap_ids: vec![],
    };
    let value = AdjudicationV1 {
        contract: text(ADJUDICATION_CONTRACT),
        schema_version: WireU64::new(1),
        adjudication_id: text("adjudication:001"),
        adjudication_version: WireU64::new(1),
        supersedes: None,
        claim_occurrence: ArtifactRefV1 {
            occurrence_id: occurrence.value().claim_occurrence_id.clone(),
            semantic_digest: occurrence.semantic_digest().clone(),
        },
        adjudicated_at: time("2026-08-18T00:00:27.000000Z"),
        knowledge_cutoff: occurrence.value().knowledge_deadline,
        evidence: evidence.clone(),
        coverage: coverage.clone(),
        disposition: AdjudicationDispositionV1::ResolvedObserved {
            outcome_id: text("profit_first"),
        },
        resolver_build_digest: digest("resolver-build"),
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    };
    validate_adjudication(value, definition, occurrence, None).expect("valid adjudication")
}

#[test]
fn canonical_definition_fixture_and_strict_unknown_field() {
    let expected = include_bytes!("../../../fixtures/epistemic-book/spot-claim-definition.v1.json");
    let validated = definition();
    assert_eq!(validated.exact_bytes(), expected);
    assert!(decode_claim_definition(expected).is_ok());
    assert!(
        decode_claim_definition(include_bytes!(
            "../../../fixtures/epistemic-book/invalid-unknown-field.v1.json"
        ))
        .is_err()
    );
}

#[test]
fn widened_authority_and_late_evidence_are_refused() {
    let mut widened = claim_value();
    widened.authority.may_influence_acquisition = true;
    assert!(validate_claim_definition(widened).is_err());

    let definition = definition();
    let (valid, port) = occurrence(&definition);
    let mut late = valid.value().clone();
    late.frozen_input.evidence[1].available_at = time("2026-08-18T00:00:02.500000Z");
    late.frozen_input.maximum_input_availability = time("2026-08-18T00:00:02.500000Z");
    assert!(validate_claim_occurrence(late, &definition, &port).is_err());
}

#[test]
fn definition_supersession_requires_the_exact_prior_object() {
    let prior = definition();
    let mut next = prior.value().clone();
    next.definition_version = WireU64::new(2);
    next.supersedes = Some(ArtifactRefV1 {
        occurrence_id: prior.value().claim_definition_id.clone(),
        semantic_digest: prior.semantic_digest().clone(),
    });
    assert!(validate_claim_definition(next.clone()).is_err());
    assert!(validate_claim_definition_supersession(next.clone(), &prior).is_ok());
    next.supersedes = Some(artifact("claim-definition:substituted", "wrong-prior"));
    assert!(validate_claim_definition_supersession(next, &prior).is_err());
}

#[test]
fn input_substitution_and_unregistered_first_round_are_refused() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let submission = forecast(
        &definition,
        &occurrence,
        "submission:candidate",
        "lineage:candidate",
        [200_000, 200_000, 50_000, 500_000, 50_000],
    );
    let mut substituted = submission.value().clone();
    substituted.frozen_input_manifest_digest = digest("different-input");
    assert!(validate_forecast_submission(substituted, &definition, &occurrence).is_err());

    let mut unregistered = submission.value().clone();
    unregistered.submission_id = text("submission:outsider");
    unregistered.lineage.forecaster_id = text("submission:outsider");
    assert!(validate_forecast_submission(unregistered, &definition, &occurrence).is_err());
}

#[test]
fn source_loss_is_retained_but_cannot_be_scored() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let submission = forecast(
        &definition,
        &occurrence,
        "submission:candidate",
        "lineage:candidate",
        [200_000, 200_000, 50_000, 500_000, 50_000],
    );
    let gaps = vec![text("gap:outcome")];
    let value = AdjudicationV1 {
        contract: text(ADJUDICATION_CONTRACT),
        schema_version: WireU64::new(1),
        adjudication_id: text("adjudication:source-loss"),
        adjudication_version: WireU64::new(1),
        supersedes: None,
        claim_occurrence: ArtifactRefV1 {
            occurrence_id: occurrence.value().claim_occurrence_id.clone(),
            semantic_digest: occurrence.semantic_digest().clone(),
        },
        adjudicated_at: time("2026-08-18T00:00:27.000000Z"),
        knowledge_cutoff: occurrence.value().knowledge_deadline,
        evidence: vec![],
        coverage: OutcomeCoverageV1 {
            status: OutcomeCoverageStatusV1::Gapped,
            coverage_ids: vec![],
            gap_ids: gaps.clone(),
        },
        disposition: AdjudicationDispositionV1::SourceLossCensored { gap_ids: gaps },
        resolver_build_digest: digest("resolver-build"),
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    };
    let adjudication = validate_adjudication(value, &definition, &occurrence, None)
        .expect("source loss is an honest adjudication");
    assert!(
        preview_brier_score(&definition, &occurrence, &submission, &adjudication, None,).is_err()
    );
}

#[test]
fn exact_brier_preview_has_an_explicit_nonpromoting_ceiling() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let candidate = forecast(
        &definition,
        &occurrence,
        "submission:candidate",
        "lineage:candidate",
        [200_000, 200_000, 50_000, 500_000, 50_000],
    );
    let baseline = forecast(
        &definition,
        &occurrence,
        "submission:baseline",
        "lineage:baseline",
        [200_000, 200_000, 200_000, 200_000, 200_000],
    );
    let adjudication = adjudication(&definition, &occurrence);
    let score = preview_brier_score(
        &definition,
        &occurrence,
        &candidate,
        &adjudication,
        Some(&baseline),
    )
    .expect("exact score");
    assert_eq!(score.candidate_loss.numerator.get(), 335_000_000_000);
    assert_eq!(
        score.baseline_increment.as_ref().map(|value| value.sign),
        Some(IncrementSignV1::CandidateBetter)
    );
    assert_eq!(
        score.status,
        EpistemicImplementationStatusV1::ContractDraftFixtureValidated
    );
}

#[test]
fn score_preview_refuses_cross_occurrence_substitution() {
    let definition = definition();
    let (first_occurrence, first_port) = occurrence(&definition);
    let candidate = forecast(
        &definition,
        &first_occurrence,
        "submission:candidate",
        "lineage:candidate",
        [200_000, 200_000, 50_000, 500_000, 50_000],
    );
    let outcome = adjudication(&definition, &first_occurrence);
    let mut second = first_occurrence.value().clone();
    second.claim_occurrence_id = text("claim-occurrence:002");
    second.sealed_forecast_journal.namespace_id = text("sealed-journal:claim-occurrence:002");
    let second = validate_claim_occurrence(second, &definition, &first_port)
        .expect("second semantic occurrence");
    assert!(preview_brier_score(&definition, &second, &candidate, &outcome, None).is_err());
}

#[test]
fn healthy_and_replay_resolution_require_real_closure() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let resolved = adjudication(&definition, &occurrence);

    let mut empty_healthy = resolved.value().clone();
    empty_healthy.evidence.clear();
    empty_healthy.coverage.coverage_ids.clear();
    empty_healthy.disposition = AdjudicationDispositionV1::HealthyNoEventThroughHorizon {
        outcome_id: text("healthy_survival"),
    };
    assert!(validate_adjudication(empty_healthy, &definition, &occurrence, None).is_err());

    let mut spot_replay = resolved.value().clone();
    spot_replay.disposition = AdjudicationDispositionV1::ResolvedFrozenReplay {
        outcome_id: text("profit_first"),
        replay_manifest: artifact("terminal-manifest:001", "terminal-manifest"),
    };
    assert!(validate_adjudication(spot_replay, &definition, &occurrence, None).is_err());
}

fn repeated_support(
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
) -> ValidatedArtifact<SupportCalibrationSummaryV1> {
    let memberships = |first: usize, last: usize, outcome_at: &str| {
        (first..last)
            .map(|index| WindowScoreMembershipV1 {
                score: artifact(
                    &format!("score:historical:{index:03}"),
                    &format!("score-{index:03}"),
                ),
                claim_occurrence: artifact(
                    &format!("occurrence:historical:{index:03}"),
                    &format!("occurrence-{index:03}"),
                ),
                adjudication: artifact(
                    &format!("adjudication:historical:{index:03}"),
                    &format!("adjudication-{index:03}"),
                ),
                outcome_available_at: time(outcome_at),
            })
            .collect::<Vec<_>>()
    };
    let first = memberships(0, 20, "2026-08-02T12:00:00.000000Z");
    let second = memberships(20, 40, "2026-08-06T12:00:00.000000Z");
    let scores = first
        .iter()
        .chain(&second)
        .map(|membership| membership.score.clone())
        .collect();
    validate_support_summary(SupportCalibrationSummaryV1 {
        contract: text(SUPPORT_SUMMARY_CONTRACT),
        schema_version: WireU64::new(1),
        summary_id: text("support:repeated"),
        claim_definition: ArtifactRefV1 {
            occurrence_id: definition.value().claim_definition_id.clone(),
            semantic_digest: definition.semantic_digest().clone(),
        },
        score_artifacts: scores,
        total_occurrences: WireU64::new(42),
        scored_occurrences: WireU64::new(40),
        adjudication_counts: vec![
            AdjudicationCountV1 {
                disposition: text("resolved_observed"),
                count: WireU64::new(40),
            },
            AdjudicationCountV1 {
                disposition: text("source_loss_censored"),
                count: WireU64::new(2),
            },
        ],
        coverage_ids: vec![text("coverage:historical")],
        gap_ids: vec![text("gap:historical")],
        windows: vec![
            EvaluationWindowV1 {
                window_id: text("window:001"),
                start: time("2026-08-01T00:00:00.000000Z"),
                end: time("2026-08-02T00:00:00.000000Z"),
                embargo_through: time("2026-08-03T00:00:00.000000Z"),
                eligible_score_count: WireU64::new(20),
                score_memberships: first,
            },
            EvaluationWindowV1 {
                window_id: text("window:002"),
                start: time("2026-08-05T00:00:00.000000Z"),
                end: time("2026-08-06T00:00:00.000000Z"),
                embargo_through: time("2026-08-07T00:00:00.000000Z"),
                eligible_score_count: WireU64::new(20),
                score_memberships: second,
            },
        ],
        calibration_bins: vec![],
        maturity: SupportMaturityV1::RepeatedProspectiveSupport,
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    })
    .expect("semantically derived repeated support")
}

#[test]
fn semantic_ensemble_preflight_never_mints_durable_eligibility() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let first = forecast(
        &definition,
        &occurrence,
        "submission:a",
        "lineage:a",
        [200_000, 200_000, 50_000, 500_000, 50_000],
    );
    let second = forecast(
        &definition,
        &occurrence,
        "submission:b",
        "lineage:b",
        [100_000, 300_000, 100_000, 400_000, 100_000],
    );
    let support = repeated_support(&definition);
    let assessment =
        assess_shadow_ensemble_semantics(&definition, &occurrence, &support, &[&first, &second]);
    assert!(matches!(
        assessment,
        ShadowEnsembleEligibilityV1::BlockedMissingDurableProof { .. }
    ));

    let mut future_support = support.value().clone();
    future_support.windows[1].embargo_through = time("2026-08-19T00:00:00.000000Z");
    future_support.windows[1]
        .score_memberships
        .iter_mut()
        .for_each(|membership| {
            membership.outcome_available_at = time("2026-08-18T00:00:02.000000Z");
        });
    let future_support = validate_support_summary(future_support)
        .expect("semantic summary can exist but cannot support this earlier target");
    assert!(matches!(
        assess_shadow_ensemble_semantics(
            &definition,
            &occurrence,
            &future_support,
            &[&first, &second],
        ),
        ShadowEnsembleEligibilityV1::SemanticallyIneligible { .. }
    ));

    let duplicate = forecast(
        &definition,
        &occurrence,
        "submission:c",
        "lineage:a",
        [100_000, 300_000, 100_000, 400_000, 100_000],
    );
    assert!(matches!(
        assess_shadow_ensemble_semantics(&definition, &occurrence, &support, &[&first, &duplicate],),
        ShadowEnsembleEligibilityV1::SemanticallyIneligible { .. }
    ));
}

#[test]
fn author_selected_support_upgrade_is_refused() {
    let definition = definition();
    let support = repeated_support(&definition);
    let mut fake = support.value().clone();
    fake.windows.truncate(1);
    assert!(validate_support_summary(fake).is_err());
}

#[test]
fn revision_requires_a_new_frozen_landmark_and_exact_visible_parent() {
    let definition = definition();
    let (prior_occurrence, _) = occurrence(&definition);
    let prior = forecast(
        &definition,
        &prior_occurrence,
        "submission:prior",
        "lineage:one",
        [200_000, 200_000, 50_000, 500_000, 50_000],
    );

    let mut next_value = prior_occurrence.value().clone();
    next_value.claim_occurrence_id = text("claim-occurrence:revision:001");
    next_value.occurrence_kind = OccurrenceKindV1::RevisionLandmark {
        landmark_id: text("landmark:route-change"),
        prior_occurrence: ArtifactRefV1 {
            occurrence_id: prior_occurrence.value().claim_occurrence_id.clone(),
            semantic_digest: prior_occurrence.semantic_digest().clone(),
        },
        evidence_class: text("registered_route_change"),
    };
    next_value.frozen_input.evidence.push(EvidenceInputV1 {
        artifact: artifact("evidence:revision", "revision-evidence"),
        available_at: time("2026-08-18T00:00:08.000000Z"),
        valid_from: time("2026-08-18T00:00:08.000000Z"),
        valid_through: time("2026-08-18T00:00:08.000000Z"),
        authority: EvidenceAuthorityV1::H2Descriptive,
        domain: text("route-state"),
        carrier: text("mint:subject-a"),
        unit: text("route-event"),
        topology_version: None,
    });
    next_value.frozen_input.evidence.sort_by(|left, right| {
        left.artifact
            .occurrence_id
            .cmp(&right.artifact.occurrence_id)
    });
    next_value.frozen_input.maximum_input_availability = time("2026-08-18T00:00:08.000000Z");
    next_value.occurrence_information_cutoff = time("2026-08-18T00:00:08.000000Z");
    next_value.occurrence_commit_at = time("2026-08-18T00:00:08.250000Z");
    next_value.issue_deadline = time("2026-08-18T00:00:09.000000Z");
    next_value.target_window_origin = time("2026-08-18T00:00:10.000000Z");
    next_value.horizon_at = time("2026-08-18T00:00:20.000000Z");
    next_value.knowledge_deadline = time("2026-08-18T00:00:30.000000Z");
    next_value.sealed_forecast_journal.namespace_id = text("sealed-journal:revision:001");
    next_value.sealed_forecast_journal.reveal_not_before = time("2026-08-18T00:00:30.000000Z");
    let port = ResolvedOccurrencePortV1 {
        scene: next_value.scene.clone(),
        instrumented_universe: next_value.instrumented_universe.clone(),
        capabilities: next_value.capability_closure.clone(),
    };
    assert!(validate_claim_occurrence(next_value.clone(), &definition, &port).is_err());
    let next_occurrence =
        validate_revision_occurrence(next_value, &definition, &port, &prior_occurrence)
            .expect("valid registered landmark occurrence");

    let mut revision = prior.value().clone();
    revision.submission_id = text("submission:revision");
    revision.claim_occurrence = ArtifactRefV1 {
        occurrence_id: next_occurrence.value().claim_occurrence_id.clone(),
        semantic_digest: next_occurrence.semantic_digest().clone(),
    };
    revision.phase = SubmissionPhaseV1::Revision {
        revises_submission: ArtifactRefV1 {
            occurrence_id: prior.value().submission_id.clone(),
            semantic_digest: prior.semantic_digest().clone(),
        },
        visible_parent_submission_ids: vec![prior.value().submission_id.clone()],
        visible_ensemble_ids: vec![],
    };
    revision.frozen_input_manifest_digest = digest_bytes(
        &canonical_bytes(&next_occurrence.value().frozen_input).expect("landmark input bytes"),
    )
    .expect("landmark input digest");
    revision.maximum_input_availability = next_occurrence
        .value()
        .frozen_input
        .maximum_input_availability;
    revision.submission_input_cutoff = next_occurrence.value().occurrence_information_cutoff;
    revision.submission_production_time = time("2026-08-18T00:00:08.500000Z");
    let revision = validate_forecast_submission(revision, &definition, &next_occurrence)
        .expect("valid revision submission");
    assert!(validate_revision(&revision, &next_occurrence, &prior, &prior_occurrence,).is_ok());
}

#[test]
fn censor_conflict_refusal_and_unsupported_dispositions_remain_distinct() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let base = AdjudicationV1 {
        contract: text(ADJUDICATION_CONTRACT),
        schema_version: WireU64::new(1),
        adjudication_id: text("adjudication:variant"),
        adjudication_version: WireU64::new(1),
        supersedes: None,
        claim_occurrence: ArtifactRefV1 {
            occurrence_id: occurrence.value().claim_occurrence_id.clone(),
            semantic_digest: occurrence.semantic_digest().clone(),
        },
        adjudicated_at: time("2026-08-18T00:00:27.000000Z"),
        knowledge_cutoff: occurrence.value().knowledge_deadline,
        evidence: vec![],
        coverage: OutcomeCoverageV1 {
            status: OutcomeCoverageStatusV1::Gapped,
            coverage_ids: vec![],
            gap_ids: vec![text("gap:outcome")],
        },
        disposition: AdjudicationDispositionV1::IntervalCensored {
            lower: Some(time("2026-08-18T00:00:10.000000Z")),
            upper: Some(time("2026-08-18T00:00:12.000000Z")),
        },
        resolver_build_digest: digest("resolver-build"),
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    };
    assert!(validate_adjudication(base.clone(), &definition, &occurrence, None).is_ok());

    let mut conflicting = base.clone();
    conflicting.evidence = vec![
        OutcomeEvidenceV1 {
            artifact: artifact("observation:a", "observation-a"),
            available_at: time("2026-08-18T00:00:20.000000Z"),
            observation_contract: text("joshi.outcome.executable_quote/v1"),
        },
        OutcomeEvidenceV1 {
            artifact: artifact("observation:b", "observation-b"),
            available_at: time("2026-08-18T00:00:21.000000Z"),
            observation_contract: text("joshi.outcome.executable_quote/v1"),
        },
    ];
    conflicting.disposition = AdjudicationDispositionV1::Conflicting {
        observation_ids: vec![text("observation:a"), text("observation:b")],
    };
    assert!(validate_adjudication(conflicting, &definition, &occurrence, None).is_ok());

    let mut refused = base.clone();
    refused.evidence = vec![OutcomeEvidenceV1 {
        artifact: artifact("observation:refusal", "observation-refusal"),
        available_at: time("2026-08-18T00:00:20.000000Z"),
        observation_contract: text("joshi.outcome.executable_quote/v1"),
    }];
    refused.disposition = AdjudicationDispositionV1::RouteOrLiquidationRefused {
        reason: text("eligible route refused exact size"),
    };
    assert!(validate_adjudication(refused, &definition, &occurrence, None).is_ok());

    let mut unsupported = base;
    unsupported.coverage.status = OutcomeCoverageStatusV1::Unavailable;
    unsupported.disposition = AdjudicationDispositionV1::Unsupported {
        reason: text("profile unsupported at knowledge cutoff"),
    };
    assert!(validate_adjudication(unsupported, &definition, &occurrence, None).is_ok());
}

#[test]
fn adjudication_corrections_are_exact_consecutive_supersessions() {
    let definition = definition();
    let (occurrence, _) = occurrence(&definition);
    let prior = adjudication(&definition, &occurrence);
    let mut correction = prior.value().clone();
    correction.adjudication_id = text("adjudication:002");
    correction.adjudication_version = WireU64::new(2);
    correction.supersedes = Some(ArtifactRefV1 {
        occurrence_id: prior.value().adjudication_id.clone(),
        semantic_digest: prior.semantic_digest().clone(),
    });
    correction.adjudicated_at = time("2026-08-18T00:00:28.000000Z");
    assert!(
        validate_adjudication(correction.clone(), &definition, &occurrence, Some(&prior)).is_ok()
    );
    correction.adjudication_version = WireU64::new(3);
    assert!(validate_adjudication(correction, &definition, &occurrence, Some(&prior)).is_err());
}
