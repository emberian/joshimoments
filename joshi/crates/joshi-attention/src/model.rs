use crate::{
    ATTENTION_CONTRACT, AttentionEventId, AttentionInputId, ClusterContextId, CohortRowId,
    CommunityId, IdentityVersionId, JsonNumberLexeme, KernelEventId, RevisionId, SignedWireI64,
    SubjectId, TerritorySnapshotId, WalletClusterHypothesisId,
};
use joshi_domain::{
    AccountId, AcquisitionId, AssetId, BlobId, ClientSessionId, CommitSeq, CoverageId,
    ObservationId, PoolId, SceneId, SourceId, StableString, UtcTimestamp, ValueDigest, VenueId,
    WireU64,
};
use serde::{Deserialize, Serialize};

/// A complete versioned attention dataset, including source inputs and study-ready tables.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttentionDataset {
    /// Must equal [`ATTENTION_CONTRACT`].
    pub contract: StableString,
    /// Immutable source-derived input occurrences.
    pub exact_inputs: Vec<ExactAttentionInput>,
    /// Point-in-time social identity assertions.
    pub identity_versions: Vec<IdentityVersion>,
    /// Versioned follow edges; absence from a partial snapshot is never deletion.
    pub follow_edge_versions: Vec<FollowEdgeVersion>,
    /// Point-in-time, non-exclusive social territory assertions.
    pub territory_snapshots: Vec<TerritorySnapshot>,
    /// Adapter-selected wallet-cluster contexts bound to exact attention events.
    pub selected_cluster_contexts: Vec<SelectedClusterContext>,
    /// Marked forcing events selected from source occurrences.
    pub attention_events: Vec<AttentionEvent>,
    /// Event index used by response-kernel construction.
    pub kernel_events: Vec<KernelEventRow>,
    /// Long-form, through-cut marks; future outcome annotations are excluded.
    pub kernel_marks: Vec<KernelMarkRow>,
    /// Separately covered audience-set intersections and denominators.
    pub audience_overlap_estimates: Vec<AudienceOverlapEstimate>,
    /// Post-anchor observations, including explicit source loss and censoring.
    pub response_observations: Vec<ResponseObservationRow>,
    /// Versioned risk-set/cohort membership rows.
    pub cohort_rows: Vec<RiskSetCohortRow>,
}

impl Default for AttentionDataset {
    fn default() -> Self {
        Self {
            contract: StableString::new(ATTENTION_CONTRACT)
                .unwrap_or_else(|_| unreachable!("static contract is valid")),
            exact_inputs: Vec::new(),
            identity_versions: Vec::new(),
            follow_edge_versions: Vec::new(),
            territory_snapshots: Vec::new(),
            selected_cluster_contexts: Vec::new(),
            attention_events: Vec::new(),
            kernel_events: Vec::new(),
            kernel_marks: Vec::new(),
            audience_overlap_estimates: Vec::new(),
            response_observations: Vec::new(),
            cohort_rows: Vec::new(),
        }
    }
}

/// Source clocks, provenance, protection, and scope shared by every exact input.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceContext {
    /// Restart-global acquisition occurrence identity.
    pub acquisition_id: AcquisitionId,
    /// Exact retained observation occurrence identity.
    pub observation_id: ObservationId,
    /// Source adapter contract.
    pub source_id: SourceId,
    /// Source-specific route/variant, such as `pump_api.callout_recent`.
    pub source_variant: StableString,
    /// Local receipt time.
    pub observed_at: UtcTimestamp,
    /// Durable availability wall time.
    pub available_at: UtcTimestamp,
    /// Local durable commit through which the evidence is available.
    pub available_commit: CommitSeq,
    /// Coverage for the exact population/query/page that could contain the occurrence.
    pub coverage: CoverageContext,
    /// Access/privacy boundary; content identity does not imply this class.
    pub protection_domain: ProtectionDomain,
    /// Retention policy class for this observation.
    pub retention_class: RetentionClass,
    /// What the source occurrence directly establishes.
    pub epistemic_class: EpistemicClass,
}

