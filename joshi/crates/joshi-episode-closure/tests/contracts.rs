use joshi_admission::{
    Sha256Digest,
    operational::{
        ChoiceMembershipReferenceV1, ClientClockV1, EpisodeLaunchRegistrationV1,
        EpisodeProtocolRegistrationV1, ExplicitAbstentionCommandV1, ExplicitAbstentionReason,
        ExplicitAbstentionReceiptV1, OperationalStatus, PresentationReferenceV1,
        PresentationSceneReceiptV1, SceneReferenceV1, SessionLaunchEnvelopeV1,
    },
    strict_json,
};
use joshi_episode_closure::*;

const SESSION_LAUNCH: &[u8] =
    include_bytes!("../../../fixtures/operational/session_launch_v1.json");
const SESSION_CLOSE_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/episode-closure/session_close.v1.json");
const KNOWLEDGE_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/episode-closure/knowledge_closure.v1.json");
const OUTCOME_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/episode-closure/outcome_at_horizon.v1.json");
const INTERVIEW_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/episode-closure/interview_disposition.v1.json");
const ADVERSARIAL_FIXTURE: &[u8] =
    include_bytes!("../../../fixtures/episode-closure/adversarial.json");

struct GoldenSet {
    session: SessionCloseV1,
    knowledge: KnowledgeClosureV1,
    outcome: OutcomeAtHorizonV1,
    interview: InterviewDispositionV1,
}

struct OwnedPrerequisites {
    envelope: SessionLaunchEnvelopeV1,
    protocol_bytes: Vec<u8>,
    launch_bytes: Vec<u8>,
    presentation: PresentationSceneReceiptV1,
    command: ExplicitAbstentionCommandV1,
    command_bytes: Vec<u8>,
    receipt: ExplicitAbstentionReceiptV1,
    receipt_bytes: Vec<u8>,
}

fn digest(byte: char) -> Sha256Digest {
    Sha256Digest::parse(format!("sha256:{}", byte.to_string().repeat(64))).expect("digest")
}

fn artifact(
    contract: &str,
    occurrence: &str,
    id: &str,
    byte: char,
    commit: &str,
    at: &str,
) -> CommittedArtifactReferenceV1 {
    CommittedArtifactReferenceV1 {
        contract: contract.into(),
        schema_version: 1,
        producer_occurrence_id: occurrence.into(),
        artifact_id: id.into(),
        artifact_digest: digest(byte),
        commit_seq: commit.into(),
        committed_at: at.into(),
    }
}

