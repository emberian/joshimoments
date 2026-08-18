//! Strict, inert Wave 5 run-registration contracts.
//!
//! A run registration freezes exact build, source-tree, configuration, budget, privacy, and
//! daily-use-surface-profile documents before provider I/O. These DTOs perform no I/O and make no
//! source, coverage, execution, or profitability claim.

use crate::{
    AdmissionError,
    operational::{AUTHORITY, ExactByteClosureV1, OperationalStatus},
    strict_json,
};
use joshi_domain::UtcTimestamp;
use serde::{Deserialize, Serialize};

pub use crate::wave5_components::{
    BuildManifestV1, BuildProfile, CollectorRuntimeConfigV1, CredentialHandlingV1,
    ExecutionAccountingDocumentV1, LocalStatusEndpointV1, PermittedProtectionClassV1,
    PrivacyPolicyV1, ProviderExecutionModeV1, RunBudgetLimitsV1,
    SemanticallyValidatedRunDocumentsV1, SourceTreeHeadV1, SourceTreeManifestV1,
    WalletMaterialRuleV1, validate_wave5_run_component_documents,
};

/// Exact contract name for a Wave 5 run registration.
pub const WAVE5_RUN_REGISTRATION_CONTRACT: &str = "joshi.wave5.run_registration";
/// Exact contract name for the durable store receipt closing a run registration.
pub const WAVE5_RUN_REGISTRATION_RECEIPT_CONTRACT: &str =
    "joshi.store.wave5_run_registration_receipt";
/// Exact contract name for an inert binding from an operational object to a registered run.
pub const WAVE5_RUN_BINDING_CONTRACT: &str = "joshi.wave5.run_binding";
/// Maximum accepted size for one canonical Wave 5 registration, receipt, or binding.
pub const MAX_WAVE5_RUN_DOCUMENT_BYTES: usize = 128 * 1024;

/// An immutable named document closed by its exact serialized bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactRegisteredDocumentV1 {
    /// Stable identity in the namespace of the containing field.
    pub document_id: String,
    /// Digest and exact byte-length closure of the document.
    pub exact_bytes: ExactByteClosureV1,
}

impl ExactRegisteredDocumentV1 {
    /// Validates the stable identity and positive exact byte length.
    ///
    /// # Errors
    ///
    /// Refuses a non-ASCII identity or a zero/noncanonical byte length.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_stable_ascii(&self.document_id, "documentId")?;
        require_positive_wire(&self.exact_bytes.byte_length, "exactBytes.byteLength").map(|_| ())
    }

    /// Verifies this document reference against its exact bytes.
    ///
    /// # Errors
    ///
    /// Refuses a malformed reference or any byte-length/digest substitution.
    pub fn verify(&self, bytes: &[u8]) -> Result<(), AdmissionError> {
        self.validate()?;
        self.exact_bytes.verify(bytes)
    }
}

/// The exact component bytes used to verify one run registration.
#[derive(Clone, Copy, Debug)]
pub struct Wave5RunRegistrationBytes<'a> {
    /// Exact build-manifest bytes.
    pub build: &'a [u8],
    /// Exact source-tree-manifest bytes.
    pub source_tree: &'a [u8],
    /// Exact collector/core configuration bytes.
    pub configuration: &'a [u8],
    /// Exact budget-policy bytes.
    pub budget: &'a [u8],
    /// Exact privacy-policy bytes.
    pub privacy: &'a [u8],
    /// Exact `DailyUseSurfaceProfile` bytes.
    pub daily_use_surface_profile: &'a [u8],
}

