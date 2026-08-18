use crate::{
    AUTHORITY, AbstentionReasonV1, ChoiceClosureV1, CommittedArtifactReferenceV1, ECONOMIC_CLAIM,
    EpisodeBasisV1, EventEvidenceAtCutV1, EventEvidenceDisposition, EventTimeV1,
    ExternalWalletEffectV1, HotScopeClosureV1, HotTerminalStatus, INTERVIEW_CONTRACT,
    InterviewDispositionKindV1, InterviewDispositionV1, KNOWLEDGE_CLOSURE_CONTRACT,
    KnowledgeClosureV1, KnowledgeCutProofV1, MAX_ARTIFACT_BYTES, OUTCOME_CONTRACT,
    OutcomeAtHorizonV1, OutcomeEvidenceV1, PrivateBlobReferenceV1, QuoteOutcomeV1, Result,
    SCHEMA_VERSION, SESSION_CLOSE_CONTRACT, SessionCloseV1, SessionCompletionStatus,
    SourceSupportStatus, error::ClosureError,
};
use joshi_admission::{
    Sha256Digest,
    operational::{
        EpisodeLaunchReceiptV1, EpisodeLaunchRegistrationV1, EpisodeProtocolReceiptV1,
        EpisodeProtocolRegistrationV1, ExplicitAbstentionCommandV1, ExplicitAbstentionReason,
        ExplicitAbstentionReceiptV1, PresentationSceneReceiptV1, ProspectiveNominationCommandV1,
        ProspectiveNominationReceiptV1,
    },
    strict_json,
};
use serde::{Serialize, de::DeserializeOwned};
use time::{Duration, OffsetDateTime, PrimitiveDateTime, macros::format_description};

pub enum QualifyingChoiceEvidence<'a> {
    Nomination {
        command: &'a ProspectiveNominationCommandV1,
        exact_command_bytes: &'a [u8],
        receipt: &'a ProspectiveNominationReceiptV1,
        exact_receipt_bytes: &'a [u8],
    },
    ExplicitAbstention {
        command: &'a ExplicitAbstentionCommandV1,
        exact_command_bytes: &'a [u8],
        receipt: &'a ExplicitAbstentionReceiptV1,
        exact_receipt_bytes: &'a [u8],
    },
}

pub struct EpisodePrerequisites<'a> {
    pub protocol: &'a EpisodeProtocolRegistrationV1,
    pub exact_protocol_bytes: &'a [u8],
    pub protocol_receipt: &'a EpisodeProtocolReceiptV1,
    pub launch: &'a EpisodeLaunchRegistrationV1,
    pub exact_launch_bytes: &'a [u8],
    pub launch_receipt: &'a EpisodeLaunchReceiptV1,
    pub presentation_receipt: &'a PresentationSceneReceiptV1,
    pub choice: QualifyingChoiceEvidence<'a>,
}

/// Marker returned only after all preregistration, presentation, and choice bytes resolve.
pub struct ValidatedEpisodeBasis<'a> {
    basis: &'a EpisodeBasisV1,
}

impl EpisodeBasisV1 {
    fn validate_syntax(&self) -> Result<()> {
        for (value, field) in [
            (&self.protocol_registration_id, "protocolRegistrationId"),
            (&self.launch_id, "launchId"),
            (&self.prospective_session_id, "prospectiveSessionId"),
            (&self.census_artifact_id, "censusArtifactId"),
            (&self.cockpit_publication_id, "cockpitPublicationId"),
            (&self.scene_id, "sceneId"),
            (&self.presentation_id, "presentationId"),
            (&self.assignment_id, "assignmentId"),
            (&self.downstream.hot_decision_id, "hotDecisionId"),
            (&self.downstream.hot_intent_id, "hotIntentId"),
            (
                &self.downstream.outcome_occurrence_id,
                "outcomeOccurrenceId",
            ),
            (
                &self.downstream.interview_occurrence_id,
                "interviewOccurrenceId",
            ),
            (&self.downstream.export_request_id, "exportRequestId"),
            (&self.downstream.analysis_run_id, "analysisRunId"),
            (&self.downstream.artifact_import_id, "artifactImportId"),
        ] {
            identity(value, field)?;
        }
        positive_wire(&self.catalog_cutoff_commit_seq, "catalogCutoffCommitSeq")?;
        let t0 = instant(&self.t0, "t0")?;
        let end = instant(&self.scheduled_session_end, "scheduledSessionEnd")?;
        let horizon = instant(&self.outcome_horizon, "outcomeHorizon")?;
        let deadline = instant(&self.knowledge_deadline, "knowledgeDeadline")?;
        if !(t0 < end && end < horizon && horizon < deadline) {
            return invalid("episode basis times must satisfy T0 < T_end < H < K");
        }
        self.choice.validate_syntax(&self.choice_universe_digest)?;
        Ok(())
    }

