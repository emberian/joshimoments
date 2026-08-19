use crate::{
    AUTHORITY_CEILING, AttemptReservation, CollectorLifecycle, DurableOutcome, GenerationId,
    JournalEvent, NoFaults, PendingSegment, ReservationId, ReservationRequest, Result,
    RetryDecision, RetryTrigger, ShutdownReport, SourceRuntimeHealth, SupervisorConfig,
    SupervisorError, SupervisorHealthV1,
    journal::{DurableJournal, FaultInjector},
    model::RuntimeState,
    queue::BoundedQueue,
    transport::{
        LocalTransport, SourceIngressError, SourceOutputAdapter, exact_closure, public_protection,
    },
};
use joshi_admission::operational::{
    AUTHORITY, LOCAL_SPOOL_RECEIPT_CONTRACT, LocalSpoolReceiptV1, OperationalStatus,
};
use joshi_domain::{OpenVariant, UtcTimestamp};
use joshi_evidence::Boundary;
use joshi_spool::{GapRecord, LocalSpool, SegmentClosure, SegmentProtector, SpoolEntry};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    sync::Arc,
    time::{Duration, Instant},
};

/// Single-writer durable supervisor. Source tasks hand ownership of bounded records to this object;
/// it never calls a provider itself.
pub struct Supervisor {
    config: SupervisorConfig,
    journal: DurableJournal,
    transport: LocalTransport,
    queue: BoundedQueue,
    queued: BTreeSet<ReservationId>,
    state: RuntimeState,
}

impl Supervisor {
    /// Open a collector root with production durability behavior and no private-domain keys.
    ///
    /// # Errors
    ///
    /// Refuses an invalid configuration, a second writer, corrupt durable state, or spool failure.
    pub fn open(config: SupervisorConfig) -> Result<Self> {
        Self::open_with(config, BTreeMap::new(), Arc::new(NoFaults))
    }

    /// Return the exact fsync-complete reservation documents for one registered run.
    ///
    /// The append-only journal remains the authority; this readback neither reserves a new
    /// attempt nor authorizes I/O.
    ///
    /// # Errors
    ///
    /// Refuses duplicate reservation identities or a journal reservation whose embedded run
    /// reference does not validate.
    pub fn reservations_for_run(&self, run_id: &str) -> Result<Vec<AttemptReservation>> {
        let mut identities = BTreeSet::new();
        let mut values = Vec::new();
        for record in self.journal.records() {
            let JournalEvent::AttemptReserved(reservation) = &record.event else {
                continue;
            };
            let Some(run) = &reservation.run else {
                continue;
            };
            run.validate()?;
            if run.run_id != run_id {
                continue;
            }
            if !identities.insert(reservation.reservation_id.clone()) {
                return Err(SupervisorError::InvalidState(
                    "durable journal repeats one reservation identity".into(),
                ));
            }
            values.push(reservation.clone());
        }
        Ok(values)
    }

    /// Return reservations whose exact journal lifecycle proves one observed, gap-free finite
    /// capture and shutdown.
    ///
    /// This is stricter than [`Self::reservations_for_run`]: a reservation recovered before I/O,
    /// abandoned after I/O, settled with a violation, stopped with a gap, or followed by a
    /// degraded shutdown refuses rather than being represented as completed.
    ///
    /// # Errors
    ///
    /// Refuses an incomplete, duplicated, reordered, recovered, abandoned, gap-bearing, or
    /// degraded lifecycle for any reservation in the selected run.
    pub fn completed_no_gap_reservations_for_run(
        &self,
        run_id: &str,
    ) -> Result<Vec<AttemptReservation>> {
        let reservations = self.reservations_for_run(run_id)?;
        for reservation in &reservations {
            let mut phase = 0_u8;
            let mut shutdown_closed = false;
            for record in self.journal.records() {
                match &record.event {
                    JournalEvent::RuntimeIoStarted { reservation_id }
                        if reservation_id == &reservation.reservation_id =>
                    {
                        if phase != 0 {
                            return Err(SupervisorError::InvalidState(
                                "completed reservation has a reordered or duplicate I/O start"
                                    .into(),
                            ));
                        }
                        phase = 1;
                    }
                    JournalEvent::LocalDurabilityRecorded { reservation_id, .. }
                        if reservation_id == &reservation.reservation_id =>
                    {
                        if phase != 1 {
                            return Err(SupervisorError::InvalidState(
                                "completed reservation has reordered or duplicate durability"
                                    .into(),
                            ));
                        }
                        phase = 2;
                    }
                    JournalEvent::RuntimeBudgetSettled {
                        reservation_id,
                        disposition,
                        violation,
                        ..
                    } if reservation_id == &reservation.reservation_id => {
                        if phase != 2
                            || *disposition != crate::RuntimeSettlementDisposition::Observed
                            || violation.is_some()
                        {
                            return Err(SupervisorError::InvalidState(
                                "completed reservation lacks an observed nonviolating settlement"
                                    .into(),
                            ));
                        }
                        phase = 3;
                    }
                    JournalEvent::AttemptCancelledBeforeIo { reservation_id }
                    | JournalEvent::AttemptAbandoned { reservation_id, .. }
                        if reservation_id == &reservation.reservation_id =>
                    {
                        return Err(SupervisorError::InvalidState(
                            "recovered or abandoned reservation is not a completed capture".into(),
                        ));
                    }
                    JournalEvent::GenerationStopped {
                        source_key,
                        operation_key,
                        generation,
                        gap_segment,
                        ..
                    } if source_key == &reservation.source_key
                        && operation_key == &reservation.operation_key
                        && generation == &reservation.generation =>
                    {
                        if phase != 3 || gap_segment.is_some() {
                            return Err(SupervisorError::InvalidState(
                                "completed reservation has a reordered or gap-bearing stop".into(),
                            ));
                        }
                        phase = 4;
                    }
                    JournalEvent::ShutdownCompleted {
                        abandoned_attempts,
                        downtime_gaps,
                        deadline_exceeded,
                        ..
                    } if phase == 4 => {
                        if *abandoned_attempts != 0
                            || *downtime_gaps != 0
                            || *deadline_exceeded
                            || shutdown_closed
                        {
                            return Err(SupervisorError::InvalidState(
                                "completed reservation has a degraded or duplicate shutdown".into(),
                            ));
                        }
                        shutdown_closed = true;
                    }
                    _ => {}
                }
            }
            if phase != 4 || !shutdown_closed {
                return Err(SupervisorError::InvalidState(
                    "reservation does not have one complete gap-free journal lifecycle".into(),
                ));
            }
        }
        Ok(reservations)
    }