/// Source event-time interval. Missing clocks are explicit, never replaced by receipt time.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventTime {
    /// Exact, bounded, missing, or not applicable.
    pub status: EventTimeStatus,
    /// Inclusive lower instant when known.
    pub lower: Option<UtcTimestamp>,
    /// Exclusive upper instant when known. All event intervals are `[lower, upper)`.
    pub upper: Option<UtcTimestamp>,
    /// Claimed source precision in microseconds.
    pub precision_us: Option<WireU64>,
    /// Source-native value before interpretation.
    pub source_value: Option<StableString>,
}

/// Event-time knowledge state.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventTimeStatus {
    /// Source establishes one instant up to its precision.
    Exact,
    /// Source establishes only an interval.
    Bounded,
    /// Relevant source clock was absent, malformed, or censored.
    SourceMissing,
    /// The source object has no event-time semantics.
    NotApplicable,
}

/// Scope-aware coverage for one source population.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CoverageContext {
    /// Logical query/population scope, not merely a route name.
    pub scope_id: CoverageId,
    /// Human-auditable population definition such as board/filter/cursor/root.
    pub population: StableString,
    /// Complete, partial, gapped, unknown, or not applicable.
    pub state: CoverageState,
    /// Evidence-backed acquisition windows supporting this claim.
    pub window_ids: Vec<CoverageId>,
    /// Exact scoped gaps intersecting the observation/risk window.
    pub gap_ids: Vec<CoverageId>,
    /// Opaque provider cursor/page/rank boundary if present.
    pub source_cursor: Option<StableString>,
}

/// Coverage state; `unknown` and `partial` are never interpreted as absence.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoverageState {
    Complete,
    Partial,
    Gapped,
    Unknown,
    NotApplicable,
}

/// Data-protection boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtectionDomain {
    PublicProtocol,
    PublicProduct,
    AuthenticatedPrivateSocial,
    OperatorPrivate,
    DerivedRestricted,
}

/// Retention policy class, interpreted by the store rather than by content hashes.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetentionClass {
    PermanentEvidence,
    LocalPrivateRaw,
    StructuredMinimum,
    EphemeralReconnaissance,
    DerivedResearch,
}

/// Epistemic class; none of these values means a causal effect.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpistemicClass {
    ProtocolFact,
    ProviderAssertion,
    FirstPartyStatement,
    OperatorAnnotation,
    ProviderPresentation,
    DerivedMeasure,
    ModelInference,
}

/// One immutable input occurrence derived from retained source evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExactAttentionInput {
    pub input_id: AttentionInputId,
    pub evidence: EvidenceContext,
    pub event_time: EventTime,
    #[serde(flatten)]
    pub kind: ExactInputKind,
}

/// Supported exact source-input families.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "payload", rename_all = "snake_case")]
pub enum ExactInputKind {
    CalloutObserved(CalloutObserved),
    FollowSnapshotObserved(FollowSnapshotObserved),
    FollowSnapshotMember(FollowSnapshotMember),
    CreatorRelationObserved(CreatorRelationObserved),
    CommunitySnapshotObserved(CommunitySnapshotObserved),
    SocialContentObserved(SocialContentObserved),
    IdentityLinkObserved(IdentityLinkObserved),
    SocialTransitionObserved(SocialTransitionObserved),
}

/// Boundary record for one fully or partially observed follow/follower snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FollowSnapshotObserved {
    pub snapshot_id: StableString,
    pub direction: FollowDirection,
    pub root_subject_id: SubjectId,
    pub reported_total: Option<WireU64>,
    pub observed_member_count: WireU64,
    pub pagination_complete: bool,
}

