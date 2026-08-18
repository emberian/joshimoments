//! Immutable checkpoint, publication, head, and durable-receipt DTOs.

use joshi_domain::{CommitSeq, SceneId, StableString, ValueDigest, WireU64};
use joshi_projection::{
    PROJECTION_CONTRACT, PROJECTION_SCHEMA_VERSION, ProjectionArtifactV1, ProjectionAuthority,
    ProjectionInputClosure,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    COCKPIT_PUBLICATION_CONTRACT, COCKPIT_PUBLICATION_RECEIPT_CONTRACT, CockpitPublicationId,
    PREPARED_ARTIFACT_CONTRACT, PROJECTION_CHECKPOINT_CONTRACT, PROJECTION_PUBLICATION_CONTRACT,
    PROJECTION_PUBLICATION_RECEIPT_CONTRACT, PUBLICATION_SCHEMA_VERSION, ProjectionPublicationId,
    PublicationError,
};

/// Financial finality admitted by the durable V1 projection publisher.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PublicationFinality {
    /// Landed accounting and its chain watermark are finalized.
    Finalized,
}

/// Whether a durable idempotency identity created a new append-only row.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PublicationCommitStatus {
    /// A new immutable object committed.
    Accepted,
    /// Exact immutable bytes already existed for the same identity.
    Idempotent,
}

/// Immutable resume checkpoint committed atomically beside a projection publication.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionCheckpointV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub projection_id: StableString,
    pub calculator_build: StableString,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub artifact_bytes: WireU64,
    pub input_closure_digest: ValueDigest,
    pub from_commit_seq: CommitSeq,
    pub through_commit_seq: CommitSeq,
    pub finality: PublicationFinality,
    pub authority: ProjectionAuthority,
    pub checkpoint_digest: ValueDigest,
}

impl ProjectionCheckpointV1 {
    /// Revalidates the closed V1 checkpoint and its self-declared digest.
    ///
    /// # Errors
    ///
    /// Refuses malformed contracts, digests, ordering, or digest material.
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != PROJECTION_CHECKPOINT_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.finality != PublicationFinality::Finalized
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
            || self.from_commit_seq > self.through_commit_seq
        {
            return Err(PublicationError::Contract);
        }
        validate_sha256(&self.result_digest)?;
        validate_sha256(&self.artifact_digest)?;
        validate_sha256(&self.input_closure_digest)?;
        validate_sha256(&self.checkpoint_digest)?;
        let computed = checkpoint_digest(self)?;
        digest_match("checkpoint", &self.checkpoint_digest, &computed)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CheckpointDigestMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    projection_id: &'a StableString,
    calculator_build: &'a StableString,
    result_digest: &'a ValueDigest,
    artifact_digest: &'a ValueDigest,
    artifact_bytes: WireU64,
    input_closure_digest: &'a ValueDigest,
    from_commit_seq: CommitSeq,
    through_commit_seq: CommitSeq,
    finality: PublicationFinality,
    authority: ProjectionAuthority,
}

fn checkpoint_digest(value: &ProjectionCheckpointV1) -> Result<ValueDigest, PublicationError> {
    digest_json(&CheckpointDigestMaterial {
        contract: &value.contract,
        schema_version: value.schema_version,
        projection_id: &value.projection_id,
        calculator_build: &value.calculator_build,
        result_digest: &value.result_digest,
        artifact_digest: &value.artifact_digest,
        artifact_bytes: value.artifact_bytes,
        input_closure_digest: &value.input_closure_digest,
        from_commit_seq: value.from_commit_seq,
        through_commit_seq: value.through_commit_seq,
        finality: value.finality,
        authority: value.authority,
    })
}

/// Exact CAS preparation receipt. It is not a catalog admission or publication receipt.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreparedProjectionArtifactReceiptV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub storage_id: joshi_domain::BlobId,
    pub projection_id: StableString,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub artifact_bytes: WireU64,
    pub authority: ProjectionAuthority,
}

