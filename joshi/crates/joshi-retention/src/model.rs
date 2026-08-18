use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeSet, fmt};

const MAX_ID: usize = 255;

macro_rules! id_type {
    ($name:ident) => {
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Creates a bounded, non-empty occurrence identifier.
            ///
            /// # Errors
            ///
            /// Returns an error for empty, padded, control-bearing, or oversized values.
            pub fn new(value: impl Into<String>) -> Result<Self, String> {
                let value = value.into();
                if value.is_empty()
                    || value.len() > MAX_ID
                    || value.trim() != value
                    || value.chars().any(char::is_control)
                {
                    return Err(format!("invalid {}", stringify!($name)));
                }
                Ok(Self(value))
            }

            /// Returns the exact identifier.
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }
    };
}

id_type!(DomainId);
id_type!(OccurrenceId);
id_type!(TombstoneId);
id_type!(ReleaseId);

/// Physical or derived member of one retention closure.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InventoryKind {
    /// Original exact segment at the collecting host.
    OriginSpool,
    /// Content-addressed exact bytes.
    Cas,
    /// A remote or removable replica of exact bytes.
    Replica,
    /// An exported artifact or archive.
    Export,
    /// A feature, index, projection, or other derived reference.
    DerivedReference,
}

/// Whether bytes are currently observed at an inventory location.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ByteFact {
    Present,
    Absent,
    Unknown,
}

/// Protection state for a domain key.  Key destruction is a separate fact from byte absence.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum KeyState {
    Present,
    Erased,
    Unknown,
}

/// Authenticated-private protection domain and its non-secret key identity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct ProtectionDomain {
    pub domain_id: DomainId,
    pub key_id: String,
    pub key_state: KeyState,
}

impl ProtectionDomain {
    /// Creates a domain; empty key identifiers are refused.
    ///
    /// # Errors
    ///
    /// Returns an error for an empty, padded, or oversized key identifier.
    pub fn new(domain_id: DomainId, key_id: impl Into<String>) -> Result<Self, String> {
        let key_id = key_id.into();
        if key_id.is_empty() || key_id.len() > MAX_ID || key_id.trim() != key_id {
            return Err("invalid key identifier".into());
        }
        Ok(Self {
            domain_id,
            key_id,
            key_state: KeyState::Present,
        })
    }
}

/// One inventory item in a dependency closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct InventoryItem {
    pub item_id: OccurrenceId,
    pub kind: InventoryKind,
    pub domain_id: DomainId,
    pub content_digest: String,
    pub bytes: ByteFact,
    pub key_id: String,
    /// Items that must be released before this item can be released.
    pub depends_on: BTreeSet<OccurrenceId>,
}

/// Origin item constructor data.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Inventory {
    pub domains: Vec<ProtectionDomain>,
    pub items: Vec<InventoryItem>,
}

impl Inventory {
    /// Computes the exact digest used by [`InventoryWitness`].
    #[must_use]
    pub fn exact_digest(&self) -> String {
        let bytes = serde_json::to_vec(self).unwrap_or_default();
        let mut digest = Sha256::new();
        digest.update(bytes);
        format!("sha256:{:x}", digest.finalize())
    }
}

/// Store-produced closure metadata. A kernel created without this witness is intentionally
/// unqualified: a caller-supplied list must not be able to hide an export or replica.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct InventoryWitness {
    pub(crate) inventory_digest: String,
    pub(crate) cutoff: u64,
    pub(crate) receipt_digest: String,
}

/// Explicit replica inventory occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplicaReference {
    pub item: InventoryItem,
    pub source_item: OccurrenceId,
}

/// Explicit export inventory occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExportReference {
    pub item: InventoryItem,
    pub source_items: BTreeSet<OccurrenceId>,
}

/// Explicit derived-reference inventory occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DerivedReference {
    pub item: InventoryItem,
    pub source_items: BTreeSet<OccurrenceId>,
}

/// Scope of a release occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct ReleaseScope {
    pub item_ids: BTreeSet<OccurrenceId>,
    pub catalog_release_digest: String,
    pub authorization_digest: String,
}

/// Append-only tombstone occurrence. It requests logical suppression, not physical mutation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct Tombstone {
    pub occurrence_id: OccurrenceId,
    pub tombstone_id: TombstoneId,
    pub domain_id: DomainId,
    pub item_ids: BTreeSet<OccurrenceId>,
    pub recorded_at: u64,
}

