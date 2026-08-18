//! Exact fixture artifact-DAG contracts.

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use serde::{Deserialize, Serialize};

use crate::{
    ARTIFACT_DAG_CONTRACT, ProgramAuthorityV1, RegistryError, Result, SemanticCeilingV1,
    Wave6ProgramRegistrationV1, canonical_bytes, digest_bytes,
};

/// Exact immutable artifact reference.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactRefV1 {
    /// Occurrence identity.
    pub artifact_id: StableString,
    /// Exact content digest.
    pub content_digest: ValueDigest,
}

/// One caller-fed fixture artifact occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactOccurrenceV1 {
    /// Distinct immutable occurrence identity.
    pub artifact_id: StableString,
    /// Registered artifact kind.
    pub kind_id: StableString,
    /// Exact canonical content digest.
    pub content_digest: ValueDigest,
    /// Latest information availability used by the artifact.
    pub information_cutoff: UtcTimestamp,
    /// Fixture production clock; not store commit time.
    pub produced_at: UtcTimestamp,
    /// Exact parents, strictly sorted and already present earlier in the DAG.
    pub parents: Vec<ArtifactRefV1>,
    /// Fixed read-only authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
}

/// One exact topologically ordered fixture DAG.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactDagV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Exact owning program identity.
    pub program_id: StableString,
    /// Exact owning registration material digest.
    pub registration_digest: ValueDigest,
    /// Topologically ordered artifact occurrences.
    pub artifacts: Vec<ArtifactOccurrenceV1>,
    /// Digest over [`ArtifactDagDigestMaterialV1`].
    pub dag_digest: ValueDigest,
}

/// Self-digest material for [`ArtifactDagV1`].
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ArtifactDagDigestMaterialV1<'a> {
    /// Contract.
    pub contract: &'a StableString,
    /// Program.
    pub program_id: &'a StableString,
    /// Registration digest.
    pub registration_digest: &'a ValueDigest,
    /// Ordered artifacts.
    pub artifacts: &'a [ArtifactOccurrenceV1],
}

impl ArtifactDagV1 {
    /// Returns exact self-digest material.
    #[must_use]
    pub fn digest_material(&self) -> ArtifactDagDigestMaterialV1<'_> {
        ArtifactDagDigestMaterialV1 {
            contract: &self.contract,
            program_id: &self.program_id,
            registration_digest: &self.registration_digest,
            artifacts: &self.artifacts,
        }
    }

    /// Revalidates exact identity, time, parent, kind, budget, and digest closure.
    ///
    /// # Errors
    ///
    /// Refuses unknown kinds, duplicate IDs/digests, future/backward edges, unordered parents,
    /// authority widening, excess artifacts, or digest mismatch.
    pub fn validate(&self, registration: &Wave6ProgramRegistrationV1) -> Result<()> {
        if self.contract.as_str() != ARTIFACT_DAG_CONTRACT
            || self.program_id != registration.program_id
            || self.registration_digest != registration.registration_digest
        {
            return Err(RegistryError::Dag("registration binding"));
        }
        if self.artifacts.is_empty()
            || u64::try_from(self.artifacts.len()).ok()
                > Some(registration.budgets.max_artifacts.get())
        {
            return Err(RegistryError::Dag("artifact budget"));
        }

        let kinds: BTreeSet<_> = registration
            .artifact_kinds
            .iter()
            .map(|kind| &kind.kind_id)
            .collect();
        let mut seen_ids = BTreeMap::new();
        let mut seen_digests = BTreeSet::new();
        for artifact in &self.artifacts {
            super::validate::validate_sha256_public(&artifact.content_digest, "contentDigest")?;
            if !kinds.contains(&artifact.kind_id)
                || artifact.authority != registration.authority
                || artifact.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
                || artifact.produced_at < registration.registered_at
                || artifact.information_cutoff > artifact.produced_at
                || seen_ids.contains_key(&artifact.artifact_id)
                || !seen_digests.insert(artifact.content_digest.clone())
                || !artifact.parents.windows(2).all(|pair| pair[0] < pair[1])
            {
                return Err(RegistryError::Dag("artifact occurrence"));
            }
            for parent in &artifact.parents {
                super::validate::validate_sha256_public(
                    &parent.content_digest,
                    "parents.contentDigest",
                )?;
                let prior: &&ArtifactOccurrenceV1 = seen_ids
                    .get(&parent.artifact_id)
                    .ok_or(RegistryError::Dag("parent is not earlier"))?;
                if prior.content_digest != parent.content_digest
                    || prior.produced_at > artifact.produced_at
                    || prior.information_cutoff > artifact.information_cutoff
                {
                    return Err(RegistryError::Dag("parent closure"));
                }
            }
            seen_ids.insert(&artifact.artifact_id, artifact);
        }
        super::validate::validate_sha256_public(&self.dag_digest, "dagDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.dag_digest {
            return Err(RegistryError::Dag("digest mismatch"));
        }
        Ok(())
    }
}