impl PreparedProjectionArtifactReceiptV1 {
    /// Creates the exact receipt a durable CAS adapter must return after fsync and readback.
    ///
    /// # Errors
    ///
    /// Refuses an invalid digest-derived blob identity.
    pub fn new(
        projection_id: StableString,
        result_digest: ValueDigest,
        artifact_digest: ValueDigest,
        artifact_bytes: WireU64,
    ) -> Result<Self, PublicationError> {
        let storage_id = joshi_domain::BlobId::new(artifact_digest.to_string())
            .map_err(|error| PublicationError::Identity(error.to_string()))?;
        let value = Self {
            contract: stable(PREPARED_ARTIFACT_CONTRACT),
            schema_version: PUBLICATION_SCHEMA_VERSION,
            storage_id,
            projection_id,
            result_digest,
            artifact_digest,
            artifact_bytes,
            authority: ProjectionAuthority::ReadOnlyNoExecution,
        };
        value.validate()?;
        Ok(value)
    }

    /// Validates the CAS receipt's closed contract and digest identity.
    ///
    /// # Errors
    ///
    /// Refuses contract, digest, or storage-identity substitution.
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != PREPARED_ARTIFACT_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::Contract);
        }
        validate_sha256(&self.result_digest)?;
        validate_sha256(&self.artifact_digest)?;
        if self.storage_id.as_str() != self.artifact_digest.as_str() {
            return Err(PublicationError::PreparedArtifact);
        }
        Ok(())
    }
}

/// Caller-chosen immutable publication identity and idempotency/supersession intent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProjectionPublicationDraft {
    pub batch_id: StableString,
    pub publication_id: ProjectionPublicationId,
    pub supersedes_publication_id: Option<ProjectionPublicationId>,
}

/// Catalog-owned context allocated inside the durable publication transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublicationCommitContext {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub commit_seq: CommitSeq,
}

/// Immutable exact projection publication. Receipt retry status is deliberately outside it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionPublicationV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub publication_id: ProjectionPublicationId,
    pub projection_id: StableString,
    pub projection_contract: StableString,
    pub projection_schema_version: u16,
    pub calculator_build: StableString,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub artifact_bytes: WireU64,
    pub input_closure_digest: ValueDigest,
    pub input: ProjectionInputClosure,
    pub from_commit_seq: CommitSeq,
    pub through_commit_seq: CommitSeq,
    pub checkpoint_digest: ValueDigest,
    pub publication_commit_seq: CommitSeq,
    pub supersedes_publication_id: Option<ProjectionPublicationId>,
    pub finality: PublicationFinality,
    pub authority: ProjectionAuthority,
    pub publication_digest: ValueDigest,
}

impl ProjectionPublicationV1 {
    /// Revalidates the immutable publication and its self-declared digest.
    ///
    /// # Errors
    ///
    /// Refuses contract, closure, ordering, digest, or finality defects.
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != PROJECTION_PUBLICATION_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.projection_contract.as_str() != PROJECTION_CONTRACT
            || self.projection_schema_version != PROJECTION_SCHEMA_VERSION
            || self.finality != PublicationFinality::Finalized
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::Contract);
        }
        self.input
            .validate()
            .map_err(joshi_projection::ProjectionError::from)?;
        if self.from_commit_seq != self.input.from_commit_seq
            || self.through_commit_seq != self.input.through_commit_seq
            || self.publication_commit_seq <= self.through_commit_seq
        {
            return Err(PublicationError::CommitOrder);
        }
        validate_sha256(&self.result_digest)?;
        validate_sha256(&self.artifact_digest)?;
        validate_sha256(&self.input_closure_digest)?;
        validate_sha256(&self.checkpoint_digest)?;
        validate_sha256(&self.publication_digest)?;
        let input_digest = digest_json(&self.input)?;
        digest_match("input closure", &self.input_closure_digest, &input_digest)?;
        let computed = publication_digest(self)?;
        digest_match("publication", &self.publication_digest, &computed)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PublicationDigestMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    catalog_id: &'a StableString,
    catalog_schema: &'a StableString,
    batch_id: &'a StableString,
    publication_id: &'a ProjectionPublicationId,
    projection_id: &'a StableString,
    projection_contract: &'a StableString,
    projection_schema_version: u16,
    calculator_build: &'a StableString,
    result_digest: &'a ValueDigest,
    artifact_digest: &'a ValueDigest,
    artifact_bytes: WireU64,
    input_closure_digest: &'a ValueDigest,
    input: &'a ProjectionInputClosure,
    from_commit_seq: CommitSeq,
    through_commit_seq: CommitSeq,
    checkpoint_digest: &'a ValueDigest,
    publication_commit_seq: CommitSeq,
    supersedes_publication_id: &'a Option<ProjectionPublicationId>,
    finality: PublicationFinality,
    authority: ProjectionAuthority,
}