fn prerequisites() -> OwnedPrerequisites {
    let envelope: SessionLaunchEnvelopeV1 =
        strict_json::parse(SESSION_LAUNCH, 64 * 1024).expect("session launch");
    let protocol_bytes = serde_json::to_vec(&envelope.protocol).expect("protocol bytes");
    let launch_bytes = serde_json::to_vec(&envelope.registration).expect("launch bytes");
    envelope
        .validate(&protocol_bytes, &launch_bytes)
        .expect("session envelope");
    let presentation = PresentationSceneReceiptV1 {
        contract: "joshi.store.presentation_scene_receipt".into(),
        schema_version: 1,
        catalog_id: "catalog-v7".into(),
        catalog_schema: "joshi.sqlite.v7".into(),
        batch_id: "presentation-batch-1".into(),
        presentation_id: "presentation-1".into(),
        idempotency_key: "presentation-key-1".into(),
        assignment_id: "assignment-1".into(),
        scene: SceneReferenceV1 {
            scene_id: "scene-1".into(),
            view_digest: digest('1'),
        },
        policy_digest: digest('f'),
        presentation_digest: digest('a'),
        commit_seq: "31".into(),
        status: OperationalStatus::Accepted,
    };
    let command = ExplicitAbstentionCommandV1 {
        contract: "joshi.operator.explicit_abstention".into(),
        schema_version: 1,
        abstention_id: "choice-command-1".into(),
        idempotency_key: "choice-key-1".into(),
        episode_launch_id: "launch-1".into(),
        client_session_id: "pairing-session-1".into(),
        client_command_seq: "1".into(),
        cockpit_publication_id: "cockpit-publication-1".into(),
        scene: SceneReferenceV1 {
            scene_id: "scene-1".into(),
            view_digest: digest('1'),
        },
        presentation: PresentationReferenceV1 {
            presentation_id: "presentation-1".into(),
            presentation_digest: digest('a'),
        },
        assignment_id: "assignment-1".into(),
        as_of_digest: digest('3'),
        choice_universe_digest: digest('4'),
        decision_deadline: "2026-08-17T14:36:00.000000Z".into(),
        reason: ExplicitAbstentionReason::InsufficientEvidence,
        issued_at: "2026-08-17T14:06:00.000000Z".into(),
        client_clock: ClientClockV1 {
            clock_id: "glass-session-1".into(),
            monotonic_ns: "360000000000".into(),
        },
        authority_class: "evidence_only".into(),
        effect_ceiling: "observe_only".into(),
    };
    let command_bytes = serde_json::to_vec(&command).expect("command bytes");
    let receipt = ExplicitAbstentionReceiptV1 {
        contract: "joshi.store.explicit_abstention_receipt".into(),
        schema_version: 1,
        catalog_id: "catalog-v7".into(),
        catalog_schema: "joshi.sqlite.v7".into(),
        batch_id: "abstention-batch-1".into(),
        abstention_id: "choice-command-1".into(),
        episode_launch_id: "launch-1".into(),
        scene: command.scene.clone(),
        presentation: command.presentation.clone(),
        choice_universe_digest: command.choice_universe_digest.clone(),
        abstention_digest: Sha256Digest::of_bytes(&command_bytes),
        commit_seq: "40".into(),
        status: OperationalStatus::Accepted,
    };
    let receipt_bytes = serde_json::to_vec(&receipt).expect("receipt bytes");
    OwnedPrerequisites {
        envelope,
        protocol_bytes,
        launch_bytes,
        presentation,
        command,
        command_bytes,
        receipt,
        receipt_bytes,
    }
}

fn basis(
    launch: &EpisodeLaunchRegistrationV1,
    command_bytes: &[u8],
    receipt: &ExplicitAbstentionReceiptV1,
    receipt_bytes: &[u8],
) -> EpisodeBasisV1 {
    EpisodeBasisV1 {
        protocol_registration_id: launch.protocol_registration_id.clone(),
        protocol_digest: launch.protocol_digest.clone(),
        privacy_digest: digest('d'),
        launch_id: launch.launch_id.clone(),
        launch_digest: Sha256Digest::of_bytes(
            &serde_json::to_vec(launch).expect("launch canonical bytes"),
        ),
        prospective_session_id: launch.prospective_session_id.clone(),
        t0: launch.t0.clone(),
        scheduled_session_end: "2026-08-17T15:00:00.000000Z".into(),
        outcome_horizon: "2026-08-17T15:30:00.000000Z".into(),
        knowledge_deadline: "2026-08-17T15:45:00.000000Z".into(),
        catalog_cutoff_commit_seq: launch.catalog_cutoff_commit_seq.clone(),
        census_artifact_id: launch.census.artifact_id.clone(),
        census_artifact_digest: launch.census.artifact_digest.clone(),
        cockpit_publication_id: launch.cockpit.publication_id.clone(),
        cockpit_publication_digest: launch.cockpit.publication_digest.clone(),
        scene_id: launch.scene.scene_id.clone(),
        view_digest: launch.scene.view_digest.clone(),
        presentation_id: launch.reserved_presentation_id.clone(),
        presentation_digest: digest('a'),
        assignment_id: launch.presentation.assignment_id.clone(),
        as_of_digest: launch.as_of_digest.clone(),
        choice_universe_digest: launch.choice_universe_digest.clone(),
        choice: ChoiceClosureV1::ExplicitAbstention {
            command_id: launch.reserved_command_id.clone(),
            command_digest: Sha256Digest::of_bytes(command_bytes),
            receipt_batch_id: receipt.batch_id.clone(),
            receipt_digest: Sha256Digest::of_bytes(receipt_bytes),
            receipt_commit_seq: receipt.commit_seq.clone(),
            reason: AbstentionReasonV1::InsufficientEvidence,
        },
        downstream: DownstreamReservationsV1 {
            hot_decision_id: launch.reserved_hot_decision_id.clone(),
            hot_intent_id: launch.reserved_hot_intent_id.clone(),
            outcome_occurrence_id: launch.reserved_outcome_id.clone(),
            interview_occurrence_id: launch.reserved_interview_id.clone(),
            export_request_id: launch.reserved_export_request_id.clone(),
            analysis_run_id: launch.reserved_analysis_run_id.clone(),
            artifact_import_id: launch.reserved_artifact_import_id.clone(),
        },
    }
}

