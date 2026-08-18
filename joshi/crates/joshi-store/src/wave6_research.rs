//! Sole-store persistence for one exact, non-executable Wave 6 research proposal.

use crate::{IdempotencyStatus, Result, SqliteStore, StoreError};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_wave6_registry::{
    RESEARCH_PROPOSAL_KIND, RESEARCH_PROPOSAL_SCHEMA, ResearchArtifactDescriptorV1,
    ResearchDispositionKindV1, SemanticCeilingV1, parse_research_disposition_exact,
    parse_research_proposal_exact,
};
use rusqlite::{OptionalExtension as _, params};
use sha2::{Digest as _, Sha256};

const MAX_PROPOSAL_BYTES: usize = 512 * 1024;
const MAX_DISPOSITION_BYTES: usize = 16 * 1024;
const AUTHORITY: &str = "read_only_proposal_only_no_query_no_glass_no_action_no_claim_promotion";
const CLAIM_SCOPE: &str = "research_design_proposal_not_result_or_live_decision";
const CEILING: &str = "unverified_semantic_fixture_only";
const REVIEWER_AUTHORITY: &str = "caller_fed_fixture_unverified";

/// The sole authority state a persisted fixture disposition can carry.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResearchDispositionAuthorityV1 {
    /// Caller-fed identity; no verified human review, approval, execution, or result authority.
    CallerFedFixtureUnverifiedNoHumanReviewApprovalExecutionOrResult,
}

impl ResearchDispositionAuthorityV1 {
    #[must_use]
    pub const fn human_review_verified(self) -> bool {
        false
    }

    #[must_use]
    pub const fn approval_authority(self) -> bool {
        false
    }

    #[must_use]
    pub const fn execution_authority(self) -> bool {
        false
    }

    #[must_use]
    pub const fn result_authority(self) -> bool {
        false
    }
}

/// Durable receipt for exact proposal bytes and their resolved prior evaluation closure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6FixtureResearchProposalReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub proposal_id: StableString,
    pub program_id: StableString,
    pub proposal_digest: ValueDigest,
    pub content_digest: ValueDigest,
    pub commitment_digest: ValueDigest,
    pub policy_digest: ValueDigest,
    pub evidence_closure_digest: ValueDigest,
    pub descriptor_count: u64,
    pub counterexample_count: u64,
    pub experiment_count: u64,
    pub total_experiment_units: u64,
    pub maximum_fixture_alleged_commit_seq: u64,
    pub maximum_resolved_artifact_commit_seq: CommitSeq,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
    pub status: IdempotencyStatus,
}

/// One exact descriptor joined to its prior durable evaluation artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6ResearchArtifactBinding {
    pub descriptor_artifact_id: StableString,
    pub provenance_digest: ValueDigest,
    pub resolved_artifact_id: StableString,
    pub resolved_kind_id: StableString,
    pub fixture_alleged_commit_seq: u64,
    pub resolved_artifact_commit_seq: CommitSeq,
}

/// Exact proposal bytes re-parsed and rejoined to prior durable evaluations after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6FixtureResearchProposal {
    pub batch_id: StableString,
    pub proposal_id: StableString,
    pub program_id: StableString,
    pub program_registration_digest: ValueDigest,
    pub schema_id: StableString,
    pub schema_digest: ValueDigest,
    pub schema_commit_seq: CommitSeq,
    pub exact_bytes: Vec<u8>,
    pub proposal_digest: ValueDigest,
    pub content_digest: ValueDigest,
    pub commitment_digest: ValueDigest,
    pub policy_digest: ValueDigest,
    pub evidence_closure_digest: ValueDigest,
    pub descriptor_count: u64,
    pub counterexample_count: u64,
    pub experiment_count: u64,
    pub total_experiment_units: u64,
    pub maximum_fixture_alleged_commit_seq: u64,
    pub maximum_resolved_artifact_commit_seq: CommitSeq,
    pub artifact_bindings: Vec<StoredWave6ResearchArtifactBinding>,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub semantic_ceiling: SemanticCeilingV1,
}

/// Durable receipt for caller-fed disposition bytes; all review/approval authority remains false.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6FixtureResearchDispositionReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub disposition_id: StableString,
    pub proposal_id: StableString,
    pub proposal_digest: ValueDigest,
    pub proposal_content_digest: ValueDigest,
    pub disposition: ResearchDispositionKindV1,
    pub reviewer_id: StableString,
    pub decided_at: UtcTimestamp,
    pub content_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub authority_boundary: ResearchDispositionAuthorityV1,
    pub semantic_ceiling: SemanticCeilingV1,
    pub status: IdempotencyStatus,
}

/// Exact disposition bytes re-parsed and rebound to their durable proposal after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6FixtureResearchDisposition {
    pub batch_id: StableString,
    pub disposition_id: StableString,
    pub proposal_id: StableString,
    pub proposal_digest: ValueDigest,
    pub proposal_content_digest: ValueDigest,
    pub disposition: ResearchDispositionKindV1,
    pub reviewer_id: StableString,
    pub decided_at: UtcTimestamp,
    pub reason: String,
    pub exact_bytes: Vec<u8>,
    pub content_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub authority_boundary: ResearchDispositionAuthorityV1,
    pub semantic_ceiling: SemanticCeilingV1,
}

