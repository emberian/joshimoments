use crate::{OperationalError, Result};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// Literal authority carried by every operational snapshot and backfill artifact.
pub const AUTHORITY_CEILING: &str = "read_only_no_execution";

pub(crate) const MAX_SOURCES: usize = 32;
pub(crate) const MAX_CURSOR_SCOPES: usize = 256;
pub(crate) const MAX_GAPS: usize = 512;
pub(crate) const MAX_RESOURCES: usize = 32;
pub(crate) const MAX_BUDGETS: usize = 64;
pub(crate) const MAX_ARTIFACTS: usize = 32;
pub(crate) const MAX_CAUSES: usize = 16;

/// Finite source-family dimension. Specific source IDs, routes, subjects, and URLs are details,
/// never metric labels.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceFamily {
    HeliusWebsocket,
    HeliusHttp,
    SolanaRpc,
    PumpPortalWebsocket,
    PumpPublicHttp,
    PumpAuthenticatedCompanion,
    PumpAuthenticatedDirect,
    WalletPublicChain,
    BrowserCompanion,
}

/// Finite system component dimension.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Component {
    Supervisor,
    Source,
    EvidenceQueue,
    Spool,
    Replica,
    Catalog,
    Normalizer,
    Projection,
    Glass,
    Export,
    Analysis,
    Host,
}

/// Coarse readiness visible before any detailed query.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HealthReadiness {
    Ready,
    Degraded,
    NotReady,
    Stopped,
}

/// Finite status-class dimension for metrics and summaries.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StatusClass {
    Ready,
    Degraded,
    Unavailable,
    Gap,
    Quarantined,
    Stale,
    Recovering,
    Refused,
    Stopped,
}

/// Collector supervisor lifecycle.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisorPhase {
    Starting,
    Running,
    Draining,
    Stopping,
    Stopped,
    Failed,
}

/// Current source connection/generation state.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceGenerationState {
    Reserved,
    Connecting,
    Live,
    RetryWaiting,
    Disconnected,
    Stopped,
}

/// Deterministic degradation order from full fidelity to clean stop.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DegradationStage {
    FullFidelity,
    OptionalMediaDisabled,
    SocialRefreshSlowed,
    HotScopesReduced,
    CensusOnly,
    StopBeforeControlReserve,
}

/// Finite cause vocabulary. Detailed errors remain durable records, not metric dimensions.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DegradationCause {
    SourceDisconnected,
    RateLimited,
    AuthenticationRejected,
    SchemaDrift,
    MalformedEvidence,
    QueuePressure,
    SpoolPressure,
    DiskFloor,
    CatalogUnavailable,
    ReplicaUnavailable,
    ReplicaCorrupt,
    ProjectionStale,
    GlassCaptureUnavailable,
    ExportStale,
    ResourceCeiling,
    ClockUncertain,
}

/// Declared recovery lifecycle. A recovered source is not proof that an evidence gap closed.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryState {
    Stable,
    Pending,
    Draining,
    Verifying,
    Recovered,
    /// Public projections may report this state, but it never qualifies semantic recovery.
    UnverifiedSemantic,
    BlockedUnrecoverable,
}

/// Typed operational cursor families; subject identity stays behind the authenticated query.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CursorKind {
    Sequence,
    Page,
    Slot,
    Epoch,
    ConnectionGeneration,
    OpaqueSourceCursor,
}

/// Finite gap taxonomy.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapKind {
    AbandonedAttempt,
    SourceDowntime,
    QueueSaturation,
    LocalDurabilityFailure,
    ReplicaTransfer,
    CatalogAdmission,
    Pagination,
    LiveOnlyMiss,
    SchemaOrDecode,
    ClockUncertain,
}

/// Backfill/reconstruction capability of a gap.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BackfillDisposition {
    SameSourceBoundedHistory,
    CrossSourceReconstructionOnly,
    LiveOnlyUnrecoverable,
    Unsupported,
}

/// Finite quarantine taxonomy.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QuarantineClass {
    CorruptSegment,
    ReplicaCorrupt,
    MalformedPayload,
    SchemaDrift,
    UnknownProgramOrVariant,
    ReceiptMismatch,
}

/// Published product whose freshness is operationally visible.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactKind {
    Projection,
    GlassPresentation,
    GlassCommandCapture,
    ExportSnapshot,
    AnalysisArtifact,
}

/// Bounded host/runtime resource dimension.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceKind {
    CpuMillicores,
    RssBytes,
    FileDescriptors,
    DiskFreeBytes,
    DiskFreeInodes,
    ClockOffsetAbsMilliseconds,
}

