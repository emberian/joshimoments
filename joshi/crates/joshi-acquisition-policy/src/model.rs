use std::collections::BTreeMap;

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64, WireU128};
use serde::{Deserialize, Serialize};

/// Append-only record occurrence identity. It is not a content digest.
pub type RecordId = StableString;

/// Common append-only occurrence header.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PolicyRecordHead {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub record_id: RecordId,
    pub record_ordinal: WireU64,
    pub recorded_at: UtcTimestamp,
    pub predecessor_record_id: Option<RecordId>,
}

/// Typed reference to retained evidence. Collections must be sorted and duplicate-free.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceLink {
    pub kind: EvidenceKind,
    pub id: StableString,
    pub digest: Option<ValueDigest>,
    pub available_at: UtcTimestamp,
    pub commit_seq: Option<WireU64>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceKind {
    Observation,
    Assertion,
    Coverage,
    Artifact,
    Scene,
    OperatorCommand,
    Receipt,
    PolicyOccurrence,
    SourceHealth,
}

/// Knowledge cutoff carried by an intent; later-known inputs cannot be smuggled into it.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AsOfCutoff {
    pub available_through: UtcTimestamp,
    pub commit_through: Option<WireU64>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SubjectKind {
    Mint,
    Wallet,
    Profile,
    Community,
    Territory,
}

/// Public subject selected for observation. It conveys no ownership or identity claim.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ScopeSubject {
    pub kind: SubjectKind,
    pub key: StableString,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CensusKind {
    IndependentChainProvider,
    ProductBoardParityPassed,
}

/// Exact denominator closure retained independently of hot-lane admission or eviction.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CensusDenominatorRef {
    pub census_id: StableString,
    pub kind: CensusKind,
    pub eligible_membership_artifact_id: StableString,
    pub eligible_universe_digest: ValueDigest,
    pub eligible_subject_count: WireU64,
    pub as_of: AsOfCutoff,
    pub evidence: Vec<EvidenceLink>,
    pub coverage_evidence: Vec<EvidenceLink>,
    pub parity_receipt_id: Option<StableString>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IntentReasonKind {
    OperatorNomination,
    SelectedAttentionOccurrence,
    WalletCandidate,
    DeterministicCensusRule,
    ModelProposal,
}

/// One justification occurrence. Activity, return, and win/loss are deliberately absent.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IntentReason {
    pub kind: IntentReasonKind,
    pub reason_id: StableString,
    pub justified_at: UtcTimestamp,
    pub evidence: Vec<EvidenceLink>,
}

/// Activation authority. A model proposal is retained but never activates directly.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ActivationAuthority {
    OperatorAccepted(Box<OperatorAcceptanceBinding>),
    DeterministicRule {
        rule_id: StableString,
        rule_version: StableString,
    },
    ProposalOnly {
        model_artifact_id: StableString,
        model_proposal_id: StableString,
    },
}

/// Exact durable operator-command and scene closure authorizing a distinct hot-scope intent.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperatorAcceptanceBinding {
    pub operator_command_id: StableString,
    pub operator_command_digest: ValueDigest,
    pub operator_admission_receipt_id: StableString,
    pub scene_id: StableString,
    pub scene_view_digest: ValueDigest,
    pub presentation_choice_binding: Option<PresentationChoiceBinding>,
}

/// Optional exact sibling closure when an admitted command is presentation/choice complete.
/// Absence means the activation is scene-bound but must not be called witnessed-presentation
/// complete.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationChoiceBinding {
    pub binding_id: StableString,
    pub presentation_id: StableString,
    pub presentation_digest: ValueDigest,
    pub choice_context_id: Option<StableString>,
    pub choice_context_digest: Option<ValueDigest>,
    pub available_at: UtcTimestamp,
    pub commit_seq: WireU64,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceFamily {
    HeliusPublicChain,
    SolanaPublicRpc,
    PumpPortalPublic,
    PumpProductPublic,
    PumpProductAuthenticated,
    SocialProfile,
    PublicMedia,
    LifecycleState,
    PoolState,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MediaFidelity {
    None,
    MetadataOnly,
    ExactOptional,
}

/// Requested or effective source fidelity.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Fidelity {
    pub exact_public_bodies: bool,
    pub exact_private_bodies_optional: bool,
    pub media: MediaFidelity,
    pub refresh_interval_us: Option<WireU64>,
}