/// Exact provider fields for one callout revision.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalloutObserved {
    pub provider_callout_id: StableString,
    pub revision_id: RevisionId,
    pub supersedes_revision_id: Option<RevisionId>,
    pub mint_id: AssetId,
    pub provider_user_id: Option<SubjectId>,
    pub author_wallet_id: Option<AccountId>,
    pub thesis_blob_id: Option<BlobId>,
    pub callout_price_lexeme: Option<JsonNumberLexeme>,
    pub market_cap_lexeme: Option<JsonNumberLexeme>,
    pub amount_atoms: Option<WireU64>,
    pub amount_asset_id: Option<AssetId>,
    pub direction: CalloutDirection,
    pub content_state: ContentState,
    /// Outcome-ranked provider fields retained as retrospective annotations only.
    pub retrospective_outcomes: Vec<RetrospectiveOutcomeAssertion>,
}

/// Callout direction when the source establishes it.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CalloutDirection {
    Positive,
    Negative,
    Neutral,
    Unspecified,
}

/// A future-derived provider value that must never become an anchor-time feature.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetrospectiveOutcomeAssertion {
    pub name: StableString,
    pub value: JsonNumberLexeme,
    pub as_of: UtcTimestamp,
    pub available_at: UtcTimestamp,
}

/// One member of one explicitly scoped follow/follower snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FollowSnapshotMember {
    pub snapshot_id: StableString,
    pub direction: FollowDirection,
    pub root_subject_id: SubjectId,
    pub member_subject_id: SubjectId,
    pub root_wallet_id: Option<AccountId>,
    pub member_wallet_id: Option<AccountId>,
    pub provider_follow_time: EventTime,
    pub ordinal: Option<WireU64>,
}

/// Edge direction relative to the snapshot root.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FollowDirection {
    RootFollowsMember,
    MemberFollowsRoot,
}

/// Point-in-time follow edge derived from explicitly comparable snapshots.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FollowEdgeVersion {
    pub assertion_id: StableString,
    pub root_subject_id: SubjectId,
    pub member_subject_id: SubjectId,
    pub direction: FollowDirection,
    pub state: FollowEdgeState,
    pub valid_time: TimeInterval,
    pub knowledge_time: KnowledgeInterval,
    pub source_snapshot_input_ids: Vec<AttentionInputId>,
    pub presence_member_input_id: Option<AttentionInputId>,
    pub comparable_scope: bool,
    pub intervening_gap_ids: Vec<CoverageId>,
    pub status: AssertionStatus,
}

/// Presence/removal assertion state.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FollowEdgeState {
    Present,
    RemovalCandidate,
    Removed,
}

/// Exact provider/chain statement about a creator or fee-routing relation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CreatorRelationObserved {
    pub mint_id: AssetId,
    pub relation: CreatorRelation,
    pub subject_wallet_id: Option<AccountId>,
    pub recipient_wallet_id: Option<AccountId>,
    pub actor_wallet_id: Option<AccountId>,
    pub permission_model: PermissionModel,
    pub chain_slot: Option<WireU64>,
}

/// Creator/routing relation. These are deliberately not one monotone lifecycle.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CreatorRelation {
    SignedLaunchUser,
    DeclaredCreator,
    CurrentCreatorField,
    FeeSharingRecipient,
    CreatorVaultAuthority,
    OrdinaryFeeSweep,
}

/// Who may invoke an action; permissionlessness is not human awareness.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PermissionModel {
    Permissionless,
    SubjectSignature,
    PlatformAuthorized,
    ProgramDerived,
    Unknown,
}

/// One provider-qualified current community snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommunitySnapshotObserved {
    pub snapshot_id: StableString,
    pub community_id: CommunityId,
    pub mint_id: Option<AssetId>,
    pub member_count: Option<WireU64>,
    pub message_count: Option<WireU64>,
    pub unique_author_count: Option<WireU64>,
    pub active_author_count: Option<WireU64>,
    pub provider_updated_at: EventTime,
}

