//! Exact, semantic-only activation closure for one bounded Wave 5 C1 read.
//!
//! This crate parses caller-supplied bytes and proves that the activation agrees exactly with a
//! single, finalized, public Solana `getSignaturesForAddress` plan. It has no provider client,
//! credential, wallet/signing material, receipt, claim, store, persistence, capability, or I/O
//! API. A successful parse is only a semantic validation result; it grants no execution authority.

#![forbid(unsafe_code)]

use joshi_sources::{
    BuiltInExecutionDisposition, CanaryProfilePort, ProviderOperation, ProviderScopePort,
    RegisteredRunPort, RuntimeAttemptCostPort, RuntimeBudgetPort, parse_provider_run_plan_exact,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Exact activation wire-contract name.
pub const WAVE5_C1_ACTIVATION_CONTRACT: &str = "joshi.wave5.c1_activation.v1";
/// Exact activation schema version.
pub const WAVE5_C1_ACTIVATION_SCHEMA_VERSION: u16 = 1;
/// The only authority statement accepted by this semantic contract.
pub const READ_ONLY_NO_EXECUTION_AUTHORITY: &str = "read_only_no_execution";
/// The largest accepted exact activation document.
pub const MAX_WAVE5_C1_ACTIVATION_BYTES: usize = 64 * 1_024;

/// Strict, exact activation body. It intentionally has no receipt or activation-digest field.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5C1ActivationV1 {
    pub contract: String,
    pub schema_version: u16,
    pub activation_id: String,
    pub installation_id: String,
    pub run: RegisteredRunPort,
    pub exact_plan: ExactPlanClosureV1,
    /// Every independent budget bound is repeated exactly rather than implied by plan closure.
    pub budget: ExactC1BudgetProjectionV1,
    pub operations: Vec<ExactSourceMethodProjectionV1>,
    pub wallet: PublicWalletPageV1,
    pub commitment: FinalityCommitmentV1,
    pub authority: String,
}

/// Closure over the supplied *exact* final-plan byte string.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactPlanClosureV1 {
    pub plan_id: String,
    pub port_version: String,
    pub raw_exact_plan_sha256: String,
    /// Canonical unsigned decimal representation of the exact-plan byte count.
    pub raw_exact_plan_byte_length: String,
    pub plan_template_digest: String,
    pub final_plan_digest: String,
}

/// Exact budget projection of the final plan and its one reserved attempt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactC1BudgetProjectionV1 {
    pub hard_cap: RuntimeBudgetPort,
    pub attempt_cost: RuntimeAttemptCostPort,
    pub max_elapsed_ms: u64,
    pub max_ingress_bytes_per_second: Option<u64>,
    pub max_in_flight_attempts: u16,
}

/// A repeated projection of one source-registry admitted operation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactSourceMethodProjectionV1 {
    pub source_key: String,
    pub method_key: String,
    pub source_contract_fingerprint: String,
    pub method_schema_fingerprint: String,
    pub coverage_family: String,
    pub protection_domain: String,
}

/// The bounded public wallet-page parameters asserted by the activation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicWalletPageV1 {
    pub address: String,
    pub max_rows: u16,
}

/// The source contract is accepted only at finalized commitment.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FinalityCommitmentV1 {
    Finalized,
}

/// A successfully checked activation. This value is data only and grants no authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticallyValidatedC1Activation {
    activation: Wave5C1ActivationV1,
    raw_activation_sha256: String,
}

impl SemanticallyValidatedC1Activation {
    /// This semantic result never authorizes execution, I/O, storage, or a claim.
    pub const GRANTS_NO_AUTHORITY: bool = true;

    /// The strict canonical activation body that was validated.
    #[must_use]
    pub fn activation(&self) -> &Wave5C1ActivationV1 {
        &self.activation
    }

    /// SHA-256 of the exact activation bytes, with no separate activation-digest field on wire.
    #[must_use]
    pub fn raw_activation_sha256(&self) -> &str {
        &self.raw_activation_sha256
    }