/// Owned exact component bytes supplied to the private durable-registration capability.
///
/// This is intentionally not a Serde wire contract. The store persists each member as the exact
/// byte string named and closed by [`Wave5RunRegistrationV1`]; it must not serialize this wrapper
/// and mistake the wrapper encoding for component truth.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnedWave5RunRegistrationDocumentsV1 {
    /// Exact build-manifest bytes.
    pub build: Vec<u8>,
    /// Exact source-tree-manifest bytes.
    pub source_tree: Vec<u8>,
    /// Exact collector/core configuration bytes.
    pub configuration: Vec<u8>,
    /// Exact budget-policy bytes.
    pub budget: Vec<u8>,
    /// Exact privacy-policy bytes.
    pub privacy: Vec<u8>,
    /// Exact `DailyUseSurfaceProfile` bytes.
    pub daily_use_surface_profile: Vec<u8>,
}

impl OwnedWave5RunRegistrationDocumentsV1 {
    /// Borrows the six exact component byte strings without copying.
    #[must_use]
    pub fn as_borrowed(&self) -> Wave5RunRegistrationBytes<'_> {
        Wave5RunRegistrationBytes {
            build: &self.build,
            source_tree: &self.source_tree,
            configuration: &self.configuration,
            budget: &self.budget,
            privacy: &self.privacy,
            daily_use_surface_profile: &self.daily_use_surface_profile,
        }
    }
}

/// Complete owned input to a private durable Wave 5 run-registration writer.
///
/// All seven byte strings are retained: the canonical registration and the six exact component
/// documents it closes. This type neither writes them nor claims durability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnedWave5RunRegistrationBundleV1 {
    /// Exact canonical `joshi.wave5.run_registration` V1 bytes.
    pub registration: Vec<u8>,
    /// Exact component bytes referenced by the registration.
    pub documents: OwnedWave5RunRegistrationDocumentsV1,
}

impl OwnedWave5RunRegistrationBundleV1 {
    /// Strict-parses the registration and verifies all six retained component byte strings.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical registration bytes or any missing, swapped, truncated, or changed
    /// component bytes.
    pub fn validate(&self) -> Result<Wave5RunRegistrationV1, AdmissionError> {
        let registration = parse_wave5_run_registration_v1(&self.registration)?;
        registration.validate_exact_documents(self.documents.as_borrowed())?;
        Ok(registration)
    }
}

/// Immutable pre-I/O registration for one Wave 5 run occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5RunRegistrationV1 {
    /// Exact contract discriminator.
    pub contract: String,
    /// Exact schema version; only V1 is admitted.
    pub schema_version: u64,
    /// Stable identity of this run occurrence.
    pub run_id: String,
    /// Exact build manifest.
    pub build: ExactRegisteredDocumentV1,
    /// Exact source-tree manifest, including dirty/unborn state when applicable.
    pub source_tree: ExactRegisteredDocumentV1,
    /// Exact runtime configuration.
    pub configuration: ExactRegisteredDocumentV1,
    /// Exact request/byte/credit and resource budget.
    pub budget: ExactRegisteredDocumentV1,
    /// Exact privacy and protection policy.
    pub privacy: ExactRegisteredDocumentV1,
    /// Preregistered breadth and critical-surface profile.
    pub daily_use_surface_profile: ExactRegisteredDocumentV1,
    /// Fixed authority ceiling; never execution authority.
    pub authority: String,
}

impl Wave5RunRegistrationV1 {
    /// Validates the closed registration syntax and authority ceiling.
    ///
    /// # Errors
    ///
    /// Refuses an unsupported header, non-ASCII identity, malformed exact-byte closure, or
    /// authority widening.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            WAVE5_RUN_REGISTRATION_CONTRACT,
        )?;
        require_stable_ascii(&self.run_id, "runId")?;
        for document in self.documents() {
            document.validate()?;
        }
        require_authority(&self.authority)
    }

    /// Validates every component's exact bytes and its finite semantic contract.
    ///
    /// # Errors
    ///
    /// Refuses a malformed registration or any swapped, truncated, or changed component.
    pub fn validate_exact_documents(
        &self,
        bytes: Wave5RunRegistrationBytes<'_>,
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        self.build.verify(bytes.build)?;
        self.source_tree.verify(bytes.source_tree)?;
        self.configuration.verify(bytes.configuration)?;
        self.budget.verify(bytes.budget)?;
        self.privacy.verify(bytes.privacy)?;
        self.daily_use_surface_profile
            .verify(bytes.daily_use_surface_profile)?;
        validate_wave5_run_component_documents(self, bytes).map(|_| ())
    }

    /// Encodes the one accepted canonical JSON representation.
    ///
    /// # Errors
    ///
    /// Returns an error if validation or JSON encoding fails.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AdmissionError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(Into::into)
    }

    fn documents(&self) -> [&ExactRegisteredDocumentV1; 6] {
        [
            &self.build,
            &self.source_tree,
            &self.configuration,
            &self.budget,
            &self.privacy,
            &self.daily_use_surface_profile,
        ]
    }
}

