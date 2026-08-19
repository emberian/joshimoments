//! Two-phase, bounded provider-runner port.
//!
//! [`ProviderRunner::plan_next`] is pure and cannot perform provider I/O. A supervisor must first
//! durably reserve the returned exact attempt and its worst-case budget, then bind the journal's
//! reservation identity through [`ProviderAttemptPermit::bind_reservation_identity_unverified`]
//! before calling `execute`. The port cannot itself prove journal durability.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    CoverageEvent, SourceId, SourceOutput, UnixMillis,
    provider_plan::{
        BuiltInExecutionDisposition, ProviderOperation, ProviderScopePort, RuntimeAttemptCostPort,
        RuntimeBudgetPort, ValidatedProviderRunPlan,
    },
};

// The supervisor's durable C0 gap discriminator adds a source-category prefix and, for explicit
// gaps, a SHA-256 coverage-envelope digest. Keeping the source reason below this bound guarantees
// that every runner-valid reason still fits the shared 512-byte StableString boundary losslessly.
const MAX_C0_DURABLE_REASON_BYTES: usize = 400;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderAttemptAssociation {
    pub run_id: String,
    pub registration_digest: String,
    pub plan_id: String,
    pub plan_template_digest: String,
    pub plan_digest: String,
    pub source_key: String,
    pub method_key: String,
    pub operation: ProviderOperation,
    pub generation: u64,
    pub attempt_ordinal: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderAttemptPlan {
    pub association: ProviderAttemptAssociation,
    pub source_id: SourceId,
    pub coverage_family: String,
    pub protection_domain: String,
    pub maximum_cost: RuntimeAttemptCostPort,
}

#[derive(Clone, Debug)]
pub struct ProviderAttemptPermit {
    association: ProviderAttemptAssociation,
    reservation_id: String,
    maximum_cost: RuntimeAttemptCostPort,
}

impl ProviderAttemptPermit {
    /// Bind an unverified supervisor reservation identity to the exact pure attempt plan.
    ///
    /// This constructor does not claim the reservation is durable; the supervisor owns that
    /// evidence. It prevents a permit for one run/source/method/generation from executing another.
    ///
    /// # Errors
    ///
    /// Refuses an empty, whitespace-bearing, or control-bearing reservation identity.
    pub fn bind_reservation_identity_unverified(
        attempt: &ProviderAttemptPlan,
        reservation_id: impl Into<String>,
    ) -> Result<Self, ProviderRunnerError> {
        let reservation_id = reservation_id.into();
        stable_identifier(&reservation_id)?;
        Ok(Self {
            association: attempt.association.clone(),
            reservation_id,
            maximum_cost: attempt.maximum_cost.clone(),
        })
    }

    #[must_use]
    pub fn reservation_id(&self) -> &str {
        &self.reservation_id
    }

    #[must_use]
    pub fn association(&self) -> &ProviderAttemptAssociation {
        &self.association
    }

    #[must_use]
    pub fn maximum_cost(&self) -> &RuntimeAttemptCostPort {
        &self.maximum_cost
    }
}

#[derive(Clone, Debug)]
pub enum ProviderRunnerNext {
    Attempt(Box<ProviderAttemptPlan>),
    Finished(ProviderRunnerCompletion),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderCompletionReason {
    Exhausted,
    ShutdownRequested,
}

#[derive(Clone, Debug)]
pub struct ProviderRunnerCompletion {
    pub run_id: String,
    pub registration_digest: String,
    pub plan_id: String,
    pub plan_digest: String,
    pub reason: ProviderCompletionReason,
}

#[derive(Clone, Debug)]
pub struct ProviderAttemptReport {
    pub association: ProviderAttemptAssociation,
    pub reservation_id: String,
    pub actual_usage: RuntimeBudgetPort,
    pub outcome: ProviderAttemptOutcome,
}

#[derive(Clone, Debug)]
pub enum ProviderAttemptOutcome {
    /// One or more exact frames. The sealed C0 adapter does not admit coverage/health controls in
    /// this variant; gaps and unavailability have distinct typed outcomes.
    Captured {
        outputs: Vec<SourceOutput>,
    },
    /// Available only to the sealed C0 fixture contract. Live provider silence never enters here.
    BoundedEmpty {
        lower: UnixMillis,
        upper: UnixMillis,
        proof_contract: String,
    },
    Unavailable {
        at: UnixMillis,
        reason: String,
    },
    /// Must contain a source-matching `GapOpened` or `GapClassified` event.
    Gap {
        at: UnixMillis,
        reason: String,
        coverage: Vec<CoverageEvent>,
    },
}

pub trait ProviderRunner: Send {
    fn validated_plan(&self) -> &ValidatedProviderRunPlan;

    /// Produce the next exact reservation request without provider I/O.
    ///
    /// # Errors
    ///
    /// Refuses a concurrent pending attempt or an exhausted operation bound.
    fn plan_next(&mut self) -> Result<ProviderRunnerNext, ProviderRunnerError>;

    /// Execute only the exact previously planned C0 attempt. No other profile has an execution
    /// path, and the C0 one is synthetic.
    ///
    /// # Errors
    ///
    /// Refuses an unbound/mismatched identity, invalid output, or usage beyond the reservation.
    fn execute(
        &mut self,
        permit: ProviderAttemptPermit,
    ) -> Result<ProviderAttemptReport, ProviderRunnerError>;

    /// Cancel a pure planned attempt before I/O. No source gap is created because acquisition did
    /// not begin; the supervisor must separately settle/cancel its durable budget reservation.
    ///
    /// # Errors
    ///
    /// Refuses when there is no pending attempt or the supplied attempt does not match it.
    fn cancel_planned(&mut self, attempt: &ProviderAttemptPlan) -> Result<(), ProviderRunnerError>;

    /// Request a graceful stop. A pending planned attempt must be cancelled first.
    ///
    /// # Errors
    ///
    /// Refuses while an attempt remains pending.
    fn request_shutdown(&mut self) -> Result<(), ProviderRunnerError>;
}

#[derive(Clone, Debug)]
pub struct SyntheticScenario {
    pub scenario_id: String,
    pub steps: Vec<SyntheticStep>,
}

#[derive(Clone, Debug)]
pub struct SyntheticStep {
    pub operation_index: usize,
    pub actual_usage: RuntimeBudgetPort,
    pub outcome: ProviderAttemptOutcome,
}

struct PendingSynthetic {
    attempt: ProviderAttemptPlan,
    step: SyntheticStep,
}

pub struct SyntheticProviderRunner {
    plan: ValidatedProviderRunPlan,
    scenario: SyntheticScenario,
    next_step: usize,
    attempts_by_operation: BTreeMap<usize, u64>,
    pending: Option<PendingSynthetic>,
    shutdown_requested: bool,
}

impl SyntheticProviderRunner {
    /// Construct the only built-in runner. It accepts only a sealed C0 plan and finite scenario.
    ///
    /// # Errors
    ///
    /// Refuses a plan whose built-in execution is not synthetic, an unbound scenario, an operation
    /// index/count violation, invalid outputs, or actual use outside the exact attempt
    /// reservation.
    pub fn new(
        plan: ValidatedProviderRunPlan,
        scenario: SyntheticScenario,
    ) -> Result<Self, ProviderRunnerError> {
        if plan.built_in_execution() != BuiltInExecutionDisposition::SyntheticEnabled {
            return Err(ProviderRunnerError::LiveProviderExecutionDisabled);
        }
        stable_identifier(&scenario.scenario_id)?;
        let mut counts = BTreeMap::<usize, u64>::new();
        for step in &scenario.steps {
            let operation = plan
                .operations()
                .get(step.operation_index)
                .ok_or(ProviderRunnerError::UnknownOperation)?;
            let ProviderScopePort::SyntheticScenario { scenario_id } = &operation.plan.scope else {
                return Err(ProviderRunnerError::LiveProviderExecutionDisabled);
            };
            if scenario_id != &scenario.scenario_id {
                return Err(ProviderRunnerError::ScenarioMismatch);
            }
            let count = counts.entry(step.operation_index).or_default();
            *count = count
                .checked_add(1)
                .ok_or(ProviderRunnerError::ArithmeticOverflow)?;
            if *count > operation.plan.max_attempts {
                return Err(ProviderRunnerError::AttemptLimitExceeded);
            }
            validate_outcome(
                &operation.source_id,
                operation.plan.operation,
                &step.actual_usage,
                &operation.plan.attempt_cost,
                &step.outcome,
            )?;
        }
        Ok(Self {
            plan,
            scenario,
            next_step: 0,
            attempts_by_operation: BTreeMap::new(),
            pending: None,
            shutdown_requested: false,
        })
    }

    fn completion(&self, reason: ProviderCompletionReason) -> ProviderRunnerCompletion {
        ProviderRunnerCompletion {
            run_id: self.plan.plan().run.run_id.clone(),
            registration_digest: self.plan.plan().run.registration_digest.clone(),
            plan_id: self.plan.plan().plan_id.clone(),
            plan_digest: self.plan.plan_digest().to_owned(),
            reason,
        }
    }

    fn execute_now(
        &mut self,
        permit: ProviderAttemptPermit,
    ) -> Result<ProviderAttemptReport, ProviderRunnerError> {
        let pending = self
            .pending
            .take()
            .ok_or(ProviderRunnerError::NoPendingAttempt)?;
        if permit.association != pending.attempt.association
            || permit.maximum_cost != pending.attempt.maximum_cost
        {
            self.pending = Some(pending);
            return Err(ProviderRunnerError::PermitMismatch);
        }
        let operation = self
            .plan
            .operations()
            .get(pending.step.operation_index)
            .ok_or(ProviderRunnerError::UnknownOperation)?;
        validate_outcome(
            &operation.source_id,
            operation.plan.operation,
            &pending.step.actual_usage,
            &pending.attempt.maximum_cost,
            &pending.step.outcome,
        )?;
        self.next_step = self.next_step.saturating_add(1);
        Ok(ProviderAttemptReport {
            association: pending.attempt.association,
            reservation_id: permit.reservation_id,
            actual_usage: pending.step.actual_usage,
            outcome: pending.step.outcome,
        })
    }
}

impl ProviderRunner for SyntheticProviderRunner {
    fn validated_plan(&self) -> &ValidatedProviderRunPlan {
        &self.plan
    }

    fn plan_next(&mut self) -> Result<ProviderRunnerNext, ProviderRunnerError> {
        if self.pending.is_some() {
            return Err(ProviderRunnerError::PendingAttemptExists);
        }
        if self.shutdown_requested {
            return Ok(ProviderRunnerNext::Finished(
                self.completion(ProviderCompletionReason::ShutdownRequested),
            ));
        }
        let Some(step) = self.scenario.steps.get(self.next_step).cloned() else {
            return Ok(ProviderRunnerNext::Finished(
                self.completion(ProviderCompletionReason::Exhausted),
            ));
        };
        let operation = self
            .plan
            .operations()
            .get(step.operation_index)
            .ok_or(ProviderRunnerError::UnknownOperation)?;
        let ordinal = self
            .attempts_by_operation
            .entry(step.operation_index)
            .or_default();
        *ordinal = ordinal
            .checked_add(1)
            .ok_or(ProviderRunnerError::ArithmeticOverflow)?;
        if *ordinal > operation.plan.max_attempts {
            return Err(ProviderRunnerError::AttemptLimitExceeded);
        }
        let attempt = ProviderAttemptPlan {
            association: ProviderAttemptAssociation {
                run_id: self.plan.plan().run.run_id.clone(),
                registration_digest: self.plan.plan().run.registration_digest.clone(),
                plan_id: self.plan.plan().plan_id.clone(),
                plan_template_digest: self.plan.plan_template_digest().to_owned(),
                plan_digest: self.plan.plan_digest().to_owned(),
                source_key: operation.plan.source_key.clone(),
                method_key: operation.plan.method_key.clone(),
                operation: operation.plan.operation,
                generation: operation.plan.generation,
                attempt_ordinal: *ordinal,
            },
            source_id: operation.source_id.clone(),
            coverage_family: operation.coverage_family.clone(),
            protection_domain: operation.protection_domain.clone(),
            maximum_cost: operation.plan.attempt_cost.clone(),
        };
        self.pending = Some(PendingSynthetic {
            attempt: attempt.clone(),
            step,
        });
        Ok(ProviderRunnerNext::Attempt(Box::new(attempt)))
    }

    fn execute(
        &mut self,
        permit: ProviderAttemptPermit,
    ) -> Result<ProviderAttemptReport, ProviderRunnerError> {
        self.execute_now(permit)
    }

    fn cancel_planned(&mut self, attempt: &ProviderAttemptPlan) -> Result<(), ProviderRunnerError> {
        let pending = self
            .pending
            .as_ref()
            .ok_or(ProviderRunnerError::NoPendingAttempt)?;
        if pending.attempt.association != attempt.association
            || pending.attempt.maximum_cost != attempt.maximum_cost
        {
            return Err(ProviderRunnerError::PermitMismatch);
        }
        self.pending = None;
        Ok(())
    }

    fn request_shutdown(&mut self) -> Result<(), ProviderRunnerError> {
        if self.pending.is_some() {
            return Err(ProviderRunnerError::PendingAttemptExists);
        }
        self.shutdown_requested = true;
        Ok(())
    }
}

pub(crate) fn validate_outcome(
    source_id: &SourceId,
    operation: ProviderOperation,
    actual: &RuntimeBudgetPort,
    maximum: &RuntimeAttemptCostPort,
    outcome: &ProviderAttemptOutcome,
) -> Result<(), ProviderRunnerError> {
    if !actual.within(&maximum.reserved_total()?) {
        return Err(ProviderRunnerError::ActualUsageExceeded);
    }
    if matches!(
        operation,
        ProviderOperation::SyntheticEmit | ProviderOperation::SolanaSignaturesForAddress
    ) && (maximum.worst_case.requests != 1
        || maximum.max_overshoot.requests != 0
        || actual.requests != 1
        || maximum.worst_case.pages != 1
        || maximum.max_overshoot.pages != 0
        || actual.pages != 1)
    {
        return Err(ProviderRunnerError::InexactStartedUsage);
    }
    match outcome {
        ProviderAttemptOutcome::Captured { outputs } => {
            if outputs.is_empty() {
                return Err(ProviderRunnerError::CapturedRequiresFrame);
            }
            for output in outputs {
                let SourceOutput::Frame(frame) = output else {
                    return Err(ProviderRunnerError::CapturedControlsNotAuthorized);
                };
                if &frame.source != source_id {
                    return Err(ProviderRunnerError::OutputSourceMismatch);
                }
            }
        }
        ProviderAttemptOutcome::BoundedEmpty {
            lower,
            upper,
            proof_contract,
        } => {
            if operation != ProviderOperation::SyntheticEmit
                || lower >= upper
                || proof_contract != "synthetic_bounded_scenario.v1"
            {
                return Err(ProviderRunnerError::BoundedEmptyNotAuthorized);
            }
        }
        ProviderAttemptOutcome::Unavailable { reason, .. } => {
            stable_reason(reason)?;
        }
        ProviderAttemptOutcome::Gap {
            reason, coverage, ..
        } => {
            stable_reason(reason)?;
            if coverage.is_empty()
                || !coverage
                    .iter()
                    .all(|event| coverage_source(event) == source_id)
                || !coverage.iter().any(|event| {
                    matches!(
                        event,
                        CoverageEvent::GapOpened { .. } | CoverageEvent::GapClassified { .. }
                    )
                })
            {
                return Err(ProviderRunnerError::InvalidGapEvidence);
            }
        }
    }
    Ok(())
}

fn coverage_source(event: &CoverageEvent) -> &SourceId {
    match event {
        CoverageEvent::WindowOpened { source, .. }
        | CoverageEvent::CursorObserved { source, .. }
        | CoverageEvent::GapOpened { source, .. }
        | CoverageEvent::RecoveryStarted { source, .. }
        | CoverageEvent::GapClassified { source, .. }
        | CoverageEvent::WindowClosed { source, .. } => source,
    }
}

fn stable_identifier(value: &str) -> Result<(), ProviderRunnerError> {
    if value.is_empty()
        || value.len() > 200
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
    {
        return Err(ProviderRunnerError::InvalidIdentifier);
    }
    Ok(())
}

fn stable_reason(value: &str) -> Result<(), ProviderRunnerError> {
    if value.is_empty()
        || value.len() > MAX_C0_DURABLE_REASON_BYTES
        || value.chars().any(char::is_control)
    {
        return Err(ProviderRunnerError::InvalidReason);
    }
    Ok(())
}

#[derive(Debug, Error)]
pub enum ProviderRunnerError {
    #[error("live provider execution is disabled")]
    LiveProviderExecutionDisabled,
    #[error("invalid non-secret runner identifier")]
    InvalidIdentifier,
    #[error("invalid bounded runner reason")]
    InvalidReason,
    #[error("synthetic scenario does not match the sealed C0 plan")]
    ScenarioMismatch,
    #[error("synthetic scenario references an unknown operation")]
    UnknownOperation,
    #[error("provider operation exceeded its planned attempt count")]
    AttemptLimitExceeded,
    #[error("provider runner arithmetic overflow")]
    ArithmeticOverflow,
    #[error("a provider attempt is already pending")]
    PendingAttemptExists,
    #[error("no provider attempt is pending")]
    NoPendingAttempt,
    #[error("provider permit does not match the exact pending attempt")]
    PermitMismatch,
    #[error("actual provider usage exceeds its reserved maximum")]
    ActualUsageExceeded,
    #[error("started bounded page attempt must report exactly one request and one page")]
    InexactStartedUsage,
    #[error("captured progress requires at least one exact source frame")]
    CapturedRequiresFrame,
    #[error("sealed C0 captured output admits frames only")]
    CapturedControlsNotAuthorized,
    #[error("source output does not match the planned source")]
    OutputSourceMismatch,
    #[error("bounded-empty outcome is not authorized by this source contract")]
    BoundedEmptyNotAuthorized,
    #[error("gap outcome lacks matching explicit coverage-gap evidence")]
    InvalidGapEvidence,
    #[error("provider plan budget could not be represented")]
    PlanBudget(#[from] crate::ProviderPlanError),
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;

    use crate::{
        ContentType, FrameDirection, RawSourceFrame, StreamClass, Transport,
        provider_plan::{
            CanaryProfilePort, PROVIDER_RUN_PLAN_PORT_VERSION, ProviderOperationPlan,
            ProviderRunPlan, ProviderScopePort, RegisteredRunPort, RuntimeAttemptCostPort,
            RuntimeBudgetPort, validate_provider_run_plan,
        },
    };

    use super::*;

    fn usage() -> RuntimeBudgetPort {
        RuntimeBudgetPort {
            requests: 1,
            pages: 1,
            ingress_bytes: 2,
            durable_bytes: 2,
            wall_millis: 1,
            ..RuntimeBudgetPort::default()
        }
    }

    fn plan() -> ValidatedProviderRunPlan {
        validate_provider_run_plan(ProviderRunPlan {
            port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
            plan_id: "runner-plan".to_owned(),
            run: RegisteredRunPort {
                run_id: "runner-run".to_owned(),
                registration_digest:
                    "sha256:9225070e38e092e3c4cdd48744c36f61a32fee85c1170d0edcdbdc278428a6ed"
                        .to_owned(),
            },
            profile: CanaryProfilePort::C0,
            hard_cap: RuntimeBudgetPort {
                requests: 1,
                pages: 1,
                ingress_bytes: 1_024,
                durable_bytes: 1_024,
                wall_millis: 1_000,
                ..RuntimeBudgetPort::default()
            },
            max_elapsed_ms: 1_000,
            max_ingress_bytes_per_second: None,
            max_in_flight_attempts: 1,
            operations: vec![ProviderOperationPlan {
                source_key: "synthetic.local".to_owned(),
                method_key: "emit".to_owned(),
                source_contract_fingerprint:
                    crate::provider_plan::SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                method_schema_fingerprint:
                    crate::provider_plan::SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
                operation: ProviderOperation::SyntheticEmit,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::SyntheticScenario {
                    scenario_id: "walk".to_owned(),
                },
                attempt_cost: RuntimeAttemptCostPort {
                    worst_case: RuntimeBudgetPort {
                        requests: 1,
                        pages: 1,
                        ingress_bytes: 1_024,
                        durable_bytes: 1_024,
                        wall_millis: 1_000,
                        ..RuntimeBudgetPort::default()
                    },
                    max_overshoot: RuntimeBudgetPort::default(),
                },
            }],
        })
        .unwrap()
    }

    fn frame() -> RawSourceFrame {
        RawSourceFrame {
            contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::Other("synthetic_local".to_owned()),
            transport: Transport::Fixture,
            stream_class: StreamClass::BroadCensus,
            direction: FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: UnixMillis(1),
            connection_epoch: 1,
            sequence: 1,
            http_status: None,
            safe_headers: Vec::new(),
            body: Bytes::from_static(b"{}"),
        }
    }

    #[test]
    fn synthetic_runner_requires_plan_then_exact_permit() {
        let mut runner = SyntheticProviderRunner::new(
            plan(),
            SyntheticScenario {
                scenario_id: "walk".to_owned(),
                steps: vec![SyntheticStep {
                    operation_index: 0,
                    actual_usage: usage(),
                    outcome: ProviderAttemptOutcome::Captured {
                        outputs: vec![SourceOutput::Frame(frame())],
                    },
                }],
            },
        )
        .unwrap();
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().unwrap() else {
            panic!("attempt expected");
        };
        assert_eq!(attempt.association.generation, 1);
        let permit =
            ProviderAttemptPermit::bind_reservation_identity_unverified(&attempt, "reservation-1")
                .unwrap();
        let report = runner.execute(permit).unwrap();
        assert_eq!(report.association, attempt.association);
        assert!(matches!(
            report.outcome,
            ProviderAttemptOutcome::Captured { .. }
        ));
        assert!(matches!(
            runner.plan_next().unwrap(),
            ProviderRunnerNext::Finished(ProviderRunnerCompletion {
                reason: ProviderCompletionReason::Exhausted,
                ..
            })
        ));
    }

    #[test]
    fn permit_for_a_different_attempt_cannot_execute() {
        let mut runner = SyntheticProviderRunner::new(
            plan(),
            SyntheticScenario {
                scenario_id: "walk".to_owned(),
                steps: vec![SyntheticStep {
                    operation_index: 0,
                    actual_usage: usage(),
                    outcome: ProviderAttemptOutcome::Captured {
                        outputs: vec![SourceOutput::Frame(frame())],
                    },
                }],
            },
        )
        .unwrap();
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().unwrap() else {
            panic!("attempt expected");
        };
        let mut wrong = attempt.clone();
        wrong.association.generation = 2;
        let permit =
            ProviderAttemptPermit::bind_reservation_identity_unverified(&wrong, "reservation-2")
                .unwrap();
        assert!(matches!(
            runner.execute(permit),
            Err(ProviderRunnerError::PermitMismatch)
        ));
        runner.cancel_planned(&attempt).unwrap();
        runner.request_shutdown().unwrap();
    }

    #[test]
    fn generic_silence_is_not_an_outcome() {
        assert!(matches!(
            validate_outcome(
                &SourceId::Other("synthetic_local".to_owned()),
                ProviderOperation::SyntheticEmit,
                &usage(),
                &RuntimeAttemptCostPort {
                    worst_case: usage(),
                    max_overshoot: RuntimeBudgetPort::default()
                },
                &ProviderAttemptOutcome::Captured {
                    outputs: Vec::new()
                }
            ),
            Err(ProviderRunnerError::CapturedRequiresFrame)
        ));
    }

    #[test]
    fn captured_c0_output_rejects_coverage_or_health_controls() {
        let source = SourceId::Other("synthetic_local".to_owned());
        let coverage = CoverageEvent::WindowOpened {
            source: source.clone(),
            connection_epoch: 1,
            at: UnixMillis(1),
        };
        assert!(matches!(
            validate_outcome(
                &source,
                ProviderOperation::SyntheticEmit,
                &usage(),
                &RuntimeAttemptCostPort {
                    worst_case: usage(),
                    max_overshoot: RuntimeBudgetPort::default()
                },
                &ProviderAttemptOutcome::Captured {
                    outputs: vec![
                        SourceOutput::Frame(frame()),
                        SourceOutput::Coverage(coverage)
                    ]
                }
            ),
            Err(ProviderRunnerError::CapturedControlsNotAuthorized)
        ));
    }

    #[test]
    fn c0_started_request_usage_cannot_be_underreported() {
        let mut underreported = usage();
        underreported.requests = 0;
        assert!(matches!(
            validate_outcome(
                &SourceId::Other("synthetic_local".to_owned()),
                ProviderOperation::SyntheticEmit,
                &underreported,
                &RuntimeAttemptCostPort {
                    worst_case: usage(),
                    max_overshoot: RuntimeBudgetPort::default()
                },
                &ProviderAttemptOutcome::Captured {
                    outputs: vec![SourceOutput::Frame(frame())]
                }
            ),
            Err(ProviderRunnerError::InexactStartedUsage)
        ));
    }

    #[test]
    fn c0_reason_bound_fits_the_durable_prefixed_gap_discriminator() {
        let source = SourceId::Other("synthetic_local".to_owned());
        let maximum = RuntimeAttemptCostPort {
            worst_case: usage(),
            max_overshoot: RuntimeBudgetPort::default(),
        };
        assert!(
            validate_outcome(
                &source,
                ProviderOperation::SyntheticEmit,
                &usage(),
                &maximum,
                &ProviderAttemptOutcome::Unavailable {
                    at: UnixMillis(1),
                    reason: "r".repeat(MAX_C0_DURABLE_REASON_BYTES),
                },
            )
            .is_ok()
        );
        assert!(matches!(
            validate_outcome(
                &source,
                ProviderOperation::SyntheticEmit,
                &usage(),
                &maximum,
                &ProviderAttemptOutcome::Unavailable {
                    at: UnixMillis(1),
                    reason: "r".repeat(MAX_C0_DURABLE_REASON_BYTES + 1),
                },
            ),
            Err(ProviderRunnerError::InvalidReason)
        ));
    }
}