    /// Explicitly states the authority ceiling of this data-only result.
    #[must_use]
    pub const fn grants_no_authority(&self) -> bool {
        Self::GRANTS_NO_AUTHORITY
    }
}

/// Refusals from exact activation parsing or C1 semantic closure validation.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum C1ActivationError {
    #[error("activation exact document is empty or too large")]
    DocumentSize,
    #[error("activation exact document could not be strictly decoded")]
    Decode,
    #[error("activation exact document is not canonical JSON")]
    NonCanonical,
    #[error("activation contract, schema, commitment, or authority is not exact")]
    Contract,
    #[error("activation identifier is not stable")]
    Identifier,
    #[error("activation digest has invalid sha256 format")]
    Digest,
    #[error("activation exact-plan byte length is not canonical decimal")]
    ByteLength,
    #[error("activation closure does not match the exact final plan")]
    PlanClosure,
    #[error("activation source-method projection does not match the final plan")]
    Projection,
    #[error("activation wallet page does not match the final plan")]
    Wallet,
    #[error("activation plan is not the isolated one-page C1 public Solana shape")]
    C1Shape,
    #[error(
        "activation plan retains provider credits, economic spend, overshoot, or hard-cap slack"
    )]
    Budget,
    #[error("exact final provider plan was refused: {0}")]
    Plan(#[from] joshi_sources::ProviderPlanError),
}

/// Strictly parse activation bytes and bind them to the supplied exact final-plan bytes.
///
/// This function performs no I/O and returns no execution/store/receipt/claim capability.
///
/// # Errors
///
/// Refuses noncanonical or ambiguous activation JSON, a noncanonical final plan, and any mismatch
/// between every declared activation projection and that exact plan.
pub fn parse_c1_activation_exact(
    exact_activation_bytes: &[u8],
    exact_final_plan_bytes: &[u8],
) -> Result<SemanticallyValidatedC1Activation, C1ActivationError> {
    if exact_activation_bytes.is_empty()
        || exact_activation_bytes.len() > MAX_WAVE5_C1_ACTIVATION_BYTES
    {
        return Err(C1ActivationError::DocumentSize);
    }
    let activation: Wave5C1ActivationV1 =
        serde_json::from_slice(exact_activation_bytes).map_err(|_| C1ActivationError::Decode)?;
    let canonical = serde_json::to_vec(&activation).map_err(|_| C1ActivationError::Decode)?;
    if canonical.as_slice() != exact_activation_bytes {
        return Err(C1ActivationError::NonCanonical);
    }
    validate_activation(&activation, exact_final_plan_bytes)?;
    Ok(SemanticallyValidatedC1Activation {
        activation,
        raw_activation_sha256: sha256(exact_activation_bytes),
    })
}

