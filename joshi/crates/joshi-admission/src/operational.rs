//! Strict Wave 4 acknowledgement and immutable-publication receipts.
//!
//! These DTOs describe post-durability facts. They never authorize provider writes, wallet use,
//! transaction construction, signing, submission, trading, or liquidity changes.

use crate::{AdmissionError, PublicStoreReceiptV1, Sha256Digest, strict_json};
use serde::{Deserialize, Serialize};

pub const LOCAL_SPOOL_RECEIPT_CONTRACT: &str = "joshi.spool.local_ack";
pub const SPOOL_CATALOG_RECEIPT_CONTRACT: &str = "joshi.spool.catalog_admission_receipt";
pub const PROJECTION_PUBLICATION_RECEIPT_CONTRACT: &str =
    "joshi.store.projection_publication_receipt";
pub const COCKPIT_PUBLICATION_RECEIPT_CONTRACT: &str = "joshi.store.cockpit_publication_receipt";
pub const PRESENTATION_SCENE_RECEIPT_CONTRACT: &str = "joshi.store.presentation_scene_receipt";
pub const PRESENTATION_EVENT_RECEIPT_CONTRACT: &str = "joshi.store.presentation_event_receipt";
pub const EXPORT_VALIDATION_RECEIPT_CONTRACT: &str = "joshi.store.export_validation_receipt";
pub const ARTIFACT_IMPORT_RECEIPT_CONTRACT: &str = "joshi.store.analysis_artifact_receipt";
pub const SOURCE_FACT_ARTIFACT_RECEIPT_CONTRACT: &str = "joshi.store.source_fact_artifact_receipt";
pub const EPISODE_PROTOCOL_CONTRACT: &str = "joshi.episode.protocol_registration";
pub const EPISODE_PROTOCOL_RECEIPT_CONTRACT: &str = "joshi.store.episode_protocol_receipt";
pub const EPISODE_LAUNCH_CONTRACT: &str = "joshi.episode.launch_registration";
pub const EPISODE_LAUNCH_RECEIPT_CONTRACT: &str = "joshi.store.episode_launch_receipt";
pub const SESSION_LAUNCH_CONTRACT: &str = "joshi.glass.session_launch";
pub const PROSPECTIVE_NOMINATION_CONTRACT: &str = "joshi.operator.prospective_nomination";
pub const PROSPECTIVE_NOMINATION_RECEIPT_CONTRACT: &str =
    "joshi.store.prospective_nomination_receipt";