/// Bounded provider/policy budget dimension.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BudgetKind {
    ProviderRequests,
    ProviderPages,
    ProviderBytes,
    ProviderCredits,
    NativeUnits,
    CurrencyMinorUnits,
    DailySpoolBytes,
    ConcurrentHotScopes,
}

/// Exact unit for a quota or policy budget.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BudgetUnit {
    Count,
    Bytes,
    Credits,
    NativeAtoms,
    CurrencyMinorUnits,
}

/// Finite metric name vocabulary.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MetricName {
    ReadinessCode,
    SupervisorPhaseCode,
    RestartCount,
    ShutdownDeadlineExceededCount,
    CurrentGeneration,
    LastReservationAgeMilliseconds,
    LastDurableFrameAgeMilliseconds,
    PendingReservationCount,
    RetryCount,
    NextRetryDelayMilliseconds,
    QueueRecordCount,
    QueueMaximumRecords,
    QueueByteCount,
    QueueMaximumBytes,
    QueueControlReserveRecords,
    QueueControlReserveBytes,
    SaturationCount,
    SpoolReadySegmentCount,
    SpoolReadyBytes,
    SpoolOldestAgeMilliseconds,
    SpoolUsedBytes,
    SpoolMaximumBytes,
    SpoolControlReserveBytes,
    SpoolDegradedCode,
    CatalogUnackedSegmentCount,
    CatalogUnackedBatchCount,
    CatalogUnackedBytes,
    CatalogOldestUnackedAgeMilliseconds,
    CatalogLastExactAckAgeMilliseconds,
    ReplicaGeneration,
    ReplicaUnackedBytes,
    ReplicaOldestUnackedAgeMilliseconds,
    ReplicaAckLagMilliseconds,
    OpenGapCount,
    QuarantineCount,
    DriftCount,
    ArtifactAgeMilliseconds,
    ResourceObserved,
    ResourceLimit,
    BudgetRemaining,
    RecoveryArrivalRecords,
    RecoveryDrainRecords,
    RecoveryBacklogRecords,
    RecoveryArrivalBytes,
    RecoveryDrainBytes,
    RecoveryBacklogBytes,
}

/// Finite metric unit vocabulary.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MetricUnit {
    Code,
    Count,
    Bytes,
    Milliseconds,
    Millicores,
    Inodes,
    Credits,
    NativeAtoms,
    CurrencyMinorUnits,
}

/// A boundary retained without inventing a shared total clock.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "clock",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum OperationalBoundaryV1 {
    Wall { value: UtcTimestamp },
    Commit { value: CommitSeq },
    SourceCursor { value: StableString },
    Unknown { reason: StableString },
}

/// Supervisor health summary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisorStatusV1 {
    pub phase: SupervisorPhase,
    pub restart_count: WireU64,
    pub shutdown_deadline_exceeded_count: WireU64,
    pub last_reservation_age_ms: Option<WireU64>,
    pub pending_reservations: WireU64,
}

/// One finite source-family generation summary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceGenerationStatusV1 {
    pub source_family: SourceFamily,
    pub state: SourceGenerationState,
    /// Durable generation is a metric value; this opaque ID is detailed health only.
    pub generation_id: StableString,
    pub generation_sequence: WireU64,
    pub last_reservation_age_ms: Option<WireU64>,
    pub last_durable_frame_age_ms: Option<WireU64>,
    pub pending_reservations: WireU64,
    pub retry_count: WireU64,
    pub next_retry_delay_ms: Option<WireU64>,
    pub status: StatusClass,
}

impl SourceGenerationStatusV1 {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.generation_id.as_str().is_empty() {
            return Err(OperationalError::Invalid("source generation ID"));
        }
        Ok(())
    }
}

/// Record/byte capacity with a protected control reserve.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapacityStatusV1 {
    pub used: WireU64,
    pub maximum: WireU64,
    pub control_reserve: WireU64,
}

impl CapacityStatusV1 {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.maximum.get() == 0
            || self.control_reserve.get() > self.maximum.get()
            || self.used.get() > self.maximum.get()
        {
            return Err(OperationalError::Invalid(
                "capacity requires 0 < maximum, reserve <= maximum, and used <= maximum",
            ));
        }
        Ok(())
    }
}

/// Saturation closure needed before a stopped source generation may restart.
#[allow(clippy::struct_excessive_bools)] // Each bit is an independently witnessed closure fact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SaturationStatusV1 {
    pub incident_count: WireU64,
    pub currently_saturated: bool,
    pub rejected_occurrence_preserved: bool,
    pub durable_scoped_gap_recorded: bool,
    pub restart_permitted: bool,
}

