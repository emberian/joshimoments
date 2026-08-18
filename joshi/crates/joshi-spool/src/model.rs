use crate::{CATALOG_ACK_CONTRACT_VERSION, REMOTE_ACK_CONTRACT_VERSION, SPOOL_CONTRACT_VERSION};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use joshi_domain::{AcquisitionId, StableString, UtcTimestamp, ValueDigest};
use joshi_evidence::{Boundary, CoverageScope, CursorAdvance, DurableIngestBatch};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeSet, fmt};

macro_rules! protocol_id {
    ($name:ident) => {
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Creates a bounded, non-empty protocol identifier.
            ///
            /// # Errors
            ///
            /// Returns an error for empty, padded, control-bearing, or oversized values.
            pub fn new(value: impl Into<String>) -> crate::Result<Self> {
                let value = value.into();
                if value.is_empty()
                    || value.len() > 255
                    || value.trim() != value
                    || value.chars().any(char::is_control)
                {
                    return Err(crate::SpoolError::Invalid(format!(
                        "{} is not a stable protocol identifier",
                        stringify!($name)
                    )));
                }
                Ok(Self(value))
            }

            /// Returns the exact retained identifier.
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

protocol_id!(SegmentId);
protocol_id!(ProtectionDomainId);
protocol_id!(ReplicaId);

/// Integrity closure over exact bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ByteClosure {
    /// Algorithm-qualified digest.
    pub digest: String,
    /// Exact byte length.
    pub byte_len: u64,
}

impl ByteClosure {
    /// Computes a SHA-256 closure over exact bytes.
    #[must_use]
    pub fn of(bytes: &[u8]) -> Self {
        Self {
            digest: sha256(bytes),
            byte_len: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        }
    }

    /// Verifies exact bytes.
    ///
    /// # Errors
    ///
    /// Returns an integrity error when either the digest or byte length differs.
    pub fn verify(&self, bytes: &[u8]) -> crate::Result<()> {
        if self == &Self::of(bytes) {
            Ok(())
        } else {
            Err(crate::SpoolError::Integrity(format!(
                "expected {} bytes at {}, received {} bytes at {}",
                self.byte_len,
                self.digest,
                bytes.len(),
                sha256(bytes)
            )))
        }
    }
}

/// Public versus authenticated-private physical protection.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtectionClass {
    /// Integrity-only bytes suitable only for explicitly public evidence.
    PublicIntegrity,
    /// AEAD-sealed bytes; privacy does not depend on transport or remote filesystem encryption.
    AuthenticatedPrivate,
}

/// Caller request for a single-domain segment.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProtectionRequest {
    /// Exact body bytes remain visible.
    Public {
        /// Storage/protection domain.
        domain: ProtectionDomainId,
    },
    /// Exact body bytes are encrypted and authenticated before crossing the remote boundary.
    AuthenticatedPrivate {
        /// Storage/protection domain.
        domain: ProtectionDomainId,
        /// Non-secret identifier of the encryption key.
        key_id: String,
        /// Unique 96-bit nonce under this key and domain.
        nonce: [u8; 12],
    },
}

impl ProtectionRequest {
    /// Protection domain for the whole physical segment.
    #[must_use]
    pub fn domain(&self) -> &ProtectionDomainId {
        match self {
            Self::Public { domain } | Self::AuthenticatedPrivate { domain, .. } => domain,
        }
    }
}

/// Non-secret protection metadata retained in the segment header.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "class", rename_all = "snake_case")]
pub enum ProtectionMetadata {
    /// Integrity-only public body.
    PublicIntegrity,
    /// ChaCha20-Poly1305 body with the header material as associated data.
    AuthenticatedPrivate {
        /// Algorithm contract.
        algorithm: String,
        /// Non-secret key identifier.
        key_id: String,
        /// Base64 96-bit nonce.
        nonce_base64: String,
    },
}

