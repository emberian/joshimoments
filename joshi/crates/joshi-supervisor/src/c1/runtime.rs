//! The C1 state machine: one durably ordered read, one journal family, and then a stop.
//!
//! [`C1Runtime`] is the only thing in this crate that can cause a provider request, and it can
//! cause exactly one. It consumes the non-cloneable [`DisabledC1RuntimeAdmission`] by value, binds
//! it to a journal record, and then walks a fixed order in which every durable fact precedes the
//! act it authorises. It takes no endpoint, no executor, no callback, and no runner: the transport
//! it uses is the crate-private `c1::transport::C1Transport`, whose endpoint and method are
//! compiled in. That transport is deliberately not part of the published surface: a public path
//! to it would let any downstream crate mint request-capable values with no admission, journal
//! binding, budget permit, or one-read cap.
//!
//! # The order, and why every step is where it is
//!
//! ```text
//! open:      C1ActivationBound
//! run_once:  C1AttemptReserved -> C1RequestPrepared -> C1IoStarted -> request
//!                              -> C1RawDurabilityRecorded -> C1BudgetSettled -> C1Stopped
//! ```
//!
//! `C1ActivationBound` is what makes the phrase "the burned claim is bound to this journal" true
//! rather than aspirational: before it is fsynced there is no durable trace that an admission ever
//! happened, so "claim burned and admitted" and "claim burned and never admitted" would be
//! indistinguishable after a crash. It is also the record that enforces the global cap: [`open`]
//! refuses if the journal already carries one.
//!
//! [`open`]: C1Runtime::open
//!
//! `C1IoStarted` is the irreversible boundary. Every failure at or after it is terminal for this
//! generation: no retry ever, an explicit durable gap where one can be stated, conservative
//! *maximum* settlement rather than observed use, and a stopped generation. A failure strictly
//! before it may cancel and refund, and only then, because replay can prove I/O did not start.
//!
//! # One read per installation, ever
//!
//! The store's one-shot claim is per *activation*, not global: a second run registration with
//! byte-identical configuration mints a fresh activation and a fresh burnable claim for the same
//! wallet and budget, and nothing in the store caps the total. The durable supervisor journal is
//! per installation and is the layer that actually gates I/O, so the global cap lives here:
//! [`C1Runtime::open`] scans the journal and refuses if any `C1ActivationBound` record exists.
//! That refusal is unconditional and survives restart, because it is a property of bytes on disk
//! rather than of process state.
//!
//! # What a finished run is, and is not
//!
//! [`C1RunReport`] is an account of one acquisition. It is not evidence, and nothing downstream
//! may treat it as authority. In particular a completed run establishes no coverage window, no
//! cursor advance, no absence, and no finality: an empty `result` array means one public endpoint
//! listed no rows for one request at one moment, and a row's `confirmationStatus` is a retained
//! provider claim. The retained observation this path produces carries none of those things, and
//! [`super::evidence`] offers no way to add them.
//!
//! # Replay
//!
//! [`scan_c1_journal`] is a C1-only reader. It ignores every C0 record, exactly as the C0 scanner
//! in `crate::runtime` ignores every C1 record, and it refuses a duplicated or out-of-order C1
//! record rather than repairing it. [`reconcile_c1_restart`] is the only restart path, and it
//! holds no transport at all: it can settle, gap, and stop, and it cannot request.
//!
//! The ceiling for every artifact produced here is [`crate::AUTHORITY_CEILING`].

use serde::Serialize;
use sha2::{Digest as _, Sha256};

use joshi_admission::wave5::Wave5RunReferenceV1;
use joshi_domain::{OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp};
use joshi_evidence::{Boundary, CoverageScope};
use joshi_sources::{
    BuiltInExecutionDisposition, CanaryProfilePort, ProviderOperation, ProviderScopePort,
    PublicSolanaC1Outcome, RuntimeBudgetPort, UnixMillis, ValidatedProviderRunPlan,
    canonical_public_solana_c1_request, parse_provider_run_plan_exact, read_public_solana_c1_frame,
};
use joshi_spool::ProtectionDomainId;

use crate::{
    AttemptBudgetClaim, AttemptBudgetUsage, AttemptKind, AttemptReservation, BudgetLedger,
    BudgetPermit, DisabledC1RuntimeAdmission, JournalEvent, JournalRecord, LocalSpoolReceiptV1,
    OperationKey, ProtectionProfile, ProviderPlanReferenceV1, ReservationRequest, Result,
    RunBudgetLimits, RuntimeSettlementDisposition, SourceKey, Supervisor, SupervisorError,
};

use super::{
    C1_CONTRACT_VERSION, C1_OPERATION_KEY, C1_SOURCE_KEY,
    evidence::C1RawObservationAdapter,
    physical_size::{C1_MAX_RESPONSE_BODY_BYTES, C1PhysicalBoundV1, c1_physical_bound},
    transport::{C1RawResponse, C1Transport, C1TransportError},
};

/// Structural classification of the one retained response, from the shared wire contract.
///
/// This says which shape the pure conformance reader recognised and nothing more. Neither variant
/// is absence, coverage, or a finality fact, and a refusal is not a transport failure: it is a
/// well-formed answer that declined.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum C1ResponseShape {
    /// A structurally conforming page of unverified raw provider claims. It may hold zero rows,
    /// which means this one request listed nothing and never that the wallet is inactive.
    Page,
    /// A typed JSON-RPC refusal. The provider declined; nothing was learned about the wallet.
    ProviderRefusal,
}

/// A read-only account of one completed C1 acquisition.
///
/// Every field describes how the one request was made and made durable. Nothing here is evidence,
/// coverage, absence, a cursor, or a finality fact, and no consumer may treat it as authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct C1RunReport {
    /// Durable contract version for this report shape.
    pub contract: String,
    /// The journal installation the burned activation was bound to.
    pub installation_id: String,
    /// The consumed activation's identity.
    pub activation_id: String,
    /// The registered run identity the activation closed over.
    pub run_id: String,
    /// The one fsynced attempt identity.
    pub reservation_id: String,
    /// The registry source key of the one admitted source.
    pub source_key: String,
    /// The registry method key of the one admitted method.
    pub operation_key: String,
    /// The one-shot generation, always its first.
    pub generation: u64,
    /// The attempt ordinal within that generation, always 1.
    pub attempt_ordinal: u64,
    /// SHA-256 of the endpoint string that was contacted. Never the endpoint itself.
    pub endpoint_digest: String,
    /// SHA-256 of the exact request body. Never the body itself.
    pub request_body_digest: String,
    /// Exact request body length in bytes.
    pub request_body_byte_length: u64,
    /// The admitted response ceiling this run ran under.
    pub maximum_response_bytes: u64,
    /// The proven physical local-segment ceiling implied by that response ceiling.
    pub maximum_segment_bytes: u64,
    /// The strict whole-request deadline in milliseconds.
    pub deadline_ms: u64,
    /// The observed response status.
    pub response_status: u16,
    /// Exact response entity body length in bytes.
    pub response_body_bytes: u64,
    /// SHA-256 of the exact response body. Never the body itself.
    pub response_body_digest: String,
    /// The retained response header names, after the bounded allowlist reduction.
    pub retained_header_names: Vec<String>,
    /// Which shape the shared wire contract recognised.
    pub response_shape: C1ResponseShape,
    /// Monotonically measured request duration in milliseconds.
    pub elapsed_ms: u64,
    /// The settled budget use for the one attempt.
    pub usage: AttemptBudgetUsage,
    /// How that use was settled.
    pub settlement: RuntimeSettlementDisposition,
    /// The strict local durability receipt for the one retained page.
    pub local_spool: LocalSpoolReceiptV1,
    /// The literal authority ceiling of everything in this report.
    pub authority: String,
}

/// The C1 lifecycle a journal proves, as a replay-only projection.
///
/// Every field is derived from durable records. None of it is permission: a state that shows a
/// bound activation and no I/O start is still not a licence to start one, because
/// [`C1Runtime::open`] refuses a journal carrying any bound activation at all.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
// Each flag is an independently observable durable journal fact, and a reader checks them
// independently. Collapsing them into one phase enum would assert an ordering the projection is
// specifically there to let a caller verify rather than assume.
#[allow(clippy::struct_excessive_bools)]
pub struct C1ReplayStateV1 {
    /// Durable contract version for this projection.
    pub contract: String,
    /// The bound activation's identity, if one is bound.
    pub activation_id: Option<String>,
    /// The admitted response ceiling the bound activation recorded.
    pub maximum_response_bytes: Option<u64>,
    /// The proven physical segment ceiling the bound activation recorded.
    pub maximum_segment_bytes: Option<u64>,
    /// The one fsynced attempt identity, if one was reserved.
    pub reservation_id: Option<String>,
    /// Whether the exact request was durably closed.
    pub request_prepared: bool,
    /// Whether the irreversible I/O boundary was crossed.
    pub io_started: bool,
    /// Whether one exact raw page was durably appended.
    pub raw_durability_recorded: bool,
    /// Whether the attempt was resolved as an explicit durable gap.
    pub attempt_abandoned: bool,
    /// Whether the one reserved attempt was durably settled.
    pub budget_settled: bool,
    /// How it was settled, if it was.
    pub settlement: Option<RuntimeSettlementDisposition>,
    /// Whether the one-shot generation is durably stopped.
    pub generation_stopped: bool,
    /// The literal authority ceiling of this projection.
    pub authority: String,
}

impl C1ReplayStateV1 {
    fn empty() -> Self {
        Self {
            contract: C1_CONTRACT_VERSION.to_owned(),
            activation_id: None,
            maximum_response_bytes: None,
            maximum_segment_bytes: None,
            reservation_id: None,
            request_prepared: false,
            io_started: false,
            raw_durability_recorded: false,
            attempt_abandoned: false,
            budget_settled: false,
            settlement: None,
            generation_stopped: false,
            authority: crate::AUTHORITY_CEILING.to_owned(),
        }
    }

    /// Whether the journal carries a bound C1 activation at all.
    #[must_use]
    pub const fn activation_bound(&self) -> bool {
        self.activation_id.is_some()
    }

    /// Whether the one reserved attempt is still unresolved.
    #[must_use]
    pub const fn attempt_unresolved(&self) -> bool {
        self.reservation_id.is_some() && !self.raw_durability_recorded && !self.attempt_abandoned
    }
}

/// The replay projection plus the exact reservation the journal recorded, for in-crate recovery.
struct C1Replay {
    state: C1ReplayStateV1,
    reservation: Option<AttemptReservation>,
}

/// Read the C1 lifecycle a durable journal proves, refusing a duplicated or out-of-order record.
///
/// This reader is C1-only. It ignores every C0 record through its catch-all arm, exactly as the
/// C0 scanner ignores every C1 record, so the two families cannot observe each other's work. It
/// performs no write and grants no permission.
///
/// # Errors
///
/// Every refusal is reachable and has its own case in
/// `replay_refuses_every_documented_out_of_order_or_duplicated_c1_record`, which asserts the
/// specific message rather than merely that the read failed:
///
/// 1. a second bound activation;
/// 2. a reservation before any bound activation;
/// 3. a second reservation;
/// 4. a prepared request naming a reservation this journal never reserved;
/// 5. a duplicated request closure, or one after the I/O boundary;
/// 6. an I/O start naming a reservation this journal never reserved;
/// 7. an I/O start before its request closure;
/// 8. a second I/O start;
/// 9. a durability record naming a reservation this journal never reserved;
/// 10. durability before any I/O start;
/// 11. a second attempt resolution, in each of the three orders durability and abandonment can
///     duplicate one another;
/// 12. an abandonment naming a reservation this journal never reserved;
/// 13. a settlement naming a reservation this journal never reserved;
/// 14. a second settlement;
/// 15. a stop before any bound activation;
/// 16. a second stop.
pub fn scan_c1_journal(records: &[JournalRecord]) -> Result<C1ReplayStateV1> {
    replay_c1_journal(records).map(|replay| replay.state)
}

#[allow(clippy::too_many_lines)] // The refused orderings must stay readable as one sequence.
fn replay_c1_journal(records: &[JournalRecord]) -> Result<C1Replay> {
    let mut state = C1ReplayStateV1::empty();
    let mut reservation: Option<AttemptReservation> = None;
    for record in records {
        match &record.event {
            JournalEvent::C1ActivationBound {
                activation_id,
                maximum_response_bytes,
                maximum_segment_bytes,
                ..
            } => {
                if state.activation_bound() {
                    return Err(out_of_order("a second C1 activation binding"));
                }
                state.activation_id = Some(activation_id.clone());
                state.maximum_response_bytes = Some(*maximum_response_bytes);
                state.maximum_segment_bytes = Some(*maximum_segment_bytes);
            }
            JournalEvent::C1AttemptReserved(reserved) => {
                if !state.activation_bound() {
                    return Err(out_of_order("a C1 reservation before any bound activation"));
                }
                if reservation.is_some() {
                    return Err(out_of_order("a second C1 reservation"));
                }
                state.reservation_id = Some(reserved.reservation_id.to_string());
                reservation = Some(reserved.clone());
            }
            JournalEvent::C1RequestPrepared { reservation_id, .. } => {
                require_known(
                    reservation.as_ref(),
                    reservation_id,
                    "a prepared C1 request",
                )?;
                // `state.io_started` is implied by `state.request_prepared`: the I/O-start arm
                // below refuses a start that has no closure before it, so a journal can never
                // reach an I/O start without one. The disjunct states the "late" half of the rule
                // where a reader looks for it; it is not the clause that refuses, and deleting it
                // would not widen what this reader accepts.
                if state.request_prepared || state.io_started {
                    return Err(out_of_order("a duplicated or late C1 request closure"));
                }
                state.request_prepared = true;
            }
            JournalEvent::C1IoStarted { reservation_id } => {
                require_known(reservation.as_ref(), reservation_id, "a C1 I/O start")?;
                if !state.request_prepared {
                    return Err(out_of_order("a C1 I/O start before its request closure"));
                }
                if state.io_started {
                    return Err(out_of_order("a second C1 I/O start"));
                }
                state.io_started = true;
            }
            JournalEvent::C1RawDurabilityRecorded { reservation_id, .. } => {
                require_known(
                    reservation.as_ref(),
                    reservation_id,
                    "a C1 durability record",
                )?;
                if !state.io_started {
                    return Err(out_of_order("C1 durability before any I/O start"));
                }
                if state.raw_durability_recorded || state.attempt_abandoned {
                    return Err(out_of_order("a second C1 attempt resolution"));
                }
                state.raw_durability_recorded = true;
            }
            JournalEvent::C1AttemptAbandoned { reservation_id, .. } => {
                require_known(reservation.as_ref(), reservation_id, "a C1 abandonment")?;
                if state.raw_durability_recorded || state.attempt_abandoned {
                    return Err(out_of_order("a second C1 attempt resolution"));
                }
                state.attempt_abandoned = true;
            }
            JournalEvent::C1BudgetSettled {
                reservation_id,
                disposition,
                ..
            } => {
                require_known(reservation.as_ref(), reservation_id, "a C1 settlement")?;
                if state.budget_settled {
                    return Err(out_of_order("a second C1 settlement"));
                }
                state.budget_settled = true;
                state.settlement = Some(*disposition);
            }
            JournalEvent::C1Stopped { .. } => {
                if !state.activation_bound() {
                    return Err(out_of_order("a C1 stop before any bound activation"));
                }
                if state.generation_stopped {
                    return Err(out_of_order("a second C1 stop"));
                }
                state.generation_stopped = true;
            }
            // Every C0 record is deliberately invisible here.
            _ => {}
        }
    }
    Ok(C1Replay { state, reservation })
}

