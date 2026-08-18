//! Bounded Core witness for the exact fixture-only Wave 6 N00 program registration.

use std::{fs, path::Path, time::Duration};

use joshi_domain::StableString;
use joshi_store::{
    IdempotencyStatus, ResearchDispositionAuthorityV1, SqliteStore, StoreConfig, StoreMode,
    StoredWave6FixtureResearchDisposition, StoredWave6FixtureResearchProposal,
    Wave6FixtureCampaignBundleBytes,
};
use joshi_wave6_registry::{ResearchDispositionKindV1, SemanticCeilingV1};
use serde::Serialize;
use thiserror::Error;

const REGISTRATION: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");
const ARTIFACT_DAG: &[u8] = include_bytes!("../../../fixtures/wave6/artifact_dag_v1.json");
const DECISION_LEDGER: &[u8] = include_bytes!("../../../fixtures/wave6/decision_ledger_v1.json");
const RESEARCH_PROPOSAL: &[u8] =
    include_bytes!("../../../fixtures/wave6/research_proposal_v1.json");
const RESEARCH_DISPOSITION: &[u8] =
    include_bytes!("../../../fixtures/wave6/research_disposition_v1.json");
const CAMPAIGN_REGISTRATION: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/registration_v1.json");
const CAMPAIGN_ENROLLMENT: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/enrollment_v1.json");
const CAMPAIGN_ASSIGNMENT: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/assignment_v1.json");
const CAMPAIGN_SEAL: &[u8] = include_bytes!("../../../fixtures/wave6/campaign/seal_v1.json");
const CAMPAIGN_ADJUDICATION: &[u8] =
    include_bytes!("../../../fixtures/wave6/campaign/adjudication_v1.json");
const PROGRAM_ID: &str = "w6-program-fixture-001";
const BATCH_ID: &str = "wave6:program-registration:fixture-001";
const AUTHORITY: &str = "read_record_replay_propose_shadow_only";

struct SchemaFixture {
    kind_id: &'static str,
    bytes: &'static [u8],
}

struct ArtifactFixture {
    kind_id: &'static str,
    bytes: &'static [u8],
}

/// One exact schema row retained by the Core witness.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6ArtifactSchemaReport {
    pub kind_id: String,
    pub schema_id: String,
    pub schema_digest: String,
    pub commit_seq: String,
}

/// One exact fixture evaluation retained and reparsed by the sole store.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureArtifactReport {
    pub artifact_id: String,
    pub kind_id: String,
    pub schema_id: String,
    pub content_digest: String,
    pub evaluation_digest: String,
    pub result_count: String,
    pub commit_seq: String,
}

/// One exact fixture DAG retained after all of its content members.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureArtifactDagReport {
    pub dag_id: String,
    pub dag_digest: String,
    pub document_digest: String,
    pub artifact_count: String,
    pub maximum_information_cutoff: String,
    pub maximum_produced_at: String,
    pub commit_seq: String,
}

/// One exact fixture disposition ledger retained after its DAG.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureDecisionLedgerReport {
    pub ledger_id: String,
    pub ledger_digest: String,
    pub document_digest: String,
    pub decision_count: String,
    pub maximum_decided_at: String,
    pub commit_seq: String,
}

/// One exact atomic fixture-campaign bundle retained after its prior program and schema.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureCampaignBundleReport {
    pub bundle_id: String,
    pub campaign_id: String,
    pub registration_digest: String,
    pub enrollment_digest: String,
    pub assignment_digest: String,
    pub seal_digest: String,
    pub adjudication_digest: String,
    pub bundle_digest: String,
    pub eligible_subject_count: String,
    pub included_subject_count: String,
    pub assignment_count: String,
    pub outcome_count: String,
    pub maximum_fixture_alleged_commit_seq: String,
    pub commit_seq: String,
}

/// One proposal descriptor resolved to an earlier exact fixture evaluation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureResearchArtifactBindingReport {
    pub descriptor_artifact_id: String,
    pub provenance_digest: String,
    pub resolved_artifact_id: String,
    pub resolved_kind_id: String,
    pub fixture_alleged_commit_seq: String,
    pub resolved_artifact_commit_seq: String,
}

/// One exact non-executable proposal retained after its prior evaluations.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureResearchProposalReport {
    pub proposal_id: String,
    pub proposal_digest: String,
    pub content_digest: String,
    pub commitment_digest: String,
    pub policy_digest: String,
    pub evidence_closure_digest: String,
    pub descriptor_count: String,
    pub counterexample_count: String,
    pub experiment_count: String,
    pub total_experiment_units: String,
    pub maximum_fixture_alleged_commit_seq: String,
    pub maximum_resolved_artifact_commit_seq: String,
    pub artifact_bindings: Vec<Wave6FixtureResearchArtifactBindingReport>,
    pub commit_seq: String,
}

/// One exact caller-fed fixture disposition retained after its proposal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wave6FixtureResearchDispositionReport {
    pub disposition_id: String,
    pub proposal_id: String,
    pub proposal_digest: String,
    pub proposal_content_digest: String,
    pub disposition: &'static str,
    pub reviewer_id: String,
    pub decided_at: String,
    pub reason: String,
    pub content_digest: String,
    pub identity_authority: &'static str,
    pub authority_boundary: &'static str,
    pub commit_seq: String,
}

