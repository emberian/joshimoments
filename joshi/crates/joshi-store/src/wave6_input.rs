//! Sole-store bridge from reverified Wave 5 discovery input into the Wave 6 fixture program.
//!
//! The bridge deliberately stops at an input census. It neither constructs nor qualifies the
//! richer six-stratum market-atlas artifact.

use crate::{
    IdempotencyStatus, Result, SqliteStore, StoreError, StoredWave5SourceOccurrence,
    Wave5SourceOccurrenceV1,
};
use joshi_domain::{CommitSeq, StableString, ValueDigest, WireU64};
use joshi_publication::CockpitV2MembershipKind;
use rusqlite::{OptionalExtension as _, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};

const CONTRACT: &str = "joshi.store.wave6.input-census.v1";
const AUTHORITY: &str = "read_record_replay_propose_shadow_only";
const CLAIM_SCOPE: &str =
    "mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution";
const SEMANTIC_CEILING: &str = "store_resolved_offline_fixture_input_census_only";
const MAX_DOCUMENT_BYTES: usize = 4 * 1024 * 1024;

/// Exact store-built document retaining the full reverified Wave 5 input census.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave6StoreInputCensusV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub binding_id: StableString,
    pub program_id: StableString,
    pub source_descriptor_digest: ValueDigest,
    pub source_created_commit_seq: CommitSeq,
    pub source_occurrence: Wave5SourceOccurrenceV1,
    pub fact_count: WireU64,
    pub eligible_subject_count: WireU64,
    pub membership_count: WireU64,
    pub coverage_count: WireU64,
    pub gap_count: WireU64,
    pub hot_subject_count: WireU64,
    pub cold_control_subject_count: WireU64,
    pub store_resolved_source: bool,
    pub market_atlas_resolved: bool,
    pub authority: StableString,
    pub claim_scope: StableString,
    pub semantic_ceiling: StableString,
}

/// Store receipt for one accepted or exactly retried input-census bridge.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave6StoreInputCensusReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub batch_id: StableString,
    pub binding_id: StableString,
    pub program_id: StableString,
    pub source_occurrence_id: StableString,
    pub document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub status: IdempotencyStatus,
}

/// Reparsed and independently rederived input census after durable readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave6StoreInputCensus {
    pub batch_id: StableString,
    pub document: Wave6StoreInputCensusV1,
    pub document_bytes: Vec<u8>,
    pub document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
}

#[derive(Clone, Copy)]
struct CensusCounts {
    facts: usize,
    subjects: usize,
    memberships: usize,
    coverage: usize,
    gaps: usize,
    hot: usize,
    cold: usize,
}