    /// Reopen the exact local-spool receipt for one completed gap-free reservation.
    ///
    /// The returned idempotent status describes this readback invocation; it does not rewrite the
    /// retained segment or its original journal outcome.
    ///
    /// # Errors
    ///
    /// Refuses a reservation without an exact completed lifecycle, a mismatched journal value,
    /// a missing attempt segment, or a segment which is not exactly one evidence batch.
    pub fn local_spool_receipt_for_completed_reservation(
        &self,
        reservation: &AttemptReservation,
    ) -> Result<LocalSpoolReceiptV1> {
        let run_id = reservation.run.as_ref().ok_or_else(|| {
            SupervisorError::InvalidState("completed reservation lost its run binding".into())
        })?;
        if !self
            .completed_no_gap_reservations_for_run(&run_id.run_id)?
            .iter()
            .any(|value| value == reservation)
        {
            return Err(SupervisorError::InvalidState(
                "reservation is not the exact completed journal value".into(),
            ));
        }
        let Some((closure, entry_kinds)) =
            self.transport.find_attempt(&reservation.reservation_id)?
        else {
            return Err(SupervisorError::InvalidState(
                "completed reservation lost its local attempt segment".into(),
            ));
        };
        if entry_kinds.len() != 1 || entry_kinds[0] != "evidence_batch" {
            return Err(SupervisorError::InvalidState(
                "completed reservation segment is not one evidence batch".into(),
            ));
        }
        local_receipt(&closure, DurableOutcome::Idempotent)
    }

    /// Open with caller-owned private-domain protectors. Keys are never serialized into config,
    /// health, journal, or spool metadata.
    ///
    /// # Errors
    ///
    /// Refuses invalid/corrupt state or a second writer.
    pub fn open_with_protectors(
        config: SupervisorConfig,
        protectors: BTreeMap<String, Arc<SegmentProtector>>,
    ) -> Result<Self> {
        Self::open_with(config, protectors, Arc::new(NoFaults))
    }

    /// Deterministic fault-injection constructor for kill-boundary tests.
    ///
    /// # Errors
    ///
    /// Refuses invalid/corrupt state or an injected transition.
    pub fn open_with_faults(
        config: SupervisorConfig,
        protectors: BTreeMap<String, Arc<SegmentProtector>>,
        faults: Arc<dyn FaultInjector>,
    ) -> Result<Self> {
        Self::open_with(config, protectors, faults)
    }

    fn open_with(
        config: SupervisorConfig,
        protectors: BTreeMap<String, Arc<SegmentProtector>>,
        faults: Arc<dyn FaultInjector>,
    ) -> Result<Self> {
        config.validate()?;
        let mut journal = DurableJournal::open(&config.root, faults.clone())?;
        let mut state = RuntimeState::default();
        for record in journal.records() {
            state.apply(&record.event);
        }
        let recovered_records = u64::try_from(journal.records().len()).unwrap_or(u64::MAX);
        let at = now_utc()?;
        let started = journal.append(at, JournalEvent::SupervisorStarted { recovered_records })?;
        state.apply(&started.event);
        let spool = LocalSpool::open(config.spool.clone())?;
        let installation_id = journal.installation_id().to_owned();
        let queue = BoundedQueue::new(config.queue);
        let transport = LocalTransport::new(
            spool,
            installation_id,
            protectors,
            faults,
            config.maximum_spool_bytes_per_utc_day,
        );
        let mut supervisor = Self {
            config,
            journal,
            transport,
            queue,
            queued: BTreeSet::new(),
            state,
        };
        supervisor.persist_health()?;
        Ok(supervisor)
    }

