//! Sole-store retention for one exact, caller-fed Wave 6 campaign fixture bundle.
//!
//! This module commits the five already-validated campaign documents atomically. It does not turn
//! their fixture clocks, alleged commit sequences, assignments, evidence, or outcomes into a
//! prospective journal or observed truth.

use crate::{IdempotencyStatus, Result, SqliteStore, StoreError};
use joshi_domain::{CommitSeq, StableString, ValueDigest};
use joshi_wave6_campaign::{
    CAMPAIGN_ARTIFACT_KIND, CAMPAIGN_REGISTRATION_CONTRACT, CAMPAIGN_REGISTRATION_SCHEMA_BYTES,
    CampaignAdjudicationV1, CampaignAssignmentV1, CampaignRegistrationV1, CampaignSealV1,
    FrozenEnrollmentV1, UnverifiedSemantic, parse_campaign_adjudication_exact,
    parse_campaign_assignment_exact, parse_campaign_registration_exact, parse_campaign_seal_exact,
    parse_frozen_enrollment_exact,
};
use joshi_wave6_registry::{
    SemanticCeilingV1, ValidatedProgramRegistration, parse_program_registration_exact,
};
use rusqlite::{OptionalExtension as _, params};
use serde::Serialize;
use sha2::{Digest as _, Sha256};

const MAX_BUNDLE_BYTES: usize = 1024 * 1024;
const FIXTURE_AUTHORITY: &str = "read_record_replay_propose_shadow_only";
const FIXTURE_CEILING: &str = "unverified_semantic_fixture_only";

/// Exact canonical campaign documents supplied to the store as one atomic fixture bundle.
#[derive(Clone, Copy, Debug)]
pub struct Wave6FixtureCampaignBundleBytes<'a> {
    /// Exact campaign registration bytes.
    pub registration: &'a [u8],
    /// Exact frozen enrollment bytes.
    pub enrollment: &'a [u8],
    /// Exact assignment bytes.
    pub assignment: &'a [u8],
    /// Exact evidence-seal bytes.
    pub seal: &'a [u8],
    /// Exact adjudication bytes.
    pub adjudication: &'a [u8],
}

impl Wave6FixtureCampaignBundleBytes<'_> {
    fn total_len(self) -> Result<usize> {
        [
            self.registration.len(),
            self.enrollment.len(),
            self.assignment.len(),
            self.seal.len(),
            self.adjudication.len(),
        ]
        .into_iter()
        .try_fold(0_usize, |total, length| {
            total.checked_add(length).ok_or_else(|| {
                StoreError::InvalidBatch("Wave 6 campaign bundle byte length overflow".into())
            })
        })
    }
}

/// Durable receipt for one exact fixture-only campaign bundle.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6FixtureCampaignBundleReceipt {
    /// Store catalog identity.
    pub catalog_id: StableString,
    /// Store catalog schema.
    pub catalog_schema: StableString,
    /// Idempotent store batch identity.
    pub batch_id: StableString,
    /// Derived bundle identity.
    pub bundle_id: StableString,
    /// Owning Wave 6 program.
    pub program_id: StableString,
    /// Caller-fed campaign identity.
    pub campaign_id: StableString,
    /// Semantic digest of the campaign registration.
    pub registration_digest: ValueDigest,
    /// Semantic digest of the frozen enrollment.
    pub enrollment_digest: ValueDigest,
    /// Semantic digest of the assignment.
    pub assignment_digest: ValueDigest,
    /// Semantic digest of the evidence seal.
    pub seal_digest: ValueDigest,
    /// Semantic digest of the adjudication.
    pub adjudication_digest: ValueDigest,
    /// Domain-separated digest over the five physical document digests.
    pub bundle_digest: ValueDigest,
    /// Number of registered eligible subjects.
    pub eligible_subject_count: u64,
    /// Number of included subjects.
    pub included_subject_count: u64,
    /// Number of exact assignments.
    pub assignment_count: u64,
    /// Number of exact outcome dispositions.
    pub outcome_count: u64,
    /// Largest caller-fed alleged commit sequence in the exact fixture chain.
    pub maximum_fixture_alleged_commit_seq: u64,
    /// Store-owned commit sequence.
    pub commit_seq: CommitSeq,
    /// Store-owned commit digest.
    pub commit_digest: ValueDigest,
    /// Fixed nonpromoting semantic ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Whether the exact batch was newly accepted or read back idempotently.
    pub status: IdempotencyStatus,
}

