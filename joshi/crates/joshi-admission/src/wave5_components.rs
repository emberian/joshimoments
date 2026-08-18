//! Finite semantic contracts for the exact documents closed by a Wave 5 run registration.
//!
//! Digest closure alone is not registration: these parsers reject arbitrary JSON, unknown fields,
//! unsupported execution modes, unbounded budgets, incoherent source-tree state, and privacy
//! widening before a durable writer can treat a run as registered.

use std::{collections::BTreeSet, net::IpAddr};

use joshi_surface::DailyUseSurfaceProfileV1;
use serde::{Deserialize, Serialize};

use crate::{
    AdmissionError,
    operational::AUTHORITY,
    strict_json,
    wave5::{MAX_WAVE5_RUN_DOCUMENT_BYTES, Wave5RunRegistrationBytes, Wave5RunRegistrationV1},
};

/// Exact build-manifest contract.
pub const BUILD_MANIFEST_CONTRACT: &str = "joshi.wave5.build_manifest";
/// Exact source-tree-manifest contract.
pub const SOURCE_TREE_MANIFEST_CONTRACT: &str = "joshi.wave5.source_tree_manifest";
/// Exact collector runtime-configuration contract shared with the C0 supervisor.
pub const COLLECTOR_RUNTIME_CONFIG_CONTRACT: &str = "joshi.collector.runtime_config.v1";
/// Exact execution-accounting contract shared with the C0 supervisor.
pub const EXECUTION_ACCOUNTING_CONTRACT: &str = "joshi.collector.execution_accounting.v1";
/// Exact privacy-policy contract.
pub const PRIVACY_POLICY_CONTRACT: &str = "joshi.wave5.privacy_policy";

/// Compiler profile used for one exact build occurrence.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BuildProfile {
    /// A local debug build; never an immutable remote release claim.
    LocalDebug,
    /// A local release build; remote qualification remains a separate gate.
    LocalRelease,
}

/// Canonical build occurrence tied to the exact source-tree document used to produce it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildManifestV1 {
    pub contract: String,
    pub schema_version: u64,
    pub build_id: String,
    pub source_tree_digest: String,
    pub rustc_version: String,
    pub target_triple: String,
    pub profile: BuildProfile,
    pub authority: String,
}

impl BuildManifestV1 {
    /// Validates the finite build contract and its exact source-tree closure.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] when the header, identities, authority, or source-tree digest is
    /// invalid.
    pub fn validate(&self, exact_source_tree_digest: &str) -> Result<(), AdmissionError> {
        require_header(&self.contract, self.schema_version, BUILD_MANIFEST_CONTRACT)?;
        require_stable(&self.build_id, "buildId")?;
        require_stable(&self.rustc_version, "rustcVersion")?;
        require_stable(&self.target_triple, "targetTriple")?;
        require_digest(&self.source_tree_digest, "sourceTreeDigest")?;
        if self.source_tree_digest != exact_source_tree_digest {
            return invalid("build manifest does not close the exact source-tree document");
        }
        require_authority(&self.authority)
    }
}

/// Git head state recorded without pretending an unborn repository has a commit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SourceTreeHeadV1 {
    /// Repository has no commit yet.
    Unborn,
    /// Repository has an exact hexadecimal commit object identity.
    Commit { object_id: String },
}

/// Exact source-tree state for a local canary or qualified immutable build.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceTreeManifestV1 {
    pub contract: String,
    pub schema_version: u64,
    pub repository_id: String,
    pub head: SourceTreeHeadV1,
    pub dirty: bool,
    pub working_tree_digest: String,
    pub diff_digest: Option<String>,
    pub authority: String,
}

impl SourceTreeManifestV1 {
    /// Validates the finite source-tree state.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] for malformed identities or digests, incoherent dirty state, or
    /// widened authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            SOURCE_TREE_MANIFEST_CONTRACT,
        )?;
        require_stable(&self.repository_id, "repositoryId")?;
        require_digest(&self.working_tree_digest, "workingTreeDigest")?;
        match &self.head {
            SourceTreeHeadV1::Unborn => {}
            SourceTreeHeadV1::Commit { object_id } => {
                if !matches!(object_id.len(), 40 | 64)
                    || !object_id.bytes().all(|byte| byte.is_ascii_hexdigit())
                {
                    return invalid(
                        "source-tree head objectId must be 40 or 64 lowercase hex bytes",
                    );
                }
                if object_id.bytes().any(|byte| byte.is_ascii_uppercase()) {
                    return invalid("source-tree head objectId must use lowercase hex");
                }
            }
        }
        match (&self.dirty, &self.diff_digest) {
            (true, Some(value)) => require_digest(value, "diffDigest")?,
            (false, None) => {}
            _ => return invalid("dirty source-tree state requires exactly one diffDigest"),
        }
        require_authority(&self.authority)
    }
}

