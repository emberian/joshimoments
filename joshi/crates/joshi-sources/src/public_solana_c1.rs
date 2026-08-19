//! Bounded C1 public-Solana runner state machine.
//!
//! The executor is deliberately injected and confers no provider or durability authority. The
//! production collector does not construct this runner. Its purpose is to freeze and exercise the
//! permit-gated one-page boundary before a separately reviewed live executor is mounted.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde_json::Value;
use thiserror::Error;

use crate::{
    ContentType, FrameDirection, ProviderAttemptAssociation, ProviderAttemptOutcome,
    ProviderAttemptPermit, ProviderAttemptPlan, ProviderAttemptReport, ProviderCompletionReason,
    ProviderOperation, ProviderRunner, ProviderRunnerCompletion, ProviderRunnerError,
    ProviderRunnerNext, ProviderScopePort, RawSourceFrame, RuntimeBudgetPort, SafeHeader, SourceId,
    SourceOutput, Transport, ValidatedProviderRunPlan,
    provider_plan::{BuiltInExecutionDisposition, CanaryProfilePort},
    runner_port::validate_outcome,
};

/// Exact logical request admitted by the C1 runner. It contains no endpoint or credential.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublicSolanaC1Request {
    pub address: String,
    pub max_rows: u16,
    pub commitment: &'static str,
    pub request_id: u64,
}

/// Exact scripted transport result. The runner derives counts, bytes, and credits; elapsed time
/// remains unverified test input and must not be reused as a production budget clock.
#[derive(Clone, Debug)]
pub struct PublicSolanaC1TransportResponse {
    pub frame: RawSourceFrame,
    pub elapsed_ms: u64,
}

/// Sanitized failure from an unverified C1 executor. It must not retain a URL or response body.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum PublicSolanaC1ExecutionError {
    #[error("public Solana C1 transport failed")]
    Transport,
}

/// Package-test-only scripted execution boundary used after exact unverified permit matching.
/// Implementing this trait proves no durable reservation and grants no source, store, or coverage
/// authority.
pub trait PublicSolanaC1Executor: Send {
    /// Perform one exact read-only request after the caller has durably started the attempt.
    ///
    /// # Errors
    ///
    /// Returns only a sanitized transport, size, or schema refusal. Implementations must not
    /// retain or render endpoint URLs or response bodies in the error.
    fn execute(
        &mut self,
        request: &PublicSolanaC1Request,
    ) -> Result<PublicSolanaC1TransportResponse, PublicSolanaC1ExecutionError>;
}

/// One-page C1 runner. No production constructor supplies it with a network executor.
pub struct PublicSolanaC1Runner<E> {
    plan: ValidatedProviderRunPlan,
    executor: E,
    pending: Option<ProviderAttemptPlan>,
    exhausted: bool,
    shutdown_requested: bool,
}

impl<E: PublicSolanaC1Executor> PublicSolanaC1Runner<E> {
    /// Construct the runner around an explicitly unverified executor.
    ///
    /// The accepted plan is still `ValidationOnlyNoProviderIo`; this constructor is not exposed by
    /// the collector CLI and grants no live-source or W5-G1 qualification.
    ///
    /// # Errors
    ///
    /// Refuses any plan other than the exact one-operation public-Solana C1 declaration.
    pub fn with_unverified_executor(
        plan: ValidatedProviderRunPlan,
        executor: E,
    ) -> Result<Self, ProviderRunnerError> {
        let [operation] = plan.operations() else {
            return Err(ProviderRunnerError::LiveProviderExecutionDisabled);
        };
        if plan.plan().profile != CanaryProfilePort::C1
            || plan.built_in_execution() != BuiltInExecutionDisposition::ValidationOnlyNoProviderIo
            || operation.plan.operation != ProviderOperation::SolanaSignaturesForAddress
            || operation.source_id != SourceId::SolanaPublicHttp
            || operation.plan.max_attempts != 1
            || !matches!(
                operation.plan.scope,
                ProviderScopePort::PublicWalletPage { .. }
            )
        {
            return Err(ProviderRunnerError::LiveProviderExecutionDisabled);
        }
        Ok(Self {
            plan,
            executor,
            pending: None,
            exhausted: false,
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
}

impl<E: PublicSolanaC1Executor> ProviderRunner for PublicSolanaC1Runner<E> {
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
        if self.exhausted {
            return Ok(ProviderRunnerNext::Finished(
                self.completion(ProviderCompletionReason::Exhausted),
            ));
        }
        let operation = &self.plan.operations()[0];
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
                attempt_ordinal: 1,
            },
            source_id: operation.source_id.clone(),
            coverage_family: operation.coverage_family.clone(),
            protection_domain: operation.protection_domain.clone(),
            maximum_cost: operation.plan.attempt_cost.clone(),
        };
        self.pending = Some(attempt.clone());
        Ok(ProviderRunnerNext::Attempt(Box::new(attempt)))
    }

