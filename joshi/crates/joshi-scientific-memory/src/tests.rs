use super::*;
use std::{collections::BTreeSet, fmt};

fn id<T: FromId>(value: &str) -> T {
    T::make(value)
}

trait FromId: Sized {
    fn make(value: &str) -> Self;
}

macro_rules! from_id {
    ($($type:ty),+ $(,)?) => { $(impl FromId for $type { fn make(value: &str) -> Self { <$type>::new(value).unwrap() } })+ };
}

from_id!(
    SceneId,
    PresentationId,
    PresentationOccurrenceId,
    ActId,
    SessionId,
    EpisodeId,
    SegmentId,
    CorrectionId,
    OntologyVersionId,
    AssertionId,
    ReplayId,
    KnowledgeClosureId,
    OutcomeId,
    InterviewId
);

fn digest(label: &str) -> Digest {
    Digest::of_bytes(label.as_bytes())
}

fn tick(value: u64) -> LogicalSessionTick {
    LogicalSessionTick::new(value).unwrap()
}

fn verified_memory() -> MemoryKernel {
    let mut memory = MemoryKernel::new();
    memory.mark_store_verified_for_tests();
    memory
}

fn scene() -> SceneRef {
    SceneRef {
        scene_id: id("scene-1"),
        scene_digest: digest("scene"),
        catalog_cutoff: CatalogCommitSeq::new(10).unwrap(),
    }
}

fn gap() -> PresentationBinding {
    PresentationBinding::Gap(PresentationGap {
        gap_id: "gap-1".into(),
        scene: Some(scene()),
        reason: PresentationGapReason::CaptureFailed,
        detected_at: tick(11),
    })
}

fn act(act_id: &str, presentation: PresentationBinding) -> MemoryOccurrence {
    MemoryOccurrence::OperatorAct(OperatorAct {
        act_id: id(act_id),
        session_id: id("session-1"),
        occurred_at: tick(12),
        scene: SceneBinding::Committed(scene()),
        presentation,
        kind: ActKind::Mark,
        subject: Some("mint-1".into()),
        assertion: Some(OperatorAssertion {
            assertion_id: id("assertion-1"),
            disposition: AssertionDisposition::CannotArticulate,
        }),
    })
}

fn presentation() -> PresentationBinding {
    PresentationBinding::Occurrence(PresentationOccurrenceRef {
        occurrence_id: id("presentation-occurrence-1"),
        presentation_id: id("presentation-1"),
        scene: scene(),
        render_digest: digest("render"),
        viewport: "1280x720".into(),
        focus: "candidate".into(),
        occurred_at: tick(11),
    })
}

fn episode() -> MemoryOccurrence {
    MemoryOccurrence::Episode(Episode {
        episode_id: id("episode-1"),
        session_id: id("session-1"),
        act_ids: vec![id("act-episode")],
        decision_cutoff: tick(20),
        started_at: tick(12),
        ended_at: Some(tick(20)),
        completeness: EpisodeCompleteness::Partial,
        segments: vec![
            EpisodeSegment {
                segment_id: id("segment-1"),
                start_at: tick(12),
                end_at: Some(tick(16)),
                path: EpisodePath::FlatWatch,
                effect: EffectStatus::Unknown {
                    reason: "manual effect not witnessed".into(),
                },
                lot: LotAssociation::Unresolved {
                    reason: "no lot association".into(),
                },
            },
            EpisodeSegment {
                segment_id: id("segment-2"),
                start_at: tick(16),
                end_at: Some(tick(20)),
                path: EpisodePath::NoTrade,
                effect: EffectStatus::NotApplicableByNoTrade,
                lot: LotAssociation::NotApplicable,
            },
        ],
    })
}

