//! End-to-end, no-I/O checks for the disabled C1 supervisor admission seam.

#![allow(clippy::struct_field_names, clippy::uninlined_format_args)]

mod support;

use joshi_domain::{StableString, UtcTimestamp};
use joshi_sources::{
    BuiltInExecutionDisposition, CanaryProfilePort, ProviderOperation, ProviderOperationPlan,
    ProviderRunPlanTemplate, ProviderScopePort, RegisteredRunPort, RuntimeAttemptCostPort,
    RuntimeBudgetPort, parse_provider_run_plan_exact, validate_provider_run_plan,
};
use joshi_store::{
    SqliteStore, StoreConfig, StoreMode, Wave5C1ActivationReceipt, Wave5CommitContext,
    Wave5RunRegistrationByteBundle,
};
use joshi_supervisor::{
    AUTHORITY_CEILING, DisabledC1AdmissionError, DisabledC1AdmissionReport, Supervisor,
};
use joshi_wave5_c1_activation::{
    ExactC1BudgetProjectionV1, ExactPlanClosureV1, ExactSourceMethodProjectionV1,
    FinalityCommitmentV1, PublicWalletPageV1, Wave5C1ActivationV1, parse_c1_activation_exact,
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

/// One durably committed and immediately burned C1 activation, plus the inputs a test needs to
/// re-derive expectations independently of whatever the admission seam reports.
struct BurnedActivation {
    claim: joshi_store::ClaimedWave5C1Activation,
    /// Receipt from the activation commit, read back out of the catalog.
    activation_receipt: Wave5C1ActivationReceipt,
    /// The exact final-plan bytes, so a test can reparse them itself rather than trusting the
    /// admission report's account of them.
    exact_plan_bytes: Vec<u8>,
}

fn registered_claim(
    store: &mut SqliteStore,
    installation_id: &str,
    activation_id: &str,
    context_suffix: &str,
) -> BurnedActivation {
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
    BurnedActivation {
        claim,
        activation_receipt: receipt,
        exact_plan_bytes: plan_bytes,
    }
}

/// The disposition string the admission report must carry.
///
/// Read this for what it is. Both arms are literals restated here; what the match buys is only
/// that the *choice* between them is made by reparsing the exact plan bytes rather than by copying
/// the report. The second arm is dead: `joshi_sources` derives a plan's built-in disposition from
/// its profile alone and yields `SyntheticEnabled` only for `CanaryProfilePort::C0`, while
/// `parse_c1_activation_exact` refuses any activation whose plan is not `CanaryProfilePort::C1`.
///
/// So against any claim the store can produce, this compares the report against the fixed string
/// `validation_only_no_provider_io`. That catches a stale, misspelled, or wrong-variant literal in
/// the seam, and nothing more. It is not evidence that the seam would refuse a synthetic plan,
/// because no such plan can reach it.
fn expected_execution_disposition(exact_plan_bytes: &[u8]) -> &'static str {
    let plan = parse_provider_run_plan_exact(exact_plan_bytes).expect("reparse exact plan bytes");
    match plan.built_in_execution() {
        BuiltInExecutionDisposition::ValidationOnlyNoProviderIo => "validation_only_no_provider_io",
        BuiltInExecutionDisposition::SyntheticEnabled => "synthetic_enabled",
    }
}