/// A reusable, transitive reference to one exact run registration.
///
/// Collector reservations, control writes, and batch policies embed this value. The reference is
/// intentionally verbose enough to prevent a caller from pairing a valid registration digest with
/// component identities copied from another run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5RunReferenceV1 {
    /// Stable run occurrence identity.
    pub run_id: String,
    /// Exact canonical run-registration bytes.
    pub exact_registration: ExactByteClosureV1,
    /// Exact build manifest reference.
    pub build: ExactRegisteredDocumentV1,
    /// Exact source-tree manifest reference.
    pub source_tree: ExactRegisteredDocumentV1,
    /// Exact runtime configuration reference.
    pub configuration: ExactRegisteredDocumentV1,
    /// Exact budget-policy reference.
    pub budget: ExactRegisteredDocumentV1,
    /// Exact privacy-policy reference.
    pub privacy: ExactRegisteredDocumentV1,
    /// Exact daily-use-surface-profile reference.
    pub daily_use_surface_profile: ExactRegisteredDocumentV1,
}

impl Wave5RunReferenceV1 {
    /// Builds the reusable reference only from exact canonical registration bytes.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical bytes, a decoded-value mismatch, or an invalid registration.
    pub fn from_registration(
        registration: &Wave5RunRegistrationV1,
        exact_registration_bytes: &[u8],
    ) -> Result<Self, AdmissionError> {
        require_exact_registration(registration, exact_registration_bytes)?;
        Ok(Self {
            run_id: registration.run_id.clone(),
            exact_registration: ExactByteClosureV1::new(exact_registration_bytes)?,
            build: registration.build.clone(),
            source_tree: registration.source_tree.clone(),
            configuration: registration.configuration.clone(),
            budget: registration.budget.clone(),
            privacy: registration.privacy.clone(),
            daily_use_surface_profile: registration.daily_use_surface_profile.clone(),
        })
    }

    /// Performs standalone syntactic validation of the transitive reference.
    ///
    /// # Errors
    ///
    /// Refuses non-ASCII identities or malformed byte lengths.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_stable_ascii(&self.run_id, "run.runId")?;
        require_positive_wire(
            &self.exact_registration.byte_length,
            "run.exactRegistration.byteLength",
        )?;
        let documents = [
            &self.build,
            &self.source_tree,
            &self.configuration,
            &self.budget,
            &self.privacy,
            &self.daily_use_surface_profile,
        ];
        for document in documents {
            document.validate()?;
        }
        Ok(())
    }

    /// Proves this reference was derived from the supplied exact registration.
    ///
    /// # Errors
    ///
    /// Refuses same-ID/different-bytes retries and any component-reference substitution.
    pub fn validate_against_registration(
        &self,
        registration: &Wave5RunRegistrationV1,
        exact_registration_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        let expected = Self::from_registration(registration, exact_registration_bytes)?;
        if self != &expected {
            return invalid("run reference does not close the exact run registration");
        }
        Ok(())
    }
}

