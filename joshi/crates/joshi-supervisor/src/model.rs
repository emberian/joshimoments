use crate::{AUTHORITY_CEILING, SUPERVISOR_CONTRACT_VERSION};
use crate::{AttemptBudgetClaim, AttemptBudgetUsage, RunBudgetLimits};
use joshi_admission::wave5::Wave5RunReferenceV1;
use joshi_domain::{OpenVariant, UtcTimestamp};
use joshi_evidence::{Boundary, CoverageScope};
use joshi_spool::{ProtectionClass, ProtectionDomainId, SegmentClosure, SpoolEntry, SpoolStatus};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::PathBuf,
    time::Duration,
};

macro_rules! stable_key {
    ($name:ident, $label:literal) => {
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Construct a bounded stable identifier.
            ///
            /// # Errors
            ///
            /// Refuses empty, padded, control-bearing, path-shaped, or oversized values.
            pub fn new(value: impl Into<String>) -> crate::Result<Self> {
                let value = value.into();
                if value.is_empty()
                    || value.len() > 255
                    || value.trim() != value
                    || value.chars().any(char::is_control)
                    || value.contains('/')
                    || value.contains('\\')
                {
                    return Err(crate::SupervisorError::InvalidValue(
                        concat!($label, " is not a stable identifier").into(),
                    ));
                }
                Ok(Self(value))
            }

            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str(&self.0)
            }
        }
    };
}

stable_key!(SourceKey, "source key");
stable_key!(OperationKey, "operation key");
stable_key!(ReservationId, "reservation ID");

/// Exact validated provider-plan identity bound independently of the run reference. Keeping this
/// outside the registered configuration avoids the registration→plan→configuration digest cycle.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderPlanReferenceV1 {
    pub plan_id: String,
    pub plan_template_digest: String,
    pub plan_digest: String,
}

impl ProviderPlanReferenceV1 {
    pub(crate) fn validate(&self) -> crate::Result<()> {
        OperationKey::new(self.plan_id.clone())?;
        validate_plan_digest(&self.plan_template_digest)?;
        validate_plan_digest(&self.plan_digest)
    }
}

fn validate_plan_digest(value: &str) -> crate::Result<()> {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return Err(crate::SupervisorError::InvalidValue(
            "provider plan digest is malformed".into(),
        ));
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(crate::SupervisorError::InvalidValue(
            "provider plan digest is malformed".into(),
        ));
    }
    Ok(())
}

/// Durable source connection/poll generation. It is operational identity, not source truth.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct GenerationId(u64);

impl GenerationId {
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

/// Network operation whose identity must exist durably before I/O.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttemptKind {
    HttpRequest,
    WebSocketConnection,
    Poll,
    ControlWrite,
}

impl AttemptKind {
    #[must_use]
    pub const fn starts_generation(self) -> bool {
        matches!(self, Self::WebSocketConnection | Self::Poll)
    }
}

/// Protection information safe to persist. It contains a key ID, never key bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "class", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProtectionProfile {
    PublicIntegrity {
        domain: ProtectionDomainId,
    },
    AuthenticatedPrivate {
        domain: ProtectionDomainId,
        key_id: String,
    },
}

impl ProtectionProfile {
    #[must_use]
    pub const fn class(&self) -> ProtectionClass {
        match self {
            Self::PublicIntegrity { .. } => ProtectionClass::PublicIntegrity,
            Self::AuthenticatedPrivate { .. } => ProtectionClass::AuthenticatedPrivate,
        }
    }

    #[must_use]
    pub fn domain(&self) -> &ProtectionDomainId {
        match self {
            Self::PublicIntegrity { domain } | Self::AuthenticatedPrivate { domain, .. } => domain,
        }
    }

    #[must_use]
    pub fn key_id(&self) -> Option<&str> {
        match self {
            Self::PublicIntegrity { .. } => None,
            Self::AuthenticatedPrivate { key_id, .. } => Some(key_id),
        }
    }

    pub(crate) fn validate(&self) -> crate::Result<()> {
        if let Some(key_id) = self.key_id()
            && (key_id.is_empty()
                || key_id.len() > 255
                || key_id.trim() != key_id
                || key_id.chars().any(char::is_control))
        {
            return Err(crate::SupervisorError::InvalidValue(
                "private key ID is malformed".into(),
            ));
        }
        Ok(())
    }
}

