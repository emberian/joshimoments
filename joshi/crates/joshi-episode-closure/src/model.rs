use joshi_admission::{Sha256Digest, operational::ChoiceMembershipReferenceV1};
use serde::{Deserialize, Serialize};

/// Immutable identities copied from and checked against the preregistered launch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeBasisV1 {
    pub protocol_registration_id: String,
    pub protocol_digest: Sha256Digest,
    pub privacy_digest: Sha256Digest,
    pub launch_id: String,
    pub launch_digest: Sha256Digest,
    pub prospective_session_id: String,
    pub t0: String,
    pub scheduled_session_end: String,
    pub outcome_horizon: String,
    pub knowledge_deadline: String,
    pub catalog_cutoff_commit_seq: String,
    pub census_artifact_id: String,
    pub census_artifact_digest: Sha256Digest,
    pub cockpit_publication_id: String,
    pub cockpit_publication_digest: Sha256Digest,
    pub scene_id: String,
    pub view_digest: Sha256Digest,
    pub presentation_id: String,
    pub presentation_digest: Sha256Digest,
    pub assignment_id: String,
    pub as_of_digest: Sha256Digest,
    pub choice_universe_digest: Sha256Digest,
    pub choice: ChoiceClosureV1,
    pub downstream: DownstreamReservationsV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DownstreamReservationsV1 {
    pub hot_decision_id: String,
    pub hot_intent_id: String,
    pub outcome_occurrence_id: String,
    pub interview_occurrence_id: String,
    pub export_request_id: String,
    pub analysis_run_id: String,
    pub artifact_import_id: String,
}