/// Collector evidence queue state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QueueStatusV1 {
    pub records: CapacityStatusV1,
    pub bytes: CapacityStatusV1,
    pub saturation: SaturationStatusV1,
}

/// Local spool capacity and backlog.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SpoolStatusV1 {
    pub ready_segment_count: WireU64,
    pub ready_bytes: WireU64,
    pub oldest_ready_age_ms: Option<WireU64>,
    pub used_bytes: WireU64,
    pub maximum_bytes: WireU64,
    pub control_reserve_bytes: WireU64,
    pub degraded: bool,
}

/// Optional ciphertext replica state. Generation IDs remain bounded health detail, never labels.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplicaStatusV1 {
    pub status: StatusClass,
    pub generation_id: StableString,
    pub generation_sequence: WireU64,
    pub unacked_bytes: WireU64,
    pub oldest_unacked_age_ms: Option<WireU64>,
    pub ack_lag_ms: Option<WireU64>,
}

/// Opaque validated projection of the exact public store receipt closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CatalogReceiptSummaryV1 {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub commit_seq: CommitSeq,
    pub from_commit_seq: CommitSeq,
    pub through_commit_seq: CommitSeq,
    pub batch_id: StableString,
    pub batch_digest: StableString,
    pub store_admission_digest: StableString,
    pub status: StableString,
    pub gap_outcome_count: WireU64,
    pub gap_outcome_ids: Vec<StableString>,
}

impl CatalogReceiptSummaryV1 {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.from_commit_seq != self.through_commit_seq
            || self.commit_seq != self.through_commit_seq
        {
            return Err(OperationalError::Invalid(
                "catalog receipt commit closure must be one exact commit",
            ));
        }
        if self.gap_outcome_ids.len() > MAX_GAPS
            || self.gap_outcome_count.get()
                != u64::try_from(self.gap_outcome_ids.len()).unwrap_or(u64::MAX)
            || self
                .gap_outcome_ids
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
        {
            return Err(OperationalError::Invalid(
                "catalog receipt gap outcomes must be bounded, counted, sorted, and unique",
            ));
        }
        Ok(())
    }
}

/// Catalog backlog and last exact admission receipt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CatalogStatusV1 {
    pub status: StatusClass,
    pub unacked_segment_count: WireU64,
    pub unacked_batch_count: WireU64,
    pub unacked_bytes: WireU64,
    pub oldest_unacked_age_ms: Option<WireU64>,
    pub last_exact_ack_age_ms: Option<WireU64>,
    pub last_closed_receipt: Option<CatalogReceiptSummaryV1>,
}

/// Detailed cursor scope. `scope_id` is a durable opaque identity and never a metric label.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CursorScopeStatusV1 {
    pub scope_id: StableString,
    pub source_family: SourceFamily,
    pub cursor_kind: CursorKind,
    pub cursor_value_present: bool,
    pub advanced_through: Option<CommitSeq>,
    pub open_gap_count: WireU64,
    pub recovery_state: RecoveryState,
}

impl CursorScopeStatusV1 {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.cursor_value_present != self.advanced_through.is_some() {
            return Err(OperationalError::Invalid(
                "cursor presence and committed advancement must agree",
            ));
        }
        Ok(())
    }
}

/// Detailed immutable gap summary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GapStatusV1 {
    pub gap_id: StableString,
    pub scope_id: StableString,
    pub source_family: SourceFamily,
    pub kind: GapKind,
    pub disposition: BackfillDisposition,
    pub lower: OperationalBoundaryV1,
    pub upper: Option<OperationalBoundaryV1>,
    pub detected_at: UtcTimestamp,
    pub recovery_state: RecoveryState,
}

impl GapStatusV1 {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.scope_id.as_str().is_empty() || self.gap_id.as_str().is_empty() {
            return Err(OperationalError::Invalid("gap identity"));
        }
        Ok(())
    }
}

/// Coverage, cursor, and gap status. Items are canonical by opaque identity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageStatusV1 {
    pub cursor_scopes: Vec<CursorScopeStatusV1>,
    pub open_gaps: Vec<GapStatusV1>,
}

/// Finite quarantine counts; exact quarantined IDs are queried separately.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuarantineStatusV1 {
    pub class: QuarantineClass,
    pub count: WireU64,
}

/// Freshness of an immutable projection, Glass, export, or analysis artifact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactStatusV1 {
    pub kind: ArtifactKind,
    pub status: StatusClass,
    pub occurrence_id: Option<StableString>,
    pub content_digest: Option<StableString>,
    pub age_ms: Option<WireU64>,
}

