//! Sole-store bridge from durable Wave 5 act/presentation evidence into Wave 6.
//!
//! The bridge deliberately preserves the act's original presentation gap. A later
//! browser-reported mount is separate evidence and cannot be used to infer human viewing,
//! recognition, session identity, or an operator-model result.

use crate::{
    IdempotencyStatus, Result, SqliteStore, StoreError, StoredCockpitV2BrowserPresentation,
    StoredCockpitV2Head, StoredCockpitV2Publication, StoredScientificMemoryOccurrence,
    StoredWave6StoreInputCensus,
    wave6::{
        digest_bytes, qualified_digest, raw_digest, sqlite_len, sqlite_u64, stable, u64_from_i64,
    },
};
use joshi_domain::{CommitSeq, StableString, ValueDigest, WireU64};
use joshi_publication::CockpitV2BrowserPresentationClaimV1;
use joshi_scientific_memory::{MemoryOccurrence, PresentationBinding, SceneBinding};
use rusqlite::{OptionalExtension as _, params};
use serde::{Deserialize, Serialize};

const CONTRACT: &str = "joshi.store.wave6.operator-evidence-input.v1";
const AUTHORITY: &str = "read_record_replay_propose_shadow_only";
const CLAIM_SCOPE: &str =
    "store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model";
const SEMANTIC_CEILING: &str = "store_resolved_operator_evidence_input_only";
const MAX_DOCUMENT_BYTES: usize = 4 * 1024 * 1024;

/// Exact store-built document over one act, its scene, and a separate later presentation claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)] // Negative qualification bits are part of the wire proof.
pub struct Wave6OperatorEvidenceInputV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub binding_id: StableString,
    pub program_id: StableString,
    pub input_census_binding_id: StableString,
    pub input_census_document_digest: ValueDigest,
    pub input_census_commit_seq: CommitSeq,
    pub source_occurrence_id: StableString,
    pub publication_id: StableString,
    pub publication_digest: ValueDigest,
    pub publication_bytes_digest: ValueDigest,
    pub publication_commit_seq: CommitSeq,
    pub head_digest: ValueDigest,
    pub head_bytes_digest: ValueDigest,
    pub head_commit_seq: CommitSeq,
    pub memory_occurrence_id: StableString,
    pub memory_occurrence_digest: ValueDigest,
    pub memory_commit_seq: CommitSeq,
    pub memory_queue_generation: WireU64,
    pub memory_occurrence: MemoryOccurrence,
    pub presentation_claim_id: StableString,
    pub presentation_claim_digest: ValueDigest,
    pub presentation_claim_bytes_digest: ValueDigest,
    pub presentation_commit_seq: CommitSeq,
    pub pairing_session_id: StableString,
    pub presentation_claim: CockpitV2BrowserPresentationClaimV1,
    pub subject_id: StableString,
    pub act_presentation_gap_retained: bool,
    pub presentation_repairs_act_gap: bool,
    pub session_equivalence_claimed: bool,
    pub human_viewing_verified: bool,
    pub recognition_observed: bool,
    pub operator_model_resolved: bool,
    pub authority: StableString,
    pub claim_scope: StableString,
    pub semantic_ceiling: StableString,
}

/// Store receipt for one accepted or exactly retried operator-evidence input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6OperatorEvidenceInputReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub binding_id: StableString,
    pub program_id: StableString,
    pub document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub status: IdempotencyStatus,
}

/// Exact operator-evidence input after durable readback and complete prior rederivation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6OperatorEvidenceInput {
    pub batch_id: StableString,
    pub document: Wave6OperatorEvidenceInputV1,
    pub document_bytes: Vec<u8>,
    pub document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
}

struct ResolvedPriors {
    census: StoredWave6StoreInputCensus,
    publication: StoredCockpitV2Publication,
    head: StoredCockpitV2Head,
    memory: StoredScientificMemoryOccurrence,
    presentation: StoredCockpitV2BrowserPresentation,
}