/// Explicit provider-currency permission. Empty collection means no provider-currency spend.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderCurrencyBudget {
    pub currency: StableString,
    pub max_minor_units: WireU128,
    pub decimals_evidence: EvidenceLink,
}

/// Explicit chain-native permission. Empty collection means no chain-native units are authorized.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChainNativeBudget {
    pub asset_id: StableString,
    pub max_atoms: WireU128,
    pub decimals_evidence: EvidenceLink,
}

/// Independent hard caps; no dimension may borrow from another.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BudgetEnvelope {
    pub max_requests: WireU64,
    pub max_pages: WireU64,
    pub max_response_bytes: WireU64,
    pub max_provider_credits: WireU64,
    pub provider_currency: Vec<ProviderCurrencyBudget>,
    pub chain_native: Vec<ChainNativeBudget>,
}

/// One exact source operation requested by an intent.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceScopeRequest {
    pub source_key: StableString,
    pub operation_key: StableString,
    pub source_family: SourceFamily,
    pub fidelity: Fidelity,
    pub budget: BudgetEnvelope,
}

impl Ord for BudgetEnvelope {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        (
            self.max_requests,
            self.max_pages,
            self.max_response_bytes,
            self.max_provider_credits,
            &self.provider_currency,
            &self.chain_native,
        )
            .cmp(&(
                other.max_requests,
                other.max_pages,
                other.max_response_bytes,
                other.max_provider_credits,
                &other.provider_currency,
                &other.chain_native,
            ))
    }
}

impl PartialOrd for BudgetEnvelope {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

/// Append-only request to consider one bounded hot scope.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeIntentV1 {
    pub head: PolicyRecordHead,
    pub intent_id: StableString,
    pub subject: ScopeSubject,
    pub opened_at: UtcTimestamp,
    pub expires_at: UtcTimestamp,
    pub last_justified_at: UtcTimestamp,
    pub requesting_occurrence_id: StableString,
    pub scene_id: Option<StableString>,
    pub policy_occurrence_id: StableString,
    pub policy_config_digest: ValueDigest,
    pub as_of: AsOfCutoff,
    pub authority: StableString,
    pub activation: ActivationAuthority,
    pub reasons: Vec<IntentReason>,
    pub census_denominators: Vec<CensusDenominatorRef>,
    pub requested_sources: Vec<SourceScopeRequest>,
}

/// Per-source hard ceiling and behavior policy.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourcePolicyV1 {
    pub source_key: StableString,
    pub operation_keys: Vec<StableString>,
    pub maximum_budget: BudgetEnvelope,
    pub native_units_authorized: bool,
}

/// Versioned deterministic policy configuration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PolicyConfigV1 {
    pub policy_id: StableString,
    pub policy_version: StableString,
    pub config_digest: ValueDigest,
    pub max_hot_mints: WireU64,
    pub max_hot_wallets: WireU64,
    pub max_other_subjects: WireU64,
    pub shortened_hot_ttl_us: WireU64,
    pub degraded_social_refresh_us: WireU64,
    pub source_policies: Vec<SourcePolicyV1>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceAvailability {
    Healthy,
    Degraded,
    Unavailable,
}

/// Durable source generation known to the policy/controller boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CollectorGeneration {
    pub source_key: StableString,
    pub generation: WireU64,
    pub availability: SourceAvailability,
    pub evidence: Vec<EvidenceLink>,
}

/// Exact resource readings used to select a deterministic degradation stage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceSnapshotV1 {
    pub sampled_at: UtcTimestamp,
    pub evidence: Vec<EvidenceLink>,
    pub queue_records_used: WireU64,
    pub queue_record_capacity: WireU64,
    pub queue_record_control_reserve: WireU64,
    pub queue_bytes_used: WireU64,
    pub queue_byte_capacity: WireU64,
    pub queue_byte_control_reserve: WireU64,
    pub spool_bytes_today: WireU64,
    pub max_spool_bytes_today: WireU64,
    pub disk_free_bytes: WireU64,
    pub disk_floor_bytes: WireU64,
    pub control_reserve_free_bytes: WireU64,
    pub control_reserve_required_bytes: WireU64,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PressureStage {
    Full,
    DropOptionalBodies,
    SlowRefresh,
    ShortenHotLeases,
    DenominatorOnly,
    StopBeforeReserve,
}