    #[must_use]
    pub fn installation_id(&self) -> &str {
        self.journal.installation_id()
    }

    #[must_use]
    pub fn spool(&self) -> &LocalSpool {
        self.transport.spool()
    }

    /// The exact local spool configuration this supervisor was opened with.
    ///
    /// A physical byte bound derived from a compile-time constant says nothing about the ceiling
    /// a running spool actually enforces, and a caller-supplied copy of the configuration proves
    /// nothing either: it can simply disagree with the live one. Reading it from the supervisor is
    /// what lets an ingest runtime compare [`crate::ingest::physical_size`]'s derived segment
    /// bound against the ceiling this process really runs under, and refuse a read it could not
    /// durably retain before opening a socket. Nothing in this tree performs that comparison
    /// today; see that module's documentation for the obligation it leaves open.
    #[must_use]
    pub const fn spool_config(&self) -> &joshi_spool::SpoolConfig {
        &self.config.spool
    }

    pub(crate) fn journal_records(&self) -> &[crate::JournalRecord] {
        self.journal.records()
    }

    pub(crate) fn append_runtime_event(
        &mut self,
        at: UtcTimestamp,
        event: JournalEvent,
    ) -> Result<()> {
        if !matches!(
            event,
            JournalEvent::RuntimeRunAttached { .. }
                | JournalEvent::RuntimeIoStarted { .. }
                | JournalEvent::RuntimeBudgetSettled { .. }
        ) {
            return Err(SupervisorError::InvalidValue(
                "runtime journal port accepts only runtime lifecycle events".into(),
            ));
        }
        let record = self.journal.append(at, event)?;
        self.state.apply(&record.event);
        self.persist_health()
    }

    /// Fsync one attempt identity before a caller performs HTTP, opens a connection generation,
    /// writes source control, or begins a poll.
    ///
    /// # Errors
    ///
    /// Refuses new work during shutdown, malformed protection, or a stopped generation.
    pub fn reserve(
        &mut self,
        request: ReservationRequest,
        at: UtcTimestamp,
    ) -> Result<AttemptReservation> {
        self.require_running()?;
        request.protection.validate()?;
        match (
            &request.run,
            request.execution_claim,
            &request.provider_plan,
        ) {
            (Some(run), Some(claim), Some(plan)) => {
                run.validate()?;
                claim.validate()?;
                plan.validate()?;
            }
            (None, None, None) => {}
            _ => {
                return Err(SupervisorError::InvalidValue(
                    "run reference and execution claim must be present together".into(),
                ));
            }
        }
        self.journal
            .check(crate::FaultPoint::BeforeAttemptReservation)?;
        let key = (request.source_key.clone(), request.operation_key.clone());
        let (generation, attempt_ordinal) = match self.state.generations.get(&key) {
            None => (GenerationId::new(1), 1),
            Some(previous) if request.kind.starts_generation() => (
                GenerationId::new(previous.generation.get().saturating_add(1)),
                1,
            ),
            Some(previous) if previous.stopped => {
                return Err(SupervisorError::InvalidState(
                    "stopped generation requires an explicit new connection or poll".into(),
                ));
            }
            Some(previous) => (previous.generation, previous.next_attempt_ordinal),
        };
        let reservation_id = ReservationId::new(format!(
            "reservation-{}-{:020}",
            self.journal.installation_id(),
            self.journal.next_ordinal()
        ))?;
        let reservation = AttemptReservation {
            contract: crate::SUPERVISOR_CONTRACT_VERSION.into(),
            reservation_id,
            installation_id: self.journal.installation_id().into(),
            source_key: request.source_key,
            operation_key: request.operation_key,
            generation,
            attempt_ordinal,
            kind: request.kind,
            scope: request.scope,
            lower: request.lower,
            protection: request.protection,
            run: request.run,
            execution_claim: request.execution_claim,
            provider_plan: request.provider_plan,
            reserved_at: at,
            authority: AUTHORITY_CEILING.into(),
        };
        let record = self
            .journal
            .append(at, JournalEvent::AttemptReserved(reservation.clone()))?;
        self.state.apply(&record.event);
        self.persist_health()?;
        self.journal
            .check(crate::FaultPoint::AfterAttemptReservation)?;
        Ok(reservation)
    }