#[test]
fn act_is_retained_even_when_presentation_is_missing() {
    let mut memory = verified_memory();
    let occurrence = act("act-gap", gap());
    let TransitionOutcome::Applied { semantic_act } = memory.append(occurrence).unwrap() else {
        panic!("new act")
    };
    assert_eq!(semantic_act.unwrap().append_sequence, 1);
    assert!(matches!(
        memory.research_admission(&id("act-gap")),
        ResearchAdmission::Refused { .. }
    ));
}

#[test]
fn external_manual_escape_is_reasoned_intention_only() {
    let mut memory = MemoryKernel::new();
    let mut occurrence = act("act-escape", gap());
    let MemoryOccurrence::OperatorAct(value) = &mut occurrence else {
        unreachable!()
    };
    value.kind = ActKind::ExternalManualExecutionEscape {
        reason: ExternalManualExecutionEscapeReason::new(
            "operator exited outside the managed path",
        )
        .unwrap(),
    };
    assert!(value.kind.is_action_intention());
    assert!(matches!(
        memory.append(occurrence),
        Ok(TransitionOutcome::Applied { .. })
    ));
}

#[test]
fn manual_escape_canonical_golden_is_frozen() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../fixtures/scientific-memory/adversarial.v1.json"
    ))
    .unwrap();
    let golden = &fixture["canonicalGoldens"][0];
    assert_eq!(
        golden["name"],
        "external_manual_execution_escape_with_presentation_gap"
    );
    let bytes = golden["canonicalOccurrence"].as_str().unwrap().as_bytes();
    let occurrence = parse_memory_occurrence_exact(bytes).unwrap();
    assert_eq!(serde_json::to_vec(&occurrence).unwrap(), bytes);
    assert_eq!(
        occurrence.exact_digest().unwrap().as_str(),
        golden["digest"].as_str().unwrap()
    );
}

#[test]
fn exact_presentation_admits_and_mismatch_refuses() {
    let mut memory = verified_memory();
    memory.append(act("act-good", presentation())).unwrap();
    assert!(matches!(
        memory.research_admission(&id("act-good")),
        ResearchAdmission::Admitted { .. }
    ));
    let wrong = PresentationBinding::Occurrence(PresentationOccurrenceRef {
        scene: SceneRef {
            scene_id: id("scene-other"),
            ..scene()
        },
        occurrence_id: id("presentation-occurrence-2"),
        presentation_id: id("presentation-2"),
        render_digest: digest("render-2"),
        viewport: "1280x720".into(),
        focus: "candidate".into(),
        occurred_at: tick(11),
    });
    assert_eq!(
        memory.append(act("act-wrong", wrong)),
        Err(MemoryError::ScenePresentationMismatch)
    );
}

#[test]
fn unverified_matching_scene_stays_unqualified_and_gap_repair_is_separate() {
    let mut memory = MemoryKernel::new();
    memory.append(act("act-unverified", gap())).unwrap();
    let refusal = memory.research_admission(&id("act-unverified"));
    assert!(
        matches!(refusal, ResearchAdmission::Refused { reasons } if reasons.contains(&ResearchRefusal::UnverifiedSemantic))
    );

    let mut verified = verified_memory();
    verified.append(act("act-repair", gap())).unwrap();
    verified
        .append(MemoryOccurrence::PresentationGapRepair(
            PresentationGapRepair {
                repair_id: id("repair-1"),
                gap_id: "gap-1".into(),
                replacement: match presentation() {
                    PresentationBinding::Occurrence(value) => value,
                    PresentationBinding::Gap(_) => unreachable!(),
                },
                recorded_at: tick(13),
            },
        ))
        .unwrap();
    assert!(matches!(
        verified.research_admission(&id("act-repair")),
        ResearchAdmission::Admitted { .. }
    ));
    assert_eq!(verified.occurrences().count(), 2);
}

#[derive(Debug)]
struct EchoStoreError;

impl fmt::Display for EchoStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("echo store failure")
    }
}

impl std::error::Error for EchoStoreError {}

struct EchoStore;

impl ScientificMemoryStorePort for EchoStore {
    type Error = EchoStoreError;