/// Durable store receipt for one exact Wave 5 run registration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5RunRegistrationReceiptV1 {
    /// Exact receipt contract discriminator.
    pub contract: String,
    /// Exact receipt schema version; only V1 is admitted.
    pub schema_version: u64,
    /// Stable catalog identity.
    pub catalog_id: String,
    /// Stable catalog schema identity.
    pub catalog_schema: String,
    /// Stable store batch occurrence identity.
    pub batch_id: String,
    /// Full transitive closure of the registered run.
    pub run: Wave5RunReferenceV1,
    /// Durable catalog commit sequence.
    pub commit_seq: String,
    /// Writer-owned time at which the registration crossed the durable commit boundary.
    pub registered_at: UtcTimestamp,
    /// Fixed authority ceiling.
    pub authority: String,
    /// Whether the exact registration was newly admitted or was an exact idempotent retry.
    pub status: OperationalStatus,
}

impl Wave5RunRegistrationReceiptV1 {
    /// Validates the durable receipt's syntax and authority ceiling.
    ///
    /// # Errors
    ///
    /// Refuses an unsupported header, malformed catalog/commit identity, invalid run reference, or
    /// authority widening.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            WAVE5_RUN_REGISTRATION_RECEIPT_CONTRACT,
        )?;
        require_stable_ascii(&self.catalog_id, "catalogId")?;
        require_stable_ascii(&self.catalog_schema, "catalogSchema")?;
        require_stable_ascii(&self.batch_id, "batchId")?;
        self.run.validate()?;
        require_positive_wire(&self.commit_seq, "commitSeq")?;
        require_authority(&self.authority)
    }

    /// Proves the durable receipt closes the supplied exact canonical registration bytes.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical input, a changed same-ID registration, or any transitive-reference
    /// substitution.
    pub fn validate_against(
        &self,
        registration: &Wave5RunRegistrationV1,
        exact_registration_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        self.run
            .validate_against_registration(registration, exact_registration_bytes)
    }

    /// Validates an idempotent retry candidate for this already registered run identity.
    ///
    /// This helper does not perform or claim a store write. It only proves that the candidate's
    /// exact canonical bytes are the bytes already closed by this receipt.
    ///
    /// # Errors
    ///
    /// Refuses a different run ID or changed bytes under the same run ID.
    pub fn validate_retry_candidate(
        &self,
        candidate: &Wave5RunRegistrationV1,
        exact_candidate_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        if self.run.run_id != candidate.run_id {
            return invalid("run retry candidate has a different run identity");
        }
        self.validate_against(candidate, exact_candidate_bytes)
    }
}

/// Operational object families that may be transitively bound to a registered run.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Wave5RunBindingKind {
    /// A pre-I/O collector attempt reservation.
    CollectorAttempt,
    /// A pre-I/O collector control-write reservation or exact command.
    ControlWrite,
    /// A physical/logical batch admission policy.
    BatchPolicy,
}

/// Inert exact-byte binding from an attempt, control write, or batch policy to a registered run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5RunBindingV1 {
    /// Exact binding contract discriminator.
    pub contract: String,
    /// Exact schema version; only V1 is admitted.
    pub schema_version: u64,
    /// Stable binding occurrence identity.
    pub binding_id: String,
    /// Kind of operational object being bound.
    pub binding_kind: Wave5RunBindingKind,
    /// Exact registered-run reference.
    pub run: Wave5RunReferenceV1,
    /// Stable object identity plus exact canonical object bytes.
    pub subject: ExactRegisteredDocumentV1,
    /// Fixed authority ceiling.
    pub authority: String,
}

