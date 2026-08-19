//! Disabled, capability-only admission for one claimed Wave 5 C1 activation.
//!
//! This is deliberately a pre-runtime seam. It consumes the store's opaque, one-shot claim,
//! binds it to the *already-open* supervisor journal identity, and checks both retained exact
//! documents again. Successful admission is a report-only value: it exposes neither an executor
//! nor a provider, transport, reservation, or I/O entry point.

use crate::{AUTHORITY_CEILING, Supervisor};
use joshi_sources::{ProviderPlanError, parse_provider_run_plan_exact};
use joshi_store::ClaimedWave5C1Activation;
use sha2::{Digest as _, Sha256};
use thiserror::Error;

/// A read-only account of a disabled C1 admission.
///
/// This is audit evidence, not a receipt that can recreate an admission or a claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DisabledC1AdmissionReport {
    pub activation_id: String,
    pub installation_id: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub plan_id: String,
    pub plan_template_digest: String,
    pub final_plan_digest: String,
    pub activation_digest: String,
    pub exact_plan_digest: String,
    pub activation_commit_sequence: u64,
    pub claim_commit_sequence: u64,
    pub claim_commit_digest: String,
    pub authority_ceiling: &'static str,
    pub execution_disposition: &'static str,
}

/// A successfully checked C1 claim that remains explicitly disabled.
///
/// The private field and intentionally absent `Clone`, `Debug`, `Serialize`, and `Deserialize`
/// implementations keep this as an in-process proof rather than transferable authority. It has
/// no method that can execute, reserve, perform provider I/O, or create a transport.
#[must_use]
pub struct DisabledC1RuntimeAdmission {
    report: DisabledC1AdmissionReport,
    // Keep the burned store capability alive for this admission's lifetime. There is
    // intentionally no accessor or recovery path: the report is structural evidence only.
    _claim: ClaimedWave5C1Activation,
}

impl DisabledC1RuntimeAdmission {
    /// Return the immutable audit report for this disabled admission.
    #[must_use]
    pub fn report(&self) -> &DisabledC1AdmissionReport {
        &self.report
    }

    /// The journal installation to which the consumed claim was bound.
    #[must_use]
    pub fn installation_id(&self) -> &str {
        &self.report.installation_id
    }

    /// The durable registration identity closed over by the exact provider plan.
    #[must_use]
    pub fn run_registration_id(&self) -> &str {
        &self.report.run_registration_id
    }

    /// The semantic authority ceiling; it remains `read_only_no_execution`.
    #[must_use]
    pub const fn authority_ceiling(&self) -> &'static str {
        AUTHORITY_CEILING
    }
}

