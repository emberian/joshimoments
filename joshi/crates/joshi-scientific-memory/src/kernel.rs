use crate::model::{
    ActCorrection, EffectStatus, Episode, EpisodeCompleteness, EpisodePath, KnowledgeClosure,
    MemoryOccurrence, OntologyVersion, OperatorAct, PresentationBinding, PresentationGapRepair,
    ReplayArtifact, ReplayContentRole, ReplayPhase, SceneBinding, SessionClose, validate_text,
};
use crate::{ActId, Digest, EpisodeId, KnowledgeState};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

/// Semantic errors that refuse an append before it enters the durable prefix.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum MemoryError {
    #[error("occurrence identity conflict: {0}")]
    IdentityConflict(String),
    #[error("unknown referenced act: {0}")]
    UnknownAct(ActId),
    #[error("unknown referenced episode: {0}")]
    UnknownEpisode(EpisodeId),
    #[error("unknown knowledge closure")]
    UnknownKnowledgeClosure,
    #[error("scene and presentation references do not close")]
    ScenePresentationMismatch,
    #[error("presentation gap is not admissible for scene-qualified research")]
    PresentationGap,
    #[error("invalid timing or ordering")]
    Timing,
    #[error("invalid bounded text: {0}")]
    Text(String),
    #[error("episode path is not bounded")]
    EpisodeBounds,
    #[error("episode segment overlaps or is unsorted")]
    EpisodeOrder,
    #[error("outcome-hidden replay contains retrospective information")]
    OutcomeLeak,
    #[error("knowledge closure is not closed by its deadline")]
    KnowledgeNotClosed,
    #[error("outcome requires a knowledge closure")]
    OutcomeNeedsKnowledge,
    #[error("session close has no session evidence")]
    UnknownSession,
    #[error("session already has a close")]
    DuplicateSessionClose,
    #[error("ontology parent is unknown")]
    UnknownOntologyParent,
    #[error("session is terminal")]
    SessionTerminal,
    #[error("unverified semantic fact cannot qualify")]
    UnverifiedSemantic,
    #[error("presentation gap repair has no matching gap")]
    UnknownPresentationGap,
}

/// A scene-qualified research refusal remains distinct from durable act capture.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ResearchRefusal {
    MissingScene,
    MissingPresentation,
    PresentationSceneMismatch,
    UnverifiedSemantic,
}

/// Result of checking one retained act for scene-bound research.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ResearchAdmission {
    Admitted {
        scene_id: String,
        presentation_id: String,
    },
    Refused {
        reasons: BTreeSet<ResearchRefusal>,
    },
}

/// Unverified semantic receipt; it is not a store durability or qualification receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnverifiedSemanticAct {
    pub act_id: ActId,
    pub occurrence_digest: Digest,
    pub append_sequence: u64,
}

/// Transition response. Exact retries return `Duplicate` without a second act.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TransitionOutcome {
    Applied {
        semantic_act: Option<UnverifiedSemanticAct>,
    },
    Duplicate,
}

/// Compatibility name for callers that call an append a transition.
pub type Transition = TransitionOutcome;

/// Pure append-only scientific memory kernel.
#[derive(Clone, Debug, Default)]
pub struct MemoryKernel {
    occurrences: BTreeMap<String, (Digest, MemoryOccurrence)>,
    acts: BTreeMap<ActId, OperatorAct>,
    episodes: BTreeMap<EpisodeId, Episode>,
    knowledge: BTreeMap<crate::KnowledgeClosureId, KnowledgeClosure>,
    replays: BTreeMap<crate::ReplayId, ReplayArtifact>,
    outcomes: BTreeMap<crate::OutcomeId, crate::OutcomeAtHorizon>,
    sessions_closed: BTreeSet<crate::SessionId>,
    ontology_versions: BTreeSet<crate::OntologyVersionId>,
    presentation_repairs: BTreeMap<String, PresentationGapRepair>,
    append_order: Vec<String>,
    store_verified: bool,
    last_recorded_at: Option<crate::LogicalSessionTick>,
}

impl MemoryKernel {
    /// Creates an empty memory prefix.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[cfg(test)]
    pub(crate) fn mark_store_verified_for_tests(&mut self) {
        self.store_verified = true;
    }

