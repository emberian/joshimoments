//! Composed offline witness for the store-resolved Wave 6 operator-evidence input.

use std::{fs, path::Path};

use joshi_domain::StableString;
use joshi_scientific_memory::{MemoryOccurrence, PresentationBinding};
use joshi_store::{
    IdempotencyStatus, SqliteStore, StoreMode, StoredWave6OperatorEvidenceInput,
    Wave6OperatorEvidenceInputReceipt, Wave6OperatorEvidenceInputV1,
};
use serde::Serialize;
use thiserror::Error;

const REGISTRATION: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
const PROGRAM_ID: &str = "w6-program-fixture-001";
const PROGRAM_BATCH_ID: &str = "wave6:program-registration:fixture-001";
const CENSUS_BATCH_ID: &str = "wave6:store-input-census:fixture-001";
const OPERATOR_BATCH_ID: &str = "wave6:operator-evidence-input:fixture-001";
const MEMORY_ACT_ID: &str = "act:g0-act-0001";
const AUTHORITY: &str = "read_record_replay_propose_shadow_only";
const SEMANTIC_CEILING: &str = "store_resolved_operator_evidence_input_only";
const CLAIM_SCOPE: &str =
    "store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model";

/// Machine-readable receipt for the exact act-gap and later browser-report input bridge.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave6OperatorEvidenceInputReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub status: &'static str,
    pub authority: &'static str,
    pub semantic_ceiling: &'static str,
    pub claim_scope: &'static str,
    pub catalog_schema: String,
    pub program_id: String,
    pub program_registration_digest: String,
    pub input_census_binding_id: String,
    pub input_census_document_digest: String,
    pub source_occurrence_id: String,
    pub publication_id: String,
    pub publication_digest: String,
    pub head_digest: String,
    pub memory_occurrence_id: String,
    pub memory_occurrence_digest: String,
    pub memory_session_id: String,
    pub memory_subject_id: String,
    pub presentation_claim_id: String,
    pub presentation_claim_digest: String,
    pub pairing_session_id: String,
    pub binding_id: String,
    pub document_digest: String,
    pub operator_evidence_input: Wave6OperatorEvidenceInputV1,
    pub accepted_commit_seq: String,
    pub first_status: IdempotencyStatus,
    pub retry_status: IdempotencyStatus,
    pub store_resolved_input_census: bool,
    pub store_resolved_memory_act: bool,
    pub store_resolved_browser_report: bool,
    pub scripted_presentation_path: bool,
    pub exact_retry_closed: bool,
    pub restart_reverified: bool,
    pub act_presentation_gap_retained: bool,
    pub presentation_repairs_act_gap: bool,
    pub session_equivalence_claimed: bool,
    pub human_viewing_verified: bool,
    pub recognition_observed: bool,
    pub operator_model_resolved: bool,
    pub provider_io: bool,
    pub external_mutation: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