    /// Validates the basis against exact current admission contracts and durable choice evidence.
    ///
    /// # Errors
    ///
    /// Returns an error for any substituted ID, digest, timestamp, cutoff, or choice branch.
    pub fn validate_against<'a>(
        &'a self,
        prerequisites: &EpisodePrerequisites<'_>,
    ) -> Result<ValidatedEpisodeBasis<'a>> {
        self.validate_syntax()?;
        let EpisodePrerequisites {
            protocol,
            exact_protocol_bytes,
            protocol_receipt,
            launch,
            exact_launch_bytes,
            launch_receipt,
            presentation_receipt,
            choice: _,
        } = prerequisites;
        protocol_receipt.validate_against(protocol, exact_protocol_bytes)?;
        launch_receipt.validate_against(launch, exact_launch_bytes)?;
        presentation_receipt.validate()?;
        if launch.outcome_contract != OUTCOME_CONTRACT
            || launch.interview_contract != INTERVIEW_CONTRACT
        {
            return invalid("launch did not preregister the frozen outcome/interview contracts");
        }

        let t0 = instant(&launch.t0, "launch.t0")?;
        let session_end = add_us(t0, wire(&protocol.duration_us, "protocol.durationUs")?)?;
        let horizon = add_us(
            t0,
            wire(
                &protocol.outcome_horizon_offset_us,
                "protocol.outcomeHorizonOffsetUs",
            )?,
        )?;
        let deadline = add_us(
            t0,
            wire(
                &protocol.knowledge_deadline_offset_us,
                "protocol.knowledgeDeadlineOffsetUs",
            )?,
        )?;
        if self.protocol_registration_id != launch.protocol_registration_id
            || self.protocol_registration_id != protocol.protocol_registration_id
            || self.protocol_digest != launch.protocol_digest
            || self.protocol_digest != protocol_receipt.protocol_digest
            || self.privacy_digest != protocol.privacy_digest
            || self.launch_id != launch.launch_id
            || self.launch_digest != launch_receipt.launch_digest
            || self.prospective_session_id != launch.prospective_session_id
            || instant(&self.t0, "basis.t0")? != t0
            || instant(&self.scheduled_session_end, "basis.scheduledSessionEnd")? != session_end
            || instant(&self.outcome_horizon, "basis.outcomeHorizon")? != horizon
            || instant(&self.knowledge_deadline, "basis.knowledgeDeadline")? != deadline
            || self.catalog_cutoff_commit_seq != launch.catalog_cutoff_commit_seq
            || self.census_artifact_id != launch.census.artifact_id
            || self.census_artifact_digest != launch.census.artifact_digest
            || self.cockpit_publication_id != launch.cockpit.publication_id
            || self.cockpit_publication_digest != launch.cockpit.publication_digest
            || self.scene_id != launch.scene.scene_id
            || self.view_digest != launch.scene.view_digest
            || self.presentation_id != launch.reserved_presentation_id
            || self.presentation_id != presentation_receipt.presentation_id
            || self.presentation_digest != presentation_receipt.presentation_digest
            || self.assignment_id != launch.presentation.assignment_id
            || self.assignment_id != presentation_receipt.assignment_id
            || self.as_of_digest != launch.as_of_digest
            || self.choice_universe_digest != launch.choice_universe_digest
            || self.downstream.hot_decision_id != launch.reserved_hot_decision_id
            || self.downstream.hot_intent_id != launch.reserved_hot_intent_id
            || self.downstream.outcome_occurrence_id != launch.reserved_outcome_id
            || self.downstream.interview_occurrence_id != launch.reserved_interview_id
            || self.downstream.export_request_id != launch.reserved_export_request_id
            || self.downstream.analysis_run_id != launch.reserved_analysis_run_id
            || self.downstream.artifact_import_id != launch.reserved_artifact_import_id
        {
            return invalid(
                "episode basis differs from its exact protocol/launch/presentation closure",
            );
        }
        self.choice.validate_against(prerequisites)?;
        Ok(ValidatedEpisodeBasis { basis: self })
    }
}

impl ChoiceClosureV1 {
    fn validate_syntax(&self, universe: &Sha256Digest) -> Result<()> {
        let (command_id, receipt_batch_id, receipt_commit_seq) = match self {
            Self::Nomination {
                command_id,
                receipt_batch_id,
                receipt_commit_seq,
                subject,
                ..
            } => {
                identity(&subject.subject_id, "choice.subject.subjectId")?;
                if &subject.choice_universe_digest != universe {
                    return invalid("nomination subject differs from choice universe");
                }
                (command_id, receipt_batch_id, receipt_commit_seq)
            }
            Self::ExplicitAbstention {
                command_id,
                receipt_batch_id,
                receipt_commit_seq,
                ..
            } => (command_id, receipt_batch_id, receipt_commit_seq),
        };
        identity(command_id, "choice.commandId")?;
        identity(receipt_batch_id, "choice.receiptBatchId")?;
        positive_wire(receipt_commit_seq, "choice.receiptCommitSeq")?;
        Ok(())
    }

    fn validate_against(&self, prerequisites: &EpisodePrerequisites<'_>) -> Result<()> {
        match (self, &prerequisites.choice) {
            (
                Self::Nomination {
                    command_id,
                    command_digest,
                    receipt_batch_id,
                    receipt_digest,
                    receipt_commit_seq,
                    subject,
                },
                QualifyingChoiceEvidence::Nomination {
                    command,
                    exact_command_bytes,
                    receipt,
                    exact_receipt_bytes,
                },
            ) => {
                command.validate_against(
                    prerequisites.protocol,
                    prerequisites.protocol_receipt,
                    prerequisites.exact_protocol_bytes,
                    prerequisites.launch,
                    prerequisites.launch_receipt,
                    prerequisites.exact_launch_bytes,
                    prerequisites.presentation_receipt,
                    subject,
                )?;
                receipt.validate_against(command, exact_command_bytes)?;
                let decoded: ProspectiveNominationReceiptV1 =
                    strict_json::parse(exact_receipt_bytes, MAX_ARTIFACT_BYTES)?;
                if &decoded != *receipt
                    || command_id != &command.nomination_id
                    || command_digest != &Sha256Digest::of_bytes(exact_command_bytes)
                    || receipt_batch_id != &receipt.batch_id
                    || receipt_digest != &Sha256Digest::of_bytes(exact_receipt_bytes)
                    || receipt_commit_seq != &receipt.commit_seq
                    || subject != &command.subject
                {
                    return invalid(
                        "nomination choice does not close exact command and receipt bytes",
                    );
                }
            }
            (
                Self::ExplicitAbstention {
                    command_id,
                    command_digest,
                    receipt_batch_id,
                    receipt_digest,
                    receipt_commit_seq,
                    reason,
                },
                QualifyingChoiceEvidence::ExplicitAbstention {
                    command,
                    exact_command_bytes,
                    receipt,
                    exact_receipt_bytes,
                },
            ) => {
                command.validate_against(
                    prerequisites.protocol,
                    prerequisites.protocol_receipt,
                    prerequisites.exact_protocol_bytes,
                    prerequisites.launch,
                    prerequisites.launch_receipt,
                    prerequisites.exact_launch_bytes,
                    prerequisites.presentation_receipt,
                )?;
                receipt.validate_against(command, exact_command_bytes)?;
                let decoded: ExplicitAbstentionReceiptV1 =
                    strict_json::parse(exact_receipt_bytes, MAX_ARTIFACT_BYTES)?;
                if &decoded != *receipt
                    || command_id != &command.abstention_id
                    || command_digest != &Sha256Digest::of_bytes(exact_command_bytes)
                    || receipt_batch_id != &receipt.batch_id
                    || receipt_digest != &Sha256Digest::of_bytes(exact_receipt_bytes)
                    || receipt_commit_seq != &receipt.commit_seq
                    || *reason != abstention_reason(command.reason)
                {
                    return invalid(
                        "abstention choice does not close exact command and receipt bytes",
                    );
                }
            }
            _ => return invalid("episode choice branch differs from durable command branch"),
        }
        Ok(())
    }