#[allow(clippy::too_many_lines)]
fn goldens() -> GoldenSet {
    let OwnedPrerequisites {
        command_bytes,
        receipt,
        receipt_bytes,
        ..
    } = prerequisites();
    let envelope: SessionLaunchEnvelopeV1 =
        strict_json::parse(SESSION_LAUNCH, 64 * 1024).expect("session launch");
    let basis = basis(
        &envelope.registration,
        &command_bytes,
        &receipt,
        &receipt_bytes,
    );
    let session = SessionCloseV1 {
        contract: SESSION_CLOSE_CONTRACT.into(),
        schema_version: 1,
        session_close_id: "session-close-1".into(),
        basis: basis.clone(),
        closed_at: "2026-08-17T15:00:00.000000Z".into(),
        actual_duration_us: "3600000000".into(),
        completion_status: SessionCompletionStatus::CompleteOnSchedule,
        closing_cutoff_commit_seq: "80".into(),
        source: SourceSessionClosureV1 {
            source_receipts: vec![EvidenceReferenceV1 {
                evidence_id: "source-session-receipt-1".into(),
                evidence_digest: digest('b'),
                available_at: "2026-08-17T14:30:00.000000Z".into(),
                commit_seq: "50".into(),
            }],
            coverage_ids: vec!["coverage-session-1".into()],
            gap_ids: vec![],
            nonfixture_occurrence_count: "1".into(),
            support_status: SourceSupportStatus::Satisfied,
            spool_status: SpoolCloseStatus::CatalogAdmitted,
            budget_status: BudgetCloseStatus::WithinRegisteredBudget,
        },
        presentation: PresentationSessionClosureV1 {
            presentation_event_receipts: vec![EvidenceReferenceV1 {
                evidence_id: "presentation-event-receipt-1".into(),
                evidence_digest: digest('c'),
                available_at: "2026-08-17T14:00:01.000000Z".into(),
                commit_seq: "32".into(),
            }],
            visibility_gap_ids: vec![],
            open_interval_count: "0".into(),
        },
        hot_scope: HotScopeClosureV1::NotApplicableByAbstention {
            reserved_hot_decision_id: envelope.registration.reserved_hot_decision_id.clone(),
            reserved_hot_intent_id: envelope.registration.reserved_hot_intent_id.clone(),
        },
        final_contemporaneous_scene: artifact(
            "joshi.glass.view",
            "final-scene-production-1",
            "final-scene-1",
            'd',
            "79",
            "2026-08-17T15:00:00.000000Z",
        ),
        witnessed_replay: artifact(
            "joshi.glass.witnessed_replay",
            "replay-production-1",
            "witnessed-replay-1",
            'e',
            "79",
            "2026-08-17T15:00:00.000000Z",
        ),
        outcome_visibility: "not_revealed".into(),
        authority: AUTHORITY.into(),
        economic_claim: ECONOMIC_CLAIM.into(),
    };
    let knowledge = KnowledgeClosureV1 {
        contract: KNOWLEDGE_CLOSURE_CONTRACT.into(),
        schema_version: 1,
        knowledge_closure_id: "knowledge-closure-1".into(),
        basis: basis.clone(),
        outcome_occurrence_id: basis.downstream.outcome_occurrence_id.clone(),
        event_window_lower: basis.t0.clone(),
        event_window_upper: basis.outcome_horizon.clone(),
        event_window_semantics: "half_open_t0_inclusive_h_exclusive".into(),
        retrospective_state_at: basis.outcome_horizon.clone(),
        knowledge_deadline: basis.knowledge_deadline.clone(),
        cut: CatalogKnowledgeCutV1 {
            catalog_id: "catalog-v7".into(),
            catalog_schema: "joshi.sqlite.v7".into(),
            through_commit_seq: "100".into(),
            through_committed_at: "2026-08-17T15:44:00.000000Z".into(),
            selected_at: "2026-08-17T15:45:00.000000Z".into(),
            proof: KnowledgeCutProofV1::CatalogHeadAtSelection {
                head_commit_seq: "100".into(),
                head_observed_at: "2026-08-17T15:45:00.000000Z".into(),
            },
        },
        event_evidence: vec![EventEvidenceAtCutV1 {
            evidence: EvidenceReferenceV1 {
                evidence_id: "event-evidence-crossing-1".into(),
                evidence_digest: digest('1'),
                available_at: "2026-08-17T15:40:00.000000Z".into(),
                commit_seq: "95".into(),
            },
            event_time: EventTimeV1::Bounded {
                lower: "2026-08-17T15:29:59.000000Z".into(),
                upper: "2026-08-17T15:30:01.000000Z".into(),
            },
            disposition: EventEvidenceDisposition::IntervalCensored,
        }],
        state_evidence: vec![StateEvidenceAtCutV1 {
            evidence: EvidenceReferenceV1 {
                evidence_id: "state-missing-closure-1".into(),
                evidence_digest: digest('2'),
                available_at: "2026-08-17T15:44:00.000000Z".into(),
                commit_seq: "99".into(),
            },
            disposition: StateAtHDisposition::Missing,
        }],
        coverage_ids: vec!["coverage-outcome-1".into()],
        gap_ids: vec!["gap-outcome-1".into()],
        authority: AUTHORITY.into(),
        economic_claim: ECONOMIC_CLAIM.into(),
    };
    let session_bytes = canonical_bytes(&session).expect("session bytes");
    let knowledge_bytes = canonical_bytes(&knowledge).expect("knowledge bytes");
    let session_ref = content_artifact_reference(
        SESSION_CLOSE_CONTRACT,
        &session.session_close_id,
        &session_bytes,
        "81",
        "2026-08-17T15:00:01.000000Z",
    )
    .expect("session ref");
    let outcome = OutcomeAtHorizonV1 {
        contract: OUTCOME_CONTRACT.into(),
        schema_version: 1,
        outcome_occurrence_id: basis.downstream.outcome_occurrence_id.clone(),
        basis: basis.clone(),
        session_close: session_ref.clone(),
        knowledge_closure: content_artifact_reference(
            KNOWLEDGE_CLOSURE_CONTRACT,
            &knowledge.knowledge_closure_id,
            &knowledge_bytes,
            "101",
            "2026-08-17T15:45:01.000000Z",
        )
        .expect("knowledge ref"),
        produced_at: "2026-08-17T15:46:00.000000Z".into(),
        retrospective_scene: OutcomeEvidenceV1::NotApplicableByAbstention,
        selected_subject: None,
        lifecycle_venue: OutcomeEvidenceV1::NotApplicableByAbstention,
        mark: OutcomeEvidenceV1::NotApplicableByAbstention,
        exact_size_quote: QuoteOutcomeV1::NotApplicableByAbstention,
        whole_position_quote: QuoteOutcomeV1::NotApplicableByAbstention,
        external_wallet_effect: ExternalWalletEffectV1::NotApplicableByAbstention,
        coverage_ids: knowledge.coverage_ids.clone(),
        gap_ids: knowledge.gap_ids.clone(),
        censoring_present: true,
        interpretation: "descriptive_non_profit_no_win_loss".into(),
        authority: AUTHORITY.into(),
        economic_claim: ECONOMIC_CLAIM.into(),
    };
    let interview = InterviewDispositionV1 {
        contract: INTERVIEW_CONTRACT.into(),
        schema_version: 1,
        interview_occurrence_id: basis.downstream.interview_occurrence_id.clone(),
        basis,
        session_close: session_ref,
        disposition_at: "2026-08-17T15:01:00.000000Z".into(),
        disposition: InterviewDispositionKindV1::Declined,
        private_artifact_policy_digest: digest('d'),
        export_policy: "metadata_only_no_text".into(),
        authority: AUTHORITY.into(),
        economic_claim: ECONOMIC_CLAIM.into(),
    };
    GoldenSet {
        session,
        knowledge,
        outcome,
        interview,
    }
}

