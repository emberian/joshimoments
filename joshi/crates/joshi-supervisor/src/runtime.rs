use crate::{
    AttemptBudgetClaim, AttemptBudgetUsage, AttemptKind, AttemptReservation, BudgetDimension,
    BudgetLedger, BudgetPermit, CollectorRuntimeConfigV1, JournalEvent, LocalSpoolReceiptV1,
    OperationKey, PendingSegment, ProtectionProfile, ProviderPlanReferenceV1, QueueClass,
    ReservationId, ReservationRequest, Result, RuntimeDocumentSet, RuntimeSettlementDisposition,
    SourceKey, Supervisor, SupervisorError,
};
use joshi_admission::wave5::Wave5RunReferenceV1;
use joshi_domain::{
    BatchDigest, CoverageId, OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp,
};
use joshi_evidence::{Boundary, CoverageScope, CoverageWindow, DurableIngestBatch, EvidenceDraft};
use joshi_sources::{
    BuiltInExecutionDisposition, ContentType, EvidenceContext, FrameDirection,
    LogicalSourceLocator, ProviderAttemptOutcome, ProviderAttemptPermit, ProviderAttemptPlan,
    ProviderAttemptReport, ProviderCompletionReason, ProviderEventTime, ProviderOperation,
    ProviderRunner, ProviderRunnerCompletion, ProviderRunnerNext, ProviderScopePort,
    RawSourceFrame, RuntimeAttemptCostPort, RuntimeBudgetPort, SourceId, SourceOutput, StreamClass,
    SyntheticProviderRunner, SyntheticScenario, SyntheticStep, Transport, UnixMillis,
    ValidatedProviderRunPlan,
};
use joshi_spool::{EvidenceBatchEntry, GapRecord, ProtectionDomainId, SpoolEntry};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::collections::{BTreeMap, BTreeSet};

/// Build the sole sealed C0 JSON fixture runner without exposing a source/evidence dependency to
/// the collector application. The returned runner contains one exact raw frame and no authorable
/// semantic-outcome adapter.
///
/// # Errors
///
/// Refuses a non-synthetic or multi-operation plan, malformed JSON, economic spend, or a
/// fixture whose exact request/page/byte/time use does not fit the operation reservation.
pub fn synthetic_c0_json_runner(
    plan: ValidatedProviderRunPlan,
    fixture_body: Vec<u8>,
    received_at: UtcTimestamp,
) -> Result<SyntheticProviderRunner> {
    let _: serde_json::Value = serde_json::from_slice(&fixture_body).map_err(|_| {
        SupervisorError::InvalidValue("sealed C0 JSON fixture body is malformed".into())
    })?;
    let [operation] = plan.operations() else {
        return Err(SupervisorError::InvalidConfig(
            "sealed C0 fixture requires exactly one operation".into(),
        ));
    };
    if operation.plan.operation != ProviderOperation::SyntheticEmit {
        return Err(SupervisorError::ProviderDisabledPendingCanonicalAdmission);
    }
    let ProviderScopePort::SyntheticScenario { scenario_id } = &operation.plan.scope else {
        return Err(SupervisorError::ProviderDisabledPendingCanonicalAdmission);
    };
    let maximum = operation.plan.attempt_cost.reserved_total()?;
    let ingress_bytes = u64::try_from(fixture_body.len())
        .map_err(|_| SupervisorError::InvalidValue("fixture body is too large".into()))?;
    if fixture_body.is_empty()
        || maximum.requests != 1
        || maximum.ingress_bytes < ingress_bytes
        || maximum.wall_millis == 0
        || maximum.provider_credits != 0
        || !maximum.provider_currency_minor.is_empty()
        || !maximum.chain_native_atoms.is_empty()
    {
        return Err(SupervisorError::InvalidConfig(
            "sealed C0 fixture does not fit its exact operation reservation".into(),
        ));
    }
    let received_millis = received_at.as_datetime().unix_timestamp_nanos() / 1_000_000;
    let received_millis = i64::try_from(received_millis).map_err(|_| {
        SupervisorError::InvalidValue("fixture timestamp is outside UnixMillis".into())
    })?;
    let source_id = operation.source_id.clone();
    let scenario_id = scenario_id.clone();
    let actual_usage = RuntimeBudgetPort {
        requests: 1,
        pages: maximum.pages,
        ingress_bytes,
        durable_bytes: 0,
        provider_credits: 0,
        wall_millis: 1,
        provider_currency_minor: BTreeMap::new(),
        chain_native_atoms: BTreeMap::new(),
    };
    let frame = RawSourceFrame {
        contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
        source: source_id,
        transport: Transport::Fixture,
        stream_class: StreamClass::BroadCensus,
        direction: FrameDirection::Inbound,
        content_type: ContentType::Json,
        received_at: UnixMillis(received_millis),
        connection_epoch: 1,
        sequence: 1,
        http_status: Some(200),
        safe_headers: Vec::new(),
        body: bytes::Bytes::from(fixture_body),
    };
    SyntheticProviderRunner::new(
        plan,
        SyntheticScenario {
            scenario_id,
            steps: vec![SyntheticStep {
                operation_index: 0,
                actual_usage,
                outcome: ProviderAttemptOutcome::Captured {
                    outputs: vec![SourceOutput::Frame(frame)],
                },
            }],
        },
    )
    .map_err(Into::into)
}

/// Built-in semantic adapter for the only executable Wave 5 profile: sealed, no-network C0.
/// Callers cannot implement a competing adapter. Its optional exact-batch carrier requires the
/// captured fixture bytes verbatim and grants no source/store authority by itself.
#[derive(Default)]
pub struct SyntheticRuntimeOutcomeAdapter {
    exact_fixture: Option<ExactFixtureBatch>,
}

struct ExactFixtureBatch {
    expected_frame_body: Vec<u8>,
    batch: DurableIngestBatch,
    exact_batch_bytes: Vec<u8>,
    policy_contract: String,
    exact_policy_bytes: Vec<u8>,
}