    fn execute(
        &mut self,
        permit: ProviderAttemptPermit,
    ) -> Result<ProviderAttemptReport, ProviderRunnerError> {
        let pending = self
            .pending
            .take()
            .ok_or(ProviderRunnerError::NoPendingAttempt)?;
        if permit.association() != &pending.association
            || permit.maximum_cost() != &pending.maximum_cost
        {
            self.pending = Some(pending);
            return Err(ProviderRunnerError::PermitMismatch);
        }
        let ProviderScopePort::PublicWalletPage { address, max_rows } =
            &self.plan.operations()[0].plan.scope
        else {
            return Err(ProviderRunnerError::LiveProviderExecutionDisabled);
        };
        // The registered method admits exactly one attempt. Once the call boundary is crossed,
        // even a transport/schema refusal cannot silently create a second request.
        self.exhausted = true;
        let response = self
            .executor
            .execute(&PublicSolanaC1Request {
                address: address.clone(),
                max_rows: *max_rows,
                commitment: "finalized",
                request_id: 1,
            })
            .map_err(|_| ProviderRunnerError::PublicSolanaC1Execution)?;
        validate_response(&response, *max_rows, &pending.maximum_cost)?;
        let ingress_bytes = u64::try_from(response.frame.body.len())
            .map_err(|_| ProviderRunnerError::ArithmeticOverflow)?;
        let actual_usage = RuntimeBudgetPort {
            requests: 1,
            pages: 1,
            ingress_bytes,
            durable_bytes: 0,
            provider_credits: 0,
            wall_millis: response.elapsed_ms,
            ..RuntimeBudgetPort::default()
        };
        let outcome = ProviderAttemptOutcome::Captured {
            outputs: vec![SourceOutput::Frame(response.frame)],
        };
        validate_outcome(
            &pending.source_id,
            pending.association.operation,
            &actual_usage,
            &pending.maximum_cost,
            &outcome,
        )?;
        Ok(ProviderAttemptReport {
            association: pending.association,
            reservation_id: permit.reservation_id().to_owned(),
            actual_usage,
            outcome,
        })
    }

