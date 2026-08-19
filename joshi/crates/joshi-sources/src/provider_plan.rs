//! Pure validation for the bounded C0 provider plan.
//!
//! Validation is synchronous and occurs before credential loading or provider I/O. The canonical
//! run registration and source registry remain owned by their respective crates; this module binds
//! strict opaque run-registration identity to admitted runtime contract projections.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{SourceId, contract_port::admit_runtime_method};

pub const PROVIDER_RUN_PLAN_PORT_VERSION: &str = "joshi.provider_run_plan_port.v2";
/// SHA-256 domain for a plan template which excludes only the registered-run binding.
pub const PROVIDER_RUN_PLAN_TEMPLATE_DIGEST_DOMAIN: &str = "joshi.provider_run_plan_template.v2";
/// SHA-256 domain for the final, run-bound provider plan.
pub const PROVIDER_RUN_PLAN_DIGEST_DOMAIN: &str = "joshi.provider_run_plan.final.v2";
/// Maximum accepted exact provider-plan document size.
pub const MAX_PROVIDER_RUN_PLAN_BYTES: usize = 128 * 1_024;
/// Exact source-contract digest for the sealed local C0 operation.
pub const SEALED_C0_SOURCE_CONTRACT_FINGERPRINT: &str =
    "sha256:9225070e38e092e3c4cdd48744c36f61a32fee85c1170d0edcdbdc278428a6ed";
/// Exact method-schema digest for the sealed local C0 operation.
pub const SEALED_C0_METHOD_SCHEMA_FINGERPRINT: &str =
    "sha256:b9620e8e7e33a4886382709f8e1bb6a744c65b111d68efce284d900e7b48fdb5";
/// Exact canonical source-contract digest for the bounded public Solana declaration.
pub const PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT: &str =
    "sha256:91f2d69db741edbef943e729cd65a0941de856badcd9d35cb153b5006ae6d247";
/// Exact method-schema digest for the bounded `getSignaturesForAddress` declaration.
pub const PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT: &str =
    "sha256:b3bafc833d9b859fb0dc475d62fac353d5862994bdb01fe184a6b1dd85aea715";

const MIB: u64 = 1_024 * 1_024;
/// Largest ingress and durable byte budget a C0 plan may declare.
const C0_MAX_BYTES: u64 = 64 * MIB;
/// Longest wall-clock budget a C0 plan may declare.
const C0_MAX_ELAPSED_MS: u64 = 3_600_000;

/// Which canary profile a provider plan declares.
///
/// This is a one-variant enum on purpose. It is a serialized member of the exact plan document
/// whose bytes are digested by [`PROVIDER_RUN_PLAN_DIGEST_DOMAIN`] and compared byte for byte by
/// [`parse_provider_run_plan_exact`], so removing the member — or spelling it as anything other
/// than `"c0"` — would change every plan digest in the tree. Keeping it an enum also means a
/// document naming a profile this tree no longer has is refused while it is being *decoded*,
/// rather than validated against a ladder that is no longer there.
///
/// It previously carried `C1` and `C2` rungs with their own frozen ceilings. Those rungs were
/// budget policy for provider spend that no code in this tree could actually incur, and their
/// only admitted operation reached a free public endpoint; they are gone.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CanaryProfilePort {
    C0,
}

/// Adapter operation mapped from one canonical source-registry method.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderOperation {
    SyntheticEmit,
    HeliusWalletTransactionsPage,
    SolanaSignaturesForAddress,
    SolanaTransaction,
    HeliusCompactTransactionSubscription,
    HeliusProgramLogsReference,
    HeliusFinalizedTransactionHydration,
    PumpPortalLaunchSubscription,
    PumpPortalMigrationSubscription,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeBudgetPort {
    pub requests: u64,
    pub pages: u64,
    pub ingress_bytes: u64,
    pub durable_bytes: u64,
    pub provider_credits: u64,
    pub wall_millis: u64,
    pub provider_currency_minor: BTreeMap<String, u128>,
    pub chain_native_atoms: BTreeMap<String, u128>,
}

impl RuntimeBudgetPort {
    #[must_use]
    pub fn is_zero(&self) -> bool {
        self.requests == 0
            && self.pages == 0
            && self.ingress_bytes == 0
            && self.durable_bytes == 0
            && self.provider_credits == 0
            && self.wall_millis == 0
            && self
                .provider_currency_minor
                .values()
                .all(|value| *value == 0)
            && self.chain_native_atoms.values().all(|value| *value == 0)
    }