    /// Appends one semantic occurrence. Operator acts receive an immediate unverified semantic result.
    ///
    /// # Errors
    ///
    /// Returns an error for changed same-ID bytes, unknown references, missing closure, timing
    /// regressions, malformed episodes, or outcome leakage into hidden replay.
    pub fn append(
        &mut self,
        occurrence: MemoryOccurrence,
    ) -> Result<TransitionOutcome, MemoryError> {
        let id = occurrence.occurrence_id();
        let digest = occurrence
            .exact_digest()
            .map_err(|_| MemoryError::Text("occurrence serialization failed".into()))?;
        if let Some((existing, _)) = self.occurrences.get(&id) {
            if existing == &digest {
                return Ok(TransitionOutcome::Duplicate);
            }
            return Err(MemoryError::IdentityConflict(id));
        }
        self.validate(&occurrence)?;
        let semantic_act = match &occurrence {
            MemoryOccurrence::OperatorAct(act) => Some(UnverifiedSemanticAct {
                act_id: act.act_id.clone(),
                occurrence_digest: digest.clone(),
                append_sequence: self.append_order.len() as u64 + 1,
            }),
            _ => None,
        };
        let occurrence_time = Self::occurrence_time(&occurrence);
        self.apply(occurrence.clone());
        self.append_order.push(id.clone());
        self.occurrences.insert(id, (digest, occurrence));
        self.last_recorded_at = Some(
            self.last_recorded_at
                .map_or(occurrence_time, |last| last.max(occurrence_time)),
        );
        Ok(TransitionOutcome::Applied { semantic_act })
    }

    /// Checks whether an act can enter scene-qualified research.
    #[must_use]
    pub fn research_admission(&self, act_id: &ActId) -> ResearchAdmission {
        let Some(act) = self.acts.get(act_id) else {
            return ResearchAdmission::Refused {
                reasons: BTreeSet::from([ResearchRefusal::MissingScene]),
            };
        };
        let mut reasons = BTreeSet::new();
        if !self.store_verified {
            reasons.insert(ResearchRefusal::UnverifiedSemantic);
        }
        let scene = match &act.scene {
            SceneBinding::Committed(scene) => Some(scene),
            SceneBinding::Missing { .. } => {
                reasons.insert(ResearchRefusal::MissingScene);
                None
            }
        };
        let presentation = match &act.presentation {
            PresentationBinding::Occurrence(presentation) => Some(presentation),
            PresentationBinding::Gap(gap) => {
                if let Some(repair) = self.presentation_repairs.get(&gap.gap_id) {
                    Some(&repair.replacement)
                } else {
                    reasons.insert(ResearchRefusal::MissingPresentation);
                    None
                }
            }
        };
        if let (Some(scene), Some(presentation)) = (scene, presentation)
            && scene != &presentation.scene
        {
            reasons.insert(ResearchRefusal::PresentationSceneMismatch);
        }
        if reasons.is_empty() {
            match (scene, presentation) {
                (Some(scene), Some(presentation)) => ResearchAdmission::Admitted {
                    scene_id: scene.scene_id.to_string(),
                    presentation_id: presentation.presentation_id.to_string(),
                },
                _ => ResearchAdmission::Refused {
                    reasons: BTreeSet::from([ResearchRefusal::MissingScene]),
                },
            }
        } else {
            ResearchAdmission::Refused { reasons }
        }
    }

    /// Returns an exact occurrence prefix in append order (lexicographic occurrence identity).
    pub fn occurrences(&self) -> impl Iterator<Item = &MemoryOccurrence> {
        self.append_order
            .iter()
            .filter_map(|id| self.occurrences.get(id).map(|(_, occurrence)| occurrence))
    }