/// Builds the W5 prefix and V21 browser report when absent, then commits the exact V22 input.
///
/// No network socket, provider, wallet, signing, transaction, deployment, or external mutation is
/// used. The browser-format claim is scripted and never becomes a human-viewing assertion.
///
/// # Errors
///
/// Refuses any missing/corrupt prior, retry drift, cross-publication linkage, or positive promotion
/// field.
#[allow(clippy::too_many_lines)]
pub async fn run_wave6_operator_evidence_input(
    state: &Path,
) -> Result<Wave6OperatorEvidenceInputReport, Wave6OperatorEvidenceInputError> {
    fs::create_dir_all(state)?;
    let program_id = StableString::new(PROGRAM_ID)?;
    let inspector_config = crate::wave5_g0::browser_inspector_store_config(state)?;
    if inspector_config.catalog_path.exists() {
        let store = SqliteStore::open(inspector_config.clone(), StoreMode::ReadOnly)?;
        if store.catalog_schema()?.as_str() == "joshi.sqlite.v22"
            && let Some(stored) =
                store.load_wave6_operator_evidence_input_for_program_v1(&program_id)?
        {
            let catalog_schema = store.catalog_schema()?.to_string();
            let program = store
                .load_wave6_program_registration_v1(&program_id)?
                .ok_or(Wave6OperatorEvidenceInputError::Invariant(
                    "reopened operator input lost its Wave 6 program",
                ))?;
            return report(
                program.registration_digest.to_string(),
                catalog_schema,
                IdempotencyStatus::Idempotent,
                &stored,
            );
        }
    }

    let component = crate::wave5_g0::run_wave5_g0_source_publication(state)?;
    if component.catalog_schema != "joshi.sqlite.v10"
        || !component.source_semantics_closed
        || !component.partial_memory_chain_closed
        || !component.censored_memory_chain_closed
        || component.provider_io
        || component.product_qualified
        || component.live_qualified
    {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "W5 G0 did not produce the exact non-promoting source/memory prefix",
        ));
    }
    let inspector = crate::g0_inspector_smoke::run_g0_inspector_smoke(state).await?;
    if !inspector.scripted_presentation_evidence_stored
        || !inspector.scripted_presentation_exact_retry_closed
        || inspector.browser_presented
        || inspector.product_qualified
        || inspector.live_qualified
    {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "G0 inspector did not produce the exact non-promoting browser report",
        ));
    }

    let mut store = crate::wave5_g0::prepare_g0_browser_inspector_store(state, &component)?;
    if store.catalog_schema()?.as_str() != "joshi.sqlite.v22" {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "operator-evidence overlay did not reach V22",
        ));
    }
    let writer_build = StableString::new(format!("joshi-core-{}", env!("CARGO_PKG_VERSION")))?;
    let program = store.commit_wave6_program_registration_v1(
        REGISTRATION,
        StableString::new(PROGRAM_BATCH_ID)?,
        writer_build.clone(),
    )?;
    if program.program_id != program_id {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "operator-evidence bridge selected an unexpected Wave 6 program",
        ));
    }
    let source_id = StableString::new(component.source_occurrence_id)?;
    let census = store.commit_wave6_store_input_census_v1(
        &program_id,
        &source_id,
        StableString::new(CENSUS_BATCH_ID)?,
        writer_build.clone(),
    )?;
    let memory_id = StableString::new(MEMORY_ACT_ID)?;
    let presentation_id = StableString::new(inspector.scripted_presentation_claim_id)?;
    let first = store.commit_wave6_operator_evidence_input_v1(
        &program_id,
        &census.binding_id,
        &memory_id,
        &presentation_id,
        StableString::new(OPERATOR_BATCH_ID)?,
        writer_build.clone(),
    )?;
    let retry = store.commit_wave6_operator_evidence_input_v1(
        &program_id,
        &census.binding_id,
        &memory_id,
        &presentation_id,
        StableString::new(OPERATOR_BATCH_ID)?,
        writer_build,
    )?;
    if retry.status != IdempotencyStatus::Idempotent || !same_receipt(&first, &retry) {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "operator-evidence exact retry changed durable identity",
        ));
    }
    drop(store);

    let reopened = SqliteStore::open(inspector_config, StoreMode::ReadOnly)?;
    let catalog_schema = reopened.catalog_schema()?.to_string();
    let stored = reopened
        .load_wave6_operator_evidence_input_v1(&first.binding_id)?
        .ok_or(Wave6OperatorEvidenceInputError::Invariant(
            "operator-evidence input was absent after restart",
        ))?;
    let selected = reopened
        .load_wave6_operator_evidence_input_for_program_v1(&program_id)?
        .ok_or(Wave6OperatorEvidenceInputError::Invariant(
            "Wave 6 program did not select its operator input after restart",
        ))?;
    if stored != selected
        || stored.document_digest != first.document_digest
        || stored.commit_seq != first.commit_seq
        || stored.commit_digest != first.commit_digest
    {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "operator-evidence input changed across read-only restart",
        ));
    }
    report(
        program.registration_digest.to_string(),
        catalog_schema,
        first.status,
        &stored,
    )
}

