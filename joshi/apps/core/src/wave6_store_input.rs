//! Composed offline witness for the store-resolved Wave 6 input-census bridge.

use std::{fs, path::Path};

use joshi_domain::StableString;
use joshi_store::{
    IdempotencyStatus, SqliteStore, StoreMode, StoredWave6StoreInputCensus,
    Wave6StoreInputCensusReceipt,
};
use serde::Serialize;
use thiserror::Error;

const REGISTRATION: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
const PROGRAM_ID: &str = "w6-program-fixture-001";
const PROGRAM_BATCH_ID: &str = "wave6:program-registration:fixture-001";
const CENSUS_BATCH_ID: &str = "wave6:store-input-census:fixture-001";
const AUTHORITY: &str = "read_record_replay_propose_shadow_only";
const SEMANTIC_CEILING: &str = "store_resolved_offline_fixture_input_census_only";
const CLAIM_SCOPE: &str =
    "mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution";

/// Machine-readable narrow receipt for the genuine W5-source-to-W6-program bridge.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave6StoreInputCensusReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub status: &'static str,
    pub authority: &'static str,
    pub semantic_ceiling: &'static str,
    pub claim_scope: &'static str,
    pub catalog_schema: String,
    pub program_id: String,
    pub program_registration_digest: String,
    pub source_occurrence_id: String,
    pub source_descriptor_digest: String,
    pub source_created_commit_seq: String,
    pub source_known_through_commit_seq: String,
    pub binding_id: String,
    pub document_digest: String,
    pub accepted_commit_seq: String,
    pub first_status: IdempotencyStatus,
    pub retry_status: IdempotencyStatus,
    pub fact_count: String,
    pub eligible_subject_count: String,
    pub membership_count: String,
    pub coverage_count: String,
    pub gap_count: String,
    pub hot_subject_count: String,
    pub cold_control_subject_count: String,
    pub store_resolved_source: bool,
    pub exact_retry_closed: bool,
    pub restart_reverified: bool,
    pub store_resolved_market_atlas: bool,
    pub field_release: bool,
    pub empirical_claim: bool,
    pub causal_claim: bool,
    pub strategy_claim: bool,
    pub provider_io: bool,
    pub external_mutation: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