fn require_known(
    reservation: Option<&AttemptReservation>,
    reservation_id: &crate::ReservationId,
    what: &str,
) -> Result<()> {
    match reservation {
        Some(value) if &value.reservation_id == reservation_id => Ok(()),
        _ => Err(out_of_order(&format!(
            "{what} naming a reservation this journal never reserved"
        ))),
    }
}

fn out_of_order(what: &str) -> SupervisorError {
    SupervisorError::InvalidState(format!("the C1 journal records {what}"))
}

/// Close out a C1 lifecycle a crash interrupted, without any possibility of a request.
///
/// This is the only restart path for C1 work, and it deliberately holds no transport: it can
/// rediscover a segment that was fsynced before its journal record, record an explicit gap where
/// none can be rediscovered, settle the one reserved attempt, and stop the generation. It cannot
/// issue a request, because nothing it can reach knows an endpoint.
///
/// Settlement is asymmetric on purpose. A journal that proves the I/O boundary was crossed settles
/// at the *conservative maximum* of the reservation's own claim, never at an observed use nobody
/// survived to observe. A journal that proves it was not crossed settles at zero and refunds.
///
/// # Errors
///
/// Refuses a journal whose C1 records are duplicated or out of order, a reservation that lost its
/// execution claim, and any durability, journal, or health failure while resolving the attempt.
pub fn reconcile_c1_restart(
    supervisor: &mut Supervisor,
    at: UtcTimestamp,
) -> Result<C1ReplayStateV1> {
    let replay = replay_c1_journal(supervisor.journal_records())?;
    let Some(reservation) = replay.reservation else {
        return Ok(replay.state);
    };
    let io_started = replay.state.io_started;
    if replay.state.attempt_unresolved() {
        // Ordering rule 6: a segment fsynced before its journal record is rediscovered here and
        // recorded idempotently. It must never become a false gap and must never be re-requested.
        supervisor.reconcile_startup(at)?;
    }
    let replay = replay_c1_journal(supervisor.journal_records())?;
    if !replay.state.budget_settled {
        let claim = reservation.execution_claim.ok_or_else(|| {
            SupervisorError::InvalidState("the C1 reservation lost its execution claim".into())
        })?;
        let (usage, disposition) = if io_started {
            (
                maximum_usage(claim),
                RuntimeSettlementDisposition::RecoveredAfterIoWorstCase,
            )
        } else {
            (zero_usage(), RuntimeSettlementDisposition::RefundedBeforeIo)
        };
        supervisor.append_c1_event(
            at,
            JournalEvent::C1BudgetSettled {
                reservation_id: reservation.reservation_id.clone(),
                usage,
                disposition,
            },
        )?;
    }
    let replay = replay_c1_journal(supervisor.journal_records())?;
    if !replay.state.generation_stopped {
        let reason = if io_started {
            "c1_recovered_after_io_started"
        } else {
            "c1_recovered_before_io_started"
        };
        supervisor.c1_stop_without_gap(&reservation, OpenVariant::known(reason)?, at)?;
    }
    replay_c1_journal(supervisor.journal_records()).map(|replay| replay.state)
}

/// The one-shot C1 read: one bound activation, one attempt, one request, then a stop.
///
/// The value owns the supervisor it writes to and the admission it consumed. It exposes no
/// endpoint, executor, callback, or runner, and [`C1Runtime::run_once`] can succeed at most once
/// for the lifetime of the process *and* at most once for the lifetime of the installation.
pub struct C1Runtime {
    supervisor: Supervisor,
    // The burned claim is held for this runtime's lifetime. There is deliberately no accessor: the
    // durable `C1ActivationBound` record, not this value, is what a request may cite.
    _admission: DisabledC1RuntimeAdmission,
    installation_id: String,
    activation_id: String,
    run_id: String,
    bound: C1PhysicalBoundV1,
    limits: RunBudgetLimits,
    claim: AttemptBudgetClaim,
    address: String,
    max_rows: u16,
    source_key: SourceKey,
    operation_key: OperationKey,
    scope: CoverageScope,
    protection: ProtectionProfile,
    run: Wave5RunReferenceV1,
    plan_reference: ProviderPlanReferenceV1,
    spent: bool,
    terminal: bool,
    #[cfg(test)]
    loopback: Option<String>,
}

/// A deliberately partial rendering.
///
/// The burned admission has no `Debug` of its own and is never rendered here; neither is the
/// wallet page, the endpoint, or anything a log line could turn into a locator. What remains is
/// the durable identity a reader needs to find the matching journal records.
impl std::fmt::Debug for C1Runtime {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("C1Runtime")
            .field("installation_id", &self.installation_id)
            .field("activation_id", &self.activation_id)
            .field("run_id", &self.run_id)
            .field("source_key", &self.source_key)
            .field("operation_key", &self.operation_key)
            .field("spent", &self.spent)
            .field("terminal", &self.terminal)
            .finish_non_exhaustive()
    }
}

impl C1Runtime {
    /// Bind one burned C1 activation to this journal installation, or refuse.
    ///
    /// Nothing here opens a socket, and nothing here is recoverable by retrying: the checks run in
    /// a fixed order and the first failure returns before the durable binding is written. The one
    /// durable act is the final `C1ActivationBound` append, which is what makes the admission
    /// visible to replay at all.
    ///
    /// The spool ceiling is read from this supervisor with `Supervisor::spool_config`, never from
    /// a caller. A compile-time physical bound cannot observe the ceiling a running spool actually
    /// enforces, and a caller-supplied copy of the configuration proves nothing because it can
    /// simply disagree with the live one.
    ///
    /// # Errors
    ///
    /// These refusals are **live** — each is reachable from a store-produced admission and has a
    /// test that fails if it is removed: a journal that already carries any bound C1 activation,
    /// an admission bound to a different installation, a run reference that does not itself
    /// validate, a run reference that is not the registration the admission closed over, exact
    /// plan bytes that do not reproduce the admission's closure, a live spool whose segment
    /// ceiling cannot host the derived physical segment, an attempt budget that cannot absorb the
    /// admitted page, and any journal or health failure while binding.
    ///
    /// The remaining refusals below are **restatements of conditions the only path that can
    /// produce a [`DisabledC1RuntimeAdmission`] has already enforced**, and are unreachable
    /// through it. They are kept as defence in depth against a second constructor for a claim, and
    /// this list exists so none of them is mistaken for a gate being applied here for the first
    /// time:
    ///
    /// * The admission's disposition and authority ceiling. Both are `&'static str` fields the
    ///   admission's own constructor derives; no store-produced claim can carry another value.
    /// * The plan shape and the bounded public wallet page.
    ///   `joshi_wave5_c1_activation::parse_c1_activation_exact` requires the same profile,
    ///   execution disposition, absent ingress rate, single in-flight attempt, single operation,
    ///   `SolanaSignaturesForAddress`, generation 1, one attempt, and `PublicWalletPage` scope over
    ///   exactly these plan bytes before the activation can be committed. `admit_c1_plan_shape`
    ///   is still exercised directly as the function it is.
    /// * The canonical request encoding of the address and row bound.
    ///   `joshi_sources::validate_provider_run_plan` already refuses a scope whose address is not
    ///   base58 decoding to 32 bytes or whose row bound is outside 1..=100, and base58 encoding is
    ///   injective, so no admitted scope can fail the canonical encoder.
    /// * The one admitted source and method pair. `joshi_sources` admits exactly two source/method
    ///   pairs, and only one of them carries `SolanaSignaturesForAddress`, which the plan shape
    ///   above already requires.
    /// * The economic-spend refusal inside `execution_envelope`. Both the plan validator and the
    ///   activation parser refuse a plan carrying provider currency or chain-native atoms. It too
    ///   is exercised directly as a function.
    /// * The live-spool agreement check. `Supervisor::open` clones one `SpoolConfig` into both the
    ///   supervisor and the spool it opens, so `spool_config()` and `spool().status()` report the
    ///   same numbers by construction. It is defence against a future supervisor that builds the
    ///   spool from a different source.
    /// * `RunBudgetLimits::validate`, `AttemptBudgetClaim::validate`, `SourceKey::new`,
    ///   `OperationKey::new`, and `ProtectionProfile::validate`. Every input is derived from a plan
    ///   the validator already bounded.
    #[allow(clippy::too_many_lines)] // The refusal order is the contract and stays in one place.
    pub fn open(
        mut supervisor: Supervisor,
        admission: DisabledC1RuntimeAdmission,
        run: Wave5RunReferenceV1,
        exact_plan_bytes: &[u8],
        at: UtcTimestamp,
    ) -> Result<Self> {
        // 1. The global one-read cap, before anything else can allocate meaning.
        let prior = scan_c1_journal(supervisor.journal_records())?;
        if prior.activation_bound() {
            return Err(SupervisorError::InvalidState(
                "this installation journal already binds a C1 activation; C1 admits one read per \
                 installation, ever"
                    .into(),
            ));
        }

        let report = admission.report();
        if report.installation_id != supervisor.installation_id() {
            return Err(SupervisorError::InvalidState(
                "the burned C1 activation is bound to a different journal installation".into(),
            ));
        }
        if admission.execution_disposition() != super::C1_EXECUTION_DISPOSITION
            || admission.authority_ceiling() != crate::AUTHORITY_CEILING
        {
            return Err(SupervisorError::InvalidState(
                "the C1 admission does not carry the single admitted disposition and ceiling"
                    .into(),
            ));
        }

        // 2. The supplied run reference must be the one the admission closed over.
        run.validate()?;
        if run.run_id != report.run_registration_id
            || run.exact_registration.digest.as_str() != report.run_registration_digest
            || run.run_id != admission.run_registration_id()
        {
            return Err(SupervisorError::InvalidState(
                "the supplied run reference is not the registration the C1 admission closed over"
                    .into(),
            ));
        }

        // 3. Reparse the exact plan bytes rather than trusting the report's account of them.
        //
        // The five equalities below are one check written five ways, and only their conjunction is
        // separately testable. `parse_provider_run_plan_exact` refuses bytes that are not the
        // canonical encoding of the plan it decodes, so the plan struct determines the bytes: any
        // substitution that changes one of these values changes all of them, and no substitution
        // can change one alone. They are kept because each names a distinct thing the admission
        // closed over, and a reader checking one of them should find it here rather than have to
        // reconstruct the argument that the others imply it.
        let plan = parse_provider_run_plan_exact(exact_plan_bytes)?;
        if sha256(exact_plan_bytes) != report.exact_plan_digest
            || plan.plan().plan_id != report.plan_id
            || plan.plan_template_digest() != report.plan_template_digest
            || plan.plan_digest() != report.final_plan_digest
            || plan.plan().run.run_id != report.run_registration_id
            || plan.plan().run.registration_digest != report.run_registration_digest
        {
            return Err(SupervisorError::InvalidState(
                "the exact C1 plan bytes do not reproduce the admission's closure".into(),
            ));
        }
        let operation = admit_c1_plan_shape(&plan)?;
        let ProviderScopePort::PublicWalletPage { address, max_rows } = &operation.plan.scope
        else {
            return Err(SupervisorError::InvalidState(
                "the C1 plan does not carry a bounded public wallet page".into(),
            ));
        };
        // Close the request shape before any durable record cites it: an address the canonical
        // encoder would refuse must never reach a bound activation.
        canonical_public_solana_c1_request(address, *max_rows)
            .map_err(|error| SupervisorError::InvalidValue(error.to_string()))?;

        // 4. The configured ceiling check. The bound is derived from the shared ingress ceiling,
        //    and the *actual* configured segment ceiling has to be able to host it.
        let bound = c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES)?;
        let spool = supervisor.spool_config().clone();
        let status = supervisor.spool().status()?;
        // Defence in depth, and unreachable as written: `Supervisor::open` clones one
        // `SpoolConfig` into both the supervisor and the `LocalSpool` it opens, and `status()`
        // reports that spool's own copy, so the two agree by construction. It stays because the
        // *next* stage reasons about a ceiling the running spool enforces rather than one a
        // configuration merely names, and that reasoning should fail loudly rather than silently
        // if a future supervisor ever builds the spool from somewhere else.
        if spool.max_total_bytes != status.maximum_bytes
            || spool.control_reserve_bytes != status.control_reserve_bytes
        {
            return Err(SupervisorError::InvalidConfig(
                "the running C1 spool does not report the ceilings this supervisor is configured \
                 with"
                    .into(),
            ));
        }
        if bound.max_segment_bytes() > spool.max_segment_bytes {
            return Err(SupervisorError::InvalidConfig(format!(
                "the derived C1 physical segment is {} bytes and the configured spool segment \
                 ceiling is {}; this spool cannot host a C1 read",
                bound.max_segment_bytes(),
                spool.max_segment_bytes
            )));
        }

        // 5. The attempt budget has to be able to absorb the admitted page. Refusing here is
        //    deliberate: the alternative is a guaranteed terminal violation after the socket.
        let (limits, claim) = execution_envelope(&plan, &operation.plan.attempt_cost)?;
        limits.validate()?;
        claim.validate()?;
        if claim.maximum_ingress_bytes < bound.max_response_body_bytes()
            || claim.maximum_durable_bytes < bound.max_segment_bytes()
        {
            return Err(SupervisorError::InvalidConfig(format!(
                "the C1 attempt reserves {} ingress and {} durable bytes, under the {} and {} the \
                 admitted page can physically need",
                claim.maximum_ingress_bytes,
                claim.maximum_durable_bytes,
                bound.max_response_body_bytes(),
                bound.max_segment_bytes()
            )));
        }

        let source_key = SourceKey::new(operation.plan.source_key.clone())?;
        let operation_key = OperationKey::new(operation.plan.method_key.clone())?;
        if source_key.as_str() != C1_SOURCE_KEY || operation_key.as_str() != C1_OPERATION_KEY {
            return Err(SupervisorError::InvalidState(
                "the C1 plan names a source or method outside the one admitted pair".into(),
            ));
        }
        let scope = CoverageScope {
            source_id: DomainSourceId::new(operation.plan.source_key.clone())?,
            family: OpenVariant::known(operation.coverage_family.clone())?,
            subject: Some(StableString::new(plan.plan().plan_id.clone())?),
        };
        let protection = ProtectionProfile::PublicIntegrity {
            domain: ProtectionDomainId::new(operation.protection_domain.clone())?,
        };
        protection.validate()?;
        let plan_reference = ProviderPlanReferenceV1 {
            plan_id: plan.plan().plan_id.clone(),
            plan_template_digest: plan.plan_template_digest().to_owned(),
            plan_digest: plan.plan_digest().to_owned(),
        };

        // 6. Bind the burned claim to this journal. Until this is fsynced there is no durable
        //    trace that an admission happened at all.
        supervisor.append_c1_event(
            at,
            JournalEvent::C1ActivationBound {
                activation_id: report.activation_id.clone(),
                installation_id: report.installation_id.clone(),
                run_registration_id: report.run_registration_id.clone(),
                run_registration_digest: report.run_registration_digest.clone(),
                activation_digest: report.activation_digest.clone(),
                exact_plan_digest: report.exact_plan_digest.clone(),
                plan_id: report.plan_id.clone(),
                plan_template_digest: report.plan_template_digest.clone(),
                final_plan_digest: report.final_plan_digest.clone(),
                activation_commit_sequence: report.activation_commit_sequence,
                claim_commit_sequence: report.claim_commit_sequence,
                claim_commit_digest: report.claim_commit_digest.clone(),
                maximum_response_bytes: bound.max_response_body_bytes(),
                maximum_segment_bytes: bound.max_segment_bytes(),
            },
        )?;