pub(crate) fn publication_digest(
    value: &ProjectionPublicationV1,
) -> Result<ValueDigest, PublicationError> {
    digest_json(&PublicationDigestMaterial {
        contract: &value.contract,
        schema_version: value.schema_version,
        catalog_id: &value.catalog_id,
        catalog_schema: &value.catalog_schema,
        batch_id: &value.batch_id,
        publication_id: &value.publication_id,
        projection_id: &value.projection_id,
        projection_contract: &value.projection_contract,
        projection_schema_version: value.projection_schema_version,
        calculator_build: &value.calculator_build,
        result_digest: &value.result_digest,
        artifact_digest: &value.artifact_digest,
        artifact_bytes: value.artifact_bytes,
        input_closure_digest: &value.input_closure_digest,
        input: &value.input,
        from_commit_seq: value.from_commit_seq,
        through_commit_seq: value.through_commit_seq,
        checkpoint_digest: &value.checkpoint_digest,
        publication_commit_seq: value.publication_commit_seq,
        supersedes_publication_id: &value.supersedes_publication_id,
        finality: value.finality,
        authority: value.authority,
    })
}

/// Durable store receipt for one exact projection-publication commit or exact retry.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionPublicationReceiptV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub publication_id: ProjectionPublicationId,
    pub projection_id: StableString,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub input_closure_digest: ValueDigest,
    pub publication_digest: ValueDigest,
    pub through_commit_seq: CommitSeq,
    pub commit_seq: CommitSeq,
    pub supersedes_publication_id: Option<ProjectionPublicationId>,
    pub authority: ProjectionAuthority,
    pub status: PublicationCommitStatus,
}

impl ProjectionPublicationReceiptV1 {
    /// Constructs the exact durable receipt after commit or exact readback.
    #[must_use]
    pub fn from_publication(
        value: &ProjectionPublicationV1,
        status: PublicationCommitStatus,
    ) -> Self {
        Self {
            contract: stable(PROJECTION_PUBLICATION_RECEIPT_CONTRACT),
            schema_version: PUBLICATION_SCHEMA_VERSION,
            catalog_id: value.catalog_id.clone(),
            catalog_schema: value.catalog_schema.clone(),
            batch_id: value.batch_id.clone(),
            publication_id: value.publication_id.clone(),
            projection_id: value.projection_id.clone(),
            result_digest: value.result_digest.clone(),
            artifact_digest: value.artifact_digest.clone(),
            input_closure_digest: value.input_closure_digest.clone(),
            publication_digest: value.publication_digest.clone(),
            through_commit_seq: value.through_commit_seq,
            commit_seq: value.publication_commit_seq,
            supersedes_publication_id: value.supersedes_publication_id.clone(),
            authority: value.authority,
            status,
        }
    }

    /// Checks that a receipt echoes its immutable publication without digest substitution.
    ///
    /// # Errors
    ///
    /// Refuses any mismatched receipt field.
    pub fn validate_against(
        &self,
        publication: &ProjectionPublicationV1,
    ) -> Result<(), PublicationError> {
        publication.validate()?;
        if self.contract.as_str() != PROJECTION_PUBLICATION_RECEIPT_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.catalog_id != publication.catalog_id
            || self.catalog_schema != publication.catalog_schema
            || self.batch_id != publication.batch_id
            || self.publication_id != publication.publication_id
            || self.projection_id != publication.projection_id
            || self.result_digest != publication.result_digest
            || self.artifact_digest != publication.artifact_digest
            || self.input_closure_digest != publication.input_closure_digest
            || self.publication_digest != publication.publication_digest
            || self.through_commit_seq != publication.through_commit_seq
            || self.commit_seq != publication.publication_commit_seq
            || self.supersedes_publication_id != publication.supersedes_publication_id
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::ReceiptMismatch);
        }
        Ok(())
    }
}