    /// Reserve a retry in the same generation after the earlier reservation has been durably
    /// resolved to evidence or an explicit gap.
    ///
    /// # Errors
    ///
    /// Refuses unresolved prior work or a stopped/changed generation.
    pub fn reserve_retry(
        &mut self,
        previous: &AttemptReservation,
        at: UtcTimestamp,
    ) -> Result<AttemptReservation> {
        if self.state.pending.contains_key(&previous.reservation_id) {
            return Err(SupervisorError::InvalidState(
                "cannot retry while the prior attempt remains unresolved".into(),
            ));
        }
        let key = (previous.source_key.clone(), previous.operation_key.clone());
        let current =
            self.state.generations.get(&key).ok_or_else(|| {
                SupervisorError::InvalidState("retry generation is absent".into())
            })?;
        if current.stopped || current.generation != previous.generation {
            return Err(SupervisorError::InvalidState(
                "retry cannot cross or restart a generation".into(),
            ));
        }
        let attempt_ordinal = current.next_attempt_ordinal;
        let reservation_id = ReservationId::new(format!(
            "reservation-{}-{:020}",
            self.journal.installation_id(),
            self.journal.next_ordinal()
        ))?;
        let reservation = AttemptReservation {
            contract: crate::SUPERVISOR_CONTRACT_VERSION.into(),
            reservation_id,
            installation_id: self.journal.installation_id().into(),
            source_key: previous.source_key.clone(),
            operation_key: previous.operation_key.clone(),
            generation: previous.generation,
            attempt_ordinal,
            kind: previous.kind,
            scope: previous.scope.clone(),
            lower: previous.lower.clone(),
            protection: previous.protection.clone(),
            run: previous.run.clone(),
            execution_claim: previous.execution_claim,
            provider_plan: previous.provider_plan.clone(),
            reserved_at: at,
            authority: AUTHORITY_CEILING.into(),
        };
        let record = self
            .journal
            .append(at, JournalEvent::AttemptReserved(reservation.clone()))?;
        self.state.apply(&record.event);
        self.persist_health()?;
        Ok(reservation)
    }