fn report(
    program_registration_digest: String,
    catalog_schema: String,
    first_status: IdempotencyStatus,
    stored: &StoredWave6OperatorEvidenceInput,
) -> Result<Wave6OperatorEvidenceInputReport, Wave6OperatorEvidenceInputError> {
    let document = &stored.document;
    let MemoryOccurrence::OperatorAct(act) = &document.memory_occurrence else {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "stored operator input no longer contains an operator act",
        ));
    };
    if !matches!(act.presentation, PresentationBinding::Gap(_))
        || !document.act_presentation_gap_retained
        || document.presentation_repairs_act_gap
        || document.session_equivalence_claimed
        || document.human_viewing_verified
        || document.recognition_observed
        || document.operator_model_resolved
        || document.authority.as_str() != AUTHORITY
        || document.semantic_ceiling.as_str() != SEMANTIC_CEILING
        || document.claim_scope.as_str() != CLAIM_SCOPE
    {
        return Err(Wave6OperatorEvidenceInputError::Invariant(
            "operator-evidence input crossed its fixed semantic ceiling",
        ));
    }
    Ok(Wave6OperatorEvidenceInputReport {
        contract: "joshi.core.wave6_operator_evidence_input_report.v1",
        schema_version: 1,
        status: "useful_partial",
        authority: AUTHORITY,
        semantic_ceiling: SEMANTIC_CEILING,
        claim_scope: CLAIM_SCOPE,
        catalog_schema,
        program_id: document.program_id.to_string(),
        program_registration_digest,
        input_census_binding_id: document.input_census_binding_id.to_string(),
        input_census_document_digest: document.input_census_document_digest.to_string(),
        source_occurrence_id: document.source_occurrence_id.to_string(),
        publication_id: document.publication_id.to_string(),
        publication_digest: document.publication_digest.to_string(),
        head_digest: document.head_digest.to_string(),
        memory_occurrence_id: document.memory_occurrence_id.to_string(),
        memory_occurrence_digest: document.memory_occurrence_digest.to_string(),
        memory_session_id: act.session_id.to_string(),
        memory_subject_id: document.subject_id.to_string(),
        presentation_claim_id: document.presentation_claim_id.to_string(),
        presentation_claim_digest: document.presentation_claim_digest.to_string(),
        pairing_session_id: document.pairing_session_id.to_string(),
        binding_id: document.binding_id.to_string(),
        document_digest: stored.document_digest.to_string(),
        operator_evidence_input: document.clone(),
        accepted_commit_seq: stored.commit_seq.to_string(),
        first_status,
        retry_status: IdempotencyStatus::Idempotent,
        store_resolved_input_census: true,
        store_resolved_memory_act: true,
        store_resolved_browser_report: true,
        scripted_presentation_path: true,
        exact_retry_closed: true,
        restart_reverified: true,
        act_presentation_gap_retained: true,
        presentation_repairs_act_gap: false,
        session_equivalence_claimed: false,
        human_viewing_verified: false,
        recognition_observed: false,
        operator_model_resolved: false,
        provider_io: false,
        external_mutation: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn same_receipt(
    first: &Wave6OperatorEvidenceInputReceipt,
    retry: &Wave6OperatorEvidenceInputReceipt,
) -> bool {
    first.catalog_id == retry.catalog_id
        && first.catalog_schema == retry.catalog_schema
        && first.batch_id == retry.batch_id
        && first.binding_id == retry.binding_id
        && first.program_id == retry.program_id
        && first.document_digest == retry.document_digest
        && first.commit_seq == retry.commit_seq
        && first.commit_digest == retry.commit_digest
}

/// Failure to complete the narrow offline operator-evidence input bridge.
#[derive(Debug, Error)]
pub enum Wave6OperatorEvidenceInputError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    G0(#[from] crate::wave5_g0::Wave5G0SourcePublicationError),
    #[error(transparent)]
    Inspector(#[from] crate::g0_inspector_smoke::G0InspectorSmokeError),
    #[error("Wave 6 operator-evidence input invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn exact_store_join_retries_and_never_repairs_the_act_gap_or_claims_recognition() {
        let state = tempfile::tempdir().expect("temporary operator-evidence state");
        let first = run_wave6_operator_evidence_input(state.path())
            .await
            .expect("first operator-evidence witness");
        assert_eq!(first.catalog_schema, "joshi.sqlite.v22");
        assert_eq!(first.first_status, IdempotencyStatus::Accepted);
        assert_eq!(first.retry_status, IdempotencyStatus::Idempotent);
        assert!(first.store_resolved_input_census);
        assert!(first.store_resolved_memory_act);
        assert!(first.store_resolved_browser_report);
        assert!(first.scripted_presentation_path);
        assert!(first.exact_retry_closed);
        assert!(first.restart_reverified);
        assert!(first.act_presentation_gap_retained);
        assert!(!first.presentation_repairs_act_gap);
        assert!(!first.session_equivalence_claimed);
        assert!(!first.human_viewing_verified);
        assert!(!first.recognition_observed);
        assert!(!first.operator_model_resolved);
        assert!(!first.provider_io);
        assert!(!first.external_mutation);
        assert!(!first.product_qualified);
        assert!(!first.live_qualified);

        let retry = run_wave6_operator_evidence_input(state.path())
            .await
            .expect("whole operator-evidence witness retry");
        assert_eq!(retry.first_status, IdempotencyStatus::Idempotent);
        assert_eq!(retry.binding_id, first.binding_id);
        assert_eq!(retry.document_digest, first.document_digest);
        assert_eq!(retry.accepted_commit_seq, first.accepted_commit_seq);
        assert_eq!(retry.presentation_claim_id, first.presentation_claim_id);
    }

    #[tokio::test]
    async fn episode_or_foreign_presentation_cannot_substitute_for_the_exact_act_report_pair() {
        let state = tempfile::tempdir().expect("temporary operator-evidence adversary state");
        let report = run_wave6_operator_evidence_input(state.path())
            .await
            .expect("operator-evidence witness");
        let config = crate::wave5_g0::browser_inspector_store_config(state.path())
            .expect("inspector config");
        let mut store =
            SqliteStore::open(config, StoreMode::SingleWriter).expect("operator input store");
        let program_id = StableString::new(&report.program_id).expect("program");
        let census_id =
            StableString::new(&report.input_census_binding_id).expect("input census binding");
        let presentation_id =
            StableString::new(&report.presentation_claim_id).expect("presentation");
        let episode_id = StableString::new("episode:g0-episode-0001").expect("episode");
        let error = store
            .commit_wave6_operator_evidence_input_v1(
                &program_id,
                &census_id,
                &episode_id,
                &presentation_id,
                StableString::new("wave6:operator-evidence-input:episode-substitution")
                    .expect("episode batch"),
                StableString::new("operator-evidence-adversary").expect("writer"),
            )
            .expect_err("episode cannot substitute for the exact operator act");
        assert!(error.to_string().contains("requires an exact operator act"));

        let missing_presentation =
            StableString::new("scripted-presentation-foreign").expect("foreign presentation");
        let error = store
            .commit_wave6_operator_evidence_input_v1(
                &program_id,
                &census_id,
                &StableString::new(MEMORY_ACT_ID).expect("memory act"),
                &missing_presentation,
                StableString::new("wave6:operator-evidence-input:foreign-presentation")
                    .expect("foreign batch"),
                StableString::new("operator-evidence-adversary").expect("writer"),
            )
            .expect_err("foreign presentation cannot substitute");
        assert!(error.to_string().contains("browser presentation"));
    }
}