    fn commit_seq(&self) -> Result<u64> {
        match self {
            Self::Nomination {
                receipt_commit_seq, ..
            }
            | Self::ExplicitAbstention {
                receipt_commit_seq, ..
            } => positive_wire(receipt_commit_seq, "choice.receiptCommitSeq"),
        }
    }
}

impl SessionCloseV1 {
    /// Validates the self-contained session-close artifact.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed timing, unsorted evidence, inconsistent terminal state, or
    /// any execution/profit authority.
    pub fn validate(&self) -> Result<()> {
        header(&self.contract, self.schema_version, SESSION_CLOSE_CONTRACT)?;
        self.basis.validate_syntax()?;
        identity(&self.session_close_id, "sessionCloseId")?;
        authority(&self.authority, &self.economic_claim)?;
        let t0 = instant(&self.basis.t0, "basis.t0")?;
        let scheduled = instant(
            &self.basis.scheduled_session_end,
            "basis.scheduledSessionEnd",
        )?;
        let closed = instant(&self.closed_at, "closedAt")?;
        let actual = wire(&self.actual_duration_us, "actualDurationUs")?;
        let actual_i128 = (closed - t0).whole_microseconds();
        if actual_i128 < 0 || u128::from(actual) != u128::try_from(actual_i128).unwrap_or(u128::MAX)
        {
            return invalid("actualDurationUs does not equal closedAt minus T0");
        }
        let expected_status = match closed.cmp(&scheduled) {
            std::cmp::Ordering::Equal => SessionCompletionStatus::CompleteOnSchedule,
            std::cmp::Ordering::Less => SessionCompletionStatus::IncompleteEarly,
            std::cmp::Ordering::Greater => SessionCompletionStatus::IncompleteLate,
        };
        if self.completion_status != expected_status {
            return invalid("completionStatus does not match the preregistered session boundary");
        }
        let close_cut = positive_wire(&self.closing_cutoff_commit_seq, "closingCutoffCommitSeq")?;
        if close_cut < self.basis.choice.commit_seq()? {
            return invalid("session close cutoff precedes the durable qualifying choice");
        }
        validate_evidence_refs(
            &self.source.source_receipts,
            close_cut,
            closed,
            "source.sourceReceipts",
        )?;
        sorted_strings(&self.source.coverage_ids, "source.coverageIds")?;
        sorted_strings(&self.source.gap_ids, "source.gapIds")?;
        let occurrence_count = wire(
            &self.source.nonfixture_occurrence_count,
            "source.nonfixtureOccurrenceCount",
        )?;
        if occurrence_count == 0 && self.source.support_status == SourceSupportStatus::Satisfied {
            return invalid("source support status does not match nonfixture occurrence count");
        }
        if self.source.source_receipts.is_empty() && self.source.gap_ids.is_empty() {
            return invalid("source closure requires a receipt or a scoped gap");
        }
        validate_evidence_refs(
            &self.presentation.presentation_event_receipts,
            close_cut,
            closed,
            "presentation.presentationEventReceipts",
        )?;
        sorted_strings(
            &self.presentation.visibility_gap_ids,
            "presentation.visibilityGapIds",
        )?;
        let open = wire(
            &self.presentation.open_interval_count,
            "presentation.openIntervalCount",
        )?;
        if self.completion_status == SessionCompletionStatus::CompleteOnSchedule && open != 0 {
            return invalid("on-schedule session cannot retain open presentation intervals");
        }
        self.hot_scope
            .validate_against_basis(&self.basis, close_cut, closed)?;
        artifact_ref(
            &self.final_contemporaneous_scene,
            close_cut,
            closed,
            "finalContemporaneousScene",
        )?;
        artifact_ref(&self.witnessed_replay, close_cut, closed, "witnessedReplay")?;
        if self.outcome_visibility != "not_revealed" {
            return invalid("session close must precede and hide the retrospective outcome");
        }
        Ok(())
    }

    /// Resolves the session close against the exact preregistered basis.
    ///
    /// # Errors
    ///
    /// Returns an error when the artifact or any prerequisite closure is invalid.
    pub fn validate_against(&self, prerequisites: &EpisodePrerequisites<'_>) -> Result<()> {
        self.validate()?;
        self.basis.validate_against(prerequisites)?;
        Ok(())
    }
}