        Ok(Self {
            installation_id: report.installation_id.clone(),
            activation_id: report.activation_id.clone(),
            run_id: report.run_registration_id.clone(),
            supervisor,
            _admission: admission,
            bound,
            limits,
            claim,
            address: address.clone(),
            max_rows: *max_rows,
            source_key,
            operation_key,
            scope,
            protection,
            run,
            plan_reference,
            spent: false,
            terminal: false,
            #[cfg(test)]
            loopback: None,
        })
    }

    /// Borrow the supervisor this runtime writes through.
    #[must_use]
    pub const fn supervisor(&self) -> &Supervisor {
        &self.supervisor
    }

    /// The physical byte bound every stage of this read is held to.
    #[must_use]
    pub const fn physical_bound(&self) -> C1PhysicalBoundV1 {
        self.bound
    }

    /// Point this runtime's transport at a private loopback listener.
    ///
    /// This exists only under `cfg(test)`, so it is compiled into this crate's own unit tests and
    /// nothing else. It is what lets the ordered durable path be exercised against scripted
    /// response bytes without any test ever contacting a public endpoint.
    #[cfg(test)]
    pub(crate) fn bind_loopback_for_tests(&mut self, base_url: String) {
        self.loopback = Some(base_url);
    }

    /// Perform the one admitted read, in the one admitted order.
    ///
    /// Every durable record precedes the act it authorises: the attempt identity is fsynced before
    /// the request is closed, the request is closed before the I/O boundary is recorded, and the
    /// boundary is recorded before a socket can open. Every failure at or after the boundary is
    /// terminal — no retry, an explicit gap where one can be stated, conservative maximum
    /// settlement, and a stopped generation.
    ///
    /// # Errors
    ///
    /// Refuses a runtime whose one admitted read is already spent — every second call, whether the
    /// first succeeded or failed — an exhausted budget, and every transport, conformance,
    /// evidence, durability, settlement, and journal failure. Failures after the I/O boundary are
    /// charged at the reservation's maximum and leave this runtime permanently terminal.
    ///
    /// Two further refusals are restated below and are **not reachable** through this type. The
    /// terminal check cannot fire on its own: nothing sets `terminal` before `spent`, so a spent
    /// runtime is what a caller actually meets. The journal-attempt check cannot fire either:
    /// [`C1Runtime::open`] refuses any journal that already binds an activation, this runtime owns
    /// its supervisor by value and hands out only `&Supervisor`, so no other writer can add a C1
    /// reservation between `open` and here, and a second `run_once` stops at `spent` above it.
    /// Both are kept as defence in depth against a future constructor or a shared supervisor, and
    /// neither should be read as a live protection.
    #[allow(clippy::too_many_lines)] // The ordered pre-I/O and post-I/O paths stay auditable here.
    pub fn run_once(&mut self, at: UtcTimestamp, monotonic_ms: u64) -> Result<C1RunReport> {
        // `spent` is checked first because it is the fact that is true in every already-run state:
        // it is set below before anything can set `terminal`, so reporting a boundary failure for
        // a read that in fact completed would simply be false.
        if self.spent {
            return Err(SupervisorError::InvalidState(
                "the one admitted C1 read has already been performed".into(),
            ));
        }
        if self.terminal {
            return Err(SupervisorError::InvalidState(
                "the C1 runtime is terminal after a prior boundary failure".into(),
            ));
        }
        // Unreachable as written, and kept anyway. `open` refuses a journal that already binds an
        // activation, this runtime owns its supervisor by value and lends out only `&Supervisor`,
        // and a second call stops at `spent` above — so no journal reaching here can already carry
        // a C1 attempt. It is the last line of the one-read cap rather than a live gate, and the
        // `terminal` refusal above it is only reachable through this branch.
        let replay = scan_c1_journal(self.supervisor.journal_records())?;
        if replay.reservation_id.is_some() || replay.io_started {
            self.terminal = true;
            return Err(SupervisorError::InvalidState(
                "this installation journal already records a C1 attempt; no second request may \
                 ever issue"
                    .into(),
            ));
        }
        // Spend the one-shot before anything else can fail. A failure below must never leave a
        // value that could be asked to try again.
        self.spent = true;

        let mut ledger = BudgetLedger::new(self.limits, monotonic_ms)?;
        let permit = ledger.reserve(self.claim, monotonic_ms)?;

        // (c) fsync the attempt identity.
        let reservation = match self.supervisor.reserve_c1(self.reservation_request(at), at) {
            Ok(value) => value,
            Err(error) => {
                // The reservation may have fsynced and then failed health persistence; the error
                // alone cannot prove no durable attempt exists.
                self.terminal = true;
                return Err(error);
            }
        };

        // (d) close the exact request. Digests only: never a URL, body, header, or credential.
        let request = match canonical_public_solana_c1_request(&self.address, self.max_rows) {
            Ok(value) => value,
            Err(error) => {
                return Err(self.cancel_before_io(
                    &reservation,
                    &mut ledger,
                    permit,
                    "c1_request_closure_failed",
                    at,
                    SupervisorError::InvalidValue(error.to_string()),
                ));
            }
        };
        let transport = match self.open_transport() {
            Ok(value) => value,
            Err(error) => {
                return Err(self.cancel_before_io(
                    &reservation,
                    &mut ledger,
                    permit,
                    "c1_transport_unavailable",
                    at,
                    transport_error(error),
                ));
            }
        };
        let request_body_byte_length = u64::try_from(request.byte_len).map_err(|_| {
            SupervisorError::InvalidValue("C1 request body length exceeds u64".into())
        })?;
        let prepared = JournalEvent::C1RequestPrepared {
            reservation_id: reservation.reservation_id.clone(),
            endpoint_digest: transport.endpoint_digest(),
            request_body_digest: sha256(&request.body),
            request_body_byte_length,
            method_key: self.operation_key.as_str().to_owned(),
            maximum_response_bytes: transport.maximum_response_bytes(),
            deadline_ms: transport.deadline_ms(),
        };
        if let Err(error) = self.supervisor.append_c1_event(at, prepared) {
            return Err(self.cancel_before_io(
                &reservation,
                &mut ledger,
                permit,
                "c1_request_closure_durability_failure",
                at,
                error,
            ));
        }

        // (e) the irreversible boundary. A failure to append is ambiguous — the record may be on
        // disk — so it is charged as though the boundary had been crossed.
        if let Err(error) = self.supervisor.append_c1_event(
            at,
            JournalEvent::C1IoStarted {
                reservation_id: reservation.reservation_id.clone(),
            },
        ) {
            return Err(self.terminate_after_io(
                &reservation,
                &mut ledger,
                permit,
                "c1_io_start_durability_ambiguous",
                at,
                error,
            ));
        }

        // (f) the single request.
        let endpoint_digest = transport.endpoint_digest();
        let maximum_response_bytes = transport.maximum_response_bytes();
        let deadline_ms = transport.deadline_ms();
        let wall_started = wall_millis(at)?;
        let response = match transport.execute_once(&request.body, wall_started) {
            Ok(value) => value,
            Err(error) => {
                return Err(self.terminate_after_io(
                    &reservation,
                    &mut ledger,
                    permit,
                    "c1_request_failed",
                    at,
                    transport_error(error),
                ));
            }
        };

        // (g) validate, retain, and make durable.
        let frame = response.to_frame();
        let response_shape = match read_public_solana_c1_frame(&frame, self.max_rows) {
            Ok(PublicSolanaC1Outcome::Page(_)) => C1ResponseShape::Page,
            Ok(PublicSolanaC1Outcome::ProviderRefusal(_)) => C1ResponseShape::ProviderRefusal,
            Err(error) => {
                return Err(self.terminate_after_io(
                    &reservation,
                    &mut ledger,
                    permit,
                    "c1_response_not_conformant",
                    at,
                    SupervisorError::InvalidValue(error.to_string()),
                ));
            }
        };
        let adapter = match C1RawObservationAdapter::new(self.bound) {
            Ok(value) => value,
            Err(error) => {
                return Err(self.terminate_after_io(
                    &reservation,
                    &mut ledger,
                    permit,
                    "c1_raw_adapter_unavailable",
                    at,
                    error,
                ));
            }
        };
        let pending = match adapter.prepare_raw_page(&reservation, frame) {
            Ok(value) => value,
            Err(error) => {
                return Err(self.terminate_after_io(
                    &reservation,
                    &mut ledger,
                    permit,
                    "c1_raw_adapter_refused",
                    at,
                    error,
                ));
            }
        };
        if self.supervisor.try_enqueue(pending).is_err() {
            return Err(self.terminate_after_io(
                &reservation,
                &mut ledger,
                permit,
                "c1_ingress_saturated",
                at,
                SupervisorError::InvalidState("the bounded queue refused the one C1 page".into()),
            ));
        }
        let receipt = match self.supervisor.drain_one_c1(at) {
            Ok(Some(value)) => value,
            Ok(None) => {
                self.terminal = true;
                return Err(SupervisorError::InvalidState(
                    "the C1 page disappeared before durability".into(),
                ));
            }
            Err(error) => {
                // The item stays queued and unreleased, so the attempt cannot be abandoned into a
                // gap here. Becoming terminal is the whole remedy.
                self.terminal = true;
                return Err(error);
            }
        };

        // (h) settle the one attempt, then stop the one-shot generation.
        let durable_bytes = parse_wire_u64(&receipt.exact_segment.byte_length)?;
        let ingress_bytes = u64::try_from(response.body.len()).map_err(|_| {
            SupervisorError::InvalidValue("C1 response body length exceeds u64".into())
        })?;
        let usage = AttemptBudgetUsage {
            requests: 1,
            pages: 1,
            ingress_bytes,
            durable_bytes,
            provider_credits: 0,
            elapsed_ms: response.elapsed_ms,
        };
        let settlement = self.settle(
            &reservation,
            &mut ledger,
            permit,
            usage,
            RuntimeSettlementDisposition::Observed,
            at,
        )?;
        self.terminal = true;
        self.supervisor.c1_stop_without_gap(
            &reservation,
            OpenVariant::known("c1_one_shot_completed")?,
            at,
        )?;

        Ok(self.report(
            &reservation,
            &response,
            response_shape,
            sha256(&request.body),
            request_body_byte_length,
            endpoint_digest,
            maximum_response_bytes,
            deadline_ms,
            usage,
            settlement,
            receipt,
        ))
    }

    fn reservation_request(&self, at: UtcTimestamp) -> ReservationRequest {
        ReservationRequest {
            source_key: self.source_key.clone(),
            operation_key: self.operation_key.clone(),
            kind: AttemptKind::HttpRequest,
            scope: self.scope.clone(),
            lower: Boundary::Wall { value: at },
            protection: self.protection.clone(),
            run: Some(self.run.clone()),
            execution_claim: Some(self.claim),
            provider_plan: Some(self.plan_reference.clone()),
        }
    }

    fn open_transport(&self) -> std::result::Result<C1Transport, C1TransportError> {
        #[cfg(test)]
        if let Some(base) = &self.loopback {
            return C1Transport::loopback(
                base.clone(),
                self.bound.max_response_body_bytes(),
                self.claim.maximum_elapsed_ms,
            );
        }
        C1Transport::open(
            self.bound.max_response_body_bytes(),
            self.claim.maximum_elapsed_ms,
        )
    }

    /// Resolve an attempt the journal proves never started I/O: refund, gap, stop, settle at zero.
    ///
    /// The refund is licensed by the journal, not by this function's own opinion: no `C1IoStarted`
    /// record exists at any point this is reachable. The durable gap is still recorded, because
    /// the reservation is pending and something has to resolve it; it states an unresolved attempt
    /// with no upper boundary, which is what happened, and it establishes no coverage.
    fn cancel_before_io(
        &mut self,
        reservation: &AttemptReservation,
        ledger: &mut BudgetLedger,
        permit: BudgetPermit,
        reason: &str,
        at: UtcTimestamp,
        error: SupervisorError,
    ) -> SupervisorError {
        self.terminal = true;
        let Ok(reason) = OpenVariant::known(reason) else {
            return error;
        };
        if ledger.cancel_before_io(permit).is_err() {
            return error;
        }
        if self
            .supervisor
            .c1_abandon_and_stop(reservation, reason, at)
            .is_err()
        {
            return error;
        }
        let _ = self.supervisor.append_c1_event(
            at,
            JournalEvent::C1BudgetSettled {
                reservation_id: reservation.reservation_id.clone(),
                usage: zero_usage(),
                disposition: RuntimeSettlementDisposition::RefundedBeforeIo,
            },
        );
        error
    }

    /// Resolve an attempt at or after the I/O boundary: explicit gap, maximum charge, stop.
    ///
    /// Nothing observed is trusted here. The settlement is the reservation's own maximum claim,
    /// raised to at least the gap segment's physical length, and the disposition is a terminal
    /// violation. There is no path back from this: the generation is stopped and the runtime is
    /// permanently terminal.
    fn terminate_after_io(
        &mut self,
        reservation: &AttemptReservation,
        ledger: &mut BudgetLedger,
        permit: BudgetPermit,
        reason: &str,
        at: UtcTimestamp,
        error: SupervisorError,
    ) -> SupervisorError {
        self.terminal = true;
        let Ok(reason) = OpenVariant::known(reason) else {
            return error;
        };
        let mut usage = maximum_usage(self.claim);
        if let Ok(receipt) = self.supervisor.c1_abandon_and_stop(reservation, reason, at)
            && let Ok(gap_bytes) = parse_wire_u64(&receipt.exact_segment.byte_length)
        {
            usage.durable_bytes = usage.durable_bytes.max(gap_bytes);
        }
        let _ = self.settle(
            reservation,
            ledger,
            permit,
            usage,
            RuntimeSettlementDisposition::TerminalViolation,
            at,
        );
        error
    }

    fn settle(
        &mut self,
        reservation: &AttemptReservation,
        ledger: &mut BudgetLedger,
        permit: BudgetPermit,
        usage: AttemptBudgetUsage,
        disposition: RuntimeSettlementDisposition,
        at: UtcTimestamp,
    ) -> Result<RuntimeSettlementDisposition> {
        let violation = ledger.settlement_violation(&permit, usage)?;
        let durable_disposition = if violation.is_some() {
            RuntimeSettlementDisposition::TerminalViolation
        } else {
            disposition
        };
        if let Err(error) = self.supervisor.append_c1_event(
            at,
            JournalEvent::C1BudgetSettled {
                reservation_id: reservation.reservation_id.clone(),
                usage,
                disposition: durable_disposition,
            },
        ) {
            // The worst-case hold is not released after an ambiguous durable append.
            self.terminal = true;
            return Err(error);
        }
        if let Err(error) = ledger.settle(permit, usage) {
            self.terminal = true;
            return Err(error);
        }
        if durable_disposition == RuntimeSettlementDisposition::TerminalViolation {
            self.terminal = true;
        }
        Ok(durable_disposition)
    }

    #[allow(clippy::too_many_arguments)] // The report is a flat account of one finished attempt.
    fn report(
        &self,
        reservation: &AttemptReservation,
        response: &C1RawResponse,
        response_shape: C1ResponseShape,
        request_body_digest: String,
        request_body_byte_length: u64,
        endpoint_digest: String,
        maximum_response_bytes: u64,
        deadline_ms: u64,
        usage: AttemptBudgetUsage,
        settlement: RuntimeSettlementDisposition,
        local_spool: LocalSpoolReceiptV1,
    ) -> C1RunReport {
        C1RunReport {
            contract: C1_CONTRACT_VERSION.to_owned(),
            installation_id: self.installation_id.clone(),
            activation_id: self.activation_id.clone(),
            run_id: self.run_id.clone(),
            reservation_id: reservation.reservation_id.to_string(),
            source_key: self.source_key.as_str().to_owned(),
            operation_key: self.operation_key.as_str().to_owned(),
            generation: reservation.generation.get(),
            attempt_ordinal: reservation.attempt_ordinal,
            endpoint_digest,
            request_body_digest,
            request_body_byte_length,
            maximum_response_bytes,
            maximum_segment_bytes: self.bound.max_segment_bytes(),
            deadline_ms,
            response_status: response.http_status,
            response_body_bytes: usage.ingress_bytes,
            response_body_digest: sha256(&response.body),
            retained_header_names: response
                .safe_headers
                .iter()
                .map(|header| header.name.clone())
                .collect(),
            response_shape,
            elapsed_ms: response.elapsed_ms,
            usage,
            settlement,
            local_spool,
            authority: crate::AUTHORITY_CEILING.to_owned(),
        }
    }
}

