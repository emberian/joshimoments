use std::collections::BTreeSet;

use joshi_domain::{SourceId, StableString, ValueDigest};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{REGISTRY_CONTRACT, REGISTRY_SCHEMA_VERSION, error::RegistryError};

/// Canonical non-secret source identity for the bounded public Solana mainnet reader.
pub const PUBLIC_SOLANA_MAINNET_SOURCE_ID: &str = "solana.public.mainnet";
/// Canonical method key for one finalized, newest-first signature page.
pub const PUBLIC_SOLANA_SIGNATURES_METHOD_KEY: &str = "get_signatures_for_address";
const PUBLIC_SOLANA_SIGNATURES_SCHEMA: &[u8] =
    include_bytes!("../../../fixtures/source-registry/solana_get_signatures_for_address.v1.json");

fn stable(value: &str) -> Result<StableString, RegistryError> {
    StableString::new(value).map_err(|_| RegistryError::InvalidValue("unstable string"))
}

/// Whether a source needs a credential and what that credential is allowed to do.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AccessClass {
    UnauthenticatedPublic,
    AuthenticatedReadOnly,
    AuthenticatedPrivate,
    CompanionSession,
}

/// Authority carried by a credential. Wallet-bearing authority is intentionally distinct from
/// read-only access, even where a provider prices an endpoint at zero.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CredentialAuthority {
    None,
    ReadOnlyApi,
    WalletBearingSigning,
    TransactionExecution,
}

/// Non-secret credential metadata. The secret itself can never be represented by this crate.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CredentialDescriptor {
    pub key_id: StableString,
    pub authority: CredentialAuthority,
    pub owner_only: bool,
    pub purpose: StableString,
}

/// A provider's assertion authority for one field, independent of access and billing.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldAuthority {
    Primary,
    Secondary,
    ProviderAssertion,
    CompanionAttestation,
    ChainEvidence,
}

/// Named semantic field families used by source contracts.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldKind {
    ProductMembership,
    ProductOrder,
    Callouts,
    Follows,
    Community,
    Launch,
    Trade,
    Lifecycle,
    Wallet,
    Pool,
    Social,
    Media,
    Coverage,
}

/// Field-specific source authority and absence rule.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FieldContract {
    pub field: FieldKind,
    pub authority: FieldAuthority,
    pub method_keys: Vec<StableString>,
    pub absence: AbsenceSemantics,
}

/// HTTP, websocket, subscription, or local fixture method identity.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MethodKind {
    HttpGet,
    HttpPostReadOnly,
    WebsocketSubscription,
    Fixture,
}

/// Provider commitment level retained on every method contract.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Commitment {
    None,
    Processed,
    Confirmed,
    Finalized,
}

/// Canonicality/finality handling. Corrections append new observations; they never rewrite old
/// bytes or turn a provisional result into a finalized result in place.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FinalityPolicy {
    NotApplicable,
    ProvisionalThenCorrect,
    RequireFinalized,
}

/// Schema identity for method responses. A fingerprint is a digest of the documented schema,
/// not a digest of one response body.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SchemaFingerprint {
    pub algorithm: StableString,
    pub digest: ValueDigest,
}