/// Admitting a claim must reproduce the identities and digests carried by the durable documents.
///
/// Read these assertions for what they are. Most compare a report field against the durable
/// document or the claim row that same admission read, so what they can catch is a report wired to
/// the wrong field, a dropped value, or a stale literal — not a seam that agrees with itself for
/// the wrong reason. One does more: the authority comparison crosses crates, checking this crate's
/// `AUTHORITY_CEILING` against the authority string `joshi-wave5-c1-activation` independently
/// requires of every activation document, so a divergence between the two constants fails here.
/// The installation block below states explicitly which of its assertions cannot fail at all.
#[test]
fn disabled_c1_admission_reproduces_the_durable_activation_identities() {
    let supervisor_root = TempDir::new().expect("supervisor root");
    let supervisor =
        Supervisor::open(support::config(supervisor_root.path())).expect("open supervisor journal");
    let journal_installation = supervisor.installation_id().to_owned();

    let store_root = TempDir::new().expect("store root");
    let mut store = open_store(store_root.path());
    let burned = registered_claim(
        &mut store,
        &journal_installation,
        "activation:c1-admission-accepted",
        "accepted",
    );
    let expected_activation = burned.claim.activation().clone();
    let expected_claim_receipt = burned.claim.claim_receipt().clone();
    let expected_activation_sequence = burned.claim.activation_commit_seq();
    let expected_disposition = expected_execution_disposition(&burned.exact_plan_bytes);
    let spool_before = supervisor
        .spool()
        .list_segments()
        .expect("list spool before");
    let status_before = supervisor.spool().status().expect("spool status before");

    let admission = supervisor
        .admit_claimed_wave5_c1_disabled(burned.claim)
        .expect("matching actual journal identity is admitted without runtime activation");
    let report = admission.report();

    assert_eq!(report.activation_id, expected_activation.activation_id);
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

    // These installation values are not independent, and none of the assertions below can fail on
    // a successful admission. All three are forced equal before the first one runs: the seam
    // returns `ForeignInstallation` unless the activation document names this journal, the store
    // refuses to hand back a claim receipt whose installation differs from the stored activation's,
    // and the fixture built the activation with this journal's identity in the first place. What
    // they check is that the report and both accessors carry that one agreed identity rather than
    // an empty or unrelated string. The property that the seam *checks* installation identity at
    // all is carried by `foreign_journal_refusal_keeps_the_store_claim_burned`, which is the only
    // test that can distinguish the check from its absence.
    assert_eq!(
        report.installation_id, expected_activation.installation_id,
        "the report must carry the one agreed installation, not an empty or unrelated string"
    );
    assert_eq!(
        report.installation_id,
        expected_claim_receipt.installation_id.as_str(),
        "the durable claim row was written with that same agreed installation"
    );
    assert_eq!(
        admission.installation_id(),
        expected_activation.installation_id
    );
    assert_eq!(
        burned.activation_receipt.installation_id.as_str(),
        expected_activation.installation_id
    );
    assert_eq!(
        admission.run_registration_id(),
        expected_activation.run.run_id
    );

    // Authority is compared against the authority string carried by the durable, reparsed C1
    // activation document rather than against the crate constant the report copied.
    assert_eq!(
        report.authority_ceiling, expected_activation.authority,
        "the admitted ceiling must match the authority the activation document declares"
    );
    assert_eq!(
        admission.authority_ceiling(),
        expected_activation.authority.as_str()
    );
    assert_eq!(
        AUTHORITY_CEILING, expected_activation.authority,
        "the supervisor ceiling and the activation document must agree on the same authority"
    );

    // Disposition is re-derived from the exact plan bytes, so a hardcoded or stale literal in the
    // report fails here instead of matching itself.
    assert_eq!(report.execution_disposition, expected_disposition);
    assert_eq!(admission.execution_disposition(), expected_disposition);

    assert_eq!(supervisor.spool().list_segments().unwrap(), spool_before);
    assert_eq!(supervisor.spool().status().unwrap(), status_before);
}

/// A refusal by a foreign journal must not refund the burn the store already committed.
///
/// This is a separate test on purpose. It used to be a helper called from the tail of the
/// admission test, so any earlier assertion failing meant this property was never exercised at
/// all — the run reported one failure and silently skipped the durability check.
#[test]
fn foreign_journal_refusal_keeps_the_store_claim_burned() {
    let owner_root = TempDir::new().expect("owning supervisor root");
    let owner = Supervisor::open(support::config(owner_root.path()))
        .expect("open the supervisor the claim is bound to");
    let owner_installation = owner.installation_id().to_owned();

    let store_root = TempDir::new().expect("store root");
    let mut store = open_store(store_root.path());
    let burned = registered_claim(
        &mut store,
        &owner_installation,
        "activation:c1-admission-foreign",
        "foreign",
    );
    let activation_id = stable("activation:c1-admission-foreign");
    let expected_receipt = burned.claim.claim_receipt().clone();

    let foreign_root = TempDir::new().expect("foreign supervisor root");
    let foreign = Supervisor::open(support::config(foreign_root.path()))
        .expect("open an independent foreign supervisor journal");
    assert_ne!(foreign.installation_id(), owner_installation);
    let spool_before = foreign.spool().list_segments().expect("list foreign spool");

    assert!(matches!(
        foreign.admit_claimed_wave5_c1_disabled(burned.claim),
        Err(DisabledC1AdmissionError::ForeignInstallation)
    ));
    assert_eq!(foreign.spool().list_segments().unwrap(), spool_before);
    drop(store);

    let mut reopened = SqliteStore::open(config(store_root.path()), StoreMode::SingleWriter)
        .expect("reopen the claimed store");
    let durable_receipt = reopened
        .load_wave5_c1_activation_claim_receipt_v1(&activation_id)
        .expect("read claim receipt")
        .expect("claim receipt remains durable after the foreign refusal");
    assert_eq!(durable_receipt, expected_receipt);
    assert!(
        reopened
            .claim_wave5_c1_activation_v1(
                &activation_id,
                &stable(&owner_installation),
                &context(&reopened, "claim:foreign-reopen"),
            )
            .is_err(),
        "the capability a foreign journal rejected stayed burned"
    );
}

