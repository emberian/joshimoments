//! Durable store port and prepare/commit/head orchestration.

use std::error::Error;

use joshi_projection::ProjectionArtifactV1;
use thiserror::Error;

use crate::{
    CockpitPublicationDraft, CockpitPublicationReceiptV1, CockpitPublicationV1, PreparedProjection,
    PreparedProjectionArtifactReceiptV1, ProjectionPublicationDraft, ProjectionPublicationQueryV1,
    ProjectionPublicationReceiptV1, ProjectionPublicationV1, PublicationError,
    finalize_cockpit_publication, prepare_projection, validate_prepared_artifact_receipt,
    validate_publication_against_prepared,
};

/// Projection publication plus durable receipt returned after one atomic catalog commit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedProjectionPublicationV1 {
    pub publication: ProjectionPublicationV1,
    pub receipt: ProjectionPublicationReceiptV1,
}

/// Cockpit publication plus durable receipt returned after a later append-only head commit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedCockpitPublicationV1 {
    pub publication: CockpitPublicationV1,
    pub receipt: CockpitPublicationReceiptV1,
}

/// Exact immutable publication and artifact bytes loaded through one explicit query.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoadedProjectionPublicationV1 {
    pub publication: ProjectionPublicationV1,
    pub artifact: ProjectionArtifactV1,
    pub artifact_bytes: Vec<u8>,
}

impl LoadedProjectionPublicationV1 {
    /// Revalidates query identity, artifact bytes, publication metadata, and every digest.
    ///
    /// # Errors
    ///
    /// Refuses query substitution, mutated bytes, or publication/artifact disagreement.
    pub fn validate(&self, query: &ProjectionPublicationQueryV1) -> Result<(), PublicationError> {
        query.validate_loaded(&self.publication)?;
        let prepared = prepare_projection(self.artifact.clone())?;
        if prepared.bytes() != self.artifact_bytes {
            return Err(PublicationError::PreparedArtifact);
        }
        validate_publication_against_prepared(&self.publication, &prepared)
    }
}

/// Store-owned implementation boundary for durable exact projection publication.
///
/// Implementations must fsync and verify CAS bytes before `prepare_projection_artifact` returns;
/// commit checkpoint and publication in one `SQLite` transaction; append the cockpit publication in
/// a later transaction only after exact scene and publication foreign keys resolve; and query
/// immutable objects by the supplied identity/digest. No method means “latest”.
pub trait ProjectionPublicationStore {
    /// Store-specific failure with no financial or execution authority.
    type Error: Error + Send + Sync + 'static;

    /// Durably prepares and read-verifies exact content-addressed artifact bytes outside SQL.
    ///
    /// # Errors
    ///
    /// Returns the adapter's error if write, sync, readback, or verification cannot complete.
    fn prepare_projection_artifact(
        &mut self,
        prepared: &PreparedProjection,
    ) -> Result<PreparedProjectionArtifactReceiptV1, Self::Error>;

    /// Atomically commits the checkpoint and immutable publication, allocating catalog commit.
    ///
    /// # Errors
    ///
    /// Returns the adapter's error if exact validation or the atomic catalog commit fails.
    fn commit_projection_publication(
        &mut self,
        prepared: &PreparedProjection,
        prepared_receipt: &PreparedProjectionArtifactReceiptV1,
        draft: ProjectionPublicationDraft,
        previous: Option<&ProjectionPublicationV1>,
    ) -> Result<CommittedProjectionPublicationV1, Self::Error>;

    /// Appends a cockpit head only after its exact scene and projection publication are durable.
    ///
    /// # Errors
    ///
    /// Returns the adapter's error if a referenced row is absent or the append cannot commit.
    fn append_cockpit_publication(
        &mut self,
        draft: CockpitPublicationDraft,
        projection: &ProjectionPublicationV1,
        previous: Option<&CockpitPublicationV1>,
    ) -> Result<CommittedCockpitPublicationV1, Self::Error>;

    /// Loads immutable publication and artifact bytes through an exact ID/digest query.
    ///
    /// # Errors
    ///
    /// Returns the adapter's error if the immutable query or artifact read cannot complete.
    fn load_projection_publication(
        &self,
        query: &ProjectionPublicationQueryV1,
    ) -> Result<Option<LoadedProjectionPublicationV1>, Self::Error>;
}