/// Exact durable closure of the one qualifying choice branch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "branch",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ChoiceClosureV1 {
    Nomination {
        command_id: String,
        command_digest: Sha256Digest,
        receipt_batch_id: String,
        receipt_digest: Sha256Digest,
        receipt_commit_seq: String,
        subject: ChoiceMembershipReferenceV1,
    },
    ExplicitAbstention {
        command_id: String,
        command_digest: Sha256Digest,
        receipt_batch_id: String,
        receipt_digest: Sha256Digest,
        receipt_commit_seq: String,
        reason: AbstentionReasonV1,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AbstentionReasonV1 {
    NoAcceptableCandidate,
    InsufficientEvidence,
    RiskBoundary,
    AttentionLimit,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CommittedArtifactReferenceV1 {
    pub contract: String,
    pub schema_version: u64,
    pub producer_occurrence_id: String,
    pub artifact_id: String,
    pub artifact_digest: Sha256Digest,
    pub commit_seq: String,
    pub committed_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceReferenceV1 {
    pub evidence_id: String,
    pub evidence_digest: Sha256Digest,
    pub available_at: String,
    pub commit_seq: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionCompletionStatus {
    CompleteOnSchedule,
    IncompleteEarly,
    IncompleteLate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SpoolCloseStatus {
    CatalogAdmitted,
    BacklogRecorded,
    Unresolved,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BudgetCloseStatus {
    WithinRegisteredBudget,
    ExceededRegisteredBudget,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceSupportStatus {
    Satisfied,
    Insufficient,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceSessionClosureV1 {
    pub source_receipts: Vec<EvidenceReferenceV1>,
    pub coverage_ids: Vec<String>,
    pub gap_ids: Vec<String>,
    pub nonfixture_occurrence_count: String,
    pub support_status: SourceSupportStatus,
    pub spool_status: SpoolCloseStatus,
    pub budget_status: BudgetCloseStatus,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationSessionClosureV1 {
    pub presentation_event_receipts: Vec<EvidenceReferenceV1>,
    pub visibility_gap_ids: Vec<String>,
    pub open_interval_count: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "disposition",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum HotScopeClosureV1 {
    NotApplicableByAbstention {
        reserved_hot_decision_id: String,
        reserved_hot_intent_id: String,
    },
    Nomination {
        reserved_hot_decision_id: String,
        reserved_hot_intent_id: String,
        subject_id: String,
        decision: EvidenceReferenceV1,
        intent: Box<CommittedArtifactReferenceV1>,
        terminal_records: Vec<CommittedArtifactReferenceV1>,
        terminal_status: HotTerminalStatus,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HotTerminalStatus {
    Closed,
    DegradedUnclosed,
    Missing,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SessionCloseV1 {
    pub contract: String,
    pub schema_version: u64,
    pub session_close_id: String,
    pub basis: EpisodeBasisV1,
    pub closed_at: String,
    pub actual_duration_us: String,
    pub completion_status: SessionCompletionStatus,
    pub closing_cutoff_commit_seq: String,
    pub source: SourceSessionClosureV1,
    pub presentation: PresentationSessionClosureV1,
    pub hot_scope: HotScopeClosureV1,
    pub final_contemporaneous_scene: CommittedArtifactReferenceV1,
    pub witnessed_replay: CommittedArtifactReferenceV1,
    pub outcome_visibility: String,
    pub authority: String,
    pub economic_claim: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CatalogKnowledgeCutV1 {
    pub catalog_id: String,
    pub catalog_schema: String,
    pub through_commit_seq: String,
    pub through_committed_at: String,
    pub selected_at: String,
    pub proof: KnowledgeCutProofV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "proofKind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum KnowledgeCutProofV1 {
    SuccessorAfterDeadline {
        first_excluded_commit_seq: String,
        first_excluded_committed_at: String,
    },
    CatalogHeadAtSelection {
        head_commit_seq: String,
        head_observed_at: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "timeKind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum EventTimeV1 {
    Point {
        at: String,
    },
    Bounded {
        lower: String,
        upper: String,
    },
    Unresolved {
        lower: Option<String>,
        upper: Option<String>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventEvidenceDisposition {
    Included,
    IntervalCensored,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EventEvidenceAtCutV1 {
    pub evidence: EvidenceReferenceV1,
    pub event_time: EventTimeV1,
    pub disposition: EventEvidenceDisposition,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateAtHDisposition {
    Available,
    Missing,
    Conflicting,
    Unsupported,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StateEvidenceAtCutV1 {
    pub evidence: EvidenceReferenceV1,
    pub disposition: StateAtHDisposition,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct KnowledgeClosureV1 {
    pub contract: String,
    pub schema_version: u64,
    pub knowledge_closure_id: String,
    pub basis: EpisodeBasisV1,
    pub outcome_occurrence_id: String,
    pub event_window_lower: String,
    pub event_window_upper: String,
    pub event_window_semantics: String,
    pub retrospective_state_at: String,
    pub knowledge_deadline: String,
    pub cut: CatalogKnowledgeCutV1,
    pub event_evidence: Vec<EventEvidenceAtCutV1>,
    pub state_evidence: Vec<StateEvidenceAtCutV1>,
    pub coverage_ids: Vec<String>,
    pub gap_ids: Vec<String>,
    pub authority: String,
    pub economic_claim: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum OutcomeEvidenceV1 {
    Available {
        artifacts: Vec<CommittedArtifactReferenceV1>,
    },
    Missing {
        reason: String,
    },
    Conflicting {
        artifacts: Vec<CommittedArtifactReferenceV1>,
    },
    Unsupported {
        reason: String,
    },
    NotApplicableByAbstention,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum QuoteOutcomeV1 {
    Available {
        quote: CommittedArtifactReferenceV1,
    },
    Refused {
        refusal: CommittedArtifactReferenceV1,
    },
    NotRequested,
    Missing {
        reason: String,
    },
    NotApplicableByAbstention,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ExternalWalletEffectV1 {
    ObservedFinalized {
        evidence: CommittedArtifactReferenceV1,
        intent: String,
    },
    NotObserved,
    NotApplicableByAbstention,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeAtHorizonV1 {
    pub contract: String,
    pub schema_version: u64,
    pub outcome_occurrence_id: String,
    pub basis: EpisodeBasisV1,
    pub session_close: CommittedArtifactReferenceV1,
    pub knowledge_closure: CommittedArtifactReferenceV1,
    pub produced_at: String,
    pub retrospective_scene: OutcomeEvidenceV1,
    pub selected_subject: Option<ChoiceMembershipReferenceV1>,
    pub lifecycle_venue: OutcomeEvidenceV1,
    pub mark: OutcomeEvidenceV1,
    pub exact_size_quote: QuoteOutcomeV1,
    pub whole_position_quote: QuoteOutcomeV1,
    pub external_wallet_effect: ExternalWalletEffectV1,
    pub coverage_ids: Vec<String>,
    pub gap_ids: Vec<String>,
    pub censoring_present: bool,
    pub interpretation: String,
    pub authority: String,
    pub economic_claim: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PrivateBlobReferenceV1 {
    pub blob_id: String,
    pub blob_digest: Sha256Digest,
    pub byte_length: String,
    pub content_type: String,
    pub protection: String,
    pub retention: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeHiddenSegmentV1 {
    pub segment_id: String,
    pub prompt_digest: Sha256Digest,
    pub started_at: String,
    pub closed_at: String,
    pub information_cutoff_commit_seq: String,
    pub witnessed_scene_id: String,
    pub blob: PrivateBlobReferenceV1,
    pub outcome_visibility: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeAwareSegmentV1 {
    pub segment_id: String,
    pub prompt_digest: Sha256Digest,
    pub started_at: String,
    pub outcome_revealed_at: String,
    pub closed_at: String,
    pub outcome: CommittedArtifactReferenceV1,
    pub retrospective_scene_id: String,
    pub blob: PrivateBlobReferenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum InterviewDispositionKindV1 {
    Declined,
    NotOfferedDueToGap {
        gap_ids: Vec<String>,
    },
    Recorded {
        outcome_hidden: Box<OutcomeHiddenSegmentV1>,
        outcome_aware: Option<Box<OutcomeAwareSegmentV1>>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InterviewDispositionV1 {
    pub contract: String,
    pub schema_version: u64,
    pub interview_occurrence_id: String,
    pub basis: EpisodeBasisV1,
    pub session_close: CommittedArtifactReferenceV1,
    pub disposition_at: String,
    pub disposition: InterviewDispositionKindV1,
    pub private_artifact_policy_digest: Sha256Digest,
    pub export_policy: String,
    pub authority: String,
    pub economic_claim: String,
}