/// Exact campaign bundle re-parsed and reverified after durable readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6FixtureCampaignBundle {
    /// Idempotent store batch identity.
    pub batch_id: StableString,
    /// Derived bundle identity.
    pub bundle_id: StableString,
    /// Owning Wave 6 program.
    pub program_id: StableString,
    /// Caller-fed campaign identity.
    pub campaign_id: StableString,
    /// Semantic digest of the owning N00 registration.
    pub program_registration_digest: ValueDigest,
    /// Commit of the prior registered campaign schema.
    pub schema_commit_seq: CommitSeq,
    /// Exact registration bytes.
    pub registration_bytes: Vec<u8>,
    /// Exact enrollment bytes.
    pub enrollment_bytes: Vec<u8>,
    /// Exact assignment bytes.
    pub assignment_bytes: Vec<u8>,
    /// Exact evidence-seal bytes.
    pub seal_bytes: Vec<u8>,
    /// Exact adjudication bytes.
    pub adjudication_bytes: Vec<u8>,
    /// Semantic digest of the registration.
    pub registration_digest: ValueDigest,
    /// Semantic digest of the enrollment.
    pub enrollment_digest: ValueDigest,
    /// Semantic digest of the assignment.
    pub assignment_digest: ValueDigest,
    /// Semantic digest of the seal.
    pub seal_digest: ValueDigest,
    /// Semantic digest of the adjudication.
    pub adjudication_digest: ValueDigest,
    /// Physical digest of the registration document.
    pub registration_document_digest: ValueDigest,
    /// Physical digest of the enrollment document.
    pub enrollment_document_digest: ValueDigest,
    /// Physical digest of the assignment document.
    pub assignment_document_digest: ValueDigest,
    /// Physical digest of the seal document.
    pub seal_document_digest: ValueDigest,
    /// Physical digest of the adjudication document.
    pub adjudication_document_digest: ValueDigest,
    /// Domain-separated digest over all five physical documents.
    pub bundle_digest: ValueDigest,
    /// Number of eligible subjects.
    pub eligible_subject_count: u64,
    /// Number of included subjects.
    pub included_subject_count: u64,
    /// Number of assignments.
    pub assignment_count: u64,
    /// Number of outcome dispositions.
    pub outcome_count: u64,
    /// Largest caller-fed alleged commit sequence in the fixture chain.
    pub maximum_fixture_alleged_commit_seq: u64,
    /// Store-owned commit sequence.
    pub commit_seq: CommitSeq,
    /// Store-owned commit digest.
    pub commit_digest: ValueDigest,
    /// Fixed nonpromoting semantic ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
}

struct ParsedBundle {
    registration: UnverifiedSemantic<CampaignRegistrationV1>,
    enrollment: UnverifiedSemantic<FrozenEnrollmentV1>,
    assignment: UnverifiedSemantic<CampaignAssignmentV1>,
    seal: UnverifiedSemantic<CampaignSealV1>,
    adjudication: UnverifiedSemantic<CampaignAdjudicationV1>,
}