/// Creates the genuine W5 C0 source occurrence on first use, then store-builds, exactly retries,
/// and read-only reopens its distinct Wave 6 input-census bridge.
///
/// This function performs no provider I/O or external mutation and deliberately does not construct
/// a Wave 6 market-atlas artifact.
///
/// # Errors
///
/// Refuses partial foreign state, an invalid W5 component, migration/commit/readback divergence,
/// or any positive promotion field.
#[allow(clippy::too_many_lines)] // Keeps the composed first-run/retry/reopen witness explicit.
pub fn run_wave6_store_input_census(
    state: &Path,
) -> Result<Wave6StoreInputCensusReport, Wave6StoreInputCensusError> {
    fs::create_dir_all(state)?;
    let config = crate::wave5_g0::offline_fixture_store_config(state)?;
    let program_id = StableString::new(PROGRAM_ID)?;
    let existing = if config.catalog_path.exists() {
        let store = SqliteStore::open(config.clone(), StoreMode::ReadOnly)?;
        if store.catalog_schema()?.as_str() == "joshi.sqlite.v21" {
            store.load_wave6_store_input_census_for_program_v1(&program_id)?
        } else {
            None
        }
    } else {
        None
    };

    let source_occurrence_id = if let Some(stored) = &existing {
        stored
            .document
            .source_occurrence
            .source_occurrence_id
            .clone()
    } else {
        if config.catalog_path.exists() {
            let store = SqliteStore::open(config.clone(), StoreMode::ReadOnly)?;
            if store.catalog_schema()?.as_str() != "joshi.sqlite.v10" {
                return Err(Wave6StoreInputCensusError::Invariant(
                    "preexisting catalog without an input census is not the exact W5 G0 V10 prefix",
                ));
            }
        }
        let g0 = crate::wave5_g0::run_wave5_g0_source_publication(state)?;
        if g0.catalog_schema != "joshi.sqlite.v10"
            || !g0.source_semantics_closed
            || g0.source_fact_count == 0
            || g0.hot_subject_count == 0
            || g0.cold_control_subject_count == 0
            || g0.provider_io
            || g0.product_qualified
            || g0.live_qualified
        {
            return Err(Wave6StoreInputCensusError::Invariant(
                "W5 G0 did not produce the exact non-promoting source prefix",
            ));
        }
        StableString::new(g0.source_occurrence_id)?
    };

    let mut store = SqliteStore::open(config.clone(), StoreMode::SingleWriter)?;
    let migration = store.migrate(now()?)?;
    if migration.current != 21 {
        return Err(Wave6StoreInputCensusError::Invariant(
            "Wave 6 input census did not reach latest V21",
        ));
    }
    let writer_build = StableString::new(format!("joshi-core-{}", env!("CARGO_PKG_VERSION")))?;
    let program = store.commit_wave6_program_registration_v1(
        REGISTRATION,
        StableString::new(PROGRAM_BATCH_ID)?,
        writer_build.clone(),
    )?;
    if program.program_id != program_id {
        return Err(Wave6StoreInputCensusError::Invariant(
            "Wave 6 fixture registration selected an unexpected program",
        ));
    }
    let first = store.commit_wave6_store_input_census_v1(
        &program_id,
        &source_occurrence_id,
        StableString::new(CENSUS_BATCH_ID)?,
        writer_build.clone(),
    )?;
    let retry = store.commit_wave6_store_input_census_v1(
        &program_id,
        &source_occurrence_id,
        StableString::new(CENSUS_BATCH_ID)?,
        writer_build,
    )?;
    if retry.status != IdempotencyStatus::Idempotent
        || !same_receipt(&first, &retry)
        || first.catalog_schema.as_str() != "joshi.sqlite.v21"
    {
        return Err(Wave6StoreInputCensusError::Invariant(
            "Wave 6 input census exact retry changed durable identity",
        ));
    }
    drop(store);

    let reopened = SqliteStore::open(config, StoreMode::ReadOnly)?;
    let stored = reopened
        .load_wave6_store_input_census_v1(&first.binding_id)?
        .ok_or(Wave6StoreInputCensusError::Invariant(
            "Wave 6 input census was absent after restart",
        ))?;
    let selected = reopened
        .load_wave6_store_input_census_for_program_v1(&program_id)?
        .ok_or(Wave6StoreInputCensusError::Invariant(
            "Wave 6 program did not select its singular input census after restart",
        ))?;
    if stored != selected
        || stored.document_digest != first.document_digest
        || stored.commit_seq != first.commit_seq
        || stored.commit_digest != first.commit_digest
        || stored.document.authority.as_str() != AUTHORITY
        || stored.document.semantic_ceiling.as_str() != SEMANTIC_CEILING
        || stored.document.claim_scope.as_str() != CLAIM_SCOPE
        || !stored.document.store_resolved_source
        || stored.document.market_atlas_resolved
    {
        return Err(Wave6StoreInputCensusError::Invariant(
            "Wave 6 input census changed or promoted across read-only restart",
        ));
    }
    Ok(report(
        program.registration_digest.to_string(),
        &first,
        stored,
    ))
}