/// Machine-readable, non-promoting result of the N00 durable fixture walk.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave6ProgramRegistrationReport {
    pub contract: &'static str,
    pub schema_version: u64,
    pub status: &'static str,
    pub authority: &'static str,
    pub semantic_ceiling: SemanticCeilingV1,
    pub catalog_schema: String,
    pub program_id: String,
    pub registration_digest: String,
    pub document_digest: String,
    pub accepted_commit_seq: String,
    pub first_status: IdempotencyStatus,
    pub retry_status: IdempotencyStatus,
    pub registration_persisted: bool,
    pub restart_reverified: bool,
    pub registered_schema_count: String,
    pub schemas: Vec<Wave6ArtifactSchemaReport>,
    pub schema_catalog_persisted: bool,
    pub schema_catalog_restart_reverified: bool,
    pub fixture_artifact_content_count: String,
    pub fixture_artifacts: Vec<Wave6FixtureArtifactReport>,
    pub fixture_artifact_content_persisted: bool,
    pub fixture_artifact_content_restart_reverified: bool,
    pub fixture_artifact_dag: Wave6FixtureArtifactDagReport,
    pub fixture_artifact_dag_persisted: bool,
    pub fixture_artifact_dag_restart_reverified: bool,
    pub fixture_decision_ledger: Wave6FixtureDecisionLedgerReport,
    pub fixture_decision_ledger_persisted: bool,
    pub fixture_decision_ledger_restart_reverified: bool,
    pub fixture_campaign_bundle: Wave6FixtureCampaignBundleReport,
    pub fixture_campaign_bundle_persisted: bool,
    pub fixture_campaign_bundle_restart_reverified: bool,
    pub prospective_campaign_journal: bool,
    pub fixture_research_proposal: Wave6FixtureResearchProposalReport,
    pub fixture_research_proposal_persisted: bool,
    pub fixture_research_proposal_restart_reverified: bool,
    pub fixture_research_disposition: Wave6FixtureResearchDispositionReport,
    pub fixture_research_disposition_persisted: bool,
    pub fixture_research_disposition_restart_reverified: bool,
    pub human_research_review: bool,
    pub proposal_executed: bool,
    pub research_result: bool,
    pub consumed_wave5_gate_count: &'static str,
    pub provider_units: &'static str,
    pub external_mutation_units: &'static str,
    pub wave5_gates_resolved: bool,
    pub operational_release: bool,
    pub empirical_claim: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