/// The premise that makes five of the six seam refusals dead branches, stated as a test.
///
/// Reachability was settled by reading the only path that can produce the seam's input.
/// `ClaimedWave5C1Activation` has exactly one constructor, `claim_wave5_c1_activation_v1`, which
/// builds it from a durable row that `parse_c1_activation_exact` already accepted over exactly the
/// two byte strings the claim then carries, and the store cross-checks the claim row against that
/// same activation closure on readback. So `ActivationBytes`, `PlanClosure`, `ClaimReceipt`,
/// `CommitOrdering`, and `ExecutionDisposition` cannot fire, and no test can reach them: a test
/// claiming to would be testing something other than the public path.
///
/// This test does the honest alternative. It recomputes each of those five refusal predicates here,
/// from the claim's own public accessors, and asserts each is false on a real burned claim. That is
/// a tripwire on the premise rather than a test of the branches: if the store ever stops deriving a
/// claim's projections from its retained bytes, or stops cross-checking the claim row against the
/// activation closure, this fails and the five branches have to be reclassified as live and given
/// real refusal tests. It is not evidence that the seam would refuse a mismatched claim, because
/// this crate cannot build one.
#[test]
fn store_produced_claims_cannot_trip_the_five_defence_in_depth_refusals() {
    let supervisor_root = TempDir::new().expect("supervisor root");
    let supervisor =
        Supervisor::open(support::config(supervisor_root.path())).expect("open supervisor journal");
    let journal_installation = supervisor.installation_id().to_owned();

    let store_root = TempDir::new().expect("store root");
    let mut store = open_store(store_root.path());
    let burned = registered_claim(
        &mut store,
        &journal_installation,
        "activation:c1-admission-dead-branches",
        "dead-branches",
    );

    let claim = &burned.claim;
    let activation = claim.activation();

    // `ActivationBytes`: the claim's activation projection is the parse of its own retained bytes.
    let reparsed =
        parse_c1_activation_exact(claim.exact_activation_bytes(), claim.exact_plan_bytes())
            .expect("a burned claim retains bytes the store already parsed once");
    assert_eq!(
        reparsed.activation(),
        activation,
        "a claim whose projection differed from its bytes would make ActivationBytes live"
    );

    // `PlanClosure`: every disjunct the seam rechecks, recomputed from the retained plan bytes.
    let plan = parse_provider_run_plan_exact(claim.exact_plan_bytes())
        .expect("a burned claim retains plan bytes the store already parsed once");
    assert_eq!(activation.run, plan.plan().run);
    assert_eq!(activation.exact_plan.plan_id, plan.plan().plan_id);
    assert_eq!(activation.exact_plan.port_version, plan.plan().port_version);
    assert_eq!(
        activation.exact_plan.plan_template_digest,
        plan.plan_template_digest()
    );
    assert_eq!(activation.exact_plan.final_plan_digest, plan.plan_digest());
    assert_eq!(
        activation.exact_plan.raw_exact_plan_sha256,
        digest(claim.exact_plan_bytes())
    );

    // `ClaimReceipt`: every disjunct the seam rechecks, against the durable claim row.
    let receipt = claim.claim_receipt();
    assert_eq!(receipt.activation_id.as_str(), activation.activation_id);
    assert_eq!(receipt.installation_id.as_str(), journal_installation);
    assert_eq!(receipt.run_registration_id.as_str(), activation.run.run_id);
    assert_eq!(
        receipt.run_registration_digest.as_str(),
        activation.run.registration_digest
    );
    assert_eq!(
        receipt.activation_digest.as_str(),
        reparsed.raw_activation_sha256()
    );
    assert_eq!(
        receipt.exact_plan_digest.as_str(),
        activation.exact_plan.raw_exact_plan_sha256
    );

    // `CommitOrdering`: the store already refuses a receipt that does not strictly follow.
    assert!(
        claim.activation_commit_seq() < receipt.claimed_commit_seq,
        "a claim commit that did not follow its activation would make CommitOrdering live"
    );

    // `ExecutionDisposition`: a C1 profile forces the validation-only disposition.
    assert_eq!(
        plan.built_in_execution(),
        BuiltInExecutionDisposition::ValidationOnlyNoProviderIo
    );

    // With all five predicates false, the only remaining refusal is installation identity, and
    // this claim names this journal, so admission succeeds.
    let admission = supervisor
        .admit_claimed_wave5_c1_disabled(burned.claim)
        .expect("a self-consistent claim on its own journal is admitted");
    assert_eq!(admission.installation_id(), journal_installation);
}