/// One content revision, deletion, moderation action, or tombstone occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SocialContentObserved {
    pub provider_object_id: StableString,
    pub revision_id: RevisionId,
    pub supersedes_revision_id: Option<RevisionId>,
    pub content_kind: SocialContentKind,
    pub state: ContentState,
    pub parent_object_id: Option<StableString>,
    pub mint_id: Option<AssetId>,
    pub community_id: Option<CommunityId>,
    pub author_subject_id: Option<SubjectId>,
    pub author_wallet_id: Option<AccountId>,
    pub content_blob_id: Option<BlobId>,
}

/// Provider content family.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SocialContentKind {
    Callout,
    Comment,
    Reply,
    Post,
    LivestreamMessage,
}

/// Revision state. A deletion never erases prior evidence.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContentState {
    Created,
    Edited,
    Deleted,
    Moderated,
    Tombstone,
    Unknown,
}

/// Exact source assertion linking two identity namespaces.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IdentityLinkObserved {
    pub left: IdentityNode,
    pub right: IdentityNode,
    pub relation: IdentityRelation,
    pub source_revision_id: Option<RevisionId>,
}

/// Typed identity namespace member.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "namespace", content = "value", rename_all = "snake_case")]
pub enum IdentityNode {
    PumpUserId(SubjectId),
    ExternalNumericId(StableString),
    Handle(StableString),
    Wallet(AccountId),
    MetadataUrl(StableString),
}

/// Meaning of an observed identity edge; provider linkage is not proof of one human.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentityRelation {
    ProfileClaimsWallet,
    ProviderMapsUserId,
    ProfileUsesHandle,
    MetadataLinksProfile,
    PublicCrossLink,
    SignedByWallet,
}

/// Exact social/creator transition that must not be collapsed into a monotone stage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SocialTransitionObserved {
    pub transition: SocialTransitionKind,
    pub subject_id: Option<SubjectId>,
    pub wallet_id: Option<AccountId>,
    pub mint_id: Option<AssetId>,
    pub community_id: Option<CommunityId>,
    pub authority: PermissionModel,
}

/// Social-transition occurrence family.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SocialTransitionKind {
    SocialFeeClaim,
    CreatorProfileLink,
    CreatorAcknowledgement,
    PublicParticipation,
    PublicEndorsement,
    AudienceArrival,
    DuplicateCoinAppeared,
    FragmentationObserved,
    PersistenceObserved,
    DecayObserved,
}

/// Point-in-time identity version. Conflicts remain explicit versions.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IdentityVersion {
    pub identity_version_id: IdentityVersionId,
    pub identity_series_id: StableString,
    pub subject_id: SubjectId,
    pub provider_user_id: Option<SubjectId>,
    pub handle: Option<StableString>,
    pub display_name: Option<StableString>,
    pub wallet_links: Vec<IdentityWalletLink>,
    pub valid_time: TimeInterval,
    pub knowledge_time: KnowledgeInterval,
    pub status: AssertionStatus,
    pub evidence_input_ids: Vec<AttentionInputId>,
    pub supersedes: Option<IdentityVersionId>,
    pub conflicts_with: Vec<IdentityVersionId>,
}

/// Wallet link within one identity assertion; cluster membership is not stored here.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IdentityWalletLink {
    pub wallet_id: AccountId,
    pub relation: IdentityWalletRelation,
    pub epistemic_class: EpistemicClass,
    pub evidence_input_ids: Vec<AttentionInputId>,
}

/// Social-to-wallet relation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentityWalletRelation {
    ProfileWallet,
    ProviderAuthorWallet,
    SocialClaimRecipient,
    VerifiedSigner,
}

/// Revisable mint/community/creator territory snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TerritorySnapshot {
    pub territory_snapshot_id: TerritorySnapshotId,
    pub territory_series_id: StableString,
    pub mint_id: AssetId,
    pub community_id: Option<CommunityId>,
    pub relation: TerritoryRelation,
    pub leader_identity_version_id: Option<IdentityVersionId>,
    pub valid_time: TimeInterval,
    pub knowledge_time: KnowledgeInterval,
    pub status: AssertionStatus,
    pub confidence: Option<JsonNumberLexeme>,
    pub resolver_version: StableString,
    pub evidence_input_ids: Vec<AttentionInputId>,
    pub supersedes: Option<TerritorySnapshotId>,
    pub competing_snapshot_ids: Vec<TerritorySnapshotId>,
}

