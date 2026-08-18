use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64, WireU128};
use serde::{Deserialize, Serialize};

/// Exact occurrence identity plus digest, resolved by the integration-owned store adapter.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactRefV1 {
    pub occurrence_id: StableString,
    pub semantic_digest: ValueDigest,
}

/// Explicitly powerless authority carried by every epistemic artifact.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)]
pub struct EpistemicAuthorityV1 {
    pub rung: AuthorityRungV1,
    pub mode: AuthorityModeV1,
    pub may_influence_acquisition: bool,
    pub may_influence_presentation: bool,
    pub may_reserve_assets: bool,
    pub may_build_transactions: bool,
    pub may_sign: bool,
    pub may_submit: bool,
}

impl EpistemicAuthorityV1 {
    /// Canonical powerless H3 authority.
    pub const READ_ONLY_H3: Self = Self {
        rung: AuthorityRungV1::H3FittedOperator,
        mode: AuthorityModeV1::ReadOnlyNoExecution,
        may_influence_acquisition: false,
        may_influence_presentation: false,
        may_reserve_assets: false,
        may_build_transactions: false,
        may_sign: false,
        may_submit: false,
    };
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityRungV1 {
    H3FittedOperator,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityModeV1 {
    ReadOnlyNoExecution,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityKindV1 {
    CoherentVenueState,
    DirectionBySizeQuote,
    FeeModel,
    QuoteFreshness,
    RouteCapacity,
    ExactRunnerLot,
    WholePositionLiquidation,
    CommonTerminalManifest,
    LpScheduleState,
    ExternalSelfFlowSeparation,
    ExactInventory,
    FrozenReplay,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityMaturityV1 {
    CoherentRealState,
    ExactQuote,
    WholePositionLiquidation,
    TerminalPositionClosed,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapabilityRequirementV1 {
    pub kind: CapabilityKindV1,
    pub profile_id: StableString,
    pub required_maturity: CapabilityMaturityV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapabilityAttestationV1 {
    pub kind: CapabilityKindV1,
    pub profile_id: StableString,
    pub maturity: CapabilityMaturityV1,
    pub artifact: ArtifactRefV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DirectionV1 {
    AssetToNumeraire,
    NumeraireToAsset,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TieRuleV1 {
    ConflictUnlessSourceOrdered,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IntervalGapRuleV1 {
    IntervalCensored,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "family",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ClaimFamilyV1 {
    SpotCompetingRisk {
        quote_profile_id: StableString,
        net_profit_threshold_atoms: WireU128,
        drawdown_threshold_atoms: WireU128,
        quote_freshness_us: WireU64,
        observation_cadence_us: WireU64,
        tie_rule: TieRuleV1,
        interval_gap_rule: IntervalGapRuleV1,
    },
    LiquiditySurvival {
        quote_profile_id: StableString,
        maximum_slippage_ppm: WireU64,
        minimum_capacity_atoms: WireU128,
        quote_freshness_us: WireU64,
        checkpoint_cadence_us: WireU64,
    },
    RunnerCompetingRisk {
        terminal_manifest_contract: StableString,
    },
    RunnerFrozenBranchValue {
        terminal_manifest_contract: StableString,
    },
    DisabledLpSchedule {
        disabled_reason: StableString,
    },
    DisabledRoutedLiquidity {
        disabled_reason: StableString,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeStateV1 {
    pub outcome_id: StableString,
    pub meaning: StableString,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProperScoreRuleV1 {
    BrierCategorical,
    LogCategorical,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)]
pub struct ScoringContractV1 {
    pub rule: ProperScoreRuleV1,
    pub probability_floor_ppm: Option<WireU64>,
    pub baseline_definition_id: StableString,
    pub permits_resolved_observed: bool,
    pub permits_healthy_no_event: bool,
    pub permits_frozen_replay: bool,
    pub abstention_is_unscored: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AdjudicationContractV1 {
    pub resolver_version: StableString,
    pub eligible_observation_contracts: Vec<StableString>,
    pub maturity_rule: StableString,
    pub correction_policy: StableString,
    pub unresolved_treatment: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupportContractV1 {
    pub eligible_population: StableString,
    pub required_coverage: Vec<StableString>,
    pub prohibited_inputs: Vec<StableString>,
    pub transfer_limit: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClaimDefinitionV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub claim_definition_id: StableString,
    pub definition_version: WireU64,
    pub supersedes: Option<ArtifactRefV1>,
    pub producer_build_digest: ValueDigest,
    pub family: ClaimFamilyV1,
    pub outcome_space: Vec<OutcomeStateV1>,
    pub adjudication: AdjudicationContractV1,
    pub scoring: ScoringContractV1,
    pub support: SupportContractV1,
    pub required_capabilities: Vec<CapabilityRequirementV1>,
    pub authority: EpistemicAuthorityV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceAuthorityV1 {
    H0Settlement,
    H1ProtocolKinematics,
    H2Descriptive,
    H3FittedInput,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceInputV1 {
    pub artifact: ArtifactRefV1,
    pub available_at: UtcTimestamp,
    pub valid_from: UtcTimestamp,
    pub valid_through: UtcTimestamp,
    pub authority: EvidenceAuthorityV1,
    pub domain: StableString,
    pub carrier: StableString,
    pub unit: StableString,
    pub topology_version: Option<StableString>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrozenInputManifestV1 {
    pub evidence: Vec<EvidenceInputV1>,
    pub coverage_ids: Vec<StableString>,
    pub gap_ids: Vec<StableString>,
    pub maximum_input_availability: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OccurrenceConditioningV1 {
    pub decision_kind: StableString,
    pub lifecycle_or_regime: StableString,
    pub direction: DirectionV1,
    pub exact_size_atoms: WireU128,
    pub asset_id: StableString,
    pub numeraire_asset_id: StableString,
    pub downstream_policy_id: StableString,
    pub support_state: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "occurrenceKind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum OccurrenceKindV1 {
    Initial,
    RevisionLandmark {
        landmark_id: StableString,
        prior_occurrence: ArtifactRefV1,
        evidence_class: StableString,
    },
}

/// Prospectively declared shape of the sealed first-round forecast journal.
///
/// This is a semantic registration only. Durable blindness additionally requires the opaque
/// store capability exposed by this crate.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SealedForecastJournalV1 {
    pub namespace_id: StableString,
    pub eligible_first_round_forecaster_ids: Vec<StableString>,
    pub required_first_round_count: WireU64,
    pub reveal_not_before: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClaimOccurrenceV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub claim_occurrence_id: StableString,
    pub claim_definition: ArtifactRefV1,
    pub occurrence_kind: OccurrenceKindV1,
    pub scene: ArtifactRefV1,
    pub instrumented_universe: ArtifactRefV1,
    pub subject_id: StableString,
    pub portfolio_domain_id: Option<StableString>,
    pub occurrence_information_cutoff: UtcTimestamp,
    pub occurrence_commit_at: UtcTimestamp,
    pub issue_deadline: UtcTimestamp,
    pub target_window_origin: UtcTimestamp,
    pub horizon_at: UtcTimestamp,
    pub knowledge_deadline: UtcTimestamp,
    pub sealed_forecast_journal: SealedForecastJournalV1,
    pub frozen_input: FrozenInputManifestV1,
    pub conditioning: OccurrenceConditioningV1,
    pub capability_closure: Vec<CapabilityAttestationV1>,
    pub authority: EpistemicAuthorityV1,
}

/// Unverified integration projection of objects a future private store adapter must resolve.
/// Equality against this caller-owned value is contract testing only; it grants no maturity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedOccurrencePortV1 {
    pub scene: ArtifactRefV1,
    pub instrumented_universe: ArtifactRefV1,
    pub capabilities: Vec<CapabilityAttestationV1>,
}

/// Unverified projection of desired occurrence commit facts. It is not a store capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedOccurrenceCommitPortV1 {
    pub committed_occurrence: ArtifactRefV1,
    pub commit_receipt: ArtifactRefV1,
    pub committed_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProducerLineageV1 {
    pub forecaster_id: StableString,
    pub producer_kind: StableString,
    pub provider: StableString,
    pub checkpoint: StableString,
    pub prompt_template_digest: ValueDigest,
    pub training_snapshot_digest: ValueDigest,
    pub calibration_snapshot_digest: Option<ValueDigest>,
    pub lineage_groups: Vec<StableString>,
    pub primary_lineage_group: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "phase",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum SubmissionPhaseV1 {
    FirstRound,
    Revision {
        revises_submission: ArtifactRefV1,
        visible_parent_submission_ids: Vec<StableString>,
        visible_ensemble_ids: Vec<StableString>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeProbabilityV1 {
    pub outcome_id: StableString,
    pub probability_ppm: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "forecastKind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ForecastPayloadV1 {
    Categorical {
        probabilities: Vec<OutcomeProbabilityV1>,
    },
    Abstain {
        reason: StableString,
    },
    Missing {
        reason: StableString,
    },
    Unsupported {
        reason: StableString,
    },
    Refused {
        reason: StableString,
    },
    Qualitative {
        disposition: StableString,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ForecastSubmissionV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub submission_id: StableString,
    pub claim_occurrence: ArtifactRefV1,
    pub phase: SubmissionPhaseV1,
    pub lineage: ProducerLineageV1,
    pub frozen_input_manifest_digest: ValueDigest,
    pub maximum_input_availability: UtcTimestamp,
    pub submission_input_cutoff: UtcTimestamp,
    pub submission_production_time: UtcTimestamp,
    pub payload: ForecastPayloadV1,
    pub support_statement: StableString,
    pub uncertainty_statement: StableString,
    pub authority: EpistemicAuthorityV1,
}

/// Unverified projection of desired commit/visibility facts. It cannot prove blindness or timing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedSubmissionCommitPortV1 {
    pub committed_submission: ArtifactRefV1,
    pub commit_receipt: ArtifactRefV1,
    pub committed_at: UtcTimestamp,
    pub visible_forecast_ids_before_commit: Vec<StableString>,
    pub visible_ensemble_ids_before_commit: Vec<StableString>,
    pub revealed_at: Option<UtcTimestamp>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutcomeCoverageStatusV1 {
    Complete,
    Partial,
    Gapped,
    Unavailable,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeEvidenceV1 {
    pub artifact: ArtifactRefV1,
    pub available_at: UtcTimestamp,
    pub observation_contract: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeCoverageV1 {
    pub status: OutcomeCoverageStatusV1,
    pub coverage_ids: Vec<StableString>,
    pub gap_ids: Vec<StableString>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "disposition",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum AdjudicationDispositionV1 {
    ResolvedObserved {
        outcome_id: StableString,
    },
    ResolvedFrozenReplay {
        outcome_id: StableString,
        replay_manifest: ArtifactRefV1,
    },
    HealthyNoEventThroughHorizon {
        outcome_id: StableString,
    },
    AdministrativeCensored {
        reason: StableString,
    },
    SourceLossCensored {
        gap_ids: Vec<StableString>,
    },
    LeftTruncated {
        reason: StableString,
    },
    IntervalCensored {
        lower: Option<UtcTimestamp>,
        upper: Option<UtcTimestamp>,
    },
    CompetingEvent {
        event_kind: StableString,
    },
    RouteOrLiquidationRefused {
        reason: StableString,
    },
    InterventionInvalidatedActualPath {
        intervention_id: StableString,
    },
    Conflicting {
        observation_ids: Vec<StableString>,
    },
    Unsupported {
        reason: StableString,
    },
    OpenNotMature,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AdjudicationV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub adjudication_id: StableString,
    pub adjudication_version: WireU64,
    pub supersedes: Option<ArtifactRefV1>,
    pub claim_occurrence: ArtifactRefV1,
    pub adjudicated_at: UtcTimestamp,
    pub knowledge_cutoff: UtcTimestamp,
    pub evidence: Vec<OutcomeEvidenceV1>,
    pub coverage: OutcomeCoverageV1,
    pub disposition: AdjudicationDispositionV1,
    pub resolver_build_digest: ValueDigest,
    pub authority: EpistemicAuthorityV1,
}

/// Unverified projection of desired adjudication evidence/coverage closure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedAdjudicationPortV1 {
    pub claim_occurrence: ArtifactRefV1,
    pub knowledge_cutoff: UtcTimestamp,
    pub evidence: Vec<OutcomeEvidenceV1>,
    pub coverage: OutcomeCoverageV1,
    pub commit_receipt: ArtifactRefV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScoreOrientationV1 {
    LowerLossBetter,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactLossV1 {
    pub numerator: WireU128,
    pub denominator: WireU128,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IncrementSignV1 {
    CandidateBetter,
    Equal,
    CandidateWorse,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ScoreIncrementV1 {
    pub sign: IncrementSignV1,
    pub magnitude_numerator: WireU128,
    pub denominator: WireU128,
}

/// Exact, non-promoting arithmetic preview. It is not a score artifact and carries no maturity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BrierScorePreviewV1 {
    pub outcome_id: StableString,
    pub candidate_loss: ExactLossV1,
    pub baseline_loss: Option<ExactLossV1>,
    pub baseline_increment: Option<ScoreIncrementV1>,
    pub status: EpistemicImplementationStatusV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProperScoreArtifactV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub score_id: StableString,
    pub claim_occurrence: ArtifactRefV1,
    pub submission: ArtifactRefV1,
    pub adjudication: ArtifactRefV1,
    pub baseline_submission: Option<ArtifactRefV1>,
    pub scoring_rule: ProperScoreRuleV1,
    pub outcome_id: StableString,
    pub candidate_loss: ExactLossV1,
    pub baseline_loss: Option<ExactLossV1>,
    pub baseline_increment: Option<ScoreIncrementV1>,
    pub orientation: ScoreOrientationV1,
    pub calculation_build_digest: ValueDigest,
    pub authority: EpistemicAuthorityV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AdjudicationCountV1 {
    pub disposition: StableString,
    pub count: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvaluationWindowV1 {
    pub window_id: StableString,
    pub start: UtcTimestamp,
    pub end: UtcTimestamp,
    pub embargo_through: UtcTimestamp,
    pub eligible_score_count: WireU64,
    pub score_memberships: Vec<WindowScoreMembershipV1>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WindowScoreMembershipV1 {
    pub score: ArtifactRefV1,
    pub claim_occurrence: ArtifactRefV1,
    pub adjudication: ArtifactRefV1,
    pub outcome_available_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CalibrationBinV1 {
    pub outcome_id: StableString,
    pub lower_ppm: WireU64,
    pub upper_ppm: WireU64,
    pub mean_forecast_ppm: WireU64,
    pub occurrence_count: WireU64,
    pub observed_count: WireU64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupportMaturityV1 {
    ClosureOnly,
    DescriptiveSupport,
    RepeatedProspectiveSupport,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupportCalibrationSummaryV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub summary_id: StableString,
    pub claim_definition: ArtifactRefV1,
    pub score_artifacts: Vec<ArtifactRefV1>,
    pub total_occurrences: WireU64,
    pub scored_occurrences: WireU64,
    pub adjudication_counts: Vec<AdjudicationCountV1>,
    pub coverage_ids: Vec<StableString>,
    pub gap_ids: Vec<StableString>,
    pub windows: Vec<EvaluationWindowV1>,
    pub calibration_bins: Vec<CalibrationBinV1>,
    pub maturity: SupportMaturityV1,
    pub authority: EpistemicAuthorityV1,
}

/// Unverified projection of support facts requested from a future private store adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedSupportPortV1 {
    pub claim_definition: ArtifactRefV1,
    pub score_artifacts: Vec<ArtifactRefV1>,
    pub total_occurrences: WireU64,
    pub scored_occurrences: WireU64,
    pub windows: Vec<EvaluationWindowV1>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EnsembleComponentV1 {
    pub submission: ArtifactRefV1,
    pub primary_lineage_group: StableString,
    pub weight_numerator: WireU64,
    pub weight_denominator: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShadowEnsembleV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub ensemble_id: StableString,
    pub claim_occurrence: ArtifactRefV1,
    pub support_summary: ArtifactRefV1,
    pub aggregation_contract: StableString,
    pub components: Vec<EnsembleComponentV1>,
    pub effective_lineage_count: WireU64,
    pub output: Vec<OutcomeProbabilityV1>,
    pub authority: EpistemicAuthorityV1,
}

/// Explicit ceiling of the current pure implementation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpistemicImplementationStatusV1 {
    ContractDraftFixtureValidated,
}

/// Missing private capabilities that prevent prospective promotion.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableProofRequirementV1 {
    StoreCommittedOccurrence,
    StoreResolvedFrozenEvidence,
    StoreResolvedCapabilityClosure,
    SealedSubmissionNamespace,
    StoreDerivedVisibilityAndReveal,
    StoreResolvedAdjudication,
    StoreDerivedSupportMembership,
}

/// Semantic preflight can find incompatibility but cannot mint durable eligibility.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "eligibility",
    rename_all = "snake_case",
    rename_all_fields = "camelCase"
)]
pub enum ShadowEnsembleEligibilityV1 {
    SemanticallyIneligible {
        reasons: Vec<StableString>,
    },
    BlockedMissingDurableProof {
        status: EpistemicImplementationStatusV1,
        required: Vec<DurableProofRequirementV1>,
    },
}

// These opaque types deliberately have no public constructor. A future private adapter in this
// crate may mint them only after resolving exact store rows and receipts.
#[derive(Debug)]
pub struct DurableOccurrenceCapability {
    occurrence: ArtifactRefV1,
    commit_receipt: ArtifactRefV1,
    committed_at: UtcTimestamp,
    frozen_input_manifest_digest: ValueDigest,
    capability_closure_digest: ValueDigest,
}

impl DurableOccurrenceCapability {
    #[must_use]
    pub const fn occurrence(&self) -> &ArtifactRefV1 {
        &self.occurrence
    }

    #[must_use]
    pub const fn committed_at(&self) -> UtcTimestamp {
        self.committed_at
    }

    #[must_use]
    pub const fn commit_receipt(&self) -> &ArtifactRefV1 {
        &self.commit_receipt
    }

    #[must_use]
    pub const fn frozen_input_manifest_digest(&self) -> &ValueDigest {
        &self.frozen_input_manifest_digest
    }

    #[must_use]
    pub const fn capability_closure_digest(&self) -> &ValueDigest {
        &self.capability_closure_digest
    }
}

#[derive(Debug)]
pub struct DurableSubmissionCapability {
    submission: ArtifactRefV1,
    occurrence: ArtifactRefV1,
    commit_receipt: ArtifactRefV1,
    committed_at: UtcTimestamp,
    sealed_namespace_id: StableString,
    visible_submission_ids_before_commit: Vec<StableString>,
    visible_ensemble_ids_before_commit: Vec<StableString>,
    all_first_round_sealed_at: Option<UtcTimestamp>,
    reveal_at: Option<UtcTimestamp>,
}

impl DurableSubmissionCapability {
    #[must_use]
    pub const fn submission(&self) -> &ArtifactRefV1 {
        &self.submission
    }

    #[must_use]
    pub const fn occurrence(&self) -> &ArtifactRefV1 {
        &self.occurrence
    }

    #[must_use]
    pub const fn committed_at(&self) -> UtcTimestamp {
        self.committed_at
    }

    #[must_use]
    pub const fn commit_receipt(&self) -> &ArtifactRefV1 {
        &self.commit_receipt
    }

    #[must_use]
    pub const fn sealed_namespace_id(&self) -> &StableString {
        &self.sealed_namespace_id
    }

    #[must_use]
    pub fn visible_submission_ids_before_commit(&self) -> &[StableString] {
        &self.visible_submission_ids_before_commit
    }

    #[must_use]
    pub fn visible_ensemble_ids_before_commit(&self) -> &[StableString] {
        &self.visible_ensemble_ids_before_commit
    }

    #[must_use]
    pub const fn all_first_round_sealed_at(&self) -> Option<UtcTimestamp> {
        self.all_first_round_sealed_at
    }

    #[must_use]
    pub const fn reveal_at(&self) -> Option<UtcTimestamp> {
        self.reveal_at
    }
}

#[derive(Debug)]
pub struct DurableAdjudicationCapability {
    adjudication: ArtifactRefV1,
    occurrence: ArtifactRefV1,
    commit_receipt: ArtifactRefV1,
    committed_at: UtcTimestamp,
}

impl DurableAdjudicationCapability {
    #[must_use]
    pub const fn adjudication(&self) -> &ArtifactRefV1 {
        &self.adjudication
    }

    #[must_use]
    pub const fn occurrence(&self) -> &ArtifactRefV1 {
        &self.occurrence
    }

    #[must_use]
    pub const fn commit_receipt(&self) -> &ArtifactRefV1 {
        &self.commit_receipt
    }

    #[must_use]
    pub const fn committed_at(&self) -> UtcTimestamp {
        self.committed_at
    }
}

#[derive(Debug)]
pub struct DurableSupportCapability {
    summary: ArtifactRefV1,
    derivation_receipt: ArtifactRefV1,
    latest_embargo_through: UtcTimestamp,
}

impl DurableSupportCapability {
    #[must_use]
    pub const fn summary(&self) -> &ArtifactRefV1 {
        &self.summary
    }

    #[must_use]
    pub const fn latest_embargo_through(&self) -> UtcTimestamp {
        self.latest_embargo_through
    }

    #[must_use]
    pub const fn derivation_receipt(&self) -> &ArtifactRefV1 {
        &self.derivation_receipt
    }
}