/// `DisabledC1AdmissionReport::claim_commit_digest` binds nothing its holder did not already have.
///
/// The report documents this digest as recomputable offline from the exact activation bytes alone.
/// That claim is checked here rather than asserted: the store digests a claim commit over the claim
/// operation domain together with the activation digest and the exact-plan digest, the first is the
/// SHA-256 of the activation bytes and the second is a field inside them, so the value below is
/// derived from those bytes and two constants and nothing else — no catalog, installation, wall
/// time, or prior commit.
///
/// This deliberately restates the store's private claim-operation domain string. If the store
/// changes how a claim commit is digested, this fails, and the correct response is to re-derive
/// what the digest now binds and rewrite the report's documentation — not to quietly update the
/// constant here.
#[test]
fn report_claim_commit_digest_is_recomputable_from_the_activation_bytes_alone() {
    const CLAIM_OPERATION_DOMAIN: &str = "joshi.store.wave5_c1_activation_claim.v1";

    let supervisor_root = TempDir::new().expect("supervisor root");
    let supervisor =
        Supervisor::open(support::config(supervisor_root.path())).expect("open supervisor journal");
    let journal_installation = supervisor.installation_id().to_owned();

    let store_root = TempDir::new().expect("store root");
    let mut store = open_store(store_root.path());
    let burned = registered_claim(
        &mut store,
        &journal_installation,
        "activation:c1-admission-offline-digest",
        "offline-digest",
    );
    let public_activation_bytes = burned.claim.exact_activation_bytes().to_vec();
    let admission = supervisor
        .admit_claimed_wave5_c1_disabled(burned.claim)
        .expect("matching journal identity is admitted");

    // Everything from here uses only `public_activation_bytes` and two constants.
    let activation: Wave5C1ActivationV1 = serde_json::from_slice(&public_activation_bytes)
        .expect("the exact activation document is public JSON");
    let recomputed = digest(
        &serde_json::to_vec(&(
            CLAIM_OPERATION_DOMAIN,
            digest(&public_activation_bytes),
            activation.exact_plan.raw_exact_plan_sha256,
        ))
        .expect("encode the claim operation tuple"),
    );
    assert_eq!(
        admission.report().claim_commit_digest,
        recomputed,
        "the claim commit digest is reproducible offline, so it attests to nothing a holder of the \
         public activation bytes lacks"
    );
}

/// `DisabledC1AdmissionReport` is a public record any crate can mint, not an attestation.
///
/// The report's documentation says holding one is no evidence that an admission happened. This
/// demonstrates that from outside the crate: every field is `pub`, so a value with an arbitrary
/// authority ceiling and disposition constructs and clones here, having passed through no
/// supervisor and consumed no claim.
///
/// This records a limitation, not a property to preserve. If it stops compiling because the fields
/// became private or the type lost `Clone`, the report has become harder to forge and its
/// documentation should be strengthened to match.
#[test]
fn admission_report_can_be_minted_outside_the_supervisor() {
    let forged = DisabledC1AdmissionReport {
        activation_id: "activation:never-committed".to_owned(),
        installation_id: "inst-00000000000000000000000000000000".to_owned(),
        run_registration_id: "run:never-registered".to_owned(),
        run_registration_digest: digest(b"not a run"),
        plan_id: "plan:never-validated".to_owned(),
        plan_template_digest: digest(b"not a template"),
        final_plan_digest: digest(b"not a plan"),
        activation_digest: digest(b"not an activation"),
        exact_plan_digest: digest(b"not exact plan bytes"),
        activation_commit_sequence: u64::MAX,
        claim_commit_sequence: 0,
        claim_commit_digest: digest(b"not a commit"),
        authority_ceiling: "unbounded_execution",
        execution_disposition: "synthetic_enabled",
    };
    let copy = forged.clone();
    assert_eq!(copy, forged);
    assert_ne!(copy.authority_ceiling, AUTHORITY_CEILING);
    assert!(
        copy.claim_commit_sequence < copy.activation_commit_sequence,
        "a minted report can even carry the commit ordering the seam refuses"
    );
}