/// Non-exclusive territory relation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerritoryRelation {
    LaunchNarrative,
    CommunityAttention,
    CreatorAffiliation,
    TradingFleet,
    DuplicateCompetitor,
}

/// Narrow, adapter-selected projection of one ecology artifact for one attention event.
///
/// This is not ecology's full row and must not be independently re-selected. Artifact, snapshot,
/// query, and adapter identities bind the source closure used for this projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SelectedClusterContext {
    pub cluster_context_id: ClusterContextId,
    pub cluster_hypothesis_id: WalletClusterHypothesisId,
    pub hypothesis_series_id: StableString,
    pub selected_for_attention_event_id: AttentionEventId,
    pub member_wallet_ids: Vec<AccountId>,
    pub source_artifact_digest: ValueDigest,
    pub source_snapshot_digest: ValueDigest,
    pub selection_query_digest: ValueDigest,
    pub selection_adapter_version: StableString,
    pub valid_time: TimeInterval,
    pub valid_slots: Option<SlotInterval>,
    pub source_available_at: UtcTimestamp,
    pub source_available_commit: CommitSeq,
    pub source_status: AssertionStatus,
    pub selected_for_event_time: EventTime,
    pub selected_for_chain_slot: Option<WireU64>,
    pub selected_as_of: UtcTimestamp,
    pub selected_as_of_commit: CommitSeq,
    pub selection_disposition: ClusterSelectionDisposition,
    pub confidence_ppm: Option<WireU64>,
    pub evidence_input_ids: Vec<AttentionInputId>,
    pub adversarial_alternatives: Vec<StableString>,
}

/// Exact adapter query semantics for one selected cluster context.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClusterSelectionDisposition {
    LatestEffectiveKnownForExactCut,
}

/// Half-open chain-slot validity interval for a wallet-cluster hypothesis.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SlotInterval {
    pub lower: WireU64,
    pub upper: Option<WireU64>,
}

/// Valid-time interval, independent of when Joshi learned it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TimeInterval {
    pub lower: UtcTimestamp,
    pub upper: Option<UtcTimestamp>,
}

/// Knowledge-time interval for a versioned assertion.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnowledgeInterval {
    pub known_from: UtcTimestamp,
    pub known_until: Option<UtcTimestamp>,
    pub available_commit: CommitSeq,
}

/// Assertion lifecycle; supported is not verified identity or causal truth.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssertionStatus {
    Candidate,
    Supported,
    Disputed,
    Retracted,
}

/// Marked external input to a response process.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttentionEvent {
    pub attention_event_id: AttentionEventId,
    pub forcing_input_id: AttentionInputId,
    pub event_kind: AttentionEventKind,
    pub mint_id: AssetId,
    pub event_time: EventTime,
    pub observed_at: UtcTimestamp,
    pub available_at: UtcTimestamp,
    pub available_commit: CommitSeq,
    pub caller_identity_version_id: Option<IdentityVersionId>,
    pub caller_wallet_id: Option<AccountId>,
    pub caller_cluster_context_id: Option<ClusterContextId>,
    pub direction: Option<CalloutDirection>,
    pub amount_atoms: Option<WireU64>,
    pub amount_asset_id: Option<AssetId>,
    pub territory_snapshot_id: Option<TerritorySnapshotId>,
    pub community_id: Option<CommunityId>,
    pub venue_id: Option<VenueId>,
    pub pool_id: Option<PoolId>,
    pub chain_slot: Option<WireU64>,
    pub lifecycle_id: Option<StableString>,
    pub regime_epoch: Option<StableString>,
    pub topology_epoch: Option<StableString>,
    pub scene_id: Option<SceneId>,
    pub presentation_context: Option<PresentationContext>,
    pub decision_id: Option<StableString>,
    pub choice_set_id: Option<StableString>,
    pub coverage: CoverageContext,
    /// Literal semantic guard: no causal claim is encoded by this row.
    pub interpretation: AttentionInterpretation,
}

