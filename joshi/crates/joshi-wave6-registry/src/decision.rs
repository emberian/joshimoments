//! Append-only fixture disposition ledger.

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use serde::{Deserialize, Serialize};

use crate::{
    ArtifactDagV1, ArtifactRefV1, FIXTURE_DECISION_LEDGER_CONTRACT, ProgramAuthorityV1,
    RegistryError, Result, SemanticCeilingV1, Wave6ProgramRegistrationV1, canonical_bytes,
    digest_bytes,
};

/// Decision kinds available before store resolution.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactDecisionKindV1 {
    /// Keep the artifact at schema/contract-only maturity.
    RetainContractOnly,
    /// Record deterministic fixture roundtrip; no operational promotion.
    PromoteFixtureRoundtrip,
    /// Park further work without deleting evidence.
    Park,
    /// Reject the fixture artifact without deleting evidence.
    Reject,
}

/// One append-only disposition for an exact artifact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactDecisionV1 {
    /// Distinct decision occurrence identity.
    pub decision_id: StableString,
    /// Exact target artifact.
    pub artifact: ArtifactRefV1,
    /// Prior decision for this artifact, or absent only for its first decision.
    pub predecessor_decision_id: Option<StableString>,
    /// Fixture-only decision kind.
    pub decision: ArtifactDecisionKindV1,
    /// Decision clock; not a human identity or durable commit.
    pub decided_at: UtcTimestamp,
    /// Exact evidence artifacts, sorted and duplicate-free.
    pub evidence: Vec<ArtifactRefV1>,
    /// Stable reason code.
    pub reason: StableString,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
}

/// Exact append-only fixture disposition ledger.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FixtureDecisionLedgerV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Owning program.
    pub program_id: StableString,
    /// Owning registration digest.
    pub registration_digest: ValueDigest,
    /// Exact input DAG digest.
    pub artifact_dag_digest: ValueDigest,
    /// Append order.
    pub decisions: Vec<ArtifactDecisionV1>,
    /// Digest over [`FixtureDecisionLedgerDigestMaterialV1`].
    pub ledger_digest: ValueDigest,
}

/// Self-digest material for [`FixtureDecisionLedgerV1`].
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FixtureDecisionLedgerDigestMaterialV1<'a> {
    /// Contract.
    pub contract: &'a StableString,
    /// Program.
    pub program_id: &'a StableString,
    /// Registration digest.
    pub registration_digest: &'a ValueDigest,
    /// Artifact DAG digest.
    pub artifact_dag_digest: &'a ValueDigest,
    /// Ordered decisions.
    pub decisions: &'a [ArtifactDecisionV1],
}

impl FixtureDecisionLedgerV1 {
    /// Returns exact self-digest material.
    #[must_use]
    pub fn digest_material(&self) -> FixtureDecisionLedgerDigestMaterialV1<'_> {
        FixtureDecisionLedgerDigestMaterialV1 {
            contract: &self.contract,
            program_id: &self.program_id,
            registration_digest: &self.registration_digest,
            artifact_dag_digest: &self.artifact_dag_digest,
            decisions: &self.decisions,
        }
    }

    /// Revalidates an append-only fixture ledger against the exact artifact DAG.
    ///
    /// # Errors
    ///
    /// Refuses branching/backdated decisions, duplicate identities, unknown/substituted evidence,
    /// authority widening, repeated promotion, empty evidence, or digest mismatch.
    pub fn validate(
        &self,
        registration: &Wave6ProgramRegistrationV1,
        dag: &ArtifactDagV1,
    ) -> Result<()> {
        if self.contract.as_str() != FIXTURE_DECISION_LEDGER_CONTRACT
            || self.program_id != registration.program_id
            || self.registration_digest != registration.registration_digest
            || self.artifact_dag_digest != dag.dag_digest
            || self.decisions.is_empty()
        {
            return Err(RegistryError::Decision("registry binding"));
        }
        let artifacts: BTreeMap<_, _> = dag
            .artifacts
            .iter()
            .map(|artifact| (&artifact.artifact_id, artifact))
            .collect();
        let mut decision_ids = BTreeSet::new();
        let mut heads: BTreeMap<&StableString, &ArtifactDecisionV1> = BTreeMap::new();
        let mut promoted = BTreeSet::new();
        for decision in &self.decisions {
            let target = artifacts
                .get(&decision.artifact.artifact_id)
                .ok_or(RegistryError::Decision("unknown target"))?;
            if target.content_digest != decision.artifact.content_digest
                || decision.authority != registration.authority
                || decision.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
                || decision.decided_at < target.produced_at
                || !decision_ids.insert(&decision.decision_id)
                || decision.evidence.is_empty()
                || !decision.evidence.windows(2).all(|pair| pair[0] < pair[1])
            {
                return Err(RegistryError::Decision("decision occurrence"));
            }
            if let Some(previous) = heads.get(&decision.artifact.artifact_id) {
                if decision.predecessor_decision_id.as_ref() != Some(&previous.decision_id)
                    || decision.decided_at < previous.decided_at
                {
                    return Err(RegistryError::Decision("branch or clock rollback"));
                }
            } else if decision.predecessor_decision_id.is_some() {
                return Err(RegistryError::Decision("orphan predecessor"));
            }
            for evidence in &decision.evidence {
                let exact = artifacts
                    .get(&evidence.artifact_id)
                    .ok_or(RegistryError::Decision("unknown evidence"))?;
                if exact.content_digest != evidence.content_digest
                    || exact.produced_at > decision.decided_at
                {
                    return Err(RegistryError::Decision("evidence closure"));
                }
            }
            if decision.decision == ArtifactDecisionKindV1::PromoteFixtureRoundtrip
                && (!promoted.insert(&decision.artifact.artifact_id)
                    || decision.evidence.binary_search(&decision.artifact).is_err())
            {
                return Err(RegistryError::Decision("fixture promotion"));
            }
            heads.insert(&decision.artifact.artifact_id, decision);
        }
        super::validate::validate_sha256_public(&self.ledger_digest, "ledgerDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.ledger_digest {
            return Err(RegistryError::Decision("digest mismatch"));
        }
        Ok(())
    }
}