    /// Record a deterministic, visible retry decision. This method does not sleep, perform I/O,
    /// or imply that the failed attempt has been resolved.
    ///
    /// # Errors
    ///
    /// Refuses an unknown reservation or a provider delay beyond the configured ceiling.
    pub fn decide_retry(
        &mut self,
        reservation: &AttemptReservation,
        trigger: RetryTrigger,
        retry_after: Option<Duration>,
        at: UtcTimestamp,
    ) -> Result<RetryDecision> {
        if !self.state.pending.contains_key(&reservation.reservation_id) {
            return Err(SupervisorError::InvalidState(
                "retry decision requires a pending attempt".into(),
            ));
        }
        let policy = self.config.retry;
        let decision = if reservation.attempt_ordinal >= policy.maximum_attempts_per_generation
            || retry_after.is_some_and(|delay| delay > policy.maximum_delay)
        {
            RetryDecision::Exhausted
        } else {
            let exponent = u32::try_from(reservation.attempt_ordinal.saturating_sub(1))
                .unwrap_or(31)
                .min(31);
            let factor = 1_u32.checked_shl(exponent).unwrap_or(u32::MAX);
            let backoff = policy
                .base_delay
                .checked_mul(factor)
                .unwrap_or(policy.maximum_delay)
                .min(policy.maximum_delay);
            let delay = retry_after.map_or(backoff, |provider| provider.max(backoff));
            RetryDecision::Scheduled {
                after_ms: u64::try_from(delay.as_millis()).unwrap_or(u64::MAX),
                next_attempt_ordinal: reservation.attempt_ordinal.saturating_add(1),
            }
        };
        let record = self.journal.append(
            at,
            JournalEvent::RetryDecided {
                reservation_id: reservation.reservation_id.clone(),
                trigger,
                decision: decision.clone(),
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()?;
        Ok(decision)
    }

    /// Transfer exact ownership into the record+byte-bounded queue.
    ///
    /// # Errors
    ///
    /// Returns the exact original item on saturation; the caller must stop the source generation
    /// and durably record a scoped gap before releasing it.
    #[allow(clippy::result_large_err)]
    pub fn try_enqueue(&mut self, item: PendingSegment) -> std::result::Result<(), PendingSegment> {
        if self.state.lifecycle != Some(CollectorLifecycle::Running)
            || !self
                .state
                .pending
                .contains_key(&item.reservation.reservation_id)
            || self.queued.contains(&item.reservation.reservation_id)
        {
            return Err(item);
        }
        let id = item.reservation.reservation_id.clone();
        self.queue.try_push(item)?;
        self.queued.insert(id);
        if self.persist_health().is_err() {
            // The owned item remains queued and unreleased. Health failure cannot manufacture an
            // acknowledgement or silently remove evidence.
        }
        Ok(())
    }

    /// Adapt an existing bounded `SourceOutput` under its pre-I/O reservation, then transfer exact
    /// ownership to the record+byte queue. Source-specific semantic choices stay in the adapter.
    ///
    /// # Errors
    ///
    /// Returns an adapter error if the source output has no lossless evidence representation, or
    /// the exact prepared item if the bounded queue is saturated.
    #[allow(clippy::result_large_err)]
    pub fn enqueue_source_output(
        &mut self,
        adapter: &mut dyn SourceOutputAdapter,
        reservation: &AttemptReservation,
        output: joshi_sources::SourceOutput,
    ) -> std::result::Result<(), SourceIngressError> {
        let item = adapter
            .prepare(reservation, output)
            .map_err(SourceIngressError::Adapter)?;
        self.try_enqueue(item)
            .map_err(SourceIngressError::Saturated)
    }

    /// Seal/fsync the oldest queued item and only then release queue ownership.
    ///
    /// Returns the shared strict `LocalSpoolReceiptV1`; no queue item is released for a partial or
    /// merely successful-looking transport result.
    ///
    /// # Errors
    ///
    /// Leaves the exact item queued on any encoding, spool, journal, or health failure.
    pub fn drain_one(&mut self, at: UtcTimestamp) -> Result<Option<LocalSpoolReceiptV1>> {
        let Some(item) = self.queue.front().cloned() else {
            return Ok(None);
        };
        let (closure, outcome) = self
            .transport
            .append_attempt(&item.reservation, &item.entry)?;
        let record = self.journal.append(
            at,
            JournalEvent::LocalDurabilityRecorded {
                reservation_id: item.reservation.reservation_id.clone(),
                segment: closure.clone(),
                outcome,
            },
        )?;
        self.state.apply(&record.event);
        let released = self.queue.pop_front().ok_or_else(|| {
            SupervisorError::InvalidState(
                "queued item disappeared before durable release".to_string(),
            )
        })?;
        self.queued.remove(&released.reservation.reservation_id);
        self.persist_health()?;
        Ok(Some(local_receipt(&closure, outcome)?))
    }

    /// Drain every currently queued item in FIFO order.
    ///
    /// # Errors
    ///
    /// Stops at the first failure without releasing that or later items.
    pub fn drain_all(&mut self, at: UtcTimestamp) -> Result<Vec<LocalSpoolReceiptV1>> {
        let mut durable = Vec::new();
        while let Some(item) = self.drain_one(at)? {
            durable.push(item);
        }
        Ok(durable)
    }

    /// Resolve one reservation without a response as an explicit durable gap. The gap consumes
    /// the attempt's deterministic segment identity, preventing a late payload from masquerading
    /// as the same occurrence.
    ///
    /// # Errors
    ///
    /// Refuses unknown/already-resolved work or unavailable protection.
    pub fn abandon(
        &mut self,
        reservation: &AttemptReservation,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<LocalSpoolReceiptV1> {
        let (closure, outcome) = self.abandon_closure(reservation, reason, at)?;
        local_receipt(&closure, outcome)
    }

    /// Resolve a durable reservation when journal replay proves provider I/O never began.
    /// No coverage gap is emitted because no acquisition interval existed.
    pub(crate) fn cancel_before_io(
        &mut self,
        reservation: &AttemptReservation,
        at: UtcTimestamp,
    ) -> Result<()> {
        let pending = self
            .state
            .pending
            .get(&reservation.reservation_id)
            .ok_or_else(|| SupervisorError::InvalidState("attempt is not pending".into()))?;
        if pending != reservation || self.queued.contains(&reservation.reservation_id) {
            return Err(SupervisorError::InvalidState(
                "queued or mismatched attempt cannot be cancelled before I/O".into(),
            ));
        }
        let record = self.journal.append(
            at,
            JournalEvent::AttemptCancelledBeforeIo {
                reservation_id: reservation.reservation_id.clone(),
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()
    }

    pub(crate) fn stop_generation_without_gap(
        &mut self,
        reservation: &AttemptReservation,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<()> {
        let record = self.journal.append(
            at,
            JournalEvent::GenerationStopped {
                source_key: reservation.source_key.clone(),
                operation_key: reservation.operation_key.clone(),
                generation: reservation.generation,
                reason,
                gap_segment: None,
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()
    }

    /// Resolve an uncompleted attempt as a durable scoped gap and stop its generation.
    ///
    /// This is the fail-closed post-I/O path: neither transition is merely in-memory, and a
    /// caller must treat an error from either append as terminal and replay-only.
    pub(crate) fn abandon_and_stop(
        &mut self,
        reservation: &AttemptReservation,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<LocalSpoolReceiptV1> {
        let (closure, outcome) = self.abandon_closure(reservation, reason.clone(), at)?;
        let record = self.journal.append(
            at,
            JournalEvent::GenerationStopped {
                source_key: reservation.source_key.clone(),
                operation_key: reservation.operation_key.clone(),
                generation: reservation.generation,
                reason,
                gap_segment: Some(closure.clone()),
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()?;
        local_receipt(&closure, outcome)
    }

    /// Stop a generation after its attempt evidence is already durable, opening a separate
    /// downtime gap so a terminal accounting failure cannot look like continued coverage.
    pub(crate) fn stop_generation_with_downtime(
        &mut self,
        reservation: &AttemptReservation,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<LocalSpoolReceiptV1> {
        let ordinal = self.journal.next_ordinal();
        let segment_id = self
            .transport
            .control_segment_id(ordinal, "runtime-terminal-downtime");
        let gap = SpoolEntry::Gap(GapRecord {
            gap_id: format!(
                "gap-runtime-terminal-{}-{:020}",
                self.journal.installation_id(),
                ordinal
            ),
            scope: reservation.scope.clone(),
            lower: Boundary::Wall { value: at },
            upper: None,
            reason: reason.clone(),
            detected_at: at,
            related_segment_id: None,
        });
        let (closure, outcome) =
            self.transport
                .append_control(segment_id, at, &reservation.protection, &gap)?;
        let record = self.journal.append(
            at,
            JournalEvent::GenerationStopped {
                source_key: reservation.source_key.clone(),
                operation_key: reservation.operation_key.clone(),
                generation: reservation.generation,
                reason,
                gap_segment: Some(closure.clone()),
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()?;
        local_receipt(&closure, outcome)
    }

    fn abandon_closure(
        &mut self,
        reservation: &AttemptReservation,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<(SegmentClosure, DurableOutcome)> {
        let pending = self
            .state
            .pending
            .get(&reservation.reservation_id)
            .ok_or_else(|| SupervisorError::InvalidState("attempt is not pending".into()))?;
        if pending != reservation || self.queued.contains(&reservation.reservation_id) {
            return Err(SupervisorError::InvalidState(
                "queued or mismatched attempt cannot be abandoned".into(),
            ));
        }
        let gap = self.gap_entry(reservation, reason.clone(), at);
        let (closure, outcome) = self
            .transport
            .append_attempt(reservation, &SpoolEntry::Gap(gap))?;
        let record = self.journal.append(
            at,
            JournalEvent::AttemptAbandoned {
                reservation_id: reservation.reservation_id.clone(),
                gap_segment: closure.clone(),
                reason,
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()?;
        Ok((closure, outcome))
    }

    /// On startup, resolve every old reservation exactly once: discover an already durable
    /// deterministic segment, or append an abandoned-attempt gap. No source cursor advances.
    ///
    /// # Errors
    ///
    /// Refuses corrupt/conflicting segments or unavailable private protection keys.
    pub fn reconcile_startup(&mut self, at: UtcTimestamp) -> Result<Vec<LocalSpoolReceiptV1>> {
        let pending: Vec<_> = self.state.pending.values().cloned().collect();
        let mut resolved = Vec::new();
        for reservation in pending {
            if let Some((closure, kinds)) =
                self.transport.find_attempt(&reservation.reservation_id)?
            {
                let event = if kinds.iter().all(|kind| kind == "evidence_batch") {
                    JournalEvent::LocalDurabilityRecorded {
                        reservation_id: reservation.reservation_id.clone(),
                        segment: closure.clone(),
                        outcome: DurableOutcome::Idempotent,
                    }
                } else if kinds.iter().all(|kind| kind == "gap") {
                    JournalEvent::AttemptAbandoned {
                        reservation_id: reservation.reservation_id.clone(),
                        gap_segment: closure.clone(),
                        reason: OpenVariant::known("restart_recovered_gap")?,
                    }
                } else {
                    return Err(SupervisorError::InvalidState(
                        "attempt segment contains mixed or unsupported entry kinds".into(),
                    ));
                };
                let record = self.journal.append(at, event)?;
                self.state.apply(&record.event);
                resolved.push(local_receipt(&closure, DurableOutcome::Idempotent)?);
            } else {
                let (closure, outcome) = self.abandon_closure(
                    &reservation,
                    OpenVariant::known("abandoned_attempt_after_restart")?,
                    at,
                )?;
                resolved.push(local_receipt(&closure, outcome)?);
            }
        }
        self.persist_health()?;
        Ok(resolved)
    }

    /// Fail closed after queue saturation. The original item is released only after a scoped gap
    /// and stopped-generation event are durable.
    ///
    /// # Errors
    ///
    /// Refuses an item that was not a current pending attempt or cannot consume control reserve.
    pub fn stop_saturated(
        &mut self,
        item: PendingSegment,
        at: UtcTimestamp,
    ) -> Result<LocalSpoolReceiptV1> {
        let reservation = item.reservation;
        let (closure, outcome) =
            self.abandon_closure(&reservation, OpenVariant::known("ingress_saturated")?, at)?;
        let record = self.journal.append(
            at,
            JournalEvent::GenerationStopped {
                source_key: reservation.source_key,
                operation_key: reservation.operation_key,
                generation: reservation.generation,
                reason: OpenVariant::known("ingress_saturated")?,
                gap_segment: Some(closure.clone()),
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()?;
        local_receipt(&closure, outcome)
    }

    /// Replace the oldest queued evidence item with a durable scoped gap when spool/disk policy
    /// refuses further evidence. The queue item is released only after the gap and stopped-
    /// generation journal record are durable.
    ///
    /// # Errors
    ///
    /// Refuses an empty/control queue or unavailable control-reserve protection.
    pub fn stop_front_for_pressure(
        &mut self,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<LocalSpoolReceiptV1> {
        let item = self.queue.front().cloned().ok_or_else(|| {
            SupervisorError::InvalidState("pressure stop has no queued item".into())
        })?;
        if item.class != crate::QueueClass::Evidence {
            return Err(SupervisorError::InvalidState(
                "control-reserve records cannot be discarded for pressure".into(),
            ));
        }
        let gap = self.gap_entry(&item.reservation, reason.clone(), at);
        let (closure, outcome) = self
            .transport
            .append_attempt(&item.reservation, &SpoolEntry::Gap(gap))?;
        let abandoned = self.journal.append(
            at,
            JournalEvent::AttemptAbandoned {
                reservation_id: item.reservation.reservation_id.clone(),
                gap_segment: closure.clone(),
                reason: reason.clone(),
            },
        )?;
        self.state.apply(&abandoned.event);
        let stopped = self.journal.append(
            at,
            JournalEvent::GenerationStopped {
                source_key: item.reservation.source_key.clone(),
                operation_key: item.reservation.operation_key.clone(),
                generation: item.reservation.generation,
                reason,
                gap_segment: Some(closure.clone()),
            },
        )?;
        self.state.apply(&stopped.event);
        let released = self.queue.pop_front().ok_or_else(|| {
            SupervisorError::InvalidState(
                "pressure item disappeared before durable gap release".to_string(),
            )
        })?;
        self.queued.remove(&released.reservation.reservation_id);
        self.persist_health()?;
        local_receipt(&closure, outcome)
    }

    /// Gracefully stop admission, drain owned records, resolve in-flight attempts, append one
    /// downtime boundary per active generation, fsync health, and report deadline status.
    ///
    /// # Errors
    ///
    /// Stops before `ShutdownCompleted` if any durable transition fails.
    pub fn shutdown(&mut self, at: UtcTimestamp) -> Result<ShutdownReport> {
        self.require_running()?;
        let started = Instant::now();
        let deadline_ms =
            u64::try_from(self.config.shutdown_deadline.as_millis()).unwrap_or(u64::MAX);
        let record = self
            .journal
            .append(at, JournalEvent::ShutdownStarted { deadline_ms })?;
        self.state.apply(&record.event);
        let drained_segments = u64::try_from(self.drain_all(at)?.len()).unwrap_or(u64::MAX);
        let before_abandoned = self.state.abandoned_attempts;
        self.reconcile_startup(at)?;
        let abandoned_attempts = self
            .state
            .abandoned_attempts
            .saturating_sub(before_abandoned);
        let active: Vec<_> = self
            .state
            .generations
            .iter()
            .filter(|(_, state)| !state.stopped)
            .map(|(key, state)| (key.clone(), state.clone()))
            .collect();
        let mut downtime_gaps = 0_u64;
        for ((source_key, operation_key), generation) in active {
            let ordinal = self.journal.next_ordinal();
            let segment_id = self
                .transport
                .control_segment_id(ordinal, "shutdown-downtime");
            let gap = SpoolEntry::Gap(GapRecord {
                gap_id: format!(
                    "gap-shutdown-{}-{:020}",
                    self.journal.installation_id(),
                    ordinal
                ),
                scope: generation.scope,
                lower: Boundary::Wall { value: at },
                upper: None,
                reason: OpenVariant::known("source_downtime_shutdown")?,
                detected_at: at,
                related_segment_id: None,
            });
            let (closure, _) =
                self.transport
                    .append_control(segment_id, at, &generation.protection, &gap)?;
            let record = self.journal.append(
                at,
                JournalEvent::GenerationStopped {
                    source_key,
                    operation_key,
                    generation: generation.generation,
                    reason: OpenVariant::known("graceful_shutdown")?,
                    gap_segment: Some(closure),
                },
            )?;
            self.state.apply(&record.event);
            downtime_gaps = downtime_gaps.saturating_add(1);
        }
        let deadline_exceeded = started.elapsed() > self.config.shutdown_deadline;
        let report = ShutdownReport {
            drained_segments,
            abandoned_attempts,
            downtime_gaps,
            deadline_exceeded,
        };
        let record = self.journal.append(
            at,
            JournalEvent::ShutdownCompleted {
                drained_segments,
                abandoned_attempts,
                downtime_gaps,
                deadline_exceeded,
            },
        )?;
        self.state.apply(&record.event);
        self.persist_health()?;
        Ok(report)
    }

    /// Return and durably refresh the finite, local health snapshot.
    ///
    /// # Errors
    ///
    /// Refuses corrupt spool state or health persistence failure.
    pub fn health(&mut self) -> Result<SupervisorHealthV1> {
        let health = self.build_health()?;
        self.journal.write_health(&serde_json::to_vec(&health)?)?;
        Ok(health)
    }

    fn require_running(&self) -> Result<()> {
        if self.state.lifecycle == Some(CollectorLifecycle::Running) {
            Ok(())
        } else {
            Err(SupervisorError::InvalidState(
                "supervisor is not accepting new work".into(),
            ))
        }
    }

    fn gap_entry(
        &self,
        reservation: &AttemptReservation,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> GapRecord {
        GapRecord {
            gap_id: format!("gap-{}", reservation.reservation_id),
            scope: reservation.scope.clone(),
            lower: reservation.lower.clone(),
            upper: None,
            reason,
            detected_at: at,
            related_segment_id: Some(
                self.transport
                    .attempt_segment_id(&reservation.reservation_id),
            ),
        }
    }

    fn persist_health(&mut self) -> Result<()> {
        let health = self.build_health()?;
        self.journal.write_health(&serde_json::to_vec(&health)?)
    }

    fn build_health(&self) -> Result<SupervisorHealthV1> {
        let spool = self.transport.spool().status()?;
        let mut health = SupervisorHealthV1::empty(self.journal.installation_id().into(), spool);
        health.lifecycle = self.state.lifecycle.unwrap_or(CollectorLifecycle::Starting);
        health.journal_ordinal = self.journal.next_ordinal().saturating_sub(1);
        health.queue_records = u64::try_from(self.queue.records()).unwrap_or(u64::MAX);
        health.queue_bytes = self.queue.bytes();
        let limits = self.queue.limits();
        health.queue_maximum_records = u64::try_from(limits.maximum_records).unwrap_or(u64::MAX);
        health.queue_maximum_bytes = limits.maximum_bytes;
        health.queue_control_reserve_records =
            u64::try_from(limits.control_reserve_records).unwrap_or(u64::MAX);
        health.queue_control_reserve_bytes = limits.control_reserve_bytes;
        health.ready_segments =
            u64::try_from(self.transport.spool().list_segments()?.len()).unwrap_or(u64::MAX);
        health.catalog_ack_files = count_files(&self.config.spool.root.join("catalog_acks"))?;
        health.remote_ack_files = count_files(&self.config.spool.root.join("acks"))?;
        health.quarantine_files = count_files(&self.config.spool.root.join("quarantine"))?;
        health.abandoned_attempts = self.state.abandoned_attempts;
        health.saturation_stops = self.state.saturation_stops;
        health.sources = self
            .state
            .generations
            .iter()
            .map(|((source_key, operation_key), generation)| {
                let pending_reservations = self
                    .state
                    .pending
                    .values()
                    .filter(|reservation| {
                        reservation.source_key == *source_key
                            && reservation.operation_key == *operation_key
                            && reservation.generation == generation.generation
                    })
                    .count();
                let retries_decided = self
                    .state
                    .retries
                    .get(&(
                        source_key.clone(),
                        operation_key.clone(),
                        generation.generation,
                    ))
                    .copied()
                    .unwrap_or(0);
                SourceRuntimeHealth {
                    source_key: source_key.clone(),
                    operation_key: operation_key.clone(),
                    generation: generation.generation,
                    pending_reservations: u64::try_from(pending_reservations).unwrap_or(u64::MAX),
                    retries_decided,
                    stopped: generation.stopped,
                }
            })
            .collect();
        health.sources.sort_by(|left, right| {
            (&left.source_key, &left.operation_key).cmp(&(&right.source_key, &right.operation_key))
        });
        Ok(health)
    }
}

fn count_files(path: &std::path::Path) -> Result<u64> {
    let count = fs::read_dir(path)
        .map_err(|source| SupervisorError::io(path, source))?
        .filter_map(std::result::Result::ok)
        .filter(|entry| entry.path().is_file())
        .count();
    Ok(u64::try_from(count).unwrap_or(u64::MAX))
}

fn now_utc() -> Result<UtcTimestamp> {
    UtcTimestamp::new(time::OffsetDateTime::now_utc())
        .map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}

fn local_receipt(closure: &SegmentClosure, outcome: DurableOutcome) -> Result<LocalSpoolReceiptV1> {
    let receipt = LocalSpoolReceiptV1 {
        contract: LOCAL_SPOOL_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        segment_id: closure.segment_id.to_string(),
        protection_domain: closure.domain.to_string(),
        protection_class: public_protection(closure.protection_class),
        exact_segment: exact_closure(
            &closure.exact_segment.digest,
            closure.exact_segment.byte_len,
        )?,
        status: match outcome {
            DurableOutcome::Accepted => OperationalStatus::Accepted,
            DurableOutcome::Idempotent => OperationalStatus::Idempotent,
        },
        authority: AUTHORITY.into(),
    };
    receipt.validate()?;
    Ok(receipt)
}