/// Caller-supplied semantic scope for one pre-I/O reservation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReservationRequest {
    pub source_key: SourceKey,
    pub operation_key: OperationKey,
    pub kind: AttemptKind,
    pub scope: CoverageScope,
    pub lower: Boundary,
    pub protection: ProtectionProfile,
    /// Wave 5 live-runtime reservations must carry both fields. `None` remains only for the
    /// pre-Wave-5 offline supervisor harness and compatibility replay.
    pub run: Option<Wave5RunReferenceV1>,
    pub execution_claim: Option<AttemptBudgetClaim>,
    pub provider_plan: Option<ProviderPlanReferenceV1>,
}

/// Fsync-complete occurrence reservation. Receipt of this value is the permission boundary for
/// one provider attempt; it says nothing about whether I/O began or a response arrived.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AttemptReservation {
    pub contract: String,
    pub reservation_id: ReservationId,
    pub installation_id: String,
    pub source_key: SourceKey,
    pub operation_key: OperationKey,
    pub generation: GenerationId,
    pub attempt_ordinal: u64,
    pub kind: AttemptKind,
    pub scope: CoverageScope,
    pub lower: Boundary,
    pub protection: ProtectionProfile,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub run: Option<Wave5RunReferenceV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution_claim: Option<AttemptBudgetClaim>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provider_plan: Option<ProviderPlanReferenceV1>,
    pub reserved_at: UtcTimestamp,
    pub authority: String,
}

/// Queue budget. Control reserve is unavailable to ordinary evidence records.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct QueueLimits {
    pub maximum_records: usize,
    pub maximum_bytes: u64,
    pub control_reserve_records: usize,
    pub control_reserve_bytes: u64,
}

impl Default for QueueLimits {
    fn default() -> Self {
        Self {
            maximum_records: 4_224,
            maximum_bytes: 65 * 1024 * 1024,
            control_reserve_records: 128,
            control_reserve_bytes: 1024 * 1024,
        }
    }
}

