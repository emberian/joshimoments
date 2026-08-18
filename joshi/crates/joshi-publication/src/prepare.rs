//! Exact projection-byte preparation and immutable publication finalization.

use joshi_domain::{ValueDigest, WireU64};
use joshi_projection::{ProjectionArtifactV1, ProjectionAuthority, projection_bytes};

use crate::{
    PROJECTION_PUBLICATION_CONTRACT, PUBLICATION_SCHEMA_VERSION,
    PreparedProjectionArtifactReceiptV1, ProjectionCheckpointV1, ProjectionPublicationDraft,
    ProjectionPublicationV1, PublicationCommitContext, PublicationError,
    model::{
        digest_json, digest_match, new_checkpoint, publication_digest, sha256_digest, stable,
        zero_digest,
    },
};

/// Validated exact financial artifact bytes ready for a durable CAS prepare.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedProjection {
    artifact: ProjectionArtifactV1,
    bytes: Vec<u8>,
    checkpoint: ProjectionCheckpointV1,
}

/// Checks that a CAS preparation receipt names the exact prepared bytes.
///
/// # Errors
///
/// Refuses storage, projection, result, byte-digest, or byte-length substitution.
pub fn validate_prepared_artifact_receipt(
    prepared: &PreparedProjection,
    receipt: &PreparedProjectionArtifactReceiptV1,
) -> Result<(), PublicationError> {
    prepared.validate()?;
    receipt.validate()?;
    if receipt.projection_id != prepared.artifact().projection_id
        || receipt.result_digest != prepared.artifact().result_digest
        || receipt.artifact_digest != *prepared.artifact_digest()
        || receipt.artifact_bytes != prepared.checkpoint().artifact_bytes
    {
        return Err(PublicationError::PreparedArtifact);
    }
    Ok(())
}

impl PreparedProjection {
    /// Exact validated financial projection.
    #[must_use]
    pub const fn artifact(&self) -> &ProjectionArtifactV1 {
        &self.artifact
    }

    /// Exact schema-ordered compact artifact bytes.
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// SHA-256 digest of exact serialized artifact bytes.
    #[must_use]
    pub const fn artifact_digest(&self) -> &ValueDigest {
        &self.checkpoint.artifact_digest
    }

    /// SHA-256 digest of the exact serialized projection input closure.
    #[must_use]
    pub const fn input_closure_digest(&self) -> &ValueDigest {
        &self.checkpoint.input_closure_digest
    }

    /// Immutable resume checkpoint committed atomically with a publication row.
    #[must_use]
    pub const fn checkpoint(&self) -> &ProjectionCheckpointV1 {
        &self.checkpoint
    }

    /// Revalidates artifact bytes and every prepared digest.
    ///
    /// # Errors
    ///
    /// Refuses mutated bytes, artifact/checkpoint disagreement, or invalid projection semantics.
    pub fn validate(&self) -> Result<(), PublicationError> {
        self.artifact.validate()?;
        self.checkpoint.validate()?;
        let exact = projection_bytes(&self.artifact)?;
        if exact != self.bytes {
            return Err(PublicationError::PreparedArtifact);
        }
        let byte_length =
            u64::try_from(self.bytes.len()).map_err(|_| PublicationError::ByteLength)?;
        if self.checkpoint.projection_id != self.artifact.projection_id
            || self.checkpoint.calculator_build != self.artifact.calculator_build
            || self.checkpoint.result_digest != self.artifact.result_digest
            || self.checkpoint.artifact_bytes != WireU64::new(byte_length)
            || self.checkpoint.from_commit_seq != self.artifact.input.from_commit_seq
            || self.checkpoint.through_commit_seq != self.artifact.input.through_commit_seq
        {
            return Err(PublicationError::ProjectionMismatch);
        }
        let artifact_digest = sha256_digest(&self.bytes);
        digest_match(
            "artifact bytes",
            &self.checkpoint.artifact_digest,
            &artifact_digest,
        )?;
        let input_digest = digest_json(&self.artifact.input)?;
        digest_match(
            "input closure",
            &self.checkpoint.input_closure_digest,
            &input_digest,
        )
    }
}