/// One replay evaluation occurrence. It has no provider or economic authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PolicyEvaluationV1 {
    pub decision_occurrence_id: StableString,
    pub evaluated_at: UtcTimestamp,
    pub policy: PolicyConfigV1,
    pub resources: ResourceSnapshotV1,
    pub collector_generations: Vec<CollectorGeneration>,
}

/// Effective scope carried to an inert collector-control command.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EffectiveScope {
    pub subject: ScopeSubject,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub source_family: SourceFamily,
    pub fidelity: Fidelity,
    pub budget: BudgetEnvelope,
    pub expires_at: UtcTimestamp,
    pub census_denominators: Vec<CensusDenominatorRef>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScopePresence {
    Active,
    Absent,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeDesiredV1 {
    pub head: PolicyRecordHead,
    pub intent_id: StableString,
    pub intent_record_id: RecordId,
    pub decision_occurrence_id: StableString,
    pub scope: EffectiveScope,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DegradationReason {
    OptionalBodiesDropped,
    SocialRefreshSlowed,
    HotLeaseShortened,
    CapacityEvictedLeastRecentlyJustified,
    SourceUnavailable,
    SourceDegraded,
    BudgetRefused,
    PolicyConfigMismatch,
    ModelProposalNonactivating,
    DenominatorOnlyOverload,
    StopBeforeReserve,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DegradationChange {
    pub reason: DegradationReason,
    pub detail: StableString,
    pub evidence: Vec<EvidenceLink>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeDegradedV1 {
    pub head: PolicyRecordHead,
    pub intent_id: StableString,
    pub intent_record_id: RecordId,
    pub decision_occurrence_id: StableString,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub effective_scope: Option<EffectiveScope>,
    pub changes: Vec<DegradationChange>,
    pub census_denominators_retained: Vec<CensusDenominatorRef>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeClosedV1 {
    pub head: PolicyRecordHead,
    pub intent_id: StableString,
    pub intent_record_id: RecordId,
    pub decision_occurrence_id: StableString,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub reason: StableString,
    pub census_denominators_retained: Vec<CensusDenominatorRef>,
}

/// Source-control application receipt. This is not provider acceptance or coverage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotScopeAppliedV1 {
    pub head: PolicyRecordHead,
    pub intent_id: StableString,
    pub target_record_id: RecordId,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub generation: WireU64,
    pub presence: ScopePresence,
    pub control_command_id: StableString,
    pub control_bytes_digest: ValueDigest,
    pub control_write_reservation_id: StableString,
    pub control_write_reservation_digest: ValueDigest,
    pub control_write_attempt_ordinal: WireU64,
    pub control_write_receipt_id: StableString,
    pub control_handed_to_adapter_at: UtcTimestamp,
    pub adapter_version: StableString,
    pub provider_acceptance: StableString,
    pub coverage_status: StableString,
}

/// Closed record family retained in one append-only journal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "recordKind", rename_all = "snake_case", deny_unknown_fields)]
pub enum HotScopeRecordV1 {
    Intent(HotScopeIntentV1),
    Desired(HotScopeDesiredV1),
    Applied(HotScopeAppliedV1),
    Degraded(HotScopeDegradedV1),
    Closed(HotScopeClosedV1),
}

impl HotScopeRecordV1 {
    #[must_use]
    pub const fn head(&self) -> &PolicyRecordHead {
        match self {
            Self::Intent(value) => &value.head,
            Self::Desired(value) => &value.head,
            Self::Applied(value) => &value.head,
            Self::Degraded(value) => &value.head,
            Self::Closed(value) => &value.head,
        }
    }
}

/// Deterministic replay result. Denominators survive even when every hot scope is absent.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PolicyDecisionV1 {
    pub decision_occurrence_id: StableString,
    pub evaluated_at: UtcTimestamp,
    pub pressure_stage: PressureStage,
    pub new_records: Vec<HotScopeRecordV1>,
    pub retained_census_denominators: Vec<CensusDenominatorRef>,
    pub inactive_model_proposal_intent_ids: Vec<StableString>,
    pub latest_desired_presence: BTreeMap<StableString, ScopePresence>,
}