impl ArtifactStatusV1 {
    pub(crate) fn validate(&self) -> Result<()> {
        if self.occurrence_id.is_some() != self.content_digest.is_some() {
            return Err(OperationalError::Invalid(
                "artifact occurrence and content digest must be present together",
            ));
        }
        Ok(())
    }
}

/// Host/runtime resource observation and its configured limit/floor.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceStatusV1 {
    pub kind: ResourceKind,
    pub observed: WireU64,
    pub limit_or_floor: WireU64,
    pub status: StatusClass,
}

pub(crate) fn validate_resource_observation(
    kind: ResourceKind,
    observed: WireU64,
    limit_or_floor: WireU64,
    status: StatusClass,
) -> Result<()> {
    let threshold_breached = match kind {
        ResourceKind::DiskFreeBytes | ResourceKind::DiskFreeInodes => {
            observed.get() <= limit_or_floor.get()
        }
        _ => observed.get() >= limit_or_floor.get(),
    };
    if threshold_breached && status == StatusClass::Ready {
        return Err(OperationalError::Invalid(
            "resource threshold breach cannot be marked ready",
        ));
    }
    Ok(())
}

/// Exact quota/policy budget. Zero authorization is valid and means disabled.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuotaBudgetV1 {
    pub kind: BudgetKind,
    pub unit: BudgetUnit,
    pub authorized: WireU64,
    pub used: WireU64,
    pub remaining: WireU64,
    pub status: StatusClass,
}

/// Declared degradation and recovery state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DegradationStatusV1 {
    pub policy_id: StableString,
    pub stage: DegradationStage,
    pub causes: Vec<DegradationCause>,
    pub since: Option<UtcTimestamp>,
    pub recovery: RecoveryState,
}

/// Complete bounded operational health snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperationalHealthV1 {
    pub contract: String,
    pub snapshot_id: StableString,
    pub observed_at: UtcTimestamp,
    pub authority: String,
    pub readiness: HealthReadiness,
    pub degradation: DegradationStatusV1,
    pub supervisor: SupervisorStatusV1,
    pub sources: Vec<SourceGenerationStatusV1>,
    pub evidence_queue: QueueStatusV1,
    pub spool: SpoolStatusV1,
    pub replica: Option<ReplicaStatusV1>,
    pub catalog: CatalogStatusV1,
    pub coverage: CoverageStatusV1,
    pub normalizer_drift_count: WireU64,
    pub quarantine: Vec<QuarantineStatusV1>,
    pub artifacts: Vec<ArtifactStatusV1>,
    pub resources: Vec<ResourceStatusV1>,
    pub budgets: Vec<QuotaBudgetV1>,
}

impl OperationalHealthV1 {
    /// Validates cross-field semantics and finite collection bounds.
    ///
    /// # Errors
    ///
    /// Refuses wrong authority/contract, duplicate finite dimensions, impossible capacity or
    /// receipt states, and saturation states that could restart without durable gap closure.
    #[allow(clippy::too_many_lines)] // Central audit keeps all cross-field health invariants together.
    pub fn validate(&self, expected_contract: &'static str) -> Result<()> {
        if self.contract != expected_contract {
            return Err(OperationalError::Contract {
                expected: expected_contract,
                received: self.contract.clone(),
            });
        }
        if self.authority != AUTHORITY_CEILING {
            return Err(OperationalError::Invalid(
                "authority must be read_only_no_execution",
            ));
        }
        check_bound(self.sources.len(), MAX_SOURCES, "sources")?;
        check_bound(
            self.coverage.cursor_scopes.len(),
            MAX_CURSOR_SCOPES,
            "cursorScopes",
        )?;
        check_bound(self.coverage.open_gaps.len(), MAX_GAPS, "openGaps")?;
        check_bound(self.resources.len(), MAX_RESOURCES, "resources")?;
        check_bound(self.budgets.len(), MAX_BUDGETS, "budgets")?;
        check_bound(self.artifacts.len(), MAX_ARTIFACTS, "artifacts")?;
        check_bound(
            self.degradation.causes.len(),
            MAX_CAUSES,
            "degradationCauses",
        )?;
        require_strictly_sorted_unique(
            self.sources.iter().map(|value| value.source_family),
            "sources must be sorted and unique by source family",
        )?;
        require_strictly_sorted_unique(
            self.coverage
                .cursor_scopes
                .iter()
                .map(|value| value.scope_id.clone()),
            "cursor scopes must be sorted and unique by scope ID",
        )?;
        require_strictly_sorted_unique(
            self.coverage
                .open_gaps
                .iter()
                .map(|value| value.gap_id.clone()),
            "open gaps must be sorted and unique by gap ID",
        )?;
        require_strictly_sorted_unique(
            self.quarantine.iter().map(|value| value.class),
            "quarantine rows must be sorted and unique by class",
        )?;
        require_strictly_sorted_unique(
            self.artifacts.iter().map(|value| value.kind),
            "artifact rows must be sorted and unique by kind",
        )?;
        require_strictly_sorted_unique(
            self.resources.iter().map(|value| value.kind),
            "resource rows must be sorted and unique by kind",
        )?;
        require_strictly_sorted_unique(
            self.budgets.iter().map(|value| value.kind),
            "budget rows must be sorted and unique by kind",
        )?;
        require_strictly_sorted_unique(
            self.degradation.causes.iter().copied(),
            "degradation causes must be sorted and unique",
        )?;
        self.evidence_queue.records.validate()?;
        self.evidence_queue.bytes.validate()?;
        validate_saturation(&self.evidence_queue.saturation)?;
        validate_spool(&self.spool)?;
        validate_catalog(&self.catalog)?;
        for budget in &self.budgets {
            if budget.used.get() > budget.authorized.get()
                || budget.remaining.get()
                    != budget.authorized.get().saturating_sub(budget.used.get())
            {
                return Err(OperationalError::Invalid(
                    "budget remaining must exactly equal authorized minus used",
                ));
            }
        }
        for artifact in &self.artifacts {
            artifact.validate()?;
        }
        for scope in &self.coverage.cursor_scopes {
            scope.validate()?;
        }
        Ok(())
    }
}