/// Refusals before a C1 claim can become even a disabled supervisor admission.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum DisabledC1AdmissionError {
    #[error("claimed C1 activation does not bind this supervisor journal installation")]
    ForeignInstallation,
    #[error("claimed C1 activation exact bytes do not reproduce its activation body")]
    ActivationBytes,
    #[error("claimed C1 activation exact plan does not reproduce its activation closure")]
    PlanClosure,
    #[error("claimed C1 activation receipt differs from the retained exact closure")]
    ClaimReceipt,
    #[error("claimed C1 activation has impossible activation/claim commit ordering")]
    CommitOrdering,
    #[error("claimed C1 activation document was refused: {0}")]
    Activation(#[from] joshi_wave5_c1_activation::C1ActivationError),
    #[error("claimed C1 provider plan was refused: {0}")]
    Plan(#[from] ProviderPlanError),
}

/// Consume one opaque store claim and bind it to the current supervisor journal installation.
///
/// This performs only in-memory exact parsing and equality checks. In particular, it does not
/// append to the journal, reserve an occurrence, load credentials, construct a provider client,
/// perform network I/O, or initialize transport. A public activation, stored record, or receipt
/// cannot be substituted: this function accepts [`ClaimedWave5C1Activation`] by value only.
///
/// # Errors
///
/// Refuses foreign journal identity, mismatched retained exact bytes, mismatched claim evidence,
/// or invalid C1 plan closure before returning the report-only disabled admission.
fn admit_claimed_wave5_c1_activation_disabled(
    supervisor: &Supervisor,
    claim: ClaimedWave5C1Activation,
) -> Result<DisabledC1RuntimeAdmission, DisabledC1AdmissionError> {
    let actual_installation_id = supervisor.installation_id();
    let activation = claim.activation();
    if activation.installation_id != actual_installation_id {
        return Err(DisabledC1AdmissionError::ForeignInstallation);
    }

    // Reparse both exact documents before trusting their projections or the opaque claim's
    // borrowed activation body. The activation parser also proves C1's validation-only shape.
    let reparsed_activation = joshi_wave5_c1_activation::parse_c1_activation_exact(
        claim.exact_activation_bytes(),
        claim.exact_plan_bytes(),
    )?;
    if reparsed_activation.activation() != activation {
        return Err(DisabledC1AdmissionError::ActivationBytes);
    }
    let reparsed_plan = parse_provider_run_plan_exact(claim.exact_plan_bytes())?;
    if activation.run != reparsed_plan.plan().run
        || activation.exact_plan.plan_id != reparsed_plan.plan().plan_id
        || activation.exact_plan.port_version != reparsed_plan.plan().port_version
        || activation.exact_plan.plan_template_digest != reparsed_plan.plan_template_digest()
        || activation.exact_plan.final_plan_digest != reparsed_plan.plan_digest()
        || activation.exact_plan.raw_exact_plan_sha256 != sha256(claim.exact_plan_bytes())
    {
        return Err(DisabledC1AdmissionError::PlanClosure);
    }

    let receipt = claim.claim_receipt();
    if receipt.activation_id.as_str() != activation.activation_id
        || receipt.installation_id.as_str() != actual_installation_id
        || receipt.run_registration_id.as_str() != activation.run.run_id
        || receipt.run_registration_digest.as_str() != activation.run.registration_digest
        || receipt.activation_digest.as_str() != reparsed_activation.raw_activation_sha256()
        || receipt.exact_plan_digest.as_str() != activation.exact_plan.raw_exact_plan_sha256
    {
        return Err(DisabledC1AdmissionError::ClaimReceipt);
    }
    if claim.activation_commit_seq() >= receipt.claimed_commit_seq {
        return Err(DisabledC1AdmissionError::CommitOrdering);
    }

    let report = DisabledC1AdmissionReport {
        activation_id: activation.activation_id.clone(),
        installation_id: actual_installation_id.to_owned(),
        run_registration_id: activation.run.run_id.clone(),
        run_registration_digest: activation.run.registration_digest.clone(),
        plan_id: activation.exact_plan.plan_id.clone(),
        plan_template_digest: activation.exact_plan.plan_template_digest.clone(),
        final_plan_digest: activation.exact_plan.final_plan_digest.clone(),
        activation_digest: reparsed_activation.raw_activation_sha256().to_owned(),
        exact_plan_digest: activation.exact_plan.raw_exact_plan_sha256.clone(),
        activation_commit_sequence: claim.activation_commit_seq().get(),
        claim_commit_sequence: receipt.claimed_commit_seq.get(),
        claim_commit_digest: receipt.claim_commit_digest.as_str().to_owned(),
        authority_ceiling: AUTHORITY_CEILING,
        execution_disposition: "validation_only_no_provider_io",
    };
    Ok(DisabledC1RuntimeAdmission {
        report,
        _claim: claim,
    })
}

impl Supervisor {
    /// Consume one opaque store claim into a report-only admission bound to this journal.
    ///
    /// This is deliberately not a runtime constructor: it performs no reservation, provider I/O,
    /// transport initialization, or journal mutation.
    ///
    /// # Errors
    ///
    /// Refuses a claim whose exact closure or installation identity differs from this supervisor.
    pub fn admit_claimed_wave5_c1_disabled(
        &self,
        claim: ClaimedWave5C1Activation,
    ) -> Result<DisabledC1RuntimeAdmission, DisabledC1AdmissionError> {
        admit_claimed_wave5_c1_activation_disabled(self, claim)
    }
}

fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("sha256:{:x}", hasher.finalize())
}