impl ProtectionMetadata {
    /// Returns the physical protection class.
    #[must_use]
    pub const fn class(&self) -> ProtectionClass {
        match self {
            Self::PublicIntegrity => ProtectionClass::PublicIntegrity,
            Self::AuthenticatedPrivate { .. } => ProtectionClass::AuthenticatedPrivate,
        }
    }
}

/// One acquisition occurrence represented in a segment.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceOccurrence {
    /// Source contract identity.
    pub source_id: String,
    /// Acquisition occurrence identity, never a content digest.
    pub acquisition_id: String,
}

/// Counts the durable store is expected to close for a retained batch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExpectedCounts {
    pub acquisitions: u64,
    pub raw_blobs: u64,
    pub raw_bytes: u64,
    pub observations: u64,
    pub source_events: u64,
    pub assertions: u64,
    pub coverage_windows: u64,
    pub coverage_gaps: u64,
    pub coverage_recoveries: u64,
    pub cursor_advances: u64,
}

/// Logical and physical closure needed to match a later catalog receipt exactly.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BatchClosure {
    pub batch_id: String,
    pub logical_digest: String,
    pub exact_batch: ByteClosure,
    pub policy_contract: String,
    pub exact_policy: ByteClosure,
    /// Must remain absent in an origin segment. The store-owned admission digest does not exist
    /// until after the exact batch is committed; it belongs only in [`CatalogAdmissionAck`].
    ///
    /// The optional wire slot is retained for strict readback of older fixtures, but catalog ACK
    /// admission refuses a segment that self-authored this postcommit value.
    pub admission_digest: Option<String>,
    pub counts: ExpectedCounts,
    pub acquisition_ids: Vec<String>,
    pub gap_ids: Vec<String>,
}

/// A copied source cursor claim. This type deliberately has no commit or authority field.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CursorCandidate {
    pub cursor_id: String,
    pub scope: CoverageScope,
    pub cursor_kind: joshi_domain::OpenVariant,
    pub cursor_value: StableString,
    pub acquisition_id: AcquisitionId,
    pub primary_observation_id: String,
    pub evidence_observation_ids: Vec<String>,
    pub predecessor_cursor_id: Option<String>,
}

impl From<&CursorAdvance> for CursorCandidate {
    fn from(value: &CursorAdvance) -> Self {
        Self {
            cursor_id: value.cursor_id.to_string(),
            scope: value.scope.clone(),
            cursor_kind: value.cursor_kind.clone(),
            cursor_value: value.cursor_value.clone(),
            acquisition_id: value.acquisition_id.clone(),
            primary_observation_id: value.primary_observation_id.to_string(),
            evidence_observation_ids: value.evidence.iter().map(ToString::to_string).collect(),
            predecessor_cursor_id: value
                .predecessor_cursor_id
                .as_ref()
                .map(ToString::to_string),
        }
    }
}

/// Exact evidence and physical-policy bytes, retained without later reserialization.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EvidenceBatchEntry {
    pub closure: BatchClosure,
    #[serde(with = "base64_bytes")]
    pub exact_batch_bytes: Vec<u8>,
    #[serde(with = "base64_bytes")]
    pub exact_policy_bytes: Vec<u8>,
    /// Descriptive copies only. Catalog `CursorAdvance` remains the sole authority.
    pub cursor_candidates: Vec<CursorCandidate>,
}