fn with_prerequisites<T>(callback: impl FnOnce(&EpisodePrerequisites<'_>) -> T) -> T {
    let OwnedPrerequisites {
        envelope,
        protocol_bytes,
        launch_bytes,
        presentation,
        command,
        command_bytes,
        receipt,
        receipt_bytes,
    } = prerequisites();
    callback(&EpisodePrerequisites {
        protocol: &envelope.protocol,
        exact_protocol_bytes: &protocol_bytes,
        protocol_receipt: &envelope.protocol_receipt,
        launch: &envelope.registration,
        exact_launch_bytes: &launch_bytes,
        launch_receipt: &envelope.receipt,
        presentation_receipt: &presentation,
        choice: QualifyingChoiceEvidence::ExplicitAbstention {
            command: &command,
            exact_command_bytes: &command_bytes,
            receipt: &receipt,
            exact_receipt_bytes: &receipt_bytes,
        },
    })
}

#[test]
fn exact_chain_validates_without_economic_authority() {
    let values = goldens();
    with_prerequisites(|prerequisites| {
        values
            .session
            .validate_against(prerequisites)
            .expect("session closure");
        values
            .knowledge
            .validate_against(prerequisites)
            .expect("knowledge closure");
        let session_bytes = canonical_bytes(&values.session).expect("session bytes");
        let knowledge_bytes = canonical_bytes(&values.knowledge).expect("knowledge bytes");
        values
            .outcome
            .validate_against(
                prerequisites,
                &values.session,
                &session_bytes,
                &values.knowledge,
                &knowledge_bytes,
            )
            .expect("outcome closure");
        values
            .interview
            .validate_against(prerequisites, &values.session, &session_bytes, None)
            .expect("interview disposition");
    });
}

#[test]
fn adversarial_future_knowledge_boundary_and_fabricated_abstention_exposure_refuse() {
    let values = goldens();
    let mut future = values.knowledge.clone();
    future.event_evidence[0].evidence.available_at = "2026-08-17T15:45:00.000001Z".into();
    assert!(future.validate().is_err());

    let mut snapped = values.knowledge.clone();
    snapped.event_evidence[0].disposition = EventEvidenceDisposition::Included;
    assert!(snapped.validate().is_err());

    let mut fabricated = values.outcome.clone();
    fabricated.mark = OutcomeEvidenceV1::Missing {
        reason: "no_mark".into(),
    };
    assert!(fabricated.validate().is_err());
}

#[test]
fn duplicate_unknown_and_authority_escalation_refuse() {
    let values = goldens();
    let bytes = canonical_bytes(&values.session).expect("bytes");
    let text = String::from_utf8(bytes).expect("utf8");
    let duplicate = text.replacen(
        "\"schemaVersion\":1",
        "\"schemaVersion\":1,\"schemaVersion\":1",
        1,
    );
    assert!(decode_session_close(duplicate.as_bytes()).is_err());
    let unknown = text.replacen(
        "\"sessionCloseId\"",
        "\"unknown\":true,\"sessionCloseId\"",
        1,
    );
    assert!(decode_session_close(unknown.as_bytes()).is_err());
    let escalated = text.replace(
        "\"authority\":\"read_only_no_execution\"",
        "\"authority\":\"trade\"",
    );
    assert!(decode_session_close(escalated.as_bytes()).is_err());
}

#[test]
fn hot_nomination_requires_launch_ids_subject_and_typed_closed_record() {
    let mut session = goldens().session;
    let subject = ChoiceMembershipReferenceV1 {
        subject_id: "asset:coin-a".into(),
        choice_universe_digest: session.basis.choice_universe_digest.clone(),
        membership_digest: digest('9'),
    };
    session.basis.choice = ChoiceClosureV1::Nomination {
        command_id: "choice-command-1".into(),
        command_digest: digest('7'),
        receipt_batch_id: "nomination-batch-1".into(),
        receipt_digest: digest('8'),
        receipt_commit_seq: "40".into(),
        subject: subject.clone(),
    };
    session.hot_scope = HotScopeClosureV1::Nomination {
        reserved_hot_decision_id: "hot-decision-1".into(),
        reserved_hot_intent_id: "hot-intent-future-1".into(),
        subject_id: subject.subject_id.clone(),
        decision: EvidenceReferenceV1 {
            evidence_id: "hot-decision-1".into(),
            evidence_digest: digest('4'),
            available_at: "2026-08-17T14:07:00.000000Z".into(),
            commit_seq: "41".into(),
        },
        intent: Box::new(artifact(
            "joshi.hot_scope_intent/v1",
            "hot-intent-future-1",
            "hot-intent-artifact-1",
            '5',
            "42",
            "2026-08-17T14:07:01.000000Z",
        )),
        terminal_records: vec![artifact(
            "joshi.hot_scope_closed/v1",
            "hot-close-production-1",
            "hot-closed-artifact-1",
            '6',
            "78",
            "2026-08-17T15:00:00.000000Z",
        )],
        terminal_status: HotTerminalStatus::Closed,
    };
    session.validate().expect("typed nomination close");

    let mut wrong_subject = session.clone();
    if let HotScopeClosureV1::Nomination { subject_id, .. } = &mut wrong_subject.hot_scope {
        *subject_id = "asset:substituted".into();
    }
    assert!(wrong_subject.validate().is_err());

    let mut wrong_reservation = session.clone();
    if let HotScopeClosureV1::Nomination {
        reserved_hot_intent_id,
        ..
    } = &mut wrong_reservation.hot_scope
    {
        *reserved_hot_intent_id = "hot-intent-other".into();
    }
    assert!(wrong_reservation.validate().is_err());

    let mut false_closed = session;
    if let HotScopeClosureV1::Nomination {
        terminal_records, ..
    } = &mut false_closed.hot_scope
    {
        terminal_records[0].contract = "joshi.hot_scope_degraded/v1".into();
    }
    assert!(false_closed.validate().is_err());
}

#[test]
fn recorded_interview_enforces_hidden_first_and_text_only_policy() {
    let values = goldens();
    let session_bytes = canonical_bytes(&values.session).expect("session bytes");
    let outcome_bytes = canonical_bytes(&values.outcome).expect("outcome bytes");
    let mut interview = values.interview;
    interview.disposition_at = "2026-08-17T15:50:00.000000Z".into();
    let text_blob = PrivateBlobReferenceV1 {
        blob_id: "private-interview-hidden-1".into(),
        blob_digest: digest('5'),
        byte_length: "12".into(),
        content_type: "text/plain;charset=utf-8".into(),
        protection: "operator_private_local_only".into(),
        retention: "hold_no_automatic_deletion".into(),
    };
    interview.disposition = InterviewDispositionKindV1::Recorded {
        outcome_hidden: Box::new(OutcomeHiddenSegmentV1 {
            segment_id: "interview-hidden-1".into(),
            prompt_digest: digest('6'),
            started_at: "2026-08-17T15:01:00.000000Z".into(),
            closed_at: "2026-08-17T15:05:00.000000Z".into(),
            information_cutoff_commit_seq: "40".into(),
            witnessed_scene_id: "scene-1".into(),
            blob: text_blob.clone(),
            outcome_visibility: "hidden".into(),
        }),
        outcome_aware: Some(Box::new(OutcomeAwareSegmentV1 {
            segment_id: "interview-aware-1".into(),
            prompt_digest: digest('7'),
            started_at: "2026-08-17T15:46:00.000000Z".into(),
            outcome_revealed_at: "2026-08-17T15:46:00.000000Z".into(),
            closed_at: "2026-08-17T15:50:00.000000Z".into(),
            outcome: content_artifact_reference(
                OUTCOME_CONTRACT,
                "outcome-1",
                &outcome_bytes,
                "102",
                "2026-08-17T15:46:01.000000Z",
            )
            .expect("outcome ref"),
            retrospective_scene_id: "retrospective-scene-1".into(),
            blob: PrivateBlobReferenceV1 {
                blob_id: "private-interview-aware-1".into(),
                ..text_blob
            },
        })),
    };
    with_prerequisites(|prerequisites| {
        interview
            .validate_against(
                prerequisites,
                &values.session,
                &session_bytes,
                Some((&values.outcome, &outcome_bytes)),
            )
            .expect("recorded interview");
    });

    let mut early_reveal = interview.clone();
    if let InterviewDispositionKindV1::Recorded {
        outcome_aware: Some(aware),
        ..
    } = &mut early_reveal.disposition
    {
        aware.started_at = "2026-08-17T15:04:00.000000Z".into();
        aware.outcome_revealed_at = "2026-08-17T15:04:00.000000Z".into();
    }
    assert!(early_reveal.validate().is_err());

    let mut audio = interview;
    if let InterviewDispositionKindV1::Recorded { outcome_hidden, .. } = &mut audio.disposition {
        outcome_hidden.blob.content_type = "audio/mpeg".into();
    }
    assert!(audio.validate().is_err());
}

#[test]
fn knowledge_cut_proof_and_content_reference_substitution_refuse() {
    let values = goldens();
    let mut wrong_head = values.knowledge.clone();
    if let KnowledgeCutProofV1::CatalogHeadAtSelection {
        head_commit_seq, ..
    } = &mut wrong_head.cut.proof
    {
        *head_commit_seq = "99".into();
    }
    assert!(wrong_head.validate().is_err());

    let mut leading_zero = values.knowledge;
    leading_zero.cut.through_commit_seq = "0100".into();
    assert!(leading_zero.validate().is_err());

    let mut substituted = values.outcome;
    substituted.session_close.artifact_digest = digest('0');
    let session = goldens().session;
    let knowledge = goldens().knowledge;
    with_prerequisites(|prerequisites| {
        assert!(
            substituted
                .validate_against(
                    prerequisites,
                    &session,
                    &canonical_bytes(&session).expect("session"),
                    &knowledge,
                    &canonical_bytes(&knowledge).expect("knowledge"),
                )
                .is_err()
        );
    });
}

#[test]
fn adversarial_fixture_names_every_enforced_case() {
    let fixture: serde_json::Value = serde_json::from_slice(ADVERSARIAL_FIXTURE).expect("fixture");
    let cases = fixture["cases"].as_array().expect("cases");
    assert_eq!(cases.len(), 14);
    assert!(cases.iter().all(|case| case["expected"] == "refuse"));
}

fn canonical_fixture(bytes: &[u8]) -> &[u8] {
    bytes
        .strip_suffix(b"\n")
        .expect("fixture has one repository terminal LF")
}

#[test]
fn fixture_payloads_are_exact_canonical_goldens() {
    let values = goldens();
    for (name, bytes, fixture, length, digest) in [
        (
            "session_close",
            canonical_bytes(&values.session).expect("session"),
            canonical_fixture(SESSION_CLOSE_FIXTURE),
            3749,
            "sha256:b12a6286255eb9710390f1114b3aefac56c6fd607fa0f9c49c36d1862fbbee8e",
        ),
        (
            "knowledge_closure",
            canonical_bytes(&values.knowledge).expect("knowledge"),
            canonical_fixture(KNOWLEDGE_FIXTURE),
            3402,
            "sha256:4eb1e51903d95a7dabf7a19c8d58ccf012991a45577e4460b253eb5970449d51",
        ),
        (
            "outcome_at_horizon",
            canonical_bytes(&values.outcome).expect("outcome"),
            canonical_fixture(OUTCOME_FIXTURE),
            3391,
            "sha256:e4c8cd094e98565506e9f5418251bb393f61390e6dcb701d73b595030a27746d",
        ),
        (
            "interview_disposition",
            canonical_bytes(&values.interview).expect("interview"),
            canonical_fixture(INTERVIEW_FIXTURE),
            2687,
            "sha256:41a775288fa3a43d3035b14dded07f7c463717f858bd530080807d22a2e86ed7",
        ),
    ] {
        assert_eq!(bytes, fixture, "{name} bytes");
        assert_eq!(bytes.len(), length, "{name} length");
        assert_eq!(
            Sha256Digest::of_bytes(&bytes).as_str(),
            digest,
            "{name} digest"
        );
    }
    assert_eq!(
        decode_session_close(canonical_fixture(SESSION_CLOSE_FIXTURE)).expect("session fixture"),
        values.session
    );
    assert_eq!(
        decode_knowledge_closure(canonical_fixture(KNOWLEDGE_FIXTURE)).expect("knowledge fixture"),
        values.knowledge
    );
    assert_eq!(
        decode_outcome_at_horizon(canonical_fixture(OUTCOME_FIXTURE)).expect("outcome fixture"),
        values.outcome
    );
    assert_eq!(
        decode_interview_disposition(canonical_fixture(INTERVIEW_FIXTURE))
            .expect("interview fixture"),
        values.interview
    );
}

#[allow(dead_code)]
fn _type_anchor(_: &EpisodeProtocolRegistrationV1) {}