/// Commits, exactly retries and read-only reopens the frozen N00 registration.
///
/// This function performs no provider, network, presentation, wallet, signing, transaction,
/// deployment or external-mutation operation. It never resolves a Wave 5 gate.
///
/// # Errors
///
/// Refuses filesystem, clock, migration, exact-registration, retry or readback failures.
#[allow(clippy::too_many_lines)] // Keeps the exact ordered fixture chain and false ceilings local.
pub fn run_wave6_program_registration(
    state: &Path,
) -> Result<Wave6ProgramRegistrationReport, Wave6RegistrationError> {
    fs::create_dir_all(state)?;
    let store_config = config(state)?;
    let mut store = SqliteStore::open(store_config.clone(), StoreMode::SingleWriter)?;
    let migration = store.migrate(now()?)?;
    if migration.current != 18 {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 registration did not reach V18",
        ));
    }
    let batch_id = StableString::new(BATCH_ID)?;
    let writer_build = StableString::new(format!("joshi-core-{}", env!("CARGO_PKG_VERSION")))?;
    let accepted = store.commit_wave6_program_registration_v1(
        REGISTRATION,
        batch_id.clone(),
        writer_build.clone(),
    )?;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.catalog_schema.as_str() != "joshi.sqlite.v18"
        || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "first Wave 6 registration returned an impossible receipt",
        ));
    }
    let retry =
        store.commit_wave6_program_registration_v1(REGISTRATION, batch_id, writer_build.clone())?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.program_id != accepted.program_id
        || retry.registration_digest != accepted.registration_digest
        || retry.document_digest != accepted.document_digest
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 registration retry changed durable identity",
        ));
    }
    let schema_reports = commit_schemas(&mut store, &accepted.program_id, &writer_build)?;
    let artifact_reports = commit_artifacts(&mut store, &accepted.program_id, &writer_build)?;
    let research_proposal =
        commit_research_proposal(&mut store, &accepted.program_id, &writer_build)?;
    let research_disposition =
        commit_research_disposition(&mut store, &research_proposal, &writer_build)?;
    let dag_report = commit_artifact_dag(&mut store, &accepted.program_id, &writer_build)?;
    let decision_report = commit_decision_ledger(&mut store, &dag_report, &writer_build)?;
    let campaign_report = commit_campaign_bundle(&mut store, &accepted.program_id, &writer_build)?;
    drop(store);

    let reopened = SqliteStore::open(store_config, StoreMode::ReadOnly)?;
    let program_id = StableString::new(PROGRAM_ID)?;
    let stored = reopened
        .load_wave6_program_registration_v1(&program_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 registration was absent after restart",
        ))?;
    if stored.program_id != accepted.program_id
        || stored.exact_bytes != REGISTRATION
        || stored.registration_digest != accepted.registration_digest
        || stored.document_digest != accepted.document_digest
        || stored.commit_seq != accepted.commit_seq
        || stored.commit_digest != accepted.commit_digest
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 registration changed across read-only reopen",
        ));
    }
    verify_schemas(&reopened, &program_id, &schema_reports)?;
    verify_artifacts(&reopened, &artifact_reports)?;
    verify_research_proposal(&reopened, &research_proposal)?;
    verify_research_disposition(&reopened, &research_disposition)?;
    verify_artifact_dag(&reopened, &dag_report)?;
    verify_decision_ledger(&reopened, &decision_report)?;
    verify_campaign_bundle(&reopened, &campaign_report)?;

    Ok(Wave6ProgramRegistrationReport {
        contract: "joshi.core.wave6_program_registration_report.v8",
        schema_version: 8,
        status: "fixture_only",
        authority: AUTHORITY,
        semantic_ceiling: stored.semantic_ceiling,
        catalog_schema: accepted.catalog_schema.to_string(),
        program_id: stored.program_id.to_string(),
        registration_digest: stored.registration_digest.to_string(),
        document_digest: stored.document_digest.to_string(),
        accepted_commit_seq: stored.commit_seq.get().to_string(),
        first_status: accepted.status,
        retry_status: retry.status,
        registration_persisted: true,
        restart_reverified: true,
        registered_schema_count: schema_reports.len().to_string(),
        schemas: schema_reports,
        schema_catalog_persisted: true,
        schema_catalog_restart_reverified: true,
        fixture_artifact_content_count: artifact_reports.len().to_string(),
        fixture_artifacts: artifact_reports,
        fixture_artifact_content_persisted: true,
        fixture_artifact_content_restart_reverified: true,
        fixture_artifact_dag: dag_report,
        fixture_artifact_dag_persisted: true,
        fixture_artifact_dag_restart_reverified: true,
        fixture_decision_ledger: decision_report,
        fixture_decision_ledger_persisted: true,
        fixture_decision_ledger_restart_reverified: true,
        fixture_campaign_bundle: campaign_report,
        fixture_campaign_bundle_persisted: true,
        fixture_campaign_bundle_restart_reverified: true,
        prospective_campaign_journal: false,
        fixture_research_proposal: research_proposal,
        fixture_research_proposal_persisted: true,
        fixture_research_proposal_restart_reverified: true,
        fixture_research_disposition: research_disposition,
        fixture_research_disposition_persisted: true,
        fixture_research_disposition_restart_reverified: true,
        human_research_review: false,
        proposal_executed: false,
        research_result: false,
        consumed_wave5_gate_count: "0",
        provider_units: "0",
        external_mutation_units: "0",
        wave5_gates_resolved: false,
        operational_release: false,
        empirical_claim: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn campaign_bundle_bytes() -> Wave6FixtureCampaignBundleBytes<'static> {
    Wave6FixtureCampaignBundleBytes {
        registration: CAMPAIGN_REGISTRATION,
        enrollment: CAMPAIGN_ENROLLMENT,
        assignment: CAMPAIGN_ASSIGNMENT,
        seal: CAMPAIGN_SEAL,
        adjudication: CAMPAIGN_ADJUDICATION,
    }
}

fn commit_research_proposal(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Wave6FixtureResearchProposalReport, Wave6RegistrationError> {
    let batch_id = StableString::new("wave6:research-proposal:fixture-001")?;
    let accepted = store.commit_wave6_fixture_research_proposal_v1(
        program_id,
        RESEARCH_PROPOSAL,
        batch_id.clone(),
        writer_build.clone(),
    )?;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research proposal returned an impossible first receipt",
        ));
    }
    let retry = store.commit_wave6_fixture_research_proposal_v1(
        program_id,
        RESEARCH_PROPOSAL,
        batch_id,
        writer_build.clone(),
    )?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.proposal_id != accepted.proposal_id
        || retry.proposal_digest != accepted.proposal_digest
        || retry.content_digest != accepted.content_digest
        || retry.commitment_digest != accepted.commitment_digest
        || retry.policy_digest != accepted.policy_digest
        || retry.evidence_closure_digest != accepted.evidence_closure_digest
        || retry.descriptor_count != accepted.descriptor_count
        || retry.counterexample_count != accepted.counterexample_count
        || retry.experiment_count != accepted.experiment_count
        || retry.total_experiment_units != accepted.total_experiment_units
        || retry.maximum_fixture_alleged_commit_seq != accepted.maximum_fixture_alleged_commit_seq
        || retry.maximum_resolved_artifact_commit_seq
            != accepted.maximum_resolved_artifact_commit_seq
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 research proposal retry changed durable identity",
        ));
    }
    let stored = store
        .load_wave6_fixture_research_proposal_v1(&accepted.proposal_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research proposal was absent after commit",
        ))?;
    if stored.exact_bytes != RESEARCH_PROPOSAL
        || stored.commit_seq != accepted.commit_seq
        || stored.commit_digest != accepted.commit_digest
        || u64::try_from(stored.artifact_bindings.len()).ok() != Some(accepted.descriptor_count)
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 research proposal readback differed from its receipt",
        ));
    }
    Ok(research_proposal_report(&stored))
}

fn research_proposal_report(
    stored: &StoredWave6FixtureResearchProposal,
) -> Wave6FixtureResearchProposalReport {
    Wave6FixtureResearchProposalReport {
        proposal_id: stored.proposal_id.to_string(),
        proposal_digest: stored.proposal_digest.to_string(),
        content_digest: stored.content_digest.to_string(),
        commitment_digest: stored.commitment_digest.to_string(),
        policy_digest: stored.policy_digest.to_string(),
        evidence_closure_digest: stored.evidence_closure_digest.to_string(),
        descriptor_count: stored.descriptor_count.to_string(),
        counterexample_count: stored.counterexample_count.to_string(),
        experiment_count: stored.experiment_count.to_string(),
        total_experiment_units: stored.total_experiment_units.to_string(),
        maximum_fixture_alleged_commit_seq: stored.maximum_fixture_alleged_commit_seq.to_string(),
        maximum_resolved_artifact_commit_seq: stored
            .maximum_resolved_artifact_commit_seq
            .get()
            .to_string(),
        artifact_bindings: stored
            .artifact_bindings
            .iter()
            .map(|binding| Wave6FixtureResearchArtifactBindingReport {
                descriptor_artifact_id: binding.descriptor_artifact_id.to_string(),
                provenance_digest: binding.provenance_digest.to_string(),
                resolved_artifact_id: binding.resolved_artifact_id.to_string(),
                resolved_kind_id: binding.resolved_kind_id.to_string(),
                fixture_alleged_commit_seq: binding.fixture_alleged_commit_seq.to_string(),
                resolved_artifact_commit_seq: binding
                    .resolved_artifact_commit_seq
                    .get()
                    .to_string(),
            })
            .collect(),
        commit_seq: stored.commit_seq.get().to_string(),
    }
}