/// Contract or store failure during publication orchestration.
#[derive(Debug, Error)]
pub enum PublishPortError<E: Error + 'static> {
    /// Pure exact-contract failure before or after store I/O.
    #[error(transparent)]
    Contract(#[from] PublicationError),
    /// Durable adapter failure at the current explicit stage.
    #[error("durable publication store failure")]
    Store(#[source] E),
}

/// Prepares exact bytes and commits one immutable publication/checkpoint transaction.
///
/// This deliberately stops before cockpit-head append. A crash leaves either no committed new
/// publication or a complete new publication queryable by ID/digest while the prior head remains.
///
/// # Errors
///
/// Returns exact-contract or durable-store failure without manufacturing a partial receipt.
pub fn publish_projection<S: ProjectionPublicationStore>(
    store: &mut S,
    artifact: ProjectionArtifactV1,
    draft: ProjectionPublicationDraft,
    previous: Option<&ProjectionPublicationV1>,
) -> Result<CommittedProjectionPublicationV1, PublishPortError<S::Error>> {
    let prepared = prepare_projection(artifact)?;
    let prepared_receipt = store
        .prepare_projection_artifact(&prepared)
        .map_err(PublishPortError::Store)?;
    validate_prepared_artifact_receipt(&prepared, &prepared_receipt)?;
    let committed = store
        .commit_projection_publication(&prepared, &prepared_receipt, draft, previous)
        .map_err(PublishPortError::Store)?;
    validate_publication_against_prepared(&committed.publication, &prepared)?;
    committed.receipt.validate_against(&committed.publication)?;
    Ok(committed)
}

/// Appends a later immutable cockpit publication naming exact durable projection and scene state.
///
/// # Errors
///
/// Returns contract or durable-store failure; the prior append-only head remains selected on
/// failure.
pub fn append_cockpit_head<S: ProjectionPublicationStore>(
    store: &mut S,
    draft: CockpitPublicationDraft,
    projection: &ProjectionPublicationV1,
    previous: Option<&CockpitPublicationV1>,
) -> Result<CommittedCockpitPublicationV1, PublishPortError<S::Error>> {
    projection.validate()?;
    let committed = store
        .append_cockpit_publication(draft, projection, previous)
        .map_err(PublishPortError::Store)?;
    committed.publication.validate()?;
    committed.receipt.validate_against(&committed.publication)?;
    if committed.publication.projection_publication_id != projection.publication_id
        || committed.publication.projection_publication_digest != projection.publication_digest
        || committed.publication.result_digest != projection.result_digest
        || committed.publication.artifact_digest != projection.artifact_digest
    {
        return Err(PublicationError::ProjectionMismatch.into());
    }
    Ok(committed)
}

/// Loads and revalidates an immutable publication by exact identity or digest.
///
/// # Errors
///
/// Returns store failure or refuses any loaded-byte/query/digest mismatch.
pub fn load_projection_publication<S: ProjectionPublicationStore>(
    store: &S,
    query: &ProjectionPublicationQueryV1,
) -> Result<Option<LoadedProjectionPublicationV1>, PublishPortError<S::Error>> {
    query.validate()?;
    let loaded = store
        .load_projection_publication(query)
        .map_err(PublishPortError::Store)?;
    if let Some(value) = &loaded {
        value.validate(query)?;
    }
    Ok(loaded)
}

/// Store helper for adapters that allocate a cockpit commit inside their transaction.
///
/// Kept as a re-exporting wrapper so store code only needs the public port module.
///
/// # Errors
///
/// Returns the same exact contract failures as [`finalize_cockpit_publication`].
pub fn finalize_store_cockpit_publication(
    draft: CockpitPublicationDraft,
    projection: &ProjectionPublicationV1,
    context: crate::PublicationCommitContext,
    previous: Option<&CockpitPublicationV1>,
) -> Result<CockpitPublicationV1, PublicationError> {
    finalize_cockpit_publication(draft, projection, context, previous)
}
