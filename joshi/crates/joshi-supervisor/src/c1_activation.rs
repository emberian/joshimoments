//! Disabled, capability-only admission for one claimed Wave 5 C1 activation.
//!
//! This is deliberately a pre-runtime seam. It consumes one store claim — the store burns exactly
//! one activation to produce it — binds it to the *already-open* supervisor journal identity, and
//! reparses both retained exact documents. Successful admission is a report-only value: it
//! exposes neither an executor nor a provider, transport, reservation, or I/O entry point.
//!
//! # Which refusals are live, and which are dead branches
//!
//! Through the only path that can produce the input, exactly one refusal is reachable:
//! [`DisabledC1AdmissionError::ForeignInstallation`]. [`ClaimedWave5C1Activation`] has a single
//! constructor, [`joshi_store::SqliteStore::claim_wave5_c1_activation_v1`], which builds it from a
//! durable row that [`joshi_wave5_c1_activation::parse_c1_activation_exact`] already accepted over
//! exactly the two byte strings the claim then carries. Both parsers used here are pure functions
//! of those bytes — no clock, environment, or mutable registry — so reparsing them in this module
//! recomputes the same values and every equality rechecked below was already proved by the store.
//!
//! The rechecks are kept, but as defence in depth against a future second constructor for a claim,
//! not as active gates. Each variant of [`DisabledC1AdmissionError`] documents its own reachability
//! and what would have to change to make it live. Nothing in this module should be read as evidence
//! that those five conditions are being enforced here for the first time.
//!
//! Scope, so this is not read as more than it is: the burn the store performs is per activation.
//! Neither the store nor this seam bounds how many C1 activations a catalog may hold or how many
//! claims it may issue in total, and this function appends nothing durable, so admitting a claim
//! here leaves no record that could support such a bound. See the module documentation on
//! `joshi_store::wave5_c1` for what is and is not capped.

use crate::{AUTHORITY_CEILING, Supervisor};
use joshi_sources::{
    BuiltInExecutionDisposition, ProviderPlanError, parse_provider_run_plan_exact,
};
use joshi_store::ClaimedWave5C1Activation;
use sha2::{Digest as _, Sha256};
use thiserror::Error;

/// The only execution disposition a C1 plan may carry, as the report spells it.
///
/// This string is not asserted about the plan; it is the rendering of exactly one variant of
/// [`BuiltInExecutionDisposition`], reached only through the match in
/// [`admit_claimed_wave5_c1_activation_disabled`]. No store-produced claim can carry the other
/// variant — see [`DisabledC1AdmissionError::ExecutionDisposition`] — so in practice this is the
/// only string the report ever publishes.
const VALIDATION_ONLY_DISPOSITION: &str = "validation_only_no_provider_io";