fn verify_research_proposal(
    store: &SqliteStore,
    report: &Wave6FixtureResearchProposalReport,
) -> Result<(), Wave6RegistrationError> {
    let proposal_id = StableString::new(report.proposal_id.clone())?;
    let stored = store
        .load_wave6_fixture_research_proposal_v1(&proposal_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research proposal was absent after restart",
        ))?;
    if stored.exact_bytes != RESEARCH_PROPOSAL
        || research_proposal_report(&stored) != *report
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research proposal changed across read-only reopen",
        ));
    }
    Ok(())
}

fn commit_research_disposition(
    store: &mut SqliteStore,
    proposal: &Wave6FixtureResearchProposalReport,
    writer_build: &StableString,
) -> Result<Wave6FixtureResearchDispositionReport, Wave6RegistrationError> {
    let proposal_id = StableString::new(proposal.proposal_id.clone())?;
    let batch_id = StableString::new("wave6:research-disposition:fixture-001")?;
    let accepted = store.commit_wave6_fixture_research_disposition_v1(
        &proposal_id,
        RESEARCH_DISPOSITION,
        batch_id.clone(),
        writer_build.clone(),
    )?;
    let expected_authority = ResearchDispositionAuthorityV1::
        CallerFedFixtureUnverifiedNoHumanReviewApprovalExecutionOrResult;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        || accepted.authority_boundary != expected_authority
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research disposition returned an impossible first receipt",
        ));
    }
    let retry = store.commit_wave6_fixture_research_disposition_v1(
        &proposal_id,
        RESEARCH_DISPOSITION,
        batch_id,
        writer_build.clone(),
    )?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.disposition_id != accepted.disposition_id
        || retry.proposal_id != accepted.proposal_id
        || retry.proposal_digest != accepted.proposal_digest
        || retry.proposal_content_digest != accepted.proposal_content_digest
        || retry.disposition != accepted.disposition
        || retry.reviewer_id != accepted.reviewer_id
        || retry.decided_at != accepted.decided_at
        || retry.content_digest != accepted.content_digest
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
        || retry.authority_boundary != expected_authority
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 research disposition retry changed durable identity",
        ));
    }
    let stored = store
        .load_wave6_fixture_research_disposition_v1(&accepted.disposition_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research disposition was absent after commit",
        ))?;
    if stored.exact_bytes != RESEARCH_DISPOSITION
        || stored.commit_seq != accepted.commit_seq
        || stored.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 research disposition readback differed from its receipt",
        ));
    }
    Ok(research_disposition_report(&stored))
}

fn research_disposition_report(
    stored: &StoredWave6FixtureResearchDisposition,
) -> Wave6FixtureResearchDispositionReport {
    Wave6FixtureResearchDispositionReport {
        disposition_id: stored.disposition_id.to_string(),
        proposal_id: stored.proposal_id.to_string(),
        proposal_digest: stored.proposal_digest.to_string(),
        proposal_content_digest: stored.proposal_content_digest.to_string(),
        disposition: disposition_kind(stored.disposition),
        reviewer_id: stored.reviewer_id.to_string(),
        decided_at: stored.decided_at.to_string(),
        reason: stored.reason.clone(),
        content_digest: stored.content_digest.to_string(),
        identity_authority: "caller_fed_fixture_unverified",
        authority_boundary: "no_verified_human_review_approval_execution_result_or_release_authority",
        commit_seq: stored.commit_seq.get().to_string(),
    }
}

fn verify_research_disposition(
    store: &SqliteStore,
    report: &Wave6FixtureResearchDispositionReport,
) -> Result<(), Wave6RegistrationError> {
    let disposition_id = StableString::new(report.disposition_id.clone())?;
    let stored = store
        .load_wave6_fixture_research_disposition_v1(&disposition_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research disposition was absent after restart",
        ))?;
    if stored.exact_bytes != RESEARCH_DISPOSITION
        || research_disposition_report(&stored) != *report
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        || stored.authority_boundary
            != ResearchDispositionAuthorityV1::
                CallerFedFixtureUnverifiedNoHumanReviewApprovalExecutionOrResult
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture research disposition changed across read-only reopen",
        ));
    }
    Ok(())
}

const fn disposition_kind(value: ResearchDispositionKindV1) -> &'static str {
    match value {
        ResearchDispositionKindV1::Accept => "accept",
        ResearchDispositionKindV1::Reject => "reject",
        ResearchDispositionKindV1::Hold => "hold",
        ResearchDispositionKindV1::Supersede => "supersede",
    }
}

