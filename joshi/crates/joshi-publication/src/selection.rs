//! Immutable publication queries and explicit fresh/stale/unsupported selection states.

use joshi_domain::{CommitSeq, StableString, ValueDigest, WireU64};
use joshi_projection::ProjectionAuthority;
use serde::{Deserialize, Serialize};

use crate::{
    PROJECTION_SELECTION_CONTRACT, PUBLICATION_SCHEMA_VERSION, ProjectionPublicationId,
    ProjectionPublicationV1, PublicationError,
    model::{digest_json, digest_match, stable, validate_sha256, zero_digest},
};

/// Exact immutable projection-publication lookup. There is intentionally no `Latest` variant.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProjectionPublicationQueryV1 {
    /// Load one exact append-only publication identity.
    PublicationId {
        publication_id: ProjectionPublicationId,
    },
    /// Load one exact immutable publication-body digest.
    PublicationDigest { publication_digest: ValueDigest },
    /// Load the publication that registered these exact serialized artifact bytes.
    ArtifactDigest { artifact_digest: ValueDigest },
    /// Load the publication that names this exact calculator result digest.
    ResultDigest { result_digest: ValueDigest },
}

impl ProjectionPublicationQueryV1 {
    /// Validates digest forms carried by immutable lookup variants.
    ///
    /// # Errors
    ///
    /// Refuses a non-SHA-256 digest wire form.
    pub fn validate(&self) -> Result<(), PublicationError> {
        match self {
            Self::PublicationId { .. } => Ok(()),
            Self::PublicationDigest { publication_digest } => validate_sha256(publication_digest),
            Self::ArtifactDigest { artifact_digest } => validate_sha256(artifact_digest),
            Self::ResultDigest { result_digest } => validate_sha256(result_digest),
        }
    }

    /// Checks an exact loaded publication against this immutable query.
    ///
    /// # Errors
    ///
    /// Refuses a query/body mismatch or invalid publication.
    pub fn validate_loaded(
        &self,
        publication: &ProjectionPublicationV1,
    ) -> Result<(), PublicationError> {
        self.validate()?;
        publication.validate()?;
        let matches = match self {
            Self::PublicationId { publication_id } => publication_id == &publication.publication_id,
            Self::PublicationDigest { publication_digest } => {
                publication_digest == &publication.publication_digest
            }
            Self::ArtifactDigest { artifact_digest } => {
                artifact_digest == &publication.artifact_digest
            }
            Self::ResultDigest { result_digest } => result_digest == &publication.result_digest,
        };
        if matches {
            Ok(())
        } else {
            Err(PublicationError::QueryMismatch)
        }
    }
}

/// Compact immutable pointer retained by a cockpit or selection response.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionPublicationPointerV1 {
    pub publication_id: ProjectionPublicationId,
    pub publication_digest: ValueDigest,
    pub projection_id: StableString,
    pub result_digest: ValueDigest,
    pub artifact_digest: ValueDigest,
    pub input_closure_digest: ValueDigest,
    pub through_commit_seq: CommitSeq,
    pub publication_commit_seq: CommitSeq,
}

impl ProjectionPublicationPointerV1 {
    /// Builds a pointer only from a valid immutable publication.
    ///
    /// # Errors
    ///
    /// Refuses invalid publication semantics.
    pub fn from_publication(value: &ProjectionPublicationV1) -> Result<Self, PublicationError> {
        value.validate()?;
        Ok(Self {
            publication_id: value.publication_id.clone(),
            publication_digest: value.publication_digest.clone(),
            projection_id: value.projection_id.clone(),
            result_digest: value.result_digest.clone(),
            artifact_digest: value.artifact_digest.clone(),
            input_closure_digest: value.input_closure_digest.clone(),
            through_commit_seq: value.through_commit_seq,
            publication_commit_seq: value.publication_commit_seq,
        })
    }

    fn validate(&self) -> Result<(), PublicationError> {
        validate_sha256(&self.publication_digest)?;
        validate_sha256(&self.result_digest)?;
        validate_sha256(&self.artifact_digest)?;
        validate_sha256(&self.input_closure_digest)?;
        if self.publication_commit_seq <= self.through_commit_seq {
            return Err(PublicationError::CommitOrder);
        }
        Ok(())
    }
}