impl Wave5RunBindingV1 {
    /// Validates the binding syntax without claiming the subject was persisted or acted upon.
    ///
    /// # Errors
    ///
    /// Refuses an unsupported header, malformed identity/reference, or authority widening.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            WAVE5_RUN_BINDING_CONTRACT,
        )?;
        require_stable_ascii(&self.binding_id, "bindingId")?;
        self.run.validate()?;
        self.subject.validate()?;
        require_authority(&self.authority)
    }

    /// Proves the run and bound object's exact canonical bytes.
    ///
    /// The caller remains responsible for parsing the subject as the DTO named by
    /// `binding_kind`; this generic layer only makes byte substitution impossible.
    ///
    /// # Errors
    ///
    /// Refuses a changed registration, changed subject bytes, or malformed binding.
    pub fn validate_against(
        &self,
        registration: &Wave5RunRegistrationV1,
        exact_registration_bytes: &[u8],
        exact_subject_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        self.run
            .validate_against_registration(registration, exact_registration_bytes)?;
        self.subject.verify(exact_subject_bytes)
    }

    /// Encodes the one accepted canonical JSON representation.
    ///
    /// # Errors
    ///
    /// Returns an error if validation or JSON encoding fails.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AdmissionError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(Into::into)
    }
}

/// Strictly parses exact canonical Wave 5 run-registration bytes.
///
/// # Errors
///
/// Refuses oversized, duplicate-key, dangerous-key, unknown-field, noncanonical, or semantically
/// invalid input.
pub fn parse_wave5_run_registration_v1(
    bytes: &[u8],
) -> Result<Wave5RunRegistrationV1, AdmissionError> {
    let registration: Wave5RunRegistrationV1 = parse_canonical(bytes)?;
    registration.validate()?;
    Ok(registration)
}

/// Strictly parses exact canonical Wave 5 run-registration receipt bytes.
///
/// # Errors
///
/// Refuses oversized, duplicate-key, dangerous-key, unknown-field, noncanonical, or semantically
/// invalid input.
pub fn parse_wave5_run_registration_receipt_v1(
    bytes: &[u8],
) -> Result<Wave5RunRegistrationReceiptV1, AdmissionError> {
    let receipt: Wave5RunRegistrationReceiptV1 = parse_canonical(bytes)?;
    receipt.validate()?;
    Ok(receipt)
}

/// Strictly parses exact canonical Wave 5 run-binding bytes.
///
/// # Errors
///
/// Refuses oversized, duplicate-key, dangerous-key, unknown-field, noncanonical, or semantically
/// invalid input.
pub fn parse_wave5_run_binding_v1(bytes: &[u8]) -> Result<Wave5RunBindingV1, AdmissionError> {
    let binding: Wave5RunBindingV1 = parse_canonical(bytes)?;
    binding.validate()?;
    Ok(binding)
}

fn require_exact_registration(
    registration: &Wave5RunRegistrationV1,
    exact_registration_bytes: &[u8],
) -> Result<(), AdmissionError> {
    let decoded = parse_wave5_run_registration_v1(exact_registration_bytes)?;
    if &decoded != registration {
        return invalid("run registration value differs from exact canonical bytes");
    }
    Ok(())
}

fn parse_canonical<T>(bytes: &[u8]) -> Result<T, AdmissionError>
where
    T: for<'de> Deserialize<'de> + Serialize,
{
    let value: T = strict_json::parse(bytes, MAX_WAVE5_RUN_DOCUMENT_BYTES)?;
    if serde_json::to_vec(&value)? != bytes {
        return invalid("Wave 5 run document bytes are not canonical");
    }
    Ok(value)
}

fn require_header(contract: &str, version: u64, expected: &str) -> Result<(), AdmissionError> {
    if contract == expected && version == 1 {
        Ok(())
    } else {
        invalid(format!(
            "unsupported Wave 5 run header {contract}/v{version}"
        ))
    }
}

fn require_stable_ascii(value: &str, field: &str) -> Result<(), AdmissionError> {
    if !value.is_empty() && value.len() <= 255 && value.bytes().all(|byte| byte.is_ascii_graphic())
    {
        Ok(())
    } else {
        invalid(format!(
            "{field} must be 1-255 printable, whitespace-free ASCII bytes"
        ))
    }
}