/// Compile-time guard: [`joshi_supervisor::DisabledC1RuntimeAdmission`] must not gain `Clone`,
/// `Debug`, `Serialize`, `Deserialize`, or `Default`.
///
/// The type's own documentation rests on those derives being absent — that is what keeps an
/// admission an in-process proof rather than something a holder can duplicate, print into a log,
/// or reconstruct from bytes. Absences have no ordinary test, so this states them as a build
/// requirement instead.
///
/// The guard is written as an ambiguity rather than as the coherence conflict used for
/// `ClaimedWave5C1Activation` inside `joshi-store`: from this integration-test crate the admission
/// type is *foreign*, and coherence refuses to reason negatively about a trait implementation
/// another crate could still add. Two blanket implementations differing only in the guarded bound
/// leave `some_item` resolvable exactly while the bound does not hold; once it holds both apply
/// and the reference below fails to compile as an ambiguous method resolution.
///
/// This is a guard, not a proof of unforgeability: it says nothing about an inherent `fn clone`
/// that is not the `Clone` trait, nor about an accessor a later lane might add to hand out the
/// admission's contents.
mod admission_stays_unduplicable {
    use joshi_supervisor::DisabledC1RuntimeAdmission;
    use serde::{Serialize, de::DeserializeOwned};

    pub const NOT_CLONE: fn() = || {
        trait AmbiguousIfClone<A> {
            fn some_item() {}
        }
        impl<T> AmbiguousIfClone<()> for T {}
        impl<T: Clone> AmbiguousIfClone<u8> for T {}
        let _ = <DisabledC1RuntimeAdmission as AmbiguousIfClone<_>>::some_item;
    };

    pub const NOT_DEBUG: fn() = || {
        trait AmbiguousIfDebug<A> {
            fn some_item() {}
        }
        impl<T> AmbiguousIfDebug<()> for T {}
        impl<T: std::fmt::Debug> AmbiguousIfDebug<u8> for T {}
        let _ = <DisabledC1RuntimeAdmission as AmbiguousIfDebug<_>>::some_item;
    };

    pub const NOT_SERIALIZE: fn() = || {
        trait AmbiguousIfSerialize<A> {
            fn some_item() {}
        }
        impl<T> AmbiguousIfSerialize<()> for T {}
        impl<T: Serialize> AmbiguousIfSerialize<u8> for T {}
        let _ = <DisabledC1RuntimeAdmission as AmbiguousIfSerialize<_>>::some_item;
    };

    pub const NOT_DESERIALIZE: fn() = || {
        trait AmbiguousIfDeserialize<A> {
            fn some_item() {}
        }
        impl<T> AmbiguousIfDeserialize<()> for T {}
        impl<T: DeserializeOwned> AmbiguousIfDeserialize<u8> for T {}
        let _ = <DisabledC1RuntimeAdmission as AmbiguousIfDeserialize<_>>::some_item;
    };

    pub const NOT_DEFAULT: fn() = || {
        trait AmbiguousIfDefault<A> {
            fn some_item() {}
        }
        impl<T> AmbiguousIfDefault<()> for T {}
        impl<T: Default> AmbiguousIfDefault<u8> for T {}
        let _ = <DisabledC1RuntimeAdmission as AmbiguousIfDefault<_>>::some_item;
    };
}

/// Force every guard above into this test binary's compilation.
#[test]
fn disabled_admission_has_no_duplicating_derives() {
    for guard in [
        admission_stays_unduplicable::NOT_CLONE,
        admission_stays_unduplicable::NOT_DEBUG,
        admission_stays_unduplicable::NOT_SERIALIZE,
        admission_stays_unduplicable::NOT_DESERIALIZE,
        admission_stays_unduplicable::NOT_DEFAULT,
    ] {
        guard();
    }
}