impl HotScopeClosureV1 {
    fn validate_against_basis(
        &self,
        basis: &EpisodeBasisV1,
        close_cut: u64,
        closed_at: OffsetDateTime,
    ) -> Result<()> {
        let launch_reserved = match self {
            Self::NotApplicableByAbstention {
                reserved_hot_decision_id,
                reserved_hot_intent_id,
            }
            | Self::Nomination {
                reserved_hot_decision_id,
                reserved_hot_intent_id,
                ..
            } => (reserved_hot_decision_id, reserved_hot_intent_id),
        };
        identity(launch_reserved.0, "hotScope.reservedHotDecisionId")?;
        identity(launch_reserved.1, "hotScope.reservedHotIntentId")?;
        if launch_reserved.0 != &basis.downstream.hot_decision_id
            || launch_reserved.1 != &basis.downstream.hot_intent_id
        {
            return invalid("hot-scope closure does not use the launch-reserved identities");
        }
        match (self, &basis.choice) {
            (
                Self::NotApplicableByAbstention { .. },
                ChoiceClosureV1::ExplicitAbstention { .. },
            ) => {}
            (
                Self::Nomination {
                    subject_id,
                    decision,
                    intent,
                    terminal_records,
                    terminal_status,
                    ..
                },
                ChoiceClosureV1::Nomination { subject, .. },
            ) => {
                if subject_id != &subject.subject_id
                    || decision.evidence_id != basis.downstream.hot_decision_id
                    || intent.contract != "joshi.hot_scope_intent/v1"
                    || intent.producer_occurrence_id != basis.downstream.hot_intent_id
                {
                    return invalid(
                        "hot-scope closure changes nominated subject or artifact contract",
                    );
                }
                evidence_ref(decision, closed_at, close_cut, "hotScope.decision")?;
                artifact_ref(intent, close_cut, closed_at, "hotScope.intent")?;
                validate_sorted_artifacts(terminal_records, "hotScope.terminalRecords")?;
                for record in terminal_records {
                    artifact_ref(record, close_cut, closed_at, "hotScope.terminalRecords")?;
                    if !matches!(
                        record.contract.as_str(),
                        "joshi.hot_scope_desired/v1"
                            | "joshi.hot_scope_applied/v1"
                            | "joshi.hot_scope_degraded/v1"
                            | "joshi.hot_scope_closed/v1"
                    ) {
                        return invalid("hot terminal record uses an unknown contract");
                    }
                }
                let has_closed = terminal_records
                    .iter()
                    .any(|record| record.contract == "joshi.hot_scope_closed/v1");
                if (*terminal_status == HotTerminalStatus::Closed) != has_closed {
                    return invalid("hot terminal status does not match a typed closed record");
                }
            }
            _ => return invalid("hot-scope disposition differs from qualifying choice branch"),
        }
        Ok(())
    }
}

impl KnowledgeClosureV1 {
    /// Validates the exact event horizon, knowledge deadline, point-in-time cut proof, and eligible
    /// evidence. Later-known evidence and convenient interval snapping are rejected.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed cuts, clocks, evidence, coverage, or authority.
    pub fn validate(&self) -> Result<()> {
        header(
            &self.contract,
            self.schema_version,
            KNOWLEDGE_CLOSURE_CONTRACT,
        )?;
        identity(&self.knowledge_closure_id, "knowledgeClosureId")?;
        self.basis.validate_syntax()?;
        identity(&self.outcome_occurrence_id, "outcomeOccurrenceId")?;
        authority(&self.authority, &self.economic_claim)?;
        if self.outcome_occurrence_id != self.basis.downstream.outcome_occurrence_id
            || self.event_window_semantics != "half_open_t0_inclusive_h_exclusive"
        {
            return invalid("knowledge closure changes the reserved outcome or event-window rule");
        }
        let t0 = instant(&self.basis.t0, "basis.t0")?;
        let horizon = instant(&self.basis.outcome_horizon, "basis.outcomeHorizon")?;
        let deadline = instant(&self.basis.knowledge_deadline, "basis.knowledgeDeadline")?;
        if instant(&self.event_window_lower, "eventWindowLower")? != t0
            || instant(&self.event_window_upper, "eventWindowUpper")? != horizon
            || instant(&self.retrospective_state_at, "retrospectiveStateAt")? != horizon
            || instant(&self.knowledge_deadline, "knowledgeDeadline")? != deadline
        {
            return invalid("knowledge closure does not use exact T0/H/K boundaries");
        }
        let cut = self.cut.validate(deadline)?;
        validate_event_evidence(&self.event_evidence, t0, horizon, deadline, cut)?;
        validate_state_evidence(&self.state_evidence, deadline, cut)?;
        sorted_strings(&self.coverage_ids, "coverageIds")?;
        sorted_strings(&self.gap_ids, "gapIds")?;
        if self.coverage_ids.is_empty() && self.gap_ids.is_empty() {
            return invalid("knowledge closure requires coverage or a typed gap");
        }
        Ok(())
    }

    /// Resolves the knowledge artifact against the exact preregistration and choice.
    ///
    /// # Errors
    ///
    /// Returns an error when the artifact or any prerequisite closure is invalid.
    pub fn validate_against(&self, prerequisites: &EpisodePrerequisites<'_>) -> Result<()> {
        self.validate()?;
        self.basis.validate_against(prerequisites)?;
        Ok(())
    }
}

impl crate::CatalogKnowledgeCutV1 {
    fn validate(&self, deadline: OffsetDateTime) -> Result<u64> {
        identity(&self.catalog_id, "cut.catalogId")?;
        identity(&self.catalog_schema, "cut.catalogSchema")?;
        let through = positive_wire(&self.through_commit_seq, "cut.throughCommitSeq")?;
        let committed = instant(&self.through_committed_at, "cut.throughCommittedAt")?;
        let selected = instant(&self.selected_at, "cut.selectedAt")?;
        if committed > deadline || selected < deadline {
            return invalid("knowledge cut was not selected at K from commits durable by K");
        }
        match &self.proof {
            KnowledgeCutProofV1::SuccessorAfterDeadline {
                first_excluded_commit_seq,
                first_excluded_committed_at,
            } => {
                let excluded = positive_wire(
                    first_excluded_commit_seq,
                    "cut.proof.firstExcludedCommitSeq",
                )?;
                if excluded
                    != through.checked_add(1).ok_or_else(|| {
                        ClosureError::Invalid("knowledge cut sequence overflow".into())
                    })?
                    || instant(
                        first_excluded_committed_at,
                        "cut.proof.firstExcludedCommittedAt",
                    )? <= deadline
                {
                    return invalid("knowledge cut successor proof does not straddle K");
                }
            }
            KnowledgeCutProofV1::CatalogHeadAtSelection {
                head_commit_seq,
                head_observed_at,
            } => {
                if positive_wire(head_commit_seq, "cut.proof.headCommitSeq")? != through
                    || instant(head_observed_at, "cut.proof.headObservedAt")? < deadline
                {
                    return invalid("knowledge cut head proof does not prove the head at/after K");
                }
            }
        }
        Ok(through)
    }
}