/// Loopback-only diagnostic endpoint. This declaration does not open a listener.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LocalStatusEndpointV1 {
    pub address: IpAddr,
    pub port: u16,
}

/// Only the sealed no-network runtime is admitted by the Phase-0 registration parser.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderExecutionModeV1 {
    OfflineFixtureOnly,
}

/// Exact collector configuration closed by the run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CollectorRuntimeConfigV1 {
    pub contract: String,
    pub schema_version: u64,
    pub plan_id: String,
    /// Domain-separated provider-plan body digest excluding run/registration bindings.
    pub plan_template_digest: String,
    pub status_endpoint: LocalStatusEndpointV1,
    pub provider_execution: ProviderExecutionModeV1,
    pub authority: String,
}

impl CollectorRuntimeConfigV1 {
    /// Validates the sealed Phase-0 collector configuration.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] for an unsupported contract, invalid plan identity, non-loopback
    /// status endpoint, or widened authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            COLLECTOR_RUNTIME_CONFIG_CONTRACT,
        )?;
        require_stable(&self.plan_id, "planId")?;
        require_digest(&self.plan_template_digest, "planTemplateDigest")?;
        if !self.status_endpoint.address.is_loopback() || self.status_endpoint.port == 0 {
            return invalid("collector status endpoint must be a nonzero loopback endpoint");
        }
        require_authority(&self.authority)
    }

    /// Returns the canonical JSON bytes after validation.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] when validation or serialization fails.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AdmissionError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(Into::into)
    }
}

/// Finite, positive hard ceilings for one collector run.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RunBudgetLimitsV1 {
    pub maximum_requests: u64,
    pub maximum_pages: u64,
    pub maximum_ingress_bytes: u64,
    pub maximum_durable_bytes: u64,
    pub maximum_provider_credits: u64,
    pub maximum_ingress_bytes_per_second: Option<u64>,
    pub maximum_elapsed_ms: u64,
    pub maximum_in_flight_attempts: u64,
    pub maximum_in_flight_elapsed_overshoot_ms: u64,
}

impl RunBudgetLimitsV1 {
    /// Validates the finite, positive budget ceilings.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] when a required ceiling is zero or internally inconsistent.
    pub fn validate(self) -> Result<(), AdmissionError> {
        if self.maximum_requests == 0
            || self.maximum_ingress_bytes == 0
            || self.maximum_durable_bytes == 0
            || self.maximum_elapsed_ms == 0
            || self.maximum_in_flight_attempts == 0
            || self.maximum_in_flight_attempts > self.maximum_requests
            || self.maximum_in_flight_elapsed_overshoot_ms == 0
            || self.maximum_in_flight_elapsed_overshoot_ms > self.maximum_elapsed_ms
            || self.maximum_ingress_bytes_per_second == Some(0)
        {
            return invalid("run budgets must be finite, positive, and bound in-flight time");
        }
        Ok(())
    }
}

/// Exact budget policy closed by the run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExecutionAccountingDocumentV1 {
    pub contract: String,
    pub schema_version: u64,
    pub limits: RunBudgetLimitsV1,
    pub authority: String,
}

impl ExecutionAccountingDocumentV1 {
    /// Validates the execution-accounting document and its limits.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] for an invalid header, authority, or budget limit.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            EXECUTION_ACCOUNTING_CONTRACT,
        )?;
        self.limits.validate()?;
        require_authority(&self.authority)
    }

    /// Returns the canonical JSON bytes after validation.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] when validation or serialization fails.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, AdmissionError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(Into::into)
    }
}

/// Protection classes that one exact run may persist.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PermittedProtectionClassV1 {
    PublicIntegrity,
    AuthenticatedPrivate,
}

/// Credential rule for this read-only run.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CredentialHandlingV1 {
    PurposeScopedHandlesOnly,
}

/// Wallet-material rule for this run.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WalletMaterialRuleV1 {
    Forbidden,
}

/// Exact protection and privacy ceiling closed before any provider I/O.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PrivacyPolicyV1 {
    pub contract: String,
    pub schema_version: u64,
    pub policy_id: String,
    pub permitted_protection_classes: Vec<PermittedProtectionClassV1>,
    pub credential_handling: CredentialHandlingV1,
    pub wallet_material: WalletMaterialRuleV1,
    pub export_private_material: bool,
    pub authority: String,
}