struct CampaignBundleRow {
    batch_id: String,
    program_id: String,
    program_registration_raw: String,
    campaign_id: String,
    enrollment_id: String,
    assignment_id: String,
    seal_id: String,
    adjudication_id: String,
    registration_semantic_raw: String,
    registration_document_raw: String,
    registration_bytes: Vec<u8>,
    registration_byte_length: i64,
    enrollment_semantic_raw: String,
    enrollment_document_raw: String,
    enrollment_bytes: Vec<u8>,
    enrollment_byte_length: i64,
    assignment_semantic_raw: String,
    assignment_document_raw: String,
    assignment_bytes: Vec<u8>,
    assignment_byte_length: i64,
    seal_semantic_raw: String,
    seal_document_raw: String,
    seal_bytes: Vec<u8>,
    seal_byte_length: i64,
    adjudication_semantic_raw: String,
    adjudication_document_raw: String,
    adjudication_bytes: Vec<u8>,
    adjudication_byte_length: i64,
    bundle_raw: String,
    eligible_subject_count: i64,
    included_subject_count: i64,
    assignment_count: i64,
    outcome_count: i64,
    maximum_fixture_alleged_commit_seq: i64,
    authority: String,
    semantic_ceiling: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

impl SqliteStore {
    /// Atomically retains one exact five-document campaign fixture bundle.
    ///
    /// This proves exact byte durability only. It does not prove prospective registration,
    /// assignment blindness, evidence observation, outcome truth, or adjudication authority.
    ///
    /// # Errors
    ///
    /// Refuses absent prior program/schema rows, empty/oversized/noncanonical documents, broken
    /// chain semantics, conflicting identity, read-only state, or failed exact readback.
    #[allow(clippy::too_many_lines)]
    pub fn commit_wave6_fixture_campaign_bundle_v1(
        &mut self,
        program_id: &StableString,
        bundle: Wave6FixtureCampaignBundleBytes<'_>,
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6FixtureCampaignBundleReceipt> {
        if [
            bundle.registration,
            bundle.enrollment,
            bundle.assignment,
            bundle.seal,
            bundle.adjudication,
        ]
        .into_iter()
        .any(<[u8]>::is_empty)
            || bundle.total_len()? > MAX_BUNDLE_BYTES
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 campaign bundle is empty or exceeds the exact-byte limit".into(),
            ));
        }
        let program = self
            .load_wave6_program_registration_v1(program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            })?;
        let validated_program = parse_program_registration_exact(&program.exact_bytes)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let schema_kind = stable(CAMPAIGN_ARTIFACT_KIND, "Wave 6 campaign schema kind")?;
        let schema = self
            .load_wave6_artifact_schema_v1(program_id, &schema_kind)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 campaign schema",
                identity: format!("{}:{CAMPAIGN_ARTIFACT_KIND}", program_id.as_str()),
            })?;
        if schema.schema_id.as_str() != CAMPAIGN_REGISTRATION_CONTRACT
            || schema.exact_bytes != CAMPAIGN_REGISTRATION_SCHEMA_BYTES
            || schema.commit_seq <= program.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 campaign schema differs from its exact registered contract".into(),
            ));
        }
        let parsed = parse_bundle(bundle, &validated_program)?;
        let value = parsed.registration.value();
        let campaign_id = value.campaign_id.clone();
        reject_second_bundle_batch(self, &campaign_id, &batch_id)?;

        let bundle_digest = campaign_bundle_digest(&parsed)?;
        let bundle_id = campaign_bundle_id(program_id, &campaign_id, &bundle_digest)?;
        let eligible_subject_count = checked_len(
            value.universe.subject_ids.len(),
            "Wave 6 campaign eligible subject count",
        )?;
        let included_subject_count = checked_len(
            parsed
                .enrollment
                .value()
                .dispositions
                .iter()
                .filter(|row| row.included)
                .count(),
            "Wave 6 campaign included subject count",
        )?;
        let assignment_count = checked_len(
            parsed.assignment.value().assignments.len(),
            "Wave 6 campaign assignment count",
        )?;
        let outcome_count = checked_len(
            parsed.adjudication.value().outcomes.len(),
            "Wave 6 campaign outcome count",
        )?;
        let maximum_fixture_alleged_commit_seq = parsed
            .seal
            .value()
            .as_of_commit_seq
            .get()
            .max(parsed.adjudication.value().as_of_commit_seq.get());
        let operation_digest =
            bundle_operation_digest(program_id, &campaign_id, &bundle_id, &bundle_digest)?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &bundle_id,
            &bundle_digest,
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_fixture_campaign_bundle_v1
                     (bundle_id,program_id,program_registration_sha256,campaign_id,
                      registration_semantic_sha256,registration_document_sha256,
                      registration_bytes,registration_byte_length,enrollment_id,
                      enrollment_semantic_sha256,enrollment_document_sha256,enrollment_bytes,
                      enrollment_byte_length,assignment_id,assignment_semantic_sha256,
                      assignment_document_sha256,assignment_bytes,assignment_byte_length,seal_id,
                      seal_semantic_sha256,seal_document_sha256,seal_bytes,seal_byte_length,
                      adjudication_id,adjudication_semantic_sha256,
                      adjudication_document_sha256,adjudication_bytes,
                      adjudication_byte_length,bundle_document_sha256,eligible_subject_count,
                      included_subject_count,assignment_count,outcome_count,
                      maximum_fixture_alleged_commit_seq,authority,semantic_ceiling,
                      created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             ?17,?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28,?29,?30,
                             ?31,?32,?33,?34,?35,?36,?37)",
                    params![
                        bundle_id.as_str(),
                        program_id.as_str(),
                        raw_digest(&program.registration_digest, "Wave 6 program digest")?,
                        campaign_id.as_str(),
                        raw_digest(
                            &value.campaign_registration_digest,
                            "Wave 6 campaign registration digest"
                        )?,
                        raw_digest(
                            parsed.registration.document_digest(),
                            "Wave 6 campaign registration document"
                        )?,
                        bundle.registration,
                        sqlite_usize(bundle.registration.len(), "Wave 6 registration bytes")?,
                        parsed.enrollment.value().enrollment_id.as_str(),
                        raw_digest(
                            &parsed.enrollment.value().enrollment_digest,
                            "Wave 6 enrollment digest"
                        )?,
                        raw_digest(
                            parsed.enrollment.document_digest(),
                            "Wave 6 enrollment document"
                        )?,
                        bundle.enrollment,
                        sqlite_usize(bundle.enrollment.len(), "Wave 6 enrollment bytes")?,
                        parsed.assignment.value().assignment_id.as_str(),
                        raw_digest(
                            &parsed.assignment.value().assignment_digest,
                            "Wave 6 assignment digest"
                        )?,
                        raw_digest(
                            parsed.assignment.document_digest(),
                            "Wave 6 assignment document"
                        )?,
                        bundle.assignment,
                        sqlite_usize(bundle.assignment.len(), "Wave 6 assignment bytes")?,
                        parsed.seal.value().seal_id.as_str(),
                        raw_digest(
                            &parsed.seal.value().seal_digest,
                            "Wave 6 campaign seal digest"
                        )?,
                        raw_digest(
                            parsed.seal.document_digest(),
                            "Wave 6 campaign seal document"
                        )?,
                        bundle.seal,
                        sqlite_usize(bundle.seal.len(), "Wave 6 seal bytes")?,
                        parsed.adjudication.value().adjudication_id.as_str(),
                        raw_digest(
                            &parsed.adjudication.value().adjudication_digest,
                            "Wave 6 adjudication digest"
                        )?,
                        raw_digest(
                            parsed.adjudication.document_digest(),
                            "Wave 6 adjudication document"
                        )?,
                        bundle.adjudication,
                        sqlite_usize(bundle.adjudication.len(), "Wave 6 adjudication bytes")?,
                        raw_digest(&bundle_digest, "Wave 6 campaign bundle digest")?,
                        sqlite_u64(eligible_subject_count, "Wave 6 eligible subject count")?,
                        sqlite_u64(included_subject_count, "Wave 6 included subject count")?,
                        sqlite_u64(assignment_count, "Wave 6 assignment count")?,
                        sqlite_u64(outcome_count, "Wave 6 outcome count")?,
                        sqlite_u64(
                            maximum_fixture_alleged_commit_seq,
                            "Wave 6 maximum fixture alleged commit"
                        )?,
                        FIXTURE_AUTHORITY,
                        FIXTURE_CEILING,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_fixture_campaign_bundle_v1(&bundle_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 campaign bundle",
                identity: bundle_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.program_id != *program_id
            || stored.campaign_id != campaign_id
            || stored.registration_bytes != bundle.registration
            || stored.enrollment_bytes != bundle.enrollment
            || stored.assignment_bytes != bundle.assignment
            || stored.seal_bytes != bundle.seal
            || stored.adjudication_bytes != bundle.adjudication
            || stored.bundle_digest != bundle_digest
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 campaign bundle readback differs from its exact commit".into(),
            ));
        }
        Ok(Wave6FixtureCampaignBundleReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            bundle_id,
            program_id: program_id.clone(),
            campaign_id,
            registration_digest: stored.registration_digest,
            enrollment_digest: stored.enrollment_digest,
            assignment_digest: stored.assignment_digest,
            seal_digest: stored.seal_digest,
            adjudication_digest: stored.adjudication_digest,
            bundle_digest: stored.bundle_digest,
            eligible_subject_count: stored.eligible_subject_count,
            included_subject_count: stored.included_subject_count,
            assignment_count: stored.assignment_count,
            outcome_count: stored.outcome_count,
            maximum_fixture_alleged_commit_seq: stored.maximum_fixture_alleged_commit_seq,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            semantic_ceiling: stored.semantic_ceiling,
            status: generic.status,
        })
    }

    /// Loads and independently reparses one exact fixture campaign bundle.
    ///
    /// # Errors
    ///
    /// Refuses changed bytes or columns, broken prior program/schema lineage, malformed digests,
    /// or a commit inconsistent with the exact bundle.
    pub fn load_wave6_fixture_campaign_bundle_v1(
        &self,
        bundle_id: &StableString,
    ) -> Result<Option<StoredWave6FixtureCampaignBundle>> {
        let row = self
            .connection
            .query_row(
                "SELECT commit_row.commit_id,bundle.program_id,
                        bundle.program_registration_sha256,bundle.campaign_id,
                        bundle.enrollment_id,bundle.assignment_id,bundle.seal_id,
                        bundle.adjudication_id,
                        bundle.registration_semantic_sha256,
                        bundle.registration_document_sha256,bundle.registration_bytes,
                        bundle.registration_byte_length,bundle.enrollment_semantic_sha256,
                        bundle.enrollment_document_sha256,bundle.enrollment_bytes,
                        bundle.enrollment_byte_length,bundle.assignment_semantic_sha256,
                        bundle.assignment_document_sha256,bundle.assignment_bytes,
                        bundle.assignment_byte_length,bundle.seal_semantic_sha256,
                        bundle.seal_document_sha256,bundle.seal_bytes,bundle.seal_byte_length,
                        bundle.adjudication_semantic_sha256,
                        bundle.adjudication_document_sha256,bundle.adjudication_bytes,
                        bundle.adjudication_byte_length,bundle.bundle_document_sha256,
                        bundle.eligible_subject_count,bundle.included_subject_count,
                        bundle.assignment_count,bundle.outcome_count,
                        bundle.maximum_fixture_alleged_commit_seq,bundle.authority,
                        bundle.semantic_ceiling,bundle.created_commit_seq,commit_row.commit_digest
                 FROM wave6_fixture_campaign_bundle_v1 bundle
                 JOIN ingest_commit commit_row ON commit_row.commit_seq=bundle.created_commit_seq
                 WHERE bundle.bundle_id=?1",
                [bundle_id.as_str()],
                |row| {
                    Ok(CampaignBundleRow {
                        batch_id: row.get(0)?,
                        program_id: row.get(1)?,
                        program_registration_raw: row.get(2)?,
                        campaign_id: row.get(3)?,
                        enrollment_id: row.get(4)?,
                        assignment_id: row.get(5)?,
                        seal_id: row.get(6)?,
                        adjudication_id: row.get(7)?,
                        registration_semantic_raw: row.get(8)?,
                        registration_document_raw: row.get(9)?,
                        registration_bytes: row.get(10)?,
                        registration_byte_length: row.get(11)?,
                        enrollment_semantic_raw: row.get(12)?,
                        enrollment_document_raw: row.get(13)?,
                        enrollment_bytes: row.get(14)?,
                        enrollment_byte_length: row.get(15)?,
                        assignment_semantic_raw: row.get(16)?,
                        assignment_document_raw: row.get(17)?,
                        assignment_bytes: row.get(18)?,
                        assignment_byte_length: row.get(19)?,
                        seal_semantic_raw: row.get(20)?,
                        seal_document_raw: row.get(21)?,
                        seal_bytes: row.get(22)?,
                        seal_byte_length: row.get(23)?,
                        adjudication_semantic_raw: row.get(24)?,
                        adjudication_document_raw: row.get(25)?,
                        adjudication_bytes: row.get(26)?,
                        adjudication_byte_length: row.get(27)?,
                        bundle_raw: row.get(28)?,
                        eligible_subject_count: row.get(29)?,
                        included_subject_count: row.get(30)?,
                        assignment_count: row.get(31)?,
                        outcome_count: row.get(32)?,
                        maximum_fixture_alleged_commit_seq: row.get(33)?,
                        authority: row.get(34)?,
                        semantic_ceiling: row.get(35)?,
                        commit_seq: row.get(36)?,
                        commit_digest_raw: row.get(37)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        stored_campaign_bundle(self, bundle_id, row).map(Some)
    }
}

fn parse_bundle(
    bundle: Wave6FixtureCampaignBundleBytes<'_>,
    program: &ValidatedProgramRegistration,
) -> Result<ParsedBundle> {
    let registration = parse_campaign_registration_exact(bundle.registration, program)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let enrollment = parse_frozen_enrollment_exact(bundle.enrollment, &registration)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let assignment = parse_campaign_assignment_exact(bundle.assignment, &registration, &enrollment)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let seal = parse_campaign_seal_exact(bundle.seal, &registration, &enrollment, &assignment)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let adjudication =
        parse_campaign_adjudication_exact(bundle.adjudication, &registration, &enrollment, &seal)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    Ok(ParsedBundle {
        registration,
        enrollment,
        assignment,
        seal,
        adjudication,
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CampaignBundleDigestMaterial<'a> {
    contract: &'static str,
    registration_document_digest: &'a ValueDigest,
    enrollment_document_digest: &'a ValueDigest,
    assignment_document_digest: &'a ValueDigest,
    seal_document_digest: &'a ValueDigest,
    adjudication_document_digest: &'a ValueDigest,
}

fn campaign_bundle_digest(parsed: &ParsedBundle) -> Result<ValueDigest> {
    let material = CampaignBundleDigestMaterial {
        contract: "joshi.store.wave6-fixture-campaign-bundle.v1",
        registration_document_digest: parsed.registration.document_digest(),
        enrollment_document_digest: parsed.enrollment.document_digest(),
        assignment_document_digest: parsed.assignment.document_digest(),
        seal_document_digest: parsed.seal.document_digest(),
        adjudication_document_digest: parsed.adjudication.document_digest(),
    };
    digest_bytes(&serde_json::to_vec(&material)?)
}

fn campaign_bundle_id(
    program_id: &StableString,
    campaign_id: &StableString,
    bundle_digest: &ValueDigest,
) -> Result<StableString> {
    let identity_digest = digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6-fixture-campaign-bundle-id.v1",
        program_id,
        campaign_id,
        bundle_digest,
    ))?)?;
    stable(
        &format!(
            "wave6-campaign:{}",
            raw_digest(&identity_digest, "Wave 6 campaign identity digest")?
        ),
        "Wave 6 campaign bundle ID",
    )
}

fn bundle_operation_digest(
    program_id: &StableString,
    campaign_id: &StableString,
    bundle_id: &StableString,
    bundle_digest: &ValueDigest,
) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6-fixture-campaign-bundle-commit.v1",
        program_id,
        campaign_id,
        bundle_id,
        bundle_digest,
    ))?)
}