impl OutcomeAtHorizonV1 {
    /// Validates a non-profit descriptive outcome artifact.
    ///
    /// # Errors
    ///
    /// Returns an error for fabricated exposure, economic claims, or malformed evidence states.
    pub fn validate(&self) -> Result<()> {
        header(&self.contract, self.schema_version, OUTCOME_CONTRACT)?;
        self.basis.validate_syntax()?;
        identity(&self.outcome_occurrence_id, "outcomeOccurrenceId")?;
        authority(&self.authority, &self.economic_claim)?;
        if self.outcome_occurrence_id != self.basis.downstream.outcome_occurrence_id
            || self.interpretation != "descriptive_non_profit_no_win_loss"
        {
            return invalid("outcome changes its reserved occurrence or claims economic judgment");
        }
        let deadline = instant(&self.basis.knowledge_deadline, "basis.knowledgeDeadline")?;
        if instant(&self.produced_at, "producedAt")? < deadline {
            return invalid("outcome was produced before the registered knowledge deadline");
        }
        validate_outcome_evidence(&self.retrospective_scene, "retrospectiveScene")?;
        validate_outcome_evidence(&self.lifecycle_venue, "lifecycleVenue")?;
        validate_outcome_evidence(&self.mark, "mark")?;
        validate_quote(&self.exact_size_quote, "exactSizeQuote")?;
        validate_quote(&self.whole_position_quote, "wholePositionQuote")?;
        match (&self.basis.choice, &self.selected_subject) {
            (ChoiceClosureV1::Nomination { subject, .. }, Some(selected))
                if subject == selected =>
            {
                if matches!(
                    self.retrospective_scene,
                    OutcomeEvidenceV1::NotApplicableByAbstention
                ) || matches!(
                    self.lifecycle_venue,
                    OutcomeEvidenceV1::NotApplicableByAbstention
                ) || matches!(self.mark, OutcomeEvidenceV1::NotApplicableByAbstention)
                    || matches!(
                        self.exact_size_quote,
                        QuoteOutcomeV1::NotApplicableByAbstention
                    )
                    || matches!(
                        self.whole_position_quote,
                        QuoteOutcomeV1::NotApplicableByAbstention
                    )
                    || matches!(
                        self.external_wallet_effect,
                        ExternalWalletEffectV1::NotApplicableByAbstention
                    )
                {
                    return invalid("nomination outcome uses abstention-only component states");
                }
            }
            (ChoiceClosureV1::ExplicitAbstention { .. }, None) => {
                if !matches!(
                    self.retrospective_scene,
                    OutcomeEvidenceV1::NotApplicableByAbstention
                ) || !matches!(
                    self.lifecycle_venue,
                    OutcomeEvidenceV1::NotApplicableByAbstention
                ) || !matches!(self.mark, OutcomeEvidenceV1::NotApplicableByAbstention)
                    || !matches!(
                        self.exact_size_quote,
                        QuoteOutcomeV1::NotApplicableByAbstention
                    )
                    || !matches!(
                        self.whole_position_quote,
                        QuoteOutcomeV1::NotApplicableByAbstention
                    )
                    || !matches!(
                        self.external_wallet_effect,
                        ExternalWalletEffectV1::NotApplicableByAbstention
                    )
                {
                    return invalid("abstention outcome fabricated subject exposure");
                }
            }
            _ => return invalid("outcome selected subject differs from qualifying choice"),
        }
        if let ExternalWalletEffectV1::ObservedFinalized { evidence, intent } =
            &self.external_wallet_effect
        {
            if intent != "unknown" {
                return invalid("external wallet effect intent must remain unknown");
            }
            artifact_ref_syntax(evidence, "externalWalletEffect.evidence")?;
        }
        sorted_strings(&self.coverage_ids, "coverageIds")?;
        sorted_strings(&self.gap_ids, "gapIds")?;
        Ok(())
    }

    /// Resolves content-derived session/knowledge references and exact coverage/censoring closure.
    ///
    /// # Errors
    ///
    /// Returns an error when exact bytes, episode bases, cutoffs, or coverage states differ.
    pub fn validate_against(
        &self,
        prerequisites: &EpisodePrerequisites<'_>,
        session: &SessionCloseV1,
        exact_session_bytes: &[u8],
        knowledge: &KnowledgeClosureV1,
        exact_knowledge_bytes: &[u8],
    ) -> Result<()> {
        self.validate()?;
        self.basis.validate_against(prerequisites)?;
        session.validate_against(prerequisites)?;
        knowledge.validate_against(prerequisites)?;
        self.session_close.verify_content(
            SESSION_CLOSE_CONTRACT,
            &session.session_close_id,
            exact_session_bytes,
        )?;
        self.knowledge_closure.verify_content(
            KNOWLEDGE_CLOSURE_CONTRACT,
            &knowledge.knowledge_closure_id,
            exact_knowledge_bytes,
        )?;
        let expected_censoring = knowledge
            .event_evidence
            .iter()
            .any(|evidence| evidence.disposition == EventEvidenceDisposition::IntervalCensored)
            || !knowledge.gap_ids.is_empty();
        if self.basis != session.basis
            || self.basis != knowledge.basis
            || self.coverage_ids != knowledge.coverage_ids
            || self.gap_ids != knowledge.gap_ids
            || self.censoring_present != expected_censoring
            || instant(&self.produced_at, "producedAt")?
                < instant(&knowledge.cut.selected_at, "knowledge.cut.selectedAt")?
        {
            return invalid(
                "outcome does not close exact session, knowledge cut, coverage, or censoring",
            );
        }
        Ok(())
    }
}