    fn validate(&self, occurrence: &MemoryOccurrence) -> Result<(), MemoryError> {
        let result = match occurrence {
            MemoryOccurrence::OperatorAct(value) => self.validate_act(value),
            MemoryOccurrence::PresentationGapRepair(value) => self.validate_gap_repair(value),
            MemoryOccurrence::ActCorrection(value) => self.validate_correction(value),
            MemoryOccurrence::OntologyVersion(value) => self.validate_ontology(value),
            MemoryOccurrence::Episode(value) => self.validate_episode(value),
            MemoryOccurrence::Replay(value) => self.validate_replay(value),
            MemoryOccurrence::SessionClose(value) => self.validate_session_close(value),
            MemoryOccurrence::KnowledgeClosure(value) => self.validate_knowledge(value),
            MemoryOccurrence::OutcomeAtHorizon(value) => {
                let Some(knowledge) = self.knowledge.get(&value.knowledge_closure_id) else {
                    return Err(MemoryError::OutcomeNeedsKnowledge);
                };
                if knowledge.episode_id != value.episode_id
                    || value.horizon < knowledge.knowledge_deadline
                    || value.outcome_known_at < value.horizon
                    || value.recorded_at < value.outcome_known_at
                    || value.committed_at < value.recorded_at
                {
                    return Err(MemoryError::Timing);
                }
                if matches!(value.state, crate::OutcomeState::Available { .. })
                    && (knowledge.state != KnowledgeState::Closed || !knowledge.gap_ids.is_empty())
                {
                    return Err(MemoryError::KnowledgeNotClosed);
                }
                if knowledge.state == KnowledgeState::Closed && !self.store_verified {
                    return Err(MemoryError::UnverifiedSemantic);
                }
                if value.qualification != crate::Qualification::UnverifiedSemantic {
                    return Err(MemoryError::UnverifiedSemantic);
                }
                Ok(())
            }
            MemoryOccurrence::InterviewDisposition(value) => {
                let Some(episode) = self.episodes.get(&value.episode_id) else {
                    return Err(MemoryError::UnknownEpisode(value.episode_id.clone()));
                };
                if !self.sessions_closed.contains(&episode.session_id) {
                    return Err(MemoryError::UnknownSession);
                }
                Ok(())
            }
        };
        result?;
        if self
            .last_recorded_at
            .is_some_and(|last| Self::occurrence_time(occurrence) < last)
        {
            return Err(MemoryError::Timing);
        }
        Ok(())
    }

    fn validate_act(&self, value: &OperatorAct) -> Result<(), MemoryError> {
        if self.sessions_closed.contains(&value.session_id) {
            return Err(MemoryError::SessionTerminal);
        }
        if let Some(subject) = &value.subject {
            validate_text(subject, "act subject").map_err(MemoryError::Text)?;
        }
        if let crate::ActKind::ExternalManualExecutionEscape { reason } = &value.kind {
            validate_text(reason.as_str(), "manual execution escape reason")
                .map_err(MemoryError::Text)?;
        }
        if let Some(assertion) = &value.assertion {
            match &assertion.disposition {
                crate::AssertionDisposition::Verbatim { text } => {
                    validate_text(text, "assertion text").map_err(MemoryError::Text)?;
                }
                crate::AssertionDisposition::Opaque { .. }
                | crate::AssertionDisposition::CannotArticulate => {}
            }
        }
        if let (SceneBinding::Committed(scene), PresentationBinding::Occurrence(presentation)) =
            (&value.scene, &value.presentation)
            && scene != &presentation.scene
        {
            return Err(MemoryError::ScenePresentationMismatch);
        }
        if let (SceneBinding::Committed(scene), PresentationBinding::Gap(gap)) =
            (&value.scene, &value.presentation)
            && gap
                .scene
                .as_ref()
                .is_some_and(|gap_scene| gap_scene != scene)
        {
            return Err(MemoryError::ScenePresentationMismatch);
        }
        if let PresentationBinding::Occurrence(presentation) = &value.presentation
            && presentation.occurred_at > value.occurred_at
        {
            return Err(MemoryError::Timing);
        }
        Ok(())
    }

    fn validate_gap_repair(&self, value: &PresentationGapRepair) -> Result<(), MemoryError> {
        let matching = self.acts.values().any(|act| {
            matches!(&act.presentation, PresentationBinding::Gap(gap) if gap.gap_id == value.gap_id)
        });
        if !matching {
            return Err(MemoryError::UnknownPresentationGap);
        }
        if value.replacement.occurred_at > value.recorded_at {
            return Err(MemoryError::Timing);
        }
        Ok(())
    }

    fn validate_correction(&self, value: &ActCorrection) -> Result<(), MemoryError> {
        let Some(act) = self.acts.get(&value.act_id) else {
            return Err(MemoryError::UnknownAct(value.act_id.clone()));
        };
        if value.recorded_at < act.occurred_at {
            return Err(MemoryError::Timing);
        }
        validate_text(&value.reason, "correction reason").map_err(MemoryError::Text)
    }

    fn validate_ontology(&self, value: &OntologyVersion) -> Result<(), MemoryError> {
        if let Some(parent) = &value.parent_version_id
            && !self.ontology_versions.contains(parent)
        {
            return Err(MemoryError::UnknownOntologyParent);
        }
        for mapping in &value.mappings {
            validate_text(&mapping.label, "ontology label").map_err(MemoryError::Text)?;
        }
        Ok(())
    }