/// Require the exact isolated one-page C1 public-Solana plan shape.
fn admit_c1_plan_shape(
    plan: &ValidatedProviderRunPlan,
) -> Result<joshi_sources::ValidatedProviderOperation> {
    if plan.plan().profile != CanaryProfilePort::C1
        || plan.built_in_execution() != BuiltInExecutionDisposition::ValidationOnlyNoProviderIo
        || plan.plan().max_in_flight_attempts != 1
        || plan.plan().max_ingress_bytes_per_second.is_some()
        || plan.operations().len() != 1
    {
        return Err(SupervisorError::InvalidState(
            "the C1 plan is not the isolated one-page public-Solana shape".into(),
        ));
    }
    let operation = plan.operations()[0].clone();
    if operation.plan.operation != ProviderOperation::SolanaSignaturesForAddress
        || operation.plan.generation != 1
        || operation.plan.max_attempts != 1
    {
        return Err(SupervisorError::InvalidState(
            "the C1 plan operation is not one bounded signature-page read".into(),
        ));
    }
    Ok(operation)
}

/// Derive the run envelope and the single attempt claim from the exact plan.
///
/// The activation parser already proved `hard_cap == reserved_total` for the one operation, so the
/// run envelope and the attempt claim describe the same one attempt from two directions rather
/// than being two independently authored numbers.
fn execution_envelope(
    plan: &ValidatedProviderRunPlan,
    cost: &joshi_sources::RuntimeAttemptCostPort,
) -> Result<(RunBudgetLimits, AttemptBudgetClaim)> {
    let reserved = cost.reserved_total()?;
    if !reserved.provider_currency_minor.is_empty() || !reserved.chain_native_atoms.is_empty() {
        return Err(SupervisorError::InvalidValue(
            "a C1 attempt cannot carry economic spend".into(),
        ));
    }
    let cap: &RuntimeBudgetPort = &plan.plan().hard_cap;
    let limits = RunBudgetLimits {
        maximum_requests: cap.requests,
        maximum_pages: cap.pages,
        maximum_ingress_bytes: cap.ingress_bytes,
        maximum_durable_bytes: cap.durable_bytes,
        maximum_provider_credits: cap.provider_credits,
        maximum_ingress_bytes_per_second: plan.plan().max_ingress_bytes_per_second,
        maximum_elapsed_ms: plan.plan().max_elapsed_ms,
        maximum_in_flight_attempts: u64::from(plan.plan().max_in_flight_attempts),
        maximum_in_flight_elapsed_overshoot_ms: reserved.wall_millis,
    };
    let claim = AttemptBudgetClaim {
        requests: reserved.requests,
        pages: reserved.pages,
        maximum_ingress_bytes: reserved.ingress_bytes,
        maximum_durable_bytes: reserved.durable_bytes,
        maximum_provider_credits: reserved.provider_credits,
        maximum_ingress_bytes_per_second: plan.plan().max_ingress_bytes_per_second,
        maximum_elapsed_ms: reserved.wall_millis,
    };
    Ok((limits, claim))
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

const fn maximum_usage(claim: AttemptBudgetClaim) -> AttemptBudgetUsage {
    AttemptBudgetUsage {
        requests: claim.requests,
        pages: claim.pages,
        ingress_bytes: claim.maximum_ingress_bytes,
        durable_bytes: claim.maximum_durable_bytes,
        provider_credits: claim.maximum_provider_credits,
        elapsed_ms: claim.maximum_elapsed_ms,
    }
}

/// Collapse a transport refusal into the supervisor error channel without widening it.
///
/// The transport's own message is already free of any URL, body, or header value, so it is safe to
/// carry here; nothing else about the refusal is retained.
fn transport_error(error: C1TransportError) -> SupervisorError {
    SupervisorError::InvalidState(format!("the one C1 request was refused: {error}"))
}

fn parse_wire_u64(value: &str) -> Result<u64> {
    value
        .parse()
        .map_err(|_| SupervisorError::InvalidValue("wire byte length is not a u64".into()))
}

fn wall_millis(at: UtcTimestamp) -> Result<UnixMillis> {
    let millis = at.as_datetime().unix_timestamp_nanos() / 1_000_000;
    i64::try_from(millis)
        .map(UnixMillis)
        .map_err(|_| SupervisorError::InvalidValue("C1 wall reading is outside UnixMillis".into()))
}

fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::super::transport::probe::{
        Loopback, Step, chunked_response, ok_page_response, request_body, request_line,
    };
    use super::*;
    use crate::{
        CollectorRuntimeConfigV1, FaultInjector, FaultPoint, QueueLimits, RetryPolicy,
        SupervisorConfig,
    };
    use joshi_admission::{
        operational::ExactByteClosureV1,
        wave5::{
            ExactRegisteredDocumentV1, ExecutionAccountingDocumentV1,
            WAVE5_RUN_REGISTRATION_CONTRACT, Wave5RunRegistrationV1,
        },
    };
    use joshi_domain::StableString;
    use joshi_sources::{
        PROVIDER_RUN_PLAN_PORT_VERSION, PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT,
        PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT, ProviderOperationPlan, ProviderRunPlanTemplate,
        RegisteredRunPort, RuntimeAttemptCostPort, validate_provider_run_plan,
    };
    use joshi_store::{
        SqliteStore, StoreConfig, StoreMode, Wave5CommitContext, Wave5RunRegistrationByteBundle,
    };
    use joshi_wave5_c1_activation::{
        ExactC1BudgetProjectionV1, ExactPlanClosureV1, ExactSourceMethodProjectionV1,
        FinalityCommitmentV1, PublicWalletPageV1, Wave5C1ActivationV1,
    };
    use std::{
        collections::BTreeMap,
        path::Path,
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
        time::Duration,
    };
    use tempfile::TempDir;

    const AUTHORITY: &str = "read_only_no_execution";
    const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";
    const MAX_ROWS: u16 = 10;
    /// The strict per-attempt deadline every fixture plan reserves, in milliseconds.
    ///
    /// The exact plan validator requires `hard_cap.wall_millis == max_elapsed_ms`, and the one
    /// attempt is the whole run, so the run envelope and the attempt deadline are the same value.
    const ATTEMPT_WALL_MS: u64 = 500;
    const SURFACE_FILE: &[u8] =
        include_bytes!("../../../../fixtures/surface/daily_use_surface_profile_v1.json");
    const EMPTY_PAGE: &str = r#"{"jsonrpc":"2.0","id":1,"result":[]}"#;
    /// One conforming row. The signature is 64 zero bytes, whose canonical base58 is 64 `1`s.
    const ONE_ROW_PAGE: &str = concat!(
        r#"{"jsonrpc":"2.0","id":1,"result":[{"signature":""#,
        "1111111111111111111111111111111111111111111111111111111111111111",
        r#"","slot":1,"err":null,"memo":null,"blockTime":null,"confirmationStatus":"finalized"}]}"#
    );
    /// A well-formed typed JSON-RPC refusal. It is an answer that declined, never a page.
    const REFUSAL_PAGE: &str =
        r#"{"jsonrpc":"2.0","id":1,"error":{"code":-32005,"message":"rate limited"}}"#;
    /// A 200 response whose envelope does not match the frozen schema.
    const NON_CONFORMANT_PAGE: &str = r#"{"jsonrpc":"1.0","id":1,"result":[]}"#;

    fn at() -> UtcTimestamp {
        "2026-08-19T12:00:00.000000Z".parse().expect("timestamp")
    }

    fn digest_of(bytes: &[u8]) -> String {
        sha256(bytes)
    }

    fn exact_document(id: &str, bytes: &[u8]) -> ExactRegisteredDocumentV1 {
        ExactRegisteredDocumentV1 {
            document_id: id.to_owned(),
            exact_bytes: ExactByteClosureV1::new(bytes).expect("exact closure"),
        }
    }

    /// The derived physical segment ceiling for the admitted ingress ceiling.
    ///
    /// Every fixture reserves at least this many durable bytes, because [`C1Runtime::open`]
    /// deliberately refuses a plan whose attempt cost cannot absorb the admitted page.
    fn derived_segment_bytes() -> u64 {
        c1_physical_bound(C1_MAX_RESPONSE_BODY_BYTES)
            .expect("derive the C1 physical bound")
            .max_segment_bytes()
    }

    fn supervisor_config(root: &Path) -> SupervisorConfig {
        let segment = derived_segment_bytes().next_power_of_two();
        SupervisorConfig {
            root: root.to_path_buf(),
            spool: joshi_spool::SpoolConfig {
                root: root.join("spool"),
                max_segment_bytes: segment,
                max_entries_per_segment: 32,
                max_total_bytes: segment * 16,
                control_reserve_bytes: segment,
                max_transfer_chunk_bytes: 4_096,
            },
            queue: QueueLimits {
                maximum_records: 8,
                maximum_bytes: segment * 4,
                control_reserve_records: 2,
                control_reserve_bytes: segment,
            },
            retry: RetryPolicy {
                maximum_attempts_per_generation: 1,
                base_delay: Duration::from_millis(1),
                maximum_delay: Duration::from_millis(10),
            },
            shutdown_deadline: Duration::from_secs(1),
            maximum_spool_bytes_per_utc_day: segment * 8,
        }
    }

    fn open_store(root: &Path) -> SqliteStore {
        std::fs::create_dir_all(root).expect("store root");
        let mut store = SqliteStore::open(
            StoreConfig {
                catalog_path: root.join("catalog.sqlite"),
                blob_root: root.join("blobs"),
                export_root: root.join("exports"),
                inline_blob_max_bytes: 1_024,
                busy_timeout: Duration::from_secs(1),
                catalog_id: StableString::new("catalog:c1-runtime-lane").expect("catalog id"),
                max_observations_per_batch: 64,
                max_raw_bytes_per_batch: 4 * 1_024 * 1_024,
            },
            StoreMode::SingleWriter,
        )
        .expect("open the durable catalog");
        store
            .migrate(at())
            .expect("migrate the catalog through V23");
        store
    }

    fn commit_context(store: &SqliteStore, id: &str) -> Wave5CommitContext {
        store
            .begin_wave5_commit(
                StableString::new(id).expect("context id"),
                StableString::new("build:c1-runtime-lane").expect("build id"),
            )
            .expect("begin a durable Wave 5 context")
    }

    fn zero_budget() -> RuntimeBudgetPort {
        RuntimeBudgetPort {
            requests: 0,
            pages: 0,
            ingress_bytes: 0,
            durable_bytes: 0,
            provider_credits: 0,
            wall_millis: 0,
            provider_currency_minor: BTreeMap::new(),
            chain_native_atoms: BTreeMap::new(),
        }
    }

    fn attempt_cost() -> RuntimeAttemptCostPort {
        RuntimeAttemptCostPort {
            worst_case: RuntimeBudgetPort {
                requests: 1,
                pages: 1,
                ingress_bytes: C1_MAX_RESPONSE_BODY_BYTES,
                durable_bytes: derived_segment_bytes(),
                provider_credits: 0,
                wall_millis: ATTEMPT_WALL_MS,
                ..zero_budget()
            },
            max_overshoot: zero_budget(),
        }
    }

    fn plan_template(suffix: &str) -> ProviderRunPlanTemplate {
        plan_template_with_cost(suffix, &attempt_cost())
    }

    /// The same fixture plan with a caller-chosen attempt cost.
    ///
    /// Nothing between here and `C1Runtime::open` requires an attempt to reserve as much as the
    /// admitted page can physically need — the plan validator bounds the cost from *above* and the
    /// activation parser only requires internal consistency — so a plan that reserves too little
    /// is committable, burnable, and reaches `open`. That is what makes the absorption refusal a
    /// live gate rather than a restatement.
    fn plan_template_with_cost(
        suffix: &str,
        cost: &RuntimeAttemptCostPort,
    ) -> ProviderRunPlanTemplate {
        ProviderRunPlanTemplate {
            port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
            plan_id: format!("c1-runtime-plan-{suffix}"),
            profile: CanaryProfilePort::C1,
            hard_cap: cost.reserved_total().expect("reserved total"),
            max_elapsed_ms: ATTEMPT_WALL_MS,
            max_ingress_bytes_per_second: None,
            max_in_flight_attempts: 1,
            operations: vec![ProviderOperationPlan {
                source_key: C1_SOURCE_KEY.to_owned(),
                method_key: C1_OPERATION_KEY.to_owned(),
                source_contract_fingerprint: PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                method_schema_fingerprint: PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT
                    .to_owned(),
                operation: ProviderOperation::SolanaSignaturesForAddress,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::PublicWalletPage {
                    address: WALLET.to_owned(),
                    max_rows: MAX_ROWS,
                },
                attempt_cost: cost.clone(),
            }],
        }
    }

    /// One validated plan bound to a nominal run, for the tests of the pure plan gates.
    ///
    /// Those gates take a `ValidatedProviderRunPlan` and nothing else, so no durable catalog,
    /// registration, or activation is involved and none is opened here.
    fn fixture_plan(suffix: &str, template: ProviderRunPlanTemplate) -> ValidatedProviderRunPlan {
        validate_provider_run_plan(template.bind_run(RegisteredRunPort {
            run_id: format!("run:c1-runtime-{suffix}"),
            registration_digest: digest_of(suffix.as_bytes()),
        }))
        .expect("a plan joshi_sources itself accepts")
    }

    /// One durably registered run, plus the exact bytes a caller has to re-supply later.
    struct RegisteredRun {
        run: Wave5RunReferenceV1,
        plan: ValidatedProviderRunPlan,
        plan_bytes: Vec<u8>,
    }

    fn register_run(store: &mut SqliteStore, suffix: &str) -> RegisteredRun {
        register_run_with_cost(store, suffix, &attempt_cost())
    }

    fn register_run_with_cost(
        store: &mut SqliteStore,
        suffix: &str,
        cost: &RuntimeAttemptCostPort,
    ) -> RegisteredRun {
        let template = plan_template_with_cost(suffix, cost);
        let template_digest = template.plan_template_digest().expect("template digest");
        let run_id = format!("run:c1-runtime-{suffix}");

        let tree = format!(
            r#"{{"contract":"joshi.wave5.source_tree_manifest","schemaVersion":1,"repositoryId":"joshi","head":{{"kind":"commit","object_id":"{}"}},"dirty":false,"workingTreeDigest":"{}","diffDigest":null,"authority":"{AUTHORITY}"}}"#,
            "1".repeat(40),
            digest_of(b"tree")
        )
        .into_bytes();
        let build = format!(
            r#"{{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"build:c1-runtime-lane","sourceTreeDigest":"{}","rustcVersion":"rustc-test","targetTriple":"test","profile":"local_debug","authority":"{AUTHORITY}"}}"#,
            digest_of(&tree)
        )
        .into_bytes();
        let privacy = format!(
            r#"{{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"privacy:c1","permittedProtectionClasses":["public_integrity"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":false,"authority":"{AUTHORITY}"}}"#
        )
        .into_bytes();
        let configuration = CollectorRuntimeConfigV1 {
            contract: "joshi.collector.runtime_config.v1".to_owned(),
            schema_version: 1,
            plan_id: template.plan_id.clone(),
            plan_template_digest: template_digest,
            status_endpoint: crate::LocalStatusEndpoint {
                address: "127.0.0.1".parse().expect("loopback"),
                port: 19_441,
            },
            provider_execution: crate::ProviderExecutionMode::OfflineFixtureOnly,
            authority: AUTHORITY.to_owned(),
        }
        .canonical_bytes()
        .expect("canonical configuration");
        let cap = cost.reserved_total().expect("reserved total");
        let budget = ExecutionAccountingDocumentV1 {
            contract: "joshi.collector.execution_accounting.v1".to_owned(),
            schema_version: 1,
            limits: RunBudgetLimits {
                maximum_requests: cap.requests,
                maximum_pages: cap.pages,
                maximum_ingress_bytes: cap.ingress_bytes,
                maximum_durable_bytes: cap.durable_bytes,
                maximum_provider_credits: 0,
                maximum_ingress_bytes_per_second: None,
                maximum_elapsed_ms: ATTEMPT_WALL_MS,
                maximum_in_flight_attempts: 1,
                maximum_in_flight_elapsed_overshoot_ms: ATTEMPT_WALL_MS,
            },
            authority: AUTHORITY.to_owned(),
        }
        .canonical_bytes()
        .expect("canonical accounting");
        let surface = SURFACE_FILE
            .strip_suffix(b"\n")
            .unwrap_or(SURFACE_FILE)
            .to_vec();

        let registration = Wave5RunRegistrationV1 {
            contract: WAVE5_RUN_REGISTRATION_CONTRACT.to_owned(),
            schema_version: 1,
            run_id: run_id.clone(),
            build: exact_document(&format!("build:{suffix}"), &build),
            source_tree: exact_document(&format!("tree:{suffix}"), &tree),
            configuration: exact_document(&format!("config:{suffix}"), &configuration),
            budget: exact_document(&format!("budget:{suffix}"), &budget),
            privacy: exact_document(&format!("privacy:{suffix}"), &privacy),
            daily_use_surface_profile: exact_document(&format!("surface:{suffix}"), &surface),
            authority: AUTHORITY.to_owned(),
        };
        let registration_bytes = registration
            .canonical_bytes()
            .expect("canonical registration");
        let run = Wave5RunReferenceV1::from_registration(&registration, &registration_bytes)
            .expect("run reference");
        let context = commit_context(store, &run_id);
        store
            .commit_wave5_run_registration_v1(
                &Wave5RunRegistrationByteBundle {
                    registration: &registration_bytes,
                    build: &build,
                    source_tree: &tree,
                    configuration: &configuration,
                    budget: &budget,
                    privacy: &privacy,
                    daily_use_surface_profile: &surface,
                },
                &context,
            )
            .expect("commit the run registration");
        let plan = validate_provider_run_plan(template.bind_run(RegisteredRunPort {
            run_id: run.run_id.clone(),
            registration_digest: run.exact_registration.digest.as_str().to_owned(),
        }))
        .expect("valid exact C1 plan");
        let plan_bytes = plan.canonical_bytes().expect("canonical plan bytes");
        RegisteredRun {
            run,
            plan,
            plan_bytes,
        }
    }

    /// One durably committed and immediately burned activation, plus what a caller re-supplies.
    struct Burned {
        claim: joshi_store::ClaimedWave5C1Activation,
        run: Wave5RunReferenceV1,
        plan_bytes: Vec<u8>,
    }

    fn burn_activation(store: &mut SqliteStore, installation_id: &str, suffix: &str) -> Burned {
        burn_activation_with_cost(store, installation_id, suffix, &attempt_cost())
    }

    fn burn_activation_with_cost(
        store: &mut SqliteStore,
        installation_id: &str,
        suffix: &str,
        cost: &RuntimeAttemptCostPort,
    ) -> Burned {
        let registered = register_run_with_cost(store, suffix, cost);
        let plan = &registered.plan;
        let operation = &plan.operations()[0];
        let activation_id = format!("activation:c1-runtime-{suffix}");
        let activation = Wave5C1ActivationV1 {
            contract: "joshi.wave5.c1_activation.v1".to_owned(),
            schema_version: 1,
            activation_id: activation_id.clone(),
            installation_id: installation_id.to_owned(),
            run: plan.plan().run.clone(),
            exact_plan: ExactPlanClosureV1 {
                plan_id: plan.plan().plan_id.clone(),
                port_version: plan.plan().port_version.clone(),
                raw_exact_plan_sha256: digest_of(&registered.plan_bytes),
                raw_exact_plan_byte_length: registered.plan_bytes.len().to_string(),
                plan_template_digest: plan.plan_template_digest().to_owned(),
                final_plan_digest: plan.plan_digest().to_owned(),
            },
            budget: ExactC1BudgetProjectionV1 {
                hard_cap: plan.plan().hard_cap.clone(),
                attempt_cost: operation.plan.attempt_cost.clone(),
                max_elapsed_ms: plan.plan().max_elapsed_ms,
                max_ingress_bytes_per_second: plan.plan().max_ingress_bytes_per_second,
                max_in_flight_attempts: plan.plan().max_in_flight_attempts,
            },
            operations: vec![ExactSourceMethodProjectionV1 {
                source_key: operation.plan.source_key.clone(),
                method_key: operation.plan.method_key.clone(),
                source_contract_fingerprint: operation.canonical_contract_fingerprint.clone(),
                method_schema_fingerprint: operation.method_schema_fingerprint.clone(),
                coverage_family: operation.coverage_family.clone(),
                protection_domain: operation.protection_domain.clone(),
            }],
            wallet: PublicWalletPageV1 {
                address: WALLET.to_owned(),
                max_rows: MAX_ROWS,
            },
            commitment: FinalityCommitmentV1::Finalized,
            authority: AUTHORITY.to_owned(),
        };
        let activation_bytes = serde_json::to_vec(&activation).expect("canonical activation bytes");
        let context = commit_context(store, &format!("activation:{suffix}"));
        store
            .commit_wave5_c1_activation_v1(&activation_bytes, &registered.plan_bytes, &context)
            .expect("commit the C1 activation");
        let context = commit_context(store, &format!("claim:{suffix}"));
        let claim = store
            .claim_wave5_c1_activation_v1(
                &StableString::new(activation_id).expect("activation id"),
                &StableString::new(installation_id.to_owned()).expect("installation id"),
                &context,
            )
            .expect("burn the C1 activation exactly once");
        Burned {
            claim,
            run: registered.run,
            plan_bytes: registered.plan_bytes,
        }
    }

    /// One durable root carrying both a supervisor and its own catalog.
    struct Bench {
        root: TempDir,
        store: SqliteStore,
    }

    impl Bench {
        fn new() -> Self {
            let root = tempfile::tempdir().expect("tempdir");
            let store = open_store(&root.path().join("store"));
            Self { root, store }
        }

        fn config(&self) -> SupervisorConfig {
            supervisor_config(self.root.path())
        }

        fn supervisor(&self) -> Supervisor {
            Supervisor::open(self.config()).expect("open the supervisor")
        }

        fn supervisor_with_faults(&self, faults: Arc<dyn FaultInjector>) -> Supervisor {
            Supervisor::open_with_faults(self.config(), BTreeMap::new(), faults)
                .expect("open the supervisor")
        }

        fn burn(&mut self, supervisor: &Supervisor, suffix: &str) -> Burned {
            let installation = supervisor.installation_id().to_owned();
            burn_activation(&mut self.store, &installation, suffix)
        }

        fn burn_with_cost(
            &mut self,
            supervisor: &Supervisor,
            suffix: &str,
            cost: &RuntimeAttemptCostPort,
        ) -> Burned {
            let installation = supervisor.installation_id().to_owned();
            burn_activation_with_cost(&mut self.store, &installation, suffix, cost)
        }
    }

    fn open_runtime(supervisor: Supervisor, burned: Burned) -> Result<C1Runtime> {
        let admission = supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit the burned claim");
        C1Runtime::open(supervisor, admission, burned.run, &burned.plan_bytes, at())
    }

    /// Open, keeping the admission's own report so durable records can be compared to it field by
    /// field rather than by discriminator.
    fn open_runtime_with_report(
        supervisor: Supervisor,
        burned: Burned,
    ) -> (crate::DisabledC1AdmissionReport, C1Runtime) {
        let admission = supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit the burned claim");
        let report = admission.report().clone();
        let runtime = C1Runtime::open(supervisor, admission, burned.run, &burned.plan_bytes, at())
            .expect("open the C1 runtime");
        (report, runtime)
    }

    fn activation_bound_record(records: &[JournalRecord]) -> &JournalEvent {
        records
            .iter()
            .find_map(|record| match &record.event {
                event @ JournalEvent::C1ActivationBound { .. } => Some(event),
                _ => None,
            })
            .expect("a bound activation")
    }

    fn prepared_record(records: &[JournalRecord]) -> &JournalEvent {
        records
            .iter()
            .find_map(|record| match &record.event {
                event @ JournalEvent::C1RequestPrepared { .. } => Some(event),
                _ => None,
            })
            .expect("a prepared request")
    }

    fn reserved_record(records: &[JournalRecord]) -> AttemptReservation {
        records
            .iter()
            .find_map(|record| match &record.event {
                JournalEvent::C1AttemptReserved(reservation) => Some(reservation.clone()),
                _ => None,
            })
            .expect("a reserved attempt")
    }

    /// The C1 journal event discriminators in order, for exact ordering assertions.
    fn c1_event_names(records: &[JournalRecord]) -> Vec<&'static str> {
        records
            .iter()
            .filter_map(|record| match &record.event {
                JournalEvent::C1ActivationBound { .. } => Some("activation_bound"),
                JournalEvent::C1AttemptReserved(_) => Some("attempt_reserved"),
                JournalEvent::C1RequestPrepared { .. } => Some("request_prepared"),
                JournalEvent::C1IoStarted { .. } => Some("io_started"),
                JournalEvent::C1RawDurabilityRecorded { .. } => Some("raw_durability_recorded"),
                JournalEvent::C1AttemptAbandoned { .. } => Some("attempt_abandoned"),
                JournalEvent::C1BudgetSettled { .. } => Some("budget_settled"),
                JournalEvent::C1Stopped { .. } => Some("stopped"),
                _ => None,
            })
            .collect()
    }

    fn settled_usage(
        records: &[JournalRecord],
    ) -> Option<(AttemptBudgetUsage, RuntimeSettlementDisposition)> {
        records.iter().find_map(|record| match &record.event {
            JournalEvent::C1BudgetSettled {
                usage, disposition, ..
            } => Some((*usage, *disposition)),
            _ => None,
        })
    }

    /// A journal fault that fires exactly once, on the nth append that reaches the sync point.
    struct NthAppendFault {
        remaining: AtomicUsize,
    }

    impl NthAppendFault {
        fn armed(nth: usize) -> Arc<Self> {
            Arc::new(Self {
                remaining: AtomicUsize::new(nth),
            })
        }
    }

    impl FaultInjector for NthAppendFault {
        fn check(&self, point: FaultPoint) -> Result<()> {
            if point == FaultPoint::AfterJournalTemporarySync {
                let remaining = self.remaining.load(Ordering::SeqCst);
                if remaining > 0 && self.remaining.fetch_sub(1, Ordering::SeqCst) == 1 {
                    return Err(SupervisorError::Injected(point));
                }
            }
            Ok(())
        }
    }

    // ---------------------------------------------------------------------------------------
    // The ordered happy path
    // ---------------------------------------------------------------------------------------

    #[test]
    fn one_admitted_read_writes_every_durable_record_in_order_and_then_stops() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "happy");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");

        assert_eq!(
            c1_event_names(runtime.supervisor().journal_records()),
            vec!["activation_bound"],
            "opening binds the burned claim and nothing else"
        );

        let server = Loopback::start(vec![Step::Write(ok_page_response(ONE_ROW_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        let report = runtime.run_once(at(), 0).expect("one bounded C1 read");

        assert_eq!(
            c1_event_names(runtime.supervisor().journal_records()),
            vec![
                "activation_bound",
                "attempt_reserved",
                "request_prepared",
                "io_started",
                "raw_durability_recorded",
                "budget_settled",
                "stopped",
            ]
        );
        server.assert_exactly_one_request();

        assert_eq!(report.response_shape, C1ResponseShape::Page);
        assert_eq!(report.response_status, 200);
        assert_eq!(report.settlement, RuntimeSettlementDisposition::Observed);
        assert_eq!(report.response_body_bytes, ONE_ROW_PAGE.len() as u64);
        assert_eq!(
            report.response_body_digest,
            digest_of(ONE_ROW_PAGE.as_bytes())
        );
        assert_eq!(report.usage.requests, 1);
        assert_eq!(report.usage.pages, 1);
        assert_eq!(report.maximum_response_bytes, C1_MAX_RESPONSE_BODY_BYTES);
        assert_eq!(report.maximum_segment_bytes, derived_segment_bytes());
        assert_eq!(report.deadline_ms, ATTEMPT_WALL_MS);
        assert_eq!(report.authority, crate::AUTHORITY_CEILING);

        let rendered = serde_json::to_string(&report).expect("the report serializes");
        for needle in ["http", "://", "api.", "solana.com", WALLET] {
            assert!(
                !rendered.contains(needle),
                "the report leaks {needle:?}: {rendered}"
            );
        }

        let state = scan_c1_journal(runtime.supervisor().journal_records()).expect("replay");
        assert!(state.activation_bound());
        assert!(state.io_started && state.raw_durability_recorded);
        assert!(state.budget_settled && state.generation_stopped);
        assert!(!state.attempt_abandoned && !state.attempt_unresolved());
    }

    /// The one-shot flag, not the terminal flag, is what refuses the second call.
    ///
    /// `run_once` spends the one-shot before anything can mark the runtime terminal, so a spent
    /// runtime is the state a caller actually meets, and the refusal has to say so: a read that
    /// *completed* is not "terminal after a prior boundary failure". Pinning the exact message is
    /// the point — asserting merely that some error came back leaves the two guards
    /// indistinguishable, which is how the flag went untested in the first place.
    /// The whole ordered path opens exactly one connection, and it carries the canonical body.
    ///
    /// The listener accepts in a loop and records every connection, so a second request — which a
    /// spent client can only make by opening one — would show up here. This is the property the
    /// entire C1 design exists to hold, so it is asserted directly on the observed connections
    /// rather than only through a "no further request" drain.
    #[test]
    fn the_one_admitted_read_opens_exactly_one_connection_carrying_the_canonical_body() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "one-connection");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(ONE_ROW_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).expect("one bounded C1 read");
        drop(runtime);

        let observed = server.observed_requests();
        assert_eq!(
            observed.len(),
            1,
            "the one admitted read issues exactly one request, and this is the assertion that \
             can see a second one"
        );
        assert_eq!(request_line(&observed[0]), "POST / HTTP/1.1");
        assert_eq!(
            request_body(&observed[0]),
            canonical_public_solana_c1_request(WALLET, MAX_ROWS)
                .expect("canonical body")
                .body,
            "and the bytes on the wire are the canonical request, not something re-encoded"
        );
    }

    #[test]
    fn a_second_run_once_after_a_completed_read_is_refused_as_spent_and_issues_no_request() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "twice");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).expect("one bounded C1 read");

        let error = runtime.run_once(at(), 0).unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message == "the one admitted C1 read has already been performed"),
            "a completed read is refused as spent, never as a boundary failure: {error}"
        );
        // And again, so the flag is not a one-time latch that clears itself.
        assert!(runtime.run_once(at(), 0).is_err());
        server.assert_exactly_one_request();
    }

    /// A read that died past the I/O boundary is equally spent, and equally never retried.
    #[test]
    fn a_second_run_once_after_a_post_io_failure_is_also_refused_as_spent() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "twice-failed");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(NON_CONFORMANT_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).unwrap_err();

        let error = runtime.run_once(at(), 0).unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message == "the one admitted C1 read has already been performed"),
            "a failed read is spent too: {error}"
        );
        server.assert_exactly_one_request();
    }

    /// The binding record is the admission report, verbatim, plus the two derived ceilings.
    ///
    /// Checking only that a `C1ActivationBound` record exists leaves every identity and digest in
    /// it free: a binding that named a different activation, or that swapped the template and
    /// final plan digests, would look identical to a discriminator sequence. This compares the
    /// whole payload against the report the admission actually carried.
    #[test]
    fn the_activation_binding_record_carries_the_admission_report_verbatim() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let installation = supervisor.installation_id().to_owned();
        let burned = bench.burn(&supervisor, "bound-payload");
        let (report, runtime) = open_runtime_with_report(supervisor, burned);

        let records = runtime.supervisor().journal_records();
        assert_eq!(c1_event_names(records), vec!["activation_bound"]);
        let JournalEvent::C1ActivationBound {
            activation_id,
            installation_id,
            run_registration_id,
            run_registration_digest,
            activation_digest,
            exact_plan_digest,
            plan_id,
            plan_template_digest,
            final_plan_digest,
            activation_commit_sequence,
            claim_commit_sequence,
            claim_commit_digest,
            maximum_response_bytes,
            maximum_segment_bytes,
        } = activation_bound_record(records)
        else {
            unreachable!("the record was just matched as a bound activation")
        };
        assert_eq!(activation_id, &report.activation_id);
        assert_eq!(installation_id, &report.installation_id);
        assert_eq!(
            installation_id, &installation,
            "the binding names the journal it was written to"
        );
        assert_eq!(run_registration_id, &report.run_registration_id);
        assert_eq!(run_registration_digest, &report.run_registration_digest);
        assert_eq!(activation_digest, &report.activation_digest);
        assert_eq!(exact_plan_digest, &report.exact_plan_digest);
        assert_eq!(plan_id, &report.plan_id);
        assert_eq!(plan_template_digest, &report.plan_template_digest);
        assert_eq!(final_plan_digest, &report.final_plan_digest);
        assert_ne!(
            plan_template_digest, final_plan_digest,
            "the two plan digests are distinct values, so swapping them is observable"
        );
        assert_eq!(
            *activation_commit_sequence,
            report.activation_commit_sequence
        );
        assert_eq!(*claim_commit_sequence, report.claim_commit_sequence);
        assert_eq!(claim_commit_digest, &report.claim_commit_digest);
        assert_eq!(*maximum_response_bytes, C1_MAX_RESPONSE_BODY_BYTES);
        assert_eq!(*maximum_segment_bytes, derived_segment_bytes());
        assert!(
            *claim_commit_sequence > *activation_commit_sequence,
            "the burn strictly follows the activation it consumed"
        );
    }

    /// The prepared-request record and the run report, field by field.
    ///
    /// Both are digest-only accounts of one request, and both were previously unasserted beyond
    /// their discriminators. The endpoint and body digests are recomputed here from the listener
    /// address and the canonical request bytes, so a record that digested something else fails.
    #[test]
    #[allow(clippy::too_many_lines)] // One flat account of one attempt, asserted field by field.
    fn the_prepared_request_record_and_the_run_report_carry_the_exact_identities_and_digests() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let installation = supervisor.installation_id().to_owned();
        let burned = bench.burn(&supervisor, "payload");
        let run_id = burned.run.run_id.clone();
        let (admission, mut runtime) = open_runtime_with_report(supervisor, burned);

        let server = Loopback::start(vec![Step::Write(ok_page_response(
            ONE_ROW_PAGE,
            "Retry-After: 3\r\nSet-Cookie: session=secret\r\n",
        ))]);
        let base_url = server.base_url();
        runtime.bind_loopback_for_tests(base_url.clone());
        let report = runtime.run_once(at(), 0).expect("one bounded C1 read");

        let expected_body = canonical_public_solana_c1_request(WALLET, MAX_ROWS)
            .expect("the canonical C1 request body");
        let expected_endpoint_digest = digest_of(base_url.as_bytes());
        let expected_body_digest = digest_of(&expected_body.body);

        let records = runtime.supervisor().journal_records();
        let reservation = reserved_record(records);
        let JournalEvent::C1RequestPrepared {
            reservation_id,
            endpoint_digest,
            request_body_digest,
            request_body_byte_length,
            method_key,
            maximum_response_bytes,
            deadline_ms,
        } = prepared_record(records)
        else {
            unreachable!("the record was just matched as a prepared request")
        };
        assert_eq!(reservation_id, &reservation.reservation_id);
        assert_eq!(endpoint_digest, &expected_endpoint_digest);
        assert_ne!(
            endpoint_digest,
            &digest_of(crate::c1::transport::C1_ENDPOINT_URL.as_bytes()),
            "a record produced against a private listener is visibly not a public read"
        );
        assert_eq!(request_body_digest, &expected_body_digest);
        assert_eq!(
            *request_body_byte_length,
            expected_body.body.len() as u64,
            "the recorded length is the exact canonical body length"
        );
        assert_eq!(method_key, C1_OPERATION_KEY);
        assert_eq!(*maximum_response_bytes, C1_MAX_RESPONSE_BODY_BYTES);
        assert_eq!(*deadline_ms, ATTEMPT_WALL_MS);

        // And the report is an account of the same one attempt, not a second opinion.
        assert_eq!(report.contract, C1_CONTRACT_VERSION);
        assert_eq!(report.installation_id, installation);
        assert_eq!(report.activation_id, admission.activation_id);
        assert_eq!(report.run_id, admission.run_registration_id);
        assert_eq!(report.run_id, run_id);
        assert_eq!(
            report.reservation_id,
            reservation.reservation_id.to_string()
        );
        assert_eq!(report.source_key, C1_SOURCE_KEY);
        assert_eq!(report.operation_key, C1_OPERATION_KEY);
        assert_eq!(
            report.generation, 1,
            "the one-shot generation is always its first"
        );
        assert_eq!(
            report.generation,
            reservation.generation.get(),
            "and it is the generation the reserved attempt recorded"
        );
        assert_eq!(
            report.attempt_ordinal, 1,
            "the attempt ordinal within that generation is always 1"
        );
        assert_eq!(report.attempt_ordinal, reservation.attempt_ordinal);
        assert_eq!(report.endpoint_digest, expected_endpoint_digest);
        assert_eq!(report.request_body_digest, expected_body_digest);
        assert_eq!(
            report.request_body_byte_length,
            expected_body.body.len() as u64
        );
        assert_eq!(report.maximum_response_bytes, C1_MAX_RESPONSE_BODY_BYTES);
        assert_eq!(report.maximum_segment_bytes, derived_segment_bytes());
        assert_eq!(report.deadline_ms, ATTEMPT_WALL_MS);
        assert_eq!(report.response_status, 200);
        assert_eq!(report.response_body_bytes, ONE_ROW_PAGE.len() as u64);
        assert_eq!(
            report.response_body_digest,
            digest_of(ONE_ROW_PAGE.as_bytes())
        );
        assert_eq!(
            report.retained_header_names,
            vec!["retry-after".to_owned()],
            "the retained names are the bounded allowlist reduction and carry no cookie"
        );
        assert_eq!(report.response_shape, C1ResponseShape::Page);
        assert!(report.elapsed_ms < ATTEMPT_WALL_MS);
        assert_eq!(report.usage.requests, 1);
        assert_eq!(report.usage.pages, 1);
        assert_eq!(report.usage.ingress_bytes, report.response_body_bytes);
        assert_eq!(report.usage.provider_credits, 0);
        assert_eq!(
            report.usage.elapsed_ms, report.elapsed_ms,
            "the settled elapsed is the measured elapsed, not a second reading"
        );
        assert_eq!(report.settlement, RuntimeSettlementDisposition::Observed);
        assert_eq!(report.authority, crate::AUTHORITY_CEILING);

        // The durable settlement record has to agree with the report it was derived from.
        let (usage, disposition) = settled_usage(records).expect("a durable settlement");
        assert_eq!(usage, report.usage);
        assert_eq!(disposition, report.settlement);

        // The local receipt is the one retained page, and its length is the settled durable use.
        report
            .local_spool
            .validate()
            .expect("a valid local receipt");
        assert_eq!(
            parse_wire_u64(&report.local_spool.exact_segment.byte_length).expect("segment length"),
            report.usage.durable_bytes
        );
        assert!(report.usage.durable_bytes <= derived_segment_bytes());
    }

    #[test]
    fn an_empty_result_array_is_retained_and_is_never_absence() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "empty");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        let report = runtime.run_once(at(), 0).expect("one bounded C1 read");
        assert_eq!(report.response_shape, C1ResponseShape::Page);
        assert_eq!(report.response_body_bytes, EMPTY_PAGE.len() as u64);
        // The one durable batch this run produced carries no coverage of any kind: the adapter
        // has no way to emit one, and this is the assertion that keeps that true end to end.
        let batches = runtime
            .supervisor()
            .spool()
            .list_segments()
            .expect("list segments");
        assert_eq!(batches.len(), 1, "one retained page, and no gap beside it");
    }

    #[test]
    fn a_chunked_page_with_no_declared_length_still_completes_the_ordered_path() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "chunked");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(chunked_response(
            &[r#"{"jsonrpc":"2.0","#, r#""id":1,"result":[]}"#],
            "",
            true,
        ))]);
        runtime.bind_loopback_for_tests(server.base_url());
        let report = runtime.run_once(at(), 0).expect("one bounded C1 read");
        assert_eq!(report.response_body_bytes, EMPTY_PAGE.len() as u64);
    }

    #[test]
    fn a_provider_refusal_is_retained_and_classified_but_is_never_a_page() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "refusal");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(REFUSAL_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        let report = runtime
            .run_once(at(), 0)
            .expect("a typed refusal is a real answer");
        assert_eq!(report.response_shape, C1ResponseShape::ProviderRefusal);
        assert_eq!(
            c1_event_names(runtime.supervisor().journal_records()),
            vec![
                "activation_bound",
                "attempt_reserved",
                "request_prepared",
                "io_started",
                "raw_durability_recorded",
                "budget_settled",
                "stopped",
            ]
        );
    }

    // ---------------------------------------------------------------------------------------
    // Post-I/O failures: gap, conservative maximum settlement, stop
    // ---------------------------------------------------------------------------------------

    fn assert_terminal_gap_with_maximum_settlement(runtime: &C1Runtime) {
        assert_eq!(
            c1_event_names(runtime.supervisor().journal_records()),
            vec![
                "activation_bound",
                "attempt_reserved",
                "request_prepared",
                "io_started",
                "attempt_abandoned",
                "stopped",
                "budget_settled",
            ]
        );
        let (usage, disposition) =
            settled_usage(runtime.supervisor().journal_records()).expect("a durable settlement");
        assert_eq!(disposition, RuntimeSettlementDisposition::TerminalViolation);
        assert_eq!(usage.requests, 1);
        assert_eq!(usage.pages, 1);
        assert_eq!(
            usage.ingress_bytes, C1_MAX_RESPONSE_BODY_BYTES,
            "a post-I/O failure is charged the full reserved ingress, never what was observed"
        );
        assert!(usage.durable_bytes >= derived_segment_bytes());
        assert_eq!(usage.elapsed_ms, ATTEMPT_WALL_MS);
    }

    #[test]
    fn a_refused_status_after_io_becomes_a_durable_gap_charged_at_the_maximum() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "status");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(
            b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}".to_vec(),
        )]);
        runtime.bind_loopback_for_tests(server.base_url());
        let error = runtime.run_once(at(), 0).unwrap_err();
        assert!(
            format!("{error}").contains("503"),
            "the refusal names the status and nothing else: {error}"
        );
        assert_terminal_gap_with_maximum_settlement(&runtime);
        server.assert_exactly_one_request();
    }

    #[test]
    fn a_non_conformant_body_after_io_becomes_a_durable_gap_charged_at_the_maximum() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "shape");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(NON_CONFORMANT_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).unwrap_err();
        assert_terminal_gap_with_maximum_settlement(&runtime);
    }

    #[test]
    fn an_expired_deadline_after_io_becomes_a_durable_gap_and_never_a_retry() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "deadline");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Sleep(Duration::from_millis(
            ATTEMPT_WALL_MS * 3,
        ))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).unwrap_err();
        assert_terminal_gap_with_maximum_settlement(&runtime);
        server.assert_exactly_one_request();
    }

    // ---------------------------------------------------------------------------------------
    // The global one-read cap
    // ---------------------------------------------------------------------------------------

    #[test]
    fn a_second_activation_for_the_same_installation_is_refused_by_the_global_cap() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let first = bench.burn(&supervisor, "cap-one");
        let mut runtime = open_runtime(supervisor, first).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).expect("one bounded C1 read");
        drop(runtime);

        // A second run registration with a distinct plan mints a fresh activation and a fresh
        // burnable claim for the same wallet and budget: the store's one-shot is per activation.
        // The durable journal is what caps the total, and this is where that is proved.
        let supervisor = bench.supervisor();
        let second = bench.burn(&supervisor, "cap-two");
        let error = open_runtime(supervisor, second).unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message.contains("one read per installation")),
            "the journal caps the installation, not the activation: {error}"
        );
        let second_server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        second_server.assert_no_further_request();
    }

    #[test]
    fn a_journal_that_already_started_io_admits_no_new_runtime_and_issues_no_request() {
        let mut bench = Bench::new();
        // Cut the journal at the durability append, which is the first append after the request.
        let faults = NthAppendFault::armed(6);
        let supervisor = bench.supervisor_with_faults(faults);
        let burned = bench.burn(&supervisor, "io-cut");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).unwrap_err();
        drop(runtime);
        server.assert_exactly_one_request();

        // Reopen with a fresh, healthy supervisor. Restart reconciliation must resolve the
        // interrupted attempt without any request, and no new runtime may be constructed at all.
        let mut supervisor = bench.supervisor();
        let state = reconcile_c1_restart(&mut supervisor, at()).expect("restart reconciliation");
        assert!(state.io_started);
        assert!(
            !state.attempt_unresolved(),
            "the attempt is resolved exactly once"
        );
        assert!(state.budget_settled && state.generation_stopped);
        assert!(
            state.raw_durability_recorded,
            "a segment fsynced before its journal record is rediscovered, never gapped"
        );
        assert_eq!(
            state.settlement,
            Some(RuntimeSettlementDisposition::RecoveredAfterIoWorstCase)
        );

        let next = bench.burn(&supervisor, "io-cut-two");
        let error = open_runtime(supervisor, next).unwrap_err();
        assert!(matches!(&error, SupervisorError::InvalidState(message)
                if message.contains("one read per installation")));
        server.assert_no_further_request();
    }

    // ---------------------------------------------------------------------------------------
    // Crash at every journal prefix
    // ---------------------------------------------------------------------------------------

    /// Cut the journal at each successive append and prove the durable outcome stays honest.
    ///
    /// Append 1 is the supervisor's own `SupervisorStarted`; the C1 appends follow it in the order
    /// the state machine writes them, so the cut index names the record being written.
    ///
    /// The injected cut lands *after* the record's own bytes are fsynced and *before* its rename,
    /// which is the honest crash model for this journal: the bytes are durable, and reopening
    /// completes the rename. The in-process call still fails, so every cut is exactly the
    /// ambiguous case the state machine is built around — the caller cannot tell whether the
    /// record survived, and must therefore charge conservatively rather than refund.
    ///
    /// For every cut the run must fail, the loopback must see at most one request, restart
    /// reconciliation must close the lifecycle without a request, and a further runtime must be
    /// refused once an activation binding is durable.
    #[test]
    fn a_crash_at_every_journal_prefix_leaves_an_honest_resolvable_lifecycle() {
        // (cut, whether the one request is expected to have been issued before the cut)
        let cuts = [
            (2_usize, false), // C1ActivationBound
            (3, false),       // C1AttemptReserved
            (4, false),       // C1RequestPrepared
            (5, false),       // C1IoStarted
            (6, true),        // C1RawDurabilityRecorded
            (7, true),        // C1BudgetSettled
            (8, true),        // C1Stopped
        ];
        for (cut, expect_request) in cuts {
            let mut bench = Bench::new();
            let supervisor = bench.supervisor_with_faults(NthAppendFault::armed(cut));
            let installation = supervisor.installation_id().to_owned();
            let burned = bench.burn(&supervisor, &format!("cut-{cut}"));
            let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
            let outcome = match open_runtime(supervisor, burned) {
                Ok(mut runtime) => {
                    runtime.bind_loopback_for_tests(server.base_url());
                    let outcome = runtime.run_once(at(), 0);
                    drop(runtime);
                    outcome.map(|_| ())
                }
                Err(error) => {
                    assert_eq!(cut, 2, "only the activation binding is cut before run_once");
                    Err(error)
                }
            };
            assert!(outcome.is_err(), "cut {cut} must not report success");
            if expect_request {
                server.assert_exactly_one_request();
            } else {
                server.assert_no_further_request();
            }

            // The claim is burned either way. Authority is never recreated or refunded.
            //
            // The re-claim uses this bench's *real* installation id, which `journal.rs` derives
            // from the root path, pid, and nanos and then persists. A literal placeholder would
            // never be it, the store would refuse on its installation-mismatch branch, and the
            // one-shot burn this assertion is named for would never be reached at all — so the
            // refusal is matched exactly rather than merely asserted to be some error.
            let activation_id = StableString::new(format!("activation:c1-runtime-cut-{cut}"))
                .expect("activation id");
            let context = commit_context(&bench.store, &format!("reclaim-{cut}"));
            let Err(refusal) = bench.store.claim_wave5_c1_activation_v1(
                &activation_id,
                &StableString::new(installation.clone()).expect("installation id"),
                &context,
            ) else {
                panic!("cut {cut}: a burned activation is never re-claimable");
            };
            assert!(
                matches!(&refusal, joshi_store::StoreError::IdentityConflict { kind, identity }
                    if *kind == "Wave 5 C1 activation claim"
                        && identity == activation_id.as_str()),
                "cut {cut}: the burn is what refuses, not an installation mismatch: {refusal}"
            );
            // And the durable claim receipt is still exactly the one burn that happened.
            assert!(
                bench
                    .store
                    .load_wave5_c1_activation_claim_receipt_v1(&activation_id)
                    .expect("claim receipt readback")
                    .is_some(),
                "cut {cut}: the burned claim stays burned"
            );

            let mut supervisor = bench.supervisor();
            let state = reconcile_c1_restart(&mut supervisor, at()).expect("reconcile");
            assert!(
                state.activation_bound(),
                "cut {cut}: the fsynced binding is recovered on reopen"
            );
            assert!(
                !state.attempt_unresolved(),
                "cut {cut} leaves an unresolved attempt"
            );
            if state.reservation_id.is_some() {
                assert!(
                    state.budget_settled,
                    "cut {cut} leaves an unsettled attempt"
                );
                assert!(
                    state.generation_stopped,
                    "cut {cut} leaves a live generation"
                );
                let settlement = state.settlement.expect("a durable disposition");
                if state.io_started {
                    assert_ne!(
                        settlement,
                        RuntimeSettlementDisposition::RefundedBeforeIo,
                        "cut {cut} refunded an attempt whose journal proves I/O started"
                    );
                }
            }
            // Whatever happened, the installation has spent its one read.
            let next = bench.burn(&supervisor, &format!("cut-{cut}-again"));
            assert!(
                open_runtime(supervisor, next).is_err(),
                "cut {cut} must still refuse a second runtime"
            );
            server.assert_no_further_request();
        }
    }

    // ---------------------------------------------------------------------------------------
    // Refusals at open
    // ---------------------------------------------------------------------------------------

    /// The supervisor is opened *with* the undersized ceiling rather than handed a mutated copy of
    /// its configuration, because `C1Runtime::open` reads `Supervisor::spool_config` and a caller
    /// has no way to describe a spool other than the live one.
    #[test]
    fn a_spool_that_cannot_host_the_derived_segment_is_refused_before_any_socket() {
        let mut bench = Bench::new();
        let mut config = bench.config();
        config.spool.max_segment_bytes = derived_segment_bytes() - 1;
        config.spool.max_total_bytes = config.spool.max_segment_bytes * 8;
        config.spool.control_reserve_bytes = config.spool.max_segment_bytes;
        config.maximum_spool_bytes_per_utc_day = config.spool.max_segment_bytes * 4;
        let supervisor = Supervisor::open(config.clone()).expect("open an undersized supervisor");
        let burned = bench.burn(&supervisor, "small-spool");
        let error = open_runtime(supervisor, burned).unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidConfig(message)
                if message.contains("cannot host a C1 read")),
            "an undersized segment ceiling is refused: {error}"
        );
    }

    #[test]
    fn an_admission_bound_to_another_installation_is_refused() {
        let mut host = Bench::new();
        let host_supervisor = host.supervisor();
        let burned = host.burn(&host_supervisor, "foreign");
        let admission = host_supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit under the host installation");
        drop(host_supervisor);

        let guest = Bench::new();
        let guest_supervisor = guest.supervisor();
        let error = C1Runtime::open(
            guest_supervisor,
            admission,
            burned.run,
            &burned.plan_bytes,
            at(),
        )
        .unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message.contains("different journal installation")),
            "a foreign installation is refused: {error}"
        );
    }

    /// A run reference that does not validate never reaches the durable binding.
    ///
    /// The mutated field is a *component document* identity, so the reference still names the run
    /// the admission closed over and still carries its registration digest: the closure equality
    /// below this guard passes. Only `Wave5RunReferenceV1::validate` refuses it, so removing that
    /// call binds a burned activation to a malformed reference rather than refusing.
    #[test]
    fn a_run_reference_that_does_not_validate_is_refused_before_any_binding() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let mut burned = bench.burn(&supervisor, "bad-run-ref");
        burned.run.build.document_id = String::new();
        let admission = supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit the burned claim");
        let error = C1Runtime::open(supervisor, admission, burned.run, &burned.plan_bytes, at())
            .unwrap_err();
        assert!(
            matches!(&error, SupervisorError::Admission(_))
                && format!("{error}").contains("documentId"),
            "the malformed component document is what refuses it, not the closure equality \
             below: {error}"
        );
    }

    /// Exact plan bytes for the *same* run, but a different plan, are refused.
    ///
    /// `substituted_exact_plan_bytes_are_refused` swaps in another run's plan, which disagrees
    /// with the admission on the run identity as well. This one keeps the run identity and digest
    /// intact and changes only the plan, so the plan half of the closure is what has to refuse it.
    #[test]
    fn exact_plan_bytes_for_the_same_run_but_a_different_plan_are_refused() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "same-run");
        let other = validate_provider_run_plan(plan_template("same-run-other").bind_run(
            RegisteredRunPort {
                run_id: burned.run.run_id.clone(),
                registration_digest: burned.run.exact_registration.digest.as_str().to_owned(),
            },
        ))
        .expect("a second valid plan over the same registered run");
        let other_bytes = other.canonical_bytes().expect("canonical plan bytes");
        assert_eq!(
            other.plan().run,
            parse_provider_run_plan_exact(&burned.plan_bytes)
                .expect("the admitted plan")
                .plan()
                .run,
            "the substituted plan closes over exactly the same registered run"
        );
        let admission = supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit the burned claim");
        let error =
            C1Runtime::open(supervisor, admission, burned.run, &other_bytes, at()).unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message.contains("do not reproduce the admission")),
            "a different plan for the same run is still not the admitted closure: {error}"
        );
    }

    /// An attempt that reserves less than the admitted page can physically need is refused.
    ///
    /// Refusing here is the whole point: the alternative is a reservation that is guaranteed to be
    /// violated once the socket is open, which is exactly the state the post-I/O path can only
    /// resolve by charging a maximum and stopping. Both dimensions are checked separately so
    /// deleting either half of the condition fails.
    #[test]
    fn an_attempt_budget_that_cannot_absorb_the_admitted_page_is_refused_before_any_socket() {
        for (label, cost) in [
            (
                "ingress",
                RuntimeAttemptCostPort {
                    worst_case: RuntimeBudgetPort {
                        ingress_bytes: C1_MAX_RESPONSE_BODY_BYTES - 1,
                        ..attempt_cost().worst_case
                    },
                    max_overshoot: zero_budget(),
                },
            ),
            (
                "durable",
                RuntimeAttemptCostPort {
                    worst_case: RuntimeBudgetPort {
                        durable_bytes: derived_segment_bytes() - 1,
                        ..attempt_cost().worst_case
                    },
                    max_overshoot: zero_budget(),
                },
            ),
        ] {
            let mut bench = Bench::new();
            let supervisor = bench.supervisor();
            let burned = bench.burn_with_cost(&supervisor, &format!("thin-{label}"), &cost);
            let error = open_runtime(supervisor, burned).unwrap_err();
            assert!(
                matches!(&error, SupervisorError::InvalidConfig(message)
                    if message.contains("the admitted page can physically need")),
                "a {label} reservation under the admitted page is refused: {error}"
            );
        }
    }

    /// The plan-shape gate, exercised as the function it is.
    ///
    /// It is not reachable from a store-produced admission — `parse_c1_activation_exact` requires
    /// the same shape over the same plan bytes before an activation can be committed — so this
    /// calls it directly with plans `joshi_sources` itself accepts. Three of its clauses can be
    /// isolated that way; the rest (`max_in_flight_attempts`, one operation, one attempt per
    /// operation) are conditions the plan validator refuses outright, so no validated plan can
    /// carry them and no test can reach them.
    #[test]
    fn the_c1_plan_shape_gate_refuses_every_plan_shape_it_can_be_handed() {
        let admitted = fixture_plan("shape-ok", plan_template("shape-ok"));
        admit_c1_plan_shape(&admitted).expect("the isolated one-page C1 shape is admitted");

        // A C0 plan: the wrong profile and, with it, the wrong built-in execution disposition.
        let synthetic = fixture_plan(
            "shape-c0",
            ProviderRunPlanTemplate {
                port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
                plan_id: "c1-runtime-shape-c0".to_owned(),
                profile: CanaryProfilePort::C0,
                hard_cap: RuntimeBudgetPort {
                    requests: 1,
                    pages: 1,
                    ingress_bytes: 1_024,
                    durable_bytes: 1_024,
                    wall_millis: ATTEMPT_WALL_MS,
                    ..zero_budget()
                },
                max_elapsed_ms: ATTEMPT_WALL_MS,
                max_ingress_bytes_per_second: None,
                max_in_flight_attempts: 1,
                operations: vec![ProviderOperationPlan {
                    // The sealed C0 pair. `joshi_sources` keeps the two key strings private, so they
                    // are named literally here; the fingerprints beside them are exported and would
                    // fail the contract lookup if the pair ever changed.
                    source_key: "synthetic.local".to_owned(),
                    method_key: "emit".to_owned(),
                    source_contract_fingerprint:
                        joshi_sources::SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                    method_schema_fingerprint: joshi_sources::SEALED_C0_METHOD_SCHEMA_FINGERPRINT
                        .to_owned(),
                    operation: ProviderOperation::SyntheticEmit,
                    generation: 1,
                    max_attempts: 1,
                    scope: ProviderScopePort::SyntheticScenario {
                        scenario_id: "scenario:shape".to_owned(),
                    },
                    attempt_cost: RuntimeAttemptCostPort {
                        worst_case: RuntimeBudgetPort {
                            requests: 1,
                            pages: 1,
                            ingress_bytes: 1_024,
                            durable_bytes: 1_024,
                            wall_millis: ATTEMPT_WALL_MS,
                            ..zero_budget()
                        },
                        max_overshoot: zero_budget(),
                    },
                }],
            },
        );
        assert!(
            matches!(admit_c1_plan_shape(&synthetic), Err(SupervisorError::InvalidState(message))
                if message.contains("isolated one-page public-Solana shape")),
            "a C0 plan is not the C1 shape"
        );

        // A C1 plan carrying an ingress-rate bound, which the C1 path compiles in no way to honour.
        let mut rated = plan_template("shape-rated");
        rated.max_ingress_bytes_per_second = Some(1_024);
        let rated = fixture_plan("shape-rated", rated);
        assert!(
            matches!(admit_c1_plan_shape(&rated), Err(SupervisorError::InvalidState(message))
                if message.contains("isolated one-page public-Solana shape")),
            "a rate-limited plan is not the C1 shape"
        );

        // A C1 plan whose one operation is not its first generation.
        let mut regenerated = plan_template("shape-generation");
        regenerated.operations[0].generation = 2;
        let regenerated = fixture_plan("shape-generation", regenerated);
        assert!(
            matches!(admit_c1_plan_shape(&regenerated),
                Err(SupervisorError::InvalidState(message))
                if message.contains("one bounded signature-page read")),
            "a later generation is not the one admitted read"
        );
    }

    /// The economic-spend refusal, exercised as the function it is.
    ///
    /// Neither `joshi_sources::validate_provider_run_plan` nor `parse_c1_activation_exact` will
    /// admit a plan carrying provider currency or chain-native atoms, so no burned activation can
    /// reach this. It is still the code that decides what a C1 attempt may cost, so it is called
    /// directly with a cost the validators would have refused.
    #[test]
    fn a_c1_attempt_carrying_economic_spend_is_refused_by_the_execution_envelope() {
        let plan = &fixture_plan("economic", plan_template("economic"));
        let (limits, claim) = execution_envelope(plan, &plan.operations()[0].plan.attempt_cost)
            .expect("the admitted envelope");
        assert_eq!(limits.maximum_requests, plan.plan().hard_cap.requests);
        assert_eq!(limits.maximum_elapsed_ms, plan.plan().max_elapsed_ms);
        assert_eq!(claim.maximum_ingress_bytes, C1_MAX_RESPONSE_BODY_BYTES);
        assert_eq!(claim.maximum_provider_credits, 0);

        for (label, spend) in [("provider currency", true), ("chain-native atoms", false)] {
            let mut worst = attempt_cost().worst_case;
            if spend {
                worst.provider_currency_minor.insert("usd".to_owned(), 1);
            } else {
                worst.chain_native_atoms.insert("sol".to_owned(), 1);
            }
            let cost = RuntimeAttemptCostPort {
                worst_case: worst,
                max_overshoot: zero_budget(),
            };
            assert!(
                matches!(execution_envelope(plan, &cost),
                    Err(SupervisorError::InvalidValue(message))
                    if message.contains("cannot carry economic spend")),
                "{label} is never an admitted C1 attempt cost"
            );
        }
    }

    #[test]
    fn substituted_exact_plan_bytes_are_refused() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "plan-one");
        let other = register_run(&mut bench.store, "plan-two");
        let admission = supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit the burned claim");
        let error = C1Runtime::open(supervisor, admission, burned.run, &other.plan_bytes, at())
            .unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message.contains("do not reproduce the admission")),
            "substituted plan bytes are refused: {error}"
        );
    }

    #[test]
    fn a_substituted_run_reference_is_refused() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "run-one");
        let other = register_run(&mut bench.store, "run-two");
        let admission = supervisor
            .admit_claimed_wave5_c1_disabled(burned.claim)
            .expect("admit the burned claim");
        let error = C1Runtime::open(supervisor, admission, other.run, &burned.plan_bytes, at())
            .unwrap_err();
        assert!(
            matches!(&error, SupervisorError::InvalidState(message)
                if message.contains("not the registration the C1 admission closed over")),
            "a substituted run reference is refused: {error}"
        );
    }

    // ---------------------------------------------------------------------------------------
    // Replay
    // ---------------------------------------------------------------------------------------

    fn record(ordinal: u64, event: JournalEvent) -> JournalRecord {
        JournalRecord {
            contract: crate::SUPERVISOR_CONTRACT_VERSION.to_owned(),
            ordinal,
            recorded_at: at(),
            event,
            authority: crate::AUTHORITY_CEILING.to_owned(),
        }
    }

    fn activation_bound_event() -> JournalEvent {
        JournalEvent::C1ActivationBound {
            activation_id: "activation:replay".to_owned(),
            installation_id: "inst-00000000000000000000000000000000".to_owned(),
            run_registration_id: "run:replay".to_owned(),
            run_registration_digest: format!("sha256:{}", "a".repeat(64)),
            activation_digest: format!("sha256:{}", "b".repeat(64)),
            exact_plan_digest: format!("sha256:{}", "c".repeat(64)),
            plan_id: "plan:replay".to_owned(),
            plan_template_digest: format!("sha256:{}", "d".repeat(64)),
            final_plan_digest: format!("sha256:{}", "e".repeat(64)),
            activation_commit_sequence: 1,
            claim_commit_sequence: 2,
            claim_commit_digest: format!("sha256:{}", "f".repeat(64)),
            maximum_response_bytes: C1_MAX_RESPONSE_BODY_BYTES,
            maximum_segment_bytes: derived_segment_bytes(),
        }
    }

    /// Take the exact reserved-attempt record a real run wrote, so replay is tested against the
    /// shape the state machine actually produces rather than a hand-built approximation.
    fn reserved_record_from_a_real_run() -> (Vec<JournalRecord>, AttemptReservation) {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "replay-source");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).expect("one bounded C1 read");
        let records: Vec<JournalRecord> = runtime.supervisor().journal_records().to_vec();
        let reservation = records
            .iter()
            .find_map(|record| match &record.event {
                JournalEvent::C1AttemptReserved(reservation) => Some(reservation.clone()),
                _ => None,
            })
            .expect("a reserved attempt");
        (records, reservation)
    }

    #[test]
    fn replay_of_a_real_completed_run_reproduces_its_lifecycle() {
        let (records, _) = reserved_record_from_a_real_run();
        let state = scan_c1_journal(&records).expect("replay a real journal");
        assert!(state.activation_bound());
        assert!(state.request_prepared && state.io_started);
        assert!(state.raw_durability_recorded && state.budget_settled);
        assert!(state.generation_stopped);
        assert_eq!(
            state.maximum_response_bytes,
            Some(C1_MAX_RESPONSE_BODY_BYTES)
        );
        assert_eq!(state.maximum_segment_bytes, Some(derived_segment_bytes()));
    }

    /// Every C1 record a real gapped run writes, for the abandonment shape replay must accept.
    fn records_from_a_real_gapped_run() -> Vec<JournalRecord> {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "replay-gap-source");
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(NON_CONFORMANT_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).unwrap_err();
        runtime.supervisor().journal_records().to_vec()
    }

    /// The first record of the named C1 family, taken from a real journal.
    fn c1_event(records: &[JournalRecord], name: &str) -> JournalEvent {
        records
            .iter()
            .find(|record| c1_event_names(std::slice::from_ref(record)) == vec![name])
            .unwrap_or_else(|| panic!("a real journal carrying a {name} record"))
            .event
            .clone()
    }

    /// Rebuild a journal slice from named C1 records, in exactly the order given.
    fn c1_slice(records: &[JournalRecord], names: &[&str]) -> Vec<JournalRecord> {
        names
            .iter()
            .enumerate()
            .map(|(index, name)| record(index as u64 + 1, c1_event(records, name)))
            .collect()
    }

    /// Repoint a C1 record at a reservation the journal never reserved.
    fn naming_an_unreserved_attempt(event: JournalEvent) -> JournalEvent {
        naming_attempt(
            event,
            crate::ReservationId::new("resv-not-in-this-journal").expect("reservation id"),
        )
    }

    /// Repoint a C1 record at a specific reservation identity.
    fn naming_attempt(mut event: JournalEvent, unknown: crate::ReservationId) -> JournalEvent {
        match &mut event {
            JournalEvent::C1RequestPrepared { reservation_id, .. }
            | JournalEvent::C1IoStarted { reservation_id }
            | JournalEvent::C1RawDurabilityRecorded { reservation_id, .. }
            | JournalEvent::C1AttemptAbandoned { reservation_id, .. }
            | JournalEvent::C1BudgetSettled { reservation_id, .. } => *reservation_id = unknown,
            _ => panic!("that C1 record carries no reservation identity"),
        }
        event
    }

    /// Every refusal [`scan_c1_journal`] documents, one case each.
    ///
    /// The reader's whole job is to refuse a duplicated or out-of-order record rather than repair
    /// it, so a refusal nothing exercises is a refusal nobody maintains. Each case is built from
    /// the exact records a real run wrote — a completed one and a gapped one — and each asserts
    /// the specific refusal, not merely that some error came back, so deleting or inverting one
    /// ordering guard fails exactly its own case.
    #[test]
    #[allow(clippy::too_many_lines)] // The refused orderings stay readable as one table.
    fn replay_refuses_every_documented_out_of_order_or_duplicated_c1_record() {
        let (completed, reservation) = reserved_record_from_a_real_run();
        let gapped = records_from_a_real_gapped_run();
        let bound = c1_event(&completed, "activation_bound");
        let reserved = c1_event(&completed, "attempt_reserved");
        let prepared = c1_event(&completed, "request_prepared");
        let io = c1_event(&completed, "io_started");
        let durable = c1_event(&completed, "raw_durability_recorded");
        let settled = c1_event(&completed, "budget_settled");
        let stopped = c1_event(&completed, "stopped");
        // The gapped run reserved its own attempt, so its abandonment is repointed at the
        // completed run's reservation; every case below then speaks about one attempt identity.
        let abandoned = naming_attempt(
            c1_event(&gapped, "attempt_abandoned"),
            reservation.reservation_id.clone(),
        );

        let build = |events: Vec<JournalEvent>| -> Vec<JournalRecord> {
            events
                .into_iter()
                .enumerate()
                .map(|(index, event)| record(index as u64 + 1, event))
                .collect()
        };

        let cases: Vec<(&str, Vec<JournalRecord>)> = vec![
            (
                "a second C1 activation binding",
                build(vec![bound.clone(), bound.clone()]),
            ),
            (
                "a C1 reservation before any bound activation",
                build(vec![reserved.clone()]),
            ),
            (
                "a second C1 reservation",
                build(vec![bound.clone(), reserved.clone(), reserved.clone()]),
            ),
            (
                "a prepared C1 request naming a reservation this journal never reserved",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    naming_an_unreserved_attempt(prepared.clone()),
                ]),
            ),
            (
                "a duplicated or late C1 request closure",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    prepared.clone(),
                ]),
            ),
            (
                "a duplicated or late C1 request closure",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    prepared.clone(),
                ]),
            ),
            (
                "a C1 I/O start naming a reservation this journal never reserved",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    naming_an_unreserved_attempt(io.clone()),
                ]),
            ),
            (
                "a C1 I/O start before its request closure",
                build(vec![bound.clone(), reserved.clone(), io.clone()]),
            ),
            (
                "a second C1 I/O start",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    io.clone(),
                ]),
            ),
            (
                "a C1 durability record naming a reservation this journal never reserved",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    naming_an_unreserved_attempt(durable.clone()),
                ]),
            ),
            (
                "C1 durability before any I/O start",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    durable.clone(),
                ]),
            ),
            (
                "a second C1 attempt resolution",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    durable.clone(),
                    durable.clone(),
                ]),
            ),
            (
                "a second C1 attempt resolution",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    durable.clone(),
                    abandoned.clone(),
                ]),
            ),
            (
                "a second C1 attempt resolution",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    abandoned.clone(),
                    durable.clone(),
                ]),
            ),
            (
                "a C1 abandonment naming a reservation this journal never reserved",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    prepared.clone(),
                    io.clone(),
                    naming_an_unreserved_attempt(abandoned.clone()),
                ]),
            ),
            (
                "a C1 settlement naming a reservation this journal never reserved",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    naming_an_unreserved_attempt(settled.clone()),
                ]),
            ),
            (
                "a second C1 settlement",
                build(vec![
                    bound.clone(),
                    reserved.clone(),
                    settled.clone(),
                    settled.clone(),
                ]),
            ),
            (
                "a C1 stop before any bound activation",
                build(vec![stopped.clone()]),
            ),
            (
                "a second C1 stop",
                build(vec![bound.clone(), stopped.clone(), stopped.clone()]),
            ),
        ];

        for (expected, records) in cases {
            let error = scan_c1_journal(&records)
                .err()
                .unwrap_or_else(|| panic!("replay must refuse {expected:?}"));
            let SupervisorError::InvalidState(message) = &error else {
                panic!("{expected:?} must be an invalid-state refusal, got {error}")
            };
            assert_eq!(
                message,
                &format!("the C1 journal records {expected}"),
                "the refusal has to name what it refused"
            );
        }

        // The abandonment record replay must *accept*, so the resolution guards above are not
        // passing merely because every abandonment is refused.
        let gap_lifecycle = c1_slice(
            &gapped,
            &[
                "activation_bound",
                "attempt_reserved",
                "request_prepared",
                "io_started",
                "attempt_abandoned",
                "stopped",
                "budget_settled",
            ],
        );
        let state = scan_c1_journal(&gap_lifecycle).expect("a real gapped lifecycle replays");
        assert!(state.attempt_abandoned && !state.raw_durability_recorded);
        assert!(state.budget_settled && state.generation_stopped);
        assert!(!state.attempt_unresolved());
    }

    #[test]
    fn replay_refuses_a_duplicated_or_out_of_order_c1_record() {
        let (records, reservation) = reserved_record_from_a_real_run();
        let id = reservation.reservation_id.clone();

        let mut doubled = records.clone();
        doubled.push(record(999, activation_bound_event()));
        assert!(
            scan_c1_journal(&doubled).is_err(),
            "a second activation binding is refused"
        );

        let mut doubled_io = records.clone();
        doubled_io.push(record(
            999,
            JournalEvent::C1IoStarted {
                reservation_id: id.clone(),
            },
        ));
        assert!(
            scan_c1_journal(&doubled_io).is_err(),
            "a second I/O start is refused"
        );

        let early_io = vec![
            record(1, activation_bound_event()),
            record(2, JournalEvent::C1AttemptReserved(reservation.clone())),
            record(
                3,
                JournalEvent::C1IoStarted {
                    reservation_id: id.clone(),
                },
            ),
        ];
        assert!(
            scan_c1_journal(&early_io).is_err(),
            "an I/O start before its request closure is refused"
        );

        let reserved_without_activation = vec![record(
            1,
            JournalEvent::C1AttemptReserved(reservation.clone()),
        )];
        assert!(
            scan_c1_journal(&reserved_without_activation).is_err(),
            "a reservation with no bound activation is refused"
        );

        let unknown = vec![
            record(1, activation_bound_event()),
            record(2, JournalEvent::C1AttemptReserved(reservation)),
            record(
                3,
                JournalEvent::C1BudgetSettled {
                    reservation_id: crate::ReservationId::new("resv-not-in-this-journal")
                        .expect("reservation id"),
                    usage: zero_usage(),
                    disposition: RuntimeSettlementDisposition::RefundedBeforeIo,
                },
            ),
        ];
        assert!(
            scan_c1_journal(&unknown).is_err(),
            "a settlement naming an unreserved attempt is refused"
        );
        let _ = id;
    }

    #[test]
    fn c1_replay_ignores_every_c0_record_and_c0_readers_never_see_c1_work() {
        let mut bench = Bench::new();
        let supervisor = bench.supervisor();
        let burned = bench.burn(&supervisor, "families");
        let run_id = burned.run.run_id.clone();
        let mut runtime = open_runtime(supervisor, burned).expect("open the C1 runtime");
        let server = Loopback::start(vec![Step::Write(ok_page_response(EMPTY_PAGE, ""))]);
        runtime.bind_loopback_for_tests(server.base_url());
        runtime.run_once(at(), 0).expect("one bounded C1 read");

        // The C0 reservation reader walks `AttemptReserved` only, so a completed C1 run is
        // invisible to it. If C1 work ever leaked into the C0 family this would return it.
        assert!(
            runtime
                .supervisor()
                .reservations_for_run(&run_id)
                .expect("C0 reservation readback")
                .is_empty(),
            "C0 replay must not observe C1 work"
        );

        // And symmetrically: C0 records interleaved into the same slice change nothing here.
        let mut records: Vec<JournalRecord> = runtime.supervisor().journal_records().to_vec();
        let baseline = scan_c1_journal(&records).expect("replay");
        records.push(record(
            9_000,
            JournalEvent::ShutdownStarted { deadline_ms: 5 },
        ));
        records.push(record(
            9_001,
            JournalEvent::ShutdownCompleted {
                drained_segments: 0,
                abandoned_attempts: 0,
                downtime_gaps: 0,
                deadline_exceeded: false,
            },
        ));
        assert_eq!(
            scan_c1_journal(&records).expect("replay"),
            baseline,
            "C1 replay must not observe C0 work"
        );
    }

    #[test]
    fn reconciling_a_journal_with_no_c1_work_changes_nothing() {
        let bench = Bench::new();
        let mut supervisor = bench.supervisor();
        let before = supervisor.journal_records().len();
        let state = reconcile_c1_restart(&mut supervisor, at()).expect("reconcile");
        assert!(!state.activation_bound());
        assert_eq!(supervisor.journal_records().len(), before);
    }
}