/// Caller-chosen scene/head identity before the catalog assigns its append commit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CockpitPublicationDraft {
    pub batch_id: StableString,
    pub cockpit_publication_id: CockpitPublicationId,
    pub scene_id: SceneId,
    pub manifest_digest: ValueDigest,
    pub query_policy: StableString,
    pub supersedes_cockpit_publication_id: Option<CockpitPublicationId>,
}

/// Append-only cockpit head naming one exact scene and one committed financial publication.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitPublicationV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub cockpit_publication_id: CockpitPublicationId,
    pub scene_id: SceneId,
    pub projection_publication_id: ProjectionPublicationId,
    pub projection_publication_digest: ValueDigest,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub manifest_digest: ValueDigest,
    pub query_policy: StableString,
    pub commit_seq: CommitSeq,
    pub supersedes_cockpit_publication_id: Option<CockpitPublicationId>,
    pub authority: ProjectionAuthority,
    pub cockpit_publication_digest: ValueDigest,
}

impl CockpitPublicationV1 {
    /// Revalidates the append-only cockpit publication and its self-declared digest.
    ///
    /// # Errors
    ///
    /// Refuses contract, digest, authority, or empty-policy defects.
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != COCKPIT_PUBLICATION_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::Contract);
        }
        validate_sha256(&self.projection_publication_digest)?;
        validate_sha256(&self.result_digest)?;
        validate_sha256(&self.artifact_digest)?;
        validate_sha256(&self.manifest_digest)?;
        validate_sha256(&self.cockpit_publication_digest)?;
        let computed = cockpit_digest(self)?;
        digest_match(
            "cockpit publication",
            &self.cockpit_publication_digest,
            &computed,
        )
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CockpitDigestMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    catalog_id: &'a StableString,
    catalog_schema: &'a StableString,
    batch_id: &'a StableString,
    cockpit_publication_id: &'a CockpitPublicationId,
    scene_id: &'a SceneId,
    projection_publication_id: &'a ProjectionPublicationId,
    projection_publication_digest: &'a ValueDigest,
    result_digest: &'a ValueDigest,
    artifact_digest: &'a ValueDigest,
    manifest_digest: &'a ValueDigest,
    query_policy: &'a StableString,
    commit_seq: CommitSeq,
    supersedes_cockpit_publication_id: &'a Option<CockpitPublicationId>,
    authority: ProjectionAuthority,
}

fn cockpit_digest(value: &CockpitPublicationV1) -> Result<ValueDigest, PublicationError> {
    digest_json(&CockpitDigestMaterial {
        contract: &value.contract,
        schema_version: value.schema_version,
        catalog_id: &value.catalog_id,
        catalog_schema: &value.catalog_schema,
        batch_id: &value.batch_id,
        cockpit_publication_id: &value.cockpit_publication_id,
        scene_id: &value.scene_id,
        projection_publication_id: &value.projection_publication_id,
        projection_publication_digest: &value.projection_publication_digest,
        result_digest: &value.result_digest,
        artifact_digest: &value.artifact_digest,
        manifest_digest: &value.manifest_digest,
        query_policy: &value.query_policy,
        commit_seq: value.commit_seq,
        supersedes_cockpit_publication_id: &value.supersedes_cockpit_publication_id,
        authority: value.authority,
    })
}

/// Durable store receipt for one append-only cockpit publication or exact retry.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitPublicationReceiptV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub cockpit_publication_id: CockpitPublicationId,
    pub scene_id: SceneId,
    pub projection_publication_id: ProjectionPublicationId,
    pub projection_publication_digest: ValueDigest,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub manifest_digest: ValueDigest,
    pub cockpit_publication_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub supersedes_cockpit_publication_id: Option<CockpitPublicationId>,
    pub query_policy: StableString,
    pub authority: ProjectionAuthority,
    pub status: PublicationCommitStatus,
}