    fn cancel_planned(&mut self, attempt: &ProviderAttemptPlan) -> Result<(), ProviderRunnerError> {
        let pending = self
            .pending
            .as_ref()
            .ok_or(ProviderRunnerError::NoPendingAttempt)?;
        if pending.association != attempt.association
            || pending.maximum_cost != attempt.maximum_cost
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

fn validate_response(
    response: &PublicSolanaC1TransportResponse,
    max_rows: u16,
    maximum: &crate::RuntimeAttemptCostPort,
) -> Result<(), ProviderRunnerError> {
    let frame = &response.frame;
    let body_len =
        u64::try_from(frame.body.len()).map_err(|_| ProviderRunnerError::ArithmeticOverflow)?;
    if response.elapsed_ms == 0
        || response.elapsed_ms > maximum.reserved_total()?.wall_millis
        || body_len == 0
        || body_len > maximum.reserved_total()?.ingress_bytes
    {
        return execution_failure();
    }
    if frame.source != SourceId::SolanaPublicHttp
        || frame.contract_version != crate::ADAPTER_CONTRACT_VERSION
        || frame.transport != Transport::Http
        || frame.stream_class != crate::StreamClass::Backfill
        || frame.direction != FrameDirection::Inbound
        || frame.content_type != ContentType::Json
        || frame.received_at.0 <= 0
        || frame.connection_epoch != 1
        || frame.sequence != 1
        || frame.http_status != Some(200)
        || !safe_headers_are_bounded(&frame.safe_headers)
    {
        return execution_failure();
    }
    let response: JsonRpcResponse = serde_json::from_slice(&frame.body)
        .map_err(|_| ProviderRunnerError::PublicSolanaC1Execution)?;
    validate_json_rpc_page(&response, max_rows)
}

fn safe_headers_are_bounded(headers: &[SafeHeader]) -> bool {
    const ALLOWED: &[&str] = &[
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ];
    let mut names = BTreeSet::new();
    headers.len() <= ALLOWED.len()
        && headers.iter().all(|header| {
            let name = header.name.to_ascii_lowercase();
            ALLOWED.contains(&name.as_str())
                && names.insert(name)
                && header.value.len() <= 256
                && !header.value.chars().any(char::is_control)
        })
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct JsonRpcResponse {
    jsonrpc: String,
    id: u64,
    result: Vec<SignatureRow>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignatureRow {
    signature: String,
    slot: u64,
    err: Value,
    memo: RequiredNullable<String>,
    block_time: RequiredNullable<i64>,
    confirmation_status: RequiredNullable<String>,
}

#[derive(Deserialize)]
#[serde(transparent)]
struct RequiredNullable<T>(Option<T>);

fn validate_json_rpc_page(
    response: &JsonRpcResponse,
    max_rows: u16,
) -> Result<(), ProviderRunnerError> {
    if response.jsonrpc != "2.0"
        || response.id != 1
        || response.result.len() > usize::from(max_rows)
    {
        return execution_failure();
    }
    let mut prior_slot = None;
    let mut signatures = BTreeSet::new();
    for row in &response.result {
        let signature_bytes = bs58::decode(&row.signature)
            .into_vec()
            .map_err(|_| ProviderRunnerError::PublicSolanaC1Execution)?;
        if signature_bytes.len() != 64
            || !signatures.insert(&row.signature)
            || prior_slot.is_some_and(|prior| row.slot > prior)
            || row.confirmation_status.0.as_deref() != Some("finalized")
        {
            return execution_failure();
        }
        let _ = (&row.err, &row.memo.0, &row.block_time.0);
        prior_slot = Some(row.slot);
    }
    Ok(())
}

fn execution_failure<T>() -> Result<T, ProviderRunnerError> {
    Err(ProviderRunnerError::PublicSolanaC1Execution)
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;

    use super::*;
    use crate::{
        PROVIDER_RUN_PLAN_PORT_VERSION, PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT,
        PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT, ProviderOperationPlan, ProviderRunPlan,
        RegisteredRunPort, RuntimeAttemptCostPort, UnixMillis, validate_provider_run_plan,
    };

    const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";

    struct ScriptedExecutor {
        response: Option<PublicSolanaC1TransportResponse>,
        calls: usize,
        last_request: Option<PublicSolanaC1Request>,
    }

    impl PublicSolanaC1Executor for ScriptedExecutor {
        fn execute(
            &mut self,
            request: &PublicSolanaC1Request,
        ) -> Result<PublicSolanaC1TransportResponse, PublicSolanaC1ExecutionError> {
            self.calls += 1;
            self.last_request = Some(request.clone());
            self.response
                .take()
                .ok_or(PublicSolanaC1ExecutionError::Transport)
        }
    }

    fn plan() -> ValidatedProviderRunPlan {
        validate_provider_run_plan(ProviderRunPlan {
            port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
            plan_id: "public-solana-c1".to_owned(),
            run: RegisteredRunPort {
                run_id: "run-public-solana-c1".to_owned(),
                registration_digest:
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                        .to_owned(),
            },
            profile: CanaryProfilePort::C1,
            hard_cap: RuntimeBudgetPort {
                requests: 1,
                pages: 1,
                ingress_bytes: 1_048_576,
                durable_bytes: 8_388_608,
                wall_millis: 10_000,
                ..RuntimeBudgetPort::default()
            },
            max_elapsed_ms: 10_000,
            max_ingress_bytes_per_second: None,
            max_in_flight_attempts: 1,
            operations: vec![ProviderOperationPlan {
                source_key: "solana.public.mainnet".to_owned(),
                method_key: "get_signatures_for_address".to_owned(),
                source_contract_fingerprint: PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                method_schema_fingerprint: PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT
                    .to_owned(),
                operation: ProviderOperation::SolanaSignaturesForAddress,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::PublicWalletPage {
                    address: WALLET.to_owned(),
                    max_rows: 2,
                },
                attempt_cost: RuntimeAttemptCostPort {
                    worst_case: RuntimeBudgetPort {
                        requests: 1,
                        pages: 1,
                        ingress_bytes: 1_048_576,
                        durable_bytes: 8_388_608,
                        wall_millis: 10_000,
                        ..RuntimeBudgetPort::default()
                    },
                    max_overshoot: RuntimeBudgetPort::default(),
                },
            }],
        })
        .expect("C1 plan")
    }

    fn response(slots: [u64; 2]) -> PublicSolanaC1TransportResponse {
        let first = bs58::encode([1_u8; 64]).into_string();
        let second = bs58::encode([2_u8; 64]).into_string();
        let body = serde_json::to_vec(&serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                {"signature": first, "slot": slots[0], "err": null, "memo": null, "blockTime": 1, "confirmationStatus": "finalized"},
                {"signature": second, "slot": slots[1], "err": null, "memo": null, "blockTime": 0, "confirmationStatus": "finalized"}
            ]
        }))
        .expect("response JSON");
        PublicSolanaC1TransportResponse {
            frame: RawSourceFrame {
                contract_version: crate::ADAPTER_CONTRACT_VERSION.to_owned(),
                source: SourceId::SolanaPublicHttp,
                transport: Transport::Http,
                stream_class: crate::StreamClass::Backfill,
                direction: FrameDirection::Inbound,
                content_type: ContentType::Json,
                received_at: UnixMillis(1_000),
                connection_epoch: 1,
                sequence: 1,
                http_status: Some(200),
                safe_headers: Vec::new(),
                body: Bytes::from(body),
            },
            elapsed_ms: 5,
        }
    }

    #[test]
    fn planning_is_pure_and_exact_permit_precedes_the_single_executor_call() {
        let executor = ScriptedExecutor {
            response: Some(response([10, 9])),
            calls: 0,
            last_request: None,
        };
        let mut runner =
            PublicSolanaC1Runner::with_unverified_executor(plan(), executor).expect("runner");
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().expect("pure plan") else {
            panic!("expected attempt");
        };
        assert_eq!(runner.executor.calls, 0);
        let permit =
            ProviderAttemptPermit::bind_reservation_identity_unverified(&attempt, "reservation-c1")
                .expect("permit");
        let report = runner.execute(permit).expect("scripted response");
        assert_eq!(runner.executor.calls, 1);
        assert_eq!(report.actual_usage.requests, 1);
        assert_eq!(report.actual_usage.pages, 1);
        assert_eq!(report.actual_usage.provider_credits, 0);
        assert_eq!(
            runner.executor.last_request,
            Some(PublicSolanaC1Request {
                address: WALLET.to_owned(),
                max_rows: 2,
                commitment: "finalized",
                request_id: 1,
            })
        );
    }

    #[test]
    fn mismatched_permit_never_calls_the_executor() {
        let executor = ScriptedExecutor {
            response: Some(response([10, 9])),
            calls: 0,
            last_request: None,
        };
        let mut runner = PublicSolanaC1Runner::with_unverified_executor(plan(), executor).unwrap();
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().unwrap() else {
            panic!("expected attempt");
        };
        let foreign_attempt = ProviderAttemptPlan {
            association: ProviderAttemptAssociation {
                run_id: "foreign".to_owned(),
                ..attempt.association.clone()
            },
            ..(*attempt).clone()
        };
        let permit = ProviderAttemptPermit::bind_reservation_identity_unverified(
            &foreign_attempt,
            "reservation-foreign",
        )
        .unwrap();
        assert!(matches!(
            runner.execute(permit),
            Err(ProviderRunnerError::PermitMismatch)
        ));
        assert_eq!(runner.executor.calls, 0);
    }

    #[test]
    fn response_order_and_registered_row_bound_are_enforced() {
        let executor = ScriptedExecutor {
            response: Some(response([9, 10])),
            calls: 0,
            last_request: None,
        };
        let mut runner = PublicSolanaC1Runner::with_unverified_executor(plan(), executor).unwrap();
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().unwrap() else {
            panic!("expected attempt");
        };
        let permit =
            ProviderAttemptPermit::bind_reservation_identity_unverified(&attempt, "reservation-c1")
                .unwrap();
        assert!(matches!(
            runner.execute(permit),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));
    }

    fn execute_response(
        response: PublicSolanaC1TransportResponse,
    ) -> Result<ProviderAttemptReport, ProviderRunnerError> {
        let executor = ScriptedExecutor {
            response: Some(response),
            calls: 0,
            last_request: None,
        };
        let mut runner = PublicSolanaC1Runner::with_unverified_executor(plan(), executor)?;
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next()? else {
            panic!("expected attempt");
        };
        let permit = ProviderAttemptPermit::bind_reservation_identity_unverified(
            &attempt,
            "reservation-c1",
        )?;
        runner.execute(permit)
    }

    #[test]
    fn empty_success_is_a_captured_raw_frame_and_never_a_bounded_empty_claim() {
        let mut response = response([10, 9]);
        response.frame.body = Bytes::from_static(br#"{"jsonrpc":"2.0","id":1,"result":[]}"#);
        let report = execute_response(response).expect("empty raw page");
        assert!(matches!(
            report.outcome,
            ProviderAttemptOutcome::Captured { outputs } if outputs.len() == 1
        ));
    }

    #[test]
    fn exact_response_and_frame_envelopes_refuse_substitution() {
        let mut wrong_id = response([10, 9]);
        wrong_id.frame.body = Bytes::from_static(br#"{"jsonrpc":"2.0","id":2,"result":[]}"#);
        assert!(matches!(
            execute_response(wrong_id),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));

        let mut extra_root = response([10, 9]);
        extra_root.frame.body =
            Bytes::from_static(br#"{"jsonrpc":"2.0","id":1,"result":[],"context":{}}"#);
        assert!(matches!(
            execute_response(extra_root),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));

        let mut duplicate_root = response([10, 9]);
        duplicate_root.frame.body =
            Bytes::from_static(br#"{"jsonrpc":"2.0","id":1,"id":1,"result":[]}"#);
        assert!(matches!(
            execute_response(duplicate_root),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));

        let mut wrong_adapter = response([10, 9]);
        wrong_adapter.frame.contract_version = "joshi.source.frame.v0".to_owned();
        assert!(matches!(
            execute_response(wrong_adapter),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));

        let mut duplicate_header = response([10, 9]);
        duplicate_header.frame.safe_headers = vec![
            SafeHeader {
                name: "retry-after".to_owned(),
                value: "1".to_owned(),
            },
            SafeHeader {
                name: "Retry-After".to_owned(),
                value: "2".to_owned(),
            },
        ];
        assert!(matches!(
            execute_response(duplicate_header),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));
    }

    #[test]
    fn nonfinalized_rows_and_second_attempt_after_transport_failure_refuse() {
        let mut nonfinalized = response([10, 9]);
        let value: Value = serde_json::from_slice(&nonfinalized.frame.body).unwrap();
        let mut value = value;
        value["result"][0]["confirmationStatus"] = Value::String("confirmed".to_owned());
        nonfinalized.frame.body = Bytes::from(serde_json::to_vec(&value).unwrap());
        assert!(matches!(
            execute_response(nonfinalized),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));

        let executor = ScriptedExecutor {
            response: None,
            calls: 0,
            last_request: None,
        };
        let mut runner = PublicSolanaC1Runner::with_unverified_executor(plan(), executor).unwrap();
        let ProviderRunnerNext::Attempt(attempt) = runner.plan_next().unwrap() else {
            panic!("expected attempt");
        };
        let permit =
            ProviderAttemptPermit::bind_reservation_identity_unverified(&attempt, "reservation-c1")
                .unwrap();
        assert!(matches!(
            runner.execute(permit),
            Err(ProviderRunnerError::PublicSolanaC1Execution)
        ));
        assert!(matches!(
            runner.plan_next().unwrap(),
            ProviderRunnerNext::Finished(ProviderRunnerCompletion {
                reason: ProviderCompletionReason::Exhausted,
                ..
            })
        ));
    }
}