/// Exact witnessed presentation/view binding for UI-derived marks or choices.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PresentationContext {
    pub kind: PresentationContextKind,
    pub presentation_id: StableString,
    pub presentation_digest: ValueDigest,
    pub view_contract: StableString,
    pub view_digest: ValueDigest,
    pub client_session_id: ClientSessionId,
    pub scene_id: SceneId,
    pub policy_version: StableString,
    pub observed_at: UtcTimestamp,
}

/// Provider-product or Joshi Glass presentation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PresentationContextKind {
    ProviderProduct,
    JoshiGlass,
}

/// Event family supplied to response models.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttentionEventKind {
    Callout,
    FollowChange,
    CreatorTransition,
    CommunityTransition,
    CommentBurst,
    SocialTransition,
}

/// Required event interpretation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttentionInterpretation {
    MarkedForcingEventNoCausalClaim,
}

/// One response-kernel event index row.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KernelEventRow {
    pub kernel_event_id: KernelEventId,
    pub attention_event_id: AttentionEventId,
    pub mint_id: AssetId,
    pub event_kind: AttentionEventKind,
    pub event_time: EventTime,
    pub event_available_at: UtcTimestamp,
    pub event_available_commit: CommitSeq,
    pub fit_eligible_from: UtcTimestamp,
    pub caller_identity_version_id: Option<IdentityVersionId>,
    pub caller_wallet_id: Option<AccountId>,
    pub caller_cluster_context_id: Option<ClusterContextId>,
    pub direction: Option<CalloutDirection>,
    pub amount_atoms: Option<WireU64>,
    pub amount_asset_id: Option<AssetId>,
    pub venue_id: Option<VenueId>,
    pub chain_slot: Option<WireU64>,
    pub territory_snapshot_id: Option<TerritorySnapshotId>,
    pub community_id: Option<CommunityId>,
    pub lifecycle_id: Option<StableString>,
    pub regime_epoch: Option<StableString>,
    pub topology_epoch: Option<StableString>,
    pub scene_id: Option<SceneId>,
    pub presentation_context: Option<PresentationContext>,
    pub decision_id: Option<StableString>,
    pub choice_set_id: Option<StableString>,
    pub mark_set_version: StableString,
    pub coverage: CoverageContext,
}

/// Long-form, through-cut event attribute.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KernelMarkRow {
    pub kernel_event_id: KernelEventId,
    pub family: KernelMarkFamily,
    pub name: StableString,
    pub direction: Option<StableString>,
    pub value: MarkValue,
    pub epistemic_class: EpistemicClass,
    pub observed_through: UtcTimestamp,
    pub available_at: UtcTimestamp,
    pub available_commit: CommitSeq,
    pub source_input_ids: Vec<AttentionInputId>,
    pub coverage: CoverageContext,
    pub through_cut: UtcTimestamp,
    pub missingness_reason: Option<StableString>,
}

/// Required callout mark families.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum KernelMarkFamily {
    CallerHistory,
    Context,
    Territory,
    Lifecycle,
    AudienceOverlap,
    Presentation,
}

/// Tagged, lossless mark value. Unknown is explicit rather than zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "encoding", content = "value", rename_all = "snake_case")]
pub enum MarkValue {
    Utf8(StableString),
    JsonNumberLexeme(JsonNumberLexeme),
    Boolean(bool),
    WireU64(WireU64),
    Identifier(StableString),
    Unknown(StableString),
}