impl CockpitPublicationReceiptV1 {
    /// Constructs a durable cockpit receipt after commit or exact readback.
    #[must_use]
    pub fn from_publication(value: &CockpitPublicationV1, status: PublicationCommitStatus) -> Self {
        Self {
            contract: stable(COCKPIT_PUBLICATION_RECEIPT_CONTRACT),
            schema_version: PUBLICATION_SCHEMA_VERSION,
            catalog_id: value.catalog_id.clone(),
            catalog_schema: value.catalog_schema.clone(),
            batch_id: value.batch_id.clone(),
            cockpit_publication_id: value.cockpit_publication_id.clone(),
            scene_id: value.scene_id.clone(),
            projection_publication_id: value.projection_publication_id.clone(),
            projection_publication_digest: value.projection_publication_digest.clone(),
            result_digest: value.result_digest.clone(),
            artifact_digest: value.artifact_digest.clone(),
            manifest_digest: value.manifest_digest.clone(),
            cockpit_publication_digest: value.cockpit_publication_digest.clone(),
            commit_seq: value.commit_seq,
            supersedes_cockpit_publication_id: value.supersedes_cockpit_publication_id.clone(),
            query_policy: value.query_policy.clone(),
            authority: value.authority,
            status,
        }
    }

    /// Checks that the durable receipt exactly echoes its cockpit publication.
    ///
    /// # Errors
    ///
    /// Refuses any mismatched field.
    pub fn validate_against(
        &self,
        publication: &CockpitPublicationV1,
    ) -> Result<(), PublicationError> {
        publication.validate()?;
        if self.contract.as_str() != COCKPIT_PUBLICATION_RECEIPT_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.catalog_id != publication.catalog_id
            || self.catalog_schema != publication.catalog_schema
            || self.batch_id != publication.batch_id
            || self.cockpit_publication_id != publication.cockpit_publication_id
            || self.scene_id != publication.scene_id
            || self.projection_publication_id != publication.projection_publication_id
            || self.projection_publication_digest != publication.projection_publication_digest
            || self.result_digest != publication.result_digest
            || self.artifact_digest != publication.artifact_digest
            || self.manifest_digest != publication.manifest_digest
            || self.cockpit_publication_digest != publication.cockpit_publication_digest
            || self.commit_seq != publication.commit_seq
            || self.supersedes_cockpit_publication_id
                != publication.supersedes_cockpit_publication_id
            || self.query_policy != publication.query_policy
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::ReceiptMismatch);
        }
        Ok(())
    }
}

/// Creates one append-only cockpit publication after its projection publication is durable.
///
/// The store adapter must additionally prove that the exact scene and projection publication rows
/// exist before inserting this object.
///
/// # Errors
///
/// Refuses a non-advancing commit, wrong catalog, broken head supersession, or malformed digest.
pub fn finalize_cockpit_publication(
    draft: CockpitPublicationDraft,
    projection: &ProjectionPublicationV1,
    context: PublicationCommitContext,
    previous: Option<&CockpitPublicationV1>,
) -> Result<CockpitPublicationV1, PublicationError> {
    projection.validate()?;
    validate_sha256(&draft.manifest_digest)?;
    if context.catalog_id != projection.catalog_id
        || context.catalog_schema != projection.catalog_schema
        || context.commit_seq <= projection.publication_commit_seq
    {
        return Err(PublicationError::CommitOrder);
    }
    match previous {
        Some(prior)
            if draft.supersedes_cockpit_publication_id.as_ref()
                == Some(&prior.cockpit_publication_id)
                && prior.catalog_id == context.catalog_id
                && prior.query_policy == draft.query_policy
                && prior.commit_seq < context.commit_seq => {}
        None if draft.supersedes_cockpit_publication_id.is_none() => {}
        _ => return Err(PublicationError::Supersession),
    }
    let mut value = CockpitPublicationV1 {
        contract: stable(COCKPIT_PUBLICATION_CONTRACT),
        schema_version: PUBLICATION_SCHEMA_VERSION,
        catalog_id: context.catalog_id,
        catalog_schema: context.catalog_schema,
        batch_id: draft.batch_id,
        cockpit_publication_id: draft.cockpit_publication_id,
        scene_id: draft.scene_id,
        projection_publication_id: projection.publication_id.clone(),
        projection_publication_digest: projection.publication_digest.clone(),
        result_digest: projection.result_digest.clone(),
        artifact_digest: projection.artifact_digest.clone(),
        manifest_digest: draft.manifest_digest,
        query_policy: draft.query_policy,
        commit_seq: context.commit_seq,
        supersedes_cockpit_publication_id: draft.supersedes_cockpit_publication_id,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        cockpit_publication_digest: zero_digest()?,
    };
    value.cockpit_publication_digest = cockpit_digest(&value)?;
    value.validate()?;
    Ok(value)
}