impl EvidenceBatchEntry {
    /// Retains caller-supplied exact encodings after checking that the batch bytes decode to the
    /// supplied typed value. An origin segment passes no `admission_digest`: that store-owned
    /// result exists only after commit and is written to the separate catalog ACK.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed/noncanonical batches, digest disagreement, or exact bytes
    /// which do not decode to the supplied value.
    pub fn from_exact_bytes(
        batch: &DurableIngestBatch,
        exact_batch_bytes: Vec<u8>,
        policy_contract: impl Into<String>,
        exact_policy_bytes: Vec<u8>,
        admission_digest: Option<&ValueDigest>,
    ) -> crate::Result<Self> {
        let computed = joshi_store::SqliteStore::canonical_batch_digest(batch)
            .map_err(|error| crate::SpoolError::Invalid(error.to_string()))?;
        if computed != batch.expected_digest {
            return Err(crate::SpoolError::Integrity(format!(
                "logical batch digest mismatch: expected {}, computed {computed}",
                batch.expected_digest
            )));
        }
        let decoded: DurableIngestBatch = serde_json::from_slice(&exact_batch_bytes)?;
        if &decoded != batch {
            return Err(crate::SpoolError::Integrity(
                "exact batch bytes do not decode to the supplied batch".into(),
            ));
        }
        let closure = batch_closure(
            batch,
            &exact_batch_bytes,
            policy_contract.into(),
            &exact_policy_bytes,
            admission_digest,
        )?;
        Ok(Self {
            closure,
            exact_batch_bytes,
            exact_policy_bytes,
            cursor_candidates: batch.cursor_advances.iter().map(Into::into).collect(),
        })
    }

    /// Serializes once at the append boundary, then retains those exact bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if the batch is noncanonical, has a wrong logical digest, or cannot be
    /// serialized.
    pub fn from_batch(
        batch: &DurableIngestBatch,
        policy_contract: impl Into<String>,
        exact_policy_bytes: Vec<u8>,
        admission_digest: Option<&ValueDigest>,
    ) -> crate::Result<Self> {
        Self::from_exact_bytes(
            batch,
            serde_json::to_vec(batch)?,
            policy_contract,
            exact_policy_bytes,
            admission_digest,
        )
    }
}

/// A visible scoped gap caused by collection, local pressure, transfer, or corruption.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GapRecord {
    pub gap_id: String,
    pub scope: CoverageScope,
    pub lower: Boundary,
    pub upper: Option<Boundary>,
    pub reason: joshi_domain::OpenVariant,
    pub detected_at: UtcTimestamp,
    pub related_segment_id: Option<SegmentId>,
}

/// Separately authorized retention intent. A remote ACK never constructs this record.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RetentionRecord {
    pub record_id: String,
    pub segment_id: SegmentId,
    pub domain: ProtectionDomainId,
    pub action: String,
    pub not_before: UtcTimestamp,
    pub catalog_release_digest: String,
    pub authorization_digest: String,
}

/// Independent byte-deletion and key-destruction states.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeletionPhase {
    Requested,
    BytesDeleted,
    KeyDestroyed,
    BytesDeletedAndKeyDestroyed,
}

/// Append-only disposal fact; it is not itself permission to delete.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeletionRecord {
    pub record_id: String,
    pub segment_id: SegmentId,
    pub domain: ProtectionDomainId,
    pub phase: DeletionPhase,
    pub recorded_at: UtcTimestamp,
    pub retention_record_id: String,
    pub evidence_digest: String,
}

/// Payload records accepted by a spool segment.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "record", rename_all = "snake_case")]
pub enum SpoolEntry {
    EvidenceBatch(EvidenceBatchEntry),
    Gap(GapRecord),
    Retention(RetentionRecord),
    Deletion(DeletionRecord),
}

impl SpoolEntry {
    #[must_use]
    pub(crate) fn occurrence_id(&self) -> String {
        match self {
            Self::EvidenceBatch(entry) => format!("batch:{}", entry.closure.batch_id),
            Self::Gap(entry) => format!("gap:{}", entry.gap_id),
            Self::Retention(entry) => format!("retention:{}", entry.record_id),
            Self::Deletion(entry) => format!("deletion:{}", entry.record_id),
        }
    }

    #[must_use]
    pub(crate) fn kind(&self) -> &'static str {
        match self {
            Self::EvidenceBatch(_) => "evidence_batch",
            Self::Gap(_) => "gap",
            Self::Retention(_) => "retention",
            Self::Deletion(_) => "deletion",
        }
    }
}

