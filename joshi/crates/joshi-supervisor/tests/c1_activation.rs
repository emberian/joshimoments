//! End-to-end, no-I/O checks for the disabled C1 supervisor admission seam.

#![allow(clippy::struct_field_names, clippy::uninlined_format_args)]

mod support;

use joshi_domain::{StableString, UtcTimestamp};
use joshi_sources::{
    CanaryProfilePort, ProviderOperation, ProviderOperationPlan, ProviderRunPlanTemplate,
    ProviderScopePort, RegisteredRunPort, RuntimeAttemptCostPort, RuntimeBudgetPort,
    validate_provider_run_plan,
};
use joshi_store::{
    SqliteStore, StoreConfig, StoreMode, Wave5C1ActivationReceipt, Wave5CommitContext,
    Wave5RunRegistrationByteBundle,
};
use joshi_supervisor::{AUTHORITY_CEILING, DisabledC1AdmissionError, Supervisor};
use joshi_wave5_c1_activation::{
    ExactC1BudgetProjectionV1, ExactPlanClosureV1, ExactSourceMethodProjectionV1,
    FinalityCommitmentV1, PublicWalletPageV1, Wave5C1ActivationV1,
};
use serde::Serialize;
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeMap, path::Path, str::FromStr, time::Duration};
use tempfile::TempDir;

const AUTHORITY: &str = "read_only_no_execution";
const WALLET: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";
const SOURCE_FP: &str = "sha256:91f2d69db741edbef943e729cd65a0941de856badcd9d35cb153b5006ae6d247";
const METHOD_FP: &str = "sha256:b3bafc833d9b859fb0dc475d62fac353d5862994bdb01fe184a6b1dd85aea715";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Closure {
    digest: String,
    byte_length: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Document<'a> {
    document_id: &'a str,
    exact_bytes: Closure,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Registration<'a> {
    contract: &'a str,
    schema_version: u64,
    run_id: &'a str,
    build: Document<'a>,
    source_tree: Document<'a>,
    configuration: Document<'a>,
    budget: Document<'a>,
    privacy: Document<'a>,
    daily_use_surface_profile: Document<'a>,
    authority: &'a str,
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable test identity")
}

fn timestamp(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("valid fixed timestamp")
}

fn digest(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn document<'a>(id: &'a str, bytes: &[u8]) -> Document<'a> {
    Document {
        document_id: id,
        exact_bytes: Closure {
            digest: digest(bytes),
            byte_length: bytes.len().to_string(),
        },
    }
}

fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 1024,
        busy_timeout: Duration::from_secs(1),
        catalog_id: stable("catalog:c1-supervisor-admission"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}

fn open_store(root: &Path) -> SqliteStore {
    let mut store = SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open store");
    store
        .migrate(timestamp("2026-08-19T00:00:00.000000Z"))
        .expect("migrate store through V23");
    store
}

fn context(store: &SqliteStore, id: &str) -> Wave5CommitContext {
    store
        .begin_wave5_commit(stable(id), stable("build:c1-supervisor-test"))
        .expect("begin durable Wave 5 context")
}

fn zero_budget() -> RuntimeBudgetPort {
    RuntimeBudgetPort {
        requests: 0,
        pages: 0,
        ingress_bytes: 0,
        durable_bytes: 0,
        provider_credits: 0,
        wall_millis: 0,
        provider_currency_minor: BTreeMap::new(),
        chain_native_atoms: BTreeMap::new(),
    }
}

fn attempt_cost() -> RuntimeAttemptCostPort {
    RuntimeAttemptCostPort {
        worst_case: RuntimeBudgetPort {
            requests: 1,
            pages: 1,
            ingress_bytes: 1024,
            durable_bytes: 1024,
            provider_credits: 0,
            wall_millis: 1000,
            ..zero_budget()
        },
        max_overshoot: zero_budget(),
    }
}