fn require_positive_wire(value: &str, field: &str) -> Result<u64, AdmissionError> {
    if value.is_empty()
        || value.starts_with('0')
        || value.bytes().any(|byte| !byte.is_ascii_digit())
    {
        return invalid(format!("{field} is not a positive canonical u64 string"));
    }
    value.parse().map_err(|_| {
        AdmissionError::Contract(format!("{field} is not a positive canonical u64 string"))
    })
}

fn require_authority(value: &str) -> Result<(), AdmissionError> {
    if value == AUTHORITY {
        Ok(())
    } else {
        invalid("Wave 5 run authority must be read_only_no_execution")
    }
}

fn invalid<T>(message: impl Into<String>) -> Result<T, AdmissionError> {
    Err(AdmissionError::Contract(message.into()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;

    const BUILD: &[u8] = br#"{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"local-debug","sourceTreeDigest":"sha256:75ca191ce724554d183a05b6f7e381686291b29376e42cf4494e8be840f21012","rustcVersion":"rustc-1.97","targetTriple":"aarch64-apple-darwin","profile":"local_debug","authority":"read_only_no_execution"}"#;
    const SOURCE_TREE: &[u8] = br#"{"contract":"joshi.wave5.source_tree_manifest","schemaVersion":1,"repositoryId":"joshi","head":{"kind":"unborn"},"dirty":true,"workingTreeDigest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","diffDigest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","authority":"read_only_no_execution"}"#;
    const CONFIGURATION: &[u8] = br#"{"contract":"joshi.collector.runtime_config.v1","schemaVersion":1,"planId":"c0-fixture","planTemplateDigest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","statusEndpoint":{"address":"127.0.0.1","port":19441},"providerExecution":"offline_fixture_only","authority":"read_only_no_execution"}"#;
    const BUDGET: &[u8] = br#"{"contract":"joshi.collector.execution_accounting.v1","schemaVersion":1,"limits":{"maximumRequests":10,"maximumPages":10,"maximumIngressBytes":1048576,"maximumDurableBytes":1048576,"maximumProviderCredits":0,"maximumIngressBytesPerSecond":null,"maximumElapsedMs":60000,"maximumInFlightAttempts":1,"maximumInFlightElapsedOvershootMs":1000},"authority":"read_only_no_execution"}"#;
    const PRIVACY: &[u8] = br#"{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"local-public-only","permittedProtectionClasses":["public_integrity"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":false,"authority":"read_only_no_execution"}"#;
    const SURFACE_FILE: &[u8] =
        include_bytes!("../../../fixtures/surface/daily_use_surface_profile_v1.json");

    fn surface() -> &'static [u8] {
        SURFACE_FILE.strip_suffix(b"\n").unwrap_or(SURFACE_FILE)
    }

    fn document(id: &str, bytes: &[u8]) -> ExactRegisteredDocumentV1 {
        ExactRegisteredDocumentV1 {
            document_id: id.into(),
            exact_bytes: ExactByteClosureV1::new(bytes).expect("closure"),
        }
    }

    fn registration() -> Wave5RunRegistrationV1 {
        Wave5RunRegistrationV1 {
            contract: WAVE5_RUN_REGISTRATION_CONTRACT.into(),
            schema_version: 1,
            run_id: "wave5-local-canary-0001".into(),
            build: document("build-local-debug", BUILD),
            source_tree: document("tree-unborn-dirty-0001", SOURCE_TREE),
            configuration: document("config-local-canary-0001", CONFIGURATION),
            budget: document("budget-local-canary-0001", BUDGET),
            privacy: document("privacy-public-integrity-0001", PRIVACY),
            daily_use_surface_profile: document("surface-daily-use-0001", surface()),
            authority: AUTHORITY.into(),
        }
    }

    fn component_bytes() -> Wave5RunRegistrationBytes<'static> {
        Wave5RunRegistrationBytes {
            build: BUILD,
            source_tree: SOURCE_TREE,
            configuration: CONFIGURATION,
            budget: BUDGET,
            privacy: PRIVACY,
            daily_use_surface_profile: surface(),
        }
    }

    fn owned_documents() -> OwnedWave5RunRegistrationDocumentsV1 {
        OwnedWave5RunRegistrationDocumentsV1 {
            build: BUILD.to_vec(),
            source_tree: SOURCE_TREE.to_vec(),
            configuration: CONFIGURATION.to_vec(),
            budget: BUDGET.to_vec(),
            privacy: PRIVACY.to_vec(),
            daily_use_surface_profile: surface().to_vec(),
        }
    }

    fn receipt(
        registration: &Wave5RunRegistrationV1,
        registration_bytes: &[u8],
    ) -> Wave5RunRegistrationReceiptV1 {
        Wave5RunRegistrationReceiptV1 {
            contract: WAVE5_RUN_REGISTRATION_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            catalog_id: "catalog-local".into(),
            catalog_schema: "joshi.sqlite.v9".into(),
            batch_id: "batch-run-registration-0001".into(),
            run: Wave5RunReferenceV1::from_registration(registration, registration_bytes)
                .expect("run reference"),
            commit_seq: "1".into(),
            registered_at: UtcTimestamp::from_str("2026-08-18T04:00:00.000000Z")
                .expect("timestamp"),
            authority: AUTHORITY.into(),
            status: OperationalStatus::Accepted,
        }
    }

    #[test]
    fn registration_closes_canonical_bytes_and_every_exact_component() {
        let registration = registration();
        registration
            .validate_exact_documents(component_bytes())
            .expect("documents close");
        let bytes = registration.canonical_bytes().expect("canonical bytes");
        assert_eq!(
            parse_wave5_run_registration_v1(&bytes).expect("parse"),
            registration
        );

        let mut changed_build = component_bytes();
        changed_build.build = br#"{"build":"release"}"#;
        assert!(
            registration
                .validate_exact_documents(changed_build)
                .is_err()
        );
    }

    #[test]
    fn owned_store_input_retains_and_verifies_all_seven_exact_byte_strings() {
        let registration = registration();
        let bytes = registration.canonical_bytes().expect("canonical bytes");
        let mut bundle = OwnedWave5RunRegistrationBundleV1 {
            registration: bytes,
            documents: owned_documents(),
        };
        assert_eq!(
            bundle.validate().expect("complete exact bundle"),
            registration
        );

        bundle.documents.privacy.push(b' ');
        assert!(bundle.validate().is_err());
    }

    #[test]
    fn strict_parser_refuses_noncanonical_unknown_duplicate_and_unicode_identity() {
        let registration = registration();
        let bytes = registration.canonical_bytes().expect("canonical bytes");

        let mut padded = bytes.clone();
        padded.push(b'\n');
        assert!(parse_wave5_run_registration_v1(&padded).is_err());

        let unknown =
            String::from_utf8(bytes.clone())
                .expect("utf8")
                .replacen('{', "{\"surprise\":true,", 1);
        assert!(parse_wave5_run_registration_v1(unknown.as_bytes()).is_err());

        let duplicate =
            String::from_utf8(bytes)
                .expect("utf8")
                .replacen('{', "{\"runId\":\"shadow\",", 1);
        assert!(parse_wave5_run_registration_v1(duplicate.as_bytes()).is_err());

        let mut unicode = registration;
        unicode.run_id = "wave5-é".into();
        assert!(unicode.validate().is_err());
    }

    #[test]
    fn receipt_refuses_same_run_id_with_changed_exact_registration() {
        let registration = registration();
        let bytes = registration.canonical_bytes().expect("canonical bytes");
        let receipt = receipt(&registration, &bytes);
        receipt
            .validate_retry_candidate(&registration, &bytes)
            .expect("exact retry");

        let mut changed = registration.clone();
        changed.configuration = document("config-local-canary-0002", PRIVACY);
        let changed_bytes = changed.canonical_bytes().expect("changed canonical bytes");
        assert_eq!(changed.run_id, registration.run_id);
        assert!(
            receipt
                .validate_retry_candidate(&changed, &changed_bytes)
                .is_err()
        );

        let receipt_bytes = serde_json::to_vec(&receipt).expect("receipt bytes");
        assert_eq!(
            parse_wave5_run_registration_receipt_v1(&receipt_bytes).expect("receipt parse"),
            receipt
        );
    }

    #[test]
    fn binding_closes_run_and_subject_without_making_source_claims() {
        let registration = registration();
        let registration_bytes = registration.canonical_bytes().expect("registration bytes");
        let attempt = br#"{"contract":"joshi.supervisor.v1","reservationId":"attempt-1"}"#;
        let binding = Wave5RunBindingV1 {
            contract: WAVE5_RUN_BINDING_CONTRACT.into(),
            schema_version: 1,
            binding_id: "binding-attempt-0001".into(),
            binding_kind: Wave5RunBindingKind::CollectorAttempt,
            run: Wave5RunReferenceV1::from_registration(&registration, &registration_bytes)
                .expect("run reference"),
            subject: document("attempt-1", attempt),
            authority: AUTHORITY.into(),
        };

        binding
            .validate_against(&registration, &registration_bytes, attempt)
            .expect("binding closes");
        assert!(
            binding
                .validate_against(
                    &registration,
                    &registration_bytes,
                    br#"{"contract":"joshi.supervisor.v1","reservationId":"attempt-2"}"#,
                )
                .is_err()
        );

        let bytes = binding.canonical_bytes().expect("binding bytes");
        assert_eq!(
            parse_wave5_run_binding_v1(&bytes).expect("binding parse"),
            binding
        );
    }

    #[test]
    fn authority_widening_and_zero_lengths_refuse() {
        let mut candidate = registration();
        candidate.authority = "execute_trades".into();
        assert!(candidate.validate().is_err());

        candidate = registration();
        candidate.build.exact_bytes.byte_length = "0".into();
        assert!(candidate.validate().is_err());
    }

    #[test]
    fn digest_closed_but_semantically_invalid_components_refuse_registration() {
        let arbitrary = b"build";
        let mut arbitrary_registration = registration();
        arbitrary_registration.build = document("build-arbitrary", arbitrary);
        let arbitrary_bytes = arbitrary_registration
            .canonical_bytes()
            .expect("syntactic registration");
        let mut arbitrary_documents = owned_documents();
        arbitrary_documents.build = arbitrary.to_vec();
        assert!(
            OwnedWave5RunRegistrationBundleV1 {
                registration: arbitrary_bytes,
                documents: arbitrary_documents,
            }
            .validate()
            .is_err()
        );

        let wrong_tree = br#"{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"local-debug","sourceTreeDigest":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","rustcVersion":"rustc-1.97","targetTriple":"aarch64-apple-darwin","profile":"local_debug","authority":"read_only_no_execution"}"#;
        let mut cross_registration = registration();
        cross_registration.build = document("build-wrong-tree", wrong_tree);
        let cross_bytes = cross_registration
            .canonical_bytes()
            .expect("syntactic registration");
        let mut cross_documents = owned_documents();
        cross_documents.build = wrong_tree.to_vec();
        assert!(
            OwnedWave5RunRegistrationBundleV1 {
                registration: cross_bytes,
                documents: cross_documents,
            }
            .validate()
            .is_err()
        );

        let widened_privacy = br#"{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"widened","permittedProtectionClasses":["public_integrity"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":true,"authority":"read_only_no_execution"}"#;
        let mut privacy_registration = registration();
        privacy_registration.privacy = document("privacy-widened", widened_privacy);
        let privacy_bytes = privacy_registration
            .canonical_bytes()
            .expect("syntactic registration");
        let mut privacy_documents = owned_documents();
        privacy_documents.privacy = widened_privacy.to_vec();
        assert!(
            OwnedWave5RunRegistrationBundleV1 {
                registration: privacy_bytes,
                documents: privacy_documents,
            }
            .validate()
            .is_err()
        );
    }
}