/// Durable lookup result supplied to the named query-policy selector.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProjectionSelectionInput {
    /// One committed publication was selected by the durable query policy.
    Found(ProjectionPublicationV1),
    /// No publication exists for the requested scope/cutoff.
    Missing { reason: StableString },
    /// The current projection cannot be produced; a prior immutable publication may remain.
    Unsupported {
        reason: StableString,
        prior: Option<ProjectionPublicationV1>,
    },
    /// The durable policy returned multiple unresolved immutable candidates.
    Conflicting {
        reason: StableString,
        candidates: Vec<ProjectionPublicationV1>,
    },
}

/// Explicit publication state. Missingness and unsupported state never become numeric values.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProjectionSelectionStateV1 {
    /// Publication closes exactly at the requested finalized knowledge cutoff.
    Fresh {
        publication: ProjectionPublicationPointerV1,
    },
    /// A complete immutable prior publication remains usable only with visible lag.
    Stale {
        publication: ProjectionPublicationPointerV1,
        lag_commits: WireU64,
        reason: StableString,
    },
    /// Current construction/query semantics are unsupported at the requested cutoff.
    Unsupported {
        prior: Option<ProjectionPublicationPointerV1>,
        reason: StableString,
    },
    /// No immutable publication exists under the named query policy.
    Missing { reason: StableString },
    /// Multiple durable candidates remain unresolved and none is silently selected.
    Conflicting {
        candidates: Vec<ProjectionPublicationPointerV1>,
        reason: StableString,
    },
}

/// Deterministic response of one named durable query policy at an explicit cutoff.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionSelectionV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub query_policy: StableString,
    pub requested_through_commit_seq: CommitSeq,
    pub evaluated_at_catalog_commit_seq: CommitSeq,
    pub state: ProjectionSelectionStateV1,
    pub authority: ProjectionAuthority,
    pub selection_digest: ValueDigest,
}

impl ProjectionSelectionV1 {
    /// Revalidates selection ordering, explicit state, and canonical digest.
    ///
    /// # Errors
    ///
    /// Refuses later-known candidates, malformed conflicts, or digest mismatch.
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != PROJECTION_SELECTION_CONTRACT
            || self.schema_version != PUBLICATION_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
            || self.evaluated_at_catalog_commit_seq < self.requested_through_commit_seq
        {
            return Err(PublicationError::Contract);
        }
        validate_selection_state(
            &self.state,
            self.requested_through_commit_seq,
            self.evaluated_at_catalog_commit_seq,
        )?;
        validate_sha256(&self.selection_digest)?;
        let computed = selection_digest(self)?;
        digest_match("selection", &self.selection_digest, &computed)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SelectionDigestMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    query_policy: &'a StableString,
    requested_through_commit_seq: CommitSeq,
    evaluated_at_catalog_commit_seq: CommitSeq,
    state: &'a ProjectionSelectionStateV1,
    authority: ProjectionAuthority,
}

fn selection_digest(value: &ProjectionSelectionV1) -> Result<ValueDigest, PublicationError> {
    digest_json(&SelectionDigestMaterial {
        contract: &value.contract,
        schema_version: value.schema_version,
        query_policy: &value.query_policy,
        requested_through_commit_seq: value.requested_through_commit_seq,
        evaluated_at_catalog_commit_seq: value.evaluated_at_catalog_commit_seq,
        state: &value.state,
        authority: value.authority,
    })
}