fn validate_saturation(value: &SaturationStatusV1) -> Result<()> {
    if value.currently_saturated && value.restart_permitted {
        return Err(OperationalError::Invalid(
            "a currently saturated generation cannot restart",
        ));
    }
    if value.incident_count.get() > 0
        && value.restart_permitted
        && (!value.rejected_occurrence_preserved || !value.durable_scoped_gap_recorded)
    {
        return Err(OperationalError::Invalid(
            "restart after saturation requires preserved rejected occurrence and durable scoped gap",
        ));
    }
    Ok(())
}

fn validate_spool(value: &SpoolStatusV1) -> Result<()> {
    if value.maximum_bytes.get() == 0
        || value.control_reserve_bytes.get() > value.maximum_bytes.get()
        || value.used_bytes.get() > value.maximum_bytes.get()
        || value.ready_bytes.get() > value.used_bytes.get()
        || (value.ready_segment_count.get() == 0) != value.oldest_ready_age_ms.is_none()
    {
        return Err(OperationalError::Invalid(
            "spool counts, ages, and byte capacities are inconsistent",
        ));
    }
    let computed_degraded = value.used_bytes.get()
        >= value
            .maximum_bytes
            .get()
            .saturating_sub(value.control_reserve_bytes.get());
    if value.degraded != computed_degraded {
        return Err(OperationalError::Invalid(
            "spool degraded flag must match protected control-reserve boundary",
        ));
    }
    Ok(())
}

fn validate_catalog(value: &CatalogStatusV1) -> Result<()> {
    let has_backlog = value.unacked_batch_count.get() > 0 || value.unacked_segment_count.get() > 0;
    if has_backlog == value.oldest_unacked_age_ms.is_none() {
        return Err(OperationalError::Invalid(
            "catalog oldest unacked age must exist exactly when backlog exists",
        ));
    }
    if let Some(receipt) = &value.last_closed_receipt {
        receipt.validate()?;
    }
    Ok(())
}

pub(crate) fn check_bound(actual: usize, maximum: usize, field: &'static str) -> Result<()> {
    if actual > maximum {
        return Err(OperationalError::BoundExceeded {
            field,
            maximum: u64::try_from(maximum).unwrap_or(u64::MAX),
        });
    }
    Ok(())
}

fn require_strictly_sorted_unique<T: Ord>(
    values: impl IntoIterator<Item = T>,
    error: &'static str,
) -> Result<()> {
    let mut prior = None;
    for value in values {
        if prior.as_ref().is_some_and(|item| item >= &value) {
            return Err(OperationalError::Invalid(error));
        }
        prior = Some(value);
    }
    Ok(())
}

pub(crate) fn unique_count<T: Ord>(values: impl IntoIterator<Item = T>) -> usize {
    values.into_iter().collect::<BTreeSet<_>>().len()
}