    fn append_memory_occurrence(
        &mut self,
        request: &MemoryStoreAppendRequestV1,
    ) -> Result<(), Self::Error> {
        assert!(parse_memory_occurrence_exact(request.occurrence_bytes()).is_ok());
        Ok(())
    }
}

#[test]
fn a_caller_implemented_port_cannot_upgrade_unverified_memory() {
    let occurrence = act("act-port-echo", presentation());
    let request = MemoryStoreAppendRequestV1::from_occurrence(&occurrence).unwrap();
    let mut store = EchoStore;
    store.append_memory_occurrence(&request).unwrap();

    let mut memory = MemoryKernel::new();
    memory.append(occurrence).unwrap();
    assert!(matches!(
        memory.research_admission(&id("act-port-echo")),
        ResearchAdmission::Refused { reasons }
            if reasons == BTreeSet::from([ResearchRefusal::UnverifiedSemantic])
    ));
}

#[test]
fn corrections_and_ontology_are_append_only() {
    let mut memory = MemoryKernel::new();
    memory.append(act("act-corrected", presentation())).unwrap();
    memory
        .append(MemoryOccurrence::ActCorrection(ActCorrection {
            correction_id: id("correction-1"),
            act_id: id("act-corrected"),
            corrected_kind: Some(ActKind::Inspect),
            corrected_subject: Some("mint-2".into()),
            reason: "operator correction".into(),
            recorded_at: tick(13),
        }))
        .unwrap();
    memory
        .append(MemoryOccurrence::OntologyVersion(OntologyVersion {
            version_id: id("ontology-1"),
            parent_version_id: None,
            effective_at: tick(14),
            mappings: vec![OntologyMapping {
                stable_kind: ActKind::Mark,
                label: "mark".into(),
            }],
        }))
        .unwrap();
    assert_eq!(memory.occurrences().count(), 3);
}

#[test]
fn episode_is_bounded_and_no_trade_does_not_claim_effect() {
    let mut memory = MemoryKernel::new();
    memory.append(act("act-episode", presentation())).unwrap();
    memory.append(episode()).unwrap();
    assert_eq!(memory.occurrences().count(), 2);
    let invalid = MemoryOccurrence::Episode(Episode {
        episode_id: id("episode-bad"),
        session_id: id("session-1"),
        act_ids: vec![id("act-episode")],
        decision_cutoff: tick(20),
        started_at: tick(20),
        ended_at: None,
        completeness: EpisodeCompleteness::Complete,
        segments: vec![],
    });
    assert_eq!(memory.append(invalid), Err(MemoryError::EpisodeBounds));
}

#[test]
fn effects_and_complete_status_require_store_witness_and_session_is_terminal() {
    let mut memory = MemoryKernel::new();
    memory.append(act("act-terminal", presentation())).unwrap();
    memory
        .append(MemoryOccurrence::SessionClose(SessionClose {
            session_id: id("session-1"),
            closed_at: tick(21),
            status: SessionCloseStatus::IncompleteLate,
            cutoff: tick(14),
            recorded_at: tick(21),
            committed_at: tick(22),
            qualification: Qualification::UnverifiedSemantic,
        }))
        .unwrap();
    assert_eq!(
        memory.append(act("act-after-close", presentation())),
        Err(MemoryError::SessionTerminal)
    );
    let complete = MemoryOccurrence::Episode(Episode {
        episode_id: id("episode-complete"),
        session_id: id("session-1"),
        act_ids: vec![id("act-terminal")],
        decision_cutoff: tick(20),
        started_at: tick(12),
        ended_at: Some(tick(20)),
        completeness: EpisodeCompleteness::Complete,
        segments: vec![],
    });
    assert_eq!(
        memory.append(complete),
        Err(MemoryError::UnverifiedSemantic)
    );
    let late_partial = MemoryOccurrence::Episode(Episode {
        episode_id: id("episode-late"),
        session_id: id("session-1"),
        act_ids: vec![id("act-terminal")],
        decision_cutoff: tick(20),
        started_at: tick(12),
        ended_at: Some(tick(20)),
        completeness: EpisodeCompleteness::Partial,
        segments: vec![],
    });
    assert_eq!(
        memory.append(late_partial),
        Err(MemoryError::SessionTerminal)
    );
}