impl PrivacyPolicyV1 {
    /// Validates the read-only protection and privacy ceiling.
    ///
    /// # Errors
    ///
    /// Returns [`AdmissionError`] for invalid identities, protection ordering, private export, or
    /// widened authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(&self.contract, self.schema_version, PRIVACY_POLICY_CONTRACT)?;
        require_stable(&self.policy_id, "policyId")?;
        if self.permitted_protection_classes.is_empty()
            || self
                .permitted_protection_classes
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
            || self
                .permitted_protection_classes
                .iter()
                .copied()
                .collect::<BTreeSet<_>>()
                .len()
                != self.permitted_protection_classes.len()
            || self.export_private_material
        {
            return invalid(
                "privacy policy must use a sorted unique protection set and forbid private export",
            );
        }
        require_authority(&self.authority)
    }
}

/// Parsed proof that every exact child document has a supported semantic contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticallyValidatedRunDocumentsV1 {
    pub build: BuildManifestV1,
    pub source_tree: SourceTreeManifestV1,
    pub configuration: CollectorRuntimeConfigV1,
    pub budget: ExecutionAccountingDocumentV1,
    pub privacy: PrivacyPolicyV1,
    pub daily_use_surface_profile: DailyUseSurfaceProfileV1,
}

/// Strict-parses and semantically validates all six exact documents closed by a run.
///
/// # Errors
///
/// Returns [`AdmissionError`] if any exact document is noncanonical, unsupported, semantically
/// invalid, or inconsistent with the registration's digest closure.
pub fn validate_wave5_run_component_documents(
    registration: &Wave5RunRegistrationV1,
    bytes: Wave5RunRegistrationBytes<'_>,
) -> Result<SemanticallyValidatedRunDocumentsV1, AdmissionError> {
    let build: BuildManifestV1 = parse(bytes.build, "build manifest")?;
    let source_tree: SourceTreeManifestV1 = parse(bytes.source_tree, "source-tree manifest")?;
    let configuration: CollectorRuntimeConfigV1 =
        parse(bytes.configuration, "collector runtime configuration")?;
    let budget: ExecutionAccountingDocumentV1 = parse(bytes.budget, "execution budget")?;
    let privacy: PrivacyPolicyV1 = parse(bytes.privacy, "privacy policy")?;
    let daily_use_surface_profile: DailyUseSurfaceProfileV1 =
        parse(bytes.daily_use_surface_profile, "daily-use surface profile")?;

    build.validate(registration.source_tree.exact_bytes.digest.as_str())?;
    source_tree.validate()?;
    configuration.validate()?;
    budget.validate()?;
    privacy.validate()?;
    daily_use_surface_profile
        .validate()
        .map_err(|error| AdmissionError::Contract(format!("daily-use surface profile: {error}")))?;
    if daily_use_surface_profile
        .canonical_bytes()
        .map_err(|error| AdmissionError::Contract(format!("daily-use surface profile: {error}")))?
        != bytes.daily_use_surface_profile
    {
        return invalid("daily-use surface profile bytes are not canonical");
    }
    Ok(SemanticallyValidatedRunDocumentsV1 {
        build,
        source_tree,
        configuration,
        budget,
        privacy,
        daily_use_surface_profile,
    })
}

fn parse<T>(bytes: &[u8], label: &str) -> Result<T, AdmissionError>
where
    T: for<'de> Deserialize<'de> + Serialize,
{
    let value: T = strict_json::parse(bytes, MAX_WAVE5_RUN_DOCUMENT_BYTES)?;
    if serde_json::to_vec(&value)? != bytes {
        return invalid(format!("{label} bytes are not canonical"));
    }
    Ok(value)
}

fn require_header(contract: &str, version: u64, expected: &str) -> Result<(), AdmissionError> {
    if contract == expected && version == 1 {
        Ok(())
    } else {
        invalid(format!(
            "unsupported component header {contract}/v{version}"
        ))
    }
}

fn require_stable(value: &str, field: &str) -> Result<(), AdmissionError> {
    if !value.is_empty()
        && value.len() <= 255
        && value.trim() == value
        && !value.chars().any(char::is_control)
    {
        Ok(())
    } else {
        invalid(format!("{field} is not a stable bounded string"))
    }
}

fn require_digest(value: &str, field: &str) -> Result<(), AdmissionError> {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return invalid(format!("{field} is not a SHA-256 digest"));
    };
    if hex.len() != 64
        || !hex.bytes().all(|byte| byte.is_ascii_hexdigit())
        || hex.bytes().any(|byte| byte.is_ascii_uppercase())
    {
        return invalid(format!("{field} is not a lowercase SHA-256 digest"));
    }
    Ok(())
}

fn require_authority(value: &str) -> Result<(), AdmissionError> {
    if value == AUTHORITY {
        Ok(())
    } else {
        invalid("component authority must be read_only_no_execution")
    }
}

fn invalid<T>(message: impl Into<String>) -> Result<T, AdmissionError> {
    Err(AdmissionError::Contract(message.into()))
}