    fn validate_episode(&self, value: &Episode) -> Result<(), MemoryError> {
        if value.act_ids.is_empty()
            || value.act_ids.iter().any(|act_id| {
                self.acts.get(act_id).is_none_or(|act| {
                    act.session_id != value.session_id || act.occurred_at > value.decision_cutoff
                })
            })
        {
            return match value.act_ids.first() {
                Some(act_id) => Err(MemoryError::UnknownAct(act_id.clone())),
                None => Err(MemoryError::Text("episode act_ids required".into())),
            };
        }
        if let Some(end) = value.ended_at
            && end < value.started_at
        {
            return Err(MemoryError::EpisodeBounds);
        }
        let mut previous_end = value.started_at;
        for segment in &value.segments {
            if segment.start_at < previous_end {
                return Err(MemoryError::EpisodeOrder);
            }
            if let Some(end) = segment.end_at {
                if end <= segment.start_at
                    || value.ended_at.is_some_and(|episode_end| end > episode_end)
                {
                    return Err(MemoryError::EpisodeBounds);
                }
                previous_end = end;
            } else if segment.path != EpisodePath::UnknownInterval
                && segment.path != EpisodePath::UnresolvedEffect
            {
                return Err(MemoryError::EpisodeBounds);
            }
            if segment.path == EpisodePath::NoTrade
                && !matches!(segment.effect, EffectStatus::NotApplicableByNoTrade)
            {
                return Err(MemoryError::EpisodeBounds);
            }
        }
        if value.completeness == EpisodeCompleteness::Complete && value.ended_at.is_none() {
            return Err(MemoryError::EpisodeBounds);
        }
        if !self.store_verified
            && (value.completeness == EpisodeCompleteness::Complete
                || value.segments.iter().any(|segment| {
                    matches!(segment.effect, EffectStatus::Observed { .. })
                        || matches!(segment.lot, crate::LotAssociation::Resolved { .. })
                }))
        {
            return Err(MemoryError::UnverifiedSemantic);
        }
        if self.sessions_closed.contains(&value.session_id) {
            return Err(MemoryError::SessionTerminal);
        }
        Ok(())
    }

    fn validate_replay(&self, value: &ReplayArtifact) -> Result<(), MemoryError> {
        if value.qualification != crate::Qualification::UnverifiedSemantic {
            return Err(MemoryError::UnverifiedSemantic);
        }
        if value.phase == ReplayPhase::OutcomeHiddenReconstruction
            && value.witnessed_scene.is_none()
        {
            return Err(MemoryError::OutcomeLeak);
        }
        if value.information_cutoff > value.recorded_at {
            return Err(MemoryError::Timing);
        }
        if value.phase == ReplayPhase::OutcomeHiddenReconstruction
            && (!matches!(value.visibility, crate::OutcomeVisibility::Hidden)
                || value.content_role != ReplayContentRole::OutcomeHiddenReconstruction)
        {
            return Err(MemoryError::OutcomeLeak);
        }
        if value.phase == ReplayPhase::RetrospectiveInterpretation
            && (!matches!(value.visibility, crate::OutcomeVisibility::Revealed { .. })
                || value.content_role != ReplayContentRole::RetrospectiveInterpretation)
        {
            return Err(MemoryError::OutcomeLeak);
        }
        if let crate::OutcomeVisibility::Revealed { reveal_id, .. } = &value.visibility {
            let Some(hidden) = self.replays.get(reveal_id) else {
                return Err(MemoryError::OutcomeLeak);
            };
            if hidden.phase != ReplayPhase::OutcomeHiddenReconstruction
                || hidden.episode_id != value.episode_id
                || hidden.recorded_at > value.recorded_at
            {
                return Err(MemoryError::OutcomeLeak);
            }
            if let crate::OutcomeVisibility::Revealed { revealed_at, .. } = &value.visibility
                && *revealed_at < hidden.recorded_at
            {
                return Err(MemoryError::Timing);
            }
        }
        if value.phase == ReplayPhase::OutcomeHiddenReconstruction
            && self
                .outcomes
                .values()
                .any(|outcome| outcome.episode_id == value.episode_id)
        {
            return Err(MemoryError::OutcomeLeak);
        }
        if !self.episodes.contains_key(&value.episode_id) {
            return Err(MemoryError::UnknownEpisode(value.episode_id.clone()));
        }
        Ok(())
    }