impl InterviewDispositionV1 {
    /// Validates explicit decline/gap/recorded states and the conservative private-artifact policy.
    ///
    /// # Errors
    ///
    /// Returns an error for omitted disposition, reveal-order failure, or private-policy drift.
    pub fn validate(&self) -> Result<()> {
        header(&self.contract, self.schema_version, INTERVIEW_CONTRACT)?;
        self.basis.validate_syntax()?;
        identity(&self.interview_occurrence_id, "interviewOccurrenceId")?;
        authority(&self.authority, &self.economic_claim)?;
        if self.interview_occurrence_id != self.basis.downstream.interview_occurrence_id
            || self.private_artifact_policy_digest != self.basis.privacy_digest
            || self.export_policy != "metadata_only_no_text"
        {
            return invalid("interview changes reserved identity or exports private text");
        }
        let session_end = instant(
            &self.basis.scheduled_session_end,
            "basis.scheduledSessionEnd",
        )?;
        if instant(&self.disposition_at, "dispositionAt")? < session_end {
            return invalid("interview disposition predates contemporaneous session end");
        }
        match &self.disposition {
            InterviewDispositionKindV1::Declined => {}
            InterviewDispositionKindV1::NotOfferedDueToGap { gap_ids } => {
                sorted_strings(gap_ids, "disposition.gapIds")?;
                if gap_ids.is_empty() {
                    return invalid("not-offered interview requires at least one typed gap");
                }
            }
            InterviewDispositionKindV1::Recorded {
                outcome_hidden,
                outcome_aware,
            } => {
                identity(&outcome_hidden.segment_id, "outcomeHidden.segmentId")?;
                let hidden_start = instant(&outcome_hidden.started_at, "outcomeHidden.startedAt")?;
                let hidden_close = instant(&outcome_hidden.closed_at, "outcomeHidden.closedAt")?;
                if hidden_start < session_end
                    || hidden_close <= hidden_start
                    || outcome_hidden.information_cutoff_commit_seq
                        != self.basis.choice.commit_seq()?.to_string()
                    || outcome_hidden.witnessed_scene_id != self.basis.scene_id
                    || outcome_hidden.outcome_visibility != "hidden"
                {
                    return invalid(
                        "outcome-hidden interview segment violates cutoff or reveal order",
                    );
                }
                private_blob(&outcome_hidden.blob, "outcomeHidden.blob")?;
                if let Some(aware) = outcome_aware {
                    identity(&aware.segment_id, "outcomeAware.segmentId")?;
                    let aware_start = instant(&aware.started_at, "outcomeAware.startedAt")?;
                    let reveal =
                        instant(&aware.outcome_revealed_at, "outcomeAware.outcomeRevealedAt")?;
                    let aware_close = instant(&aware.closed_at, "outcomeAware.closedAt")?;
                    if aware_start < hidden_close
                        || reveal < aware_start
                        || aware_close < reveal
                        || reveal
                            < instant(&self.basis.knowledge_deadline, "basis.knowledgeDeadline")?
                    {
                        return invalid(
                            "outcome-aware interview precedes hidden closure or knowledge K",
                        );
                    }
                    artifact_ref_syntax(&aware.outcome, "outcomeAware.outcome")?;
                    if aware.outcome.contract != OUTCOME_CONTRACT {
                        return invalid("outcome-aware segment references a non-outcome artifact");
                    }
                    identity(
                        &aware.retrospective_scene_id,
                        "outcomeAware.retrospectiveSceneId",
                    )?;
                    private_blob(&aware.blob, "outcomeAware.blob")?;
                }
            }
        }
        Ok(())
    }

    /// Resolves the interview against exact session bytes and, only after reveal, outcome bytes.
    ///
    /// # Errors
    ///
    /// Returns an error for substituted content, cross-episode linkage, or improper reveal state.
    pub fn validate_against(
        &self,
        prerequisites: &EpisodePrerequisites<'_>,
        session: &SessionCloseV1,
        exact_session_bytes: &[u8],
        outcome: Option<(&OutcomeAtHorizonV1, &[u8])>,
    ) -> Result<()> {
        self.validate()?;
        self.basis.validate_against(prerequisites)?;
        session.validate_against(prerequisites)?;
        self.session_close.verify_content(
            SESSION_CLOSE_CONTRACT,
            &session.session_close_id,
            exact_session_bytes,
        )?;
        if self.basis != session.basis {
            return invalid("interview and session close have different episode bases");
        }
        match (&self.disposition, outcome) {
            (
                InterviewDispositionKindV1::Recorded {
                    outcome_aware: Some(aware),
                    ..
                },
                Some((outcome, exact_outcome_bytes)),
            ) => {
                aware.outcome.verify_content(
                    OUTCOME_CONTRACT,
                    &outcome.outcome_occurrence_id,
                    exact_outcome_bytes,
                )?;
                if outcome.basis != self.basis {
                    return invalid("outcome-aware interview points to another episode");
                }
            }
            (
                InterviewDispositionKindV1::Recorded {
                    outcome_aware: Some(_),
                    ..
                },
                None,
            ) => {
                return invalid("outcome-aware interview lacks exact outcome bytes");
            }
            (
                InterviewDispositionKindV1::Declined
                | InterviewDispositionKindV1::NotOfferedDueToGap { .. }
                | InterviewDispositionKindV1::Recorded {
                    outcome_aware: None,
                    ..
                },
                None,
            ) => {}
            (_, Some(_)) => {
                return invalid("outcome bytes supplied to a disposition that did not reveal them");
            }
        }
        Ok(())
    }
}

impl CommittedArtifactReferenceV1 {
    fn verify_content(
        &self,
        expected_contract: &str,
        expected_occurrence: &str,
        bytes: &[u8],
    ) -> Result<()> {
        artifact_ref_syntax(self, "artifactReference")?;
        let digest = Sha256Digest::of_bytes(bytes);
        if self.contract != expected_contract
            || self.schema_version != SCHEMA_VERSION
            || self.producer_occurrence_id != expected_occurrence
            || self.artifact_digest != digest
            || self.artifact_id != digest.as_str()
        {
            return invalid("content-derived artifact reference differs from exact bytes");
        }
        Ok(())
    }
}

/// Makes the canonical content-derived reference used by downstream episode artifacts.
///
/// # Errors
///
/// Returns an error for a malformed contract, occurrence, commit, or timestamp.
pub fn content_artifact_reference(
    contract: &str,
    producer_occurrence_id: &str,
    exact_bytes: &[u8],
    commit_seq: &str,
    committed_at: &str,
) -> Result<CommittedArtifactReferenceV1> {
    identity(contract, "contract")?;
    identity(producer_occurrence_id, "producerOccurrenceId")?;
    positive_wire(commit_seq, "commitSeq")?;
    instant(committed_at, "committedAt")?;
    let digest = Sha256Digest::of_bytes(exact_bytes);
    Ok(CommittedArtifactReferenceV1 {
        contract: contract.to_owned(),
        schema_version: SCHEMA_VERSION,
        producer_occurrence_id: producer_occurrence_id.to_owned(),
        artifact_id: digest.as_str().to_owned(),
        artifact_digest: digest,
        commit_seq: commit_seq.to_owned(),
        committed_at: committed_at.to_owned(),
    })
}