fn commit_campaign_bundle(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Wave6FixtureCampaignBundleReport, Wave6RegistrationError> {
    let batch_id = StableString::new("wave6:campaign-bundle:fixture-001")?;
    let accepted = store.commit_wave6_fixture_campaign_bundle_v1(
        program_id,
        campaign_bundle_bytes(),
        batch_id.clone(),
        writer_build.clone(),
    )?;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture campaign bundle returned an impossible first receipt",
        ));
    }
    let retry = store.commit_wave6_fixture_campaign_bundle_v1(
        program_id,
        campaign_bundle_bytes(),
        batch_id,
        writer_build.clone(),
    )?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.bundle_id != accepted.bundle_id
        || retry.campaign_id != accepted.campaign_id
        || retry.registration_digest != accepted.registration_digest
        || retry.enrollment_digest != accepted.enrollment_digest
        || retry.assignment_digest != accepted.assignment_digest
        || retry.seal_digest != accepted.seal_digest
        || retry.adjudication_digest != accepted.adjudication_digest
        || retry.bundle_digest != accepted.bundle_digest
        || retry.eligible_subject_count != accepted.eligible_subject_count
        || retry.included_subject_count != accepted.included_subject_count
        || retry.assignment_count != accepted.assignment_count
        || retry.outcome_count != accepted.outcome_count
        || retry.maximum_fixture_alleged_commit_seq != accepted.maximum_fixture_alleged_commit_seq
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 campaign bundle retry changed durable identity",
        ));
    }
    Ok(Wave6FixtureCampaignBundleReport {
        bundle_id: accepted.bundle_id.to_string(),
        campaign_id: accepted.campaign_id.to_string(),
        registration_digest: accepted.registration_digest.to_string(),
        enrollment_digest: accepted.enrollment_digest.to_string(),
        assignment_digest: accepted.assignment_digest.to_string(),
        seal_digest: accepted.seal_digest.to_string(),
        adjudication_digest: accepted.adjudication_digest.to_string(),
        bundle_digest: accepted.bundle_digest.to_string(),
        eligible_subject_count: accepted.eligible_subject_count.to_string(),
        included_subject_count: accepted.included_subject_count.to_string(),
        assignment_count: accepted.assignment_count.to_string(),
        outcome_count: accepted.outcome_count.to_string(),
        maximum_fixture_alleged_commit_seq: accepted.maximum_fixture_alleged_commit_seq.to_string(),
        commit_seq: accepted.commit_seq.get().to_string(),
    })
}

fn commit_decision_ledger(
    store: &mut SqliteStore,
    dag: &Wave6FixtureArtifactDagReport,
    writer_build: &StableString,
) -> Result<Wave6FixtureDecisionLedgerReport, Wave6RegistrationError> {
    let dag_id = StableString::new(dag.dag_id.clone())?;
    let batch_id = StableString::new("wave6:decision-ledger:fixture-001")?;
    let accepted = store.commit_wave6_fixture_decision_ledger_v1(
        &dag_id,
        DECISION_LEDGER,
        batch_id.clone(),
        writer_build.clone(),
    )?;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture decision ledger returned an impossible first receipt",
        ));
    }
    let retry = store.commit_wave6_fixture_decision_ledger_v1(
        &dag_id,
        DECISION_LEDGER,
        batch_id,
        writer_build.clone(),
    )?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.ledger_id != accepted.ledger_id
        || retry.dag_id != accepted.dag_id
        || retry.ledger_digest != accepted.ledger_digest
        || retry.document_digest != accepted.document_digest
        || retry.decision_count != accepted.decision_count
        || retry.maximum_decided_at != accepted.maximum_decided_at
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 fixture decision retry changed durable identity",
        ));
    }
    Ok(Wave6FixtureDecisionLedgerReport {
        ledger_id: accepted.ledger_id.to_string(),
        ledger_digest: accepted.ledger_digest.to_string(),
        document_digest: accepted.document_digest.to_string(),
        decision_count: accepted.decision_count.to_string(),
        maximum_decided_at: accepted.maximum_decided_at.to_string(),
        commit_seq: accepted.commit_seq.get().to_string(),
    })
}

fn commit_artifact_dag(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Wave6FixtureArtifactDagReport, Wave6RegistrationError> {
    let batch_id = StableString::new("wave6:artifact-dag:fixture-001")?;
    let accepted = store.commit_wave6_fixture_artifact_dag_v1(
        program_id,
        ARTIFACT_DAG,
        batch_id.clone(),
        writer_build.clone(),
    )?;
    if !matches!(
        accepted.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture DAG returned an impossible first receipt",
        ));
    }
    let retry = store.commit_wave6_fixture_artifact_dag_v1(
        program_id,
        ARTIFACT_DAG,
        batch_id,
        writer_build.clone(),
    )?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.dag_id != accepted.dag_id
        || retry.dag_digest != accepted.dag_digest
        || retry.document_digest != accepted.document_digest
        || retry.artifact_count != accepted.artifact_count
        || retry.maximum_information_cutoff != accepted.maximum_information_cutoff
        || retry.maximum_produced_at != accepted.maximum_produced_at
        || retry.commit_seq != accepted.commit_seq
        || retry.commit_digest != accepted.commit_digest
    {
        return Err(Wave6RegistrationError::Invariant(
            "exact Wave 6 fixture DAG retry changed durable identity",
        ));
    }
    Ok(Wave6FixtureArtifactDagReport {
        dag_id: accepted.dag_id.to_string(),
        dag_digest: accepted.dag_digest.to_string(),
        document_digest: accepted.document_digest.to_string(),
        artifact_count: accepted.artifact_count.to_string(),
        maximum_information_cutoff: accepted.maximum_information_cutoff.to_string(),
        maximum_produced_at: accepted.maximum_produced_at.to_string(),
        commit_seq: accepted.commit_seq.get().to_string(),
    })
}

