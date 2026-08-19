//! Adversarial sole-store tests for the inert Wave 5 C1 activation/claim seam.

#![allow(clippy::struct_field_names, clippy::uninlined_format_args)]

use joshi_domain::{StableString, UtcTimestamp};
use joshi_store::{
    IdempotencyStatus, SqliteStore, StoreConfig, StoreMode, Wave5CommitContext,
    Wave5RunRegistrationByteBundle,
};
use serde::Serialize;
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeMap, path::Path, str::FromStr, time::Duration};
use tempfile::TempDir;

const AUTHORITY: &str = "read_only_no_execution";
const INSTALLATION: &str = "inst-0123456789abcdef0123456789abcdef";
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

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Budget {
    requests: u64,
    pages: u64,
    ingress_bytes: u64,
    durable_bytes: u64,
    provider_credits: u64,
    wall_millis: u64,
    provider_currency_minor: BTreeMap<String, u128>,
    chain_native_atoms: BTreeMap<String, u128>,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AttemptCost {
    worst_case: Budget,
    max_overshoot: Budget,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Scope {
    kind: &'static str,
    address: &'static str,
    max_rows: u16,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Operation {
    source_key: &'static str,
    method_key: &'static str,
    source_contract_fingerprint: &'static str,
    method_schema_fingerprint: &'static str,
    operation: &'static str,
    generation: u64,
    max_attempts: u64,
    scope: Scope,
    attempt_cost: AttemptCost,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Template {
    port_version: &'static str,
    plan_id: &'static str,
    profile: &'static str,
    hard_cap: Budget,
    max_elapsed_ms: u64,
    max_ingress_bytes_per_second: Option<u64>,
    max_in_flight_attempts: u16,
    operations: Vec<Operation>,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Run {
    run_id: &'static str,
    registration_digest: String,
}
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Plan {
    port_version: &'static str,
    plan_id: &'static str,
    run: Run,
    profile: &'static str,
    hard_cap: Budget,
    max_elapsed_ms: u64,
    max_ingress_bytes_per_second: Option<u64>,
    max_in_flight_attempts: u16,
    operations: Vec<Operation>,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PlanClosure {
    plan_id: &'static str,
    port_version: &'static str,
    raw_exact_plan_sha256: String,
    raw_exact_plan_byte_length: String,
    plan_template_digest: String,
    final_plan_digest: String,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BudgetProjection {
    hard_cap: Budget,
    attempt_cost: AttemptCost,
    max_elapsed_ms: u64,
    max_ingress_bytes_per_second: Option<u64>,
    max_in_flight_attempts: u16,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Projection {
    source_key: &'static str,
    method_key: &'static str,
    source_contract_fingerprint: &'static str,
    method_schema_fingerprint: &'static str,
    coverage_family: &'static str,
    protection_domain: &'static str,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Wallet {
    address: &'static str,
    max_rows: u16,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Activation {
    contract: &'static str,
    schema_version: u16,
    activation_id: String,
    installation_id: String,
    run: Run,
    exact_plan: PlanClosure,
    budget: BudgetProjection,
    operations: Vec<Projection>,
    wallet: Wallet,
    commitment: &'static str,
    authority: &'static str,
}

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}
fn timestamp(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).unwrap()
}
fn digest(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}
fn domain_digest(domain: &str, value: &impl Serialize) -> String {
    let bytes = serde_json::to_vec(value).unwrap();
    let mut hash = Sha256::new();
    hash.update(domain.as_bytes());
    hash.update([0]);
    hash.update(u64::try_from(bytes.len()).unwrap().to_be_bytes());
    hash.update(bytes);
    format!("sha256:{:x}", hash.finalize())
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
        catalog_id: stable("catalog:c1"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}
fn open() -> (TempDir, SqliteStore) {
    let root = TempDir::new().unwrap();
    let mut store = SqliteStore::open(config(root.path()), StoreMode::SingleWriter).unwrap();
    store
        .migrate(timestamp("2026-08-19T00:00:00.000000Z"))
        .unwrap();
    (root, store)
}
fn context(store: &SqliteStore, id: &str) -> Wave5CommitContext {
    store
        .begin_wave5_commit(stable(id), stable("build:c1-test"))
        .unwrap()
}
fn zero() -> Budget {
    Budget {
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
fn cost() -> AttemptCost {
    AttemptCost {
        worst_case: Budget {
            requests: 1,
            pages: 1,
            ingress_bytes: 1024,
            durable_bytes: 1024,
            provider_credits: 0,
            wall_millis: 1000,
            ..zero()
        },
        max_overshoot: zero(),
    }
}
fn template() -> Template {
    let attempt = cost();
    Template {
        port_version: "joshi.provider_run_plan_port.v2",
        plan_id: "c1-plan-test",
        profile: "c1",
        hard_cap: attempt.worst_case.clone(),
        max_elapsed_ms: 1000,
        max_ingress_bytes_per_second: None,
        max_in_flight_attempts: 1,
        operations: vec![Operation {
            source_key: "solana.public.mainnet",
            method_key: "get_signatures_for_address",
            source_contract_fingerprint: SOURCE_FP,
            method_schema_fingerprint: METHOD_FP,
            operation: "solana_signatures_for_address",
            generation: 1,
            max_attempts: 1,
            scope: Scope {
                kind: "public_wallet_page",
                address: WALLET,
                max_rows: 10,
            },
            attempt_cost: attempt,
        }],
    }
}
fn register_run(store: &mut SqliteStore, template_digest: &str) -> String {
    register_run_with_limits(store, template_digest, 1, 1_024, 1_024, 1_000)
}

fn register_run_with_limits(
    store: &mut SqliteStore,
    template_digest: &str,
    maximum_pages: u64,
    maximum_ingress_bytes: u64,
    maximum_durable_bytes: u64,
    maximum_elapsed_ms: u64,
) -> String {
    let tree = format!(r#"{{"contract":"joshi.wave5.source_tree_manifest","schemaVersion":1,"repositoryId":"joshi","head":{{"kind":"commit","object_id":"{}"}},"dirty":false,"workingTreeDigest":"{}","diffDigest":null,"authority":"{}"}}"#, "1".repeat(40), digest(b"tree"), AUTHORITY).into_bytes();
    let build = format!(r#"{{"contract":"joshi.wave5.build_manifest","schemaVersion":1,"buildId":"build:c1-test","sourceTreeDigest":"{}","rustcVersion":"rustc-test","targetTriple":"test","profile":"local_debug","authority":"{}"}}"#, digest(&tree), AUTHORITY).into_bytes();
    let cfg = format!(r#"{{"contract":"joshi.collector.runtime_config.v1","schemaVersion":1,"planId":"c1-plan-test","planTemplateDigest":"{}","statusEndpoint":{{"address":"127.0.0.1","port":8123}},"providerExecution":"offline_fixture_only","authority":"{}"}}"#, template_digest, AUTHORITY).into_bytes();
    let budget = format!(r#"{{"contract":"joshi.collector.execution_accounting.v1","schemaVersion":1,"limits":{{"maximumRequests":1,"maximumPages":{maximum_pages},"maximumIngressBytes":{maximum_ingress_bytes},"maximumDurableBytes":{maximum_durable_bytes},"maximumProviderCredits":0,"maximumIngressBytesPerSecond":1024,"maximumElapsedMs":{maximum_elapsed_ms},"maximumInFlightAttempts":1,"maximumInFlightElapsedOvershootMs":1}},"authority":"{}"}}"#, AUTHORITY).into_bytes();
    let privacy = format!(r#"{{"contract":"joshi.wave5.privacy_policy","schemaVersion":1,"policyId":"privacy:c1","permittedProtectionClasses":["public_integrity"],"credentialHandling":"purpose_scoped_handles_only","walletMaterial":"forbidden","exportPrivateMaterial":false,"authority":"{}"}}"#, AUTHORITY).into_bytes();
    let surface = include_str!("../../../fixtures/surface/daily_use_surface_profile_v1.json")
        .trim_end()
        .as_bytes()
        .to_vec();
    let registration = Registration {
        contract: "joshi.wave5.run_registration",
        schema_version: 1,
        run_id: "run:c1-test",
        build: document("build:c1", &build),
        source_tree: document("tree:c1", &tree),
        configuration: document("config:c1", &cfg),
        budget: document("budget:c1", &budget),
        privacy: document("privacy:c1", &privacy),
        daily_use_surface_profile: document("surface:c1", &surface),
        authority: AUTHORITY,
    };
    let bytes = serde_json::to_vec(&registration).unwrap();
    store
        .commit_wave5_run_registration_v1(
            &Wave5RunRegistrationByteBundle {
                registration: &bytes,
                build: &build,
                source_tree: &tree,
                configuration: &cfg,
                budget: &budget,
                privacy: &privacy,
                daily_use_surface_profile: &surface,
            },
            &context(store, "run:c1"),
        )
        .unwrap()
        .exact_document_digest
        .to_string()
}
fn activation_bytes(run_digest: String, activation_id: &str) -> (Vec<u8>, Vec<u8>) {
    let template = template();
    let template_digest = domain_digest("joshi.provider_run_plan_template.v2", &template);
    let plan = Plan {
        port_version: template.port_version,
        plan_id: template.plan_id,
        run: Run {
            run_id: "run:c1-test",
            registration_digest: run_digest,
        },
        profile: template.profile,
        hard_cap: template.hard_cap.clone(),
        max_elapsed_ms: template.max_elapsed_ms,
        max_ingress_bytes_per_second: None,
        max_in_flight_attempts: 1,
        operations: template.operations.clone(),
    };
    let plan_bytes = serde_json::to_vec(&plan).unwrap();
    let plan_digest = domain_digest("joshi.provider_run_plan.final.v2", &plan);
    let activation = Activation {
        contract: "joshi.wave5.c1_activation.v1",
        schema_version: 1,
        activation_id: activation_id.into(),
        installation_id: INSTALLATION.into(),
        run: plan.run.clone(),
        exact_plan: PlanClosure {
            plan_id: "c1-plan-test",
            port_version: "joshi.provider_run_plan_port.v2",
            raw_exact_plan_sha256: digest(&plan_bytes),
            raw_exact_plan_byte_length: plan_bytes.len().to_string(),
            plan_template_digest: template_digest,
            final_plan_digest: plan_digest,
        },
        budget: BudgetProjection {
            hard_cap: template.hard_cap.clone(),
            attempt_cost: template.operations[0].attempt_cost.clone(),
            max_elapsed_ms: 1000,
            max_ingress_bytes_per_second: None,
            max_in_flight_attempts: 1,
        },
        operations: vec![Projection {
            source_key: "solana.public.mainnet",
            method_key: "get_signatures_for_address",
            source_contract_fingerprint: SOURCE_FP,
            method_schema_fingerprint: METHOD_FP,
            coverage_family: "wallet_signature_page",
            protection_domain: "public_chain_evidence",
        }],
        wallet: Wallet {
            address: WALLET,
            max_rows: 10,
        },
        commitment: "finalized",
        authority: AUTHORITY,
    };
    (serde_json::to_vec(&activation).unwrap(), plan_bytes)
}

#[test]
fn c1_activation_is_exact_durable_and_claim_burns_once() {
    let (root, mut store) = open();
    let template_digest = domain_digest("joshi.provider_run_plan_template.v2", &template());
    let run_digest = register_run(&mut store, &template_digest);
    let (activation, plan) = activation_bytes(run_digest, "activation:c1-test");
    let receipt = store
        .commit_wave5_c1_activation_v1(&activation, &plan, &context(&store, "activation:c1"))
        .unwrap();
    assert_eq!(receipt.status, IdempotencyStatus::Accepted);
    assert_eq!(
        store
            .commit_wave5_c1_activation_v1(
                &activation,
                &plan,
                &context(&store, "activation:c1-retry")
            )
            .unwrap()
            .status,
        IdempotencyStatus::Idempotent
    );
    let prior_run_digest = store
        .load_wave5_run_registration_v1(&stable("run:c1-test"))
        .unwrap()
        .unwrap()
        .exact_digest
        .to_string();
    let (alternate_id, same_plan) = activation_bytes(prior_run_digest, "activation:c1-alternate");
    assert_eq!(same_plan, plan);
    assert!(
        store
            .commit_wave5_c1_activation_v1(
                &alternate_id,
                &same_plan,
                &context(&store, "activation:alternate-id"),
            )
            .is_err()
    );
    let id = stable("activation:c1-test");
    let installation = stable(INSTALLATION);
    let changed = activation_bytes(
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".into(),
        "activation:c1-test",
    )
    .0;
    assert!(
        store
            .commit_wave5_c1_activation_v1(&changed, &plan, &context(&store, "activation:changed"))
            .is_err()
    );
    assert!(
        store
            .claim_wave5_c1_activation_v1(
                &id,
                &stable("inst-ffffffffffffffffffffffffffffffff"),
                &context(&store, "claim:foreign")
            )
            .is_err()
    );
    let claim_context = context(&store, "claim:c1");
    let capability = store
        .claim_wave5_c1_activation_v1(&id, &installation, &claim_context)
        .unwrap();
    assert_eq!(capability.activation().activation_id, id.as_str());
    assert!(
        store
            .claim_wave5_c1_activation_v1(&id, &installation, &claim_context)
            .is_err()
    );
    assert!(
        store
            .claim_wave5_c1_activation_v1(&id, &installation, &context(&store, "claim:again"))
            .is_err()
    );
    drop(store);
    let mut reopened = SqliteStore::open(config(root.path()), StoreMode::ReadOnly).unwrap();
    assert_eq!(
        reopened
            .load_wave5_c1_activation_v1(&id)
            .unwrap()
            .unwrap()
            .exact_plan_bytes,
        plan
    );
    let reopened_claim = reopened
        .load_wave5_c1_activation_claim_receipt_v1(&id)
        .unwrap()
        .unwrap();
    assert_eq!(reopened_claim.activation_id, id);
    assert_eq!(reopened_claim.run_registration_id.as_str(), "run:c1-test");
    assert_eq!(
        reopened_claim.run_registration_digest,
        receipt.run_registration_digest
    );
    assert!(
        reopened
            .claim_wave5_c1_activation_v1(&id, &installation, &claim_context)
            .is_err()
    );
}

#[test]
fn c1_activation_refuses_mismatched_run_template_and_each_lowered_comparable_cap() {
    let template_digest = domain_digest("joshi.provider_run_plan_template.v2", &template());
    let adversaries = [
        ("template", 1, 1_024, 1_024, 1_000),
        ("pages", 0, 1_024, 1_024, 1_000),
        ("ingress", 1, 1, 1_024, 1_000),
        ("durable", 1, 1_024, 1, 1_000),
        ("elapsed", 1, 1_024, 1_024, 1),
    ];
    for (name, pages, ingress, durable, elapsed) in adversaries {
        let (_root, mut store) = open();
        let registered_template = if name == "template" {
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        } else {
            &template_digest
        };
        let run_digest = register_run_with_limits(
            &mut store,
            registered_template,
            pages,
            ingress,
            durable,
            elapsed,
        );
        let (activation, plan) = activation_bytes(run_digest, &format!("activation:c1-{name}"));
        assert!(
            store
                .commit_wave5_c1_activation_v1(
                    &activation,
                    &plan,
                    &context(&store, &format!("activation:{name}")),
                )
                .is_err()
        );
    }
}

#[test]
fn c1_activation_refuses_noncanonical_activation_and_plan_bytes_before_storage() {
    let (_root, mut store) = open();
    let template_digest = domain_digest("joshi.provider_run_plan_template.v2", &template());
    let run_digest = register_run(&mut store, &template_digest);
    let (activation, plan) = activation_bytes(run_digest, "activation:c1-noncanonical");
    let mut noncanonical_activation = activation.clone();
    noncanonical_activation.push(b'\n');
    assert!(
        store
            .commit_wave5_c1_activation_v1(
                &noncanonical_activation,
                &plan,
                &context(&store, "activation:noncanonical-body"),
            )
            .is_err()
    );
    let mut noncanonical_plan = plan;
    noncanonical_plan.push(b'\n');
    assert!(
        store
            .commit_wave5_c1_activation_v1(
                &activation,
                &noncanonical_plan,
                &context(&store, "activation:noncanonical-plan"),
            )
            .is_err()
    );
}