/// Returns exact schema-ordered compact JSON bytes for an immutable publication.
///
/// # Errors
///
/// Refuses invalid publication semantics or JSON serialization failure.
pub fn projection_publication_bytes(
    value: &ProjectionPublicationV1,
) -> Result<Vec<u8>, PublicationError> {
    value.validate()?;
    serde_json::to_vec(value).map_err(PublicationError::from)
}

/// Returns exact schema-ordered compact JSON bytes for an append-only cockpit publication.
///
/// # Errors
///
/// Refuses invalid head semantics or JSON serialization failure.
pub fn cockpit_publication_bytes(
    value: &CockpitPublicationV1,
) -> Result<Vec<u8>, PublicationError> {
    value.validate()?;
    serde_json::to_vec(value).map_err(PublicationError::from)
}

pub(crate) fn new_checkpoint(
    artifact: &ProjectionArtifactV1,
    artifact_digest: ValueDigest,
    artifact_bytes: WireU64,
    input_closure_digest: ValueDigest,
) -> Result<ProjectionCheckpointV1, PublicationError> {
    let mut value = ProjectionCheckpointV1 {
        contract: stable(PROJECTION_CHECKPOINT_CONTRACT),
        schema_version: PUBLICATION_SCHEMA_VERSION,
        projection_id: artifact.projection_id.clone(),
        calculator_build: artifact.calculator_build.clone(),
        result_digest: artifact.result_digest.clone(),
        artifact_digest,
        artifact_bytes,
        input_closure_digest,
        from_commit_seq: artifact.input.from_commit_seq,
        through_commit_seq: artifact.input.through_commit_seq,
        finality: PublicationFinality::Finalized,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        checkpoint_digest: zero_digest()?,
    };
    value.checkpoint_digest = checkpoint_digest(&value)?;
    value.validate()?;
    Ok(value)
}

pub(crate) fn stable(value: &str) -> StableString {
    StableString::new(value).expect("static publication contract value is valid")
}

pub(crate) fn zero_digest() -> Result<ValueDigest, PublicationError> {
    ValueDigest::new(format!("sha256:{}", "0".repeat(64)))
        .map_err(|error| PublicationError::Identity(error.to_string()))
}

pub(crate) fn digest_json(value: &impl Serialize) -> Result<ValueDigest, PublicationError> {
    let bytes = serde_json::to_vec(value)?;
    Ok(sha256_digest(&bytes))
}

pub(crate) fn sha256_digest(bytes: &[u8]) -> ValueDigest {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .expect("fixed SHA-256 wire identity is a stable string")
}

pub(crate) fn validate_sha256(value: &ValueDigest) -> Result<(), PublicationError> {
    let text = value.as_str();
    if text.len() != 71
        || !text.starts_with("sha256:")
        || !text[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(PublicationError::DigestFormat(text.to_owned()));
    }
    Ok(())
}

pub(crate) fn digest_match(
    field: &'static str,
    declared: &ValueDigest,
    computed: &ValueDigest,
) -> Result<(), PublicationError> {
    if declared == computed {
        Ok(())
    } else {
        Err(PublicationError::DigestMismatch {
            field,
            declared: declared.to_string(),
            computed: computed.to_string(),
        })
    }
}