fn commit_schemas(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Vec<Wave6ArtifactSchemaReport>, Wave6RegistrationError> {
    let mut reports = Vec::with_capacity(schemas().len());
    for fixture in schemas() {
        let kind_id = StableString::new(fixture.kind_id)?;
        let batch_id = StableString::new(format!("wave6:schema:{}", fixture.kind_id))?;
        let accepted = store.commit_wave6_artifact_schema_v1(
            program_id,
            kind_id.clone(),
            fixture.bytes,
            batch_id.clone(),
            writer_build.clone(),
        )?;
        if !matches!(
            accepted.status,
            IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
        ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 schema returned an impossible first receipt",
            ));
        }
        let retry = store.commit_wave6_artifact_schema_v1(
            program_id,
            kind_id,
            fixture.bytes,
            batch_id,
            writer_build.clone(),
        )?;
        if retry.status != IdempotencyStatus::Idempotent
            || retry.kind_id != accepted.kind_id
            || retry.schema_id != accepted.schema_id
            || retry.schema_digest != accepted.schema_digest
            || retry.commit_seq != accepted.commit_seq
            || retry.commit_digest != accepted.commit_digest
        {
            return Err(Wave6RegistrationError::Invariant(
                "exact Wave 6 schema retry changed durable identity",
            ));
        }
        reports.push(Wave6ArtifactSchemaReport {
            kind_id: accepted.kind_id.to_string(),
            schema_id: accepted.schema_id.to_string(),
            schema_digest: accepted.schema_digest.to_string(),
            commit_seq: accepted.commit_seq.get().to_string(),
        });
    }
    Ok(reports)
}

fn verify_schemas(
    store: &SqliteStore,
    program_id: &StableString,
    reports: &[Wave6ArtifactSchemaReport],
) -> Result<(), Wave6RegistrationError> {
    if reports.len() != schemas().len() {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 schema catalog has the wrong cardinality",
        ));
    }
    for (fixture, report) in schemas().into_iter().zip(reports) {
        if fixture.kind_id != report.kind_id {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 schema order changed before restart readback",
            ));
        }
        let kind_id = StableString::new(fixture.kind_id)?;
        let stored = store
            .load_wave6_artifact_schema_v1(program_id, &kind_id)?
            .ok_or(Wave6RegistrationError::Invariant(
                "Wave 6 schema was absent after restart",
            ))?;
        if stored.kind_id.as_str() != report.kind_id
            || stored.schema_id.as_str() != report.schema_id
            || stored.schema_digest.as_str() != report.schema_digest
            || stored.commit_seq.get().to_string() != report.commit_seq
            || stored.exact_bytes != fixture.bytes
            || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 schema changed across read-only reopen",
            ));
        }
    }
    Ok(())
}

fn commit_artifacts(
    store: &mut SqliteStore,
    program_id: &StableString,
    writer_build: &StableString,
) -> Result<Vec<Wave6FixtureArtifactReport>, Wave6RegistrationError> {
    let mut reports = Vec::with_capacity(artifacts().len());
    for fixture in artifacts() {
        let kind_id = StableString::new(fixture.kind_id)?;
        let batch_id = StableString::new(format!("wave6:artifact:{}", fixture.kind_id))?;
        let accepted = store.commit_wave6_fixture_artifact_v1(
            program_id,
            kind_id.clone(),
            fixture.bytes,
            batch_id.clone(),
            writer_build.clone(),
        )?;
        if !matches!(
            accepted.status,
            IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
        ) || accepted.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 fixture artifact returned an impossible first receipt",
            ));
        }
        let retry = store.commit_wave6_fixture_artifact_v1(
            program_id,
            kind_id,
            fixture.bytes,
            batch_id,
            writer_build.clone(),
        )?;
        if retry.status != IdempotencyStatus::Idempotent
            || retry.artifact_id != accepted.artifact_id
            || retry.kind_id != accepted.kind_id
            || retry.schema_id != accepted.schema_id
            || retry.content_digest != accepted.content_digest
            || retry.evaluation_digest != accepted.evaluation_digest
            || retry.result_count != accepted.result_count
            || retry.commit_seq != accepted.commit_seq
            || retry.commit_digest != accepted.commit_digest
        {
            return Err(Wave6RegistrationError::Invariant(
                "exact Wave 6 artifact retry changed durable identity",
            ));
        }
        reports.push(Wave6FixtureArtifactReport {
            artifact_id: accepted.artifact_id.to_string(),
            kind_id: accepted.kind_id.to_string(),
            schema_id: accepted.schema_id.to_string(),
            content_digest: accepted.content_digest.to_string(),
            evaluation_digest: accepted.evaluation_digest.to_string(),
            result_count: accepted.result_count.to_string(),
            commit_seq: accepted.commit_seq.get().to_string(),
        });
    }
    Ok(reports)
}

fn verify_artifacts(
    store: &SqliteStore,
    reports: &[Wave6FixtureArtifactReport],
) -> Result<(), Wave6RegistrationError> {
    if reports.len() != artifacts().len() {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture artifact catalog has the wrong cardinality",
        ));
    }
    for (fixture, report) in artifacts().into_iter().zip(reports) {
        if fixture.kind_id != report.kind_id {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 artifact order changed before restart readback",
            ));
        }
        let artifact_id = StableString::new(report.artifact_id.clone())?;
        let stored = store.load_wave6_fixture_artifact_v1(&artifact_id)?.ok_or(
            Wave6RegistrationError::Invariant("Wave 6 fixture artifact was absent after restart"),
        )?;
        if stored.artifact_id.as_str() != report.artifact_id
            || stored.kind_id.as_str() != report.kind_id
            || stored.schema_id.as_str() != report.schema_id
            || stored.content_digest.as_str() != report.content_digest
            || stored.evaluation_digest.as_str() != report.evaluation_digest
            || stored.result_count.to_string() != report.result_count
            || stored.commit_seq.get().to_string() != report.commit_seq
            || stored.exact_bytes != fixture.bytes
            || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(Wave6RegistrationError::Invariant(
                "Wave 6 fixture artifact changed across read-only reopen",
            ));
        }
    }
    Ok(())
}