impl SyntheticRuntimeOutcomeAdapter {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            exact_fixture: None,
        }
    }

    /// Build the sealed C0 carrier for one already validated exact semantic batch.
    ///
    /// This constructor grants no source or store authority. At the attempt boundary it still
    /// requires one exact fixture frame with `expected_frame_body`; the sole store must later
    /// parse and admit the retained batch and policy bytes independently.
    ///
    /// # Errors
    ///
    /// Refuses empty frame bytes or a noncanonical, digest-mismatched, or byte-mismatched batch.
    pub fn for_exact_fixture_batch(
        expected_frame_body: Vec<u8>,
        batch: DurableIngestBatch,
        exact_batch_bytes: Vec<u8>,
        policy_contract: impl Into<String>,
        exact_policy_bytes: Vec<u8>,
    ) -> Result<Self> {
        if expected_frame_body.is_empty() {
            return Err(SupervisorError::InvalidValue(
                "exact fixture frame body must be nonempty".into(),
            ));
        }
        let _: serde_json::Value = serde_json::from_slice(&expected_frame_body).map_err(|_| {
            SupervisorError::InvalidValue("exact fixture frame body must be JSON".into())
        })?;
        // Construct once without retaining the temporary entry. This validates the canonical
        // digest and exact batch encoding at the capability boundary.
        let policy_contract = policy_contract.into();
        StableString::new(policy_contract.clone())
            .map_err(|error| SupervisorError::InvalidValue(error.to_string()))?;
        if exact_policy_bytes.is_empty() {
            return Err(SupervisorError::InvalidValue(
                "exact fixture policy bytes must be nonempty".into(),
            ));
        }
        EvidenceBatchEntry::from_exact_bytes(
            &batch,
            exact_batch_bytes.clone(),
            policy_contract.clone(),
            exact_policy_bytes.clone(),
            None,
        )?;
        Ok(Self {
            exact_fixture: Some(ExactFixtureBatch {
                expected_frame_body,
                batch,
                exact_batch_bytes,
                policy_contract,
                exact_policy_bytes,
            }),
        })
    }

    #[allow(clippy::unused_self)] // The sealed adapter is passed as capability, not policy state.
    fn prepare(
        &mut self,
        reservation: &AttemptReservation,
        outcome: ProviderAttemptOutcome,
    ) -> Result<PendingSegment> {
        if let Some(fixture) = &self.exact_fixture {
            let ProviderAttemptOutcome::Captured { outputs } = outcome else {
                return Err(SupervisorError::InvalidValue(
                    "exact fixture batch requires captured progress".into(),
                ));
            };
            let [SourceOutput::Frame(frame)] = outputs.as_slice() else {
                return Err(SupervisorError::InvalidValue(
                    "exact fixture batch requires one raw frame".into(),
                ));
            };
            if frame.transport != Transport::Fixture
                || frame.content_type != ContentType::Json
                || frame.body.as_ref() != fixture.expected_frame_body
            {
                return Err(SupervisorError::InvalidValue(
                    "captured frame differs from the exact fixture batch ingress".into(),
                ));
            }
            return crate::prepare_evidence_batch(
                reservation.clone(),
                &fixture.batch,
                fixture.exact_batch_bytes.clone(),
                fixture.policy_contract.clone(),
                fixture.exact_policy_bytes.clone(),
            );
        }
        match outcome {
            ProviderAttemptOutcome::Captured { outputs } => captured_item(reservation, outputs),
            ProviderAttemptOutcome::BoundedEmpty {
                lower,
                upper,
                proof_contract,
            } => bounded_empty_item(reservation, lower, upper, &proof_contract),
            ProviderAttemptOutcome::Unavailable { at, reason } => {
                gap_item(reservation, at, format!("source_unavailable:{reason}"))
            }
            ProviderAttemptOutcome::Gap {
                at,
                reason,
                coverage,
            } => {
                let exact_coverage = serde_json::to_vec(&coverage)?;
                let coverage_digest = format!("sha256:{:x}", Sha256::digest(exact_coverage));
                gap_item(
                    reservation,
                    at,
                    format!("provider_gap:{reason}:{coverage_digest}"),
                )
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeProgressKind {
    Captured,
    BoundedEmpty,
    Unavailable,
    Gap,
    SaturationGap,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeStepReport {
    pub run_id: String,
    pub reservation_id: ReservationId,
    pub source_key: SourceKey,
    pub operation_key: OperationKey,
    pub generation: crate::GenerationId,
    pub attempt_ordinal: u64,
    pub progress: RuntimeProgressKind,
    pub usage: AttemptBudgetUsage,
    pub local_spool: LocalSpoolReceiptV1,
    pub authority: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeRunReport {
    pub run_id: String,
    pub plan_id: String,
    pub plan_digest: String,
    pub completion: ProviderCompletionReason,
    pub steps: Vec<RuntimeStepReport>,
    pub budget: crate::BudgetSnapshot,
    pub shutdown: crate::ShutdownReport,
    pub authority: String,
}

struct OutstandingRuntimeAttempt {
    reservation: AttemptReservation,
    budget: BudgetPermit,
}

#[derive(Clone, Copy)]
enum RecoveredPhase {
    Reserved,
    IoStarted,
    Settled {
        usage: AttemptBudgetUsage,
        disposition: RuntimeSettlementDisposition,
        violation: Option<BudgetDimension>,
    },
}

struct RecoveredAttempt {
    reservation: AttemptReservation,
    phase: RecoveredPhase,
    durable: bool,
    cancelled_before_io: bool,
}

struct RecoveredJournal {
    attachment: Option<(crate::RunBudgetLimits, UtcTimestamp)>,
    attempts: BTreeMap<ReservationId, RecoveredAttempt>,
    stopped_generations: BTreeSet<(SourceKey, OperationKey, crate::GenerationId)>,
}

#[allow(clippy::too_many_lines)] // Keeping lifecycle replay in one ordered match is audit-critical.
fn scan_runtime_journal(
    records: &[crate::JournalRecord],
    config: &CollectorRuntimeConfigV1,
    run: &Wave5RunReferenceV1,
    limits: crate::RunBudgetLimits,
    plan: &ValidatedProviderRunPlan,
) -> Result<RecoveredJournal> {
    let mut attachment = None;
    let mut attempts = BTreeMap::<ReservationId, RecoveredAttempt>::new();
    let mut stopped_generations = BTreeSet::new();
    for record in records {
        match &record.event {
            JournalEvent::RuntimeRunAttached {
                run: attached,
                limits: attached_limits,
            } => {
                attached.validate()?;
                attached_limits.validate()?;
                if attached != run || *attached_limits != limits || attachment.is_some() {
                    return Err(SupervisorError::InvalidState(
                        "runtime run attachment is foreign, changed, or duplicated".into(),
                    ));
                }
                attachment = Some((*attached_limits, record.recorded_at));
            }
            JournalEvent::AttemptReserved(reservation) if reservation.run.is_some() => {
                let Some(attached) = reservation.run.as_ref() else {
                    return Err(SupervisorError::InvalidState(
                        "runtime reservation lost its run".into(),
                    ));
                };
                if attached != run || attachment.is_none() {
                    return Err(SupervisorError::InvalidState(
                        "runtime reservation is foreign or precedes its run attachment".into(),
                    ));
                }
                validate_recovered_reservation(reservation, config, run, plan)?;
                if attempts
                    .insert(
                        reservation.reservation_id.clone(),
                        RecoveredAttempt {
                            reservation: reservation.clone(),
                            phase: RecoveredPhase::Reserved,
                            durable: false,
                            cancelled_before_io: false,
                        },
                    )
                    .is_some()
                {
                    return Err(SupervisorError::InvalidState(
                        "runtime reservation identity is duplicated".into(),
                    ));
                }
            }
            JournalEvent::RuntimeIoStarted { reservation_id } => {
                let attempt = attempts.get_mut(reservation_id).ok_or_else(|| {
                    SupervisorError::InvalidState(
                        "runtime I/O start references an unknown reservation".into(),
                    )
                })?;
                if !matches!(attempt.phase, RecoveredPhase::Reserved)
                    || attempt.cancelled_before_io
                    || attempt.durable
                {
                    return Err(SupervisorError::InvalidState(
                        "runtime I/O start is duplicated or out of order".into(),
                    ));
                }
                attempt.phase = RecoveredPhase::IoStarted;
            }
            JournalEvent::LocalDurabilityRecorded { reservation_id, .. }
            | JournalEvent::AttemptAbandoned { reservation_id, .. } => {
                if let Some(attempt) = attempts.get_mut(reservation_id) {
                    if attempt.durable
                        || attempt.cancelled_before_io
                        || !matches!(attempt.phase, RecoveredPhase::IoStarted)
                    {
                        return Err(SupervisorError::InvalidState(
                            "runtime durability is duplicated or out of order".into(),
                        ));
                    }
                    attempt.durable = true;
                }
            }
            JournalEvent::AttemptCancelledBeforeIo { reservation_id } => {
                let attempt = attempts.get_mut(reservation_id).ok_or_else(|| {
                    SupervisorError::InvalidState(
                        "runtime pre-I/O cancellation references an unknown reservation".into(),
                    )
                })?;
                if attempt.durable
                    || attempt.cancelled_before_io
                    || !matches!(attempt.phase, RecoveredPhase::Reserved)
                {
                    return Err(SupervisorError::InvalidState(
                        "runtime pre-I/O cancellation is duplicated or out of order".into(),
                    ));
                }
                attempt.cancelled_before_io = true;
            }
            JournalEvent::RuntimeBudgetSettled {
                reservation_id,
                usage,
                disposition,
                violation,
            } => {
                let attempt = attempts.get_mut(reservation_id).ok_or_else(|| {
                    SupervisorError::InvalidState(
                        "runtime settlement references an unknown reservation".into(),
                    )
                })?;
                let claim = attempt.reservation.execution_claim.ok_or_else(|| {
                    SupervisorError::InvalidState(
                        "runtime settlement reservation lost its claim".into(),
                    )
                })?;
                validate_recovered_settlement(
                    attempt.phase,
                    attempt.durable,
                    attempt.cancelled_before_io,
                    claim,
                    *usage,
                    *disposition,
                    *violation,
                )?;
                attempt.phase = RecoveredPhase::Settled {
                    usage: *usage,
                    disposition: *disposition,
                    violation: *violation,
                };
            }
            JournalEvent::GenerationStopped {
                source_key,
                operation_key,
                generation,
                ..
            } => {
                stopped_generations.insert((
                    source_key.clone(),
                    operation_key.clone(),
                    *generation,
                ));
            }
            _ => {}
        }
    }
    Ok(RecoveredJournal {
        attachment,
        attempts,
        stopped_generations,
    })
}

/// Wave 5's foreground C0 runtime. It is deliberately not a live-provider client: source plans
/// beyond sealed synthetic C0 refuse before a budget or attempt reservation is created.
pub struct CollectorRuntime {
    config: CollectorRuntimeConfigV1,
    run: Wave5RunReferenceV1,
    supervisor: Supervisor,
    budget: BudgetLedger,
    process_started_monotonic_ms: u64,
    prior_wall_elapsed_ms: u64,
    outstanding: BTreeMap<crate::BudgetPermitId, OutstandingRuntimeAttempt>,
    previous: BTreeMap<(SourceKey, OperationKey), AttemptReservation>,
    terminal: bool,
}

impl CollectorRuntime {
    /// Open and recover one exact no-network runtime occurrence.
    ///
    /// The run registration, configuration, and execution-accounting documents are all separate
    /// exact byte strings. This avoids a self-referential configuration digest. C0 accepts an
    /// exact local registration; live promotion later requires the durable store receipt too.
    ///
    /// # Errors
    ///
    /// Refuses changed/uncanonical documents, a non-C0 plan, run/plan substitution, changed same-
    /// run attachment, corrupt budget lifecycle, or any unresolved restart state.
    #[allow(clippy::too_many_lines)] // Recovery ordering is intentionally visible in one entrypoint.
    pub fn open(
        documents: RuntimeDocumentSet<'_>,
        mut supervisor: Supervisor,
        plan: &ValidatedProviderRunPlan,
        at: UtcTimestamp,
        monotonic_ms: u64,
    ) -> Result<Self> {
        let (_, run, config, budget_document) = documents.parse_and_close()?;
        validate_plan_binding(&config, &run, plan)?;
        if plan.built_in_execution() != BuiltInExecutionDisposition::SyntheticEnabled {
            return Err(SupervisorError::ProviderDisabledPendingCanonicalAdmission);
        }
        validate_execution_limits(budget_document.limits, plan)?;
        // Full read-only replay validation precedes every recovery write. A forged/out-of-order
        // journal is therefore refused without a cancellation, gap, or settlement side effect.
        let preflight = scan_runtime_journal(
            supervisor.journal_records(),
            &config,
            &run,
            budget_document.limits,
            plan,
        )?;
        let reserved_without_io: Vec<_> = preflight
            .attempts
            .values()
            .filter(|attempt| {
                matches!(attempt.phase, RecoveredPhase::Reserved)
                    && !attempt.cancelled_before_io
                    && !attempt.durable
            })
            .map(|attempt| attempt.reservation.clone())
            .collect();
        for reservation in reserved_without_io {
            supervisor.cancel_before_io(&reservation, at)?;
        }
        supervisor.reconcile_startup(at)?;
        let recovered = scan_runtime_journal(
            supervisor.journal_records(),
            &config,
            &run,
            budget_document.limits,
            plan,
        )?;
        let mut stopped_generations = recovered.stopped_generations;
        let attempts = recovered.attempts;
        let attached_at = if let Some((_, value)) = recovered.attachment {
            value
        } else {
            supervisor.append_runtime_event(
                at,
                JournalEvent::RuntimeRunAttached {
                    run: run.clone(),
                    limits: budget_document.limits,
                },
            )?;
            at
        };
        let prior_wall_elapsed_ms = elapsed_ms(attached_at, at)?;
        let mut budget = BudgetLedger::new(budget_document.limits, 0)?;
        let mut had_prior_attempts = false;
        for attempt in attempts.values() {
            let Some(attached) = &attempt.reservation.run else {
                continue;
            };
            if attached.run_id != run.run_id {
                continue;
            }
            had_prior_attempts = true;
            let claim = attempt.reservation.execution_claim.ok_or_else(|| {
                SupervisorError::InvalidState("runtime reservation lost its execution claim".into())
            })?;
            if let RecoveredPhase::Settled {
                usage,
                disposition,
                violation,
            } = attempt.phase
            {
                // The disposition was already validated against exact journal order and claim.
                budget.restore_consumed(usage, violation)?;
                let generation_key = (
                    attempt.reservation.source_key.clone(),
                    attempt.reservation.operation_key.clone(),
                    attempt.reservation.generation,
                );
                if !stopped_generations.contains(&generation_key) {
                    let reason = if disposition == RuntimeSettlementDisposition::TerminalViolation
                        || violation.is_some()
                    {
                        "recovered_runtime_terminal_violation"
                    } else {
                        "runtime_restart_replay_only"
                    };
                    supervisor.stop_generation_with_downtime(
                        &attempt.reservation,
                        OpenVariant::known(reason)?,
                        at,
                    )?;
                    stopped_generations.insert(generation_key);
                }
                continue;
            }
            let started = matches!(attempt.phase, RecoveredPhase::IoStarted);
            let usage = if attempt.cancelled_before_io {
                zero_usage()
            } else {
                maximum_usage(claim)
            };
            let disposition = if attempt.cancelled_before_io {
                RuntimeSettlementDisposition::RefundedBeforeIo
            } else if started {
                RuntimeSettlementDisposition::RecoveredAfterIoWorstCase
            } else {
                return Err(SupervisorError::InvalidState(
                    "reserved runtime attempt was not cancelled before recovery".into(),
                ));
            };
            supervisor.append_runtime_event(
                at,
                JournalEvent::RuntimeBudgetSettled {
                    reservation_id: attempt.reservation.reservation_id.clone(),
                    usage,
                    disposition,
                    violation: None,
                },
            )?;
            budget.restore_consumed(usage, None)?;
            let generation_key = (
                attempt.reservation.source_key.clone(),
                attempt.reservation.operation_key.clone(),
                attempt.reservation.generation,
            );
            if !stopped_generations.contains(&generation_key) {
                if attempt.cancelled_before_io {
                    supervisor.stop_generation_without_gap(
                        &attempt.reservation,
                        OpenVariant::known("cancelled_before_provider_io")?,
                        at,
                    )?;
                } else {
                    supervisor.stop_generation_with_downtime(
                        &attempt.reservation,
                        OpenVariant::known("runtime_restart_replay_only")?,
                        at,
                    )?;
                }
                stopped_generations.insert(generation_key);
            }
        }
        let budget_terminal = budget
            .snapshot(prior_wall_elapsed_ms)
            .terminal_violation
            .is_some();
        Ok(Self {
            config,
            run,
            supervisor,
            budget,
            process_started_monotonic_ms: monotonic_ms,
            prior_wall_elapsed_ms,
            outstanding: BTreeMap::new(),
            previous: BTreeMap::new(),
            terminal: had_prior_attempts || budget_terminal,
        })
    }

    #[must_use]
    pub fn supervisor(&self) -> &Supervisor {
        &self.supervisor
    }

    /// Execute one pure-plan → durable reservation → I/O-start → result → durable settlement
    /// transition.
    ///
    /// # Errors
    ///
    /// Refuses terminal state, any runner/config/run mismatch, budget exhaustion, adapter loss,
    /// durability failure, or usage overrun. Errors after I/O are charged conservatively and
    /// create a durable gap whenever the control reserve remains available.
    #[allow(clippy::too_many_lines)] // The pre-I/O/durability sequence must remain linearly auditable.
    pub fn run_one(
        &mut self,
        runner: &mut dyn ProviderRunner,
        adapter: &mut SyntheticRuntimeOutcomeAdapter,
        at: UtcTimestamp,
        monotonic_ms: u64,
    ) -> Result<Option<RuntimeStepReport>> {
        if self.terminal {
            return Err(SupervisorError::InvalidState(
                "runtime is terminal after a prior boundary failure".into(),
            ));
        }
        validate_plan_binding(&self.config, &self.run, runner.validated_plan())?;
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next()? else {
            return Ok(None);
        };
        let attempt = *attempt;
        if let Err(error) = self.validate_attempt(&attempt, runner.validated_plan()) {
            runner.cancel_planned(&attempt)?;
            return Err(error);
        }
        let claim = execution_claim(&attempt.maximum_cost, runner.validated_plan())?;
        let effective_monotonic = self.effective_monotonic(monotonic_ms)?;
        let budget_permit = match self.budget.reserve(claim, effective_monotonic) {
            Ok(value) => value,
            Err(error) => {
                runner.cancel_planned(&attempt)?;
                return Err(error);
            }
        };
        let reservation = match self.reserve_attempt(&attempt, claim, at) {
            Ok(value) => value,
            Err(error) => {
                // `Supervisor::reserve` may have fsynced AttemptReserved and then failed health
                // persistence. The error alone cannot prove no durable reservation exists.
                self.terminal = true;
                let _ = runner.cancel_planned(&attempt);
                return Err(error);
            }
        };
        let permit_id = budget_permit.id();
        self.outstanding.insert(
            permit_id,
            OutstandingRuntimeAttempt {
                reservation: reservation.clone(),
                budget: budget_permit,
            },
        );
        let provider_permit = match ProviderAttemptPermit::bind_reservation_identity_unverified(
            &attempt,
            reservation.reservation_id.as_str(),
        ) {
            Ok(value) => value,
            Err(error) => {
                // Binding is still provably pre-I/O. Refund only after the cancellation itself is
                // durable; otherwise retain the hold and become replay-only.
                if runner.cancel_planned(&attempt).is_err()
                    || self.supervisor.cancel_before_io(&reservation, at).is_err()
                {
                    self.terminal = true;
                    return Err(error.into());
                }
                let outstanding = self.outstanding.remove(&permit_id).ok_or_else(|| {
                    self.terminal = true;
                    SupervisorError::InvalidState(
                        "runtime execution permit disappeared during pre-I/O cancellation".into(),
                    )
                })?;
                if let Err(cleanup) = self.budget.cancel_before_io(outstanding.budget) {
                    self.terminal = true;
                    return Err(cleanup);
                }
                return Err(error.into());
            }
        };
        if let Err(error) = self.supervisor.append_runtime_event(
            at,
            JournalEvent::RuntimeIoStarted {
                reservation_id: reservation.reservation_id.clone(),
            },
        ) {
            self.terminal = true;
            let _ = runner.cancel_planned(&attempt);
            return Err(error);
        }

        let report = match runner.execute(provider_permit) {
            Ok(value) => value,
            Err(error) => {
                let _ = self.finish_after_io_error(
                    permit_id,
                    OpenVariant::known("provider_runner_error")?,
                    at,
                );
                self.terminal = true;
                return Err(error.into());
            }
        };
        if let Err(error) = validate_report(&attempt, &reservation, &report) {
            let _ = self.finish_after_io_error(
                permit_id,
                OpenVariant::known("provider_report_mismatch")?,
                at,
            );
            self.terminal = true;
            return Err(error);
        }
        let mut usage = match usage_from_port(&report.actual_usage) {
            Ok(value) => value,
            Err(error) => {
                let _ = self.finish_after_io_error(
                    permit_id,
                    OpenVariant::known("provider_usage_invalid")?,
                    at,
                );
                self.terminal = true;
                return Err(error);
            }
        };
        if usage.requests != claim.requests || usage.pages != claim.pages {
            let _ = self.finish_after_io_error(
                permit_id,
                OpenVariant::known("provider_usage_underreported")?,
                at,
            );
            self.terminal = true;
            return Err(SupervisorError::InvalidValue(
                "started C0 attempt must report its exact reserved request and page counts".into(),
            ));
        }
        let progress = progress_kind(&report.outcome);
        let item = match adapter.prepare(&reservation, report.outcome) {
            Ok(value) if value.reservation == reservation => value,
            Ok(_) => {
                let _ = self.finish_after_io_error(
                    permit_id,
                    OpenVariant::known("adapter_reservation_mismatch")?,
                    at,
                );
                self.terminal = true;
                return Err(SupervisorError::InvalidState(
                    "runtime adapter changed the exact reservation".into(),
                ));
            }
            Err(error) => {
                let _ = self.finish_after_io_error(
                    permit_id,
                    OpenVariant::known("runtime_adapter_refused")?,
                    at,
                );
                self.terminal = true;
                return Err(error);
            }
        };
        let (receipt, actual_progress) = match self.supervisor.try_enqueue(item) {
            Ok(()) => {
                let receipt = match self.supervisor.drain_one(at) {
                    Ok(Some(value)) => value,
                    Ok(None) => {
                        self.terminal = true;
                        return Err(SupervisorError::InvalidState(
                            "runtime item disappeared before durability".into(),
                        ));
                    }
                    Err(error) => {
                        self.terminal = true;
                        return Err(error);
                    }
                };
                (receipt, progress)
            }
            Err(item) => match self.supervisor.stop_saturated(item, at) {
                Ok(receipt) => (receipt, RuntimeProgressKind::SaturationGap),
                Err(error) => {
                    self.terminal = true;
                    return Err(error);
                }
            },
        };
        usage.durable_bytes = match parse_wire_u64(&receipt.exact_segment.byte_length) {
            Ok(value) => value,
            Err(error) => {
                self.terminal = true;
                let _ = self.supervisor.stop_generation_with_downtime(
                    &reservation,
                    OpenVariant::known("runtime_receipt_invalid")?,
                    at,
                );
                return Err(error);
            }
        };
        self.settle(permit_id, usage, RuntimeSettlementDisposition::Observed, at)?;
        self.previous.insert(
            (
                reservation.source_key.clone(),
                reservation.operation_key.clone(),
            ),
            reservation.clone(),
        );
        Ok(Some(RuntimeStepReport {
            run_id: self.run.run_id.clone(),
            reservation_id: reservation.reservation_id,
            source_key: reservation.source_key,
            operation_key: reservation.operation_key,
            generation: reservation.generation,
            attempt_ordinal: reservation.attempt_ordinal,
            progress: actual_progress,
            usage,
            local_spool: receipt,
            authority: crate::AUTHORITY_CEILING.into(),
        }))
    }

    /// Run the finite C0 scenario to completion, durably close its finite generation without a
    /// gap, then request runner shutdown.
    ///
    /// # Errors
    ///
    /// Refuses any failed attempt transition, changed completion binding, runner shutdown error,
    /// or supervisor durability failure.
    pub fn run_to_completion(
        &mut self,
        runner: &mut dyn ProviderRunner,
        adapter: &mut SyntheticRuntimeOutcomeAdapter,
        mut at: UtcTimestamp,
        mut monotonic_ms: u64,
    ) -> Result<RuntimeRunReport> {
        let mut steps = Vec::new();
        loop {
            if let Some(step) = self.run_one(runner, adapter, at, monotonic_ms)? {
                steps.push(step);
                monotonic_ms = monotonic_ms.saturating_add(1);
                at = add_milliseconds(at, 1)?;
                continue;
            }
            match runner.plan_next()? {
                ProviderRunnerNext::Finished(completion) => {
                    validate_completion(
                        &self.config,
                        &self.run,
                        runner.validated_plan().plan_digest(),
                        &completion,
                    )?;
                    // A finite, completed C0 page has no open stream interval. Mark its
                    // generation terminal before the generic supervisor shutdown so that
                    // shutdown does not manufacture a downtime gap after successfully captured
                    // finite work. Any failure to durably mark that terminal boundary leaves the
                    // runtime replay-only rather than permitting another execution.
                    let completed = self.previous.values().next().cloned().ok_or_else(|| {
                        SupervisorError::InvalidState(
                            "finite C0 completion has no durably settled reservation".into(),
                        )
                    })?;
                    if self.previous.len() != 1 {
                        self.terminal = true;
                        return Err(SupervisorError::InvalidState(
                            "sealed C0 completion has more than one reservation".into(),
                        ));
                    }
                    if let Err(error) = self.supervisor.stop_generation_without_gap(
                        &completed,
                        OpenVariant::known("finite_c0_completed")?,
                        at,
                    ) {
                        self.terminal = true;
                        return Err(error);
                    }
                    if let Err(error) = runner.request_shutdown() {
                        self.terminal = true;
                        return Err(error.into());
                    }
                    let shutdown = match self.supervisor.shutdown(at) {
                        Ok(value) => value,
                        Err(error) => {
                            self.terminal = true;
                            return Err(error);
                        }
                    };
                    self.terminal = true;
                    return Ok(RuntimeRunReport {
                        run_id: self.run.run_id.clone(),
                        plan_id: self.config.plan_id.clone(),
                        plan_digest: runner.validated_plan().plan_digest().to_owned(),
                        completion: completion.reason,
                        steps,
                        budget: self
                            .budget
                            .snapshot(self.effective_monotonic(monotonic_ms)?),
                        shutdown,
                        authority: crate::AUTHORITY_CEILING.into(),
                    });
                }
                ProviderRunnerNext::Attempt(attempt) => {
                    runner.cancel_planned(&attempt)?;
                    return Err(SupervisorError::InvalidState(
                        "runner changed from finished back to an attempt".into(),
                    ));
                }
            }
        }
    }

    fn validate_attempt(
        &self,
        attempt: &ProviderAttemptPlan,
        plan: &ValidatedProviderRunPlan,
    ) -> Result<()> {
        let association = &attempt.association;
        if association.run_id != self.run.run_id
            || association.registration_digest != self.run.exact_registration.digest.as_str()
            || association.plan_id != self.config.plan_id
            || association.plan_template_digest != self.config.plan_template_digest
            || association.plan_template_digest != plan.plan_template_digest()
            || association.plan_digest != plan.plan_digest()
            || association.generation != 1
            || association.attempt_ordinal == 0
            || !matches!(attempt.source_id, SourceId::Other(_))
        {
            return Err(SupervisorError::InvalidValue(
                "provider attempt does not match the exact C0 run/plan/generation".into(),
            ));
        }
        Ok(())
    }

    fn reserve_attempt(
        &mut self,
        attempt: &ProviderAttemptPlan,
        claim: AttemptBudgetClaim,
        at: UtcTimestamp,
    ) -> Result<AttemptReservation> {
        let source_key = SourceKey::new(attempt.association.source_key.clone())?;
        let operation_key = OperationKey::new(attempt.association.method_key.clone())?;
        let key = (source_key.clone(), operation_key.clone());
        let reservation = if attempt.association.attempt_ordinal == 1 {
            self.supervisor.reserve(
                ReservationRequest {
                    source_key,
                    operation_key,
                    kind: AttemptKind::Poll,
                    scope: CoverageScope {
                        source_id: domain_source_id(&attempt.source_id)?,
                        family: OpenVariant::known(attempt.coverage_family.clone())?,
                        subject: Some(StableString::new(self.config.plan_id.clone())?),
                    },
                    lower: Boundary::Wall { value: at },
                    protection: ProtectionProfile::PublicIntegrity {
                        domain: ProtectionDomainId::new(attempt.protection_domain.clone())?,
                    },
                    run: Some(self.run.clone()),
                    execution_claim: Some(claim),
                    provider_plan: Some(ProviderPlanReferenceV1 {
                        plan_id: attempt.association.plan_id.clone(),
                        plan_template_digest: attempt.association.plan_template_digest.clone(),
                        plan_digest: attempt.association.plan_digest.clone(),
                    }),
                },
                at,
            )?
        } else {
            let previous = self.previous.get(&key).ok_or_else(|| {
                SupervisorError::InvalidState(
                    "runner attempt ordinal has no resolved predecessor".into(),
                )
            })?;
            self.supervisor.reserve_retry(previous, at)?
        };
        if reservation.generation.get() != attempt.association.generation
            || reservation.attempt_ordinal != attempt.association.attempt_ordinal
            || reservation.execution_claim != Some(claim)
            || reservation.run.as_ref() != Some(&self.run)
            || reservation.provider_plan
                != Some(ProviderPlanReferenceV1 {
                    plan_id: attempt.association.plan_id.clone(),
                    plan_template_digest: attempt.association.plan_template_digest.clone(),
                    plan_digest: attempt.association.plan_digest.clone(),
                })
        {
            return Err(SupervisorError::InvalidState(
                "durable supervisor reservation disagrees with the pure provider plan".into(),
            ));
        }
        Ok(reservation)
    }

    fn settle(
        &mut self,
        permit_id: crate::BudgetPermitId,
        usage: AttemptBudgetUsage,
        disposition: RuntimeSettlementDisposition,
        at: UtcTimestamp,
    ) -> Result<()> {
        let outstanding = self.outstanding.get(&permit_id).ok_or_else(|| {
            SupervisorError::InvalidState("runtime execution permit is absent".into())
        })?;
        let reservation = outstanding.reservation.clone();
        let violation = self
            .budget
            .settlement_violation(&outstanding.budget, usage)?;
        let durable_disposition = if violation.is_some() {
            RuntimeSettlementDisposition::TerminalViolation
        } else {
            disposition
        };
        if let Err(error) = self.supervisor.append_runtime_event(
            at,
            JournalEvent::RuntimeBudgetSettled {
                reservation_id: reservation.reservation_id.clone(),
                usage,
                disposition: durable_disposition,
                violation,
            },
        ) {
            // The worst-case hold remains in both maps. Releasing it after an ambiguous durable
            // append would let a restart or continued process reuse paid capacity.
            self.terminal = true;
            let _ = self.supervisor.stop_generation_with_downtime(
                &reservation,
                OpenVariant::known("runtime_settlement_durability_failure")?,
                at,
            );
            return Err(error);
        }
        let outstanding = self.outstanding.remove(&permit_id).ok_or_else(|| {
            SupervisorError::InvalidState("runtime execution permit disappeared".into())
        })?;
        let settlement = self.budget.settle(outstanding.budget, usage);
        if let Err(error) = settlement {
            self.terminal = true;
            let _ = self.supervisor.stop_generation_with_downtime(
                &reservation,
                OpenVariant::known("runtime_budget_terminal_violation")?,
                at,
            );
            return Err(error);
        }
        if durable_disposition == RuntimeSettlementDisposition::TerminalViolation {
            self.terminal = true;
        }
        Ok(())
    }

    fn finish_after_io_error(
        &mut self,
        permit_id: crate::BudgetPermitId,
        reason: OpenVariant,
        at: UtcTimestamp,
    ) -> Result<()> {
        let outstanding = self.outstanding.get(&permit_id).ok_or_else(|| {
            SupervisorError::InvalidState("runtime execution permit is absent".into())
        })?;
        let receipt = self
            .supervisor
            .abandon_and_stop(&outstanding.reservation, reason, at)?;
        let mut usage = maximum_usage(outstanding.budget.claim());
        usage.durable_bytes = usage
            .durable_bytes
            .max(parse_wire_u64(&receipt.exact_segment.byte_length)?);
        self.settle(
            permit_id,
            usage,
            RuntimeSettlementDisposition::TerminalViolation,
            at,
        )
    }

    fn effective_monotonic(&self, monotonic_ms: u64) -> Result<u64> {
        let process_elapsed = monotonic_ms
            .checked_sub(self.process_started_monotonic_ms)
            .ok_or_else(|| {
                SupervisorError::InvalidState("monotonic clock moved backward".into())
            })?;
        self.prior_wall_elapsed_ms
            .checked_add(process_elapsed)
            .ok_or_else(|| SupervisorError::InvalidState("runtime elapsed clock overflow".into()))
    }
}

fn validate_plan_binding(
    config: &CollectorRuntimeConfigV1,
    run: &Wave5RunReferenceV1,
    plan: &ValidatedProviderRunPlan,
) -> Result<()> {
    let plan_value = plan.plan();
    if plan_value.run.run_id != run.run_id
        || plan_value.run.registration_digest != run.exact_registration.digest.as_str()
        || plan_value.plan_id != config.plan_id
        || plan.plan_template_digest() != config.plan_template_digest
        || plan.operations().len() != 1
    {
        return Err(SupervisorError::InvalidConfig(
            "provider plan does not close the exact run/configuration".into(),
        ));
    }
    Ok(())
}

fn validate_recovered_reservation(
    reservation: &AttemptReservation,
    config: &CollectorRuntimeConfigV1,
    run: &Wave5RunReferenceV1,
    plan: &ValidatedProviderRunPlan,
) -> Result<()> {
    let claim = reservation.execution_claim.ok_or_else(|| {
        SupervisorError::InvalidState("runtime reservation lost its execution claim".into())
    })?;
    claim.validate()?;
    let reference = reservation.provider_plan.as_ref().ok_or_else(|| {
        SupervisorError::InvalidState("runtime reservation lost its provider plan".into())
    })?;
    reference.validate()?;
    let operation = plan
        .operations()
        .first()
        .ok_or_else(|| SupervisorError::InvalidState("sealed C0 plan lost its operation".into()))?;
    let expected_claim = execution_claim(&operation.plan.attempt_cost, plan)?;
    if reservation.run.as_ref() != Some(run)
        || reference.plan_id != config.plan_id
        || reference.plan_template_digest != config.plan_template_digest
        || reference.plan_template_digest != plan.plan_template_digest()
        || reference.plan_digest != plan.plan_digest()
        || reservation.source_key.as_str() != operation.plan.source_key
        || reservation.operation_key.as_str() != operation.plan.method_key
        || reservation.generation.get() != operation.plan.generation
        || claim != expected_claim
    {
        return Err(SupervisorError::InvalidState(
            "runtime reservation does not close the exact run, plan, operation, and claim".into(),
        ));
    }
    Ok(())
}

fn validate_execution_limits(
    limits: crate::RunBudgetLimits,
    plan: &ValidatedProviderRunPlan,
) -> Result<()> {
    let cap = &plan.plan().hard_cap;
    let maximum_attempt_ms = plan
        .operations()
        .iter()
        .map(|operation| {
            operation
                .plan
                .attempt_cost
                .reserved_total()
                .map(|value| value.wall_millis)
        })
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .max()
        .unwrap_or(0);
    if limits.maximum_requests != cap.requests
        || limits.maximum_pages != cap.pages
        || limits.maximum_ingress_bytes != cap.ingress_bytes
        || limits.maximum_durable_bytes != cap.durable_bytes
        || limits.maximum_provider_credits != cap.provider_credits
        || limits.maximum_elapsed_ms != plan.plan().max_elapsed_ms
        || limits.maximum_in_flight_attempts != u64::from(plan.plan().max_in_flight_attempts)
        || limits.maximum_ingress_bytes_per_second != plan.plan().max_ingress_bytes_per_second
        || limits.maximum_in_flight_elapsed_overshoot_ms < maximum_attempt_ms
    {
        return Err(SupervisorError::InvalidConfig(
            "execution-accounting document disagrees with the sealed provider plan".into(),
        ));
    }
    Ok(())
}

fn execution_claim(
    cost: &RuntimeAttemptCostPort,
    plan: &ValidatedProviderRunPlan,
) -> Result<AttemptBudgetClaim> {
    let maximum = cost.reserved_total()?;
    if !maximum.provider_currency_minor.is_empty() || !maximum.chain_native_atoms.is_empty() {
        return Err(SupervisorError::InvalidValue(
            "C0 attempt cannot carry economic spend".into(),
        ));
    }
    Ok(AttemptBudgetClaim {
        requests: maximum.requests,
        pages: maximum.pages,
        maximum_ingress_bytes: maximum.ingress_bytes,
        maximum_durable_bytes: maximum.durable_bytes,
        maximum_provider_credits: maximum.provider_credits,
        maximum_ingress_bytes_per_second: plan.plan().max_ingress_bytes_per_second,
        maximum_elapsed_ms: maximum.wall_millis,
    })
}

fn usage_from_port(value: &RuntimeBudgetPort) -> Result<AttemptBudgetUsage> {
    if !value.provider_currency_minor.is_empty() || !value.chain_native_atoms.is_empty() {
        return Err(SupervisorError::InvalidValue(
            "C0 actual use cannot carry economic spend".into(),
        ));
    }
    Ok(AttemptBudgetUsage {
        requests: value.requests,
        pages: value.pages,
        ingress_bytes: value.ingress_bytes,
        durable_bytes: value.durable_bytes,
        provider_credits: value.provider_credits,
        elapsed_ms: value.wall_millis,
    })
}

fn maximum_usage(claim: AttemptBudgetClaim) -> AttemptBudgetUsage {
    AttemptBudgetUsage {
        requests: claim.requests,
        pages: claim.pages,
        ingress_bytes: claim.maximum_ingress_bytes,
        durable_bytes: claim.maximum_durable_bytes,
        provider_credits: claim.maximum_provider_credits,
        elapsed_ms: claim.maximum_elapsed_ms,
    }
}

const fn zero_usage() -> AttemptBudgetUsage {
    AttemptBudgetUsage {
        requests: 0,
        pages: 0,
        ingress_bytes: 0,
        durable_bytes: 0,
        provider_credits: 0,
        elapsed_ms: 0,
    }
}

fn validate_recovered_settlement(
    phase: RecoveredPhase,
    durable: bool,
    cancelled_before_io: bool,
    claim: AttemptBudgetClaim,
    usage: AttemptBudgetUsage,
    disposition: RuntimeSettlementDisposition,
    violation: Option<BudgetDimension>,
) -> Result<()> {
    if matches!(phase, RecoveredPhase::Settled { .. }) {
        return Err(SupervisorError::InvalidState(
            "runtime budget settlement identity is duplicated".into(),
        ));
    }
    let before_io = matches!(phase, RecoveredPhase::Reserved);
    let maximum = maximum_usage(claim);
    let within = usage.requests <= claim.requests
        && usage.pages <= claim.pages
        && usage.ingress_bytes <= claim.maximum_ingress_bytes
        && usage.durable_bytes <= claim.maximum_durable_bytes
        && usage.provider_credits <= claim.maximum_provider_credits
        && usage.elapsed_ms <= claim.maximum_elapsed_ms;
    let valid = match disposition {
        RuntimeSettlementDisposition::RefundedBeforeIo => {
            before_io
                && cancelled_before_io
                && !durable
                && violation.is_none()
                && usage == zero_usage()
        }
        RuntimeSettlementDisposition::RecoveredBeforeIo => false,
        RuntimeSettlementDisposition::Observed => {
            !before_io
                && !cancelled_before_io
                && durable
                && violation.is_none()
                && usage.requests == claim.requests
                && usage.pages == claim.pages
                && within
        }
        RuntimeSettlementDisposition::RecoveredAfterIoWorstCase => {
            !before_io && !cancelled_before_io && durable && violation.is_none() && usage == maximum
        }
        RuntimeSettlementDisposition::TerminalViolation => {
            !before_io
                && !cancelled_before_io
                && durable
                && usage.requests >= claim.requests
                && usage.pages >= claim.pages
                && (usage == maximum || violation.is_some())
        }
    };
    if !valid {
        return Err(SupervisorError::InvalidState(
            "runtime settlement contradicts its durable lifecycle or claim".into(),
        ));
    }
    Ok(())
}

fn progress_kind(outcome: &ProviderAttemptOutcome) -> RuntimeProgressKind {
    match outcome {
        ProviderAttemptOutcome::Captured { .. } => RuntimeProgressKind::Captured,
        ProviderAttemptOutcome::BoundedEmpty { .. } => RuntimeProgressKind::BoundedEmpty,
        ProviderAttemptOutcome::Unavailable { .. } => RuntimeProgressKind::Unavailable,
        ProviderAttemptOutcome::Gap { .. } => RuntimeProgressKind::Gap,
    }
}

fn validate_report(
    attempt: &ProviderAttemptPlan,
    reservation: &AttemptReservation,
    report: &ProviderAttemptReport,
) -> Result<()> {
    if report.association != attempt.association
        || report.reservation_id != reservation.reservation_id.as_str()
    {
        return Err(SupervisorError::InvalidValue(
            "provider report changed its exact attempt association".into(),
        ));
    }
    if let ProviderAttemptOutcome::Captured { outputs } = &report.outcome
        && outputs.iter().any(|output| {
            matches!(
                output,
                joshi_sources::SourceOutput::Frame(frame) if frame.transport != Transport::Fixture
            )
        })
    {
        return Err(SupervisorError::ProviderDisabledPendingCanonicalAdmission);
    }
    Ok(())
}

fn validate_completion(
    config: &CollectorRuntimeConfigV1,
    run: &Wave5RunReferenceV1,
    plan_digest: &str,
    completion: &ProviderRunnerCompletion,
) -> Result<()> {
    if completion.run_id != run.run_id
        || completion.registration_digest != run.exact_registration.digest.as_str()
        || completion.plan_id != config.plan_id
        || completion.plan_digest != plan_digest
    {
        return Err(SupervisorError::InvalidValue(
            "provider completion changed the exact run/plan association".into(),
        ));
    }
    Ok(())
}

fn domain_source_id(source: &SourceId) -> Result<DomainSourceId> {
    let SourceId::Other(value) = source else {
        return Err(SupervisorError::ProviderDisabledPendingCanonicalAdmission);
    };
    DomainSourceId::new(format!("source.other.{value}"))
        .map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}

fn parse_wire_u64(value: &str) -> Result<u64> {
    value
        .parse()
        .map_err(|_| SupervisorError::InvalidValue("wire byte length is not a u64".into()))
}

fn elapsed_ms(lower: UtcTimestamp, upper: UtcTimestamp) -> Result<u64> {
    let nanos = (upper.as_datetime() - lower.as_datetime()).whole_nanoseconds();
    if nanos < 0 {
        return Err(SupervisorError::InvalidState(
            "runtime wall clock precedes its durable attachment".into(),
        ));
    }
    u64::try_from(nanos / 1_000_000)
        .map_err(|_| SupervisorError::InvalidState("runtime wall duration overflow".into()))
}

fn add_milliseconds(value: UtcTimestamp, milliseconds: u64) -> Result<UtcTimestamp> {
    let milliseconds = i64::try_from(milliseconds)
        .map_err(|_| SupervisorError::InvalidValue("runtime timestamp overflow".into()))?;
    let value = value
        .as_datetime()
        .checked_add(time::Duration::milliseconds(milliseconds))
        .ok_or_else(|| SupervisorError::InvalidValue("runtime timestamp overflow".into()))?;
    UtcTimestamp::new(value).map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}

fn captured_item(
    reservation: &AttemptReservation,
    outputs: Vec<SourceOutput>,
) -> Result<PendingSegment> {
    let mut observations = Vec::with_capacity(outputs.len());
    for output in outputs {
        let SourceOutput::Frame(frame) = output else {
            return Err(SupervisorError::InvalidValue(
                "sealed C0 capture admits exact fixture frames only".into(),
            ));
        };
        if frame.transport != Transport::Fixture {
            return Err(SupervisorError::ProviderDisabledPendingCanonicalAdmission);
        }
        let sequence = frame.sequence;
        let draft = joshi_sources::observation_draft(
            frame,
            EvidenceContext {
                occurrence_namespace: reservation.installation_id.clone(),
                redacted_request_fingerprint_material: format!(
                    "fixture:{}:{}",
                    reservation.source_key, reservation.operation_key
                ),
                parent_acquisition_id: None,
                locator: LogicalSourceLocator::Fixture {
                    name: format!("runtime:{}", reservation.reservation_id),
                },
                source_variant: OpenVariant::known("synthetic_runtime_frame")?,
                source_cursor: None,
                source_events: Vec::new(),
                provider_event_time: ProviderEventTime::Missing {
                    reason: "synthetic_fixture_has_no_provider_clock".into(),
                },
                chain_slot: None,
                transaction_index: None,
                instruction_path: Vec::new(),
                log_index: None,
                finality: None,
                acquisition_started_at: reservation.reserved_at,
                requested_at: Some(reservation.reserved_at),
                monotonic_clock_id: format!("runtime:{}", reservation.installation_id),
                acquisition_started_monotonic_ns: sequence.saturating_mul(1_000),
                received_monotonic_ns: sequence.saturating_mul(1_000).saturating_add(1),
                persisted_at: reservation.reserved_at,
            },
        )?;
        let EvidenceDraft::Observation(observation) = draft else {
            return Err(SupervisorError::InvalidState(
                "fixture frame did not produce an observation".into(),
            ));
        };
        observations.push(observation);
    }
    if observations.is_empty() {
        return Err(SupervisorError::InvalidValue(
            "captured progress requires a fixture frame".into(),
        ));
    }
    evidence_item(
        reservation,
        DurableIngestBatch {
            contract_version: StableString::new(
                joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION,
            )?,
            batch_id: StableString::new(format!("batch:{}", reservation.reservation_id))?,
            expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))?,
            observations,
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            cursor_advances: Vec::new(),
        },
    )
}

fn bounded_empty_item(
    reservation: &AttemptReservation,
    lower: joshi_sources::UnixMillis,
    upper: joshi_sources::UnixMillis,
    proof_contract: &str,
) -> Result<PendingSegment> {
    if proof_contract != "synthetic_bounded_scenario.v1" || lower >= upper {
        return Err(SupervisorError::InvalidValue(
            "bounded-empty proof is not the sealed C0 contract".into(),
        ));
    }
    let lower = unix_millis_to_utc(lower)?;
    let upper = unix_millis_to_utc(upper)?;
    evidence_item(
        reservation,
        DurableIngestBatch {
            contract_version: StableString::new(
                joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION,
            )?,
            batch_id: StableString::new(format!("batch:{}", reservation.reservation_id))?,
            expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))?,
            observations: Vec::new(),
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: vec![CoverageWindow {
                coverage_id: CoverageId::new(format!("coverage:{}", reservation.reservation_id))?,
                scope: reservation.scope.clone(),
                lower: Boundary::Wall { value: lower },
                upper: Some(Boundary::Wall { value: upper }),
                state: OpenVariant::known("bounded_empty_source_contract")?,
                available_at: upper,
            }],
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            cursor_advances: Vec::new(),
        },
    )
}

fn evidence_item(
    reservation: &AttemptReservation,
    mut batch: DurableIngestBatch,
) -> Result<PendingSegment> {
    batch.expected_digest = joshi_store::SqliteStore::canonical_batch_digest(&batch)
        .map_err(|error| SupervisorError::InvalidValue(error.to_string()))?;
    let policy = br#"{"observationStorage":{"fixture":"public_source"},"coverageGapSeverity":{"synthetic":"informational"}}"#.to_vec();
    let entry = EvidenceBatchEntry::from_batch(&batch, "joshi.store.policy.v1", policy, None)?;
    PendingSegment::new(
        reservation.clone(),
        SpoolEntry::EvidenceBatch(entry),
        QueueClass::Evidence,
    )
}

fn gap_item(
    reservation: &AttemptReservation,
    at: joshi_sources::UnixMillis,
    reason: String,
) -> Result<PendingSegment> {
    let upper = unix_millis_to_utc(at)?;
    PendingSegment::new(
        reservation.clone(),
        SpoolEntry::Gap(GapRecord {
            gap_id: format!("gap-runtime-{}", reservation.reservation_id),
            scope: reservation.scope.clone(),
            lower: reservation.lower.clone(),
            upper: Some(Boundary::Wall { value: upper }),
            reason: OpenVariant::unknown(reason)?,
            detected_at: upper,
            related_segment_id: None,
        }),
        QueueClass::Control,
    )
}

fn unix_millis_to_utc(value: joshi_sources::UnixMillis) -> Result<UtcTimestamp> {
    let nanos = i128::from(value.0)
        .checked_mul(1_000_000)
        .ok_or_else(|| SupervisorError::InvalidValue("UnixMillis overflow".into()))?;
    let value = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| SupervisorError::InvalidValue("UnixMillis is outside UTC range".into()))?;
    UtcTimestamp::new(value).map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{FaultInjector, FaultPoint, QueueLimits, RetryPolicy, SupervisorConfig};
    use joshi_admission::{
        operational::ExactByteClosureV1,
        wave5::{
            ExactRegisteredDocumentV1, ExecutionAccountingDocumentV1,
            WAVE5_RUN_REGISTRATION_CONTRACT, Wave5RunReferenceV1, Wave5RunRegistrationV1,
        },
    };
    use joshi_sources::{
        CanaryProfilePort, PROVIDER_RUN_PLAN_PORT_VERSION, ProviderOperationPlan,
        ProviderRunPlanTemplate, RegisteredRunPort, RuntimeAttemptCostPort,
        validate_provider_run_plan,
    };
    use joshi_spool::{SpoolConfig, SpoolEntry};
    use std::{
        collections::BTreeMap,
        path::Path,
        sync::{
            Arc,
            atomic::{AtomicBool, AtomicUsize, Ordering},
        },
        time::Duration,
    };

    const SOURCE_TREE: &[u8] = br#"{"contract":"joshi.wave5.source_tree_manifest","schemaVersion":1,"repositoryId":"joshi","head":{"kind":"unborn"},"dirty":true,"workingTreeDigest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","diffDigest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","authority":"read_only_no_execution"}"#;
    const BUILD: &[u8] = br#"{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"runtime-test","sourceTreeDigest":"sha256:75ca191ce724554d183a05b6f7e381686291b29376e42cf4494e8be840f21012","rustcVersion":"rustc-test","targetTriple":"test-target","profile":"local_debug","authority":"read_only_no_execution"}"#;
    const PRIVACY: &[u8] = br#"{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"runtime-public-only","permittedProtectionClasses":["public_integrity"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":false,"authority":"read_only_no_execution"}"#;
    const SURFACE_FILE: &[u8] =
        include_bytes!("../../../fixtures/surface/daily_use_surface_profile_v1.json");

    struct ExactRuntimeDocuments {
        registration: Vec<u8>,
        configuration: Vec<u8>,
        budget: Vec<u8>,
        surface: Vec<u8>,
    }

    impl ExactRuntimeDocuments {
        fn set(&self) -> RuntimeDocumentSet<'_> {
            RuntimeDocumentSet {
                exact_registration: &self.registration,
                exact_build: BUILD,
                exact_source_tree: SOURCE_TREE,
                exact_configuration: &self.configuration,
                exact_budget: &self.budget,
                exact_privacy: PRIVACY,
                exact_daily_use_surface_profile: &self.surface,
            }
        }
    }

    fn at() -> UtcTimestamp {
        "2026-08-18T12:00:00.000000Z".parse().expect("timestamp")
    }

    fn exact_document(id: &str, bytes: &[u8]) -> ExactRegisteredDocumentV1 {
        ExactRegisteredDocumentV1 {
            document_id: id.to_owned(),
            exact_bytes: ExactByteClosureV1::new(bytes).expect("exact closure"),
        }
    }

    fn runtime_fixture() -> (ExactRuntimeDocuments, ValidatedProviderRunPlan) {
        let hard_cap = RuntimeBudgetPort {
            requests: 1,
            pages: 1,
            ingress_bytes: 1024 * 1024,
            durable_bytes: 8 * 1024 * 1024,
            provider_credits: 0,
            wall_millis: 1_000,
            provider_currency_minor: BTreeMap::new(),
            chain_native_atoms: BTreeMap::new(),
        };
        let template = ProviderRunPlanTemplate {
            port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
            plan_id: "runtime-c0-fixture".to_owned(),
            profile: CanaryProfilePort::C0,
            hard_cap: hard_cap.clone(),
            max_elapsed_ms: 1_000,
            max_ingress_bytes_per_second: None,
            max_in_flight_attempts: 1,
            operations: vec![ProviderOperationPlan {
                source_key: "synthetic.local".to_owned(),
                method_key: "emit".to_owned(),
                operation: ProviderOperation::SyntheticEmit,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::SyntheticScenario {
                    scenario_id: "runtime-walk".to_owned(),
                },
                attempt_cost: RuntimeAttemptCostPort {
                    worst_case: hard_cap.clone(),
                    max_overshoot: RuntimeBudgetPort::default(),
                },
            }],
        };
        let template_digest = template.plan_template_digest().expect("template digest");
        let configuration = CollectorRuntimeConfigV1 {
            contract: "joshi.collector.runtime_config.v1".to_owned(),
            schema_version: 1,
            plan_id: "runtime-c0-fixture".to_owned(),
            plan_template_digest: template_digest,
            status_endpoint: crate::LocalStatusEndpoint {
                address: "127.0.0.1".parse().expect("loopback"),
                port: 19_441,
            },
            provider_execution: crate::ProviderExecutionMode::OfflineFixtureOnly,
            authority: crate::AUTHORITY_CEILING.to_owned(),
        }
        .canonical_bytes()
        .expect("configuration");
        let budget = ExecutionAccountingDocumentV1 {
            contract: "joshi.collector.execution_accounting.v1".to_owned(),
            schema_version: 1,
            limits: crate::RunBudgetLimits {
                maximum_requests: hard_cap.requests,
                maximum_pages: hard_cap.pages,
                maximum_ingress_bytes: hard_cap.ingress_bytes,
                maximum_durable_bytes: hard_cap.durable_bytes,
                maximum_provider_credits: 0,
                maximum_ingress_bytes_per_second: None,
                maximum_elapsed_ms: 1_000,
                maximum_in_flight_attempts: 1,
                maximum_in_flight_elapsed_overshoot_ms: 1_000,
            },
            authority: crate::AUTHORITY_CEILING.to_owned(),
        }
        .canonical_bytes()
        .expect("budget");
        let surface = SURFACE_FILE
            .strip_suffix(b"\n")
            .unwrap_or(SURFACE_FILE)
            .to_vec();
        let registration = Wave5RunRegistrationV1 {
            contract: WAVE5_RUN_REGISTRATION_CONTRACT.to_owned(),
            schema_version: 1,
            run_id: "runtime-test-run-0001".to_owned(),
            build: exact_document("build-runtime-test", BUILD),
            source_tree: exact_document("tree-runtime-test", SOURCE_TREE),
            configuration: exact_document("config-runtime-test", &configuration),
            budget: exact_document("budget-runtime-test", &budget),
            privacy: exact_document("privacy-runtime-test", PRIVACY),
            daily_use_surface_profile: exact_document("surface-runtime-test", &surface),
            authority: crate::AUTHORITY_CEILING.to_owned(),
        };
        let registration_bytes = registration.canonical_bytes().expect("registration");
        let run = Wave5RunReferenceV1::from_registration(&registration, &registration_bytes)
            .expect("run reference");
        let plan = validate_provider_run_plan(template.bind_run(RegisteredRunPort {
            run_id: run.run_id,
            registration_digest: run.exact_registration.digest.as_str().to_owned(),
        }))
        .expect("validated plan");
        (
            ExactRuntimeDocuments {
                registration: registration_bytes,
                configuration,
                budget,
                surface,
            },
            plan,
        )
    }

    fn supervisor_config(root: &Path) -> SupervisorConfig {
        SupervisorConfig {
            root: root.to_path_buf(),
            spool: SpoolConfig {
                root: root.join("spool"),
                max_segment_bytes: 16 * 1024 * 1024,
                max_entries_per_segment: 32,
                max_total_bytes: 64 * 1024 * 1024,
                control_reserve_bytes: 1024 * 1024,
                max_transfer_chunk_bytes: 4096,
            },
            queue: QueueLimits {
                maximum_records: 8,
                maximum_bytes: 16 * 1024 * 1024,
                control_reserve_records: 2,
                control_reserve_bytes: 1024 * 1024,
            },
            retry: RetryPolicy {
                maximum_attempts_per_generation: 2,
                base_delay: Duration::from_millis(1),
                maximum_delay: Duration::from_millis(10),
            },
            shutdown_deadline: Duration::from_secs(1),
            maximum_spool_bytes_per_utc_day: 60 * 1024 * 1024,
        }
    }

    fn open_runtime(
        root: &Path,
        docs: &ExactRuntimeDocuments,
        plan: &ValidatedProviderRunPlan,
    ) -> CollectorRuntime {
        let supervisor = Supervisor::open(supervisor_config(root)).expect("supervisor");
        CollectorRuntime::open(docs.set(), supervisor, plan, at(), 0).expect("runtime")
    }

    #[test]
    fn sealed_json_helper_refuses_malformed_bytes() {
        let (_, plan) = runtime_fixture();
        assert!(matches!(
            synthetic_c0_json_runner(plan, b"{".to_vec(), at()),
            Err(SupervisorError::InvalidValue(message))
                if message.contains("malformed")
        ));
    }

    #[test]
    fn final_plan_run_substitution_refuses_even_when_the_template_digest_matches() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let mut substituted = plan.plan().clone();
        // The template explicitly excludes this field, so this is the adversarial case the
        // final plan digest/run binding must catch rather than treating a template match as
        // execution permission.
        substituted.run.run_id = "different-runtime-test-run".to_owned();
        let substituted = validate_provider_run_plan(substituted).expect("sealed C0 plan");
        assert_eq!(
            substituted.plan_template_digest(),
            plan.plan_template_digest()
        );
        assert_ne!(substituted.plan_digest(), plan.plan_digest());

        let supervisor = Supervisor::open(supervisor_config(root.path())).expect("supervisor");
        assert!(matches!(
            CollectorRuntime::open(docs.set(), supervisor, &substituted, at(), 0),
            Err(SupervisorError::InvalidConfig(message))
                if message.contains("exact run/configuration")
        ));
    }

    #[test]
    fn happy_c0_orders_reservation_before_io_and_reopen_refuses_fresh_runner() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let mut runtime = open_runtime(root.path(), &docs, &plan);
        let mut runner = synthetic_c0_json_runner(plan.clone(), br#"{"ok":true}"#.to_vec(), at())
            .expect("runner");
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        let report = runtime
            .run_to_completion(&mut runner, &mut adapter, at(), 0)
            .expect("finite C0 run");
        assert_eq!(report.steps.len(), 1);
        assert_eq!(report.steps[0].usage.requests, 1);
        assert_eq!(report.shutdown.downtime_gaps, 0);
        assert_eq!(
            runtime
                .supervisor()
                .completed_no_gap_reservations_for_run(&report.run_id)
                .expect("completed reservation readback"),
            runtime
                .supervisor()
                .reservations_for_run(&report.run_id)
                .expect("reservation readback")
        );
        assert_eq!(
            runtime
                .supervisor()
                .reservations_for_run(&report.run_id)
                .expect("reservation readback"),
            vec![
                runtime
                    .supervisor()
                    .journal_records()
                    .iter()
                    .find_map(|record| match &record.event {
                        JournalEvent::AttemptReserved(value) => Some(value.clone()),
                        _ => None,
                    })
                    .expect("journal reservation")
            ]
        );
        let records = runtime.supervisor.journal_records();
        let reserved = records
            .iter()
            .position(|record| matches!(record.event, JournalEvent::AttemptReserved(_)))
            .expect("reservation");
        let io = records
            .iter()
            .position(|record| matches!(record.event, JournalEvent::RuntimeIoStarted { .. }))
            .expect("I/O start");
        let durable = records
            .iter()
            .position(|record| matches!(record.event, JournalEvent::LocalDurabilityRecorded { .. }))
            .expect("durability");
        let settled = records
            .iter()
            .position(|record| matches!(record.event, JournalEvent::RuntimeBudgetSettled { .. }))
            .expect("settlement");
        assert!(reserved < io && io < durable && durable < settled);
        let source_gap_count = records
            .iter()
            .filter(|record| {
                matches!(record.event, JournalEvent::AttemptAbandoned { .. })
                    || matches!(
                        record.event,
                        JournalEvent::GenerationStopped {
                            gap_segment: Some(_),
                            ..
                        }
                    )
            })
            .count();
        assert_eq!(
            source_gap_count, 0,
            "completed finite C0 must not open a gap"
        );
        drop(runtime);

        let mut reopened = open_runtime(root.path(), &docs, &plan);
        let reopened_source_gap_count = reopened
            .supervisor
            .journal_records()
            .iter()
            .filter(|record| {
                matches!(record.event, JournalEvent::AttemptAbandoned { .. })
                    || matches!(
                        record.event,
                        JournalEvent::GenerationStopped {
                            gap_segment: Some(_),
                            ..
                        }
                    )
            })
            .count();
        assert_eq!(reopened_source_gap_count, source_gap_count);
        let mut fresh =
            synthetic_c0_json_runner(plan, br#"{"ok":true}"#.to_vec(), at()).expect("fresh runner");
        assert!(matches!(
            reopened.run_one(&mut fresh, &mut adapter, at(), 0),
            Err(SupervisorError::InvalidState(message)) if message.contains("terminal")
        ));
    }

    #[test]
    fn exact_fixture_batch_refuses_a_different_captured_frame_before_positive_durability() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let run_id = plan.plan().run.run_id.clone();
        let mut runtime = open_runtime(root.path(), &docs, &plan);
        let mut batch = DurableIngestBatch {
            contract_version: StableString::new(
                joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION,
            )
            .expect("contract"),
            batch_id: StableString::new("batch:exact-fixture-mismatch").expect("batch"),
            expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))
                .expect("placeholder"),
            observations: Vec::new(),
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            cursor_advances: Vec::new(),
        };
        batch.expected_digest =
            joshi_store::SqliteStore::canonical_batch_digest(&batch).expect("digest");
        let exact_batch_bytes = serde_json::to_vec(&batch).expect("batch bytes");
        let mut adapter = SyntheticRuntimeOutcomeAdapter::for_exact_fixture_batch(
            br#"{"expected":true}"#.to_vec(),
            batch,
            exact_batch_bytes,
            "joshi.test.exact_fixture_policy.v1",
            br#"{"retention":"public"}"#.to_vec(),
        )
        .expect("adapter");
        let mut runner =
            synthetic_c0_json_runner(plan, br#"{"actual":true}"#.to_vec(), at()).expect("runner");
        assert!(matches!(
            runtime.run_to_completion(&mut runner, &mut adapter, at(), 0),
            Err(SupervisorError::InvalidValue(message))
                if message.contains("differs from the exact fixture batch ingress")
        ));
        assert!(
            runtime
                .supervisor()
                .completed_no_gap_reservations_for_run(&run_id)
                .is_err()
        );
    }

    fn reserve_without_execution(
        runtime: &mut CollectorRuntime,
        runner: &mut SyntheticProviderRunner,
        mark_io_started: bool,
    ) -> AttemptReservation {
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().expect("pure plan") else {
            panic!("expected attempt")
        };
        let claim = execution_claim(&attempt.maximum_cost, runner.validated_plan()).expect("claim");
        let permit = runtime.budget.reserve(claim, 0).expect("budget permit");
        let reservation = runtime
            .reserve_attempt(&attempt, claim, at())
            .expect("durable reservation");
        runtime.outstanding.insert(
            permit.id(),
            OutstandingRuntimeAttempt {
                reservation: reservation.clone(),
                budget: permit,
            },
        );
        if mark_io_started {
            runtime
                .supervisor
                .append_runtime_event(
                    at(),
                    JournalEvent::RuntimeIoStarted {
                        reservation_id: reservation.reservation_id.clone(),
                    },
                )
                .expect("I/O marker");
        }
        reservation
    }

    #[test]
    fn two_reopens_refund_reserved_before_io_without_fabricating_source_gap() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let mut runtime = open_runtime(root.path(), &docs, &plan);
        let mut runner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let reservation = reserve_without_execution(&mut runtime, &mut runner, false);
        drop(runtime);

        let reopened = open_runtime(root.path(), &docs, &plan);
        let records = reopened.supervisor.journal_records();
        assert!(records.iter().any(|record| matches!(
            &record.event,
            JournalEvent::AttemptCancelledBeforeIo { reservation_id }
                if reservation_id == &reservation.reservation_id
        )));
        assert!(records.iter().any(|record| matches!(
            &record.event,
            JournalEvent::RuntimeBudgetSettled {
                reservation_id,
                usage,
                disposition: RuntimeSettlementDisposition::RefundedBeforeIo,
                violation: None,
            } if reservation_id == &reservation.reservation_id && *usage == zero_usage()
        )));
        assert!(!records.iter().any(|record| matches!(
            &record.event,
            JournalEvent::AttemptAbandoned { reservation_id, .. }
                if reservation_id == &reservation.reservation_id
        )));
        assert!(
            reopened
                .supervisor()
                .completed_no_gap_reservations_for_run(
                    reservation.run.as_ref().expect("run").run_id.as_str()
                )
                .is_err()
        );
        drop(reopened);
        let second = open_runtime(root.path(), &docs, &plan);
        assert!(second.terminal);
    }

    #[test]
    fn two_reopens_charge_io_started_worst_case_after_durable_gap() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let mut runtime = open_runtime(root.path(), &docs, &plan);
        let mut runner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let reservation = reserve_without_execution(&mut runtime, &mut runner, true);
        let claim = reservation.execution_claim.expect("claim");
        drop(runtime);

        let reopened = open_runtime(root.path(), &docs, &plan);
        let records = reopened.supervisor.journal_records();
        let gap = records
            .iter()
            .position(|record| {
                matches!(
                    &record.event,
                    JournalEvent::AttemptAbandoned { reservation_id, .. }
                        if reservation_id == &reservation.reservation_id
                )
            })
            .expect("crash gap");
        let settled = records
            .iter()
            .position(|record| matches!(
                &record.event,
                JournalEvent::RuntimeBudgetSettled {
                    reservation_id,
                    usage,
                    disposition: RuntimeSettlementDisposition::RecoveredAfterIoWorstCase,
                    ..
                } if reservation_id == &reservation.reservation_id && *usage == maximum_usage(claim)
            ))
            .expect("worst-case settlement");
        assert!(gap < settled);
        assert!(
            reopened
                .supervisor()
                .completed_no_gap_reservations_for_run(
                    reservation.run.as_ref().expect("run").run_id.as_str()
                )
                .is_err()
        );
        drop(reopened);
        let second = open_runtime(root.path(), &docs, &plan);
        assert!(second.terminal);
    }

    #[test]
    fn replay_settlement_state_machine_rejects_reordering_and_underreporting() {
        let claim = AttemptBudgetClaim {
            requests: 1,
            pages: 1,
            maximum_ingress_bytes: 10,
            maximum_durable_bytes: 10,
            maximum_provider_credits: 0,
            maximum_ingress_bytes_per_second: None,
            maximum_elapsed_ms: 10,
        };
        assert!(
            validate_recovered_settlement(
                RecoveredPhase::Reserved,
                false,
                false,
                claim,
                maximum_usage(claim),
                RuntimeSettlementDisposition::Observed,
                None,
            )
            .is_err()
        );
        assert!(
            validate_recovered_settlement(
                RecoveredPhase::IoStarted,
                true,
                false,
                claim,
                AttemptBudgetUsage {
                    requests: 0,
                    pages: 0,
                    ..maximum_usage(claim)
                },
                RuntimeSettlementDisposition::TerminalViolation,
                Some(BudgetDimension::Requests),
            )
            .is_err()
        );
        assert!(
            validate_recovered_settlement(
                RecoveredPhase::Reserved,
                false,
                true,
                claim,
                zero_usage(),
                RuntimeSettlementDisposition::RefundedBeforeIo,
                None,
            )
            .is_ok()
        );
    }

    #[test]
    fn forged_durability_before_io_refuses_before_recovery_mutates_journal() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let mut runtime = open_runtime(root.path(), &docs, &plan);
        let mut runner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let reservation = reserve_without_execution(&mut runtime, &mut runner, false);
        runtime
            .supervisor
            .abandon(
                &reservation,
                OpenVariant::known("forged_before_io").unwrap(),
                at(),
            )
            .expect("construct adversarial durable order");
        drop(runtime);

        let supervisor = Supervisor::open(supervisor_config(root.path())).expect("reopen");
        let events = root.path().join("journal/events");
        let before = std::fs::read_dir(&events).expect("events").count();
        assert!(matches!(
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0),
            Err(SupervisorError::InvalidState(message)) if message.contains("out of order")
        ));
        let after = std::fs::read_dir(&events).expect("events").count();
        assert_eq!(after, before);
    }

    #[derive(Default)]
    struct ArmedJournalFault {
        remaining: AtomicUsize,
    }

    impl ArmedJournalFault {
        fn arm(&self, calls: usize) {
            self.remaining.store(calls, Ordering::SeqCst);
        }
    }

    impl FaultInjector for ArmedJournalFault {
        fn check(&self, point: FaultPoint) -> Result<()> {
            if point == FaultPoint::AfterJournalTemporarySync {
                let remaining = self.remaining.load(Ordering::SeqCst);
                if remaining > 0
                    && remaining != usize::MAX
                    && self.remaining.fetch_sub(1, Ordering::SeqCst) == 1
                {
                    return Err(SupervisorError::Injected(point));
                }
            }
            Ok(())
        }
    }

    struct CancelRefusingRunner {
        inner: SyntheticProviderRunner,
    }

    impl ProviderRunner for CancelRefusingRunner {
        fn validated_plan(&self) -> &ValidatedProviderRunPlan {
            self.inner.validated_plan()
        }

        fn plan_next(
            &mut self,
        ) -> std::result::Result<ProviderRunnerNext, joshi_sources::ProviderRunnerError> {
            self.inner.plan_next()
        }

        fn execute(
            &mut self,
            permit: ProviderAttemptPermit,
        ) -> std::result::Result<ProviderAttemptReport, joshi_sources::ProviderRunnerError>
        {
            self.inner.execute(permit)
        }

        fn cancel_planned(
            &mut self,
            _attempt: &ProviderAttemptPlan,
        ) -> std::result::Result<(), joshi_sources::ProviderRunnerError> {
            Err(joshi_sources::ProviderRunnerError::NoPendingAttempt)
        }

        fn request_shutdown(
            &mut self,
        ) -> std::result::Result<(), joshi_sources::ProviderRunnerError> {
            self.inner.request_shutdown()
        }
    }

    #[test]
    fn io_start_append_and_runner_cancel_failure_still_terminalize_and_hold() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let faults = Arc::new(ArmedJournalFault {
            remaining: AtomicUsize::new(usize::MAX),
        });
        let supervisor = Supervisor::open_with_faults(
            supervisor_config(root.path()),
            BTreeMap::new(),
            faults.clone(),
        )
        .expect("supervisor");
        let mut runtime =
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0).expect("runtime");
        let inner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let mut runner = CancelRefusingRunner { inner };
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        faults.arm(2);
        assert!(matches!(
            runtime.run_one(&mut runner, &mut adapter, at(), 0),
            Err(SupervisorError::Injected(
                FaultPoint::AfterJournalTemporarySync
            ))
        ));
        assert!(runtime.terminal);
        assert_eq!(runtime.outstanding.len(), 1);
        assert!(runtime.budget.has_outstanding_permits());
        drop(runtime);

        let recovered = open_runtime(root.path(), &docs, &plan);
        assert!(recovered.terminal);
        assert!(
            recovered
                .supervisor
                .journal_records()
                .iter()
                .any(|record| matches!(
                    record.event,
                    JournalEvent::RuntimeBudgetSettled {
                        disposition: RuntimeSettlementDisposition::RecoveredAfterIoWorstCase,
                        ..
                    }
                ))
        );
    }

    struct OneShotFault {
        point: FaultPoint,
        armed: AtomicBool,
    }

    impl OneShotFault {
        fn new(point: FaultPoint) -> Self {
            Self {
                point,
                armed: AtomicBool::new(false),
            }
        }

        fn arm(&self) {
            self.armed.store(true, Ordering::SeqCst);
        }
    }

    impl FaultInjector for OneShotFault {
        fn check(&self, point: FaultPoint) -> Result<()> {
            if point == self.point && self.armed.swap(false, Ordering::SeqCst) {
                Err(SupervisorError::Injected(point))
            } else {
                Ok(())
            }
        }
    }

    #[test]
    fn ambiguous_reservation_health_failure_is_terminal_and_replay_refunds() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let faults = Arc::new(OneShotFault::new(FaultPoint::AfterHealthTemporarySync));
        let supervisor = Supervisor::open_with_faults(
            supervisor_config(root.path()),
            BTreeMap::new(),
            faults.clone(),
        )
        .expect("supervisor");
        let mut runtime =
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0).expect("runtime");
        let mut runner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        faults.arm();
        assert!(matches!(
            runtime.run_one(&mut runner, &mut adapter, at(), 0),
            Err(SupervisorError::Injected(
                FaultPoint::AfterHealthTemporarySync
            ))
        ));
        assert!(runtime.terminal);
        assert!(runtime.budget.has_outstanding_permits());
        drop(runtime);

        let recovered = open_runtime(root.path(), &docs, &plan);
        assert!(recovered.terminal);
        assert!(
            recovered
                .supervisor
                .journal_records()
                .iter()
                .any(|record| matches!(
                    record.event,
                    JournalEvent::RuntimeBudgetSettled {
                        disposition: RuntimeSettlementDisposition::RefundedBeforeIo,
                        ..
                    }
                ))
        );
    }

    #[test]
    fn saturation_gap_append_failure_is_terminal_and_restart_charges_worst_case() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let faults = Arc::new(OneShotFault::new(FaultPoint::AfterLocalSpoolAppend));
        let mut config = supervisor_config(root.path());
        config.queue.maximum_bytes = 4_096;
        config.queue.control_reserve_bytes = 1_024;
        let supervisor =
            Supervisor::open_with_faults(config.clone(), BTreeMap::new(), faults.clone())
                .expect("supervisor");
        let mut runtime =
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0).expect("runtime");
        let runner = synthetic_c0_json_runner(plan.clone(), vec![b' '; 8_192], at());
        assert!(runner.is_err(), "spaces are not a JSON fixture");
        let body = serde_json::to_vec(&"x".repeat(8_192)).expect("large JSON string");
        let mut runner = synthetic_c0_json_runner(plan.clone(), body, at()).expect("runner");
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        faults.arm();
        assert!(matches!(
            runtime.run_one(&mut runner, &mut adapter, at(), 0),
            Err(SupervisorError::Injected(FaultPoint::AfterLocalSpoolAppend))
        ));
        assert!(runtime.terminal);
        assert_eq!(runtime.outstanding.len(), 1);
        assert!(runtime.budget.has_outstanding_permits());
        drop(runtime);

        let supervisor = Supervisor::open(config).expect("reopen");
        let recovered =
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0).expect("recover");
        assert!(recovered.terminal);
        assert!(
            recovered
                .supervisor
                .journal_records()
                .iter()
                .any(|record| matches!(
                    record.event,
                    JournalEvent::RuntimeBudgetSettled {
                        disposition: RuntimeSettlementDisposition::RecoveredAfterIoWorstCase,
                        ..
                    }
                ))
        );
    }

    #[test]
    fn settlement_append_failure_retains_hold_then_recovery_repairs_terminal_stop() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let faults = Arc::new(ArmedJournalFault {
            remaining: AtomicUsize::new(usize::MAX),
        });
        let supervisor = Supervisor::open_with_faults(
            supervisor_config(root.path()),
            BTreeMap::new(),
            faults.clone(),
        )
        .expect("supervisor");
        let mut runtime =
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0).expect("runtime");
        let mut runner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        faults.arm(4);
        assert!(matches!(
            runtime.run_one(&mut runner, &mut adapter, at(), 0),
            Err(SupervisorError::Injected(
                FaultPoint::AfterJournalTemporarySync
            ))
        ));
        assert!(runtime.terminal);
        assert_eq!(runtime.outstanding.len(), 1);
        assert!(runtime.budget.has_outstanding_permits());
        drop(runtime);

        let recovered = open_runtime(root.path(), &docs, &plan);
        assert!(recovered.terminal);
        assert!(
            recovered
                .supervisor
                .journal_records()
                .iter()
                .any(|record| matches!(record.event, JournalEvent::GenerationStopped { .. }))
        );
    }

    #[test]
    fn local_durability_journal_failure_reopens_from_exact_evidence_without_a_false_gap() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let faults = Arc::new(ArmedJournalFault {
            remaining: AtomicUsize::new(usize::MAX),
        });
        let supervisor = Supervisor::open_with_faults(
            supervisor_config(root.path()),
            BTreeMap::new(),
            faults.clone(),
        )
        .expect("supervisor");
        let mut runtime =
            CollectorRuntime::open(docs.set(), supervisor, &plan, at(), 0).expect("runtime");
        let mut runner = synthetic_c0_json_runner(plan.clone(), b"{}".to_vec(), at()).unwrap();
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        // Reservation, I/O-start, then the local-durability journal append. The spool segment
        // has already been sealed when this third append is interrupted.
        faults.arm(3);
        assert!(matches!(
            runtime.run_one(&mut runner, &mut adapter, at(), 0),
            Err(SupervisorError::Injected(
                FaultPoint::AfterJournalTemporarySync
            ))
        ));
        assert!(runtime.terminal);
        assert!(runtime.budget.has_outstanding_permits());
        drop(runtime);

        let recovered = open_runtime(root.path(), &docs, &plan);
        assert!(recovered.terminal);
        let records = recovered.supervisor.journal_records();
        assert!(
            records
                .iter()
                .any(|record| matches!(record.event, JournalEvent::LocalDurabilityRecorded { .. }))
        );
        assert!(records.iter().any(|record| matches!(
            record.event,
            JournalEvent::RuntimeBudgetSettled {
                disposition: RuntimeSettlementDisposition::RecoveredAfterIoWorstCase,
                ..
            }
        )));
        assert!(
            !records
                .iter()
                .any(|record| matches!(record.event, JournalEvent::AttemptAbandoned { .. }))
        );
    }

    #[test]
    fn gap_adapter_preserves_reason_and_binds_exact_coverage() {
        let root = tempfile::tempdir().expect("tempdir");
        let (docs, plan) = runtime_fixture();
        let mut runtime = open_runtime(root.path(), &docs, &plan);
        let mut runner = synthetic_c0_json_runner(plan, b"{}".to_vec(), at()).unwrap();
        let reservation = reserve_without_execution(&mut runtime, &mut runner, false);
        let mut adapter = SyntheticRuntimeOutcomeAdapter::new();
        let long_reason = "r".repeat(400);
        let unavailable = adapter
            .prepare(
                &reservation,
                ProviderAttemptOutcome::Unavailable {
                    at: UnixMillis(1),
                    reason: long_reason.clone(),
                },
            )
            .expect("bounded unavailable reason");
        let SpoolEntry::Gap(unavailable) = unavailable.entry else {
            panic!("expected gap")
        };
        assert!(
            unavailable
                .reason
                .discriminator
                .as_str()
                .ends_with(&long_reason)
        );

        let coverage = vec![joshi_sources::CoverageEvent::GapOpened {
            source: SourceId::Other("synthetic_local".to_owned()),
            connection_epoch: 1,
            at: UnixMillis(1),
            after_cursor: None,
            reason: "wire_loss".to_owned(),
        }];
        let first = adapter
            .prepare(
                &reservation,
                ProviderAttemptOutcome::Gap {
                    at: UnixMillis(1),
                    reason: "disconnect".to_owned(),
                    coverage: coverage.clone(),
                },
            )
            .expect("gap one");
        let second = adapter
            .prepare(
                &reservation,
                ProviderAttemptOutcome::Gap {
                    at: UnixMillis(1),
                    reason: "disconnect".to_owned(),
                    coverage: vec![joshi_sources::CoverageEvent::GapOpened {
                        source: SourceId::Other("synthetic_local".to_owned()),
                        connection_epoch: 2,
                        at: UnixMillis(1),
                        after_cursor: None,
                        reason: "wire_loss".to_owned(),
                    }],
                },
            )
            .expect("gap two");
        let (SpoolEntry::Gap(first), SpoolEntry::Gap(second)) = (first.entry, second.entry) else {
            panic!("expected gaps")
        };
        assert!(first.reason.discriminator.as_str().contains("disconnect"));
        assert_ne!(first.reason, second.reason);
    }
}