struct ProposalRow {
    batch_id: String,
    program_id: String,
    program_registration_raw: String,
    kind_id: String,
    schema_id: String,
    schema_raw: String,
    schema_commit_seq: i64,
    proposal_raw: String,
    content_raw: String,
    commitment_raw: String,
    policy_raw: String,
    evidence_raw: String,
    bytes: Vec<u8>,
    byte_length: i64,
    descriptor_count: i64,
    counterexample_count: i64,
    experiment_count: i64,
    total_experiment_units: i64,
    maximum_fixture_alleged_commit_seq: i64,
    maximum_resolved_artifact_commit_seq: i64,
    authority: String,
    claim_scope: String,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

struct BindingRow {
    ordinal: i64,
    descriptor_artifact_id: String,
    provenance_raw: String,
    resolved_artifact_id: String,
    resolved_kind_id: String,
    fixture_alleged_commit_seq: i64,
    resolved_artifact_commit_seq: i64,
    role: String,
    semantic_ceiling: String,
}

struct DispositionRow {
    batch_id: String,
    proposal_id: String,
    proposal_raw: String,
    proposal_content_raw: String,
    disposition_kind: String,
    reviewer_id: String,
    decided_at: String,
    reason: String,
    content_raw: String,
    bytes: Vec<u8>,
    byte_length: i64,
    identity_authority: String,
    human_review_verified: i64,
    approval_authority: i64,
    execution_authority: i64,
    result_authority: i64,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

impl SqliteStore {
    /// Persists one exact fixture proposal only after resolving all three prior evaluations.
    ///
    /// The receipt proves byte and lineage durability, not human review, execution, result,
    /// release, or claim authority.
    ///
    /// # Errors
    ///
    /// Refuses absent program/schema/evaluation rows, noncanonical or oversized bytes, changed
    /// descriptor provenance, conflicting identity, read-only state, or failed exact readback.
    #[allow(clippy::too_many_lines)]
    pub fn commit_wave6_fixture_research_proposal_v1(
        &mut self,
        program_id: &StableString,
        exact_bytes: &[u8],
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6FixtureResearchProposalReceipt> {
        if exact_bytes.is_empty() || exact_bytes.len() > MAX_PROPOSAL_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 research proposal is empty or exceeds the exact-byte limit".into(),
            ));
        }
        let program = self
            .load_wave6_program_registration_v1(program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            })?;
        let kind_id = stable(RESEARCH_PROPOSAL_KIND, "Wave 6 research kind")?;
        let schema = self
            .load_wave6_artifact_schema_v1(program_id, &kind_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 research proposal schema",
                identity: format!("{}:{RESEARCH_PROPOSAL_KIND}", program_id.as_str()),
            })?;
        if schema.schema_id.as_str() != RESEARCH_PROPOSAL_SCHEMA {
            return Err(StoreError::InvalidBatch(
                "Wave 6 research schema differs from the registered contract".into(),
            ));
        }
        let parsed = parse_research_proposal_exact(exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let value = parsed.value();
        let proposal_id = value.proposal_id.clone();
        reject_second_proposal_batch(self, &proposal_id, &batch_id)?;
        let bindings = resolve_artifacts(self, program_id, &value.artifact_descriptors)?;
        let descriptor_count = checked_len(bindings.len(), "Wave 6 research descriptor count")?;
        let counterexample_count = checked_len(
            value.specification.counterexamples.len(),
            "Wave 6 research counterexample count",
        )?;
        let experiment_count = checked_len(
            value.specification.experiments.len(),
            "Wave 6 research experiment count",
        )?;
        let total_experiment_units =
            value
                .specification
                .experiments
                .iter()
                .try_fold(0_u64, |total, experiment| {
                    total.checked_add(experiment.resource_units).ok_or_else(|| {
                        StoreError::IntegerRange {
                            field: "Wave 6 research total experiment units",
                            value: u64::MAX.to_string(),
                        }
                    })
                })?;
        let maximum_fixture_alleged_commit_seq = bindings
            .iter()
            .map(|binding| binding.fixture_alleged_commit_seq)
            .max()
            .ok_or_else(|| StoreError::InvalidBatch("Wave 6 research has no descriptors".into()))?;
        let maximum_resolved_artifact_commit_seq = bindings
            .iter()
            .map(|binding| binding.resolved_artifact_commit_seq)
            .max()
            .ok_or_else(|| StoreError::InvalidBatch("Wave 6 research has no artifacts".into()))?;
        let operation_digest = proposal_operation_digest(
            program_id,
            &proposal_id,
            &value.proposal_digest,
            parsed.content_digest(),
        )?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &proposal_id,
            parsed.content_digest(),
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_fixture_research_proposal_v1
                     (proposal_id,program_id,program_registration_sha256,kind_id,schema_id,
                      schema_sha256,schema_created_commit_seq,proposal_semantic_sha256,
                      content_sha256,commitment_sha256,policy_sha256,evidence_closure_sha256,
                      proposal_bytes,proposal_byte_length,descriptor_count,counterexample_count,
                      experiment_count,total_experiment_units,
                      maximum_fixture_alleged_commit_seq,maximum_resolved_artifact_commit_seq,
                      authority,claim_scope,semantic_ceiling,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             ?17,?18,?19,?20,?21,?22,?23,?24)",
                    params![
                        proposal_id.as_str(),
                        program_id.as_str(),
                        raw_digest(&program.registration_digest, "Wave 6 program digest")?,
                        RESEARCH_PROPOSAL_KIND,
                        RESEARCH_PROPOSAL_SCHEMA,
                        raw_digest(&schema.schema_digest, "Wave 6 research schema digest")?,
                        sqlite_u64(schema.commit_seq.get(), "Wave 6 research schema commit")?,
                        raw_digest(&value.proposal_digest, "Wave 6 proposal digest")?,
                        raw_digest(parsed.content_digest(), "Wave 6 proposal content digest")?,
                        raw_digest(&value.commitment_digest, "Wave 6 commitment digest")?,
                        raw_digest(&value.policy_digest, "Wave 6 policy digest")?,
                        raw_digest(
                            &value.evidence_closure_digest,
                            "Wave 6 evidence closure digest"
                        )?,
                        exact_bytes,
                        sqlite_usize(exact_bytes.len(), "Wave 6 proposal bytes")?,
                        sqlite_u64(descriptor_count, "Wave 6 descriptor count")?,
                        sqlite_u64(counterexample_count, "Wave 6 counterexample count")?,
                        sqlite_u64(experiment_count, "Wave 6 experiment count")?,
                        sqlite_u64(total_experiment_units, "Wave 6 experiment units")?,
                        sqlite_u64(
                            maximum_fixture_alleged_commit_seq,
                            "Wave 6 maximum alleged commit"
                        )?,
                        sqlite_u64(
                            maximum_resolved_artifact_commit_seq.get(),
                            "Wave 6 maximum resolved commit"
                        )?,
                        AUTHORITY,
                        CLAIM_SCOPE,
                        CEILING,
                        seq,
                    ],
                )?;
                for (ordinal, binding) in bindings.iter().enumerate() {
                    tx.execute(
                        "INSERT INTO wave6_fixture_research_proposal_artifact_v1
                         (proposal_id,descriptor_ordinal,descriptor_artifact_id,provenance_sha256,
                          resolved_artifact_id,resolved_kind_id,fixture_alleged_commit_seq,
                          resolved_artifact_commit_seq,role,semantic_ceiling)
                         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,'design',?9)",
                        params![
                            proposal_id.as_str(),
                            sqlite_usize(ordinal, "Wave 6 research descriptor ordinal")?,
                            binding.descriptor_artifact_id.as_str(),
                            raw_digest(&binding.provenance_digest, "Wave 6 provenance digest")?,
                            binding.resolved_artifact_id.as_str(),
                            binding.resolved_kind_id.as_str(),
                            sqlite_u64(
                                binding.fixture_alleged_commit_seq,
                                "Wave 6 descriptor alleged commit"
                            )?,
                            sqlite_u64(
                                binding.resolved_artifact_commit_seq.get(),
                                "Wave 6 descriptor resolved commit"
                            )?,
                            CEILING,
                        ],
                    )?;
                }
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_fixture_research_proposal_v1(&proposal_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 fixture research proposal",
                identity: proposal_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.program_id != *program_id
            || stored.exact_bytes != exact_bytes
            || stored.proposal_digest != value.proposal_digest
            || stored.content_digest != *parsed.content_digest()
            || stored.artifact_bindings != bindings
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 research proposal readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6FixtureResearchProposalReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            proposal_id,
            program_id: program_id.clone(),
            proposal_digest: stored.proposal_digest,
            content_digest: stored.content_digest,
            commitment_digest: stored.commitment_digest,
            policy_digest: stored.policy_digest,
            evidence_closure_digest: stored.evidence_closure_digest,
            descriptor_count: stored.descriptor_count,
            counterexample_count: stored.counterexample_count,
            experiment_count: stored.experiment_count,
            total_experiment_units: stored.total_experiment_units,
            maximum_fixture_alleged_commit_seq: stored.maximum_fixture_alleged_commit_seq,
            maximum_resolved_artifact_commit_seq: stored.maximum_resolved_artifact_commit_seq,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads, reparses, and rejoins one exact fixture research proposal after restart.
    ///
    /// # Errors
    ///
    /// Refuses changed bytes/scalars, missing or substituted evaluation lineage, malformed
    /// digests, or invalid commit order.
    pub fn load_wave6_fixture_research_proposal_v1(
        &self,
        proposal_id: &StableString,
    ) -> Result<Option<StoredWave6FixtureResearchProposal>> {
        let row = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,proposal.program_id,
                        proposal.program_registration_sha256,proposal.kind_id,proposal.schema_id,
                        proposal.schema_sha256,proposal.schema_created_commit_seq,
                        proposal.proposal_semantic_sha256,proposal.content_sha256,
                        proposal.commitment_sha256,proposal.policy_sha256,
                        proposal.evidence_closure_sha256,proposal.proposal_bytes,
                        proposal.proposal_byte_length,proposal.descriptor_count,
                        proposal.counterexample_count,proposal.experiment_count,
                        proposal.total_experiment_units,
                        proposal.maximum_fixture_alleged_commit_seq,
                        proposal.maximum_resolved_artifact_commit_seq,proposal.authority,
                        proposal.claim_scope,proposal.semantic_ceiling,proposal.created_commit_seq,
                        commit_row.commit_digest
                 FROM wave6_fixture_research_proposal_v1 proposal
                 JOIN ingest_commit commit_row ON commit_row.commit_seq=proposal.created_commit_seq
                 WHERE proposal.proposal_id=?1",
                [proposal_id.as_str()],
                |row| {
                    Ok(ProposalRow {
                        batch_id: row.get(0)?,
                        program_id: row.get(1)?,
                        program_registration_raw: row.get(2)?,
                        kind_id: row.get(3)?,
                        schema_id: row.get(4)?,
                        schema_raw: row.get(5)?,
                        schema_commit_seq: row.get(6)?,
                        proposal_raw: row.get(7)?,
                        content_raw: row.get(8)?,
                        commitment_raw: row.get(9)?,
                        policy_raw: row.get(10)?,
                        evidence_raw: row.get(11)?,
                        bytes: row.get(12)?,
                        byte_length: row.get(13)?,
                        descriptor_count: row.get(14)?,
                        counterexample_count: row.get(15)?,
                        experiment_count: row.get(16)?,
                        total_experiment_units: row.get(17)?,
                        maximum_fixture_alleged_commit_seq: row.get(18)?,
                        maximum_resolved_artifact_commit_seq: row.get(19)?,
                        authority: row.get(20)?,
                        claim_scope: row.get(21)?,
                        semantic_ceiling: row.get(22)?,
                        commit_seq: row.get(23)?,
                        commit_digest_raw: row.get(24)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        stored_research_proposal(self, proposal_id, row).map(Some)
    }
}

impl SqliteStore {
    /// Persists exact caller-fed disposition bytes after resolving the exact prior proposal.
    ///
    /// The receipt proves durability and proposal lineage only. It never authenticates the
    /// reviewer or grants human-review, approval, execution, result, or release authority.
    ///
    /// # Errors
    ///
    /// Refuses missing/foreign proposal lineage, noncanonical or oversized bytes, backdating,
    /// changed identity, a second batch for one disposition, read-only state, or failed readback.
    #[allow(clippy::too_many_lines)]
    pub fn commit_wave6_fixture_research_disposition_v1(
        &mut self,
        proposal_id: &StableString,
        exact_bytes: &[u8],
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6FixtureResearchDispositionReceipt> {
        if exact_bytes.is_empty() || exact_bytes.len() > MAX_DISPOSITION_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 research disposition is empty or exceeds the exact-byte limit".into(),
            ));
        }
        let proposal = self
            .load_wave6_fixture_research_proposal_v1(proposal_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 fixture research proposal",
                identity: proposal_id.to_string(),
            })?;
        let parsed_proposal = parse_research_proposal_exact(&proposal.exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let parsed = parse_research_disposition_exact(exact_bytes, &parsed_proposal)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let value = parsed.value();
        let disposition_id = value.disposition_id.clone();
        reject_second_disposition_batch(self, &disposition_id, &batch_id)?;
        let operation_digest =
            disposition_operation_digest(proposal_id, &disposition_id, parsed.content_digest())?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &disposition_id,
            parsed.content_digest(),
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_fixture_research_disposition_v1
                     (disposition_id,proposal_id,proposal_semantic_sha256,
                      proposal_content_sha256,disposition_kind,reviewer_id,decided_at,reason,
                      disposition_content_sha256,disposition_bytes,disposition_byte_length,
                      identity_authority,human_review_verified,approval_authority,
                      execution_authority,result_authority,semantic_ceiling,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,0,0,0,0,?13,?14)",
                    params![
                        disposition_id.as_str(),
                        proposal_id.as_str(),
                        raw_digest(&proposal.proposal_digest, "Wave 6 proposal digest")?,
                        raw_digest(&proposal.content_digest, "Wave 6 proposal content digest")?,
                        disposition_kind(value.disposition),
                        value.human_id.as_str(),
                        value.decided_at.to_string(),
                        value.reason.as_str(),
                        raw_digest(parsed.content_digest(), "Wave 6 disposition content digest")?,
                        exact_bytes,
                        sqlite_usize(exact_bytes.len(), "Wave 6 disposition bytes")?,
                        REVIEWER_AUTHORITY,
                        CEILING,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_fixture_research_disposition_v1(&disposition_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 fixture research disposition",
                identity: disposition_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.proposal_id != *proposal_id
            || stored.exact_bytes != exact_bytes
            || stored.content_digest != *parsed.content_digest()
            || stored.commit_seq != generic.commit_seq
            || stored.authority_boundary
                != ResearchDispositionAuthorityV1::CallerFedFixtureUnverifiedNoHumanReviewApprovalExecutionOrResult
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 research disposition readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6FixtureResearchDispositionReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            disposition_id,
            proposal_id: proposal_id.clone(),
            proposal_digest: stored.proposal_digest,
            proposal_content_digest: stored.proposal_content_digest,
            disposition: stored.disposition,
            reviewer_id: stored.reviewer_id,
            decided_at: stored.decided_at,
            content_digest: stored.content_digest,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            authority_boundary: ResearchDispositionAuthorityV1::CallerFedFixtureUnverifiedNoHumanReviewApprovalExecutionOrResult,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads and reparses one fixture disposition against its exact prior proposal.
    ///
    /// # Errors
    ///
    /// Refuses missing/substituted proposal lineage, changed bytes or scalars, malformed clocks or
    /// digests, or any attempted authority promotion.
    pub fn load_wave6_fixture_research_disposition_v1(
        &self,
        disposition_id: &StableString,
    ) -> Result<Option<StoredWave6FixtureResearchDisposition>> {
        let row = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,disposition.proposal_id,
                        disposition.proposal_semantic_sha256,
                        disposition.proposal_content_sha256,disposition.disposition_kind,
                        disposition.reviewer_id,disposition.decided_at,disposition.reason,
                        disposition.disposition_content_sha256,disposition.disposition_bytes,
                        disposition.disposition_byte_length,disposition.identity_authority,
                        disposition.human_review_verified,disposition.approval_authority,
                        disposition.execution_authority,disposition.result_authority,
                        disposition.semantic_ceiling,disposition.created_commit_seq,
                        commit_row.commit_digest
                 FROM wave6_fixture_research_disposition_v1 disposition
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=disposition.created_commit_seq
                 WHERE disposition.disposition_id=?1",
                [disposition_id.as_str()],
                |row| {
                    Ok(DispositionRow {
                        batch_id: row.get(0)?,
                        proposal_id: row.get(1)?,
                        proposal_raw: row.get(2)?,
                        proposal_content_raw: row.get(3)?,
                        disposition_kind: row.get(4)?,
                        reviewer_id: row.get(5)?,
                        decided_at: row.get(6)?,
                        reason: row.get(7)?,
                        content_raw: row.get(8)?,
                        bytes: row.get(9)?,
                        byte_length: row.get(10)?,
                        identity_authority: row.get(11)?,
                        human_review_verified: row.get(12)?,
                        approval_authority: row.get(13)?,
                        execution_authority: row.get(14)?,
                        result_authority: row.get(15)?,
                        semantic_ceiling: row.get(16)?,
                        commit_seq: row.get(17)?,
                        commit_digest_raw: row.get(18)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        stored_research_disposition(self, disposition_id, row).map(Some)
    }
}

fn resolve_artifacts(
    store: &SqliteStore,
    program_id: &StableString,
    descriptors: &[ResearchArtifactDescriptorV1],
) -> Result<Vec<StoredWave6ResearchArtifactBinding>> {
    descriptors
        .iter()
        .map(|descriptor| {
            let provenance_raw = raw_digest(
                &descriptor.provenance_digest,
                "Wave 6 research provenance digest",
            )?;
            let resolved: Option<(String, String, i64)> = store
                .connection
                .query_row(
                    "SELECT artifact_id,kind_id,created_commit_seq
                     FROM wave6_fixture_artifact_content_v1
                     WHERE program_id=?1 AND evaluation_semantic_sha256=?2",
                    params![program_id.as_str(), provenance_raw],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .optional()?;
            let (artifact_id_raw, kind_id_raw, commit_raw) =
                resolved.ok_or_else(|| StoreError::MissingIdentity {
                    kind: "Wave 6 research evaluation artifact",
                    identity: descriptor.provenance_digest.to_string(),
                })?;
            let artifact_id = stable(&artifact_id_raw, "Wave 6 resolved artifact ID")?;
            let kind_id = stable(&kind_id_raw, "Wave 6 resolved artifact kind")?;
            let stored = store
                .load_wave6_fixture_artifact_v1(&artifact_id)?
                .ok_or_else(|| StoreError::MissingIdentity {
                    kind: "Wave 6 fixture evaluation artifact",
                    identity: artifact_id.to_string(),
                })?;
            let expected_descriptor_id = descriptor_id(&kind_id, &descriptor.provenance_digest)?;
            let commit_seq =
                CommitSeq::new(u64_from_i64(commit_raw, "Wave 6 resolved artifact commit")?);
            if expected_descriptor_id != descriptor.artifact_id
                || stored.program_id != *program_id
                || stored.kind_id != kind_id
                || stored.evaluation_digest != descriptor.provenance_digest
                || stored.commit_seq != commit_seq
                || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            {
                return Err(StoreError::InvalidBatch(
                    "Wave 6 research descriptor differs from its prior evaluation artifact".into(),
                ));
            }
            Ok(StoredWave6ResearchArtifactBinding {
                descriptor_artifact_id: descriptor.artifact_id.clone(),
                provenance_digest: descriptor.provenance_digest.clone(),
                resolved_artifact_id: artifact_id,
                resolved_kind_id: kind_id,
                fixture_alleged_commit_seq: descriptor.commit_seq.get(),
                resolved_artifact_commit_seq: commit_seq,
            })
        })
        .collect()
}

fn descriptor_id(kind_id: &StableString, digest: &ValueDigest) -> Result<StableString> {
    let prefix = match kind_id.as_str() {
        "known_truth_evaluation_fixture" => "known-truth-evaluation-",
        "protocol_known_truth_evaluation_fixture" => "protocol-truth-evaluation-",
        "structural_known_truth_evaluation_fixture" => "structural-truth-evaluation-",
        _ => {
            return Err(StoreError::InvalidBatch(
                "unsupported research evidence kind".into(),
            ));
        }
    };
    let raw = raw_digest(digest, "Wave 6 research descriptor digest")?;
    stable(
        &format!("{prefix}{}", &raw[..32]),
        "Wave 6 research descriptor ID",
    )
}

#[allow(clippy::too_many_lines)]
fn stored_research_proposal(
    store: &SqliteStore,
    proposal_id: &StableString,
    row: ProposalRow,
) -> Result<StoredWave6FixtureResearchProposal> {
    let program_id = stable(&row.program_id, "Wave 6 research program ID")?;
    let program = store
        .load_wave6_program_registration_v1(&program_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 program registration",
            identity: program_id.to_string(),
        })?;
    let kind_id = stable(RESEARCH_PROPOSAL_KIND, "Wave 6 research kind")?;
    let schema = store
        .load_wave6_artifact_schema_v1(&program_id, &kind_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 research proposal schema",
            identity: program_id.to_string(),
        })?;
    let parsed = parse_research_proposal_exact(&row.bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let value = parsed.value();
    let expected_bindings = resolve_artifacts(store, &program_id, &value.artifact_descriptors)?;
    let stored_bindings = load_binding_rows(store, proposal_id)?;
    let descriptor_count = checked_len(expected_bindings.len(), "Wave 6 descriptor count")?;
    let counterexample_count = checked_len(
        value.specification.counterexamples.len(),
        "Wave 6 counterexample count",
    )?;
    let experiment_count = checked_len(
        value.specification.experiments.len(),
        "Wave 6 experiment count",
    )?;
    let total_experiment_units =
        value
            .specification
            .experiments
            .iter()
            .try_fold(0_u64, |total, experiment| {
                total.checked_add(experiment.resource_units).ok_or_else(|| {
                    StoreError::IntegerRange {
                        field: "Wave 6 total experiment units",
                        value: u64::MAX.to_string(),
                    }
                })
            })?;
    let maximum_fixture_alleged_commit_seq = expected_bindings
        .iter()
        .map(|binding| binding.fixture_alleged_commit_seq)
        .max()
        .ok_or_else(|| StoreError::InvalidBatch("Wave 6 research has no descriptors".into()))?;
    let maximum_resolved_artifact_commit_seq = expected_bindings
        .iter()
        .map(|binding| binding.resolved_artifact_commit_seq)
        .max()
        .ok_or_else(|| StoreError::InvalidBatch("Wave 6 research has no artifacts".into()))?;
    let commit_seq = CommitSeq::new(u64_from_i64(row.commit_seq, "Wave 6 proposal commit")?);
    if value.proposal_id != *proposal_id
        || row.program_registration_raw
            != raw_digest(&program.registration_digest, "Wave 6 program digest")?
        || row.kind_id != RESEARCH_PROPOSAL_KIND
        || row.schema_id != RESEARCH_PROPOSAL_SCHEMA
        || row.schema_raw != raw_digest(&schema.schema_digest, "Wave 6 schema digest")?
        || CommitSeq::new(u64_from_i64(row.schema_commit_seq, "Wave 6 schema commit")?)
            != schema.commit_seq
        || row.proposal_raw != raw_digest(&value.proposal_digest, "Wave 6 proposal digest")?
        || row.content_raw != raw_digest(parsed.content_digest(), "Wave 6 content digest")?
        || row.commitment_raw != raw_digest(&value.commitment_digest, "Wave 6 commitment digest")?
        || row.policy_raw != raw_digest(&value.policy_digest, "Wave 6 policy digest")?
        || row.evidence_raw != raw_digest(&value.evidence_closure_digest, "Wave 6 evidence digest")?
        || usize_from_i64(row.byte_length, "Wave 6 proposal byte length")? != row.bytes.len()
        || u64_from_i64(row.descriptor_count, "Wave 6 descriptor count")? != descriptor_count
        || u64_from_i64(row.counterexample_count, "Wave 6 counterexample count")?
            != counterexample_count
        || u64_from_i64(row.experiment_count, "Wave 6 experiment count")? != experiment_count
        || u64_from_i64(row.total_experiment_units, "Wave 6 experiment units")?
            != total_experiment_units
        || u64_from_i64(
            row.maximum_fixture_alleged_commit_seq,
            "Wave 6 maximum alleged commit",
        )? != maximum_fixture_alleged_commit_seq
        || CommitSeq::new(u64_from_i64(
            row.maximum_resolved_artifact_commit_seq,
            "Wave 6 maximum resolved commit",
        )?) != maximum_resolved_artifact_commit_seq
        || stored_bindings != expected_bindings
        || row.authority != AUTHORITY
        || row.claim_scope != CLAIM_SCOPE
        || row.semantic_ceiling != CEILING
        || schema.commit_seq >= commit_seq
        || maximum_resolved_artifact_commit_seq >= commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 research proposal differs from exact bytes or prior lineage".into(),
        ));
    }
    Ok(StoredWave6FixtureResearchProposal {
        batch_id: stable(&row.batch_id, "Wave 6 proposal batch ID")?,
        proposal_id: proposal_id.clone(),
        program_id,
        program_registration_digest: program.registration_digest,
        schema_id: schema.schema_id,
        schema_digest: schema.schema_digest,
        schema_commit_seq: schema.commit_seq,
        exact_bytes: row.bytes,
        proposal_digest: value.proposal_digest.clone(),
        content_digest: parsed.content_digest().clone(),
        commitment_digest: value.commitment_digest.clone(),
        policy_digest: value.policy_digest.clone(),
        evidence_closure_digest: value.evidence_closure_digest.clone(),
        descriptor_count,
        counterexample_count,
        experiment_count,
        total_experiment_units,
        maximum_fixture_alleged_commit_seq,
        maximum_resolved_artifact_commit_seq,
        artifact_bindings: expected_bindings,
        commit_seq,
        commit_digest: qualified_digest(&row.commit_digest_raw, "Wave 6 proposal commit digest")?,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
}

fn load_binding_rows(
    store: &SqliteStore,
    proposal_id: &StableString,
) -> Result<Vec<StoredWave6ResearchArtifactBinding>> {
    let mut statement = store.connection.prepare(
        "SELECT descriptor_ordinal,descriptor_artifact_id,provenance_sha256,
                resolved_artifact_id,resolved_kind_id,fixture_alleged_commit_seq,
                resolved_artifact_commit_seq,role,semantic_ceiling
         FROM wave6_fixture_research_proposal_artifact_v1
         WHERE proposal_id=?1 ORDER BY descriptor_ordinal",
    )?;
    let rows = statement
        .query_map([proposal_id.as_str()], |row| {
            Ok(BindingRow {
                ordinal: row.get(0)?,
                descriptor_artifact_id: row.get(1)?,
                provenance_raw: row.get(2)?,
                resolved_artifact_id: row.get(3)?,
                resolved_kind_id: row.get(4)?,
                fixture_alleged_commit_seq: row.get(5)?,
                resolved_artifact_commit_seq: row.get(6)?,
                role: row.get(7)?,
                semantic_ceiling: row.get(8)?,
            })
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    rows.into_iter()
        .enumerate()
        .map(|(ordinal, row)| {
            if usize_from_i64(row.ordinal, "Wave 6 descriptor ordinal")? != ordinal
                || row.role != "design"
                || row.semantic_ceiling != CEILING
            {
                return Err(StoreError::InvalidBatch(
                    "persisted Wave 6 research descriptor ordering or ceiling changed".into(),
                ));
            }
            Ok(StoredWave6ResearchArtifactBinding {
                descriptor_artifact_id: stable(
                    &row.descriptor_artifact_id,
                    "Wave 6 descriptor artifact ID",
                )?,
                provenance_digest: qualified_digest(
                    &row.provenance_raw,
                    "Wave 6 provenance digest",
                )?,
                resolved_artifact_id: stable(
                    &row.resolved_artifact_id,
                    "Wave 6 resolved artifact ID",
                )?,
                resolved_kind_id: stable(&row.resolved_kind_id, "Wave 6 resolved artifact kind")?,
                fixture_alleged_commit_seq: u64_from_i64(
                    row.fixture_alleged_commit_seq,
                    "Wave 6 descriptor alleged commit",
                )?,
                resolved_artifact_commit_seq: CommitSeq::new(u64_from_i64(
                    row.resolved_artifact_commit_seq,
                    "Wave 6 descriptor resolved commit",
                )?),
            })
        })
        .collect()
}

fn reject_second_proposal_batch(
    store: &SqliteStore,
    proposal_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_fixture_research_proposal_v1 proposal
             JOIN ingest_commit commit_row ON commit_row.commit_seq=proposal.created_commit_seq
             WHERE proposal.proposal_id=?1",
            [proposal_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|stored| stored != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 fixture research proposal",
            identity: proposal_id.to_string(),
        });
    }
    Ok(())
}

fn stored_research_disposition(
    store: &SqliteStore,
    disposition_id: &StableString,
    row: DispositionRow,
) -> Result<StoredWave6FixtureResearchDisposition> {
    let proposal_id = stable(&row.proposal_id, "Wave 6 disposition proposal ID")?;
    let proposal = store
        .load_wave6_fixture_research_proposal_v1(&proposal_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 fixture research proposal",
            identity: proposal_id.to_string(),
        })?;
    let parsed_proposal = parse_research_proposal_exact(&proposal.exact_bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let parsed = parse_research_disposition_exact(&row.bytes, &parsed_proposal)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let value = parsed.value();
    let decided_at = row
        .decided_at
        .parse::<UtcTimestamp>()
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let commit_seq = CommitSeq::new(u64_from_i64(row.commit_seq, "Wave 6 disposition commit")?);
    if value.disposition_id != *disposition_id
        || value.proposal_id != proposal_id
        || row.proposal_raw != raw_digest(&proposal.proposal_digest, "Wave 6 proposal digest")?
        || row.proposal_content_raw
            != raw_digest(&proposal.content_digest, "Wave 6 proposal content digest")?
        || row.disposition_kind != disposition_kind(value.disposition)
        || row.reviewer_id != value.human_id.as_str()
        || decided_at != value.decided_at
        || row.reason != value.reason
        || row.content_raw
            != raw_digest(parsed.content_digest(), "Wave 6 disposition content digest")?
        || usize_from_i64(row.byte_length, "Wave 6 disposition byte length")? != row.bytes.len()
        || row.identity_authority != REVIEWER_AUTHORITY
        || row.human_review_verified != 0
        || row.approval_authority != 0
        || row.execution_authority != 0
        || row.result_authority != 0
        || row.semantic_ceiling != CEILING
        || proposal.commit_seq >= commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 research disposition differs from exact bytes or proposal lineage"
                .into(),
        ));
    }
    Ok(StoredWave6FixtureResearchDisposition {
        batch_id: stable(&row.batch_id, "Wave 6 disposition batch ID")?,
        disposition_id: disposition_id.clone(),
        proposal_id,
        proposal_digest: proposal.proposal_digest,
        proposal_content_digest: proposal.content_digest,
        disposition: value.disposition,
        reviewer_id: value.human_id.clone(),
        decided_at,
        reason: value.reason.clone(),
        exact_bytes: row.bytes,
        content_digest: parsed.content_digest().clone(),
        commit_seq,
        commit_digest: qualified_digest(
            &row.commit_digest_raw,
            "Wave 6 disposition commit digest",
        )?,
        authority_boundary: ResearchDispositionAuthorityV1::CallerFedFixtureUnverifiedNoHumanReviewApprovalExecutionOrResult,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
}

fn reject_second_disposition_batch(
    store: &SqliteStore,
    disposition_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_fixture_research_disposition_v1 disposition
             JOIN ingest_commit commit_row ON commit_row.commit_seq=disposition.created_commit_seq
             WHERE disposition.disposition_id=?1",
            [disposition_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|stored| stored != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 fixture research disposition",
            identity: disposition_id.to_string(),
        });
    }
    Ok(())
}

fn disposition_operation_digest(
    proposal_id: &StableString,
    disposition_id: &StableString,
    content_digest: &ValueDigest,
) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6-fixture-research-disposition-commit.v1",
        proposal_id,
        disposition_id,
        content_digest,
    ))?)
}