fn verify_artifact_dag(
    store: &SqliteStore,
    report: &Wave6FixtureArtifactDagReport,
) -> Result<(), Wave6RegistrationError> {
    let dag_id = StableString::new(report.dag_id.clone())?;
    let stored = store.load_wave6_fixture_artifact_dag_v1(&dag_id)?.ok_or(
        Wave6RegistrationError::Invariant("Wave 6 fixture DAG was absent after restart"),
    )?;
    if stored.exact_bytes != ARTIFACT_DAG
        || stored.dag_digest.as_str() != report.dag_digest
        || stored.document_digest.as_str() != report.document_digest
        || stored.artifact_count.to_string() != report.artifact_count
        || stored.maximum_information_cutoff.to_string() != report.maximum_information_cutoff
        || stored.maximum_produced_at.to_string() != report.maximum_produced_at
        || stored.commit_seq.get().to_string() != report.commit_seq
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture DAG changed across read-only reopen",
        ));
    }
    Ok(())
}

fn verify_decision_ledger(
    store: &SqliteStore,
    report: &Wave6FixtureDecisionLedgerReport,
) -> Result<(), Wave6RegistrationError> {
    let ledger_id = StableString::new(report.ledger_id.clone())?;
    let stored = store
        .load_wave6_fixture_decision_ledger_v1(&ledger_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 fixture decision ledger was absent after restart",
        ))?;
    if stored.exact_bytes != DECISION_LEDGER
        || stored.ledger_digest.as_str() != report.ledger_digest
        || stored.document_digest.as_str() != report.document_digest
        || stored.decision_count.to_string() != report.decision_count
        || stored.maximum_decided_at.to_string() != report.maximum_decided_at
        || stored.commit_seq.get().to_string() != report.commit_seq
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture decision ledger changed across read-only reopen",
        ));
    }
    Ok(())
}

fn verify_campaign_bundle(
    store: &SqliteStore,
    report: &Wave6FixtureCampaignBundleReport,
) -> Result<(), Wave6RegistrationError> {
    let bundle_id = StableString::new(report.bundle_id.clone())?;
    let stored = store
        .load_wave6_fixture_campaign_bundle_v1(&bundle_id)?
        .ok_or(Wave6RegistrationError::Invariant(
            "Wave 6 fixture campaign bundle was absent after restart",
        ))?;
    if stored.registration_bytes != CAMPAIGN_REGISTRATION
        || stored.enrollment_bytes != CAMPAIGN_ENROLLMENT
        || stored.assignment_bytes != CAMPAIGN_ASSIGNMENT
        || stored.seal_bytes != CAMPAIGN_SEAL
        || stored.adjudication_bytes != CAMPAIGN_ADJUDICATION
        || stored.campaign_id.as_str() != report.campaign_id
        || stored.registration_digest.as_str() != report.registration_digest
        || stored.enrollment_digest.as_str() != report.enrollment_digest
        || stored.assignment_digest.as_str() != report.assignment_digest
        || stored.seal_digest.as_str() != report.seal_digest
        || stored.adjudication_digest.as_str() != report.adjudication_digest
        || stored.bundle_digest.as_str() != report.bundle_digest
        || stored.eligible_subject_count.to_string() != report.eligible_subject_count
        || stored.included_subject_count.to_string() != report.included_subject_count
        || stored.assignment_count.to_string() != report.assignment_count
        || stored.outcome_count.to_string() != report.outcome_count
        || stored.maximum_fixture_alleged_commit_seq.to_string()
            != report.maximum_fixture_alleged_commit_seq
        || stored.commit_seq.get().to_string() != report.commit_seq
        || stored.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    {
        return Err(Wave6RegistrationError::Invariant(
            "Wave 6 fixture campaign bundle changed across read-only reopen",
        ));
    }
    Ok(())
}

fn schemas() -> [SchemaFixture; 6] {
    [
        SchemaFixture {
            kind_id: "campaign_registration_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/campaign_registration_v1.json"),
        },
        SchemaFixture {
            kind_id: "known_truth_evaluation_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/known_truth_evaluation_v1.json"),
        },
        SchemaFixture {
            kind_id: "market_atlas_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/market_atlas_snapshot_v1.json"),
        },
        SchemaFixture {
            kind_id: "protocol_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/schemas/protocol_known_truth_evaluation_v1.json"
            ),
        },
        SchemaFixture {
            kind_id: "research_proposal_fixture",
            bytes: include_bytes!("../../../fixtures/wave6/schemas/research_proposal_v1.json"),
        },
        SchemaFixture {
            kind_id: "structural_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/schemas/structural_known_truth_evaluation_v1.json"
            ),
        },
    ]
}

fn artifacts() -> [ArtifactFixture; 3] {
    [
        ArtifactFixture {
            kind_id: "known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/artifacts/known_truth_evaluation_v1.json"
            ),
        },
        ArtifactFixture {
            kind_id: "protocol_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/artifacts/protocol_known_truth_evaluation_v1.json"
            ),
        },
        ArtifactFixture {
            kind_id: "structural_known_truth_evaluation_fixture",
            bytes: include_bytes!(
                "../../../fixtures/wave6/artifacts/structural_known_truth_evaluation_v1.json"
            ),
        },
    ]
}