impl SqliteStore {
    /// Builds and commits an exact input census from two prior store-resolved identities.
    ///
    /// # Errors
    ///
    /// Refuses missing or corrupt priors, an empty or one-sided hot/control census, a conflicting
    /// identity/batch, read-only use, or failed exact postcommit readback.
    #[allow(clippy::too_many_lines)] // Keeps the sole exact commit and readback proof contiguous.
    pub fn commit_wave6_store_input_census_v1(
        &mut self,
        program_id: &StableString,
        source_occurrence_id: &StableString,
        batch_id: StableString,
        writer_build: StableString,
    ) -> Result<Wave6StoreInputCensusReceipt> {
        let program = self
            .load_wave6_program_registration_v1(program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_id.to_string(),
            })?;
        let source = self
            .load_wave5_source_occurrence_v1(source_occurrence_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 source occurrence",
                identity: source_occurrence_id.to_string(),
            })?;
        let binding_id = binding_id(program_id, source_occurrence_id)?;
        reject_conflicting_batch(self, &binding_id, &batch_id)?;
        let document = build_document(program_id, &source, binding_id.clone())?;
        let document_bytes = serde_json::to_vec(&document)?;
        if document_bytes.len() > MAX_DOCUMENT_BYTES {
            return Err(StoreError::InvalidBatch(
                "Wave 6 input census exceeds the exact-byte limit".into(),
            ));
        }
        let document_digest = digest_bytes(&document_bytes)?;
        let operation_digest = digest_json(&(
            "joshi.store.wave6_input_census_commit.v1",
            binding_id.as_str(),
            program.commit_seq,
            source.commit_seq,
            document_digest.as_str(),
        ))?;
        let context = self.begin_wave5_commit(batch_id.clone(), writer_build)?;
        let counts = census_counts(&source.occurrence)?;
        let generic = self.commit_wave5(
            &context,
            "maintenance",
            &binding_id,
            &document_digest,
            &operation_digest,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave6_store_input_census_v1
                     (binding_id,program_id,source_occurrence_id,source_descriptor_sha256,
                      source_created_commit_seq,source_known_through_commit_seq,document_sha256,
                      document_bytes,document_byte_length,fact_count,eligible_subject_count,
                      membership_count,coverage_count,gap_count,hot_subject_count,
                      cold_control_subject_count,store_resolved_source,market_atlas_resolved,
                      authority,claim_scope,semantic_ceiling,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             1,0,?17,?18,?19,?20)",
                    params![
                        binding_id.as_str(),
                        program_id.as_str(),
                        source_occurrence_id.as_str(),
                        raw_digest(&source.descriptor_digest, "Wave 5 source descriptor")?,
                        sqlite_u64(source.commit_seq.get(), "Wave 5 source commit")?,
                        sqlite_u64(
                            source.occurrence.known_through_commit_seq.get(),
                            "Wave 5 source cutoff",
                        )?,
                        raw_digest(&document_digest, "Wave 6 input census")?,
                        document_bytes,
                        sqlite_usize(document_bytes.len(), "Wave 6 input census bytes")?,
                        sqlite_usize(counts.facts, "Wave 6 input facts")?,
                        sqlite_usize(counts.subjects, "Wave 6 eligible subjects")?,
                        sqlite_usize(counts.memberships, "Wave 6 memberships")?,
                        sqlite_usize(counts.coverage, "Wave 6 coverage")?,
                        sqlite_usize(counts.gaps, "Wave 6 gaps")?,
                        sqlite_usize(counts.hot, "Wave 6 hot subjects")?,
                        sqlite_usize(counts.cold, "Wave 6 cold-control subjects")?,
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
            .load_wave6_store_input_census_v1(&binding_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 store input census",
                identity: binding_id.to_string(),
            })?;
        if stored.batch_id != batch_id
            || stored.document != document
            || stored.document_bytes != document_bytes
            || stored.document_digest != document_digest
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "Wave 6 input census readback differs from its store-built commit".into(),
            ));
        }
        Ok(Wave6StoreInputCensusReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            batch_id,
            binding_id,
            program_id: program_id.clone(),
            source_occurrence_id: source_occurrence_id.clone(),
            document_digest,
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest,
            status: generic.status,
        })
    }

    /// Loads and rederives an input census from its exact prior program and W5 source occurrence.
    ///
    /// # Errors
    ///
    /// Refuses malformed/noncanonical bytes, scalar drift, changed prior identities, or broken
    /// commit lineage.
    #[allow(clippy::too_many_lines)] // Keeps every persisted scalar in one fail-closed comparison.
    pub fn load_wave6_store_input_census_v1(
        &self,
        binding_id: &StableString,
    ) -> Result<Option<StoredWave6StoreInputCensus>> {
        type Row = (
            String,
            String,
            String,
            i64,
            i64,
            Vec<u8>,
            i64,
            String,
            i64,
            i64,
            i64,
            i64,
            i64,
            i64,
            i64,
            String,
            String,
            String,
            i64,
            String,
            String,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT census.program_id,census.source_occurrence_id,
                        census.source_descriptor_sha256,census.source_created_commit_seq,
                        census.source_known_through_commit_seq,census.document_bytes,
                        census.document_byte_length,census.document_sha256,census.fact_count,
                        census.eligible_subject_count,census.membership_count,census.coverage_count,
                        census.gap_count,census.hot_subject_count,census.cold_control_subject_count,
                        census.authority,census.claim_scope,census.semantic_ceiling,
                        census.created_commit_seq,commit_row.commit_id,commit_row.commit_digest
                 FROM wave6_store_input_census_v1 census
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=census.created_commit_seq
                 WHERE census.binding_id=?1",
                [binding_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                        row.get(7)?,
                        row.get(8)?,
                        row.get(9)?,
                        row.get(10)?,
                        row.get(11)?,
                        row.get(12)?,
                        row.get(13)?,
                        row.get(14)?,
                        row.get(15)?,
                        row.get(16)?,
                        row.get(17)?,
                        row.get(18)?,
                        row.get(19)?,
                        row.get(20)?,
                    ))
                },
            )
            .optional()?;
        let Some((
            program_raw,
            source_raw,
            descriptor_raw,
            source_seq,
            source_cut,
            bytes,
            byte_length,
            document_raw,
            facts,
            subjects,
            memberships,
            coverage,
            gaps,
            hot,
            cold,
            authority,
            claim_scope,
            ceiling,
            commit_seq,
            batch_raw,
            commit_raw,
        )) = row
        else {
            return Ok(None);
        };
        if bytes.len() > MAX_DOCUMENT_BYTES {
            return Err(StoreError::InvalidBatch(
                "stored Wave 6 input census exceeds the exact-byte limit".into(),
            ));
        }
        let document: Wave6StoreInputCensusV1 = serde_json::from_slice(&bytes)?;
        if serde_json::to_vec(&document)? != bytes {
            return Err(StoreError::InvalidBatch(
                "stored Wave 6 input census is not canonical JSON".into(),
            ));
        }
        let program_id = stable(&program_raw, "Wave 6 input census program")?;
        let source_id = stable(&source_raw, "Wave 6 input census source")?;
        let program = self
            .load_wave6_program_registration_v1(&program_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 6 program registration",
                identity: program_raw.clone(),
            })?;
        let source = self
            .load_wave5_source_occurrence_v1(&source_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 source occurrence",
                identity: source_raw.clone(),
            })?;
        let expected = build_document(&program_id, &source, binding_id.clone())?;
        let expected_counts = census_counts(&source.occurrence)?;
        let document_digest = digest_bytes(&bytes)?;
        if document != expected
            || program.commit_seq >= CommitSeq::new(as_u64(commit_seq, "input census commit")?)
            || source.commit_seq >= CommitSeq::new(as_u64(commit_seq, "input census commit")?)
            || raw_digest(&source.descriptor_digest, "Wave 5 source descriptor")? != descriptor_raw
            || sqlite_u64(source.commit_seq.get(), "Wave 5 source commit")? != source_seq
            || sqlite_u64(
                source.occurrence.known_through_commit_seq.get(),
                "Wave 5 source cutoff",
            )? != source_cut
            || sqlite_usize(bytes.len(), "Wave 6 input census bytes")? != byte_length
            || raw_digest(&document_digest, "Wave 6 input census")? != document_raw
            || sqlite_usize(expected_counts.facts, "Wave 6 input facts")? != facts
            || sqlite_usize(expected_counts.subjects, "Wave 6 eligible subjects")? != subjects
            || sqlite_usize(expected_counts.memberships, "Wave 6 memberships")? != memberships
            || sqlite_usize(expected_counts.coverage, "Wave 6 coverage")? != coverage
            || sqlite_usize(expected_counts.gaps, "Wave 6 gaps")? != gaps
            || sqlite_usize(expected_counts.hot, "Wave 6 hot subjects")? != hot
            || sqlite_usize(expected_counts.cold, "Wave 6 cold-control subjects")? != cold
            || authority != AUTHORITY
            || claim_scope != CLAIM_SCOPE
            || ceiling != SEMANTIC_CEILING
        {
            return Err(StoreError::InvalidBatch(
                "stored Wave 6 input census differs from store rederivation".into(),
            ));
        }
        Ok(Some(StoredWave6StoreInputCensus {
            batch_id: stable(&batch_raw, "Wave 6 input census batch")?,
            document,
            document_bytes: bytes,
            document_digest,
            commit_seq: CommitSeq::new(as_u64(commit_seq, "Wave 6 input census commit")?),
            commit_digest: qualified_digest(&commit_raw, "Wave 6 input census commit")?,
        }))
    }

    /// Loads the singular V1 input census selected by a fixture program, when present.
    ///
    /// # Errors
    ///
    /// Refuses malformed stored identity or any exact readback/rederivation failure.
    pub fn load_wave6_store_input_census_for_program_v1(
        &self,
        program_id: &StableString,
    ) -> Result<Option<StoredWave6StoreInputCensus>> {
        let binding: Option<String> = self
            .connection
            .query_row(
                "SELECT binding_id FROM wave6_store_input_census_v1 WHERE program_id=?1",
                [program_id.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        binding
            .map(|value| {
                let identity = stable(&value, "Wave 6 input census identity")?;
                self.load_wave6_store_input_census_v1(&identity)?
                    .ok_or_else(|| StoreError::MissingIdentity {
                        kind: "Wave 6 store input census",
                        identity: value,
                    })
            })
            .transpose()
    }
}

fn build_document(
    program_id: &StableString,
    source: &StoredWave5SourceOccurrence,
    binding_id: StableString,
) -> Result<Wave6StoreInputCensusV1> {
    let counts = census_counts(&source.occurrence)?;
    Ok(Wave6StoreInputCensusV1 {
        contract: stable(CONTRACT, "Wave 6 input census contract")?,
        schema_version: 1,
        binding_id,
        program_id: program_id.clone(),
        source_descriptor_digest: source.descriptor_digest.clone(),
        source_created_commit_seq: source.commit_seq,
        source_occurrence: source.occurrence.clone(),
        fact_count: wire_usize(counts.facts, "Wave 6 input facts")?,
        eligible_subject_count: wire_usize(counts.subjects, "Wave 6 eligible subjects")?,
        membership_count: wire_usize(counts.memberships, "Wave 6 memberships")?,
        coverage_count: wire_usize(counts.coverage, "Wave 6 coverage")?,
        gap_count: wire_usize(counts.gaps, "Wave 6 gaps")?,
        hot_subject_count: wire_usize(counts.hot, "Wave 6 hot subjects")?,
        cold_control_subject_count: wire_usize(counts.cold, "Wave 6 cold-control subjects")?,
        store_resolved_source: true,
        market_atlas_resolved: false,
        authority: stable(AUTHORITY, "Wave 6 input census authority")?,
        claim_scope: stable(CLAIM_SCOPE, "Wave 6 input census claim scope")?,
        semantic_ceiling: stable(SEMANTIC_CEILING, "Wave 6 input census ceiling")?,
    })
}

fn census_counts(source: &Wave5SourceOccurrenceV1) -> Result<CensusCounts> {
    let hot = source
        .memberships
        .iter()
        .filter(|value| value.membership == CockpitV2MembershipKind::Hot)
        .count();
    let cold = source
        .memberships
        .iter()
        .filter(|value| value.membership == CockpitV2MembershipKind::ColdControl)
        .count();
    let counts = CensusCounts {
        facts: source.facts.len(),
        subjects: source.eligible_subjects.len(),
        memberships: source.memberships.len(),
        coverage: source.coverage.len(),
        gaps: source.gaps.len(),
        hot,
        cold,
    };
    if counts.facts == 0
        || counts.subjects == 0
        || counts.memberships != counts.subjects
        || counts.coverage == 0
        || hot == 0
        || cold == 0
    {
        return Err(StoreError::InvalidBatch(
            "Wave 6 input census requires nonempty facts, an exact denominator, coverage, and both hot and cold-control subjects".into(),
        ));
    }
    Ok(counts)
}

fn binding_id(program_id: &StableString, source_id: &StableString) -> Result<StableString> {
    let digest = digest_json(&(
        "joshi.store.wave6_input_census_identity.v1",
        program_id.as_str(),
        source_id.as_str(),
    ))?;
    stable(
        &format!(
            "wave6-input-census:{}",
            raw_digest(&digest, "Wave 6 input census identity")?
        ),
        "Wave 6 input census identity",
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
             FROM wave6_store_input_census_v1 census
             JOIN ingest_commit commit_row ON commit_row.commit_seq=census.created_commit_seq
             WHERE census.binding_id=?1",
            [binding_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if existing
        .as_deref()
        .is_some_and(|value| value != batch_id.as_str())
    {
        return Err(StoreError::IdentityConflict {
            kind: "Wave 6 store input census",
            identity: binding_id.to_string(),
        });
    }
    Ok(())
}

fn digest_json(value: &impl Serialize) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(value)?)
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

fn sqlite_u64(value: u64, field: &'static str) -> Result<i64> {
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

fn wire_usize(value: usize, field: &'static str) -> Result<WireU64> {
    Ok(WireU64::new(value.try_into().map_err(|_| {
        StoreError::IntegerRange {
            field,
            value: value.to_string(),
        }
    })?))
}

fn as_u64(value: i64, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}