/// Unit in which a provider may meter a method. Zero price is still a priced/credentialed method
/// unless a separate public-surface attestation is supplied.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BillingUnit {
    None,
    Request,
    Page,
    ResponseByte,
    ProviderCredit,
    Event,
    TokenTradeEvent,
    ChainNativeAtom,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ZeroPriceAttestation {
    NotProvided,
    DocumentedPublicSurface,
    OperatorConformanceOnly,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BillingPolicy {
    pub unit: BillingUnit,
    pub minor_units_per_unit: u64,
    pub currency: Option<StableString>,
    pub asset_id: Option<StableString>,
    pub zero_price_attestation: ZeroPriceAttestation,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QuotaReset {
    Unknown,
    RollingWindow,
    UtcDay,
    ProviderReported,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuotaSpec {
    pub unit: BillingUnit,
    pub hard_limit: Option<u64>,
    pub reset: QuotaReset,
    pub window_seconds: Option<u64>,
    pub remaining_observable: bool,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MethodContract {
    pub key: StableString,
    pub kind: MethodKind,
    pub schema_fingerprint: SchemaFingerprint,
    pub billing: BillingPolicy,
    pub quota: QuotaSpec,
    pub commitment: Commitment,
    pub finality: FinalityPolicy,
    pub absence: AbsenceSemantics,
    pub max_request_bytes: u64,
    pub max_response_bytes: u64,
}

/// Whether a response or missing response can close a requested coverage interval.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AbsenceSemantics {
    NeverProvesAbsence,
    EmptyOnlyWhenComplete,
    NullObservedNotAbsent,
    IntervalCensored,
    LiveOnlyGap,
    AuthFailureUnknown,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProgressSemantics {
    ReplayCursor,
    SlotAnchorRequiresRecovery,
    IntervalPoll,
    LiveOnlyNoReplay,
    FixtureSequence,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapSemantics {
    RecoverableWithBoundedRead,
    PartialUntilReconciled,
    UnrecoverableLiveOnly,
    IntervalCensored,
    UnknownOnAuthFailure,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RetryPolicy {
    pub max_attempts: u16,
    pub max_delay_ms: u64,
    pub retryable_statuses: Vec<u16>,
    pub gap: GapSemantics,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtectionClass {
    Public,
    AppPrivate,
    AuthenticatedPrivate,
    SecretExcluded,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetentionClass {
    Public,
    AppPrivate,
    AuthenticatedPrivate,
    LocalOnly,
    NeverRetain,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct KillSwitch {
    pub enabled: bool,
    pub reason: StableString,
    pub requires_operator_reenable: bool,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceStatus {
    Enabled,
    Disabled,
    Unavailable,
}

/// Complete field-specific source declaration. It contains fingerprints and policy, never secret
/// material or endpoint URLs.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceContract {
    pub source_id: SourceId,
    pub provider: StableString,
    pub contract_version: StableString,
    pub status: SourceStatus,
    pub access: AccessClass,
    pub credential: CredentialAuthority,
    pub credential_descriptor: Option<CredentialDescriptor>,
    pub methods: Vec<MethodContract>,
    pub fields: Vec<FieldContract>,
    pub progress: ProgressSemantics,
    pub retry: RetryPolicy,
    pub protection: ProtectionClass,
    pub retention: RetentionClass,
    pub kill_switch: KillSwitch,
    pub schema_fingerprint: Option<ValueDigest>,
}

impl SourceContract {
    /// Validates source policy and returns the canonical non-secret schema fingerprint.
    ///
    /// # Errors
    ///
    /// Refuses malformed identities, duplicate references, unsafe credentials, semantic joins, or
    /// a mismatched fingerprint.
    #[allow(clippy::too_many_lines)] // One ordered validator keeps the authority decision auditable.
    pub fn validate(&self) -> Result<ValueDigest, RegistryError> {
        if self.contract_version.as_str().is_empty() || self.provider.as_str().is_empty() {
            return Err(RegistryError::InvalidContract("source identity"));
        }
        if self.credential == CredentialAuthority::WalletBearingSigning
            || self.credential == CredentialAuthority::TransactionExecution
        {
            return Err(RegistryError::WalletBearingCredential);
        }
        if self.access == AccessClass::UnauthenticatedPublic
            && self.credential != CredentialAuthority::None
        {
            return Err(RegistryError::InvalidContract(
                "public access has credential authority",
            ));
        }
        if self.access != AccessClass::UnauthenticatedPublic
            && self.credential == CredentialAuthority::None
        {
            return Err(RegistryError::InvalidContract(
                "credentialed access lacks credential authority",
            ));
        }
        if let Some(credential) = &self.credential_descriptor {
            if credential.authority != self.credential {
                return Err(RegistryError::InvalidContract(
                    "credential descriptor authority",
                ));
            }
            if !credential.owner_only {
                return Err(RegistryError::InvalidContract(
                    "credential is not owner-only",
                ));
            }
        } else if self.credential != CredentialAuthority::None {
            return Err(RegistryError::InvalidContract(
                "credential descriptor missing",
            ));
        }
        if self.protection == ProtectionClass::SecretExcluded {
            return Err(RegistryError::InvalidContract(
                "secret protection cannot be a source",
            ));
        }
        if self.retention == RetentionClass::NeverRetain {
            return Err(RegistryError::InvalidContract(
                "never-retain source cannot enter collector",
            ));
        }
        if self.access != AccessClass::UnauthenticatedPublic
            && (self.protection == ProtectionClass::Public
                || self.retention == RetentionClass::Public)
        {
            return Err(RegistryError::InvalidContract(
                "authenticated source requires private protection and retention",
            ));
        }
        if self.methods.is_empty() || self.fields.is_empty() {
            return Err(RegistryError::InvalidContract("empty source contract"));
        }
        let mut methods = BTreeSet::new();
        for method in &self.methods {
            if !methods.insert(method.key.clone()) {
                return Err(RegistryError::DuplicateMethod);
            }
            validate_method(method, self.access)?;
        }
        let mut fields = BTreeSet::new();
        for field in &self.fields {
            if !fields.insert(field.field) {
                return Err(RegistryError::DuplicateField);
            }
            if field.method_keys.is_empty()
                || field.method_keys.iter().any(|key| !methods.contains(key))
            {
                return Err(RegistryError::InvalidContract("field method reference"));
            }
            if field.method_keys.iter().any(|key| {
                self.methods
                    .iter()
                    .find(|method| &method.key == key)
                    .is_some_and(|method| method.absence != field.absence)
            }) {
                return Err(RegistryError::InvalidSemantics);
            }
            if field.authority == FieldAuthority::ChainEvidence
                && self.provider.as_str().contains("pumpportal")
            {
                return Err(RegistryError::InvalidContract(
                    "provider assertion cannot be chain authority",
                ));
            }
        }
        if self.progress == ProgressSemantics::LiveOnlyNoReplay
            && !self
                .methods
                .iter()
                .all(|method| method.absence == AbsenceSemantics::LiveOnlyGap)
        {
            return Err(RegistryError::InvalidSemantics);
        }
        if self.progress == ProgressSemantics::IntervalPoll
            && !self
                .methods
                .iter()
                .all(|method| method.absence == AbsenceSemantics::IntervalCensored)
        {
            return Err(RegistryError::InvalidSemantics);
        }
        let expected_gap = match self.progress {
            ProgressSemantics::ReplayCursor | ProgressSemantics::SlotAnchorRequiresRecovery => {
                Some(GapSemantics::RecoverableWithBoundedRead)
            }
            ProgressSemantics::IntervalPoll => Some(GapSemantics::IntervalCensored),
            ProgressSemantics::LiveOnlyNoReplay => Some(GapSemantics::UnrecoverableLiveOnly),
            ProgressSemantics::FixtureSequence => Some(GapSemantics::RecoverableWithBoundedRead),
        };
        if expected_gap.is_some_and(|gap| self.retry.gap != gap) {
            return Err(RegistryError::InvalidSemantics);
        }
        if self.retry.max_attempts == 0 {
            return Err(RegistryError::InvalidValue("retry attempts"));
        }
        let digest = self.canonical_fingerprint()?;
        if self.schema_fingerprint.is_none() {
            return Err(RegistryError::InvalidContract(
                "source schema fingerprint required",
            ));
        }
        if self
            .schema_fingerprint
            .as_ref()
            .is_some_and(|expected| expected != &digest)
        {
            return Err(RegistryError::FingerprintMismatch);
        }
        Ok(digest)
    }

    /// Validates structure and admits one source for a run. Disabled/unavailable sources and an
    /// active kill switch remain useful declarations for gap reporting but cannot be admitted.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError::KillSwitched`] or [`RegistryError::SourceDisabled`] when the source
    /// is not runnable, after structural validation.
    pub fn admit(&self) -> Result<(), RegistryError> {
        self.validate()?;
        if self.kill_switch.enabled {
            return Err(RegistryError::KillSwitched);
        }
        match self.status {
            SourceStatus::Enabled => Ok(()),
            SourceStatus::Disabled | SourceStatus::Unavailable => {
                Err(RegistryError::SourceDisabled)
            }
        }
    }

    /// Resolves a method after source-level admission. This is the collector's narrow pre-I/O
    /// lookup; it does not build a URL, read a credential, or perform a request.
    ///
    /// # Errors
    ///
    /// Refuses a source that is not admitted or a method key that is not declared.
    pub fn admit_method(&self, key: &StableString) -> Result<&MethodContract, RegistryError> {
        self.admit()?;
        self.methods
            .iter()
            .find(|method| &method.key == key)
            .ok_or(RegistryError::InvalidValue("unknown source method"))
    }

    /// Computes the schema fingerprint while excluding the self-referential fingerprint field.
    ///
    /// # Errors
    ///
    /// Returns an encoding or digest-construction refusal.
    pub fn canonical_fingerprint(&self) -> Result<ValueDigest, RegistryError> {
        let bytes = self.canonical_template_bytes()?;
        let digest = Sha256::digest(bytes);
        let text = format!("sha256:{digest:x}");
        ValueDigest::new(text).map_err(|_| RegistryError::InvalidValue("digest"))
    }

    /// Returns canonical source/method policy bytes with the self-referential schema fingerprint
    /// omitted. Integrators may include these bytes in a larger plan-template digest; this method
    /// performs no run binding, credential lookup, or provider I/O.
    ///
    /// # Errors
    ///
    /// Returns an encoding refusal when the contract cannot be represented canonically.
    pub fn canonical_template_bytes(&self) -> Result<Vec<u8>, RegistryError> {
        let mut copy = self.clone();
        copy.schema_fingerprint = None;
        serde_json::to_vec(&copy).map_err(Into::into)
    }

    /// Computes the canonical digest used to bind a source policy into a plan template.
    ///
    /// # Errors
    ///
    /// Returns a digest-construction refusal.
    pub fn canonical_template_digest(&self) -> Result<ValueDigest, RegistryError> {
        self.canonical_fingerprint()
    }

    /// Returns a copy with its canonical fingerprint populated.
    ///
    /// # Errors
    ///
    /// Returns any structural validation or digest refusal.
    pub fn fingerprinted(mut self) -> Result<Self, RegistryError> {
        self.schema_fingerprint = Some(self.canonical_fingerprint()?);
        self.validate()?;
        Ok(self)
    }
}

fn validate_method(method: &MethodContract, access: AccessClass) -> Result<(), RegistryError> {
    if method.max_request_bytes == 0 || method.max_response_bytes == 0 {
        return Err(RegistryError::InvalidValue("method byte bound"));
    }
    if method.billing.unit == BillingUnit::None && method.billing.minor_units_per_unit != 0 {
        return Err(RegistryError::InvalidValue("billing unit"));
    }
    if method.billing.minor_units_per_unit == 0
        && access == AccessClass::UnauthenticatedPublic
        && method.billing.zero_price_attestation == ZeroPriceAttestation::NotProvided
    {
        return Err(RegistryError::ZeroPriceNotUnauthenticated);
    }
    if access == AccessClass::UnauthenticatedPublic
        && method.billing.zero_price_attestation == ZeroPriceAttestation::OperatorConformanceOnly
        && method.kind != MethodKind::Fixture
    {
        return Err(RegistryError::ZeroPriceNotUnauthenticated);
    }
    if method.billing.minor_units_per_unit > 0 && !method.quota.remaining_observable {
        return Err(RegistryError::InvalidContract(
            "paid quota must be observable",
        ));
    }
    if method.billing.minor_units_per_unit > 0 && method.quota.hard_limit.is_none() {
        return Err(RegistryError::InvalidContract(
            "paid method requires a hard quota cap",
        ));
    }
    if method.billing.minor_units_per_unit > 0
        && method.billing.currency.is_none()
        && method.billing.unit != BillingUnit::ProviderCredit
        && method.billing.unit != BillingUnit::ChainNativeAtom
    {
        return Err(RegistryError::InvalidContract(
            "charged method lacks currency",
        ));
    }
    if method.billing.unit == BillingUnit::ChainNativeAtom && method.billing.asset_id.is_none() {
        return Err(RegistryError::InvalidContract("native billing asset"));
    }
    if method.quota.unit != method.billing.unit {
        return Err(RegistryError::InvalidContract("billing/quota unit"));
    }
    if method.quota.window_seconds == Some(0) {
        return Err(RegistryError::InvalidValue("quota window"));
    }
    if method.commitment == Commitment::None && method.finality == FinalityPolicy::RequireFinalized
    {
        return Err(RegistryError::InvalidSemantics);
    }
    Ok(())
}

/// A strict registry of source contracts. It is intentionally not a global mutable registry.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceRegistry {
    pub contract: StableString,
    pub schema_version: u64,
    pub sources: Vec<SourceContract>,
}

impl SourceRegistry {
    /// # Errors
    ///
    /// Refuses a wrong registry contract/version, an empty registry, duplicate source, or invalid
    /// source contract.
    pub fn validate(&self) -> Result<(), RegistryError> {
        if self.contract.as_str() != REGISTRY_CONTRACT
            || self.schema_version != REGISTRY_SCHEMA_VERSION
        {
            return Err(RegistryError::InvalidContract("registry version"));
        }
        if self.sources.is_empty() {
            return Err(RegistryError::InvalidContract("empty registry"));
        }
        let mut ids = BTreeSet::new();
        for source in &self.sources {
            if !ids.insert(source.source_id.clone()) {
                return Err(RegistryError::DuplicateSource);
            }
            source.validate()?;
        }
        Ok(())
    }
    /// # Errors
    ///
    /// Returns any registry validation or JSON encoding refusal.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, RegistryError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    /// Performs the explicit pre-I/O admission check for one source identity.
    ///
    /// # Errors
    ///
    /// Refuses an unknown, disabled, unavailable, kill-switched, or structurally invalid source.
    pub fn admit(&self, source_id: &SourceId) -> Result<&SourceContract, RegistryError> {
        let source = self
            .sources
            .iter()
            .find(|source| &source.source_id == source_id)
            .ok_or(RegistryError::InvalidValue("unknown source"))?;
        source.admit()?;
        Ok(source)
    }
}

/// Small builder kept as a convenience for fixture and adapter authors; validation remains on the
/// resulting contract and no builder method performs I/O.
#[derive(Default)]
pub struct SourceContractBuilder {
    source: Option<SourceContract>,
}

impl SourceContractBuilder {
    #[must_use]
    pub fn new(source: SourceContract) -> Self {
        Self {
            source: Some(source),
        }
    }
    /// # Errors
    ///
    /// Refuses a missing or invalid source declaration.
    pub fn build(self) -> Result<SourceContract, RegistryError> {
        self.source
            .ok_or(RegistryError::InvalidContract("missing source"))?
            .fingerprinted()
    }
}

#[derive(Default)]
pub struct SourceRegistryBuilder {
    sources: Vec<SourceContract>,
}

impl SourceRegistryBuilder {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
    #[must_use]
    pub fn push(mut self, source: SourceContract) -> Self {
        self.sources.push(source);
        self
    }
    /// # Errors
    ///
    /// Refuses an empty or structurally invalid registry.
    pub fn build(self) -> Result<SourceRegistry, RegistryError> {
        let contract = stable(REGISTRY_CONTRACT)?;
        let registry = SourceRegistry {
            contract,
            schema_version: REGISTRY_SCHEMA_VERSION,
            sources: self.sources,
        };
        registry.validate()?;
        Ok(registry)
    }
}

/// Built-in declaration for one bounded, credential-free Solana mainnet signature page.
///
/// The official public endpoint is rate-limited and explicitly unsuitable as a production
/// backend. This contract therefore supplies only a C1 conformance source declaration. It does
/// not open a socket, prove availability or remaining quota, or authorize a sustained collector.
/// Empty results never prove wallet inactivity or historical absence.
///
/// # Errors
///
/// Returns a structural or fingerprint refusal if the frozen source policy is inconsistent.
pub fn public_solana_mainnet_contract() -> Result<SourceContract, RegistryError> {
    let method_key = stable(PUBLIC_SOLANA_SIGNATURES_METHOD_KEY)?;
    let method_schema_digest = ValueDigest::new(format!(
        "sha256:{:x}",
        Sha256::digest(PUBLIC_SOLANA_SIGNATURES_SCHEMA)
    ))
    .map_err(|_| RegistryError::InvalidValue("schema digest"))?;
    SourceContract {
        source_id: SourceId::new(PUBLIC_SOLANA_MAINNET_SOURCE_ID)
            .map_err(|_| RegistryError::InvalidValue("source id"))?,
        provider: stable("solana-public-rpc")?,
        contract_version: stable("solana-json-rpc/mainnet/v1")?,
        status: SourceStatus::Enabled,
        access: AccessClass::UnauthenticatedPublic,
        credential: CredentialAuthority::None,
        credential_descriptor: None,
        methods: vec![MethodContract {
            key: method_key.clone(),
            kind: MethodKind::HttpPostReadOnly,
            schema_fingerprint: SchemaFingerprint {
                algorithm: stable("sha256")?,
                digest: method_schema_digest,
            },
            billing: BillingPolicy {
                unit: BillingUnit::Request,
                minor_units_per_unit: 0,
                currency: None,
                asset_id: None,
                zero_price_attestation: ZeroPriceAttestation::DocumentedPublicSurface,
            },
            quota: QuotaSpec {
                unit: BillingUnit::Request,
                hard_limit: None,
                reset: QuotaReset::Unknown,
                window_seconds: None,
                remaining_observable: false,
            },
            commitment: Commitment::Finalized,
            finality: FinalityPolicy::RequireFinalized,
            absence: AbsenceSemantics::NeverProvesAbsence,
            max_request_bytes: 4 * 1_024,
            max_response_bytes: 64 * 1_024 * 1_024,
        }],
        fields: vec![FieldContract {
            field: FieldKind::Wallet,
            authority: FieldAuthority::ChainEvidence,
            method_keys: vec![method_key],
            absence: AbsenceSemantics::NeverProvesAbsence,
        }],
        progress: ProgressSemantics::ReplayCursor,
        retry: RetryPolicy {
            max_attempts: 3,
            max_delay_ms: 10_000,
            retryable_statuses: vec![429, 500, 502, 503, 504],
            gap: GapSemantics::RecoverableWithBoundedRead,
        },
        protection: ProtectionClass::Public,
        retention: RetentionClass::Public,
        kill_switch: KillSwitch {
            enabled: false,
            reason: stable("bounded_c1_conformance_only")?,
            requires_operator_reenable: false,
        },
        schema_fingerprint: None,
    }
    .fingerprinted()
}

/// Built-in declaration for `PumpPortal`'s provider contract. It is deliberately disabled: the
/// provider's API key confers wallet-bearing signing authority, including for zero-priced routes.
///
/// # Errors
///
/// Always returns [`RegistryError::WalletBearingCredential`]. This explicit refusal keeps the
/// credentialed provider out of the read-only collector.
pub fn pumpportal_contract() -> Result<SourceContract, RegistryError> {
    let key = stable("pumpportal")?;
    let method_key = stable("new_token")?;
    let schema = SchemaFingerprint {
        algorithm: stable("sha256")?,
        digest: ValueDigest::new("sha256:fixture-pumpportal-schema")
            .map_err(|_| RegistryError::InvalidValue("schema digest"))?,
    };
    let method = MethodContract {
        key: method_key.clone(),
        kind: MethodKind::WebsocketSubscription,
        schema_fingerprint: schema,
        billing: BillingPolicy {
            unit: BillingUnit::TokenTradeEvent,
            minor_units_per_unit: 0,
            currency: None,
            asset_id: None,
            zero_price_attestation: ZeroPriceAttestation::NotProvided,
        },
        quota: QuotaSpec {
            unit: BillingUnit::TokenTradeEvent,
            hard_limit: Some(0),
            reset: QuotaReset::ProviderReported,
            window_seconds: None,
            remaining_observable: false,
        },
        commitment: Commitment::Processed,
        finality: FinalityPolicy::ProvisionalThenCorrect,
        absence: AbsenceSemantics::LiveOnlyGap,
        max_request_bytes: 64 * 1024,
        max_response_bytes: 4 * 1024 * 1024,
    };
    let source = SourceContract {
        source_id: SourceId::new(key.as_str())
            .map_err(|_| RegistryError::InvalidValue("source id"))?,
        provider: stable("pumpportal")?,
        contract_version: stable("pumpportal.data_api/v1")?,
        status: SourceStatus::Disabled,
        access: AccessClass::AuthenticatedPrivate,
        credential: CredentialAuthority::WalletBearingSigning,
        credential_descriptor: Some(CredentialDescriptor {
            key_id: stable("pumpportal-wallet-api-key")?,
            authority: CredentialAuthority::WalletBearingSigning,
            owner_only: true,
            purpose: stable("provider session")?,
        }),
        methods: vec![method],
        fields: vec![FieldContract {
            field: FieldKind::Launch,
            authority: FieldAuthority::ProviderAssertion,
            method_keys: vec![method_key],
            absence: AbsenceSemantics::LiveOnlyGap,
        }],
        progress: ProgressSemantics::LiveOnlyNoReplay,
        retry: RetryPolicy {
            max_attempts: 3,
            max_delay_ms: 60_000,
            retryable_statuses: vec![429, 500, 502, 503, 504],
            gap: GapSemantics::UnrecoverableLiveOnly,
        },
        protection: ProtectionClass::AuthenticatedPrivate,
        retention: RetentionClass::LocalOnly,
        kill_switch: KillSwitch {
            enabled: true,
            reason: stable("wallet_bearing_key_not_admitted")?,
            requires_operator_reenable: true,
        },
        schema_fingerprint: None,
    };
    // This source is intentionally rejected before it can be handed to a collector. The caller
    // receives a typed policy refusal rather than an apparently usable contract.
    source.validate()?;
    Ok(source)
}