fn plan_template() -> ProviderRunPlanTemplate {
    let attempt_cost = attempt_cost();
    ProviderRunPlanTemplate {
        port_version: "joshi.provider_run_plan_port.v2".into(),
        plan_id: "c1-supervisor-admission-plan".into(),
        profile: CanaryProfilePort::C1,
        hard_cap: attempt_cost.worst_case.clone(),
        max_elapsed_ms: 1000,
        max_ingress_bytes_per_second: None,
        max_in_flight_attempts: 1,
        operations: vec![ProviderOperationPlan {
            source_key: "solana.public.mainnet".into(),
            method_key: "get_signatures_for_address".into(),
            source_contract_fingerprint: SOURCE_FP.into(),
            method_schema_fingerprint: METHOD_FP.into(),
            operation: ProviderOperation::SolanaSignaturesForAddress,
            generation: 1,
            max_attempts: 1,
            scope: ProviderScopePort::PublicWalletPage {
                address: WALLET.into(),
                max_rows: 10,
            },
            attempt_cost,
        }],
    }
}

fn register_run(store: &mut SqliteStore, template_digest: &str) -> String {
    let tree = format!(r#"{{"contract":"joshi.wave5.source_tree_manifest","schemaVersion":1,"repositoryId":"joshi","head":{{"kind":"commit","object_id":"{}"}},"dirty":false,"workingTreeDigest":"{}","diffDigest":null,"authority":"{}"}}"#, "1".repeat(40), digest(b"tree"), AUTHORITY).into_bytes();
    let build = format!(r#"{{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"build:c1-supervisor-test","sourceTreeDigest":"{}","rustcVersion":"rustc-test","targetTriple":"test","profile":"local_debug","authority":"{}"}}"#, digest(&tree), AUTHORITY).into_bytes();
    let configuration = format!(r#"{{"contract":"joshi.collector.runtime_config.v1","schemaVersion":1,"planId":"c1-supervisor-admission-plan","planTemplateDigest":"{}","statusEndpoint":{{"address":"127.0.0.1","port":8123}},"providerExecution":"offline_fixture_only","authority":"{}"}}"#, template_digest, AUTHORITY).into_bytes();
    let budget = format!(r#"{{"contract":"joshi.collector.execution_accounting.v1","schemaVersion":1,"limits":{{"maximumRequests":1,"maximumPages":1,"maximumIngressBytes":1024,"maximumDurableBytes":1024,"maximumProviderCredits":0,"maximumIngressBytesPerSecond":1024,"maximumElapsedMs":1000,"maximumInFlightAttempts":1,"maximumInFlightElapsedOvershootMs":1}},"authority":"{}"}}"#, AUTHORITY).into_bytes();
    let privacy = format!(r#"{{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"privacy:c1","permittedProtectionClasses":["public_integrity"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":false,"authority":"{}"}}"#, AUTHORITY).into_bytes();
    let surface = include_str!("../../../fixtures/surface/daily_use_surface_profile_v1.json")
        .trim_end()
        .as_bytes()
        .to_vec();
    let registration = Registration {
        contract: "joshi.wave5.run_registration",
        schema_version: 1,
        run_id: "run:c1-supervisor-admission",
        build: document("build:c1", &build),
        source_tree: document("tree:c1", &tree),
        configuration: document("config:c1", &configuration),
        budget: document("budget:c1", &budget),
        privacy: document("privacy:c1", &privacy),
        daily_use_surface_profile: document("surface:c1", &surface),
        authority: AUTHORITY,
    };
    let registration = serde_json::to_vec(&registration).expect("canonical registration fixture");
    store
        .commit_wave5_run_registration_v1(
            &Wave5RunRegistrationByteBundle {
                registration: &registration,
                build: &build,
                source_tree: &tree,
                configuration: &configuration,
                budget: &budget,
                privacy: &privacy,
                daily_use_surface_profile: &surface,
            },
            &context(store, "run:c1-supervisor-admission"),
        )
        .expect("commit run registration")
        .exact_document_digest
        .to_string()
}

fn registered_claim(
    store: &mut SqliteStore,
    installation_id: &str,
    activation_id: &str,
    context_suffix: &str,
) -> (
    joshi_store::ClaimedWave5C1Activation,
    Wave5C1ActivationReceipt,
) {
    let template = plan_template();
    let template_digest = template.plan_template_digest().expect("template digest");
    let run_digest = register_run(store, &template_digest);
    let plan = validate_provider_run_plan(template.bind_run(RegisteredRunPort {
        run_id: "run:c1-supervisor-admission".into(),
        registration_digest: run_digest,
    }))
    .expect("valid exact C1 plan");
    let plan_bytes = plan.canonical_bytes().expect("canonical plan bytes");
    let operation = &plan.operations()[0];
    let activation = Wave5C1ActivationV1 {
        contract: "joshi.wave5.c1_activation.v1".into(),
        schema_version: 1,
        activation_id: activation_id.into(),
        installation_id: installation_id.into(),
        run: plan.plan().run.clone(),
        exact_plan: ExactPlanClosureV1 {
            plan_id: plan.plan().plan_id.clone(),
            port_version: plan.plan().port_version.clone(),
            raw_exact_plan_sha256: digest(&plan_bytes),
            raw_exact_plan_byte_length: plan_bytes.len().to_string(),
            plan_template_digest: plan.plan_template_digest().to_owned(),
            final_plan_digest: plan.plan_digest().to_owned(),
        },
        budget: ExactC1BudgetProjectionV1 {
            hard_cap: plan.plan().hard_cap.clone(),
            attempt_cost: operation.plan.attempt_cost.clone(),
            max_elapsed_ms: plan.plan().max_elapsed_ms,
            max_ingress_bytes_per_second: plan.plan().max_ingress_bytes_per_second,
            max_in_flight_attempts: plan.plan().max_in_flight_attempts,
        },
        operations: vec![ExactSourceMethodProjectionV1 {
            source_key: operation.plan.source_key.clone(),
            method_key: operation.plan.method_key.clone(),
            source_contract_fingerprint: operation.canonical_contract_fingerprint.clone(),
            method_schema_fingerprint: operation.method_schema_fingerprint.clone(),
            coverage_family: operation.coverage_family.clone(),
            protection_domain: operation.protection_domain.clone(),
        }],
        wallet: PublicWalletPageV1 {
            address: WALLET.into(),
            max_rows: 10,
        },
        commitment: FinalityCommitmentV1::Finalized,
        authority: AUTHORITY.into(),
    };
    let activation = serde_json::to_vec(&activation).expect("canonical activation bytes");
    let receipt = store
        .commit_wave5_c1_activation_v1(
            &activation,
            &plan_bytes,
            &context(store, &format!("activation:{context_suffix}")),
        )
        .expect("commit C1 activation");
    let claim = store
        .claim_wave5_c1_activation_v1(
            &stable(activation_id),
            &stable(installation_id),
            &context(store, &format!("claim:{context_suffix}")),
        )
        .expect("burn C1 activation once");
    (claim, receipt)
}

fn foreign_journal_refusal_keeps_claim_burned(installation_a: &str) {
    let foreign_store_root = TempDir::new().expect("foreign store root");
    let mut foreign_store = open_store(foreign_store_root.path());
    let (foreign_claim, _) = registered_claim(
        &mut foreign_store,
        installation_a,
        "activation:c1-admission-foreign",
        "foreign",
    );
    let foreign_id = stable("activation:c1-admission-foreign");
    let expected_receipt = foreign_claim.claim_receipt().clone();
    let foreign_supervisor_root = TempDir::new().expect("foreign supervisor root");
    let foreign_supervisor = Supervisor::open(support::config(foreign_supervisor_root.path()))
        .expect("open independent foreign supervisor journal");
    assert_ne!(foreign_supervisor.installation_id(), installation_a);
    let spool_before = foreign_supervisor
        .spool()
        .list_segments()
        .expect("list foreign spool");
    assert!(matches!(
        foreign_supervisor.admit_claimed_wave5_c1_disabled(foreign_claim),
        Err(DisabledC1AdmissionError::ForeignInstallation)
    ));
    assert_eq!(
        foreign_supervisor.spool().list_segments().unwrap(),
        spool_before
    );
    drop(foreign_store);

    let mut reopened =
        SqliteStore::open(config(foreign_store_root.path()), StoreMode::SingleWriter)
            .expect("reopen foreign claimed store");
    let durable_receipt = reopened
        .load_wave5_c1_activation_claim_receipt_v1(&foreign_id)
        .expect("read foreign claim receipt")
        .expect("claim receipt remains durable after foreign refusal");
    assert_eq!(durable_receipt, expected_receipt);
    assert!(
        reopened
            .claim_wave5_c1_activation_v1(
                &foreign_id,
                &stable(installation_a),
                &context(&reopened, "claim:foreign-reopen"),
            )
            .is_err(),
        "the rejected-by-foreign-journal capability stayed burned"
    );
}

#[test]
fn disabled_c1_admission_binds_real_journal_and_burned_store_claim_without_io() {
    let supervisor_a_root = TempDir::new().expect("supervisor A root");
    let supervisor_a = Supervisor::open(support::config(supervisor_a_root.path()))
        .expect("open supervisor A journal");
    let installation_a = supervisor_a.installation_id().to_owned();

    let accepted_store_root = TempDir::new().expect("accepted store root");
    let mut accepted_store = open_store(accepted_store_root.path());
    let (accepted_claim, activation_receipt) = registered_claim(
        &mut accepted_store,
        &installation_a,
        "activation:c1-admission-accepted",
        "accepted",
    );
    let expected_activation = accepted_claim.activation().clone();
    let expected_claim_receipt = accepted_claim.claim_receipt().clone();
    let expected_activation_sequence = accepted_claim.activation_commit_seq();
    let spool_before = supervisor_a
        .spool()
        .list_segments()
        .expect("list spool before");
    let status_before = supervisor_a.spool().status().expect("spool status before");

    let admission = supervisor_a
        .admit_claimed_wave5_c1_disabled(accepted_claim)
        .expect("matching actual journal identity is admitted without runtime activation");
    let report = admission.report();
    assert_eq!(report.activation_id, expected_activation.activation_id);
    assert_eq!(report.installation_id, installation_a);
    assert_eq!(report.run_registration_id, expected_activation.run.run_id);
    assert_eq!(
        report.run_registration_digest,
        expected_activation.run.registration_digest
    );
    assert_eq!(report.plan_id, expected_activation.exact_plan.plan_id);
    assert_eq!(
        report.plan_template_digest,
        expected_activation.exact_plan.plan_template_digest
    );
    assert_eq!(
        report.final_plan_digest,
        expected_activation.exact_plan.final_plan_digest
    );
    assert_eq!(
        report.activation_digest,
        expected_claim_receipt.activation_digest.as_str()
    );
    assert_eq!(
        report.exact_plan_digest,
        expected_claim_receipt.exact_plan_digest.as_str()
    );
    assert_eq!(
        report.activation_commit_sequence,
        expected_activation_sequence.get()
    );
    assert_eq!(
        report.claim_commit_sequence,
        expected_claim_receipt.claimed_commit_seq.get()
    );
    assert_eq!(
        report.claim_commit_digest,
        expected_claim_receipt.claim_commit_digest.as_str()
    );
    assert_eq!(report.authority_ceiling, AUTHORITY_CEILING);
    assert_eq!(
        report.execution_disposition,
        "validation_only_no_provider_io"
    );
    assert_eq!(admission.installation_id(), installation_a);
    assert_eq!(
        admission.run_registration_id(),
        expected_activation.run.run_id
    );
    assert_eq!(admission.authority_ceiling(), AUTHORITY_CEILING);
    assert_eq!(supervisor_a.spool().list_segments().unwrap(), spool_before);
    assert_eq!(supervisor_a.spool().status().unwrap(), status_before);
    assert_eq!(activation_receipt.installation_id.as_str(), installation_a);

    foreign_journal_refusal_keeps_claim_burned(&installation_a);
}