/// A read-only account of a disabled C1 admission.
///
/// This is a plain public data record, not an attestation. Every field is `pub` and the type
/// derives `Clone`, so any crate can mint one with arbitrary contents; possessing one is therefore
/// no evidence that an admission ever happened, that a claim was burned, or that this installation
/// produced it. What is true is the converse half: it carries no private material and cannot
/// recreate an admission, a claim, or the consumed capability.
///
/// `claim_commit_digest` binds less than its name suggests. The store sets a claim's maintenance
/// commit digest to the digest of the claim operation domain together with the activation digest
/// and the exact-plan digest, and both of those are derivable from the exact activation bytes
/// alone — the first is their SHA-256 and the second is a field inside them. Anyone holding those
/// public bytes can recompute it offline. It names no catalog, installation, wall time, or prior
/// commit.
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
    /// The admitted plan's built-in execution disposition, re-derived from the exact plan bytes.
    ///
    /// This is not a constant the report asserts about itself: it is produced by matching on
    /// [`joshi_sources::ValidatedProviderRunPlan::built_in_execution`] for the plan reparsed from
    /// the claim's retained bytes.
    ///
    /// The match is not a live filter. `joshi_sources` derives the disposition from the plan
    /// profile alone and yields `SyntheticEnabled` only for `CanaryProfilePort::C0`, which a C1
    /// activation cannot carry, so this field is `validation_only_no_provider_io` for every claim
    /// the store can produce. Re-deriving it still keeps the published string a value this function
    /// computed from bytes rather than a literal copied onto the report.
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

    /// The authority ceiling this admission recorded.
    ///
    /// [`AUTHORITY_CEILING`] is the only value ever assigned to the report's `authority_ceiling`,
    /// and that assignment is in the same function that builds the report, so this accessor cannot
    /// disagree with the constant and a caller comparing the two learns nothing about the
    /// admission. What a comparison against an *independently sourced* string does establish is
    /// agreement between this crate's constant and that other source — for example the `authority`
    /// field of the exact activation document, which
    /// [`joshi_wave5_c1_activation::parse_c1_activation_exact`] independently requires to be
    /// `read_only_no_execution`.
    #[must_use]
    pub const fn authority_ceiling(&self) -> &'static str {
        self.report.authority_ceiling
    }

    /// The execution disposition re-derived from the admitted plan's exact bytes.
    #[must_use]
    pub const fn execution_disposition(&self) -> &'static str {
        self.report.execution_disposition
    }
}