/// Selects a publication without consulting process-local state or an unversioned latest pointer.
///
/// # Errors
///
/// Refuses a candidate from later knowledge, invalid publication, malformed conflict set, or
/// impossible evaluated/requested ordering.
pub fn select_projection_publication(
    query_policy: StableString,
    requested_through_commit_seq: CommitSeq,
    evaluated_at_catalog_commit_seq: CommitSeq,
    input: ProjectionSelectionInput,
) -> Result<ProjectionSelectionV1, PublicationError> {
    if evaluated_at_catalog_commit_seq < requested_through_commit_seq {
        return Err(PublicationError::CommitOrder);
    }
    let state = match input {
        ProjectionSelectionInput::Found(value) => {
            let pointer = checked_pointer(
                &value,
                requested_through_commit_seq,
                evaluated_at_catalog_commit_seq,
            )?;
            if pointer.through_commit_seq == requested_through_commit_seq {
                ProjectionSelectionStateV1::Fresh {
                    publication: pointer,
                }
            } else {
                ProjectionSelectionStateV1::Stale {
                    lag_commits: WireU64::new(
                        requested_through_commit_seq.get() - pointer.through_commit_seq.get(),
                    ),
                    publication: pointer,
                    reason: stable("publication_precedes_requested_cutoff"),
                }
            }
        }
        ProjectionSelectionInput::Missing { reason } => {
            ProjectionSelectionStateV1::Missing { reason }
        }
        ProjectionSelectionInput::Unsupported { reason, prior } => {
            let prior = prior
                .as_ref()
                .map(|value| {
                    checked_pointer(
                        value,
                        requested_through_commit_seq,
                        evaluated_at_catalog_commit_seq,
                    )
                })
                .transpose()?;
            ProjectionSelectionStateV1::Unsupported { prior, reason }
        }
        ProjectionSelectionInput::Conflicting { reason, candidates } => {
            let mut pointers = candidates
                .iter()
                .map(|value| {
                    checked_pointer(
                        value,
                        requested_through_commit_seq,
                        evaluated_at_catalog_commit_seq,
                    )
                })
                .collect::<Result<Vec<_>, _>>()?;
            pointers.sort_by(|left, right| left.publication_id.cmp(&right.publication_id));
            if pointers.len() < 2
                || pointers
                    .windows(2)
                    .any(|window| window[0].publication_id >= window[1].publication_id)
            {
                return Err(PublicationError::ConflictCandidates);
            }
            ProjectionSelectionStateV1::Conflicting {
                candidates: pointers,
                reason,
            }
        }
    };
    let mut value = ProjectionSelectionV1 {
        contract: stable(PROJECTION_SELECTION_CONTRACT),
        schema_version: PUBLICATION_SCHEMA_VERSION,
        query_policy,
        requested_through_commit_seq,
        evaluated_at_catalog_commit_seq,
        state,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        selection_digest: zero_digest()?,
    };
    value.selection_digest = selection_digest(&value)?;
    value.validate()?;
    Ok(value)
}

/// Returns exact schema-ordered compact JSON selection bytes.
///
/// # Errors
///
/// Refuses invalid selection semantics or JSON serialization failure.
pub fn projection_selection_bytes(
    value: &ProjectionSelectionV1,
) -> Result<Vec<u8>, PublicationError> {
    value.validate()?;
    serde_json::to_vec(value).map_err(PublicationError::from)
}

fn checked_pointer(
    value: &ProjectionPublicationV1,
    requested: CommitSeq,
    evaluated: CommitSeq,
) -> Result<ProjectionPublicationPointerV1, PublicationError> {
    value.validate()?;
    if value.through_commit_seq > requested || value.publication_commit_seq > evaluated {
        return Err(PublicationError::LaterKnowledge);
    }
    ProjectionPublicationPointerV1::from_publication(value)
}

fn validate_selection_state(
    state: &ProjectionSelectionStateV1,
    requested: CommitSeq,
    evaluated: CommitSeq,
) -> Result<(), PublicationError> {
    let validate_pointer = |value: &ProjectionPublicationPointerV1| {
        value.validate()?;
        if value.through_commit_seq > requested || value.publication_commit_seq > evaluated {
            return Err(PublicationError::LaterKnowledge);
        }
        Ok(())
    };
    match state {
        ProjectionSelectionStateV1::Fresh { publication } => {
            validate_pointer(publication)?;
            if publication.through_commit_seq != requested {
                return Err(PublicationError::CommitOrder);
            }
        }
        ProjectionSelectionStateV1::Stale {
            publication,
            lag_commits,
            ..
        } => {
            validate_pointer(publication)?;
            let lag = requested
                .get()
                .checked_sub(publication.through_commit_seq.get())
                .ok_or(PublicationError::LaterKnowledge)?;
            if lag == 0 || lag_commits.get() != lag {
                return Err(PublicationError::CommitOrder);
            }
        }
        ProjectionSelectionStateV1::Unsupported { prior, .. } => {
            if let Some(prior) = prior {
                validate_pointer(prior)?;
            }
        }
        ProjectionSelectionStateV1::Missing { .. } => {}
        ProjectionSelectionStateV1::Conflicting { candidates, .. } => {
            if candidates.len() < 2
                || candidates
                    .windows(2)
                    .any(|window| window[0].publication_id >= window[1].publication_id)
            {
                return Err(PublicationError::ConflictCandidates);
            }
            for candidate in candidates {
                validate_pointer(candidate)?;
            }
        }
    }
    Ok(())
}