/// Append-only catalog/reference release occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct Release {
    pub occurrence_id: OccurrenceId,
    pub release_id: ReleaseId,
    pub domain_id: DomainId,
    pub tombstone_id: TombstoneId,
    pub scope: ReleaseScope,
    pub recorded_at: u64,
}

/// Requested external retention action. This crate never executes it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct DeletionRequest {
    pub occurrence_id: OccurrenceId,
    pub request_id: OccurrenceId,
    pub domain_id: DomainId,
    pub tombstone_id: TombstoneId,
    pub release_id: ReleaseId,
    pub item_ids: BTreeSet<OccurrenceId>,
    pub authorization_digest: String,
    pub requested_at: u64,
}

/// Independently observed external result. It is never treated as an instruction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct DeletionReceipt {
    pub occurrence_id: OccurrenceId,
    pub receipt_id: OccurrenceId,
    pub request_id: OccurrenceId,
    pub domain_id: DomainId,
    pub item_ids: BTreeSet<OccurrenceId>,
    pub phase: DeletionPhase,
    pub evidence_digest: String,
    pub recorded_at: u64,
}

/// Independent byte/key facts, matching the spool protocol without authorizing disposal.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeletionPhase {
    Requested,
    BytesDeleted,
    KeyDestroyed,
    BytesDeletedAndKeyDestroyed,
}

/// All append-only occurrences accepted by the kernel.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "occurrence", rename_all = "snake_case")]
pub enum Occurrence {
    Tombstone(Tombstone),
    Release(Release),
    DeletionRequest(DeletionRequest),
    DeletionReceipt(DeletionReceipt),
}

impl Occurrence {
    /// Returns its append-only occurrence identity.
    #[must_use]
    pub fn occurrence_id(&self) -> &OccurrenceId {
        match self {
            Self::Tombstone(value) => &value.occurrence_id,
            Self::Release(value) => &value.occurrence_id,
            Self::DeletionRequest(value) => &value.occurrence_id,
            Self::DeletionReceipt(value) => &value.occurrence_id,
        }
    }
}

/// Retention never changes source coverage; this marker prevents an outcome from impersonating it.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoverageEffect {
    Unchanged,
}

/// Deterministic status of a retention report.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetentionStatus {
    Blocked,
    Eligible,
    Observed,
}

/// Independent physical/key fact summary; no scalar status implies both facts.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompletionState {
    Neither,
    BytesOnly,
    KeyOnly,
    BytesAndKey,
}

/// Why an external controller must not proceed.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Refusal {
    MissingTombstone,
    MissingRelease,
    OutstandingDependency,
    OutstandingReference,
    PartialReplica,
    UnknownInventory,
    KeyAlreadyErased,
    StaleReceipt,
    RequestNotEligible,
    DomainMismatch,
    CoverageUnaffected,
}

/// Pure report produced from the current occurrence prefix.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RetentionReport {
    pub status: RetentionStatus,
    pub domain_id: DomainId,
    pub item_ids: BTreeSet<OccurrenceId>,
    pub refusals: BTreeSet<Refusal>,
    pub key_state: KeyState,
    pub coverage_effect: CoverageEffect,
    pub request_id: Option<OccurrenceId>,
    pub observed_phases: BTreeSet<DeletionPhase>,
    pub completion: CompletionState,
}

/// Stable digest of an occurrence, useful for retry and audit identity.
#[must_use]
pub fn occurrence_digest(value: &Occurrence) -> String {
    let bytes = serde_json::to_vec(value).unwrap_or_default();
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("sha256:{:x}", digest.finalize())
}

/// Parses one exact, canonical occurrence and rejects unknown fields or changed formatting.
///
/// # Errors
///
/// Returns an error when JSON is malformed, contains unknown fields, or is not canonical.
pub fn parse_occurrence_exact(bytes: &[u8]) -> Result<Occurrence, String> {
    let occurrence: Occurrence =
        serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    let canonical = serde_json::to_vec(&occurrence).map_err(|error| error.to_string())?;
    if canonical != bytes {
        return Err("occurrence bytes are not canonical".into());
    }
    Ok(occurrence)
}