    fn validate_session_close(&self, value: &SessionClose) -> Result<(), MemoryError> {
        if self.sessions_closed.contains(&value.session_id) {
            return Err(MemoryError::DuplicateSessionClose);
        }
        let has_session = self
            .acts
            .values()
            .any(|act| act.session_id == value.session_id)
            || self
                .episodes
                .values()
                .any(|episode| episode.session_id == value.session_id);
        if !has_session {
            return Err(MemoryError::UnknownSession);
        }
        if value.committed_at < value.recorded_at || value.recorded_at < value.closed_at {
            return Err(MemoryError::Timing);
        }
        if value.cutoff > value.closed_at {
            return Err(MemoryError::Timing);
        }
        if self
            .acts
            .values()
            .any(|act| act.session_id == value.session_id && act.occurred_at > value.cutoff)
        {
            return Err(MemoryError::Timing);
        }
        if self.episodes.values().any(|episode| {
            episode.session_id == value.session_id
                && (episode.ended_at.is_none_or(|ended| ended > value.cutoff)
                    || episode
                        .segments
                        .iter()
                        .any(|segment| segment.end_at.is_none()))
        }) {
            return Err(MemoryError::EpisodeBounds);
        }
        if value.qualification != crate::Qualification::UnverifiedSemantic {
            return Err(MemoryError::UnverifiedSemantic);
        }
        Ok(())
    }

    fn validate_knowledge(&self, value: &KnowledgeClosure) -> Result<(), MemoryError> {
        if !self.episodes.contains_key(&value.episode_id) {
            return Err(MemoryError::UnknownEpisode(value.episode_id.clone()));
        }
        let Some(episode) = self.episodes.get(&value.episode_id) else {
            return Err(MemoryError::UnknownEpisode(value.episode_id.clone()));
        };
        if !self.sessions_closed.contains(&episode.session_id) {
            return Err(MemoryError::UnknownSession);
        }
        if value.evidence_cutoff > value.knowledge_deadline
            || (value.state == KnowledgeState::Closed && !value.gap_ids.is_empty())
            || value.recorded_at < value.knowledge_deadline
            || value.committed_at < value.recorded_at
            || value.gap_ids.windows(2).any(|pair| pair[0] >= pair[1])
        {
            return Err(MemoryError::KnowledgeNotClosed);
        }
        if value.qualification != crate::Qualification::UnverifiedSemantic {
            return Err(MemoryError::UnverifiedSemantic);
        }
        if value.state == KnowledgeState::Closed && !self.store_verified {
            return Err(MemoryError::UnverifiedSemantic);
        }
        Ok(())
    }

    fn apply(&mut self, occurrence: MemoryOccurrence) {
        match occurrence {
            MemoryOccurrence::OperatorAct(value) => {
                self.acts.insert(value.act_id.clone(), value);
            }
            MemoryOccurrence::PresentationGapRepair(value) => {
                self.presentation_repairs
                    .insert(value.gap_id.clone(), value);
            }
            MemoryOccurrence::Episode(value) => {
                self.episodes.insert(value.episode_id.clone(), value);
            }
            MemoryOccurrence::KnowledgeClosure(value) => {
                self.knowledge.insert(value.closure_id.clone(), value);
            }
            MemoryOccurrence::Replay(value) => {
                self.replays.insert(value.replay_id.clone(), value);
            }
            MemoryOccurrence::SessionClose(value) => {
                self.sessions_closed.insert(value.session_id);
            }
            MemoryOccurrence::OntologyVersion(value) => {
                self.ontology_versions.insert(value.version_id);
            }
            MemoryOccurrence::OutcomeAtHorizon(value) => {
                self.outcomes.insert(value.outcome_id.clone(), value);
            }
            MemoryOccurrence::ActCorrection(_) | MemoryOccurrence::InterviewDisposition(_) => {}
        }
    }

    fn occurrence_time(occurrence: &MemoryOccurrence) -> crate::LogicalSessionTick {
        match occurrence {
            MemoryOccurrence::OperatorAct(value) => value.occurred_at,
            MemoryOccurrence::PresentationGapRepair(value) => value.recorded_at,
            MemoryOccurrence::ActCorrection(value) => value.recorded_at,
            MemoryOccurrence::OntologyVersion(value) => value.effective_at,
            MemoryOccurrence::Episode(value) => value.ended_at.unwrap_or(value.started_at),
            MemoryOccurrence::Replay(value) => value.recorded_at,
            MemoryOccurrence::SessionClose(value) => value.closed_at,
            MemoryOccurrence::KnowledgeClosure(value) => value.knowledge_deadline,
            MemoryOccurrence::OutcomeAtHorizon(value) => value.horizon,
            MemoryOccurrence::InterviewDisposition(value) => value.recorded_at,
        }
    }
}