fn reject_second_bundle_batch(
    store: &SqliteStore,
    campaign_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_fixture_campaign_bundle_v1 bundle
             JOIN ingest_commit commit_row ON commit_row.commit_seq=bundle.created_commit_seq
             WHERE bundle.campaign_id=?1",
            [campaign_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|stored| stored != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 fixture campaign bundle",
            identity: campaign_id.to_string(),
        });
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn stored_campaign_bundle(
    store: &SqliteStore,
    bundle_id: &StableString,
    row: CampaignBundleRow,
) -> Result<StoredWave6FixtureCampaignBundle> {
    let program_id = stable(&row.program_id, "Wave 6 campaign program ID")?;
    let campaign_id = stable(&row.campaign_id, "Wave 6 campaign ID")?;
    let program = store
        .load_wave6_program_registration_v1(&program_id)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 program registration",
            identity: program_id.to_string(),
        })?;
    let schema_kind = stable(CAMPAIGN_ARTIFACT_KIND, "Wave 6 campaign schema kind")?;
    let schema = store
        .load_wave6_artifact_schema_v1(&program_id, &schema_kind)?
        .ok_or_else(|| StoreError::MissingIdentity {
            kind: "Wave 6 campaign schema",
            identity: format!("{}:{CAMPAIGN_ARTIFACT_KIND}", program_id.as_str()),
        })?;
    let validated_program = parse_program_registration_exact(&program.exact_bytes)
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
    let exact = Wave6FixtureCampaignBundleBytes {
        registration: &row.registration_bytes,
        enrollment: &row.enrollment_bytes,
        assignment: &row.assignment_bytes,
        seal: &row.seal_bytes,
        adjudication: &row.adjudication_bytes,
    };
    let parsed = parse_bundle(exact, &validated_program)?;
    let expected_bundle_digest = campaign_bundle_digest(&parsed)?;
    let expected_bundle_id =
        campaign_bundle_id(&program_id, &campaign_id, &expected_bundle_digest)?;
    let eligible_subject_count = checked_len(
        parsed.registration.value().universe.subject_ids.len(),
        "Wave 6 eligible subject count",
    )?;
    let included_subject_count = checked_len(
        parsed
            .enrollment
            .value()
            .dispositions
            .iter()
            .filter(|entry| entry.included)
            .count(),
        "Wave 6 included subject count",
    )?;
    let assignment_count = checked_len(
        parsed.assignment.value().assignments.len(),
        "Wave 6 assignment count",
    )?;
    let outcome_count = checked_len(
        parsed.adjudication.value().outcomes.len(),
        "Wave 6 outcome count",
    )?;
    let maximum_fixture_alleged_commit_seq = parsed
        .seal
        .value()
        .as_of_commit_seq
        .get()
        .max(parsed.adjudication.value().as_of_commit_seq.get());
    let commit_seq = CommitSeq::new(u64_from_i64(row.commit_seq, "Wave 6 campaign commit")?);
    let byte_lengths = [
        (row.registration_byte_length, row.registration_bytes.len()),
        (row.enrollment_byte_length, row.enrollment_bytes.len()),
        (row.assignment_byte_length, row.assignment_bytes.len()),
        (row.seal_byte_length, row.seal_bytes.len()),
        (row.adjudication_byte_length, row.adjudication_bytes.len()),
    ];
    if expected_bundle_id != *bundle_id
        || parsed.registration.value().campaign_id != campaign_id
        || row.enrollment_id != parsed.enrollment.value().enrollment_id.as_str()
        || row.assignment_id != parsed.assignment.value().assignment_id.as_str()
        || row.seal_id != parsed.seal.value().seal_id.as_str()
        || row.adjudication_id != parsed.adjudication.value().adjudication_id.as_str()
        || row.program_registration_raw
            != raw_digest(&program.registration_digest, "Wave 6 program digest")?
        || row.registration_semantic_raw
            != raw_digest(
                &parsed.registration.value().campaign_registration_digest,
                "Wave 6 campaign registration digest",
            )?
        || row.registration_document_raw
            != raw_digest(
                parsed.registration.document_digest(),
                "Wave 6 registration document",
            )?
        || row.enrollment_semantic_raw
            != raw_digest(
                &parsed.enrollment.value().enrollment_digest,
                "Wave 6 enrollment digest",
            )?
        || row.enrollment_document_raw
            != raw_digest(
                parsed.enrollment.document_digest(),
                "Wave 6 enrollment document",
            )?
        || row.assignment_semantic_raw
            != raw_digest(
                &parsed.assignment.value().assignment_digest,
                "Wave 6 assignment digest",
            )?
        || row.assignment_document_raw
            != raw_digest(
                parsed.assignment.document_digest(),
                "Wave 6 assignment document",
            )?
        || row.seal_semantic_raw
            != raw_digest(&parsed.seal.value().seal_digest, "Wave 6 seal digest")?
        || row.seal_document_raw
            != raw_digest(parsed.seal.document_digest(), "Wave 6 seal document")?
        || row.adjudication_semantic_raw
            != raw_digest(
                &parsed.adjudication.value().adjudication_digest,
                "Wave 6 adjudication digest",
            )?
        || row.adjudication_document_raw
            != raw_digest(
                parsed.adjudication.document_digest(),
                "Wave 6 adjudication document",
            )?
        || row.bundle_raw != raw_digest(&expected_bundle_digest, "Wave 6 campaign bundle digest")?
        || byte_lengths.into_iter().any(|(stored, actual)| {
            usize::try_from(stored)
                .ok()
                .is_none_or(|length| length != actual)
        })
        || u64_from_i64(row.eligible_subject_count, "Wave 6 eligible subject count")?
            != eligible_subject_count
        || u64_from_i64(row.included_subject_count, "Wave 6 included subject count")?
            != included_subject_count
        || u64_from_i64(row.assignment_count, "Wave 6 assignment count")? != assignment_count
        || u64_from_i64(row.outcome_count, "Wave 6 outcome count")? != outcome_count
        || u64_from_i64(
            row.maximum_fixture_alleged_commit_seq,
            "Wave 6 maximum fixture alleged commit",
        )? != maximum_fixture_alleged_commit_seq
        || row.authority != FIXTURE_AUTHORITY
        || row.semantic_ceiling != FIXTURE_CEILING
        || schema.schema_id.as_str() != CAMPAIGN_REGISTRATION_CONTRACT
        || schema.exact_bytes != CAMPAIGN_REGISTRATION_SCHEMA_BYTES
        || schema.commit_seq >= commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "persisted Wave 6 campaign bundle differs from exact bytes or prior lineage".into(),
        ));
    }
    Ok(StoredWave6FixtureCampaignBundle {
        batch_id: stable(&row.batch_id, "Wave 6 campaign batch ID")?,
        bundle_id: bundle_id.clone(),
        program_id,
        campaign_id,
        program_registration_digest: program.registration_digest,
        schema_commit_seq: schema.commit_seq,
        registration_bytes: row.registration_bytes,
        enrollment_bytes: row.enrollment_bytes,
        assignment_bytes: row.assignment_bytes,
        seal_bytes: row.seal_bytes,
        adjudication_bytes: row.adjudication_bytes,
        registration_digest: parsed
            .registration
            .value()
            .campaign_registration_digest
            .clone(),
        enrollment_digest: parsed.enrollment.value().enrollment_digest.clone(),
        assignment_digest: parsed.assignment.value().assignment_digest.clone(),
        seal_digest: parsed.seal.value().seal_digest.clone(),
        adjudication_digest: parsed.adjudication.value().adjudication_digest.clone(),
        registration_document_digest: parsed.registration.document_digest().clone(),
        enrollment_document_digest: parsed.enrollment.document_digest().clone(),
        assignment_document_digest: parsed.assignment.document_digest().clone(),
        seal_document_digest: parsed.seal.document_digest().clone(),
        adjudication_document_digest: parsed.adjudication.document_digest().clone(),
        bundle_digest: expected_bundle_digest,
        eligible_subject_count,
        included_subject_count,
        assignment_count,
        outcome_count,
        maximum_fixture_alleged_commit_seq,
        commit_seq,
        commit_digest: qualified_digest(&row.commit_digest_raw, "Wave 6 campaign commit digest")?,
        semantic_ceiling: SemanticCeilingV1::UnverifiedSemanticFixtureOnly,
    })
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
    const REGISTRATION: &[u8] =
        include_bytes!("../../../fixtures/wave6/campaign/registration_v1.json");
    const ENROLLMENT: &[u8] = include_bytes!("../../../fixtures/wave6/campaign/enrollment_v1.json");
    const ASSIGNMENT: &[u8] = include_bytes!("../../../fixtures/wave6/campaign/assignment_v1.json");
    const SEAL: &[u8] = include_bytes!("../../../fixtures/wave6/campaign/seal_v1.json");
    const ADJUDICATION: &[u8] =
        include_bytes!("../../../fixtures/wave6/campaign/adjudication_v1.json");

    fn config(root: &std::path::Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(2),
            catalog_id: StableString::new("wave6-campaign-test").expect("catalog ID"),
            max_observations_per_batch: 256,
            max_raw_bytes_per_batch: 4 * 1024 * 1024,
        }
    }

    fn exact_bundle() -> Wave6FixtureCampaignBundleBytes<'static> {
        Wave6FixtureCampaignBundleBytes {
            registration: REGISTRATION,
            enrollment: ENROLLMENT,
            assignment: ASSIGNMENT,
            seal: SEAL,
            adjudication: ADJUDICATION,
        }
    }

    fn prepare_store(root: &std::path::Path) -> (SqliteStore, StableString, StableString) {
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("writer store");
        let migration = store
            .migrate(
                "2026-08-18T17:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        assert_eq!(migration.current, 17);
        let build = StableString::new("wave6-campaign-store-test").expect("build ID");
        let program = store
            .commit_wave6_program_registration_v1(
                PROGRAM,
                StableString::new("wave6:campaign-program").expect("program batch"),
                build.clone(),
            )
            .expect("program registration");
        store
            .commit_wave6_artifact_schema_v1(
                &program.program_id,
                StableString::new(CAMPAIGN_ARTIFACT_KIND).expect("kind"),
                CAMPAIGN_REGISTRATION_SCHEMA_BYTES,
                StableString::new("wave6:campaign-schema").expect("schema batch"),
                build.clone(),
            )
            .expect("campaign schema");
        (store, program.program_id, build)
    }

    #[test]
    fn exact_campaign_bundle_is_atomic_idempotent_and_restart_safe() {
        let root = tempfile::tempdir().expect("temporary store");
        let store_config = config(root.path());
        let (mut store, program_id, build) = prepare_store(root.path());
        let batch = StableString::new("wave6:campaign-bundle:fixture-001").expect("batch");
        let accepted = store
            .commit_wave6_fixture_campaign_bundle_v1(
                &program_id,
                exact_bundle(),
                batch.clone(),
                build.clone(),
            )
            .expect("campaign bundle");
        assert_eq!(accepted.catalog_schema.as_str(), "joshi.sqlite.v17");
        assert_eq!(accepted.status, IdempotencyStatus::Accepted);
        assert_eq!(accepted.eligible_subject_count, 3);
        assert_eq!(accepted.included_subject_count, 2);
        assert_eq!(accepted.assignment_count, 2);
        assert_eq!(accepted.outcome_count, 2);
        assert_eq!(accepted.maximum_fixture_alleged_commit_seq, 21);
        assert_eq!(
            accepted.semantic_ceiling,
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
        let retry = store
            .commit_wave6_fixture_campaign_bundle_v1(&program_id, exact_bundle(), batch, build)
            .expect("idempotent campaign bundle");
        assert_eq!(retry.status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.commit_seq, accepted.commit_seq);
        assert_eq!(retry.commit_digest, accepted.commit_digest);
        drop(store);

        let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly).expect("reader store");
        let stored = reopened
            .load_wave6_fixture_campaign_bundle_v1(&accepted.bundle_id)
            .expect("campaign readback")
            .expect("campaign bundle");
        assert_eq!(stored.registration_bytes, REGISTRATION);
        assert_eq!(stored.enrollment_bytes, ENROLLMENT);
        assert_eq!(stored.assignment_bytes, ASSIGNMENT);
        assert_eq!(stored.seal_bytes, SEAL);
        assert_eq!(stored.adjudication_bytes, ADJUDICATION);
        assert_eq!(stored.bundle_digest, accepted.bundle_digest);
        assert_eq!(stored.commit_digest, accepted.commit_digest);
    }

    #[test]
    fn changed_bytes_and_second_batch_cannot_replace_campaign() {
        let root = tempfile::tempdir().expect("temporary store");
        let (mut store, program_id, build) = prepare_store(root.path());
        let batch = StableString::new("wave6:campaign-bundle:fixture-001").expect("batch");
        store
            .commit_wave6_fixture_campaign_bundle_v1(
                &program_id,
                exact_bundle(),
                batch.clone(),
                build.clone(),
            )
            .expect("campaign bundle");

        let mut changed = ASSIGNMENT.to_vec();
        let position = changed
            .windows(b"assignment-fixture-001".len())
            .position(|window| window == b"assignment-fixture-001")
            .expect("assignment identity");
        changed[position] = b'A';
        let changed_bundle = Wave6FixtureCampaignBundleBytes {
            assignment: &changed,
            ..exact_bundle()
        };
        assert!(
            store
                .commit_wave6_fixture_campaign_bundle_v1(
                    &program_id,
                    changed_bundle,
                    batch,
                    build.clone(),
                )
                .is_err()
        );
        assert!(matches!(
            store.commit_wave6_fixture_campaign_bundle_v1(
                &program_id,
                exact_bundle(),
                StableString::new("wave6:campaign-bundle:second").expect("second batch"),
                build,
            ),
            Err(StoreError::IdentityConflict { .. })
        ));
    }

    #[test]
    fn campaign_bundle_requires_prior_exact_schema() {
        let root = tempfile::tempdir().expect("temporary store");
        let mut store =
            SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("writer store");
        store
            .migrate(
                "2026-08-18T17:00:00.000000Z"
                    .parse()
                    .expect("migration time"),
            )
            .expect("latest migration");
        let build = StableString::new("wave6-campaign-store-test").expect("build ID");
        let program = store
            .commit_wave6_program_registration_v1(
                PROGRAM,
                StableString::new("wave6:campaign-program").expect("program batch"),
                build.clone(),
            )
            .expect("program registration");
        assert!(matches!(
            store.commit_wave6_fixture_campaign_bundle_v1(
                &program.program_id,
                exact_bundle(),
                StableString::new("wave6:campaign-bundle:fixture-001").expect("bundle batch"),
                build,
            ),
            Err(StoreError::MissingIdentity { .. })
        ));
    }
}