struct StoredScalars {
    program_id: String,
    census_id: String,
    source_id: String,
    publication_id: String,
    publication_digest: String,
    publication_bytes_digest: String,
    publication_commit: i64,
    head_digest: String,
    head_bytes_digest: String,
    head_commit: i64,
    memory_id: String,
    memory_digest: String,
    memory_commit: i64,
    memory_queue: i64,
    presentation_id: String,
    presentation_digest: String,
    presentation_bytes_digest: String,
    presentation_commit: i64,
    pairing_session_id: String,
    subject_id: String,
    document_digest: String,
    document_bytes: Vec<u8>,
    document_len: i64,
    gap_retained: i64,
    repairs_gap: i64,
    session_equivalence: i64,
    human_viewing: i64,
    recognition: i64,
    operator_model: i64,
    authority: String,
    claim_scope: String,
    ceiling: String,
    commit_seq: i64,
    batch_id: String,
    commit_digest: String,
}

impl SqliteStore {
    /// Builds and commits the exact non-promoting operator-evidence input from durable identities.
    ///
    /// # Errors
    ///
    /// Refuses missing/corrupt priors, cross-source or cross-publication substitution, a memory act
    /// without its original presentation gap, a later claim that omits the act subject, a
    /// conflicting identity/batch, or failed exact postcommit readback.
    #[allow(clippy::too_many_arguments, clippy::too_many_lines)]
    pub fn commit_wave6_operator_evidence_input_v1(
        &mut self,
        program_id: &StableString,
        input_census_binding_id: &StableString,
        memory_occurrence_id: &StableString,
        presentation_claim_id: &StableString,
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6OperatorEvidenceInputReceipt> {
        let priors = self.resolve_operator_evidence_priors(
            program_id,
            input_census_binding_id,
            memory_occurrence_id,
            presentation_claim_id,
        )?;
        let binding_id = operator_binding_id(
            program_id,
            input_census_binding_id,
            memory_occurrence_id,
            presentation_claim_id,
        )?;
        reject_conflicting_batch(self, &binding_id, &batch_id)?;
        let document = build_document(program_id, binding_id.clone(), &priors)?;
        let document_bytes = serde_json::to_vec(&document)?;
        if document_bytes.len() > MAX_DOCUMENT_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 operator-evidence input exceeds the exact-byte limit".into(),
            ));
        }
        let document_digest = digest_bytes(&document_bytes)?;
        let operation_digest = digest_bytes(&serde_json::to_vec(&(
            "joshi.store.wave6_operator_evidence_input_commit.v1",
            binding_id.as_str(),
            priors.census.commit_seq,
            priors.memory.commit_seq,
            priors.presentation.commit_seq,
            document_digest.as_str(),
        ))?)?;
        let subject = document.subject_id.clone();
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &binding_id,
            &document_digest,
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_operator_evidence_input_v1
                     (binding_id,program_id,input_census_binding_id,source_occurrence_id,
                      publication_id,publication_sha256,publication_bytes_sha256,
                      publication_commit_seq,head_sha256,head_bytes_sha256,head_commit_seq,
                      memory_occurrence_id,memory_occurrence_sha256,memory_commit_seq,
                      memory_queue_generation,presentation_claim_id,presentation_claim_sha256,
                      presentation_claim_bytes_sha256,presentation_commit_seq,pairing_session_id,
                      subject_id,
                      document_sha256,document_bytes,document_byte_length,
                      act_presentation_gap_retained,presentation_repairs_act_gap,
                      session_equivalence_claimed,human_viewing_verified,recognition_observed,
                      operator_model_resolved,authority,claim_scope,semantic_ceiling,
                      created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             ?17,?18,?19,?20,?21,?22,?23,?24,1,0,0,0,0,0,?25,?26,?27,?28)",
                    params![
                        binding_id.as_str(),
                        program_id.as_str(),
                        input_census_binding_id.as_str(),
                        document.source_occurrence_id.as_str(),
                        document.publication_id.as_str(),
                        raw_digest(&document.publication_digest, "operator publication")?,
                        raw_digest(
                            &document.publication_bytes_digest,
                            "operator publication bytes"
                        )?,
                        sqlite_u64(document.publication_commit_seq.get(), "publication commit")?,
                        raw_digest(&document.head_digest, "operator head")?,
                        raw_digest(&document.head_bytes_digest, "operator head bytes")?,
                        sqlite_u64(document.head_commit_seq.get(), "head commit")?,
                        memory_occurrence_id.as_str(),
                        raw_digest(&document.memory_occurrence_digest, "operator memory")?,
                        sqlite_u64(document.memory_commit_seq.get(), "memory commit")?,
                        sqlite_u64(
                            document.memory_queue_generation.get(),
                            "memory queue generation"
                        )?,
                        presentation_claim_id.as_str(),
                        raw_digest(&document.presentation_claim_digest, "presentation claim")?,
                        raw_digest(
                            &document.presentation_claim_bytes_digest,
                            "presentation claim bytes"
                        )?,
                        sqlite_u64(
                            document.presentation_commit_seq.get(),
                            "presentation commit"
                        )?,
                        document.pairing_session_id.as_str(),
                        subject.as_str(),
                        raw_digest(&document_digest, "operator input document")?,
                        document_bytes,
                        sqlite_len(document_bytes.len(), "operator input document bytes")?,
                        AUTHORITY,
                        CLAIM_SCOPE,
                        SEMANTIC_CEILING,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave6_operator_evidence_input_v1(&binding_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 operator-evidence input",
                identity: binding_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.document != document
            || stored.document_bytes != document_bytes
            || stored.document_digest != document_digest
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 operator-evidence readback differs from its store-built commit".into(),
            ));
        }
        Ok(Wave6OperatorEvidenceInputReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            binding_id,
            program_id: program_id.clone(),
            document_digest,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            status: generic.status,
        })
    }

    /// Loads and independently rebuilds one exact operator-evidence input from all durable priors.
    ///
    /// # Errors
    ///
    /// Refuses malformed/noncanonical bytes, scalar drift, changed priors, or broken commit order.
    #[allow(clippy::too_many_lines)]
    pub fn load_wave6_operator_evidence_input_v1(
        &self,
        binding_id: &StableString,
    ) -> Result<Option<StoredWave6OperatorEvidenceInput>> {
        let row: Option<StoredScalars> = self
            .connection
            .query_row(
                "SELECT input.program_id,input.input_census_binding_id,input.source_occurrence_id,
                        input.publication_id,input.publication_sha256,
                        input.publication_bytes_sha256,input.publication_commit_seq,
                        input.head_sha256,input.head_bytes_sha256,input.head_commit_seq,
                        input.memory_occurrence_id,input.memory_occurrence_sha256,
                        input.memory_commit_seq,input.memory_queue_generation,
                        input.presentation_claim_id,input.presentation_claim_sha256,
                        input.presentation_claim_bytes_sha256,input.presentation_commit_seq,
                        input.pairing_session_id,input.subject_id,input.document_sha256,input.document_bytes,
                        input.document_byte_length,input.act_presentation_gap_retained,
                        input.presentation_repairs_act_gap,input.session_equivalence_claimed,
                        input.human_viewing_verified,input.recognition_observed,
                        input.operator_model_resolved,input.authority,input.claim_scope,
                        input.semantic_ceiling,input.created_commit_seq,commit_row.commit_id,
                        commit_row.commit_digest
                 FROM wave6_operator_evidence_input_v1 input
                 JOIN ingest_commit commit_row ON commit_row.commit_seq=input.created_commit_seq
                 WHERE input.binding_id=?1",
                [binding_id.as_str()],
                |row| {
                    Ok(StoredScalars {
                        program_id: row.get(0)?,
                        census_id: row.get(1)?,
                        source_id: row.get(2)?,
                        publication_id: row.get(3)?,
                        publication_digest: row.get(4)?,
                        publication_bytes_digest: row.get(5)?,
                        publication_commit: row.get(6)?,
                        head_digest: row.get(7)?,
                        head_bytes_digest: row.get(8)?,
                        head_commit: row.get(9)?,
                        memory_id: row.get(10)?,
                        memory_digest: row.get(11)?,
                        memory_commit: row.get(12)?,
                        memory_queue: row.get(13)?,
                        presentation_id: row.get(14)?,
                        presentation_digest: row.get(15)?,
                        presentation_bytes_digest: row.get(16)?,
                        presentation_commit: row.get(17)?,
                        pairing_session_id: row.get(18)?,
                        subject_id: row.get(19)?,
                        document_digest: row.get(20)?,
                        document_bytes: row.get(21)?,
                        document_len: row.get(22)?,
                        gap_retained: row.get(23)?,
                        repairs_gap: row.get(24)?,
                        session_equivalence: row.get(25)?,
                        human_viewing: row.get(26)?,
                        recognition: row.get(27)?,
                        operator_model: row.get(28)?,
                        authority: row.get(29)?,
                        claim_scope: row.get(30)?,
                        ceiling: row.get(31)?,
                        commit_seq: row.get(32)?,
                        batch_id: row.get(33)?,
                        commit_digest: row.get(34)?,
                    })
                },
            )
            .optional()?;
        let Some(row) = row else {
            return Ok(None);
        };
        if row.document_bytes.len() > MAX_DOCUMENT_BYTES {
            return Err(StoreError::InvalidBatch(
                "stored Wave 6 operator-evidence input exceeds the exact-byte limit".into(),
            ));
        }
        let document: Wave6OperatorEvidenceInputV1 = serde_json::from_slice(&row.document_bytes)?;
        if serde_json::to_vec(&document)? != row.document_bytes {
            return Err(StoreError::InvalidBatch(
                "stored Wave 6 operator-evidence input is not canonical JSON".into(),
            ));
        }
        let program_id = stable(&row.program_id, "operator input program")?;
        let census_id = stable(&row.census_id, "operator input census")?;
        let memory_id = stable(&row.memory_id, "operator input memory")?;
        let presentation_id = stable(&row.presentation_id, "operator input presentation")?;
        let priors = self.resolve_operator_evidence_priors(
            &program_id,
            &census_id,
            &memory_id,
            &presentation_id,
        )?;
        let expected = build_document(&program_id, binding_id.clone(), &priors)?;
        let document_digest = digest_bytes(&row.document_bytes)?;
        let commit_seq = CommitSeq::new(u64_from_i64(row.commit_seq, "operator input commit")?);
        if document != expected
            || row.source_id != document.source_occurrence_id.as_str()
            || row.publication_id != document.publication_id.as_str()
            || row.publication_digest
                != raw_digest(&document.publication_digest, "operator publication")?
            || row.publication_bytes_digest
                != raw_digest(
                    &document.publication_bytes_digest,
                    "operator publication bytes",
                )?
            || row.publication_commit
                != sqlite_u64(document.publication_commit_seq.get(), "publication commit")?
            || row.head_digest != raw_digest(&document.head_digest, "operator head")?
            || row.head_bytes_digest
                != raw_digest(&document.head_bytes_digest, "operator head bytes")?
            || row.head_commit != sqlite_u64(document.head_commit_seq.get(), "head commit")?
            || row.memory_digest
                != raw_digest(&document.memory_occurrence_digest, "operator memory")?
            || row.memory_commit != sqlite_u64(document.memory_commit_seq.get(), "memory commit")?
            || row.memory_queue
                != sqlite_u64(
                    document.memory_queue_generation.get(),
                    "memory queue generation",
                )?
            || row.presentation_digest
                != raw_digest(&document.presentation_claim_digest, "presentation claim")?
            || row.presentation_bytes_digest
                != raw_digest(
                    &document.presentation_claim_bytes_digest,
                    "presentation claim bytes",
                )?
            || row.presentation_commit
                != sqlite_u64(
                    document.presentation_commit_seq.get(),
                    "presentation commit",
                )?
            || row.pairing_session_id != document.pairing_session_id.as_str()
            || row.subject_id != document.subject_id.as_str()
            || row.document_len
                != sqlite_len(row.document_bytes.len(), "operator input document bytes")?
            || row.document_digest != raw_digest(&document_digest, "operator input document")?
            || row.gap_retained != 1
            || row.repairs_gap != 0
            || row.session_equivalence != 0
            || row.human_viewing != 0
            || row.recognition != 0
            || row.operator_model != 0
            || row.authority != AUTHORITY
            || row.claim_scope != CLAIM_SCOPE
            || row.ceiling != SEMANTIC_CEILING
            || priors.census.commit_seq >= commit_seq
            || priors.memory.commit_seq >= commit_seq
            || priors.presentation.commit_seq >= commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "stored Wave 6 operator-evidence input differs from store rederivation".into(),
            ));
        }
        Ok(Some(StoredWave6OperatorEvidenceInput {
            batch_id: stable(&row.batch_id, "operator input batch")?,
            document,
            document_bytes: row.document_bytes,
            document_digest,
            commit_seq,
            commit_digest: qualified_digest(&row.commit_digest, "operator input commit")?,
        }))
    }

    /// Loads the singular V1 operator-evidence input selected by a fixture program, when present.
    ///
    /// # Errors
    ///
    /// Refuses malformed stored identity or any exact readback/rederivation failure.
    pub fn load_wave6_operator_evidence_input_for_program_v1(
        &self,
        program_id: &StableString,
    ) -> Result<Option<StoredWave6OperatorEvidenceInput>> {
        let binding: Option<String> = self
            .connection
            .query_row(
                "SELECT binding_id FROM wave6_operator_evidence_input_v1 WHERE program_id=?1",
                [program_id.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        binding
            .map(|value| {
                let identity = stable(&value, "operator input identity")?;
                self.load_wave6_operator_evidence_input_v1(&identity)?
                    .ok_or_else(|| StoreError::MissingIdentity {
                        kind: "Wave 6 operator-evidence input",
                        identity: value,
                    })
            })
            .transpose()
    }

    fn resolve_operator_evidence_priors(
        &self,
        program_id: &StableString,
        census_id: &StableString,
        memory_id: &StableString,
        presentation_id: &StableString,
    ) -> Result<ResolvedPriors> {
        let program = self
            .load_wave6_program_registration_v1(program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            })?;
        let census = self
            .load_wave6_store_input_census_v1(census_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 store input census",
                identity: census_id.to_string(),
            })?;
        if census.document.program_id != program.program_id {
            return Err(StoreError::InvalidBatch(
                "operator-evidence census belongs to another Wave 6 program".into(),
            ));
        }
        let memory = self
            .load_scientific_memory_occurrence_v1(memory_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "scientific-memory operator act",
                identity: memory_id.to_string(),
            })?;
        let presentation = self
            .load_cockpit_v2_browser_presentation_v1(presentation_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "browser presentation",
                identity: presentation_id.to_string(),
            })?;
        let publication_id = presentation.claim.publication.publication_id.clone();
        let publication = self
            .load_cockpit_v2_publication_v1(&publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 publication",
                identity: publication_id.to_string(),
            })?;
        let head = self
            .load_cockpit_v2_head_v1(&publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 head",
                identity: publication_id.to_string(),
            })?;
        Ok(ResolvedPriors {
            census,
            publication,
            head,
            memory,
            presentation,
        })
    }
}