/// A separately covered audience-overlap estimate; no single similarity score is canonical.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AudienceOverlapEstimate {
    pub estimate_id: StableString,
    pub left_subject_id: SubjectId,
    pub right_subject_id: SubjectId,
    pub intersection_count: WireU64,
    pub left_denominator: WireU64,
    pub right_denominator: WireU64,
    pub estimator_version: StableString,
    pub observed_through: UtcTimestamp,
    pub available_at: UtcTimestamp,
    pub left_coverage: CoverageContext,
    pub right_coverage: CoverageContext,
}

/// One post-anchor response bin with exact coverage and censoring.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResponseObservationRow {
    pub kernel_event_id: KernelEventId,
    pub subject_mint_id: AssetId,
    pub response_name: StableString,
    pub window_start_seconds: SignedWireI64,
    pub window_end_seconds: SignedWireI64,
    pub value: Option<MarkValue>,
    pub event_time: EventTime,
    pub observed_at: UtcTimestamp,
    pub available_at: UtcTimestamp,
    /// Analysis cut at which this outcome row may be used.
    pub analysis_cutoff: UtcTimestamp,
    pub venue_id: Option<VenueId>,
    pub pool_id: Option<PoolId>,
    pub coverage: CoverageContext,
    pub censoring: ResponseCensoring,
    pub source_input_ids: Vec<AttentionInputId>,
}

/// Response-bin censoring state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ResponseCensoring {
    None,
    RightAdministrative {
        at: UtcTimestamp,
    },
    Interval {
        lower: UtcTimestamp,
        upper: UtcTimestamp,
        reason: StableString,
    },
    SourceLoss {
        lower: UtcTimestamp,
        upper: Option<UtcTimestamp>,
        gap_ids: Vec<CoverageId>,
    },
}

/// One subject membership in one explicitly versioned risk set.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RiskSetCohortRow {
    pub cohort_row_id: CohortRowId,
    pub cohort_definition_id: StableString,
    pub candidate_census_id: StableString,
    pub risk_set_id: StableString,
    pub risk_set_denominator: WireU64,
    pub anchor_kernel_event_id: KernelEventId,
    pub anchor_cut: UtcTimestamp,
    pub fit_cutoff: UtcTimestamp,
    pub subject: CohortSubject,
    pub risk_origin_at: UtcTimestamp,
    pub risk_entry_at: UtcTimestamp,
    pub risk_exit_at: Option<UtcTimestamp>,
    pub horizon_seconds: WireU64,
    pub left_truncated: bool,
    pub event_of_interest: Option<CohortEvent>,
    pub competing_events: Vec<CohortEvent>,
    pub censoring: CohortCensoring,
    pub choice_set_id: Option<StableString>,
    pub witnessed_choice_set_complete: Option<bool>,
    pub exposure_summaries: Vec<ExposureSummary>,
    pub coverage: CoverageContext,
}

/// Mint or territory under risk.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum CohortSubject {
    Mint(AssetId),
    Territory(TerritorySnapshotId),
}

/// Event of interest or competing event with its own known-at boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CohortEvent {
    pub event_kind: StableString,
    pub event_time: EventTime,
    pub known_at: UtcTimestamp,
    pub source_input_ids: Vec<AttentionInputId>,
}

/// Censoring is separate from migration, fragmentation, or other competing events.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum CohortCensoring {
    None,
    RightAdministrative {
        at: UtcTimestamp,
        reason: StableString,
    },
    Interval {
        lower: UtcTimestamp,
        upper: UtcTimestamp,
        reason: StableString,
    },
    SourceLoss {
        lower: UtcTimestamp,
        upper: Option<UtcTimestamp>,
        gap_ids: Vec<CoverageId>,
    },
}

/// Exposure aggregation with its own through-cut and evidence coverage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExposureSummary {
    pub family: KernelMarkFamily,
    pub name: StableString,
    pub value: MarkValue,
    pub observed_through: UtcTimestamp,
    pub available_at: UtcTimestamp,
    pub coverage: CoverageContext,
}

/// Keeps the compile-time constant used by fixtures visible in generated documentation.
#[must_use]
pub const fn contract_version() -> &'static str {
    ATTENTION_CONTRACT
}