const fn disposition_kind(value: ResearchDispositionKindV1) -> &'static str {
    match value {
        ResearchDispositionKindV1::Accept => "accept",
        ResearchDispositionKindV1::Reject => "reject",
        ResearchDispositionKindV1::Hold => "hold",
        ResearchDispositionKindV1::Supersede => "supersede",
    }
}

fn proposal_operation_digest(
    program_id: &StableString,
    proposal_id: &StableString,
    proposal_digest: &ValueDigest,
    content_digest: &ValueDigest,
) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6-fixture-research-proposal-commit.v1",
        program_id,
        proposal_id,
        proposal_digest,
        content_digest,
    ))?)
}

fn digest_bytes(bytes: &[u8]) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}

fn raw_digest<'a>(value: &'a ValueDigest, field: &'static str) -> Result<&'a str> {
    value
        .as_str()
        .strip_prefix("sha256:")
        .filter(|raw| {
            raw.len() == 64
                && raw
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
        .ok_or_else(|| StoreError::InvalidBatch(format!("{field} is not canonical SHA-256")))
}

fn qualified_digest(raw: &str, field: &'static str) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{raw}"))
        .map_err(|error| StoreError::InvalidBatch(format!("{field}: {error}")))
}

fn stable(value: &str, field: &'static str) -> Result<StableString> {
    StableString::new(value.to_owned())
        .map_err(|error| StoreError::InvalidBatch(format!("{field}: {error}")))
}

fn checked_len(value: usize, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn sqlite_usize(value: usize, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn sqlite_u64(value: u64, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn usize_from_i64(value: i64, field: &'static str) -> Result<usize> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn u64_from_i64(value: i64, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{StoreConfig, StoreMode};
    use std::time::Duration;

    const PROGRAM: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
    const PROPOSAL: &[u8] = include_bytes!("../../../fixtures/wave6/research_proposal_v1.json");
    const DISPOSITION: &[u8] =
        include_bytes!("../../../fixtures/wave6/research_disposition_v1.json");

    const SCHEMAS: [(&str, &[u8]); 4] = [
        (
            "known_truth_evaluation_fixture",
            include_bytes!("../../../fixtures/wave6/schemas/known_truth_evaluation_v1.json"),
        ),
        (
            "protocol_known_truth_evaluation_fixture",
            include_bytes!(
                "../../../fixtures/wave6/schemas/protocol_known_truth_evaluation_v1.json"
            ),
        ),
        (
            RESEARCH_PROPOSAL_KIND,
            include_bytes!("../../../fixtures/wave6/schemas/research_proposal_v1.json"),
        ),
        (
            "structural_known_truth_evaluation_fixture",
            include_bytes!(
                "../../../fixtures/wave6/schemas/structural_known_truth_evaluation_v1.json"
            ),
        ),
    ];

    const ARTIFACTS: [(&str, &[u8]); 3] = [
        (
            "known_truth_evaluation_fixture",
            include_bytes!("../../../fixtures/wave6/artifacts/known_truth_evaluation_v1.json"),
        ),
        (
            "protocol_known_truth_evaluation_fixture",
            include_bytes!(
                "../../../fixtures/wave6/artifacts/protocol_known_truth_evaluation_v1.json"
            ),
        ),
        (
            "structural_known_truth_evaluation_fixture",
            include_bytes!(
                "../../../fixtures/wave6/artifacts/structural_known_truth_evaluation_v1.json"
            ),
        ),
    ];

    fn config(root: &std::path::Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(2),
            catalog_id: StableString::new("wave6-research-test").expect("catalog ID"),
            max_observations_per_batch: 256,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        }
    }

    fn prepare_program_and_schemas(
        root: &std::path::Path,
    ) -> (SqliteStore, StableString, StableString) {
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("writer store");
        let migration = store
            .migrate(
                "2026-08-18T18:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        assert_eq!(migration.current, 19);
        let build = StableString::new("wave6-research-store-test").expect("build ID");
        let program = store
            .commit_wave6_program_registration_v1(
                PROGRAM,
                StableString::new("wave6:research-program").expect("program batch"),
                build.clone(),
            )
            .expect("program registration");
        for (kind, bytes) in SCHEMAS {
            store
                .commit_wave6_artifact_schema_v1(
                    &program.program_id,
                    StableString::new(kind).expect("kind"),
                    bytes,
                    StableString::new(format!("wave6:research-schema:{kind}"))
                        .expect("schema batch"),
                    build.clone(),
                )
                .unwrap_or_else(|error| panic!("schema {kind}: {error}"));
        }
        (store, program.program_id, build)
    }

    fn prepare(root: &std::path::Path) -> (SqliteStore, StableString, StableString) {
        let (mut store, program_id, build) = prepare_program_and_schemas(root);
        for (kind, bytes) in ARTIFACTS {
            store
                .commit_wave6_fixture_artifact_v1(
                    &program_id,
                    StableString::new(kind).expect("kind"),
                    bytes,
                    StableString::new(format!("wave6:research-artifact:{kind}"))
                        .expect("artifact batch"),
                    build.clone(),
                )
                .unwrap_or_else(|error| panic!("artifact {kind}: {error}"));
        }
        (store, program_id, build)
    }

    #[test]
    fn exact_proposal_resolves_prior_evaluations_and_restarts_without_promotion() {
        let root = tempfile::tempdir().expect("temporary store");
        let store_config = config(root.path());
        let (mut store, program_id, build) = prepare(root.path());
        let batch = StableString::new("wave6:research-proposal:fixture-001").expect("batch");
        let accepted = store
            .commit_wave6_fixture_research_proposal_v1(
                &program_id,
                PROPOSAL,
                batch.clone(),
                build.clone(),
            )
            .expect("proposal");
        assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v19");
        assert_eq!(accepted.status, IdempotencyStatus::Accepted);
        assert_eq!(accepted.descriptor_count, 3);
        assert_eq!(accepted.counterexample_count, 18);
        assert_eq!(accepted.experiment_count, 1);
        assert_eq!(accepted.total_experiment_units, 3);
        assert_eq!(accepted.maximum_fixture_alleged_commit_seq, 12);
        assert!(accepted.maximum_resolved_artifact_commit_seq < accepted.commit_seq);
        assert_eq!(
            accepted.semantic_ceiling,
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
        let retry = store
            .commit_wave6_fixture_research_proposal_v1(&program_id, PROPOSAL, batch, build)
            .expect("idempotent proposal");
        assert_eq!(retry.status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.commit_seq, accepted.commit_seq);
        assert_eq!(retry.commit_digest, accepted.commit_digest);
        drop(store);

        let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly).expect("reader store");
        let stored = reopened
            .load_wave6_fixture_research_proposal_v1(&accepted.proposal_id)
            .expect("proposal readback")
            .expect("stored proposal");
        assert_eq!(stored.exact_bytes, PROPOSAL);
        assert_eq!(stored.artifact_bindings.len(), 3);
        assert_eq!(stored.content_digest, accepted.content_digest);
        assert_eq!(stored.commit_digest, accepted.commit_digest);
    }

    #[test]
    fn proposal_refuses_missing_evaluation() {
        let root = tempfile::tempdir().expect("temporary store");
        let (mut store, program_id, build) = prepare_program_and_schemas(root.path());
        assert!(matches!(
            store.commit_wave6_fixture_research_proposal_v1(
                &program_id,
                PROPOSAL,
                StableString::new("wave6:research-proposal:missing-evaluation").expect("batch"),
                build,
            ),
            Err(StoreError::MissingIdentity {
                kind: "Wave 6 research evaluation artifact",
                ..
            })
        ));
    }

    #[test]
    fn proposal_refuses_changed_bytes_and_second_batch() {
        let root = tempfile::tempdir().expect("temporary store");
        let (mut store, program_id, build) = prepare(root.path());
        let batch = StableString::new("wave6:research-proposal:fixture-001").expect("batch");
        store
            .commit_wave6_fixture_research_proposal_v1(
                &program_id,
                PROPOSAL,
                batch.clone(),
                build.clone(),
            )
            .expect("proposal");
        let mut changed = PROPOSAL.to_vec();
        let position = changed
            .windows(b"query_count\":0".len())
            .position(|window| window == b"query_count\":0")
            .expect("query count");
        changed[position + b"query_count\":".len()] = b'1';
        assert!(
            store
                .commit_wave6_fixture_research_proposal_v1(
                    &program_id,
                    &changed,
                    batch,
                    build.clone(),
                )
                .is_err()
        );
        assert!(matches!(
            store.commit_wave6_fixture_research_proposal_v1(
                &program_id,
                PROPOSAL,
                StableString::new("wave6:research-proposal:second").expect("second batch"),
                build,
            ),
            Err(StoreError::IdentityConflict { .. })
        ));
    }

    #[test]
    fn exact_disposition_resolves_proposal_retries_and_reopens_without_review_authority() {
        let root = tempfile::tempdir().expect("temporary store");
        let store_config = config(root.path());
        let (mut store, program_id, build) = prepare(root.path());
        let proposal = store
            .commit_wave6_fixture_research_proposal_v1(
                &program_id,
                PROPOSAL,
                StableString::new("wave6:research-proposal:fixture-001").expect("proposal batch"),
                build.clone(),
            )
            .expect("proposal");
        let batch = StableString::new("wave6:research-disposition:fixture-001").expect("batch");
        let accepted = store
            .commit_wave6_fixture_research_disposition_v1(
                &proposal.proposal_id,
                DISPOSITION,
                batch.clone(),
                build.clone(),
            )
            .expect("disposition");
        assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v19");
        assert_eq!(accepted.status, IdempotencyStatus::Accepted);
        assert_eq!(accepted.disposition, ResearchDispositionKindV1::Hold);
        assert!(!accepted.authority_boundary.human_review_verified());
        assert!(!accepted.authority_boundary.approval_authority());
        assert!(!accepted.authority_boundary.execution_authority());
        assert!(!accepted.authority_boundary.result_authority());
        let retry = store
            .commit_wave6_fixture_research_disposition_v1(
                &proposal.proposal_id,
                DISPOSITION,
                batch,
                build,
            )
            .expect("idempotent disposition");
        assert_eq!(retry.status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.commit_seq, accepted.commit_seq);
        assert_eq!(retry.commit_digest, accepted.commit_digest);
        drop(store);

        let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly).expect("reader store");
        let stored = reopened
            .load_wave6_fixture_research_disposition_v1(&accepted.disposition_id)
            .expect("disposition readback")
            .expect("stored disposition");
        assert_eq!(stored.exact_bytes, DISPOSITION);
        assert_eq!(stored.proposal_digest, accepted.proposal_digest);
        assert_eq!(stored.commit_digest, accepted.commit_digest);
        assert!(!stored.authority_boundary.human_review_verified());
    }

    #[test]
    fn disposition_refuses_missing_proposal_changed_bytes_and_second_batch() {
        let missing_root = tempfile::tempdir().expect("missing temporary store");
        let mut missing =
            SqliteStore::open(config(missing_root.path()), StoreMode::SingleWriter).expect("store");
        missing
            .migrate(
                "2026-08-18T18:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("migration");
        let proposal_id = StableString::new("research-proposal-482af6e85fb9edae5a00eccf29af12b2")
            .expect("proposal ID");
        assert!(matches!(
            missing.commit_wave6_fixture_research_disposition_v1(
                &proposal_id,
                DISPOSITION,
                StableString::new("wave6:research-disposition:missing").expect("batch"),
                StableString::new("wave6-research-store-test").expect("build"),
            ),
            Err(StoreError::MissingIdentity {
                kind: "Wave 6 fixture research proposal",
                ..
            })
        ));

        let root = tempfile::tempdir().expect("temporary store");
        let (mut store, program_id, build) = prepare(root.path());
        let proposal = store
            .commit_wave6_fixture_research_proposal_v1(
                &program_id,
                PROPOSAL,
                StableString::new("wave6:research-proposal:fixture-001").expect("proposal batch"),
                build.clone(),
            )
            .expect("proposal");
        let batch = StableString::new("wave6:research-disposition:fixture-001").expect("batch");
        store
            .commit_wave6_fixture_research_disposition_v1(
                &proposal.proposal_id,
                DISPOSITION,
                batch.clone(),
                build.clone(),
            )
            .expect("disposition");
        let mut changed = DISPOSITION.to_vec();
        let position = changed
            .windows(b"fixture-only hold".len())
            .position(|window| window == b"fixture-only hold")
            .expect("reason");
        changed[position] = b'F';
        assert!(
            store
                .commit_wave6_fixture_research_disposition_v1(
                    &proposal.proposal_id,
                    &changed,
                    batch,
                    build.clone(),
                )
                .is_err()
        );
        assert!(matches!(
            store.commit_wave6_fixture_research_disposition_v1(
                &proposal.proposal_id,
                DISPOSITION,
                StableString::new("wave6:research-disposition:second").expect("second batch"),
                build,
            ),
            Err(StoreError::IdentityConflict { .. })
        ));
    }
}