/// Validates and prepares one exact finalized financial artifact for durable storage.
///
/// Preparation performs no I/O. A store port must fsync and read back these bytes before returning
/// a prepared-artifact receipt.
///
/// # Errors
///
/// Refuses invalid projection semantics, serialization failure, or a byte length beyond u64.
pub fn prepare_projection(
    artifact: ProjectionArtifactV1,
) -> Result<PreparedProjection, PublicationError> {
    let bytes = projection_bytes(&artifact)?;
    let byte_length = u64::try_from(bytes.len()).map_err(|_| PublicationError::ByteLength)?;
    let artifact_digest = sha256_digest(&bytes);
    let input_closure_digest = digest_json(&artifact.input)?;
    let checkpoint = new_checkpoint(
        &artifact,
        artifact_digest,
        WireU64::new(byte_length),
        input_closure_digest,
    )?;
    let value = PreparedProjection {
        artifact,
        bytes,
        checkpoint,
    };
    value.validate()?;
    Ok(value)
}

/// Finalizes the immutable publication body inside a catalog-owned commit transaction.
///
/// The exact checkpoint and returned publication must be inserted atomically. Retry status belongs
/// to the separate durable receipt and never changes these bytes.
///
/// # Errors
///
/// Refuses invalid prepared bytes, commit ordering, or supersession/projection lineage mismatch.
pub fn finalize_projection_publication(
    prepared: &PreparedProjection,
    draft: ProjectionPublicationDraft,
    context: PublicationCommitContext,
    previous: Option<&ProjectionPublicationV1>,
) -> Result<ProjectionPublicationV1, PublicationError> {
    prepared.validate()?;
    let artifact = prepared.artifact();
    if context.commit_seq <= artifact.input.through_commit_seq {
        return Err(PublicationError::CommitOrder);
    }
    match previous {
        Some(prior)
            if draft.supersedes_publication_id.as_ref() == Some(&prior.publication_id)
                && artifact.supersedes_projection_id.as_ref() == Some(&prior.projection_id)
                && prior.catalog_id == context.catalog_id
                && prior.catalog_schema == context.catalog_schema
                && prior.publication_commit_seq < context.commit_seq
                && prior.through_commit_seq <= artifact.input.through_commit_seq
                && prior.publication_id != draft.publication_id =>
        {
            prior.validate()?;
        }
        None if draft.supersedes_publication_id.is_none()
            && artifact.supersedes_projection_id.is_none() => {}
        _ => return Err(PublicationError::Supersession),
    }
    let mut value = ProjectionPublicationV1 {
        contract: stable(PROJECTION_PUBLICATION_CONTRACT),
        schema_version: PUBLICATION_SCHEMA_VERSION,
        catalog_id: context.catalog_id,
        catalog_schema: context.catalog_schema,
        batch_id: draft.batch_id,
        publication_id: draft.publication_id,
        projection_id: artifact.projection_id.clone(),
        projection_contract: artifact.contract.clone(),
        projection_schema_version: artifact.schema_version,
        calculator_build: artifact.calculator_build.clone(),
        result_digest: artifact.result_digest.clone(),
        artifact_digest: prepared.artifact_digest().clone(),
        artifact_bytes: prepared.checkpoint().artifact_bytes,
        input_closure_digest: prepared.input_closure_digest().clone(),
        input: artifact.input.clone(),
        from_commit_seq: artifact.input.from_commit_seq,
        through_commit_seq: artifact.input.through_commit_seq,
        checkpoint_digest: prepared.checkpoint().checkpoint_digest.clone(),
        publication_commit_seq: context.commit_seq,
        supersedes_publication_id: draft.supersedes_publication_id,
        finality: crate::PublicationFinality::Finalized,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        publication_digest: zero_digest()?,
    };
    value.publication_digest = publication_digest(&value)?;
    value.validate()?;
    validate_publication_against_prepared(&value, prepared)?;
    Ok(value)
}

/// Checks that an immutable publication names exactly one prepared artifact and checkpoint.
///
/// # Errors
///
/// Refuses result/artifact/closure/checkpoint substitution or projection metadata drift.
pub fn validate_publication_against_prepared(
    publication: &ProjectionPublicationV1,
    prepared: &PreparedProjection,
) -> Result<(), PublicationError> {
    publication.validate()?;
    prepared.validate()?;
    let artifact = prepared.artifact();
    if publication.projection_id != artifact.projection_id
        || publication.calculator_build != artifact.calculator_build
        || publication.result_digest != artifact.result_digest
        || publication.artifact_digest != *prepared.artifact_digest()
        || publication.artifact_bytes != prepared.checkpoint().artifact_bytes
        || publication.input_closure_digest != *prepared.input_closure_digest()
        || publication.input != artifact.input
        || publication.checkpoint_digest != prepared.checkpoint().checkpoint_digest
        || publication.from_commit_seq != artifact.input.from_commit_seq
        || publication.through_commit_seq != artifact.input.through_commit_seq
    {
        return Err(PublicationError::ProjectionMismatch);
    }
    Ok(())
}