/// One ordered entry in a segment header.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EntryDescriptor {
    pub ordinal: u64,
    pub kind: String,
    pub occurrence_id: String,
    pub exact_entry: ByteClosure,
    pub batch: Option<BatchClosure>,
}

/// Segment header binding one domain, ordered entries, inner bytes, and ciphertext bytes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SegmentHeader {
    pub contract: String,
    pub segment_id: SegmentId,
    pub created_at: UtcTimestamp,
    pub domain: ProtectionDomainId,
    pub protection: ProtectionMetadata,
    pub entries: Vec<EntryDescriptor>,
    pub source_occurrences: Vec<SourceOccurrence>,
    pub body: ByteClosure,
    pub sealed_body: ByteClosure,
}

/// On-disk segment envelope. The body is ciphertext for authenticated-private domains.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiskSegment {
    pub header: SegmentHeader,
    #[serde(with = "base64_bytes")]
    pub sealed_body_bytes: Vec<u8>,
}

/// Exact occurrence/container closure used for replication and conflict detection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SegmentClosure {
    pub segment_id: SegmentId,
    pub domain: ProtectionDomainId,
    pub protection_class: ProtectionClass,
    pub exact_segment: ByteClosure,
}

/// A transport-neutral transfer chunk. Chunks are applied at their exact durable offset.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TransferChunk {
    pub closure: SegmentClosure,
    pub offset: u64,
    #[serde(with = "base64_bytes")]
    pub bytes: Vec<u8>,
}

/// Key identifying one durable remote receipt.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AckKey {
    pub replica_id: ReplicaId,
    pub replica_generation: String,
}

/// Proof only that exact sealed segment bytes are durable at one replica generation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RemoteDurabilityAck {
    pub contract: String,
    pub replica_id: ReplicaId,
    pub replica_generation: String,
    pub segment: SegmentClosure,
}

impl RemoteDurabilityAck {
    pub(crate) fn new(
        replica_id: ReplicaId,
        replica_generation: String,
        segment: SegmentClosure,
    ) -> Self {
        Self {
            contract: REMOTE_ACK_CONTRACT_VERSION.into(),
            replica_id,
            replica_generation,
            segment,
        }
    }
}

/// Separately persisted exact catalog admission closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CatalogAdmissionAck {
    pub contract: String,
    pub segment_id: SegmentId,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub logical_digest: String,
    pub admission_digest: String,
    pub from_commit_seq: u64,
    pub through_commit_seq: u64,
}

impl CatalogAdmissionAck {
    pub(crate) fn with_contract(mut self) -> Self {
        self.contract = CATALOG_ACK_CONTRACT_VERSION.into();
        self
    }
}

/// Capacity state. Degraded means evidence admission stopped before consuming control reserve.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SpoolStatus {
    pub used_bytes: u64,
    pub maximum_bytes: u64,
    pub control_reserve_bytes: u64,
    pub degraded: bool,
}

pub(crate) fn source_occurrences(entries: &[SpoolEntry]) -> Vec<SourceOccurrence> {
    let mut result = BTreeSet::new();
    for entry in entries {
        if let SpoolEntry::EvidenceBatch(batch) = entry
            && let Ok(value) =
                serde_json::from_slice::<DurableIngestBatch>(&batch.exact_batch_bytes)
        {
            result.extend(
                value
                    .observations
                    .into_iter()
                    .map(|observation| SourceOccurrence {
                        source_id: observation.acquisition.source_id.to_string(),
                        acquisition_id: observation.acquisition.acquisition_id.to_string(),
                    }),
            );
        }
    }
    result.into_iter().collect()
}