fn config(root: &Path) -> Result<StoreConfig, Wave6RegistrationError> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-wave6-fixture-registry")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

fn now() -> Result<joshi_domain::UtcTimestamp, Wave6RegistrationError> {
    let nanos = time::OffsetDateTime::now_utc().unix_timestamp_nanos();
    let micros = nanos.div_euclid(1_000) * 1_000;
    joshi_domain::UtcTimestamp::new(
        time::OffsetDateTime::from_unix_timestamp_nanos(micros)
            .map_err(|_| Wave6RegistrationError::Clock)?,
    )
    .map_err(|_| Wave6RegistrationError::Clock)
}

/// Failure to produce the exact, non-promoting registration witness.
#[derive(Debug, Error)]
pub enum Wave6RegistrationError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error("system clock is unavailable")]
    Clock,
    #[error("Wave 6 fixture registration invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_registration_retries_and_reopens_without_operational_claims() {
        let state = tempfile::tempdir().expect("temporary registration state");
        let first =
            run_wave6_program_registration(state.path()).expect("first registration witness");
        assert_eq!(first.status, "fixture_only");
        assert_eq!(first.catalog_schema, "joshi.sqlite.v18");
        assert_eq!(first.first_status, IdempotencyStatus::Accepted);
        assert_eq!(first.retry_status, IdempotencyStatus::Idempotent);
        assert!(first.registration_persisted);
        assert!(first.restart_reverified);
        assert_eq!(first.registered_schema_count, "6");
        assert_eq!(first.schemas.len(), 6);
        assert!(first.schema_catalog_persisted);
        assert!(first.schema_catalog_restart_reverified);
        assert_eq!(first.fixture_artifact_content_count, "3");
        assert_eq!(first.fixture_artifacts.len(), 3);
        assert!(first.fixture_artifact_content_persisted);
        assert!(first.fixture_artifact_content_restart_reverified);
        assert_eq!(first.fixture_artifact_dag.artifact_count, "3");
        assert!(first.fixture_artifact_dag_persisted);
        assert!(first.fixture_artifact_dag_restart_reverified);
        assert_eq!(first.fixture_decision_ledger.decision_count, "3");
        assert!(first.fixture_decision_ledger_persisted);
        assert!(first.fixture_decision_ledger_restart_reverified);
        assert_eq!(first.fixture_campaign_bundle.eligible_subject_count, "3");
        assert_eq!(first.fixture_campaign_bundle.included_subject_count, "2");
        assert_eq!(first.fixture_campaign_bundle.assignment_count, "2");
        assert_eq!(first.fixture_campaign_bundle.outcome_count, "2");
        assert_eq!(
            first
                .fixture_campaign_bundle
                .maximum_fixture_alleged_commit_seq,
            "21"
        );
        assert!(first.fixture_campaign_bundle_persisted);
        assert!(first.fixture_campaign_bundle_restart_reverified);
        assert!(!first.prospective_campaign_journal);
        assert_eq!(first.fixture_research_proposal.descriptor_count, "3");
        assert_eq!(first.fixture_research_proposal.counterexample_count, "18");
        assert_eq!(first.fixture_research_proposal.experiment_count, "1");
        assert_eq!(first.fixture_research_proposal.total_experiment_units, "3");
        assert_eq!(first.fixture_research_proposal.artifact_bindings.len(), 3);
        assert!(first.fixture_research_proposal_persisted);
        assert!(first.fixture_research_proposal_restart_reverified);
        assert_eq!(first.fixture_research_disposition.disposition, "hold");
        assert_eq!(
            first.fixture_research_disposition.reviewer_id,
            "fixture-reviewer-unverified"
        );
        assert_eq!(
            first.fixture_research_disposition.identity_authority,
            "caller_fed_fixture_unverified"
        );
        assert!(first.fixture_research_disposition_persisted);
        assert!(first.fixture_research_disposition_restart_reverified);
        assert!(!first.human_research_review);
        assert!(!first.proposal_executed);
        assert!(!first.research_result);
        assert_eq!(first.consumed_wave5_gate_count, "0");
        assert!(!first.wave5_gates_resolved);
        assert!(!first.operational_release);
        assert!(!first.empirical_claim);
        assert!(!first.product_qualified);
        assert!(!first.live_qualified);

        let repeated =
            run_wave6_program_registration(state.path()).expect("repeated registration witness");
        assert_eq!(repeated.first_status, IdempotencyStatus::Idempotent);
        assert_eq!(repeated.retry_status, IdempotencyStatus::Idempotent);
        assert_eq!(repeated.registration_digest, first.registration_digest);
        assert_eq!(repeated.document_digest, first.document_digest);
        assert_eq!(repeated.accepted_commit_seq, first.accepted_commit_seq);
        assert_eq!(repeated.schemas, first.schemas);
        assert_eq!(repeated.fixture_artifacts, first.fixture_artifacts);
        assert_eq!(repeated.fixture_artifact_dag, first.fixture_artifact_dag);
        assert_eq!(
            repeated.fixture_decision_ledger,
            first.fixture_decision_ledger
        );
        assert_eq!(
            repeated.fixture_campaign_bundle,
            first.fixture_campaign_bundle
        );
        assert_eq!(
            repeated.fixture_research_proposal,
            first.fixture_research_proposal
        );
        assert_eq!(
            repeated.fixture_research_disposition,
            first.fixture_research_disposition
        );
    }
}