    /// Add two exact usage vectors without saturating.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderPlanError::ArithmeticOverflow`] when any dimension cannot be represented.
    pub fn checked_add(&self, other: &Self) -> Result<Self, ProviderPlanError> {
        Ok(Self {
            requests: add(self.requests, other.requests)?,
            pages: add(self.pages, other.pages)?,
            ingress_bytes: add(self.ingress_bytes, other.ingress_bytes)?,
            durable_bytes: add(self.durable_bytes, other.durable_bytes)?,
            provider_credits: add(self.provider_credits, other.provider_credits)?,
            wall_millis: add(self.wall_millis, other.wall_millis)?,
            provider_currency_minor: checked_map_add(
                &self.provider_currency_minor,
                &other.provider_currency_minor,
            )?,
            chain_native_atoms: checked_map_add(
                &self.chain_native_atoms,
                &other.chain_native_atoms,
            )?,
        })
    }

    #[must_use]
    pub fn within(&self, cap: &Self) -> bool {
        self.requests <= cap.requests
            && self.pages <= cap.pages
            && self.ingress_bytes <= cap.ingress_bytes
            && self.durable_bytes <= cap.durable_bytes
            && self.provider_credits <= cap.provider_credits
            && self.wall_millis <= cap.wall_millis
            && map_within(&self.provider_currency_minor, &cap.provider_currency_minor)
            && map_within(&self.chain_native_atoms, &cap.chain_native_atoms)
    }