#[test]
fn append_order_is_not_lexicographic_identity_order() {
    let mut memory = MemoryKernel::new();
    memory.append(act("z-act", gap())).unwrap();
    memory.append(act("a-act", gap())).unwrap();
    let ids: Vec<String> = memory
        .occurrences()
        .map(MemoryOccurrence::occurrence_id)
        .collect();
    assert_eq!(ids, vec!["act:z-act", "act:a-act"]);
}

#[test]
fn two_pass_replay_and_knowledge_outcome_closure_are_distinct() {
    let mut memory = MemoryKernel::new();
    memory.append(act("act-episode", presentation())).unwrap();
    memory.append(episode()).unwrap();
    let hidden = MemoryOccurrence::Replay(ReplayArtifact {
        replay_id: id("replay-hidden"),
        episode_id: id("episode-1"),
        phase: ReplayPhase::OutcomeHiddenReconstruction,
        visibility: OutcomeVisibility::Hidden,
        content_role: ReplayContentRole::OutcomeHiddenReconstruction,
        information_cutoff: tick(12),
        witnessed_scene: Some(scene()),
        blob_digest: digest("hidden"),
        recorded_at: tick(21),
        qualification: Qualification::UnverifiedSemantic,
    });
    memory.append(hidden).unwrap();
    let leak = MemoryOccurrence::Replay(ReplayArtifact {
        replay_id: id("replay-leak"),
        episode_id: id("episode-1"),
        phase: ReplayPhase::OutcomeHiddenReconstruction,
        visibility: OutcomeVisibility::Revealed {
            reveal_id: id("reveal-1"),
            revealed_at: tick(22),
        },
        content_role: ReplayContentRole::RetrospectiveInterpretation,
        information_cutoff: tick(12),
        witnessed_scene: None,
        blob_digest: digest("leak"),
        recorded_at: tick(22),
        qualification: Qualification::UnverifiedSemantic,
    });
    assert_eq!(memory.append(leak), Err(MemoryError::OutcomeLeak));
    memory
        .append(MemoryOccurrence::SessionClose(SessionClose {
            session_id: id("session-1"),
            closed_at: tick(21),
            status: SessionCloseStatus::IncompleteLate,
            cutoff: tick(20),
            recorded_at: tick(21),
            committed_at: tick(22),
            qualification: Qualification::UnverifiedSemantic,
        }))
        .unwrap();
    memory
        .append(MemoryOccurrence::KnowledgeClosure(KnowledgeClosure {
            closure_id: id("knowledge-1"),
            episode_id: id("episode-1"),
            knowledge_deadline: tick(25),
            evidence_cutoff: tick(24),
            gap_ids: vec!["gap-outcome".into()],
            state: KnowledgeState::Partial,
            recorded_at: tick(26),
            committed_at: tick(27),
            qualification: Qualification::UnverifiedSemantic,
        }))
        .unwrap();
    memory
        .append(MemoryOccurrence::OutcomeAtHorizon(OutcomeAtHorizon {
            outcome_id: id("outcome-1"),
            episode_id: id("episode-1"),
            horizon: tick(30),
            knowledge_closure_id: id("knowledge-1"),
            state: OutcomeState::Missing {
                reason: "source gap".into(),
            },
            interpretation: None,
            outcome_known_at: tick(31),
            recorded_at: tick(32),
            committed_at: tick(33),
            qualification: Qualification::UnverifiedSemantic,
        }))
        .unwrap();
    assert_eq!(memory.occurrences().count(), 6);
}

