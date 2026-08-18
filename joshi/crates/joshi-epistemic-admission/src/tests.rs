use crate::{
    ClaimOccurrencePreflight, EpistemicAdmissionError, FirstRoundSubmissionPreflight,
    preflight_claim_occurrence, preflight_first_round_submission,
};
use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64, WireU128};
use joshi_epistemic_book::*;
use std::{path::PathBuf, str::FromStr};

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

fn definition() -> ValidatedArtifact<ClaimDefinitionV1> {
    let bytes = std::fs::read(fixture("spot-claim-definition.v1.json")).expect("fixture");
    decode_claim_definition(&bytes).expect("definition fixture")
}

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../fixtures/epistemic-book")
        .join(name)
}

fn capabilities() -> Vec<CapabilityAttestationV1> {
    vec![
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::CoherentVenueState,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::CoherentRealState,
            artifact: artifact("capability:state", "state"),
        },
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::DirectionBySizeQuote,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::ExactQuote,
            artifact: artifact("capability:quote", "quote"),
        },
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::FeeModel,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::ExactQuote,
            artifact: artifact("capability:fee", "fee"),
        },
        CapabilityAttestationV1 {
            kind: CapabilityKindV1::QuoteFreshness,
            profile_id: text("pump:curve:v1"),
            maturity: CapabilityMaturityV1::ExactQuote,
            artifact: artifact("capability:freshness", "freshness"),
        },
    ]
}

fn occurrence_definition() -> (ClaimOccurrenceV1, ResolvedOccurrencePortV1) {
    let definition = definition();
    let scene = artifact("scene:001", "scene");
    let universe = artifact("universe:001", "universe");
    let capabilities = capabilities();
    let occurrence = ClaimOccurrenceV1 {
        contract: text(CLAIM_OCCURRENCE_CONTRACT),
        schema_version: WireU64::new(1),
        claim_occurrence_id: text("claim-occurrence:001"),
        claim_definition: ArtifactRefV1 {
            occurrence_id: definition.value().claim_definition_id.clone(),
            semantic_digest: definition.semantic_digest().clone(),
        },
        occurrence_kind: OccurrenceKindV1::Initial,
        scene: scene.clone(),
        instrumented_universe: universe.clone(),
        subject_id: text("mint:subject-a"),
        portfolio_domain_id: None,
        occurrence_information_cutoff: time("2026-08-18T00:00:02.000000Z"),
        occurrence_commit_at: time("2026-08-18T00:00:03.000000Z"),
        issue_deadline: time("2026-08-18T00:00:05.000000Z"),
        target_window_origin: time("2026-08-18T00:00:06.000000Z"),
        horizon_at: time("2026-08-18T00:00:16.000000Z"),
        knowledge_deadline: time("2026-08-18T00:00:26.000000Z"),
        sealed_forecast_journal: SealedForecastJournalV1 {
            namespace_id: text("sealed-journal:001"),
            eligible_first_round_forecaster_ids: vec![text("forecaster:a"), text("forecaster:b")],
            required_first_round_count: WireU64::new(2),
            reveal_not_before: time("2026-08-18T00:00:26.000000Z"),
        },
        frozen_input: FrozenInputManifestV1 {
            evidence: vec![EvidenceInputV1 {
                artifact: artifact("evidence:market", "market"),
                available_at: time("2026-08-18T00:00:02.000000Z"),
                valid_from: time("2026-08-18T00:00:00.000000Z"),
                valid_through: time("2026-08-18T00:00:02.000000Z"),
                authority: EvidenceAuthorityV1::H2Descriptive,
                domain: text("pump-market"),
                carrier: text("mint:subject-a"),
                unit: text("typed-event"),
                topology_version: None,
            }],
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
        capability_closure: capabilities.clone(),
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    };
    (
        occurrence,
        ResolvedOccurrencePortV1 {
            scene,
            instrumented_universe: universe,
            capabilities,
        },
    )
}

#[test]
fn caller_can_only_make_unverified_b0_preflight() {
    let (occurrence, resolved) = occurrence_definition();
    let preflight = preflight_claim_occurrence(ClaimOccurrencePreflight {
        definition: definition(),
        occurrence,
        resolved,
    })
    .expect("unverified preflight");
    assert_eq!(
        preflight.artifact().value().claim_occurrence_id.as_str(),
        "claim-occurrence:001"
    );
}

#[test]
fn b0_commit_after_issue_is_refused_before_any_durable_claim() {
    let (mut occurrence, resolved) = occurrence_definition();
    occurrence.occurrence_commit_at = time("2026-08-18T00:00:05.000001Z");
    let error = preflight_claim_occurrence(ClaimOccurrencePreflight {
        definition: definition(),
        occurrence,
        resolved,
    })
    .expect_err("late commit must fail");
    assert!(error.to_string().contains("clock chain"));
}

#[test]
fn caller_cannot_launder_revision_as_a_first_round_seal() {
    let (occurrence, resolved) = occurrence_definition();
    let occurrence = preflight_claim_occurrence(ClaimOccurrencePreflight {
        definition: definition(),
        occurrence,
        resolved,
    })
    .expect("occurrence")
    .artifact()
    .clone();
    let submission = ForecastSubmissionV1 {
        contract: text(FORECAST_SUBMISSION_CONTRACT),
        schema_version: WireU64::new(1),
        submission_id: text("submission:revision"),
        claim_occurrence: ArtifactRefV1 {
            occurrence_id: occurrence.value().claim_occurrence_id.clone(),
            semantic_digest: occurrence.semantic_digest().clone(),
        },
        phase: SubmissionPhaseV1::Revision {
            revises_submission: artifact("submission:prior", "prior"),
            visible_parent_submission_ids: vec![text("submission:prior")],
            visible_ensemble_ids: vec![],
        },
        lineage: ProducerLineageV1 {
            forecaster_id: text("forecaster:a"),
            producer_kind: text("human"),
            provider: text("ember"),
            checkpoint: text("n/a"),
            prompt_template_digest: digest("prompt"),
            training_snapshot_digest: digest("training"),
            calibration_snapshot_digest: None,
            lineage_groups: vec![text("human:ember")],
            primary_lineage_group: text("human:ember"),
        },
        frozen_input_manifest_digest: digest_bytes(
            &canonical_bytes(&occurrence.value().frozen_input).expect("canonical"),
        )
        .expect("digest"),
        maximum_input_availability: occurrence.value().frozen_input.maximum_input_availability,
        submission_input_cutoff: occurrence.value().occurrence_information_cutoff,
        submission_production_time: time("2026-08-18T00:00:04.000000Z"),
        payload: ForecastPayloadV1::Abstain {
            reason: text("not now"),
        },
        support_statement: text("none"),
        uncertainty_statement: text("high"),
        authority: EpistemicAuthorityV1::READ_ONLY_H3,
    };
    let error = preflight_first_round_submission(FirstRoundSubmissionPreflight {
        definition: definition(),
        occurrence,
        submission,
    })
    .expect_err("revision cannot be first round");
    assert!(matches!(error, EpistemicAdmissionError::FirstRoundNotBlind));
}

#[test]
fn every_adversarial_fixture_refuses_before_durable_admission() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/epistemic-admission");
    for name in [
        "b0-issue-before-commit.json",
        "first-round-peer-visible.json",
        "reveal-before-seal.json",
        "future-support.json",
    ] {
        let bytes = std::fs::read_to_string(root.join(name)).expect("adversarial fixture");
        let vector: serde_json::Value = serde_json::from_str(&bytes).expect("fixture JSON");
        assert_eq!(vector["expectation"], "reject_before_durable_admission");
    }
}