/// Refusals before a C1 claim can become even a disabled supervisor admission.
///
/// Only [`ForeignInstallation`](Self::ForeignInstallation) is reachable through
/// [`Supervisor::admit_claimed_wave5_c1_disabled`], which is the sole public path. The rest are
/// documented individually with the construction that makes them dead today.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum DisabledC1AdmissionError {
    /// **Reachable.** The one refusal a caller can actually trigger.
    ///
    /// The store binds a claim to the installation named by the activation document, but nothing
    /// prevents that claim from being handed to a *different* open supervisor journal. This is the
    /// check that refuses it, and it is what makes the several installation equalities further
    /// down redundant.
    #[error("claimed C1 activation does not bind this supervisor journal installation")]
    ForeignInstallation,
    /// **Unreachable by construction.** Kept as defence in depth.
    ///
    /// The claim's `activation()` projection *is* the activation body
    /// [`joshi_wave5_c1_activation::parse_c1_activation_exact`] produced from the same
    /// `exact_activation_bytes()` and `exact_plan_bytes()` this seam reparses, cloned unchanged
    /// into the row the store returns. Both are the same pure function of the same bytes, so they
    /// cannot differ.
    ///
    /// It becomes live if a second constructor for [`ClaimedWave5C1Activation`] appears that can
    /// take a projection from a different source than its retained bytes — a deserializing
    /// constructor, a builder, or a store readback that stops reparsing.
    #[error("claimed C1 activation exact bytes do not reproduce its activation body")]
    ActivationBytes,
    /// **Unreachable by construction.** Kept as defence in depth.
    ///
    /// Every disjunct restates a check `joshi_wave5_c1_activation` already performed against
    /// `parse_provider_run_plan_exact` of these same plan bytes: the run identity, plan id, port
    /// version, template digest, final plan digest, and the SHA-256 of the exact plan bytes.
    ///
    /// It becomes live if the activation parser is widened to stop closing the activation over the
    /// exact plan, or if a claim can be constructed carrying plan bytes that were never the ones
    /// the activation was validated against.
    #[error("claimed C1 activation exact plan does not reproduce its activation closure")]
    PlanClosure,
    /// **Unreachable by construction.** Kept as defence in depth.
    ///
    /// The store refuses to return a claim receipt whose installation, activation digest,
    /// exact-plan digest, run identity, or run digest differs from the stored activation closure,
    /// and refuses a stored activation whose identity differs from the key it was loaded by. That
    /// closure is derived from the same parsed activation body this seam compares against. The
    /// remaining disjunct, the receipt naming this journal, is already forced by
    /// [`ForeignInstallation`](Self::ForeignInstallation) above it.
    ///
    /// It becomes live if the store stops cross-checking the claim row against the activation
    /// closure on readback, or if a claim can be constructed from a receipt supplied separately
    /// from the activation it belongs to.
    #[error("claimed C1 activation receipt differs from the retained exact closure")]
    ClaimReceipt,
    /// **Unreachable by construction.** Kept as defence in depth.
    ///
    /// This is the identical predicate the store applies when reading the claim row back: it
    /// refuses a receipt whose claimed commit sequence does not strictly follow the activation's
    /// own commit sequence.
    ///
    /// It becomes live if that readback check is removed, or if a claim can be constructed with
    /// commit sequences that never passed through one durable commit ledger.
    #[error("claimed C1 activation has impossible activation/claim commit ordering")]
    CommitOrdering,
    /// **Unreachable by construction, twice over.** Kept as defence in depth.
    ///
    /// [`joshi_wave5_c1_activation::parse_c1_activation_exact`] refuses any activation whose plan
    /// does not carry `ValidationOnlyNoProviderIo`, and `joshi_sources` derives that disposition
    /// from the plan profile alone, yielding `SyntheticEnabled` only for `CanaryProfilePort::C0` —
    /// which the same parser refuses for a C1 activation.
    ///
    /// It becomes live if the disposition stops being a function of the profile, or if the
    /// activation parser stops pinning the profile and the disposition.
    #[error("claimed C1 provider plan carries a built-in execution disposition other than C1's")]
    ExecutionDisposition,
    /// **Unreachable by construction.** The store parsed these exact bytes successfully in order
    /// to construct the claim, and the parser is a pure function of them.
    #[error("claimed C1 activation document was refused: {0}")]
    Activation(#[from] joshi_wave5_c1_activation::C1ActivationError),
    /// **Unreachable by construction.** Same reason as
    /// [`Activation`](Self::Activation): the store already parsed these plan bytes.
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
/// Against any claim the store can produce, the only refusal that can fire is
/// [`DisabledC1AdmissionError::ForeignInstallation`]: an activation document that names a journal
/// installation other than this supervisor's. The remaining variants — mismatched retained exact
/// bytes, a broken plan closure, mismatched claim evidence, impossible commit ordering, a non-C1
/// execution disposition, and either parse failure — are defence in depth against a future second
/// constructor for a claim and are unreachable today; each variant documents why.
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

    // Re-derive the reported disposition from the plan just reparsed out of the claim's retained
    // bytes, rather than restating a literal. `SyntheticEnabled` is the C0 disposition and is the
    // only other variant; it must not reach a report that says provider I/O is out of scope.
    //
    // This arm is dead for every claim the store can produce, and doubly so: the activation parser
    // already rejects a plan that is not `ValidationOnlyNoProviderIo`, and `joshi_sources` derives
    // the disposition from the plan profile, emitting `SyntheticEnabled` only for C0. The value of
    // the match is not the refusal but the derivation — the string this function publishes is one
    // it computed from bytes and could in principle have refused, not a constant nothing re-derives.
    let execution_disposition = match reparsed_plan.built_in_execution() {
        BuiltInExecutionDisposition::ValidationOnlyNoProviderIo => VALIDATION_ONLY_DISPOSITION,
        BuiltInExecutionDisposition::SyntheticEnabled => {
            return Err(DisabledC1AdmissionError::ExecutionDisposition);
        }
    };

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
        execution_disposition,
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
    /// Refuses a claim whose activation document names a journal installation other than this
    /// supervisor's, with [`DisabledC1AdmissionError::ForeignInstallation`]. That is the only
    /// refusal reachable through this method: every other variant of
    /// [`DisabledC1AdmissionError`] restates a check the store already performed while building
    /// the claim, and is kept as defence in depth rather than as an active gate. See that enum's
    /// per-variant documentation.
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