#[allow(clippy::too_many_lines)] // Keeps the one exact cross-prior closure visibly contiguous.
fn build_document(
    program_id: &StableString,
    binding_id: StableString,
    priors: &ResolvedPriors,
) -> Result<Wave6OperatorEvidenceInputV1> {
    let source = &priors.census.document.source_occurrence;
    let MemoryOccurrence::OperatorAct(act) = &priors.memory.occurrence else {
        return Err(StoreError::InvalidBatch(
            "Wave 6 operator-evidence input requires an exact operator act".into(),
        ));
    };
    let SceneBinding::Committed(scene) = &act.scene else {
        return Err(StoreError::InvalidBatch(
            "Wave 6 operator-evidence act requires a committed scene".into(),
        ));
    };
    let PresentationBinding::Gap(gap) = &act.presentation else {
        return Err(StoreError::InvalidBatch(
            "Wave 6 operator-evidence V1 requires the original typed presentation gap".into(),
        ));
    };
    let subject = act.subject.as_deref().ok_or_else(|| {
        StoreError::InvalidBatch("Wave 6 operator-evidence act lacks its exact subject".into())
    })?;
    let publication_id = priors.publication.publication.publication_id.as_str();
    if priors
        .census
        .document
        .source_occurrence
        .source_occurrence_id
        != priors.presentation.claim.source_occurrence_id
        || priors.publication.source_occurrence_id != source.source_occurrence_id
        || priors.head.source_occurrence_id != source.source_occurrence_id
        || priors.memory.scene_publication_id.as_str() != publication_id
        || priors
            .presentation
            .claim
            .publication
            .publication_id
            .as_str()
            != publication_id
        || scene.scene_id.as_str() != publication_id
        || scene.scene_digest.as_str() != priors.publication.publication.publication_digest.as_str()
        || scene.catalog_cutoff.value() != priors.publication.commit_seq.get()
        || gap.scene.as_ref() != Some(scene)
        || act.assertion.is_some()
        || !source
            .eligible_subjects
            .iter()
            .any(|candidate| candidate.as_str() == subject)
        || !priors
            .presentation
            .claim
            .rendered_subjects
            .iter()
            .any(|candidate| candidate.as_str() == subject)
        || priors.publication.commit_seq >= priors.head.commit_seq
        || priors.head.commit_seq >= priors.memory.commit_seq
        || priors.memory.commit_seq >= priors.presentation.commit_seq
    {
        return Err(StoreError::InvalidBatch(
            "Wave 6 operator-evidence priors do not close one exact gapped act and later presentation"
                .into(),
        ));
    }
    Ok(Wave6OperatorEvidenceInputV1 {
        contract: stable(CONTRACT, "operator input contract")?,
        schema_version: 1,
        binding_id,
        program_id: program_id.clone(),
        input_census_binding_id: priors.census.document.binding_id.clone(),
        input_census_document_digest: priors.census.document_digest.clone(),
        input_census_commit_seq: priors.census.commit_seq,
        source_occurrence_id: source.source_occurrence_id.clone(),
        publication_id: stable(publication_id, "operator input publication")?,
        publication_digest: priors.publication.publication.publication_digest.clone(),
        publication_bytes_digest: priors.publication.publication_bytes_digest.clone(),
        publication_commit_seq: priors.publication.commit_seq,
        head_digest: priors.head.head.head_digest.clone(),
        head_bytes_digest: priors.head.head_digest.clone(),
        head_commit_seq: priors.head.commit_seq,
        memory_occurrence_id: stable(
            &priors.memory.occurrence.occurrence_id(),
            "operator input memory occurrence",
        )?,
        memory_occurrence_digest: priors.memory.occurrence_digest.clone(),
        memory_commit_seq: priors.memory.commit_seq,
        memory_queue_generation: WireU64::new(priors.memory.queue_generation),
        memory_occurrence: priors.memory.occurrence.clone(),
        presentation_claim_id: priors.presentation.claim.client_presentation_id.clone(),
        presentation_claim_digest: priors.presentation.claim.claim_digest.clone(),
        presentation_claim_bytes_digest: priors.presentation.claim_bytes_digest.clone(),
        presentation_commit_seq: priors.presentation.commit_seq,
        pairing_session_id: priors.presentation.pairing_session_id.clone(),
        presentation_claim: priors.presentation.claim.clone(),
        subject_id: stable(subject, "operator input subject")?,
        act_presentation_gap_retained: true,
        presentation_repairs_act_gap: false,
        session_equivalence_claimed: false,
        human_viewing_verified: false,
        recognition_observed: false,
        operator_model_resolved: false,
        authority: stable(AUTHORITY, "operator input authority")?,
        claim_scope: stable(CLAIM_SCOPE, "operator input claim scope")?,
        semantic_ceiling: stable(SEMANTIC_CEILING, "operator input ceiling")?,
    })
}

fn operator_binding_id(
    program_id: &StableString,
    census_id: &StableString,
    memory_id: &StableString,
    presentation_id: &StableString,
) -> Result<StableString> {
    let digest = digest_bytes(&serde_json::to_vec(&(
        "joshi.store.wave6_operator_evidence_input_identity.v1",
        program_id.as_str(),
        census_id.as_str(),
        memory_id.as_str(),
        presentation_id.as_str(),
    ))?)?;
    stable(
        &format!(
            "wave6-operator-input:{}",
            raw_digest(&digest, "operator input identity")?
        ),
        "operator input identity",
    )
}

fn reject_conflicting_batch(
    store: &SqliteStore,
    binding_id: &StableString,
    batch_id: &StableString,
) -> Result<()> {
    let existing: Option<String> = store
        .connection
        .query_row(
            "SELECT commit_row.commit_id
             FROM wave6_operator_evidence_input_v1 input
             JOIN ingest_commit commit_row ON commit_row.commit_seq=input.created_commit_seq
             WHERE input.binding_id=?1",
            [binding_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|value| value != batch_id.as_str())
    {
        return Err(StoreError::InvalidBatch(
            "Wave 6 operator-evidence identity already belongs to another batch".into(),
        ));
    }
    Ok(())
}