pub(crate) fn validate_batch_entry(entry: &EvidenceBatchEntry) -> crate::Result<()> {
    let batch: DurableIngestBatch = serde_json::from_slice(&entry.exact_batch_bytes)?;
    let admission_digest = entry
        .closure
        .admission_digest
        .as_deref()
        .map(ValueDigest::new)
        .transpose()
        .map_err(|error| crate::SpoolError::Invalid(error.to_string()))?;
    let rebuilt = EvidenceBatchEntry::from_exact_bytes(
        &batch,
        entry.exact_batch_bytes.clone(),
        entry.closure.policy_contract.clone(),
        entry.exact_policy_bytes.clone(),
        admission_digest.as_ref(),
    )?;
    if &rebuilt == entry {
        Ok(())
    } else {
        Err(crate::SpoolError::Integrity(
            "batch body, closure, or cursor candidates disagree".into(),
        ))
    }
}

fn batch_closure(
    batch: &DurableIngestBatch,
    exact_batch_bytes: &[u8],
    policy_contract: String,
    exact_policy_bytes: &[u8],
    admission_digest: Option<&ValueDigest>,
) -> crate::Result<BatchClosure> {
    if batch.contract_version.as_str() != joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION {
        return Err(crate::SpoolError::Invalid(format!(
            "unsupported evidence batch contract {}",
            batch.contract_version
        )));
    }
    let acquisitions: BTreeSet<_> = batch
        .observations
        .iter()
        .map(|item| item.acquisition.acquisition_id.to_string())
        .collect();
    let raw_blobs: BTreeSet<_> = batch
        .observations
        .iter()
        .map(|item| sha256(&item.payload))
        .collect();
    let raw_bytes = batch.observations.iter().try_fold(0_u64, |total, item| {
        let len = u64::try_from(item.payload.len())
            .map_err(|_| crate::SpoolError::BoundExceeded("observation payload length".into()))?;
        total
            .checked_add(len)
            .ok_or_else(|| crate::SpoolError::BoundExceeded("batch payload byte sum".into()))
    })?;
    Ok(BatchClosure {
        batch_id: batch.batch_id.as_str().into(),
        logical_digest: batch.expected_digest.as_str().into(),
        exact_batch: ByteClosure::of(exact_batch_bytes),
        policy_contract,
        exact_policy: ByteClosure::of(exact_policy_bytes),
        admission_digest: admission_digest.map(ToString::to_string),
        counts: ExpectedCounts {
            acquisitions: u64::try_from(acquisitions.len()).unwrap_or(u64::MAX),
            raw_blobs: u64::try_from(raw_blobs.len()).unwrap_or(u64::MAX),
            raw_bytes,
            observations: u64::try_from(batch.observations.len()).unwrap_or(u64::MAX),
            source_events: u64::try_from(batch.source_events.len()).unwrap_or(u64::MAX),
            assertions: u64::try_from(batch.assertions.len()).unwrap_or(u64::MAX),
            coverage_windows: u64::try_from(batch.coverage_windows.len()).unwrap_or(u64::MAX),
            coverage_gaps: u64::try_from(batch.coverage_gaps.len()).unwrap_or(u64::MAX),
            coverage_recoveries: u64::try_from(batch.coverage_recoveries.len()).unwrap_or(u64::MAX),
            cursor_advances: u64::try_from(batch.cursor_advances.len()).unwrap_or(u64::MAX),
        },
        acquisition_ids: acquisitions.into_iter().collect(),
        gap_ids: batch
            .coverage_gaps
            .iter()
            .map(|gap| gap.gap_id.to_string())
            .collect(),
    })
}

#[must_use]
pub(crate) fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

pub(crate) fn stable_path_component(value: &str) -> String {
    sha256(value.as_bytes()).replace(':', "-")
}

pub(crate) fn contract_header() -> String {
    SPOOL_CONTRACT_VERSION.into()
}

mod base64_bytes {
    use super::*;
    use serde::{Deserializer, Serializer, de};

    pub fn serialize<S>(bytes: &[u8], serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&STANDARD.encode(bytes))
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Vec<u8>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let encoded = String::deserialize(deserializer)?;
        STANDARD.decode(encoded).map_err(de::Error::custom)
    }
}