/// Serializes exact compact UTF-8 JSON in Rust struct field order.
///
/// # Errors
///
/// Returns an error if the value cannot be serialized.
pub fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(value)?)
}

/// Parses bounded duplicate-aware session-close JSON and validates it.
///
/// # Errors
///
/// Returns an error for invalid JSON or contract semantics.
pub fn decode_session_close(bytes: &[u8]) -> Result<SessionCloseV1> {
    decode(bytes, SessionCloseV1::validate)
}

/// Parses bounded duplicate-aware knowledge-closure JSON and validates it.
///
/// # Errors
///
/// Returns an error for invalid JSON or contract semantics.
pub fn decode_knowledge_closure(bytes: &[u8]) -> Result<KnowledgeClosureV1> {
    decode(bytes, KnowledgeClosureV1::validate)
}

/// Parses bounded duplicate-aware outcome JSON and validates it.
///
/// # Errors
///
/// Returns an error for invalid JSON or contract semantics.
pub fn decode_outcome_at_horizon(bytes: &[u8]) -> Result<OutcomeAtHorizonV1> {
    decode(bytes, OutcomeAtHorizonV1::validate)
}

/// Parses bounded duplicate-aware interview-disposition JSON and validates it.
///
/// # Errors
///
/// Returns an error for invalid JSON or contract semantics.
pub fn decode_interview_disposition(bytes: &[u8]) -> Result<InterviewDispositionV1> {
    decode(bytes, InterviewDispositionV1::validate)
}

fn decode<T>(bytes: &[u8], validate: impl FnOnce(&T) -> Result<()>) -> Result<T>
where
    T: DeserializeOwned,
{
    let value: T = strict_json::parse(bytes, MAX_ARTIFACT_BYTES)?;
    validate(&value)?;
    Ok(value)
}

fn validate_event_evidence(
    values: &[EventEvidenceAtCutV1],
    t0: OffsetDateTime,
    horizon: OffsetDateTime,
    deadline: OffsetDateTime,
    cut: u64,
) -> Result<()> {
    if values
        .windows(2)
        .any(|pair| pair[0].evidence.evidence_id >= pair[1].evidence.evidence_id)
    {
        return invalid("eventEvidence must be strictly evidenceId-sorted");
    }
    for value in values {
        evidence_ref(&value.evidence, deadline, cut, "eventEvidence.evidence")?;
        match (&value.event_time, value.disposition) {
            (EventTimeV1::Point { at }, EventEvidenceDisposition::Included) => {
                let at = instant(at, "eventEvidence.eventTime.at")?;
                if at < t0 || at >= horizon {
                    return invalid("included point evidence lies outside [T0,H)");
                }
            }
            (EventTimeV1::Bounded { lower, upper }, disposition) => {
                let lower = instant(lower, "eventEvidence.eventTime.lower")?;
                let upper = instant(upper, "eventEvidence.eventTime.upper")?;
                if lower >= upper {
                    return invalid("bounded event interval must be nonempty and half-open");
                }
                let contained = lower >= t0 && upper <= horizon;
                let overlaps = lower < horizon && upper > t0;
                if (disposition == EventEvidenceDisposition::Included) != contained
                    || (disposition == EventEvidenceDisposition::IntervalCensored && !overlaps)
                {
                    return invalid(
                        "bounded event was included or censored with the wrong [T0,H) rule",
                    );
                }
            }
            (
                EventTimeV1::Unresolved { lower, upper },
                EventEvidenceDisposition::IntervalCensored,
            ) => {
                if lower.is_none() && upper.is_none() {
                    return invalid("unresolved event interval must retain at least one bound");
                }
                let lower = lower
                    .as_deref()
                    .map(|value| instant(value, "eventEvidence.eventTime.lower"))
                    .transpose()?;
                let upper = upper
                    .as_deref()
                    .map(|value| instant(value, "eventEvidence.eventTime.upper"))
                    .transpose()?;
                if lower
                    .zip(upper)
                    .is_some_and(|(lower, upper)| lower >= upper)
                {
                    return invalid("unresolved interval has reversed known bounds");
                }
            }
            _ => return invalid("point/unresolved event evidence has an invalid disposition"),
        }
    }
    Ok(())
}

fn validate_state_evidence(
    values: &[crate::StateEvidenceAtCutV1],
    deadline: OffsetDateTime,
    cut: u64,
) -> Result<()> {
    if values.is_empty()
        || values
            .windows(2)
            .any(|pair| pair[0].evidence.evidence_id >= pair[1].evidence.evidence_id)
    {
        return invalid("stateEvidence must be nonempty and strictly evidenceId-sorted");
    }
    for value in values {
        evidence_ref(&value.evidence, deadline, cut, "stateEvidence.evidence")?;
    }
    Ok(())
}

fn validate_outcome_evidence(value: &OutcomeEvidenceV1, field: &str) -> Result<()> {
    match value {
        OutcomeEvidenceV1::Available { artifacts } => {
            if artifacts.is_empty() {
                return invalid(format!("{field} available state requires an artifact"));
            }
            validate_sorted_artifacts(artifacts, field)
        }
        OutcomeEvidenceV1::Conflicting { artifacts } => {
            if artifacts.len() < 2 {
                return invalid(format!("{field} conflict requires at least two artifacts"));
            }
            validate_sorted_artifacts(artifacts, field)
        }
        OutcomeEvidenceV1::Missing { reason } | OutcomeEvidenceV1::Unsupported { reason } => {
            identity(reason, field)
        }
        OutcomeEvidenceV1::NotApplicableByAbstention => Ok(()),
    }
}

fn validate_quote(value: &QuoteOutcomeV1, field: &str) -> Result<()> {
    match value {
        QuoteOutcomeV1::Available { quote } => artifact_ref_syntax(quote, field),
        QuoteOutcomeV1::Refused { refusal } => artifact_ref_syntax(refusal, field),
        QuoteOutcomeV1::Missing { reason } => identity(reason, field),
        QuoteOutcomeV1::NotRequested | QuoteOutcomeV1::NotApplicableByAbstention => Ok(()),
    }
}