    fn checked_scale(&self, factor: u64) -> Result<Self, ProviderPlanError> {
        let factor_u128 = u128::from(factor);
        Ok(Self {
            requests: self
                .requests
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?,
            pages: self
                .pages
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?,
            ingress_bytes: self
                .ingress_bytes
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?,
            durable_bytes: self
                .durable_bytes
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?,
            provider_credits: self
                .provider_credits
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?,
            wall_millis: self
                .wall_millis
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?,
            provider_currency_minor: checked_map_scale(&self.provider_currency_minor, factor_u128)?,
            chain_native_atoms: checked_map_scale(&self.chain_native_atoms, factor_u128)?,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeAttemptCostPort {
    pub worst_case: RuntimeBudgetPort,
    pub max_overshoot: RuntimeBudgetPort,
}

impl RuntimeAttemptCostPort {
    /// Return worst case plus the separately declared bounded overshoot.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderPlanError::ArithmeticOverflow`] when a dimension cannot be represented.
    pub fn reserved_total(&self) -> Result<RuntimeBudgetPort, ProviderPlanError> {
        self.worst_case.checked_add(&self.max_overshoot)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RegisteredRunPort {
    pub run_id: String,
    pub registration_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ProviderScopePort {
    SyntheticScenario {
        scenario_id: String,
    },
    PublicWalletPage {
        address: String,
        max_rows: u16,
    },
    TransactionReferenceSet {
        reference_set_id: String,
    },
    ProgramWindow {
        program_ids: Vec<String>,
        window_millis: u64,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderOperationPlan {
    pub source_key: String,
    pub method_key: String,
    pub source_contract_fingerprint: String,
    pub method_schema_fingerprint: String,
    pub operation: ProviderOperation,
    pub generation: u64,
    pub max_attempts: u64,
    pub scope: ProviderScopePort,
    pub attempt_cost: RuntimeAttemptCostPort,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderRunPlan {
    pub port_version: String,
    pub plan_id: String,
    pub run: RegisteredRunPort,
    pub profile: CanaryProfilePort,
    pub hard_cap: RuntimeBudgetPort,
    pub max_elapsed_ms: u64,
    pub max_ingress_bytes_per_second: Option<u64>,
    pub max_in_flight_attempts: u16,
    pub operations: Vec<ProviderOperationPlan>,
}

/// Canonical pre-registration plan body. It contains every [`ProviderRunPlan`] field except the
/// run occurrence binding, breaking the config/registration/final-plan digest cycle without
/// weakening the final plan closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderRunPlanTemplate {
    pub port_version: String,
    pub plan_id: String,
    pub profile: CanaryProfilePort,
    pub hard_cap: RuntimeBudgetPort,
    pub max_elapsed_ms: u64,
    pub max_ingress_bytes_per_second: Option<u64>,
    pub max_in_flight_attempts: u16,
    pub operations: Vec<ProviderOperationPlan>,
}

impl ProviderRunPlanTemplate {
    /// Compute the domain-separated canonical template digest.
    ///
    /// The SHA-256 preimage is the UTF-8 domain, one zero byte, the big-endian encoded payload
    /// length, then the strict JSON encoding of this fixed-field struct.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderPlanError::Encode`] if strict JSON encoding fails.
    pub fn plan_template_digest(&self) -> Result<String, ProviderPlanError> {
        digest_struct(PROVIDER_RUN_PLAN_TEMPLATE_DIGEST_DOMAIN, self)
    }

    /// Add the final registered-run occurrence and registration digest.
    #[must_use]
    pub fn bind_run(self, run: RegisteredRunPort) -> ProviderRunPlan {
        ProviderRunPlan {
            port_version: self.port_version,
            plan_id: self.plan_id,
            run,
            profile: self.profile,
            hard_cap: self.hard_cap,
            max_elapsed_ms: self.max_elapsed_ms,
            max_ingress_bytes_per_second: self.max_ingress_bytes_per_second,
            max_in_flight_attempts: self.max_in_flight_attempts,
            operations: self.operations,
        }
    }
}

impl ProviderRunPlan {
    /// Project the canonical body excluding only `run_id` and `registration_digest`.
    #[must_use]
    pub fn template(&self) -> ProviderRunPlanTemplate {
        ProviderRunPlanTemplate {
            port_version: self.port_version.clone(),
            plan_id: self.plan_id.clone(),
            profile: self.profile,
            hard_cap: self.hard_cap.clone(),
            max_elapsed_ms: self.max_elapsed_ms,
            max_ingress_bytes_per_second: self.max_ingress_bytes_per_second,
            max_in_flight_attempts: self.max_in_flight_attempts,
            operations: self.operations.clone(),
        }
    }

    /// Compute the same pre-registration template digest exposed after validation.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderPlanError::Encode`] if strict JSON encoding fails.
    pub fn plan_template_digest(&self) -> Result<String, ProviderPlanError> {
        self.template().plan_template_digest()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BuiltInExecutionDisposition {
    SyntheticEnabled,
    /// The plan is safe to register/reserve but this crate exposes no live implementation.
    ///
    /// Nothing constructs this today: [`CanaryProfilePort`] has one variant and it maps to
    /// [`Self::SyntheticEnabled`]. The variant stays as the vocabulary a future profile with no
    /// built-in executor would carry, and the guards that compare against
    /// [`Self::SyntheticEnabled`] stay as fail-safes rather than active gates.
    ValidationOnlyNoProviderIo,
}

#[derive(Clone, Debug)]
pub struct ValidatedProviderOperation {
    pub plan: ProviderOperationPlan,
    pub source_id: SourceId,
    pub canonical_contract_fingerprint: String,
    pub method_schema_fingerprint: String,
    pub coverage_family: String,
    pub protection_domain: String,
}

#[derive(Clone, Debug)]
pub struct ValidatedProviderRunPlan {
    plan: ProviderRunPlan,
    plan_template_digest: String,
    plan_digest: String,
    operations: Vec<ValidatedProviderOperation>,
    execution: BuiltInExecutionDisposition,
}

impl ValidatedProviderRunPlan {
    #[must_use]
    pub fn plan(&self) -> &ProviderRunPlan {
        &self.plan
    }

    #[must_use]
    pub fn plan_digest(&self) -> &str {
        &self.plan_digest
    }

    /// Digest of every plan field except the final registered-run binding.
    #[must_use]
    pub fn plan_template_digest(&self) -> &str {
        &self.plan_template_digest
    }

    #[must_use]
    pub fn operations(&self) -> &[ValidatedProviderOperation] {
        &self.operations
    }

    #[must_use]
    pub const fn built_in_execution(&self) -> BuiltInExecutionDisposition {
        self.execution
    }

    /// Return the exact canonical JSON representation of the validated final plan.
    ///
    /// # Errors
    ///
    /// Returns [`ProviderPlanError::Encode`] if the fixed-field plan cannot be encoded.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, ProviderPlanError> {
        let bytes = serde_json::to_vec(&self.plan).map_err(|_| ProviderPlanError::Encode)?;
        if bytes.len() > MAX_PROVIDER_RUN_PLAN_BYTES {
            return Err(ProviderPlanError::DocumentSize);
        }
        Ok(bytes)
    }
}

/// Strictly parse, canonically reserialize, and validate one exact final provider plan.
///
/// This is a semantic parser only. It grants no execution, source, store, or durability authority.
///
/// # Errors
///
/// Refuses empty/oversized JSON, duplicate or unknown fixed fields, noncanonical bytes, and every
/// semantic error enforced by [`validate_provider_run_plan`].
pub fn parse_provider_run_plan_exact(
    exact_bytes: &[u8],
) -> Result<ValidatedProviderRunPlan, ProviderPlanError> {
    if exact_bytes.is_empty() || exact_bytes.len() > MAX_PROVIDER_RUN_PLAN_BYTES {
        return Err(ProviderPlanError::DocumentSize);
    }
    let plan: ProviderRunPlan =
        serde_json::from_slice(exact_bytes).map_err(|_| ProviderPlanError::Decode)?;
    let validated = validate_provider_run_plan(plan)?;
    if validated.canonical_bytes()?.as_slice() != exact_bytes {
        return Err(ProviderPlanError::NonCanonical);
    }
    Ok(validated)
}

/// Validate a provider plan against the strict runtime projection before any credential load or
/// provider I/O.
///
/// # Errors
///
/// Refuses authority/status/kill-switch violations, unbounded work, profile-incompatible methods,
/// unknown scopes, and any aggregate cost which can exceed the C0 ceiling.
#[allow(clippy::too_many_lines)]
pub fn validate_provider_run_plan(
    plan: ProviderRunPlan,
) -> Result<ValidatedProviderRunPlan, ProviderPlanError> {
    if plan.port_version != PROVIDER_RUN_PLAN_PORT_VERSION {
        return Err(ProviderPlanError::WrongPortVersion);
    }
    stable_identifier(&plan.plan_id)?;
    stable_identifier(&plan.run.run_id)?;
    stable_digest(&plan.run.registration_digest)?;
    if plan.operations.is_empty() {
        return Err(ProviderPlanError::EmptyOperations);
    }
    if plan.max_in_flight_attempts != 1 {
        return Err(ProviderPlanError::InFlightMustBeOne);
    }
    if plan.max_elapsed_ms == 0 || plan.hard_cap.wall_millis != plan.max_elapsed_ms {
        return Err(ProviderPlanError::ElapsedCapMismatch);
    }
    if !plan.hard_cap.provider_currency_minor.is_empty()
        || !plan.hard_cap.chain_native_atoms.is_empty()
    {
        return Err(ProviderPlanError::EconomicSpendForbidden);
    }

    validate_profile_caps(&plan)?;
    let mut operations = Vec::with_capacity(plan.operations.len());
    let mut total = RuntimeBudgetPort::default();
    for operation in &plan.operations {
        if operation.generation == 0 || operation.max_attempts == 0 {
            return Err(ProviderPlanError::InvalidOperationBound);
        }
        stable_identifier(&operation.source_key)?;
        stable_identifier(&operation.method_key)?;
        stable_digest(&operation.source_contract_fingerprint)?;
        stable_digest(&operation.method_schema_fingerprint)?;
        if operation.attempt_cost.worst_case.requests != 1
            || operation.attempt_cost.max_overshoot.requests != 0
        {
            return Err(ProviderPlanError::OneRequestPerAttempt);
        }
        if operation.attempt_cost.worst_case.is_zero()
            || !operation
                .attempt_cost
                .max_overshoot
                .within(&operation.attempt_cost.worst_case)
        {
            return Err(ProviderPlanError::UnboundedAttempt);
        }
        if !operation
            .attempt_cost
            .worst_case
            .provider_currency_minor
            .is_empty()
            || !operation
                .attempt_cost
                .worst_case
                .chain_native_atoms
                .is_empty()
            || !operation
                .attempt_cost
                .max_overshoot
                .provider_currency_minor
                .is_empty()
            || !operation
                .attempt_cost
                .max_overshoot
                .chain_native_atoms
                .is_empty()
        {
            return Err(ProviderPlanError::EconomicSpendForbidden);
        }
        let reserved = operation.attempt_cost.reserved_total()?;
        if reserved.durable_bytes > plan.hard_cap.durable_bytes {
            return Err(ProviderPlanError::MethodByteBoundExceeded);
        }
        validate_scope(operation.operation, &operation.scope)?;
        total = total.checked_add(&reserved.checked_scale(operation.max_attempts)?)?;
    }
    if !total.within(&plan.hard_cap) {
        return Err(ProviderPlanError::AggregateBudgetExceeded);
    }
    validate_profile_shape(&plan)?;
    for operation in &plan.operations {
        let contract = admit_runtime_method(&operation.source_key, &operation.method_key)
            .map_err(|_| ProviderPlanError::ProviderDisabledPendingCanonicalAdmission)?;
        if operation.source_contract_fingerprint != contract.canonical_contract_fingerprint {
            return Err(ProviderPlanError::SourceContractFingerprintMismatch);
        }
        if operation.method_schema_fingerprint != contract.method.schema_fingerprint {
            return Err(ProviderPlanError::MethodSchemaFingerprintMismatch);
        }
        let reserved = operation.attempt_cost.reserved_total()?;
        if contract.method.operation != operation.operation
            || operation.max_attempts > contract.method.max_attempts
            || reserved.ingress_bytes > contract.method.max_response_bytes
            || reserved.provider_credits > contract.method.max_provider_credits_per_request
        {
            return Err(ProviderPlanError::MethodContractBoundExceeded);
        }
        operations.push(ValidatedProviderOperation {
            plan: operation.clone(),
            source_id: contract.source_id,
            canonical_contract_fingerprint: contract.canonical_contract_fingerprint.clone(),
            method_schema_fingerprint: contract.method.schema_fingerprint.clone(),
            coverage_family: contract.coverage_family.clone(),
            protection_domain: contract.protection_domain.clone(),
        });
    }
    let plan_template_digest = plan.plan_template_digest()?;
    let plan_digest = digest_struct(PROVIDER_RUN_PLAN_DIGEST_DOMAIN, &plan)?;
    let execution = match plan.profile {
        CanaryProfilePort::C0 => BuiltInExecutionDisposition::SyntheticEnabled,
    };
    Ok(ValidatedProviderRunPlan {
        plan,
        plan_template_digest,
        plan_digest,
        operations,
        execution,
    })
}

fn digest_struct<T: Serialize>(domain: &str, value: &T) -> Result<String, ProviderPlanError> {
    let encoded = serde_json::to_vec(value).map_err(|_| ProviderPlanError::Encode)?;
    let encoded_len = u64::try_from(encoded.len()).map_err(|_| ProviderPlanError::Encode)?;
    let mut hasher = Sha256::new();
    hasher.update(domain.as_bytes());
    hasher.update([0]);
    hasher.update(encoded_len.to_be_bytes());
    hasher.update(encoded);
    Ok(format!("sha256:{:x}", hasher.finalize()))
}

fn validate_profile_caps(plan: &ProviderRunPlan) -> Result<(), ProviderPlanError> {
    let cap = &plan.hard_cap;
    match plan.profile {
        CanaryProfilePort::C0 => {
            if cap.provider_credits != 0
                || !cap.provider_currency_minor.is_empty()
                || !cap.chain_native_atoms.is_empty()
            {
                return Err(ProviderPlanError::C0MustBeFree);
            }
            if cap.ingress_bytes > C0_MAX_BYTES
                || cap.durable_bytes > C0_MAX_BYTES
                || plan.max_elapsed_ms > C0_MAX_ELAPSED_MS
            {
                return Err(ProviderPlanError::ProfileCapExceeded);
            }
        }
    }
    Ok(())
}

fn validate_scope(
    operation: ProviderOperation,
    scope: &ProviderScopePort,
) -> Result<(), ProviderPlanError> {
    match (operation, scope) {
        (
            ProviderOperation::SyntheticEmit,
            ProviderScopePort::SyntheticScenario { scenario_id },
        ) => stable_identifier(scenario_id),
        (
            ProviderOperation::HeliusWalletTransactionsPage
            | ProviderOperation::SolanaSignaturesForAddress,
            ProviderScopePort::PublicWalletPage { address, max_rows },
        ) => {
            validate_address(address)?;
            if *max_rows == 0 || *max_rows > 100 {
                return Err(ProviderPlanError::InvalidWalletPage);
            }
            Ok(())
        }
        (
            ProviderOperation::SolanaTransaction
            | ProviderOperation::HeliusFinalizedTransactionHydration,
            ProviderScopePort::TransactionReferenceSet { reference_set_id },
        ) => stable_identifier(reference_set_id),
        (
            ProviderOperation::HeliusCompactTransactionSubscription
            | ProviderOperation::HeliusProgramLogsReference,
            ProviderScopePort::ProgramWindow {
                program_ids,
                window_millis,
            },
        ) => {
            if program_ids.is_empty() || program_ids.len() > 4 || *window_millis == 0 {
                return Err(ProviderPlanError::InvalidProgramWindow);
            }
            for program in program_ids {
                validate_address(program)?;
            }
            Ok(())
        }
        _ => Err(ProviderPlanError::ScopeOperationMismatch),
    }
}

fn validate_profile_shape(plan: &ProviderRunPlan) -> Result<(), ProviderPlanError> {
    match plan.profile {
        CanaryProfilePort::C0 => {
            if plan.operations.len() != 1
                || plan.operations[0].operation != ProviderOperation::SyntheticEmit
            {
                return Err(ProviderPlanError::C0RequiresSingleSyntheticOperation);
            }
        }
    }
    Ok(())
}

fn validate_address(value: &str) -> Result<(), ProviderPlanError> {
    let decoded = bs58::decode(value)
        .into_vec()
        .map_err(|_| ProviderPlanError::InvalidAddress)?;
    if decoded.len() != 32 {
        return Err(ProviderPlanError::InvalidAddress);
    }
    Ok(())
}

fn stable_identifier(value: &str) -> Result<(), ProviderPlanError> {
    if value.is_empty()
        || value.len() > 200
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
    {
        return Err(ProviderPlanError::InvalidIdentifier);
    }
    Ok(())
}

fn stable_digest(value: &str) -> Result<(), ProviderPlanError> {
    stable_identifier(value)?;
    let valid = value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    });
    if !valid {
        return Err(ProviderPlanError::InvalidDigest);
    }
    Ok(())
}

fn add(left: u64, right: u64) -> Result<u64, ProviderPlanError> {
    left.checked_add(right)
        .ok_or(ProviderPlanError::ArithmeticOverflow)
}

fn checked_map_add(
    left: &BTreeMap<String, u128>,
    right: &BTreeMap<String, u128>,
) -> Result<BTreeMap<String, u128>, ProviderPlanError> {
    let mut result = left.clone();
    for (key, value) in right {
        stable_identifier(key)?;
        let entry = result.entry(key.clone()).or_default();
        *entry = entry
            .checked_add(*value)
            .ok_or(ProviderPlanError::ArithmeticOverflow)?;
    }
    Ok(result)
}

fn checked_map_scale(
    values: &BTreeMap<String, u128>,
    factor: u128,
) -> Result<BTreeMap<String, u128>, ProviderPlanError> {
    values
        .iter()
        .map(|(key, value)| {
            stable_identifier(key)?;
            let value = value
                .checked_mul(factor)
                .ok_or(ProviderPlanError::ArithmeticOverflow)?;
            Ok((key.clone(), value))
        })
        .collect()
}

fn map_within(actual: &BTreeMap<String, u128>, cap: &BTreeMap<String, u128>) -> bool {
    actual
        .iter()
        .all(|(key, value)| cap.get(key).is_some_and(|limit| value <= limit))
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ProviderPlanError {
    #[error("wrong provider-run plan port version")]
    WrongPortVersion,
    #[error("invalid non-secret provider plan identifier")]
    InvalidIdentifier,
    #[error("invalid registered-run digest")]
    InvalidDigest,
    #[error("provider plan has no operations")]
    EmptyOperations,
    #[error("provider plans permit exactly one in-flight attempt")]
    InFlightMustBeOne,
    #[error("elapsed hard cap and budget wall milliseconds disagree")]
    ElapsedCapMismatch,
    #[error("provider currency and chain-native spend are forbidden")]
    EconomicSpendForbidden,
    #[error("provider disabled pending canonical source-registry admission")]
    ProviderDisabledPendingCanonicalAdmission,
    #[error("operation generation and attempt bounds must be nonzero")]
    InvalidOperationBound,
    #[error("each reserved attempt must contain exactly one request and no request overshoot")]
    OneRequestPerAttempt,
    #[error("attempt cost or overshoot is not bounded")]
    UnboundedAttempt,
    #[error("attempt exceeds the admitted method byte bound")]
    MethodByteBoundExceeded,
    #[error("attempt exceeds the canonical method's operation, retry, byte, or cost bound")]
    MethodContractBoundExceeded,
    #[error("operation scope does not match its admitted method")]
    ScopeOperationMismatch,
    #[error("wallet page is outside the one-to-100-row envelope")]
    InvalidWalletPage,
    #[error("program window is empty or outside its structural bound")]
    InvalidProgramWindow,
    #[error("invalid Solana address")]
    InvalidAddress,
    #[error("aggregate worst-case cost exceeds the registered run cap")]
    AggregateBudgetExceeded,
    #[error("provider plan exceeds its C0 hard ceiling")]
    ProfileCapExceeded,
    #[error("C0 must have no provider-credit or economic budget")]
    C0MustBeFree,
    #[error("C0 requires exactly one sealed synthetic operation")]
    C0RequiresSingleSyntheticOperation,
    #[error("provider operation is not admitted by this canary profile")]
    ProfileOperationMismatch,
    #[error("provider plan arithmetic overflow")]
    ArithmeticOverflow,
    #[error("provider plan source-contract fingerprint differs from the canonical registry")]
    SourceContractFingerprintMismatch,
    #[error("provider plan method-schema fingerprint differs from the canonical registry")]
    MethodSchemaFingerprintMismatch,
    #[error("provider plan could not be encoded")]
    Encode,
    #[error("provider plan exact document is empty or too large")]
    DocumentSize,
    #[error("provider plan exact document could not be strictly decoded")]
    Decode,
    #[error("provider plan exact document is not canonical JSON")]
    NonCanonical,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attempt_cost(credits: u64, elapsed: u64) -> RuntimeAttemptCostPort {
        RuntimeAttemptCostPort {
            worst_case: RuntimeBudgetPort {
                requests: 1,
                pages: 1,
                ingress_bytes: MIB,
                durable_bytes: MIB,
                provider_credits: credits,
                wall_millis: elapsed,
                ..RuntimeBudgetPort::default()
            },
            max_overshoot: RuntimeBudgetPort::default(),
        }
    }

    fn run(profile: CanaryProfilePort, operations: Vec<ProviderOperationPlan>) -> ProviderRunPlan {
        let (requests, credits, ingress, durable, elapsed) = match profile {
            CanaryProfilePort::C0 => (25, 0, 64 * MIB, 64 * MIB, 60_000),
        };
        ProviderRunPlan {
            port_version: PROVIDER_RUN_PLAN_PORT_VERSION.to_owned(),
            plan_id: "plan-1".to_owned(),
            run: RegisteredRunPort {
                run_id: "run-1".to_owned(),
                registration_digest:
                    "sha256:9225070e38e092e3c4cdd48744c36f61a32fee85c1170d0edcdbdc278428a6ed"
                        .to_owned(),
            },
            profile,
            hard_cap: RuntimeBudgetPort {
                requests,
                pages: requests,
                ingress_bytes: ingress,
                durable_bytes: durable,
                provider_credits: credits,
                wall_millis: elapsed,
                ..RuntimeBudgetPort::default()
            },
            max_elapsed_ms: elapsed,
            max_ingress_bytes_per_second: None,
            max_in_flight_attempts: 1,
            operations,
        }
    }

    #[test]
    fn c0_sealed_synthetic_plan_is_the_only_built_in_execution() {
        let plan = run(
            CanaryProfilePort::C0,
            vec![ProviderOperationPlan {
                source_key: "synthetic.local".to_owned(),
                method_key: "emit".to_owned(),
                source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
                operation: ProviderOperation::SyntheticEmit,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::SyntheticScenario {
                    scenario_id: "walking-fixture".to_owned(),
                },
                attempt_cost: attempt_cost(0, 1_000),
            }],
        );
        let validated = validate_provider_run_plan(plan).unwrap();
        assert_eq!(
            validated.built_in_execution(),
            BuiltInExecutionDisposition::SyntheticEnabled
        );
        assert!(validated.plan_digest().starts_with("sha256:"));
    }

    #[test]
    fn v1_plan_wire_refuses_after_fingerprint_binding_upgrade() {
        let mut plan = run(
            CanaryProfilePort::C0,
            vec![ProviderOperationPlan {
                source_key: "synthetic.local".to_owned(),
                method_key: "emit".to_owned(),
                source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
                operation: ProviderOperation::SyntheticEmit,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::SyntheticScenario {
                    scenario_id: "v1-refusal".to_owned(),
                },
                attempt_cost: attempt_cost(0, 1_000),
            }],
        );
        plan.port_version = "joshi.provider_run_plan_port.v1".to_owned();
        assert_eq!(
            validate_provider_run_plan(plan).unwrap_err(),
            ProviderPlanError::WrongPortVersion
        );
    }

    #[test]
    fn exact_final_plan_roundtrips_and_refuses_noncanonical_or_ambiguous_json() {
        let plan = run(
            CanaryProfilePort::C0,
            vec![ProviderOperationPlan {
                source_key: "synthetic.local".to_owned(),
                method_key: "emit".to_owned(),
                source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
                method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
                operation: ProviderOperation::SyntheticEmit,
                generation: 1,
                max_attempts: 1,
                scope: ProviderScopePort::SyntheticScenario {
                    scenario_id: "canonical-roundtrip".to_owned(),
                },
                attempt_cost: attempt_cost(0, 10_000),
            }],
        );
        let validated = validate_provider_run_plan(plan).expect("valid plan");
        let canonical = validated.canonical_bytes().expect("canonical bytes");
        let reparsed = parse_provider_run_plan_exact(&canonical).expect("exact parser");
        assert_eq!(reparsed.plan(), validated.plan());
        assert_eq!(reparsed.plan_digest(), validated.plan_digest());
        assert_eq!(
            reparsed.plan_template_digest(),
            validated.plan_template_digest()
        );

        let mut whitespace = canonical.clone();
        whitespace.push(b'\n');
        assert_eq!(
            parse_provider_run_plan_exact(&whitespace).unwrap_err(),
            ProviderPlanError::NonCanonical
        );

        let mut root: serde_json::Value = serde_json::from_slice(&canonical).unwrap();
        root.as_object_mut()
            .unwrap()
            .insert("unexpected".to_owned(), serde_json::Value::Bool(true));
        assert_eq!(
            parse_provider_run_plan_exact(&serde_json::to_vec(&root).unwrap()).unwrap_err(),
            ProviderPlanError::Decode
        );

        let canonical_text = std::str::from_utf8(&canonical).unwrap();
        let duplicate = canonical_text.replacen(
            "\"planId\":\"plan-1\"",
            "\"planId\":\"plan-1\",\"planId\":\"plan-1\"",
            1,
        );
        assert_eq!(
            parse_provider_run_plan_exact(duplicate.as_bytes()).unwrap_err(),
            ProviderPlanError::Decode
        );

        let mut unknown_scope: serde_json::Value = serde_json::from_slice(&canonical).unwrap();
        unknown_scope["operations"][0]["scope"]["unexpected"] =
            serde_json::Value::String("hidden".to_owned());
        assert_eq!(
            parse_provider_run_plan_exact(&serde_json::to_vec(&unknown_scope).unwrap())
                .unwrap_err(),
            ProviderPlanError::Decode
        );
        assert_eq!(
            parse_provider_run_plan_exact(&vec![b' '; MAX_PROVIDER_RUN_PLAN_BYTES + 1])
                .unwrap_err(),
            ProviderPlanError::DocumentSize
        );

        let mut enormous_attempt_count = validated.plan().clone();
        enormous_attempt_count.operations[0].max_attempts = u64::MAX;
        assert_eq!(
            validate_provider_run_plan(enormous_attempt_count).unwrap_err(),
            ProviderPlanError::ArithmeticOverflow
        );
    }

    #[test]
    fn a_substituted_source_or_method_fingerprint_is_refused_against_the_registry() {
        let operation = ProviderOperationPlan {
            source_key: "synthetic.local".to_owned(),
            method_key: "emit".to_owned(),
            source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
            method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
            operation: ProviderOperation::SyntheticEmit,
            generation: 1,
            max_attempts: 1,
            scope: ProviderScopePort::SyntheticScenario {
                scenario_id: "fingerprint-substitution".to_owned(),
            },
            attempt_cost: attempt_cost(0, 10_000),
        };
        let mut source_substitution = run(CanaryProfilePort::C0, vec![operation.clone()]);
        source_substitution.operations[0].source_contract_fingerprint =
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_owned();
        assert_eq!(
            validate_provider_run_plan(source_substitution).unwrap_err(),
            ProviderPlanError::SourceContractFingerprintMismatch
        );

        let mut method_substitution = run(CanaryProfilePort::C0, vec![operation]);
        method_substitution.operations[0].method_schema_fingerprint =
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_owned();
        assert_eq!(
            validate_provider_run_plan(method_substitution).unwrap_err(),
            ProviderPlanError::MethodSchemaFingerprintMismatch
        );
    }

    #[test]
    fn template_digest_excludes_only_the_final_run_binding() {
        let operation = ProviderOperationPlan {
            source_key: "synthetic.local".to_owned(),
            method_key: "emit".to_owned(),
            source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
            method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
            operation: ProviderOperation::SyntheticEmit,
            generation: 1,
            max_attempts: 1,
            scope: ProviderScopePort::SyntheticScenario {
                scenario_id: "digest-walk".to_owned(),
            },
            attempt_cost: attempt_cost(0, 1_000),
        };
        let first = run(CanaryProfilePort::C0, vec![operation]);
        let mut second = first.clone();
        second.run.run_id = "run-2".to_owned();
        second.run.registration_digest =
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_owned();

        let first = validate_provider_run_plan(first).unwrap();
        let second = validate_provider_run_plan(second).unwrap();
        assert_eq!(first.plan_template_digest(), second.plan_template_digest());
        assert_ne!(first.plan_digest(), second.plan_digest());
    }

    #[test]
    fn template_digest_detects_source_method_operation_and_cap_substitution() {
        let operation = ProviderOperationPlan {
            source_key: "synthetic.local".to_owned(),
            method_key: "emit".to_owned(),
            source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
            method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
            operation: ProviderOperation::SyntheticEmit,
            generation: 1,
            max_attempts: 1,
            scope: ProviderScopePort::SyntheticScenario {
                scenario_id: "digest-walk".to_owned(),
            },
            attempt_cost: attempt_cost(0, 1_000),
        };
        let base = run(CanaryProfilePort::C0, vec![operation]);
        let base_digest = base.plan_template_digest().unwrap();

        let mut source = base.clone();
        source.operations[0].source_key = "synthetic.substituted".to_owned();
        assert_ne!(base_digest, source.plan_template_digest().unwrap());

        let mut method = base.clone();
        method.operations[0].method_key = "substituted".to_owned();
        assert_ne!(base_digest, method.plan_template_digest().unwrap());

        let mut source_fingerprint = base.clone();
        source_fingerprint.operations[0].source_contract_fingerprint =
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_owned();
        assert_ne!(
            base_digest,
            source_fingerprint.plan_template_digest().unwrap()
        );

        let mut method_fingerprint = base.clone();
        method_fingerprint.operations[0].method_schema_fingerprint =
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_owned();
        assert_ne!(
            base_digest,
            method_fingerprint.plan_template_digest().unwrap()
        );

        let mut operation = base.clone();
        operation.operations[0].operation = ProviderOperation::SolanaTransaction;
        assert_ne!(base_digest, operation.plan_template_digest().unwrap());

        let mut cap = base.clone();
        cap.hard_cap.ingress_bytes -= 1;
        assert_ne!(base_digest, cap.plan_template_digest().unwrap());
    }

    #[test]
    fn final_plan_validation_still_requires_the_run_binding() {
        let operation = ProviderOperationPlan {
            source_key: "synthetic.local".to_owned(),
            method_key: "emit".to_owned(),
            source_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
            method_schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
            operation: ProviderOperation::SyntheticEmit,
            generation: 1,
            max_attempts: 1,
            scope: ProviderScopePort::SyntheticScenario {
                scenario_id: "digest-walk".to_owned(),
            },
            attempt_cost: attempt_cost(0, 1_000),
        };
        let mut missing_run = run(CanaryProfilePort::C0, vec![operation.clone()]);
        missing_run.run.run_id.clear();
        assert_eq!(
            validate_provider_run_plan(missing_run).unwrap_err(),
            ProviderPlanError::InvalidIdentifier
        );

        let mut malformed_registration = run(CanaryProfilePort::C0, vec![operation]);
        malformed_registration.run.registration_digest = "sha256:short".to_owned();
        assert_eq!(
            validate_provider_run_plan(malformed_registration).unwrap_err(),
            ProviderPlanError::InvalidDigest
        );
    }
}