fn report(
    program_registration_digest: String,
    receipt: &Wave6StoreInputCensusReceipt,
    stored: StoredWave6StoreInputCensus,
) -> Wave6StoreInputCensusReport {
    let document = stored.document;
    Wave6StoreInputCensusReport {
        contract: "joshi.core.wave6_store_input_census_report.v1",
        schema_version: 1,
        status: "useful_partial",
        authority: AUTHORITY,
        semantic_ceiling: SEMANTIC_CEILING,
        claim_scope: CLAIM_SCOPE,
        catalog_schema: receipt.catalog_schema.to_string(),
        program_id: document.program_id.to_string(),
        program_registration_digest,
        source_occurrence_id: document.source_occurrence.source_occurrence_id.to_string(),
        source_descriptor_digest: document.source_descriptor_digest.to_string(),
        source_created_commit_seq: document.source_created_commit_seq.to_string(),
        source_known_through_commit_seq: document
            .source_occurrence
            .known_through_commit_seq
            .to_string(),
        binding_id: document.binding_id.to_string(),
        document_digest: stored.document_digest.to_string(),
        accepted_commit_seq: stored.commit_seq.to_string(),
        first_status: receipt.status,
        retry_status: IdempotencyStatus::Idempotent,
        fact_count: document.fact_count.to_string(),
        eligible_subject_count: document.eligible_subject_count.to_string(),
        membership_count: document.membership_count.to_string(),
        coverage_count: document.coverage_count.to_string(),
        gap_count: document.gap_count.to_string(),
        hot_subject_count: document.hot_subject_count.to_string(),
        cold_control_subject_count: document.cold_control_subject_count.to_string(),
        store_resolved_source: true,
        exact_retry_closed: true,
        restart_reverified: true,
        store_resolved_market_atlas: false,
        field_release: false,
        empirical_claim: false,
        causal_claim: false,
        strategy_claim: false,
        provider_io: false,
        external_mutation: false,
        product_qualified: false,
        live_qualified: false,
    }
}

fn same_receipt(
    first: &Wave6StoreInputCensusReceipt,
    retry: &Wave6StoreInputCensusReceipt,
) -> bool {
    first.catalog_id == retry.catalog_id
        && first.catalog_schema == retry.catalog_schema
        && first.batch_id == retry.batch_id
        && first.binding_id == retry.binding_id
        && first.program_id == retry.program_id
        && first.source_occurrence_id == retry.source_occurrence_id
        && first.document_digest == retry.document_digest
        && first.commit_seq == retry.commit_seq
        && first.commit_digest == retry.commit_digest
}

fn now() -> Result<joshi_domain::UtcTimestamp, Wave6StoreInputCensusError> {
    let nanos = time::OffsetDateTime::now_utc().unix_timestamp_nanos();
    let micros = nanos.div_euclid(1_000) * 1_000;
    joshi_domain::UtcTimestamp::new(
        time::OffsetDateTime::from_unix_timestamp_nanos(micros)
            .map_err(|_| Wave6StoreInputCensusError::Clock)?,
    )
    .map_err(|_| Wave6StoreInputCensusError::Clock)
}

/// Failure to complete the narrow offline input-census bridge.
#[derive(Debug, Error)]
pub enum Wave6StoreInputCensusError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    G0(#[from] crate::wave5_g0::Wave5G0SourcePublicationError),
    #[error("system clock is unavailable")]
    Clock,
    #[error("Wave 6 store input census invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn genuine_w5_source_retries_and_reopens_without_market_atlas_promotion() {
        let state = tempfile::tempdir().expect("temporary input-census state");
        let first = run_wave6_store_input_census(state.path()).expect("first bridge witness");
        assert_eq!(first.catalog_schema, "joshi.sqlite.v21");
        assert_eq!(first.first_status, IdempotencyStatus::Accepted);
        assert_eq!(first.retry_status, IdempotencyStatus::Idempotent);
        assert_eq!(first.fact_count, "2");
        assert_eq!(first.eligible_subject_count, "2");
        assert_eq!(first.hot_subject_count, "1");
        assert_eq!(first.cold_control_subject_count, "1");
        assert!(first.store_resolved_source);
        assert!(first.exact_retry_closed);
        assert!(first.restart_reverified);
        assert!(!first.store_resolved_market_atlas);
        assert!(!first.field_release);
        assert!(!first.empirical_claim);
        assert!(!first.causal_claim);
        assert!(!first.strategy_claim);
        assert!(!first.provider_io);
        assert!(!first.external_mutation);
        assert!(!first.product_qualified);
        assert!(!first.live_qualified);

        let retry = run_wave6_store_input_census(state.path()).expect("whole witness retry");
        assert_eq!(retry.first_status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.binding_id, first.binding_id);
        assert_eq!(retry.document_digest, first.document_digest);
        assert_eq!(retry.accepted_commit_seq, first.accepted_commit_seq);
    }
}