fn validate_activation(
    activation: &Wave5C1ActivationV1,
    exact_final_plan_bytes: &[u8],
) -> Result<(), C1ActivationError> {
    if activation.contract != WAVE5_C1_ACTIVATION_CONTRACT
        || activation.schema_version != WAVE5_C1_ACTIVATION_SCHEMA_VERSION
        || activation.commitment != FinalityCommitmentV1::Finalized
        || activation.authority != READ_ONLY_NO_EXECUTION_AUTHORITY
    {
        return Err(C1ActivationError::Contract);
    }
    stable_identifier(&activation.activation_id)?;
    stable_identifier(&activation.installation_id)?;
    stable_identifier(&activation.run.run_id)?;
    stable_digest(&activation.run.registration_digest)?;
    stable_identifier(&activation.exact_plan.plan_id)?;
    stable_identifier(&activation.exact_plan.port_version)?;
    stable_digest(&activation.exact_plan.raw_exact_plan_sha256)?;
    stable_digest(&activation.exact_plan.plan_template_digest)?;
    stable_digest(&activation.exact_plan.final_plan_digest)?;
    let declared_length =
        canonical_decimal_length(&activation.exact_plan.raw_exact_plan_byte_length)?;
    let plan = parse_provider_run_plan_exact(exact_final_plan_bytes)?;
    if declared_length != exact_final_plan_bytes.len()
        || activation.exact_plan.raw_exact_plan_sha256 != sha256(exact_final_plan_bytes)
    {
        return Err(C1ActivationError::PlanClosure);
    }
    if activation.run != plan.plan().run
        || activation.exact_plan.plan_id != plan.plan().plan_id
        || activation.exact_plan.port_version != plan.plan().port_version
        || activation.exact_plan.plan_template_digest != plan.plan_template_digest()
        || activation.exact_plan.final_plan_digest != plan.plan_digest()
    {
        return Err(C1ActivationError::PlanClosure);
    }
    if plan.plan().profile != CanaryProfilePort::C1
        || plan.built_in_execution() != BuiltInExecutionDisposition::ValidationOnlyNoProviderIo
        || plan.plan().max_ingress_bytes_per_second.is_some()
        || plan.plan().max_in_flight_attempts != 1
        || plan.plan().operations.len() != 1
        || plan.operations().len() != 1
    {
        return Err(C1ActivationError::C1Shape);
    }

    let operation = &plan.operations()[0];
    let operation_plan = &operation.plan;
    if operation_plan.operation != ProviderOperation::SolanaSignaturesForAddress
        || operation_plan.generation != 1
        || operation_plan.max_attempts != 1
    {
        return Err(C1ActivationError::C1Shape);
    }
    let ProviderScopePort::PublicWalletPage { address, max_rows } = &operation_plan.scope else {
        return Err(C1ActivationError::C1Shape);
    };
    if activation.wallet.address != *address || activation.wallet.max_rows != *max_rows {
        return Err(C1ActivationError::Wallet);
    }
    let expected_projection = ExactSourceMethodProjectionV1 {
        source_key: operation_plan.source_key.clone(),
        method_key: operation_plan.method_key.clone(),
        source_contract_fingerprint: operation.canonical_contract_fingerprint.clone(),
        method_schema_fingerprint: operation.method_schema_fingerprint.clone(),
        coverage_family: operation.coverage_family.clone(),
        protection_domain: operation.protection_domain.clone(),
    };
    if activation.operations.as_slice() != std::slice::from_ref(&expected_projection) {
        return Err(C1ActivationError::Projection);
    }

    let reserved = operation_plan.attempt_cost.reserved_total()?;
    if activation.budget.hard_cap != plan.plan().hard_cap
        || activation.budget.attempt_cost != operation_plan.attempt_cost
        || activation.budget.max_elapsed_ms != plan.plan().max_elapsed_ms
        || activation.budget.max_ingress_bytes_per_second
            != plan.plan().max_ingress_bytes_per_second
        || activation.budget.max_in_flight_attempts != plan.plan().max_in_flight_attempts
        || !operation_plan.attempt_cost.max_overshoot.is_zero()
        || reserved.requests != 1
        || reserved.pages != 1
        || !zero_economic_or_credits(&reserved)
        || !zero_economic_or_credits(&plan.plan().hard_cap)
        || plan.plan().hard_cap != reserved
    {
        return Err(C1ActivationError::Budget);
    }
    Ok(())
}

fn zero_economic_or_credits(budget: &RuntimeBudgetPort) -> bool {
    budget.provider_credits == 0
        && budget.provider_currency_minor.is_empty()
        && budget.chain_native_atoms.is_empty()
}

fn canonical_decimal_length(value: &str) -> Result<usize, C1ActivationError> {
    if value.is_empty()
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.len() > 1 && value.starts_with('0'))
    {
        return Err(C1ActivationError::ByteLength);
    }
    value
        .parse::<usize>()
        .map_err(|_| C1ActivationError::ByteLength)
}

fn stable_identifier(value: &str) -> Result<(), C1ActivationError> {
    if value.is_empty()
        || value.len() > 200
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
    {
        return Err(C1ActivationError::Identifier);
    }
    Ok(())
}

fn stable_digest(value: &str) -> Result<(), C1ActivationError> {
    let valid = value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    });
    if !valid {
        return Err(C1ActivationError::Digest);
    }
    Ok(())
}

fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use joshi_sources::{
        PROVIDER_RUN_PLAN_PORT_VERSION, PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT,
        PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT, ProviderOperationPlan, ProviderRunPlan,
        RuntimeAttemptCostPort, validate_provider_run_plan,
    };

    use super::*;

    const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";
    const RUN_DIGEST: &str =
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    type ActivationMutation = Box<dyn Fn(&mut Wave5C1ActivationV1)>;

    fn cost() -> RuntimeAttemptCostPort {
        RuntimeAttemptCostPort {
            worst_case: RuntimeBudgetPort {
                requests: 1,
                pages: 1,
                ingress_bytes: 1_024,
                durable_bytes: 1_024,
                provider_credits: 0,
                wall_millis: 1_000,
                provider_currency_minor: BTreeMap::new(),
                chain_native_atoms: BTreeMap::new(),
            },
            max_overshoot: RuntimeBudgetPort::default(),
        }
    }

    fn plan() -> ProviderRunPlan {
        let attempt_cost = cost();
        ProviderRunPlan {
            port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
            plan_id: "c1-plan-1".to_owned(),
            run: RegisteredRunPort {
                run_id: "run-1".to_owned(),
                registration_digest: RUN_DIGEST.to_owned(),
            },
            profile: CanaryProfilePort::C1,
            hard_cap: attempt_cost.reserved_total().unwrap(),
            max_elapsed_ms: 1_000,
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
                    max_rows: 10,
                },
                attempt_cost,
            }],
        }
    }

    fn bundle() -> (Wave5C1ActivationV1, Vec<u8>) {
        let validated = validate_provider_run_plan(plan()).unwrap();
        let bytes = validated.canonical_bytes().unwrap();
        let op = &validated.operations()[0];
        (
            Wave5C1ActivationV1 {
                contract: WAVE5_C1_ACTIVATION_CONTRACT.to_owned(),
                schema_version: WAVE5_C1_ACTIVATION_SCHEMA_VERSION,
                activation_id: "activation-1".to_owned(),
                installation_id: "installation-1".to_owned(),
                run: validated.plan().run.clone(),
                exact_plan: ExactPlanClosureV1 {
                    plan_id: validated.plan().plan_id.clone(),
                    port_version: validated.plan().port_version.clone(),
                    raw_exact_plan_sha256: sha256(&bytes),
                    raw_exact_plan_byte_length: bytes.len().to_string(),
                    plan_template_digest: validated.plan_template_digest().to_owned(),
                    final_plan_digest: validated.plan_digest().to_owned(),
                },
                budget: ExactC1BudgetProjectionV1 {
                    hard_cap: validated.plan().hard_cap.clone(),
                    attempt_cost: validated.plan().operations[0].attempt_cost.clone(),
                    max_elapsed_ms: validated.plan().max_elapsed_ms,
                    max_ingress_bytes_per_second: validated.plan().max_ingress_bytes_per_second,
                    max_in_flight_attempts: validated.plan().max_in_flight_attempts,
                },
                operations: vec![ExactSourceMethodProjectionV1 {
                    source_key: op.plan.source_key.clone(),
                    method_key: op.plan.method_key.clone(),
                    source_contract_fingerprint: op.canonical_contract_fingerprint.clone(),
                    method_schema_fingerprint: op.method_schema_fingerprint.clone(),
                    coverage_family: op.coverage_family.clone(),
                    protection_domain: op.protection_domain.clone(),
                }],
                wallet: PublicWalletPageV1 {
                    address: WALLET.to_owned(),
                    max_rows: 10,
                },
                commitment: FinalityCommitmentV1::Finalized,
                authority: READ_ONLY_NO_EXECUTION_AUTHORITY.to_owned(),
            },
            bytes,
        )
    }

    fn activation_bytes(activation: &Wave5C1ActivationV1) -> Vec<u8> {
        serde_json::to_vec(activation).unwrap()
    }

    fn close_to_exact_plan(activation: &mut Wave5C1ActivationV1, bytes: &[u8]) {
        let validated = parse_provider_run_plan_exact(bytes).unwrap();
        activation.run = validated.plan().run.clone();
        activation.exact_plan = ExactPlanClosureV1 {
            plan_id: validated.plan().plan_id.clone(),
            port_version: validated.plan().port_version.clone(),
            raw_exact_plan_sha256: sha256(bytes),
            raw_exact_plan_byte_length: bytes.len().to_string(),
            plan_template_digest: validated.plan_template_digest().to_owned(),
            final_plan_digest: validated.plan_digest().to_owned(),
        };
    }

    #[test]
    fn exact_canonical_bundle_is_semantic_only() {
        let (activation, plan_bytes) = bundle();
        let activation_bytes = activation_bytes(&activation);
        let validated = parse_c1_activation_exact(&activation_bytes, &plan_bytes).unwrap();
        assert_eq!(validated.activation(), &activation);
        assert_eq!(validated.raw_activation_sha256(), sha256(&activation_bytes));
        assert!(validated.grants_no_authority());
    }

    #[test]
    fn activation_refuses_noncanonical_unknown_and_duplicate_json() {
        let (activation, plan_bytes) = bundle();
        let canonical = activation_bytes(&activation);
        let mut whitespace = canonical.clone();
        whitespace.push(b'\n');
        assert_eq!(
            parse_c1_activation_exact(&whitespace, &plan_bytes),
            Err(C1ActivationError::NonCanonical)
        );
        let mut unknown: serde_json::Value = serde_json::from_slice(&canonical).unwrap();
        unknown["unexpected"] = serde_json::Value::Bool(true);
        assert_eq!(
            parse_c1_activation_exact(&serde_json::to_vec(&unknown).unwrap(), &plan_bytes),
            Err(C1ActivationError::Decode)
        );
        let text = std::str::from_utf8(&canonical).unwrap();
        let duplicate = text.replacen(
            "\"activationId\":\"activation-1\"",
            "\"activationId\":\"activation-1\",\"activationId\":\"activation-1\"",
            1,
        );
        assert_eq!(
            parse_c1_activation_exact(duplicate.as_bytes(), &plan_bytes),
            Err(C1ActivationError::Decode)
        );
    }

    #[test]
    fn activation_refuses_changed_closure_and_repeated_projection_fields() {
        let (activation, plan_bytes) = bundle();
        let mutations: Vec<ActivationMutation> = vec![
            Box::new(|value| value.run.run_id = "other-run".to_owned()),
            Box::new(|value| value.run.registration_digest = format!("sha256:{}", "b".repeat(64))),
            Box::new(|value| value.exact_plan.plan_id = "other-plan".to_owned()),
            Box::new(|value| value.exact_plan.port_version = "other-port".to_owned()),
            Box::new(|value| {
                value.exact_plan.raw_exact_plan_sha256 = format!("sha256:{}", "b".repeat(64));
            }),
            Box::new(|value| value.exact_plan.raw_exact_plan_byte_length = "1".to_owned()),
            Box::new(|value| {
                value.exact_plan.plan_template_digest = format!("sha256:{}", "b".repeat(64));
            }),
            Box::new(|value| {
                value.exact_plan.final_plan_digest = format!("sha256:{}", "b".repeat(64));
            }),
            Box::new(|value| value.operations[0].source_key = "other-source".to_owned()),
            Box::new(|value| value.operations[0].method_key = "other-method".to_owned()),
            Box::new(|value| {
                value.operations[0].source_contract_fingerprint =
                    format!("sha256:{}", "b".repeat(64));
            }),
            Box::new(|value| {
                value.operations[0].method_schema_fingerprint =
                    format!("sha256:{}", "b".repeat(64));
            }),
            Box::new(|value| value.operations[0].coverage_family = "other-coverage".to_owned()),
            Box::new(|value| value.operations[0].protection_domain = "other-domain".to_owned()),
            Box::new(|value| value.wallet.address = "11111111111111111111111111111111".to_owned()),
            Box::new(|value| value.wallet.max_rows = 11),
        ];
        for mutate in mutations {
            let mut changed = activation.clone();
            mutate(&mut changed);
            assert!(parse_c1_activation_exact(&activation_bytes(&changed), &plan_bytes).is_err());
        }
    }

    #[test]
    fn commitment_authority_and_bytes_are_exact() {
        let (activation, plan_bytes) = bundle();
        let mut authority = activation.clone();
        authority.authority = "read_only_with_execution".to_owned();
        assert_eq!(
            parse_c1_activation_exact(&activation_bytes(&authority), &plan_bytes),
            Err(C1ActivationError::Contract)
        );

        let mut commitment: serde_json::Value =
            serde_json::from_slice(&activation_bytes(&activation)).unwrap();
        commitment["commitment"] = serde_json::Value::String("confirmed".to_owned());
        assert_eq!(
            parse_c1_activation_exact(&serde_json::to_vec(&commitment).unwrap(), &plan_bytes),
            Err(C1ActivationError::Decode)
        );

        let mut length = activation.clone();
        length.exact_plan.raw_exact_plan_byte_length = format!("0{}", plan_bytes.len());
        assert_eq!(
            parse_c1_activation_exact(&activation_bytes(&length), &plan_bytes),
            Err(C1ActivationError::ByteLength)
        );

        let bytes = activation_bytes(&activation);
        let mut changed_id = activation.clone();
        changed_id.activation_id = "activation-2".to_owned();
        let changed_bytes = activation_bytes(&changed_id);
        let first = parse_c1_activation_exact(&bytes, &plan_bytes).unwrap();
        let second = parse_c1_activation_exact(&changed_bytes, &plan_bytes).unwrap();
        assert_ne!(
            first.raw_activation_sha256(),
            second.raw_activation_sha256()
        );
    }

    #[test]
    fn activation_repeats_each_budget_cap_exactly() {
        let (activation, plan_bytes) = bundle();
        let mut adversaries = Vec::new();
        let cap_mutations: [fn(&mut RuntimeBudgetPort); 6] = [
            |budget: &mut RuntimeBudgetPort| budget.requests += 1,
            |budget: &mut RuntimeBudgetPort| budget.pages += 1,
            |budget: &mut RuntimeBudgetPort| budget.ingress_bytes += 1,
            |budget: &mut RuntimeBudgetPort| budget.durable_bytes += 1,
            |budget: &mut RuntimeBudgetPort| budget.provider_credits += 1,
            |budget: &mut RuntimeBudgetPort| budget.wall_millis += 1,
        ];
        for cap in cap_mutations {
            let mut changed = activation.clone();
            cap(&mut changed.budget.hard_cap);
            adversaries.push(changed);
        }
        let mut currency = activation.clone();
        currency
            .budget
            .hard_cap
            .provider_currency_minor
            .insert("usd".to_owned(), 1);
        adversaries.push(currency);
        let mut native = activation.clone();
        native
            .budget
            .hard_cap
            .chain_native_atoms
            .insert("sol".to_owned(), 1);
        adversaries.push(native);
        let mut attempt = activation.clone();
        attempt.budget.attempt_cost.worst_case.ingress_bytes += 1;
        adversaries.push(attempt);
        let mut elapsed = activation.clone();
        elapsed.budget.max_elapsed_ms += 1;
        adversaries.push(elapsed);
        let mut ingress_rate = activation.clone();
        ingress_rate.budget.max_ingress_bytes_per_second = Some(1);
        adversaries.push(ingress_rate);
        let mut inflight = activation.clone();
        inflight.budget.max_in_flight_attempts = 2;
        adversaries.push(inflight);

        for changed in adversaries {
            assert_eq!(
                parse_c1_activation_exact(&activation_bytes(&changed), &plan_bytes),
                Err(C1ActivationError::Budget)
            );
        }
    }

    #[test]
    fn activation_refuses_plan_noncanonical_unknown_and_c1_shape_violations() {
        let (activation, plan_bytes) = bundle();
        let canonical_activation_bytes = activation_bytes(&activation);
        let mut whitespace = plan_bytes.clone();
        whitespace.push(b'\n');
        assert_eq!(
            parse_c1_activation_exact(&canonical_activation_bytes, &whitespace),
            Err(C1ActivationError::Plan(
                joshi_sources::ProviderPlanError::NonCanonical
            ))
        );
        let mut unknown: serde_json::Value = serde_json::from_slice(&plan_bytes).unwrap();
        unknown["unexpected"] = serde_json::Value::Bool(true);
        assert_eq!(
            parse_c1_activation_exact(
                &canonical_activation_bytes,
                &serde_json::to_vec(&unknown).unwrap()
            ),
            Err(C1ActivationError::Plan(
                joshi_sources::ProviderPlanError::Decode
            ))
        );

        let mut multi = plan();
        multi.operations.push(multi.operations[0].clone());
        assert!(
            parse_c1_activation_exact(
                &canonical_activation_bytes,
                &serde_json::to_vec(&multi).unwrap()
            )
            .is_err()
        );
        let mut retry = plan();
        retry.operations[0].max_attempts = 2;
        assert!(
            parse_c1_activation_exact(
                &canonical_activation_bytes,
                &serde_json::to_vec(&retry).unwrap()
            )
            .is_err()
        );
        let mut credits = plan();
        credits.operations[0]
            .attempt_cost
            .worst_case
            .provider_credits = 1;
        assert!(
            parse_c1_activation_exact(
                &canonical_activation_bytes,
                &serde_json::to_vec(&credits).unwrap()
            )
            .is_err()
        );
        let mut spend = plan();
        spend
            .hard_cap
            .provider_currency_minor
            .insert("usd".to_owned(), 1);
        assert!(
            parse_c1_activation_exact(
                &canonical_activation_bytes,
                &serde_json::to_vec(&spend).unwrap()
            )
            .is_err()
        );
        let mut native = plan();
        native
            .hard_cap
            .chain_native_atoms
            .insert("sol".to_owned(), 1);
        assert!(
            parse_c1_activation_exact(
                &canonical_activation_bytes,
                &serde_json::to_vec(&native).unwrap()
            )
            .is_err()
        );

        let mut generation = plan();
        generation.operations[0].generation = 2;
        let generation_bytes = serde_json::to_vec(&generation).unwrap();
        let mut generation_activation = activation.clone();
        close_to_exact_plan(&mut generation_activation, &generation_bytes);
        assert_eq!(
            parse_c1_activation_exact(&activation_bytes(&generation_activation), &generation_bytes),
            Err(C1ActivationError::C1Shape)
        );
    }

    #[test]
    fn activation_refuses_a_separate_ingress_rate_setting() {
        let (activation, _) = bundle();
        let mut ingress_rate = plan();
        ingress_rate.max_ingress_bytes_per_second = Some(1);
        let ingress_rate_bytes = serde_json::to_vec(&ingress_rate).unwrap();
        let mut ingress_rate_activation = activation;
        close_to_exact_plan(&mut ingress_rate_activation, &ingress_rate_bytes);
        assert_eq!(
            parse_c1_activation_exact(
                &activation_bytes(&ingress_rate_activation),
                &ingress_rate_bytes
            ),
            Err(C1ActivationError::C1Shape)
        );
    }

    #[test]
    fn activation_refuses_plan_budget_overshoot_and_slack() {
        let (activation, _) = bundle();
        let mut overshoot = plan();
        overshoot.operations[0].attempt_cost.max_overshoot.pages = 1;
        overshoot.hard_cap.pages = 2;
        let overshoot_bytes = serde_json::to_vec(&overshoot).unwrap();
        let mut overshoot_activation = activation.clone();
        close_to_exact_plan(&mut overshoot_activation, &overshoot_bytes);
        assert_eq!(
            parse_c1_activation_exact(&activation_bytes(&overshoot_activation), &overshoot_bytes),
            Err(C1ActivationError::Budget)
        );

        let mut slack = plan();
        slack.hard_cap.ingress_bytes += 1;
        let slack_bytes = serde_json::to_vec(&slack).unwrap();
        let mut slack_activation = activation;
        close_to_exact_plan(&mut slack_activation, &slack_bytes);
        assert_eq!(
            parse_c1_activation_exact(&activation_bytes(&slack_activation), &slack_bytes),
            Err(C1ActivationError::Budget)
        );
    }
}