impl QueueLimits {
    pub(crate) fn validate(self) -> crate::Result<()> {
        if self.maximum_records == 0
            || self.maximum_bytes == 0
            || self.control_reserve_records >= self.maximum_records
            || self.control_reserve_bytes >= self.maximum_bytes
        {
            return Err(crate::SupervisorError::InvalidConfig(
                "queue bounds must leave positive evidence capacity and control reserve".into(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn evidence_records(self) -> usize {
        self.maximum_records - self.control_reserve_records
    }

    #[must_use]
    pub const fn evidence_bytes(self) -> u64 {
        self.maximum_bytes - self.control_reserve_bytes
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueueClass {
    Evidence,
    Control,
}

/// An owned provider/control record. Ownership remains here until local spool durability is
/// journaled; a saturated return gives the exact item back to the caller.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PendingSegment {
    pub reservation: AttemptReservation,
    pub entry: SpoolEntry,
    pub class: QueueClass,
    pub exact_entry_bytes: u64,
}

impl PendingSegment {
    /// Build a bounded queue item and measure the exact entry encoding.
    ///
    /// # Errors
    ///
    /// Returns an error when the entry cannot be serialized or its length cannot fit in `u64`.
    pub fn new(
        reservation: AttemptReservation,
        entry: SpoolEntry,
        class: QueueClass,
    ) -> crate::Result<Self> {
        let exact_entry_bytes = u64::try_from(serde_json::to_vec(&entry)?.len())
            .map_err(|_| crate::SupervisorError::InvalidValue("entry is too large".into()))?;
        if matches!(entry, SpoolEntry::EvidenceBatch(_)) != (class == QueueClass::Evidence) {
            return Err(crate::SupervisorError::InvalidValue(
                "evidence batches use the evidence queue; control records use the reserve".into(),
            ));
        }
        Ok(Self {
            reservation,
            entry,
            class,
            exact_entry_bytes,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableOutcome {
    Accepted,
    Idempotent,
}

impl From<joshi_spool::AppendOutcome> for DurableOutcome {
    fn from(value: joshi_spool::AppendOutcome) -> Self {
        match value {
            joshi_spool::AppendOutcome::Appended => Self::Accepted,
            joshi_spool::AppendOutcome::Idempotent => Self::Idempotent,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetryTrigger {
    Transport,
    Inactivity,
    RateLimited,
    ProviderUnavailable,
    SubscriptionRejected,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RetryPolicy {
    pub maximum_attempts_per_generation: u64,
    pub base_delay: Duration,
    pub maximum_delay: Duration,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            maximum_attempts_per_generation: 3,
            base_delay: Duration::from_secs(1),
            maximum_delay: Duration::from_secs(30),
        }
    }
}

impl RetryPolicy {
    pub(crate) fn validate(self) -> crate::Result<()> {
        if self.maximum_attempts_per_generation == 0
            || self.base_delay.is_zero()
            || self.maximum_delay < self.base_delay
        {
            return Err(crate::SupervisorError::InvalidConfig(
                "retry bounds are invalid".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "decision", rename_all = "snake_case", deny_unknown_fields)]
pub enum RetryDecision {
    Scheduled {
        after_ms: u64,
        next_attempt_ordinal: u64,
    },
    Exhausted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CollectorLifecycle {
    Starting,
    Running,
    Degraded,
    Stopping,
    Stopped,
}

/// Durable settlement outcome for a runtime attempt budget.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeSettlementDisposition {
    Observed,
    RefundedBeforeIo,
    RecoveredBeforeIo,
    RecoveredAfterIoWorstCase,
    TerminalViolation,
}

/// Append-only supervisor journal event. The embedded segment closure is evidence about local
/// progress, not a substitute local-spool ACK DTO.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", content = "value", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)] // Stable append-only wire events remain direct, not boxed.
pub enum JournalEvent {
    SupervisorStarted {
        recovered_records: u64,
    },
    RuntimeRunAttached {
        run: Wave5RunReferenceV1,
        limits: RunBudgetLimits,
    },
    AttemptReserved(AttemptReservation),
    AttemptCancelledBeforeIo {
        reservation_id: ReservationId,
    },
    RuntimeIoStarted {
        reservation_id: ReservationId,
    },
    RuntimeBudgetSettled {
        reservation_id: ReservationId,
        usage: AttemptBudgetUsage,
        disposition: RuntimeSettlementDisposition,
        violation: Option<crate::BudgetDimension>,
    },
    LocalDurabilityRecorded {
        reservation_id: ReservationId,
        segment: SegmentClosure,
        outcome: DurableOutcome,
    },
    AttemptAbandoned {
        reservation_id: ReservationId,
        gap_segment: SegmentClosure,
        reason: OpenVariant,
    },
    RetryDecided {
        reservation_id: ReservationId,
        trigger: RetryTrigger,
        decision: RetryDecision,
    },
    GenerationStopped {
        source_key: SourceKey,
        operation_key: OperationKey,
        generation: GenerationId,
        reason: OpenVariant,
        gap_segment: Option<SegmentClosure>,
    },
    ShutdownStarted {
        deadline_ms: u64,
    },
    ShutdownCompleted {
        drained_segments: u64,
        abandoned_attempts: u64,
        downtime_gaps: u64,
        deadline_exceeded: bool,
    },
    /// One consumed C1 activation claim durably bound to this journal installation, carrying the
    /// physically proven maxima that later bound the single page. This is the only event that may
    /// precede a C1 reservation; it is not itself permission to open a socket.
    C1ActivationBound {
        activation_id: String,
        installation_id: String,
        run_registration_id: String,
        run_registration_digest: String,
        activation_digest: String,
        exact_plan_digest: String,
        plan_id: String,
        plan_template_digest: String,
        final_plan_digest: String,
        activation_commit_sequence: u64,
        claim_commit_sequence: u64,
        claim_commit_digest: String,
        /// Admitted maximum response-entity bytes for the single page.
        maximum_response_bytes: u64,
        /// Proven maximum physical local-segment bytes implied by that response ceiling.
        maximum_segment_bytes: u64,
    },
    /// One C1 attempt reservation. The deliberately separate family leaves C0 replay unchanged.
    C1AttemptReserved(AttemptReservation),
    /// The exact request closed before any socket may open. Digests only: never a URL, body,
    /// header value, or credential.
    C1RequestPrepared {
        reservation_id: ReservationId,
        endpoint_digest: String,
        request_body_digest: String,
        request_body_byte_length: u64,
        method_key: String,
        maximum_response_bytes: u64,
        deadline_ms: u64,
    },
    /// The irreversible I/O boundary. Every later failure is terminal for this generation.
    C1IoStarted {
        reservation_id: ReservationId,
    },
    /// One exact raw page durably appended to the local spool.
    C1RawDurabilityRecorded {
        reservation_id: ReservationId,
        segment: SegmentClosure,
        outcome: DurableOutcome,
    },
    /// A post-I/O attempt resolved as an explicit durable gap instead of raw evidence.
    C1AttemptAbandoned {
        reservation_id: ReservationId,
        gap_segment: SegmentClosure,
        reason: OpenVariant,
    },
    /// Conservative settlement of the single reserved attempt.
    C1BudgetSettled {
        reservation_id: ReservationId,
        usage: AttemptBudgetUsage,
        disposition: RuntimeSettlementDisposition,
    },
    /// The one-shot C1 generation is stopped; no further request may ever be issued.
    C1Stopped {
        source_key: SourceKey,
        operation_key: OperationKey,
        generation: GenerationId,
        reason: OpenVariant,
        gap_segment: Option<SegmentClosure>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct JournalRecord {
    pub contract: String,
    pub ordinal: u64,
    pub recorded_at: UtcTimestamp,
    pub event: JournalEvent,
    pub authority: String,
}

#[derive(Clone, Debug)]
pub struct SupervisorConfig {
    pub root: PathBuf,
    pub spool: joshi_spool::SpoolConfig,
    pub queue: QueueLimits,
    pub retry: RetryPolicy,
    pub shutdown_deadline: Duration,
    pub maximum_spool_bytes_per_utc_day: u64,
}

impl SupervisorConfig {
    pub(crate) fn validate(&self) -> crate::Result<()> {
        self.queue.validate()?;
        self.retry.validate()?;
        if self.shutdown_deadline.is_zero() {
            return Err(crate::SupervisorError::InvalidConfig(
                "shutdown deadline must be positive".into(),
            ));
        }
        if self.maximum_spool_bytes_per_utc_day == 0
            || self.maximum_spool_bytes_per_utc_day
                > self
                    .spool
                    .max_total_bytes
                    .saturating_sub(self.spool.control_reserve_bytes)
        {
            return Err(crate::SupervisorError::InvalidConfig(
                "daily spool cap must be positive and fit below the total/control reserve".into(),
            ));
        }
        if self.spool.root != self.root.join("spool") {
            return Err(crate::SupervisorError::InvalidConfig(
                "spool root must be <collector-root>/spool".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceRuntimeHealth {
    pub source_key: SourceKey,
    pub operation_key: OperationKey,
    pub generation: GenerationId,
    pub pending_reservations: u64,
    pub retries_decided: u64,
    pub stopped: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SupervisorHealthV1 {
    pub contract: String,
    pub installation_id: String,
    pub lifecycle: CollectorLifecycle,
    pub journal_ordinal: u64,
    pub queue_records: u64,
    pub queue_bytes: u64,
    pub queue_maximum_records: u64,
    pub queue_maximum_bytes: u64,
    pub queue_control_reserve_records: u64,
    pub queue_control_reserve_bytes: u64,
    pub spool: SpoolStatus,
    pub ready_segments: u64,
    pub catalog_ack_files: u64,
    pub remote_ack_files: u64,
    pub abandoned_attempts: u64,
    pub saturation_stops: u64,
    pub quarantine_files: u64,
    pub sources: Vec<SourceRuntimeHealth>,
    pub authority: String,
}

impl SupervisorHealthV1 {
    pub(crate) fn empty(installation_id: String, spool: SpoolStatus) -> Self {
        Self {
            contract: SUPERVISOR_CONTRACT_VERSION.into(),
            installation_id,
            lifecycle: CollectorLifecycle::Starting,
            journal_ordinal: 0,
            queue_records: 0,
            queue_bytes: 0,
            queue_maximum_records: 0,
            queue_maximum_bytes: 0,
            queue_control_reserve_records: 0,
            queue_control_reserve_bytes: 0,
            spool,
            ready_segments: 0,
            catalog_ack_files: 0,
            remote_ack_files: 0,
            abandoned_attempts: 0,
            saturation_stops: 0,
            quarantine_files: 0,
            sources: Vec::new(),
            authority: AUTHORITY_CEILING.into(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ShutdownReport {
    pub drained_segments: u64,
    pub abandoned_attempts: u64,
    pub downtime_gaps: u64,
    pub deadline_exceeded: bool,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct RuntimeState {
    pub lifecycle: Option<CollectorLifecycle>,
    pub pending: BTreeMap<ReservationId, AttemptReservation>,
    /// Which pending reservations belong to the C1 family. Restart reconciliation must resolve a
    /// pending attempt in the family that reserved it; emitting a C0 record for C1 work would make
    /// C1 replay observe a foreign event and C0 replay observe C1 work.
    pub pending_c1: BTreeSet<ReservationId>,
    pub generations: BTreeMap<(SourceKey, OperationKey), GenerationState>,
    pub retries: BTreeMap<(SourceKey, OperationKey, GenerationId), u64>,
    pub abandoned_attempts: u64,
    pub saturation_stops: u64,
}

#[derive(Clone, Debug)]
pub(crate) struct GenerationState {
    pub generation: GenerationId,
    pub next_attempt_ordinal: u64,
    pub scope: CoverageScope,
    pub lower: Boundary,
    pub protection: ProtectionProfile,
    pub stopped: bool,
}

impl RuntimeState {
    /// Record which durable family owns one pending reservation.
    ///
    /// Restart reconciliation resolves a pending attempt in the family that reserved it, so this
    /// membership is state, not decoration: losing it would let a C0 record close C1 work.
    fn track_reservation_family(&mut self, event: &JournalEvent, reservation: &AttemptReservation) {
        if matches!(event, JournalEvent::C1AttemptReserved(_)) {
            self.pending_c1.insert(reservation.reservation_id.clone());
        } else {
            self.pending_c1.remove(&reservation.reservation_id);
        }
    }

    pub(crate) fn apply(&mut self, event: &JournalEvent) {
        match event {
            JournalEvent::SupervisorStarted { .. } => {
                self.lifecycle = Some(CollectorLifecycle::Running);
            }
            JournalEvent::RuntimeRunAttached { .. }
            | JournalEvent::RuntimeIoStarted { .. }
            | JournalEvent::RuntimeBudgetSettled { .. }
            | JournalEvent::C1ActivationBound { .. }
            | JournalEvent::C1RequestPrepared { .. }
            | JournalEvent::C1IoStarted { .. }
            | JournalEvent::C1BudgetSettled { .. } => {}
            JournalEvent::AttemptReserved(reservation)
            | JournalEvent::C1AttemptReserved(reservation) => {
                self.track_reservation_family(event, reservation);
                let key = (
                    reservation.source_key.clone(),
                    reservation.operation_key.clone(),
                );
                let generation = self
                    .generations
                    .entry(key)
                    .or_insert_with(|| GenerationState {
                        generation: reservation.generation,
                        next_attempt_ordinal: 1,
                        scope: reservation.scope.clone(),
                        lower: reservation.lower.clone(),
                        protection: reservation.protection.clone(),
                        stopped: false,
                    });
                generation.generation = reservation.generation;
                generation.next_attempt_ordinal = generation
                    .next_attempt_ordinal
                    .max(reservation.attempt_ordinal.saturating_add(1));
                generation.scope = reservation.scope.clone();
                generation.lower = reservation.lower.clone();
                generation.protection = reservation.protection.clone();
                generation.stopped = false;
                self.pending
                    .insert(reservation.reservation_id.clone(), reservation.clone());
            }
            JournalEvent::AttemptCancelledBeforeIo { reservation_id }
            | JournalEvent::LocalDurabilityRecorded { reservation_id, .. }
            | JournalEvent::C1RawDurabilityRecorded { reservation_id, .. } => {
                self.pending.remove(reservation_id);
                self.pending_c1.remove(reservation_id);
            }
            JournalEvent::AttemptAbandoned { reservation_id, .. }
            | JournalEvent::C1AttemptAbandoned { reservation_id, .. } => {
                self.pending.remove(reservation_id);
                self.pending_c1.remove(reservation_id);
                self.abandoned_attempts = self.abandoned_attempts.saturating_add(1);
            }
            JournalEvent::RetryDecided {
                reservation_id,
                decision,
                ..
            } => {
                if matches!(decision, RetryDecision::Scheduled { .. })
                    && let Some(reservation) = self.pending.get(reservation_id)
                {
                    let key = (
                        reservation.source_key.clone(),
                        reservation.operation_key.clone(),
                        reservation.generation,
                    );
                    *self.retries.entry(key).or_default() += 1;
                }
            }
            JournalEvent::GenerationStopped {
                source_key,
                operation_key,
                generation,
                reason,
                ..
            }
            | JournalEvent::C1Stopped {
                source_key,
                operation_key,
                generation,
                reason,
                ..
            } => {
                if let Some(state) = self
                    .generations
                    .get_mut(&(source_key.clone(), operation_key.clone()))
                    && state.generation == *generation
                {
                    state.stopped = true;
                }
                if reason.discriminator.as_str() == "ingress_saturated" {
                    self.saturation_stops = self.saturation_stops.saturating_add(1);
                }
            }
            JournalEvent::ShutdownStarted { .. } => {
                self.lifecycle = Some(CollectorLifecycle::Stopping);
            }
            JournalEvent::ShutdownCompleted { .. } => {
                self.lifecycle = Some(CollectorLifecycle::Stopped);
            }
        }
    }
}