pub const EXPLICIT_ABSTENTION_CONTRACT: &str = "joshi.operator.explicit_abstention";
pub const EXPLICIT_ABSTENTION_RECEIPT_CONTRACT: &str = "joshi.store.explicit_abstention_receipt";
pub const AUTHORITY: &str = "read_only_no_execution";
pub const MAX_OPERATIONAL_RECEIPT_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationalStatus {
    Accepted,
    Idempotent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PublicProtectionClass {
    PublicIntegrity,
    AuthenticatedPrivate,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExactByteClosureV1 {
    pub digest: Sha256Digest,
    pub byte_length: String,
}

impl ExactByteClosureV1 {
    /// Builds the exact SHA-256 and byte-length closure for a byte string.
    ///
    /// # Errors
    ///
    /// Returns an error if the byte length cannot be represented as a `u64`.
    pub fn new(bytes: &[u8]) -> Result<Self, AdmissionError> {
        Ok(Self {
            digest: Sha256Digest::of_bytes(bytes),
            byte_length: u64::try_from(bytes.len())
                .map_err(|_| AdmissionError::Receipt("byte length exceeds u64".into()))?
                .to_string(),
        })
    }

    /// Verifies bytes against this exact digest and length closure.
    ///
    /// # Errors
    ///
    /// Returns an error when the bytes differ or their length exceeds `u64`.
    pub fn verify(&self, bytes: &[u8]) -> Result<(), AdmissionError> {
        let actual = Self::new(bytes)?;
        if self == &actual {
            Ok(())
        } else {
            Err(AdmissionError::Receipt(
                "exact byte digest/length closure mismatch".into(),
            ))
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LocalSpoolReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub segment_id: String,
    pub protection_domain: String,
    pub protection_class: PublicProtectionClass,
    pub exact_segment: ExactByteClosureV1,
    pub status: OperationalStatus,
    pub authority: String,
}

impl LocalSpoolReceiptV1 {
    /// Validates the local durable-spool acknowledgement contract.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid contract, identity, length, or authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            LOCAL_SPOOL_RECEIPT_CONTRACT,
        )?;
        require_identity(&self.segment_id, "segmentId")?;
        require_identity(&self.protection_domain, "protectionDomain")?;
        require_positive_wire(&self.exact_segment.byte_length, "exactSegment.byteLength")?;
        require_authority(&self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SpoolBatchClosureV1 {
    pub batch_id: String,
    pub exact_batch: ExactByteClosureV1,
    pub logical_batch_digest: Sha256Digest,
    pub exact_policy: ExactByteClosureV1,
    pub store_admission_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SpoolCatalogReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub segment_id: String,
    pub protection_domain: String,
    pub protection_class: PublicProtectionClass,
    pub exact_segment: ExactByteClosureV1,
    pub batch: SpoolBatchClosureV1,
    pub catalog_receipt: PublicStoreReceiptV1,
    pub status: OperationalStatus,
    pub authority: String,
}

impl SpoolCatalogReceiptV1 {
    /// Validates the exact spool-segment to catalog-receipt closure.
    ///
    /// # Errors
    ///
    /// Returns an error when any identity, digest, commit, or authority differs.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            SPOOL_CATALOG_RECEIPT_CONTRACT,
        )?;
        require_identity(&self.segment_id, "segmentId")?;
        require_identity(&self.protection_domain, "protectionDomain")?;
        require_positive_wire(&self.exact_segment.byte_length, "exactSegment.byteLength")?;
        require_identity(&self.batch.batch_id, "batch.batchId")?;
        require_positive_wire(
            &self.batch.exact_batch.byte_length,
            "batch.exactBatch.byteLength",
        )?;
        require_positive_wire(
            &self.batch.exact_policy.byte_length,
            "batch.exactPolicy.byteLength",
        )?;
        if self.catalog_receipt.batch_id != self.batch.batch_id
            || self.catalog_receipt.batch_digest != self.batch.logical_batch_digest
            || self.catalog_receipt.store_admission_digest != self.batch.store_admission_digest
            || self.catalog_receipt.from_commit_seq != self.catalog_receipt.through_commit_seq
            || self.catalog_receipt.commit_seq != self.catalog_receipt.through_commit_seq
        {
            return Err(AdmissionError::Receipt(
                "spool/catalog logical, admission, identity, or commit closure mismatch".into(),
            ));
        }
        require_authority(&self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionPublicationReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub publication_id: String,
    pub projection_id: String,
    pub result_digest: Sha256Digest,
    pub artifact_digest: Sha256Digest,
    pub input_closure_digest: Sha256Digest,
    pub publication_digest: Sha256Digest,
    pub through_commit_seq: String,
    pub commit_seq: String,
    pub supersedes_publication_id: Option<String>,
    pub authority: String,
    pub status: OperationalStatus,
}

impl ProjectionPublicationReceiptV1 {
    /// Validates a durable projection-publication receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identities, cuts, digests, or authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            PROJECTION_PUBLICATION_RECEIPT_CONTRACT,
        )?;
        require_catalog(self.catalog_id.as_str(), self.catalog_schema.as_str())?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.publication_id, "publicationId"),
            (&self.projection_id, "projectionId"),
        ] {
            require_identity(value, field)?;
        }
        if self
            .supersedes_publication_id
            .as_deref()
            .is_some_and(|value| value == self.publication_id)
        {
            return Err(AdmissionError::Receipt(
                "publication cannot supersede itself".into(),
            ));
        }
        let through = require_positive_wire(&self.through_commit_seq, "throughCommitSeq")?;
        let commit = require_positive_wire(&self.commit_seq, "commitSeq")?;
        if through >= commit {
            return Err(AdmissionError::Receipt(
                "publication must consume only prior catalog knowledge".into(),
            ));
        }
        require_authority(&self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitPublicationReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub cockpit_publication_id: String,
    pub scene_id: String,
    pub projection_publication_id: String,
    pub projection_publication_digest: Sha256Digest,
    pub result_digest: Sha256Digest,
    pub artifact_digest: Sha256Digest,
    pub manifest_digest: Sha256Digest,
    pub cockpit_publication_digest: Sha256Digest,
    pub query_policy: String,
    pub commit_seq: String,
    pub supersedes_cockpit_publication_id: Option<String>,
    pub authority: String,
    pub status: OperationalStatus,
}

impl CockpitPublicationReceiptV1 {
    /// Validates a durable cockpit-publication receipt and its projection closure.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identities, cuts, digests, or authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            COCKPIT_PUBLICATION_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.cockpit_publication_id, "cockpitPublicationId"),
            (&self.scene_id, "sceneId"),
            (&self.projection_publication_id, "projectionPublicationId"),
            (&self.query_policy, "queryPolicy"),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.commit_seq, "commitSeq")?;
        if self
            .supersedes_cockpit_publication_id
            .as_deref()
            .is_some_and(|value| value == self.cockpit_publication_id)
        {
            return Err(AdmissionError::Receipt(
                "cockpit publication cannot supersede itself".into(),
            ));
        }
        require_authority(&self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SceneReferenceV1 {
    pub scene_id: String,
    pub view_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DurableSceneReferenceV1 {
    pub scene_id: String,
    pub view_digest: Sha256Digest,
    pub captured_commit_seq: String,
    pub scene_receipt_digest: Sha256Digest,
    pub as_of_digest: Sha256Digest,
    pub choice_universe_digest: Sha256Digest,
    pub authority_class: String,
    pub effect_ceiling: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationReferenceV1 {
    pub presentation_id: String,
    pub presentation_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationSceneReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub presentation_id: String,
    pub idempotency_key: String,
    pub assignment_id: String,
    pub scene: SceneReferenceV1,
    pub policy_digest: Sha256Digest,
    pub presentation_digest: Sha256Digest,
    pub commit_seq: String,
    pub status: OperationalStatus,
}

impl PresentationSceneReceiptV1 {
    /// Validates a durable presentation-scene receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed scene, presentation, commit, or authority fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            PRESENTATION_SCENE_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.presentation_id, "presentationId"),
            (&self.idempotency_key, "idempotencyKey"),
            (&self.assignment_id, "assignmentId"),
            (&self.scene.scene_id, "scene.sceneId"),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.commit_seq, "commitSeq").map(|_| ())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationEventReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub event_id: String,
    pub presentation: PresentationReferenceV1,
    pub scene: SceneReferenceV1,
    pub event_digest: Sha256Digest,
    pub commit_seq: String,
    pub status: OperationalStatus,
}

impl PresentationEventReceiptV1 {
    /// Validates a durable ordered presentation-event receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identities, sequence, commit, or authority fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            PRESENTATION_EVENT_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.event_id, "eventId"),
            (
                &self.presentation.presentation_id,
                "presentation.presentationId",
            ),
            (&self.scene.scene_id, "scene.sceneId"),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.commit_seq, "commitSeq").map(|_| ())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExportValidationReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub validation_id: String,
    pub snapshot_id: String,
    pub manifest_digest: Sha256Digest,
    pub rust_validation_digest: Sha256Digest,
    pub python_validation_digest: Sha256Digest,
    pub validation_digest: Sha256Digest,
    pub commit_seq: String,
    pub status: OperationalStatus,
}

impl ExportValidationReceiptV1 {
    /// Constructs the strict public V1 receipt from a post-commit store closure.
    ///
    /// # Errors
    ///
    /// Returns an error if a store digest cannot be represented on the public SHA-256 wire.
    pub fn from_store(
        value: &joshi_store::ProductionExportCommitReceipt,
    ) -> Result<Self, AdmissionError> {
        let receipt = Self {
            contract: EXPORT_VALIDATION_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            catalog_id: value.catalog_id().to_string(),
            catalog_schema: value.catalog_schema().to_string(),
            batch_id: value.batch_id().to_string(),
            validation_id: value.validation_id().to_string(),
            snapshot_id: value.snapshot_id().to_string(),
            manifest_digest: Sha256Digest::parse(value.manifest_digest().to_string())?,
            rust_validation_digest: Sha256Digest::parse(
                value.rust_validation_digest().to_string(),
            )?,
            python_validation_digest: Sha256Digest::parse(
                value.python_validation_digest().to_string(),
            )?,
            validation_digest: Sha256Digest::parse(value.validation_digest().to_string())?,
            commit_seq: value.commit_seq().get().to_string(),
            status: operational_status(value.status()),
        };
        receipt.validate()?;
        Ok(receipt)
    }

    /// Validates a production export-validation receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed digest, publication, validator, or authority closure.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            EXPORT_VALIDATION_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.validation_id, "validationId"),
            (&self.snapshot_id, "snapshotId"),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.commit_seq, "commitSeq").map(|_| ())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AnalysisArtifactImportReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub import_id: String,
    pub artifact_id: String,
    pub artifact_contract: String,
    pub artifact_digest: Sha256Digest,
    pub manifest_digest: Sha256Digest,
    pub input_snapshot_id: String,
    pub input_snapshot_digest: Sha256Digest,
    pub claim_scope: String,
    pub truth_fingerprint_before: Sha256Digest,
    pub truth_fingerprint_after: Sha256Digest,
    pub commit_seq: String,
    pub authority: String,
    pub status: OperationalStatus,
}

impl AnalysisArtifactImportReceiptV1 {
    /// Constructs the strict public V1 receipt from a post-commit store closure.
    ///
    /// The V1 wire does not echo the separately durable export-request and analysis-run IDs; those
    /// remain retained in the store receipt and V8 occurrence mapping rather than being conflated
    /// with snapshot or artifact content identities.
    ///
    /// # Errors
    ///
    /// Returns an error if a store digest cannot be represented on the public SHA-256 wire.
    pub fn from_store(
        value: &joshi_store::AnalysisArtifactCommitReceipt,
    ) -> Result<Self, AdmissionError> {
        let truth = Sha256Digest::parse(value.truth_fingerprint().to_string())?;
        let receipt = Self {
            contract: ARTIFACT_IMPORT_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            catalog_id: value.catalog_id().to_string(),
            catalog_schema: value.catalog_schema().to_string(),
            batch_id: value.batch_id().to_string(),
            import_id: value.import_id().to_string(),
            artifact_id: value.artifact_id().to_string(),
            artifact_contract: value.artifact_contract().to_string(),
            artifact_digest: Sha256Digest::parse(value.artifact_digest().to_string())?,
            manifest_digest: Sha256Digest::parse(value.manifest_digest().to_string())?,
            input_snapshot_id: value.snapshot_id().to_string(),
            input_snapshot_digest: Sha256Digest::parse(
                value.snapshot_manifest_digest().to_string(),
            )?,
            claim_scope: value.claim_scope().to_string(),
            truth_fingerprint_before: truth.clone(),
            truth_fingerprint_after: truth,
            commit_seq: value.commit_seq().get().to_string(),
            authority: AUTHORITY.into(),
            status: operational_status(value.status()),
        };
        receipt.validate()?;
        Ok(receipt)
    }

    /// Validates a derived-artifact import receipt and truth-preservation proof.
    ///
    /// # Errors
    ///
    /// Returns an error if the import is malformed or changes the truth fingerprint.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            ARTIFACT_IMPORT_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.import_id, "importId"),
            (&self.artifact_id, "artifactId"),
            (&self.artifact_contract, "artifactContract"),
            (&self.input_snapshot_id, "inputSnapshotId"),
            (&self.claim_scope, "claimScope"),
        ] {
            require_identity(value, field)?;
        }
        if self.truth_fingerprint_before != self.truth_fingerprint_after {
            return Err(AdmissionError::Receipt(
                "analysis artifact import changed the catalog truth fingerprint".into(),
            ));
        }
        require_positive_wire(&self.commit_seq, "commitSeq")?;
        require_authority(&self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceFactArtifactReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub artifact_id: String,
    pub artifact_family: String,
    pub artifact_contract: String,
    pub artifact_digest: Sha256Digest,
    pub input_closure_digest: Sha256Digest,
    pub known_through_commit_seq: String,
    pub commit_seq: String,
    pub authority: String,
    pub status: OperationalStatus,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactReferenceV1 {
    pub artifact_id: String,
    pub artifact_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationReferenceV1 {
    pub publication_id: String,
    pub publication_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationPlanReferenceV1 {
    pub policy_id: String,
    pub policy_digest: Sha256Digest,
    pub bundle_id: String,
    pub bundle_digest: Sha256Digest,
    pub assignment_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DurableReceiptReferenceV1 {
    pub receipt_id: String,
    pub receipt_digest: Sha256Digest,
    pub through_commit_seq: String,
    pub originated_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeProtocolRegistrationV1 {
    pub contract: String,
    pub schema_version: u64,
    pub protocol_registration_id: String,
    pub protocol_definition_id: String,
    pub protocol_revision: String,
    pub build_digest: Sha256Digest,
    pub configuration_digest: Sha256Digest,
    pub budget_digest: Sha256Digest,
    pub privacy_digest: Sha256Digest,
    pub duration_us: String,
    pub warmup_offset_us: String,
    pub choice_deadline_offset_us: String,
    pub outcome_horizon_offset_us: String,
    pub knowledge_deadline_offset_us: String,
    pub authority: String,
}

impl EpisodeProtocolRegistrationV1 {
    /// Validates the immutable prospective-episode protocol registration.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid identities, authority, or frozen timing formulas.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        const MINUTE_US: u64 = 60_000_000;
        const MIN_DURATION_US: u64 = 30 * MINUTE_US;
        const MAX_DURATION_US: u64 = 90 * MINUTE_US;
        const WARMUP_US: u64 = 300_000_000;
        const OUTCOME_LAG_US: u64 = 1_800_000_000;
        const KNOWLEDGE_LAG_US: u64 = 900_000_000;

        require_header(
            &self.contract,
            self.schema_version,
            EPISODE_PROTOCOL_CONTRACT,
        )?;
        require_identity(&self.protocol_registration_id, "protocolRegistrationId")?;
        require_identity(&self.protocol_definition_id, "protocolDefinitionId")?;
        require_positive_wire(&self.protocol_revision, "protocolRevision")?;
        let duration = require_positive_wire(&self.duration_us, "durationUs")?;
        let warmup = require_wire(&self.warmup_offset_us, "warmupOffsetUs")?;
        let choice =
            require_positive_wire(&self.choice_deadline_offset_us, "choiceDeadlineOffsetUs")?;
        let outcome =
            require_positive_wire(&self.outcome_horizon_offset_us, "outcomeHorizonOffsetUs")?;
        let knowledge = require_positive_wire(
            &self.knowledge_deadline_offset_us,
            "knowledgeDeadlineOffsetUs",
        )?;
        let expected_choice = duration
            .checked_mul(3)
            .ok_or_else(|| AdmissionError::Receipt("episode duration overflow".into()))?
            / 5;
        if !(MIN_DURATION_US..=MAX_DURATION_US).contains(&duration)
            || duration % MINUTE_US != 0
            || warmup != WARMUP_US
            || choice != expected_choice
            || outcome != duration.saturating_add(OUTCOME_LAG_US)
            || knowledge != outcome.saturating_add(KNOWLEDGE_LAG_US)
        {
            return Err(AdmissionError::Receipt(
                "episode protocol must use a 30-90 minute aligned duration and the frozen warmup/choice/outcome/knowledge formulas".into(),
            ));
        }
        require_authority(&self.authority)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeProtocolReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub protocol_registration_id: String,
    pub protocol_definition_id: String,
    pub protocol_revision: String,
    pub protocol_digest: Sha256Digest,
    pub commit_seq: String,
    pub committed_at: String,
    pub authority: String,
    pub status: OperationalStatus,
}

impl EpisodeProtocolReceiptV1 {
    /// Validates a durable episode-protocol receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed catalog, identity, time, commit, or authority fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            EPISODE_PROTOCOL_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        require_identity(&self.batch_id, "batchId")?;
        require_identity(&self.protocol_registration_id, "protocolRegistrationId")?;
        require_identity(&self.protocol_definition_id, "protocolDefinitionId")?;
        require_positive_wire(&self.protocol_revision, "protocolRevision")?;
        require_positive_wire(&self.commit_seq, "commitSeq")?;
        require_utc_instant(&self.committed_at, "committedAt")?;
        require_authority(&self.authority)
    }

    /// Proves that this receipt closes the exact protocol-registration bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if parsing, validation, identity, or digest closure fails.
    pub fn validate_against(
        &self,
        registration: &EpisodeProtocolRegistrationV1,
        exact_registration_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        registration.validate()?;
        let decoded: EpisodeProtocolRegistrationV1 =
            strict_json::parse(exact_registration_bytes, MAX_OPERATIONAL_RECEIPT_BYTES)?;
        if &decoded != registration
            || self.protocol_registration_id != registration.protocol_registration_id
            || self.protocol_definition_id != registration.protocol_definition_id
            || self.protocol_revision != registration.protocol_revision
            || self.protocol_digest != Sha256Digest::of_bytes(exact_registration_bytes)
        {
            return Err(AdmissionError::Receipt(
                "episode protocol receipt does not close exact registration bytes".into(),
            ));
        }
        Ok(())
    }
}

/// Strict-parses, semantically validates, and durably appends one protocol registration.
///
/// The returned receipt exists only after the exact registration bytes and frozen timing formula
/// have crossed the private store capability. This does not create a launch or pairing session.
///
/// # Errors
///
/// Returns an error for noncanonical bytes, invalid timing/identity/digest closure, identity
/// conflict, or failed durable commit.
pub fn commit_episode_protocol_registration_v1(
    store: &mut joshi_store::SqliteStore,
    registration: &EpisodeProtocolRegistrationV1,
    exact_registration_bytes: &[u8],
    context: &joshi_store::OperationalCommitContext,
) -> Result<EpisodeProtocolReceiptV1, AdmissionError> {
    registration.validate()?;
    let decoded: EpisodeProtocolRegistrationV1 =
        strict_json::parse(exact_registration_bytes, MAX_OPERATIONAL_RECEIPT_BYTES)?;
    if &decoded != registration {
        return Err(AdmissionError::Receipt(
            "episode protocol value differs from exact registration bytes".into(),
        ));
    }
    let protocol_digest = Sha256Digest::of_bytes(exact_registration_bytes);
    let capability = joshi_store::EpisodeProtocolCapability::new(
        joshi_domain::StableString::new(registration.protocol_registration_id.clone())?,
        joshi_domain::StableString::new(registration.protocol_definition_id.clone())?,
        require_positive_wire(&registration.protocol_revision, "protocolRevision")?,
        joshi_domain::ValueDigest::new(protocol_digest.to_string())?,
        exact_registration_bytes.to_vec(),
        joshi_domain::ValueDigest::new(registration.build_digest.to_string())?,
        joshi_domain::ValueDigest::new(registration.configuration_digest.to_string())?,
        joshi_domain::ValueDigest::new(registration.budget_digest.to_string())?,
        joshi_domain::ValueDigest::new(registration.privacy_digest.to_string())?,
        require_positive_wire(&registration.duration_us, "durationUs")?,
        require_wire(&registration.warmup_offset_us, "warmupOffsetUs")?,
        require_positive_wire(
            &registration.choice_deadline_offset_us,
            "choiceDeadlineOffsetUs",
        )?,
        require_positive_wire(
            &registration.outcome_horizon_offset_us,
            "outcomeHorizonOffsetUs",
        )?,
        require_positive_wire(
            &registration.knowledge_deadline_offset_us,
            "knowledgeDeadlineOffsetUs",
        )?,
    )?;
    let stored = store.commit_episode_protocol_v1(&capability, context)?;
    let receipt = EpisodeProtocolReceiptV1 {
        contract: EPISODE_PROTOCOL_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        catalog_id: stored.catalog_id().to_string(),
        catalog_schema: stored.catalog_schema().to_string(),
        batch_id: stored.batch_id().to_string(),
        protocol_registration_id: registration.protocol_registration_id.clone(),
        protocol_definition_id: registration.protocol_definition_id.clone(),
        protocol_revision: registration.protocol_revision.clone(),
        protocol_digest,
        commit_seq: stored.commit_seq().get().to_string(),
        committed_at: context.committed_at().to_string(),
        authority: AUTHORITY.into(),
        status: operational_status(stored.status()),
    };
    receipt.validate_against(registration, exact_registration_bytes)?;
    Ok(receipt)
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeLaunchRegistrationV1 {
    pub contract: String,
    pub schema_version: u64,
    pub launch_id: String,
    pub protocol_registration_id: String,
    pub prospective_session_id: String,
    pub protocol_digest: Sha256Digest,
    pub t0: String,
    pub catalog_cutoff_commit_seq: String,
    pub source_receipts: Vec<DurableReceiptReferenceV1>,
    pub census: ArtifactReferenceV1,
    pub hot_scope_intents: Vec<ArtifactReferenceV1>,
    pub projection: PublicationReferenceV1,
    pub cockpit: PublicationReferenceV1,
    pub scene: DurableSceneReferenceV1,
    pub as_of_digest: Sha256Digest,
    pub choice_universe_digest: Sha256Digest,
    pub choice_members: Vec<ChoiceMembershipReferenceV1>,
    pub presentation: PresentationPlanReferenceV1,
    pub reserved_presentation_id: String,
    pub reserved_hot_decision_id: String,
    pub reserved_hot_intent_id: String,
    pub reserved_command_id: String,
    pub reserved_command_idempotency_key: String,
    pub reserved_outcome_id: String,
    pub reserved_interview_id: String,
    pub reserved_export_request_id: String,
    pub reserved_analysis_run_id: String,
    pub reserved_artifact_import_id: String,
    pub nomination_contract: String,
    pub abstention_contract: String,
    pub outcome_contract: String,
    pub interview_contract: String,
    pub export_contract: String,
    pub authority: String,
}

impl EpisodeLaunchRegistrationV1 {
    /// Validates a preregistered prospective episode launch.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed, unordered, future-cut, or over-authoritative fields.
    #[allow(clippy::too_many_lines)]
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(&self.contract, self.schema_version, EPISODE_LAUNCH_CONTRACT)?;
        for (value, field) in [
            (&self.launch_id, "launchId"),
            (&self.protocol_registration_id, "protocolRegistrationId"),
            (&self.prospective_session_id, "prospectiveSessionId"),
            (&self.census.artifact_id, "census.artifactId"),
            (&self.projection.publication_id, "projection.publicationId"),
            (&self.cockpit.publication_id, "cockpit.publicationId"),
            (&self.scene.scene_id, "scene.sceneId"),
            (&self.presentation.policy_id, "presentation.policyId"),
            (&self.presentation.bundle_id, "presentation.bundleId"),
            (
                &self.presentation.assignment_id,
                "presentation.assignmentId",
            ),
            (&self.reserved_presentation_id, "reservedPresentationId"),
            (&self.reserved_hot_decision_id, "reservedHotDecisionId"),
            (&self.reserved_hot_intent_id, "reservedHotIntentId"),
            (&self.reserved_command_id, "reservedCommandId"),
            (
                &self.reserved_command_idempotency_key,
                "reservedCommandIdempotencyKey",
            ),
            (&self.reserved_outcome_id, "reservedOutcomeId"),
            (&self.reserved_interview_id, "reservedInterviewId"),
            (&self.reserved_export_request_id, "reservedExportRequestId"),
            (&self.reserved_analysis_run_id, "reservedAnalysisRunId"),
            (
                &self.reserved_artifact_import_id,
                "reservedArtifactImportId",
            ),
            (&self.nomination_contract, "nominationContract"),
            (&self.abstention_contract, "abstentionContract"),
            (&self.outcome_contract, "outcomeContract"),
            (&self.interview_contract, "interviewContract"),
            (&self.export_contract, "exportContract"),
        ] {
            require_identity(value, field)?;
        }
        if self.nomination_contract != PROSPECTIVE_NOMINATION_CONTRACT
            || self.abstention_contract != EXPLICIT_ABSTENTION_CONTRACT
        {
            return Err(AdmissionError::Receipt(
                "episode launch must preregister both prospective choice branches".into(),
            ));
        }
        require_utc_instant(&self.t0, "t0")?;
        if self.choice_members.is_empty()
            || self.choice_members.iter().any(|member| {
                require_identity(&member.subject_id, "choiceMembers.subjectId").is_err()
                    || member.choice_universe_digest != self.choice_universe_digest
            })
            || self
                .choice_members
                .windows(2)
                .any(|pair| pair[0].subject_id >= pair[1].subject_id)
        {
            return Err(AdmissionError::Receipt(
                "choiceMembers must be nonempty, universe-bound, and strictly subjectId-sorted"
                    .into(),
            ));
        }
        require_positive_wire(&self.scene.captured_commit_seq, "scene.capturedCommitSeq")?;
        if self.scene.authority_class != "evidence_only"
            || self.scene.effect_ceiling != "observe_only"
            || self.as_of_digest != self.scene.as_of_digest
            || self.choice_universe_digest != self.scene.choice_universe_digest
        {
            return Err(AdmissionError::Receipt(
                "episode scene must be evidence-only and close exact as-of/choice-universe digests"
                    .into(),
            ));
        }
        let cutoff =
            require_positive_wire(&self.catalog_cutoff_commit_seq, "catalogCutoffCommitSeq")?;
        if self.source_receipts.is_empty() {
            return Err(AdmissionError::Receipt(
                "sourceReceipts must be nonempty".into(),
            ));
        }
        for receipt in &self.source_receipts {
            require_identity(&receipt.receipt_id, "sourceReceipts.receiptId")?;
            require_utc_instant(&receipt.originated_at, "sourceReceipts.originatedAt")?;
            if require_positive_wire(
                &receipt.through_commit_seq,
                "sourceReceipts.throughCommitSeq",
            )? > cutoff
            {
                return Err(AdmissionError::Receipt(
                    "source receipt exceeds launch catalog cutoff".into(),
                ));
            }
        }
        if self
            .source_receipts
            .windows(2)
            .any(|pair| pair[0].receipt_id >= pair[1].receipt_id)
        {
            return Err(AdmissionError::Receipt(
                "sourceReceipts must be strictly receiptId-sorted".into(),
            ));
        }
        for intent in &self.hot_scope_intents {
            require_identity(&intent.artifact_id, "hotScopeIntents.artifactId")?;
        }
        if self
            .hot_scope_intents
            .windows(2)
            .any(|pair| pair[0].artifact_id >= pair[1].artifact_id)
        {
            return Err(AdmissionError::Receipt(
                "hotScopeIntents must be strictly artifactId-sorted".into(),
            ));
        }
        require_authority(&self.authority)
    }

    #[allow(clippy::too_many_arguments)]
    /// Resolves a launch against exact durable upstream references.
    ///
    /// # Errors
    ///
    /// Returns an error when any supplied durable receipt or closure differs.
    pub fn validate_against(
        &self,
        protocol_receipt: &EpisodeProtocolReceiptV1,
        census_receipt: &SourceFactArtifactReceiptV1,
        projection_receipt: &ProjectionPublicationReceiptV1,
        cockpit_receipt: &CockpitPublicationReceiptV1,
        durable_scene: &DurableSceneReferenceV1,
        durable_presentation_plan: &PresentationPlanReferenceV1,
        durable_source_receipts: &[DurableReceiptReferenceV1],
        durable_hot_scope_intents: &[ArtifactReferenceV1],
        durable_choice_members: &[ChoiceMembershipReferenceV1],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        protocol_receipt.validate()?;
        census_receipt.validate()?;
        projection_receipt.validate()?;
        cockpit_receipt.validate()?;
        let protocol_committed =
            require_utc_instant(&protocol_receipt.committed_at, "protocol.committedAt")?;
        if self.protocol_registration_id != protocol_receipt.protocol_registration_id
            || self.protocol_digest != protocol_receipt.protocol_digest
            || self.census.artifact_id != census_receipt.artifact_id
            || self.census.artifact_digest != census_receipt.artifact_digest
            || self.projection.publication_id != projection_receipt.publication_id
            || self.projection.publication_digest != projection_receipt.publication_digest
            || self.cockpit.publication_id != cockpit_receipt.cockpit_publication_id
            || self.cockpit.publication_digest != cockpit_receipt.cockpit_publication_digest
            || cockpit_receipt.projection_publication_id != projection_receipt.publication_id
            || cockpit_receipt.projection_publication_digest
                != projection_receipt.publication_digest
            || cockpit_receipt.result_digest != projection_receipt.result_digest
            || cockpit_receipt.artifact_digest != projection_receipt.artifact_digest
            || self.scene.scene_id != cockpit_receipt.scene_id
            || &self.scene != durable_scene
            || &self.presentation != durable_presentation_plan
            || self.source_receipts != durable_source_receipts
            || self.hot_scope_intents != durable_hot_scope_intents
            || self.choice_members != durable_choice_members
            || self.source_receipts.iter().any(|receipt| {
                match require_utc_instant(&receipt.originated_at, "sourceReceipts.originatedAt") {
                    Ok(originated) => originated <= protocol_committed,
                    Err(_) => true,
                }
            })
        {
            return Err(AdmissionError::Receipt(
                "episode launch does not close durable protocol/source/census/hot/publication/scene receipts"
                    .into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeLaunchReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub launch_id: String,
    pub launch_digest: Sha256Digest,
    pub protocol_registration_id: String,
    pub prospective_session_id: String,
    pub protocol_digest: Sha256Digest,
    pub cockpit_publication_id: String,
    pub cockpit_publication_digest: Sha256Digest,
    pub scene: DurableSceneReferenceV1,
    pub catalog_cutoff_commit_seq: String,
    pub commit_seq: String,
    pub committed_at: String,
    pub authority: String,
    pub status: OperationalStatus,
}

impl EpisodeLaunchReceiptV1 {
    /// Validates a durable episode-launch receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed catalog, identity, cut, time, or authority fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            EPISODE_LAUNCH_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.launch_id, "launchId"),
            (&self.protocol_registration_id, "protocolRegistrationId"),
            (&self.prospective_session_id, "prospectiveSessionId"),
            (&self.cockpit_publication_id, "cockpitPublicationId"),
            (&self.scene.scene_id, "scene.sceneId"),
        ] {
            require_identity(value, field)?;
        }
        let cutoff =
            require_positive_wire(&self.catalog_cutoff_commit_seq, "catalogCutoffCommitSeq")?;
        let commit = require_positive_wire(&self.commit_seq, "commitSeq")?;
        require_utc_instant(&self.committed_at, "committedAt")?;
        if cutoff >= commit {
            return Err(AdmissionError::Receipt(
                "episode launch cutoff must precede registration commit".into(),
            ));
        }
        require_authority(&self.authority)
    }

    /// Proves that this receipt closes the exact launch-registration bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if parsing, validation, identity, digest, or timing closure fails.
    pub fn validate_against(
        &self,
        registration: &EpisodeLaunchRegistrationV1,
        exact_registration_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        registration.validate()?;
        let decoded: EpisodeLaunchRegistrationV1 =
            strict_json::parse(exact_registration_bytes, MAX_OPERATIONAL_RECEIPT_BYTES)?;
        if &decoded != registration
            || self.launch_id != registration.launch_id
            || self.launch_digest != Sha256Digest::of_bytes(exact_registration_bytes)
            || self.protocol_registration_id != registration.protocol_registration_id
            || self.prospective_session_id != registration.prospective_session_id
            || self.protocol_digest != registration.protocol_digest
            || self.cockpit_publication_id != registration.cockpit.publication_id
            || self.cockpit_publication_digest != registration.cockpit.publication_digest
            || self.scene != registration.scene
            || self.catalog_cutoff_commit_seq != registration.catalog_cutoff_commit_seq
            || require_utc_instant(&self.committed_at, "committedAt")?
                >= require_utc_instant(&registration.t0, "t0")?
        {
            return Err(AdmissionError::Receipt(
                "episode launch receipt does not close exact preregistration bytes".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SessionLaunchEnvelopeV1 {
    pub contract: String,
    pub schema_version: u64,
    pub protocol: EpisodeProtocolRegistrationV1,
    pub protocol_receipt: EpisodeProtocolReceiptV1,
    pub registration: EpisodeLaunchRegistrationV1,
    pub receipt: EpisodeLaunchReceiptV1,
}

impl SessionLaunchEnvelopeV1 {
    /// Validates the no-index Glass session envelope against exact nested bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the protocol and launch receipts do not close the nested values.
    pub fn validate(
        &self,
        exact_protocol_bytes: &[u8],
        exact_registration_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        require_header(&self.contract, self.schema_version, SESSION_LAUNCH_CONTRACT)?;
        self.protocol_receipt
            .validate_against(&self.protocol, exact_protocol_bytes)?;
        self.receipt
            .validate_against(&self.registration, exact_registration_bytes)?;
        if self.registration.protocol_registration_id != self.protocol.protocol_registration_id
            || self.registration.protocol_digest != self.protocol_receipt.protocol_digest
        {
            return Err(AdmissionError::Receipt(
                "session launch protocol and launch closures differ".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExplicitAbstentionReason {
    NoAcceptableCandidate,
    InsufficientEvidence,
    RiskBoundary,
    AttentionLimit,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ClientClockV1 {
    pub clock_id: String,
    pub monotonic_ns: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChoiceMembershipReferenceV1 {
    pub subject_id: String,
    pub choice_universe_digest: Sha256Digest,
    pub membership_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProspectiveNominationCommandV1 {
    pub contract: String,
    pub schema_version: u64,
    pub nomination_id: String,
    pub idempotency_key: String,
    pub episode_launch_id: String,
    pub client_session_id: String,
    pub client_command_seq: String,
    pub subject: ChoiceMembershipReferenceV1,
    pub cockpit_publication_id: String,
    pub scene: SceneReferenceV1,
    pub presentation: PresentationReferenceV1,
    pub assignment_id: String,
    pub as_of_digest: Sha256Digest,
    pub choice_universe_digest: Sha256Digest,
    pub decision_deadline: String,
    pub issued_at: String,
    pub client_clock: ClientClockV1,
    pub authority_class: String,
    pub effect_ceiling: String,
}

impl ProspectiveNominationCommandV1 {
    /// Validates the standalone prospective-nomination syntax and authority ceiling.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identity, membership, clock, deadline, or authority fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            PROSPECTIVE_NOMINATION_CONTRACT,
        )?;
        for (value, field) in [
            (&self.nomination_id, "nominationId"),
            (&self.idempotency_key, "idempotencyKey"),
            (&self.episode_launch_id, "episodeLaunchId"),
            (&self.client_session_id, "clientSessionId"),
            (&self.subject.subject_id, "subject.subjectId"),
            (&self.cockpit_publication_id, "cockpitPublicationId"),
            (&self.scene.scene_id, "scene.sceneId"),
            (
                &self.presentation.presentation_id,
                "presentation.presentationId",
            ),
            (&self.assignment_id, "assignmentId"),
            (&self.client_clock.clock_id, "clientClock.clockId"),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.client_command_seq, "clientCommandSeq")?;
        require_wire(&self.client_clock.monotonic_ns, "clientClock.monotonicNs")?;
        let deadline = require_utc_instant(&self.decision_deadline, "decisionDeadline")?;
        let issued = require_utc_instant(&self.issued_at, "issuedAt")?;
        if issued >= deadline || self.choice_universe_digest != self.subject.choice_universe_digest
        {
            return Err(AdmissionError::Receipt(
                "prospective nomination is outside its deadline or choice universe".into(),
            ));
        }
        if self.authority_class != "evidence_only" || self.effect_ceiling != "observe_only" {
            return Err(AdmissionError::Receipt(
                "prospective nomination must remain evidence-only/observe-only".into(),
            ));
        }
        Ok(())
    }

    /// Resolves a nomination against exact launch, presentation, and membership evidence.
    ///
    /// # Errors
    ///
    /// Returns an error for any substitution or action outside the preregistered choice window.
    #[allow(clippy::too_many_arguments)]
    pub fn validate_against(
        &self,
        protocol: &EpisodeProtocolRegistrationV1,
        protocol_receipt: &EpisodeProtocolReceiptV1,
        exact_protocol_bytes: &[u8],
        launch: &EpisodeLaunchRegistrationV1,
        launch_receipt: &EpisodeLaunchReceiptV1,
        exact_launch_bytes: &[u8],
        presentation_receipt: &PresentationSceneReceiptV1,
        durable_membership: &ChoiceMembershipReferenceV1,
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        protocol_receipt.validate_against(protocol, exact_protocol_bytes)?;
        launch_receipt.validate_against(launch, exact_launch_bytes)?;
        presentation_receipt.validate()?;
        let (earliest_choice, expected_deadline) = choice_window(protocol, launch)?;
        if self.episode_launch_id != launch.launch_id
            || self.episode_launch_id != launch_receipt.launch_id
            || launch.protocol_registration_id != protocol.protocol_registration_id
            || launch.protocol_digest != protocol_receipt.protocol_digest
            || self.nomination_id != launch.reserved_command_id
            || self.idempotency_key != launch.reserved_command_idempotency_key
            || self.cockpit_publication_id != launch.cockpit.publication_id
            || self.scene.scene_id != launch.scene.scene_id
            || self.scene.view_digest != launch.scene.view_digest
            || self.presentation.presentation_id != launch.reserved_presentation_id
            || self.presentation.presentation_id != presentation_receipt.presentation_id
            || self.presentation.presentation_digest != presentation_receipt.presentation_digest
            || presentation_receipt.scene.scene_id != launch.scene.scene_id
            || presentation_receipt.scene.view_digest != launch.scene.view_digest
            || self.assignment_id != launch.presentation.assignment_id
            || self.assignment_id != presentation_receipt.assignment_id
            || self.as_of_digest != launch.as_of_digest
            || self.choice_universe_digest != launch.choice_universe_digest
            || &self.subject != durable_membership
            || !launch.choice_members.contains(&self.subject)
            || require_utc_instant(&self.decision_deadline, "decisionDeadline")?
                != expected_deadline
            || require_utc_instant(&self.issued_at, "issuedAt")? < earliest_choice
        {
            return Err(AdmissionError::Receipt(
                "prospective nomination does not close its launch, presentation, choice membership, as-of, or deadline"
                    .into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProspectiveNominationReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub nomination_id: String,
    pub episode_launch_id: String,
    pub subject: ChoiceMembershipReferenceV1,
    pub scene: SceneReferenceV1,
    pub presentation: PresentationReferenceV1,
    pub choice_universe_digest: Sha256Digest,
    pub nomination_digest: Sha256Digest,
    pub commit_seq: String,
    pub status: OperationalStatus,
}

impl ProspectiveNominationReceiptV1 {
    /// Validates a durable prospective-nomination receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identity, subject, scene, presentation, or commit fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            PROSPECTIVE_NOMINATION_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.nomination_id, "nominationId"),
            (&self.episode_launch_id, "episodeLaunchId"),
            (&self.subject.subject_id, "subject.subjectId"),
            (&self.scene.scene_id, "scene.sceneId"),
            (
                &self.presentation.presentation_id,
                "presentation.presentationId",
            ),
        ] {
            require_identity(value, field)?;
        }
        if self.subject.choice_universe_digest != self.choice_universe_digest {
            return Err(AdmissionError::Receipt(
                "nomination subject is not closed by the choice universe".into(),
            ));
        }
        require_positive_wire(&self.commit_seq, "commitSeq").map(|_| ())
    }

    /// Proves that this receipt closes the exact prospective-nomination bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if parsing, validation, identity, or digest closure fails.
    pub fn validate_against(
        &self,
        command: &ProspectiveNominationCommandV1,
        exact_command_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        command.validate()?;
        let decoded: ProspectiveNominationCommandV1 =
            strict_json::parse(exact_command_bytes, MAX_OPERATIONAL_RECEIPT_BYTES)?;
        if &decoded != command
            || self.nomination_id != command.nomination_id
            || self.episode_launch_id != command.episode_launch_id
            || self.subject != command.subject
            || self.scene != command.scene
            || self.presentation != command.presentation
            || self.choice_universe_digest != command.choice_universe_digest
            || self.nomination_digest != Sha256Digest::of_bytes(exact_command_bytes)
        {
            return Err(AdmissionError::Receipt(
                "prospective nomination receipt does not close exact command bytes".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExplicitAbstentionCommandV1 {
    pub contract: String,
    pub schema_version: u64,
    pub abstention_id: String,
    pub idempotency_key: String,
    pub episode_launch_id: String,
    pub client_session_id: String,
    pub client_command_seq: String,
    pub cockpit_publication_id: String,
    pub scene: SceneReferenceV1,
    pub presentation: PresentationReferenceV1,
    pub assignment_id: String,
    pub as_of_digest: Sha256Digest,
    pub choice_universe_digest: Sha256Digest,
    pub decision_deadline: String,
    pub reason: ExplicitAbstentionReason,
    pub issued_at: String,
    pub client_clock: ClientClockV1,
    pub authority_class: String,
    pub effect_ceiling: String,
}

impl ExplicitAbstentionCommandV1 {
    /// Validates the standalone explicit-abstention command syntax and authority ceiling.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identity, clock, deadline, or authority fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            EXPLICIT_ABSTENTION_CONTRACT,
        )?;
        for (value, field) in [
            (&self.abstention_id, "abstentionId"),
            (&self.idempotency_key, "idempotencyKey"),
            (&self.episode_launch_id, "episodeLaunchId"),
            (&self.client_session_id, "clientSessionId"),
            (&self.cockpit_publication_id, "cockpitPublicationId"),
            (&self.scene.scene_id, "scene.sceneId"),
            (
                &self.presentation.presentation_id,
                "presentation.presentationId",
            ),
            (&self.assignment_id, "assignmentId"),
            (&self.client_clock.clock_id, "clientClock.clockId"),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.client_command_seq, "clientCommandSeq")?;
        require_wire(&self.client_clock.monotonic_ns, "clientClock.monotonicNs")?;
        let deadline = require_utc_instant(&self.decision_deadline, "decisionDeadline")?;
        let issued = require_utc_instant(&self.issued_at, "issuedAt")?;
        if issued >= deadline {
            return Err(AdmissionError::Receipt(
                "explicit abstention was issued after its preregistered deadline".into(),
            ));
        }
        if self.authority_class != "evidence_only" || self.effect_ceiling != "observe_only" {
            return Err(AdmissionError::Receipt(
                "explicit abstention must remain evidence-only/observe-only".into(),
            ));
        }
        Ok(())
    }

    /// Resolves an abstention against the exact preregistered launch and presentation.
    ///
    /// # Errors
    ///
    /// Returns an error for any closure substitution or action outside the choice window.
    #[allow(clippy::too_many_arguments)]
    pub fn validate_against(
        &self,
        protocol: &EpisodeProtocolRegistrationV1,
        protocol_receipt: &EpisodeProtocolReceiptV1,
        exact_protocol_bytes: &[u8],
        launch: &EpisodeLaunchRegistrationV1,
        launch_receipt: &EpisodeLaunchReceiptV1,
        exact_launch_bytes: &[u8],
        presentation_receipt: &PresentationSceneReceiptV1,
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        protocol_receipt.validate_against(protocol, exact_protocol_bytes)?;
        launch.validate()?;
        launch_receipt.validate_against(launch, exact_launch_bytes)?;
        presentation_receipt.validate()?;
        let (earliest_choice, expected_deadline) = choice_window(protocol, launch)?;
        if self.episode_launch_id != launch.launch_id
            || self.episode_launch_id != launch_receipt.launch_id
            || launch.protocol_registration_id != protocol.protocol_registration_id
            || launch.protocol_digest != protocol_receipt.protocol_digest
            || self.abstention_id != launch.reserved_command_id
            || self.idempotency_key != launch.reserved_command_idempotency_key
            || self.cockpit_publication_id != launch.cockpit.publication_id
            || self.scene.scene_id != launch.scene.scene_id
            || self.scene.view_digest != launch.scene.view_digest
            || self.presentation.presentation_id != launch.reserved_presentation_id
            || self.presentation.presentation_id != presentation_receipt.presentation_id
            || self.presentation.presentation_digest != presentation_receipt.presentation_digest
            || presentation_receipt.scene.scene_id != launch.scene.scene_id
            || presentation_receipt.scene.view_digest != launch.scene.view_digest
            || self.assignment_id != launch.presentation.assignment_id
            || self.assignment_id != presentation_receipt.assignment_id
            || self.as_of_digest != launch.as_of_digest
            || self.choice_universe_digest != launch.choice_universe_digest
            || require_utc_instant(&self.decision_deadline, "decisionDeadline")?
                != expected_deadline
            || require_utc_instant(&self.issued_at, "issuedAt")? < earliest_choice
        {
            return Err(AdmissionError::Receipt(
                "explicit abstention does not close the preregistered launch, exact presentation, choice universe, as-of, or deadline"
                    .into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ExplicitAbstentionReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub batch_id: String,
    pub abstention_id: String,
    pub episode_launch_id: String,
    pub scene: SceneReferenceV1,
    pub presentation: PresentationReferenceV1,
    pub choice_universe_digest: Sha256Digest,
    pub abstention_digest: Sha256Digest,
    pub commit_seq: String,
    pub status: OperationalStatus,
}

impl ExplicitAbstentionReceiptV1 {
    /// Validates a durable explicit-abstention receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed identity, scene, presentation, or commit fields.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            EXPLICIT_ABSTENTION_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.abstention_id, "abstentionId"),
            (&self.episode_launch_id, "episodeLaunchId"),
            (&self.scene.scene_id, "scene.sceneId"),
            (
                &self.presentation.presentation_id,
                "presentation.presentationId",
            ),
        ] {
            require_identity(value, field)?;
        }
        require_positive_wire(&self.commit_seq, "commitSeq").map(|_| ())
    }

    /// Proves that this receipt closes the exact abstention-command bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if parsing, validation, identity, or digest closure fails.
    pub fn validate_against(
        &self,
        command: &ExplicitAbstentionCommandV1,
        exact_command_bytes: &[u8],
    ) -> Result<(), AdmissionError> {
        self.validate()?;
        command.validate()?;
        let decoded: ExplicitAbstentionCommandV1 =
            strict_json::parse(exact_command_bytes, MAX_OPERATIONAL_RECEIPT_BYTES)?;
        if &decoded != command
            || self.abstention_id != command.abstention_id
            || self.episode_launch_id != command.episode_launch_id
            || self.scene != command.scene
            || self.presentation != command.presentation
            || self.choice_universe_digest != command.choice_universe_digest
            || self.abstention_digest != Sha256Digest::of_bytes(exact_command_bytes)
        {
            return Err(AdmissionError::Receipt(
                "explicit abstention receipt does not close exact command bytes".into(),
            ));
        }
        Ok(())
    }
}

impl SourceFactArtifactReceiptV1 {
    /// Validates a source-derived fact artifact receipt.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed fields, future knowledge cuts, or excess authority.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        require_header(
            &self.contract,
            self.schema_version,
            SOURCE_FACT_ARTIFACT_RECEIPT_CONTRACT,
        )?;
        require_catalog(&self.catalog_id, &self.catalog_schema)?;
        for (value, field) in [
            (&self.batch_id, "batchId"),
            (&self.artifact_id, "artifactId"),
            (&self.artifact_family, "artifactFamily"),
            (&self.artifact_contract, "artifactContract"),
        ] {
            require_identity(value, field)?;
        }
        let cutoff =
            require_positive_wire(&self.known_through_commit_seq, "knownThroughCommitSeq")?;
        let commit = require_positive_wire(&self.commit_seq, "commitSeq")?;
        if cutoff >= commit {
            return Err(AdmissionError::Receipt(
                "source/fact artifact must consume only prior knowledge".into(),
            ));
        }
        require_authority(&self.authority)
    }
}

pub trait StrictOperationalReceipt: Sized + for<'de> Deserialize<'de> {
    /// Validates one recognized strict receipt contract.
    ///
    /// # Errors
    ///
    /// Returns an error when the receipt violates its contract-specific invariants.
    fn validate(&self) -> Result<(), AdmissionError>;
}

macro_rules! receipt_impl {
    ($($ty:ty),+ $(,)?) => {$ (
        impl StrictOperationalReceipt for $ty {
            fn validate(&self) -> Result<(), AdmissionError> {
                <$ty>::validate(self)
            }
        }
    )+ };
}

receipt_impl!(
    LocalSpoolReceiptV1,
    SpoolCatalogReceiptV1,
    ProjectionPublicationReceiptV1,
    CockpitPublicationReceiptV1,
    PresentationSceneReceiptV1,
    PresentationEventReceiptV1,
    ExportValidationReceiptV1,
    AnalysisArtifactImportReceiptV1,
    SourceFactArtifactReceiptV1,
    EpisodeProtocolReceiptV1,
    EpisodeLaunchReceiptV1,
    ProspectiveNominationReceiptV1,
    ExplicitAbstentionReceiptV1,
);

fn choice_window(
    protocol: &EpisodeProtocolRegistrationV1,
    launch: &EpisodeLaunchRegistrationV1,
) -> Result<(time::OffsetDateTime, time::OffsetDateTime), AdmissionError> {
    let t0 = require_utc_instant(&launch.t0, "launch.t0")?;
    let choice_us = require_positive_wire(
        &protocol.choice_deadline_offset_us,
        "choiceDeadlineOffsetUs",
    )?;
    let warmup_us = require_wire(&protocol.warmup_offset_us, "warmupOffsetUs")?;
    let earliest = t0
        .checked_add(time::Duration::microseconds(
            i64::try_from(warmup_us)
                .map_err(|_| AdmissionError::Receipt("warmup exceeds i64 microseconds".into()))?,
        ))
        .ok_or_else(|| AdmissionError::Receipt("warmup overflows UTC".into()))?;
    let deadline = t0
        .checked_add(time::Duration::microseconds(
            i64::try_from(choice_us).map_err(|_| {
                AdmissionError::Receipt("choice deadline exceeds i64 microseconds".into())
            })?,
        ))
        .ok_or_else(|| AdmissionError::Receipt("choice deadline overflows UTC".into()))?;
    Ok((earliest, deadline))
}

const fn operational_status(value: joshi_store::IdempotencyStatus) -> OperationalStatus {
    match value {
        joshi_store::IdempotencyStatus::Accepted => OperationalStatus::Accepted,
        joshi_store::IdempotencyStatus::Idempotent => OperationalStatus::Idempotent,
    }
}

/// Parses duplicate-aware bounded JSON and validates the selected receipt contract.
///
/// # Errors
///
/// Returns an error for oversized, duplicate-key, dangerous-key, unknown-field, malformed, or
/// semantically invalid receipt bytes.
pub fn parse_receipt<T: StrictOperationalReceipt>(bytes: &[u8]) -> Result<T, AdmissionError> {
    let receipt: T = strict_json::parse(bytes, MAX_OPERATIONAL_RECEIPT_BYTES)?;
    receipt.validate()?;
    Ok(receipt)
}

fn require_header(contract: &str, version: u64, expected: &str) -> Result<(), AdmissionError> {
    if contract == expected && version == 1 {
        Ok(())
    } else {
        Err(AdmissionError::Receipt(format!(
            "unsupported receipt header {contract}/v{version}"
        )))
    }
}

fn require_catalog(catalog_id: &str, catalog_schema: &str) -> Result<(), AdmissionError> {
    require_identity(catalog_id, "catalogId")?;
    require_identity(catalog_schema, "catalogSchema")
}

fn require_identity(value: &str, field: &str) -> Result<(), AdmissionError> {
    if !value.is_empty()
        && value.len() <= 512
        && value.trim() == value
        && !value.chars().any(char::is_control)
    {
        Ok(())
    } else {
        Err(AdmissionError::Receipt(format!(
            "{field} is not a stable identity"
        )))
    }
}

fn require_positive_wire(value: &str, field: &str) -> Result<u64, AdmissionError> {
    if value.starts_with('0') || value.bytes().any(|byte| !byte.is_ascii_digit()) {
        return Err(AdmissionError::Receipt(format!(
            "{field} is not a positive canonical u64 string"
        )));
    }
    value.parse::<u64>().map_err(|_| {
        AdmissionError::Receipt(format!("{field} is not a positive canonical u64 string"))
    })
}

fn require_wire(value: &str, field: &str) -> Result<u64, AdmissionError> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || value.bytes().any(|byte| !byte.is_ascii_digit())
    {
        return Err(AdmissionError::Receipt(format!(
            "{field} is not a canonical u64 string"
        )));
    }
    value
        .parse::<u64>()
        .map_err(|_| AdmissionError::Receipt(format!("{field} is not a canonical u64 string")))
}

fn require_utc_instant(value: &str, field: &str) -> Result<time::OffsetDateTime, AdmissionError> {
    if value.len() != 27 || !value.ends_with('Z') || value.as_bytes().get(19) != Some(&b'.') {
        return Err(AdmissionError::Receipt(format!(
            "{field} must be UTC RFC3339 with exactly six fractional digits"
        )));
    }
    let parsed = time::PrimitiveDateTime::parse(
        value,
        &time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ),
    )
    .map_err(|_| AdmissionError::Receipt(format!("{field} is not a valid UTC instant")))?;
    Ok(parsed.assume_utc())
}

fn require_authority(value: &str) -> Result<(), AdmissionError> {
    if value == AUTHORITY {
        Ok(())
    } else {
        Err(AdmissionError::Receipt(
            "operational receipt authority must be read_only_no_execution".into(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_domain::{StableString, UtcTimestamp};
    use joshi_store::{OperationalCommitContext, SqliteStore, StoreConfig, StoreMode};
    use std::{path::PathBuf, time::Duration};

    const SESSION_LAUNCH_GOLDEN: &str =
        include_str!("../../../fixtures/operational/session_launch_v1.json");

    const NOMINATION_GOLDEN: &str = concat!(
        "{\"contract\":\"joshi.operator.prospective_nomination\",\"schemaVersion\":1,",
        "\"nominationId\":\"command-reservation-1\",\"idempotencyKey\":\"command-key-1\",",
        "\"episodeLaunchId\":\"launch-1\",\"clientSessionId\":\"session-1\",",
        "\"clientCommandSeq\":\"1\",\"subject\":{\"subjectId\":\"asset:coin-a\",",
        "\"choiceUniverseDigest\":\"sha256:1111111111111111111111111111111111111111111111111111111111111111\",",
        "\"membershipDigest\":\"sha256:2222222222222222222222222222222222222222222222222222222222222222\"},",
        "\"cockpitPublicationId\":\"cockpit-1\",\"scene\":{\"sceneId\":\"scene-1\",",
        "\"viewDigest\":\"sha256:3333333333333333333333333333333333333333333333333333333333333333\"},",
        "\"presentation\":{\"presentationId\":\"presentation-1\",",
        "\"presentationDigest\":\"sha256:4444444444444444444444444444444444444444444444444444444444444444\"},",
        "\"assignmentId\":\"assignment-1\",",
        "\"asOfDigest\":\"sha256:5555555555555555555555555555555555555555555555555555555555555555\",",
        "\"choiceUniverseDigest\":\"sha256:1111111111111111111111111111111111111111111111111111111111111111\",",
        "\"decisionDeadline\":\"2026-08-17T13:41:00.000000Z\",",
        "\"issuedAt\":\"2026-08-17T13:10:00.000000Z\",",
        "\"clientClock\":{\"clockId\":\"glass-session-1\",\"monotonicNs\":\"9000\"},",
        "\"authorityClass\":\"evidence_only\",\"effectCeiling\":\"observe_only\"}"
    );
    const NOMINATION_RECEIPT_GOLDEN: &str = concat!(
        "{\"contract\":\"joshi.store.prospective_nomination_receipt\",\"schemaVersion\":1,",
        "\"catalogId\":\"catalog-v7\",\"catalogSchema\":\"joshi.sqlite.v7\",",
        "\"batchId\":\"nomination-batch-1\",\"nominationId\":\"command-reservation-1\",",
        "\"episodeLaunchId\":\"launch-1\",\"subject\":{\"subjectId\":\"asset:coin-a\",",
        "\"choiceUniverseDigest\":\"sha256:1111111111111111111111111111111111111111111111111111111111111111\",",
        "\"membershipDigest\":\"sha256:2222222222222222222222222222222222222222222222222222222222222222\"},",
        "\"scene\":{\"sceneId\":\"scene-1\",",
        "\"viewDigest\":\"sha256:3333333333333333333333333333333333333333333333333333333333333333\"},",
        "\"presentation\":{\"presentationId\":\"presentation-1\",",
        "\"presentationDigest\":\"sha256:4444444444444444444444444444444444444444444444444444444444444444\"},",
        "\"choiceUniverseDigest\":\"sha256:1111111111111111111111111111111111111111111111111111111111111111\",",
        "\"nominationDigest\":\"sha256:e1826827d4b2629b88e9b51af1d84cc3afffeb7bb07e7a756a758894556a320e\",",
        "\"commitSeq\":\"44\",\"status\":\"accepted\"}"
    );

    fn digest(value: u8) -> Sha256Digest {
        Sha256Digest::parse(format!("sha256:{}", format!("{value:02x}").repeat(32)))
            .expect("digest")
    }

    fn stable(value: &str) -> StableString {
        StableString::new(value).expect("stable test identity")
    }

    fn workspace() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(std::path::Path::parent)
            .expect("workspace root")
            .to_owned()
    }

    #[test]
    fn prospective_nomination_cross_language_golden_is_exact() {
        let command: ProspectiveNominationCommandV1 =
            strict_json::parse(NOMINATION_GOLDEN.as_bytes(), MAX_OPERATIONAL_RECEIPT_BYTES)
                .expect("strict nomination golden");
        command.validate().expect("valid nomination golden");
        assert_eq!(
            serde_json::to_vec(&command).expect("serialize nomination"),
            NOMINATION_GOLDEN.as_bytes()
        );
        assert_eq!(
            Sha256Digest::of_bytes(NOMINATION_GOLDEN.as_bytes()).as_str(),
            "sha256:e1826827d4b2629b88e9b51af1d84cc3afffeb7bb07e7a756a758894556a320e"
        );
        let receipt: ProspectiveNominationReceiptV1 = strict_json::parse(
            NOMINATION_RECEIPT_GOLDEN.as_bytes(),
            MAX_OPERATIONAL_RECEIPT_BYTES,
        )
        .expect("strict nomination receipt golden");
        receipt
            .validate_against(&command, NOMINATION_GOLDEN.as_bytes())
            .expect("receipt closes nomination golden");
        assert_eq!(
            serde_json::to_vec(&receipt).expect("serialize nomination receipt"),
            NOMINATION_RECEIPT_GOLDEN.as_bytes()
        );
        assert_eq!(
            Sha256Digest::of_bytes(NOMINATION_RECEIPT_GOLDEN.as_bytes()).as_str(),
            "sha256:7dd5ce90b1a5ae882f81570c0b7adae5d9216302365616b5e1110a66b85b96a3"
        );
    }

    #[test]
    fn session_launch_cross_language_golden_closes_exact_nested_bytes() {
        let exact = SESSION_LAUNCH_GOLDEN.trim_end().as_bytes();
        let envelope: SessionLaunchEnvelopeV1 =
            strict_json::parse(exact, MAX_OPERATIONAL_RECEIPT_BYTES)
                .expect("strict session launch golden");
        let protocol_bytes = serde_json::to_vec(&envelope.protocol).expect("protocol bytes");
        let launch_bytes = serde_json::to_vec(&envelope.registration).expect("launch bytes");
        envelope
            .validate(&protocol_bytes, &launch_bytes)
            .expect("session launch closes nested bytes");
        assert_eq!(
            serde_json::to_vec(&envelope).expect("session envelope bytes"),
            exact
        );
        assert_eq!(
            Sha256Digest::of_bytes(&protocol_bytes).as_str(),
            "sha256:e0ba94b70025608d151a77e983d9a4099dc8aeb19bb282cac94d33ef44569c63"
        );
        assert_eq!(
            Sha256Digest::of_bytes(&launch_bytes).as_str(),
            "sha256:43372761a889a26422ca6a24fa84d42530ec8c48ca1a1fb7ea79c12f14b8d881"
        );
        assert_eq!(
            Sha256Digest::of_bytes(exact).as_str(),
            "sha256:589610ad2d07fd9a60763bf1cf82834d2c755716141e454bfef2ada41a1b152a"
        );
    }

    #[test]
    fn protocol_admission_commits_exact_bytes_and_survives_restart() {
        let exact = SESSION_LAUNCH_GOLDEN.trim_end().as_bytes();
        let envelope: SessionLaunchEnvelopeV1 =
            strict_json::parse(exact, MAX_OPERATIONAL_RECEIPT_BYTES).expect("session envelope");
        let protocol_bytes = serde_json::to_vec(&envelope.protocol).expect("protocol bytes");
        let temporary = tempfile::tempdir().expect("temporary catalog root");
        std::fs::copy(
            workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
            temporary.path().join("catalog.sqlite"),
        )
        .expect("copy V8 catalog");
        let config = StoreConfig {
            catalog_path: temporary.path().join("catalog.sqlite"),
            blob_root: temporary.path().join("blobs"),
            export_root: temporary.path().join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable("catalog-publication-test"),
            max_observations_per_batch: 16,
            max_raw_bytes_per_batch: 1024 * 1024,
        };
        let context = OperationalCommitContext::new(
            stable("protocol-store-batch-001"),
            "2026-08-17T12:01:00.000000Z"
                .parse::<UtcTimestamp>()
                .expect("commit timestamp"),
            stable("protocol-test-clock"),
            1,
            stable("protocol-test-build"),
        );
        let mut store =
            SqliteStore::open(config.clone(), StoreMode::SingleWriter).expect("open writer");
        let accepted = commit_episode_protocol_registration_v1(
            &mut store,
            &envelope.protocol,
            &protocol_bytes,
            &context,
        )
        .expect("commit protocol");
        assert_eq!(accepted.status, OperationalStatus::Accepted);
        accepted
            .validate_against(&envelope.protocol, &protocol_bytes)
            .expect("accepted receipt closes bytes");
        let retry = commit_episode_protocol_registration_v1(
            &mut store,
            &envelope.protocol,
            &protocol_bytes,
            &context,
        )
        .expect("retry protocol");
        assert_eq!(retry.status, OperationalStatus::Idempotent);
        drop(store);

        let store = SqliteStore::open(config, StoreMode::ReadOnly).expect("reopen reader");
        let retained = store
            .load_episode_protocol_v1(&stable(&envelope.protocol.protocol_registration_id))
            .expect("load protocol")
            .expect("retained protocol");
        assert_eq!(retained.protocol_bytes, protocol_bytes);
        assert_eq!(
            retained.protocol_digest.to_string(),
            accepted.protocol_digest.to_string()
        );

        let mut changed = envelope.protocol.clone();
        changed.duration_us = "3599000000".into();
        let changed_bytes = serde_json::to_vec(&changed).expect("changed bytes");
        assert!(changed.validate().is_err());
        assert_ne!(changed_bytes, retained.protocol_bytes);
    }

    #[test]
    fn publication_receipt_rejects_future_cut_and_digest_domain_substitution() {
        let receipt = ProjectionPublicationReceiptV1 {
            contract: PROJECTION_PUBLICATION_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            catalog_id: "catalog-v7".into(),
            catalog_schema: "joshi.sqlite.v7".into(),
            batch_id: "publication-batch-1".into(),
            publication_id: "publication-1".into(),
            projection_id: "projection-1".into(),
            result_digest: digest(1),
            artifact_digest: digest(2),
            input_closure_digest: digest(3),
            publication_digest: digest(4),
            through_commit_seq: "4".into(),
            commit_seq: "5".into(),
            supersedes_publication_id: None,
            authority: AUTHORITY.into(),
            status: OperationalStatus::Accepted,
        };
        receipt.validate().expect("valid receipt");
        let mut future = receipt.clone();
        future.through_commit_seq = "5".into();
        assert!(future.validate().is_err());
        assert_ne!(receipt.result_digest, receipt.artifact_digest);
        assert_ne!(receipt.artifact_digest, receipt.publication_digest);
    }

    #[test]
    fn strict_parser_rejects_unknown_duplicate_and_dangerous_keys() {
        let value = LocalSpoolReceiptV1 {
            contract: LOCAL_SPOOL_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            segment_id: "segment-1".into(),
            protection_domain: "public-chain".into(),
            protection_class: PublicProtectionClass::PublicIntegrity,
            exact_segment: ExactByteClosureV1 {
                digest: digest(1),
                byte_length: "9".into(),
            },
            status: OperationalStatus::Accepted,
            authority: AUTHORITY.into(),
        };
        let exact = serde_json::to_vec(&value).expect("receipt bytes");
        assert_eq!(
            parse_receipt::<LocalSpoolReceiptV1>(&exact).ok(),
            Some(value)
        );
        let unknown = String::from_utf8(exact.clone())
            .expect("utf8")
            .replace("\"authority\"", "\"extra\":true,\"authority\"");
        assert!(parse_receipt::<LocalSpoolReceiptV1>(unknown.as_bytes()).is_err());
        let duplicate = String::from_utf8(exact.clone()).expect("utf8").replacen(
            '{',
            "{\"contract\":\"duplicate\",",
            1,
        );
        assert!(parse_receipt::<LocalSpoolReceiptV1>(duplicate.as_bytes()).is_err());
        let dangerous =
            String::from_utf8(exact)
                .expect("utf8")
                .replacen('{', "{\"__proto__\":{},", 1);
        assert!(parse_receipt::<LocalSpoolReceiptV1>(dangerous.as_bytes()).is_err());
    }

    #[test]
    fn analysis_receipt_requires_truth_fingerprint_stability() {
        let mut receipt = AnalysisArtifactImportReceiptV1 {
            contract: ARTIFACT_IMPORT_RECEIPT_CONTRACT.into(),
            schema_version: 1,
            catalog_id: "catalog-v7".into(),
            catalog_schema: "joshi.sqlite.v7".into(),
            batch_id: "artifact-import-batch".into(),
            import_id: "import-1".into(),
            artifact_id: "artifact-1".into(),
            artifact_contract: "joshi.analysis.kernel".into(),
            artifact_digest: digest(1),
            manifest_digest: digest(2),
            input_snapshot_id: "snapshot-1".into(),
            input_snapshot_digest: digest(3),
            claim_scope: "descriptive_noncausal".into(),
            truth_fingerprint_before: digest(4),
            truth_fingerprint_after: digest(4),
            commit_seq: "9".into(),
            authority: AUTHORITY.into(),
            status: OperationalStatus::Accepted,
        };
        receipt.validate().expect("stable truth fingerprint");
        receipt.truth_fingerprint_after = digest(5);
        assert!(receipt.validate().is_err());
    }
}