#[test]
fn fixture_chain_is_exact_and_censored_without_outcome_upgrade() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../fixtures/scientific-memory/adversarial.v1.json"
    ))
    .unwrap();
    let mut memory = MemoryKernel::new();
    for value in fixture["goldenChain"]["occurrences"].as_array().unwrap() {
        let bytes = value.as_str().unwrap().as_bytes();
        let occurrence = parse_memory_occurrence_exact(bytes).unwrap();
        assert_eq!(serde_json::to_vec(&occurrence).unwrap(), bytes);
        memory.append(occurrence).unwrap();
    }
    assert_eq!(memory.occurrences().count(), 6);
    assert!(matches!(
        memory.research_admission(&id("act-episode")),
        ResearchAdmission::Refused { reasons }
            if reasons.contains(&ResearchRefusal::UnverifiedSemantic)
    ));
}

#[test]
fn exact_retry_is_idempotent_and_changed_bytes_conflict() {
    let mut memory = MemoryKernel::new();
    let occurrence = act("act-retry", gap());
    assert!(matches!(
        memory.append(occurrence.clone()),
        Ok(TransitionOutcome::Applied { .. })
    ));
    assert_eq!(memory.append(occurrence), Ok(TransitionOutcome::Duplicate));
    let changed = act("act-retry", presentation());
    assert!(matches!(
        memory.append(changed),
        Err(MemoryError::IdentityConflict(_))
    ));
}

#[test]
fn strict_occurrence_parser_rejects_unknown_fields() {
    let bytes = serde_json::to_vec(&act("act-parse", gap())).unwrap();
    assert!(parse_memory_occurrence_exact(&bytes).is_ok());
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    value
        .as_object_mut()
        .unwrap()
        .insert("future".into(), serde_json::Value::Bool(true));
    assert!(parse_memory_occurrence_exact(&serde_json::to_vec(&value).unwrap()).is_err());
}

#[test]
fn strict_occurrence_parser_rejects_noncanonical_ticks() {
    let bytes = serde_json::to_vec(&act("act-time-parse", gap())).unwrap();
    for invalid in [
        serde_json::json!(0),
        serde_json::json!("0"),
        serde_json::json!("01"),
        serde_json::json!("12x"),
    ] {
        let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        value["value"]["occurredAt"] = invalid;
        assert!(parse_memory_occurrence_exact(&serde_json::to_vec(&value).unwrap()).is_err());
    }
}

#[test]
fn strict_occurrence_parser_rejects_invalid_ids() {
    let bytes = serde_json::to_vec(&act("act-id-parse", gap())).unwrap();
    for invalid in [
        serde_json::json!(""),
        serde_json::json!(" padded"),
        serde_json::json!("padded "),
        serde_json::json!("bad\u{0000}id"),
    ] {
        let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        value["value"]["actId"] = invalid;
        assert!(parse_memory_occurrence_exact(&serde_json::to_vec(&value).unwrap()).is_err());
    }
}

#[test]
fn positive_closures_are_store_qualified_only() {
    let mut memory = MemoryKernel::new();
    memory.append(act("act-episode", presentation())).unwrap();
    memory.append(episode()).unwrap();
    memory
        .append(MemoryOccurrence::SessionClose(SessionClose {
            session_id: id("session-1"),
            closed_at: tick(21),
            status: SessionCloseStatus::Complete,
            cutoff: tick(20),
            recorded_at: tick(21),
            committed_at: tick(22),
            qualification: Qualification::UnverifiedSemantic,
        }))
        .unwrap();
    assert_eq!(
        memory.append(MemoryOccurrence::KnowledgeClosure(KnowledgeClosure {
            closure_id: id("closed-knowledge"),
            episode_id: id("episode-1"),
            knowledge_deadline: tick(25),
            evidence_cutoff: tick(24),
            gap_ids: vec![],
            state: KnowledgeState::Closed,
            recorded_at: tick(26),
            committed_at: tick(27),
            qualification: Qualification::UnverifiedSemantic,
        })),
        Err(MemoryError::UnverifiedSemantic)
    );
}