fn validate_sorted_artifacts(values: &[CommittedArtifactReferenceV1], field: &str) -> Result<()> {
    if values
        .windows(2)
        .any(|pair| pair[0].artifact_id >= pair[1].artifact_id)
    {
        return invalid(format!("{field} must be strictly artifactId-sorted"));
    }
    for value in values {
        artifact_ref_syntax(value, field)?;
    }
    Ok(())
}

fn validate_evidence_refs(
    values: &[crate::EvidenceReferenceV1],
    max_commit: u64,
    max_available: OffsetDateTime,
    field: &str,
) -> Result<()> {
    if values
        .windows(2)
        .any(|pair| pair[0].evidence_id >= pair[1].evidence_id)
    {
        return invalid(format!("{field} must be strictly evidenceId-sorted"));
    }
    for value in values {
        evidence_ref(value, max_available, max_commit, field)?;
    }
    Ok(())
}

fn evidence_ref(
    value: &crate::EvidenceReferenceV1,
    max_available: OffsetDateTime,
    max_commit: u64,
    field: &str,
) -> Result<()> {
    identity(&value.evidence_id, field)?;
    if instant(&value.available_at, field)? > max_available
        || positive_wire(&value.commit_seq, field)? > max_commit
    {
        return invalid(format!("{field} exceeds its knowledge cut"));
    }
    Ok(())
}

fn artifact_ref(
    value: &CommittedArtifactReferenceV1,
    max_commit: u64,
    max_time: OffsetDateTime,
    field: &str,
) -> Result<()> {
    artifact_ref_syntax(value, field)?;
    if positive_wire(&value.commit_seq, field)? > max_commit
        || instant(&value.committed_at, field)? > max_time
    {
        return invalid(format!("{field} exceeds the enclosing cut"));
    }
    Ok(())
}

fn artifact_ref_syntax(value: &CommittedArtifactReferenceV1, field: &str) -> Result<()> {
    identity(&value.contract, field)?;
    identity(&value.producer_occurrence_id, field)?;
    identity(&value.artifact_id, field)?;
    if value.schema_version != SCHEMA_VERSION {
        return invalid(format!("{field} has unsupported schema version"));
    }
    positive_wire(&value.commit_seq, field)?;
    instant(&value.committed_at, field)?;
    Ok(())
}

fn private_blob(value: &PrivateBlobReferenceV1, field: &str) -> Result<()> {
    identity(&value.blob_id, field)?;
    positive_wire(&value.byte_length, field)?;
    if value.content_type != "text/plain;charset=utf-8"
        || value.protection != "operator_private_local_only"
        || value.retention != "hold_no_automatic_deletion"
    {
        return invalid(format!("{field} violates the frozen private-text policy"));
    }
    Ok(())
}

fn header(contract: &str, version: u64, expected: &str) -> Result<()> {
    if contract == expected && version == SCHEMA_VERSION {
        Ok(())
    } else {
        invalid(format!("unsupported contract {contract}/v{version}"))
    }
}

fn authority(authority: &str, economic_claim: &str) -> Result<()> {
    if authority == AUTHORITY && economic_claim == ECONOMIC_CLAIM {
        Ok(())
    } else {
        invalid("episode artifact cannot carry execution or economic authority")
    }
}

fn identity(value: &str, field: &str) -> Result<()> {
    if !value.is_empty()
        && value.len() <= 512
        && value.trim() == value
        && !value.chars().any(char::is_control)
    {
        Ok(())
    } else {
        invalid(format!("{field} is not a stable identity"))
    }
}

fn sorted_strings(values: &[String], field: &str) -> Result<()> {
    if values.windows(2).any(|pair| pair[0] >= pair[1]) {
        return invalid(format!("{field} must be strictly sorted and unique"));
    }
    for value in values {
        identity(value, field)?;
    }
    Ok(())
}

fn wire(value: &str, field: &str) -> Result<u64> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || value.bytes().any(|byte| !byte.is_ascii_digit())
    {
        return invalid(format!("{field} is not a canonical u64 string"));
    }
    value
        .parse()
        .map_err(|_| ClosureError::Invalid(format!("{field} exceeds u64")))
}

fn positive_wire(value: &str, field: &str) -> Result<u64> {
    let parsed = wire(value, field)?;
    if parsed == 0 {
        invalid(format!("{field} must be positive"))
    } else {
        Ok(parsed)
    }
}

fn instant(value: &str, field: &str) -> Result<OffsetDateTime> {
    if value.len() != 27 || !value.ends_with('Z') || value.as_bytes().get(19) != Some(&b'.') {
        return invalid(format!(
            "{field} must be UTC with exactly six fractional digits"
        ));
    }
    PrimitiveDateTime::parse(
        value,
        &format_description!("[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"),
    )
    .map(PrimitiveDateTime::assume_utc)
    .map_err(|_| ClosureError::Invalid(format!("{field} is not a valid Gregorian UTC instant")))
}

fn add_us(value: OffsetDateTime, microseconds: u64) -> Result<OffsetDateTime> {
    let microseconds = i64::try_from(microseconds)
        .map_err(|_| ClosureError::Invalid("timestamp offset exceeds i64 microseconds".into()))?;
    value
        .checked_add(Duration::microseconds(microseconds))
        .ok_or_else(|| ClosureError::Invalid("timestamp addition overflow".into()))
}

const fn abstention_reason(value: ExplicitAbstentionReason) -> AbstentionReasonV1 {
    match value {
        ExplicitAbstentionReason::NoAcceptableCandidate => {
            AbstentionReasonV1::NoAcceptableCandidate
        }
        ExplicitAbstentionReason::InsufficientEvidence => AbstentionReasonV1::InsufficientEvidence,
        ExplicitAbstentionReason::RiskBoundary => AbstentionReasonV1::RiskBoundary,
        ExplicitAbstentionReason::AttentionLimit => AbstentionReasonV1::AttentionLimit,
    }
}

fn invalid<T>(message: impl Into<String>) -> Result<T> {
    Err(ClosureError::Invalid(message.into()))
}

impl<'a> ValidatedEpisodeBasis<'a> {
    #[must_use]
    pub const fn basis(&self) -> &'a EpisodeBasisV1 {
        self.basis
    }
}
