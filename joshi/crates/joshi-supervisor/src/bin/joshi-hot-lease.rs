//! One hot lease, end to end, against the real provider.
//!
//! The run has four phases and each one hands the next only things it can prove:
//!
//! 1. **Census.** A bounded authenticated HTTP read of recent Pump-program activity is retained
//!    through the shared admission path, and the eligible mint universe is derived from the
//!    retained bytes alone.
//! 2. **Promotion.** This machine is measured, the readings become an exact resource snapshot, and
//!    `joshi-acquisition-policy` reduces one intent over that snapshot into one effective scope.
//!    The executable ceilings of the lease are that scope's own budget.
//! 3. **Lease.** Exactly one Helius WebSocket connection carries exactly one filtered
//!    subscription for the promoted mint, for the leased window, under a preregistered finite
//!    budget. Every frame is retained; every interval that was not observed becomes a typed gap.
//! 4. **Readback.** The catalog is reopened read-only and the lease is read back out of its rows.
//!
//! This binary constructs no transaction, signs nothing, submits nothing, and quotes no fill.

use std::{
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use joshi_acquisition_policy::{
    ActivationAuthority, AsOfCutoff, BudgetEnvelope, CensusDenominatorRef, CensusKind,
    CollectorGeneration, DESIRED_CONTRACT, EvidenceKind, EvidenceLink, Fidelity, HotScopeIntentV1,
    HotScopeRecordV1, INTENT_CONTRACT, IntentReason, IntentReasonKind, MediaFidelity,
    PolicyConfigV1, PolicyEvaluationV1, PolicyJournal, PolicyRecordHead, ScopeSubject,
    SourceAvailability, SourceFamily, SourcePolicyV1, SourceScopeRequest, SubjectKind, evaluate,
    promote_one,
};
use joshi_admission::{
    AdmissionPolicy, PublicStoreReceiptV1, SourceDraftBatch, SourceFrameInput, source_drafts,
    source_frames,
};
use joshi_domain::{
    CoverageId, OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp, ValueDigest,
    WireU64,
};
use joshi_evidence::{Boundary, CoverageScope, CoverageWindow, EvidenceDraft};
use joshi_sources::{
    ADAPTER_CONTRACT_VERSION, CredentialFile, EvidenceContext, HeliusConfig, HeliusHttpClient,
    HeliusSubscription, LogicalSourceLocator, ProviderEventTime, RawSourceFrame, SolanaReadMethod,
    SolanaReadRequest, UnixMillis,
};
use joshi_store::{SourceRegistration, SqliteStore, StoreConfig, StoreMode};
use joshi_supervisor::hot_lease::{
    IngressOccupancy, LeaseCommitContext, LeaseReadbackV1, LeaseRetentionReceiptV1,
    LeaseSettlementV1, MintUniverseV1, ResourceCeilings, ResourceMeasurementV1, RetainedPayload,
    census_coverage_id, commit_lease, commit_seq_of, derive_mint_universe, measure, read_lease,
    run_hot_lease, settle_lease,
};
use serde_json::{Value, json};
use sha2::{Digest as _, Sha256};
use time::OffsetDateTime;

/// Pump.fun bonding-curve program. Census reads name it; the lease never subscribes to it.
const PUMP_PROGRAM: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
const DEFAULT_HELIUS_KEY_PATH: &str = "~/.helius-key";
const CATALOG_ID: &str = "joshi-hot-lease";
const INLINE_BLOB_MAX_BYTES: u64 = 4 * 1024 * 1024;
const MAX_OBSERVATIONS_PER_BATCH: usize = 256;
const MAX_RAW_BYTES_PER_BATCH: u64 = 64 * 1024 * 1024;
const BUSY_TIMEOUT: Duration = Duration::from_secs(5);
const READBACK_PAYLOAD_LIMIT: usize = 4_096;
const SOURCE_KEY: &str = "helius-websocket-mainnet";
const OPERATION_KEY: &str = "mint-hot-logs-subscription";
const COMMITMENT: &str = "confirmed";
const RECEIPT_CONTRACT: &str = "joshi.supervisor.hot_lease_run_receipt/v1";

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let Some(command) = arguments.first().map(String::as_str) else {
        return Err(usage());
    };
    match command {
        "lease" => println!("{}", run_lease(&Options::parse(&arguments[1..])?)?),
        "readback" => {
            let options = Options::parse(&arguments[1..])?;
            let coverage = options
                .coverage_id
                .clone()
                .ok_or("readback requires --coverage-id")?;
            let readback = read_lease(
                &catalog_config(&options.root)?,
                &coverage,
                READBACK_PAYLOAD_LIMIT,
            )?;
            println!("{}", serde_json::to_string_pretty(&readback)?);
        }
        _ => return Err(usage()),
    }
    Ok(())
}

fn usage() -> Box<dyn Error> {
    "usage: joshi-hot-lease lease --root <dir> [--key <file>] [--window-seconds N] \
     [--max-ingress-bytes N] [--max-frames N] [--census-signatures N] \
     [--census-transactions N] [--subject <mint>]\n       \
     joshi-hot-lease readback --root <dir> --coverage-id <id>"
        .into()
}

#[derive(Debug)]
struct Options {
    root: PathBuf,
    key_file: PathBuf,
    window_seconds: u64,
    max_ingress_bytes: u64,
    max_frames: u64,
    census_signatures: u32,
    census_transactions: u32,
    subject: Option<String>,
    coverage_id: Option<String>,
}

impl Options {
    fn parse(arguments: &[String]) -> Result<Self, Box<dyn Error>> {
        let mut options = Self {
            root: PathBuf::new(),
            key_file: PathBuf::from(DEFAULT_HELIUS_KEY_PATH),
            window_seconds: 45,
            max_ingress_bytes: 8 * 1024 * 1024,
            max_frames: 20_000,
            census_signatures: 40,
            census_transactions: 6,
            subject: None,
            coverage_id: None,
        };
        let mut index = 0;
        while index < arguments.len() {
            let flag = arguments[index].as_str();
            let value = arguments
                .get(index + 1)
                .ok_or_else(|| format!("{flag} requires a value"))?;
            match flag {
                "--root" => options.root = PathBuf::from(value),
                "--key" => options.key_file = PathBuf::from(value),
                "--window-seconds" => options.window_seconds = value.parse()?,
                "--max-ingress-bytes" => options.max_ingress_bytes = value.parse()?,
                "--max-frames" => options.max_frames = value.parse()?,
                "--census-signatures" => options.census_signatures = value.parse()?,
                "--census-transactions" => options.census_transactions = value.parse()?,
                "--subject" => options.subject = Some(value.clone()),
                "--coverage-id" => options.coverage_id = Some(value.clone()),
                other => return Err(format!("unknown flag {other}").into()),
            }
            index += 2;
        }
        if options.root.as_os_str().is_empty() {
            return Err("--root is required".into());
        }
        if options.window_seconds == 0 || options.window_seconds > 600 {
            return Err("--window-seconds must be between 1 and 600".into());
        }
        Ok(options)
    }
}

#[allow(clippy::too_many_lines)] // The four phases are one narrative; splitting them hides order.
fn run_lease(options: &Options) -> Result<String, Box<dyn Error>> {
    let process_start = Instant::now();
    let namespace = format!("hot-lease-{}-{}", unix_millis(now())?, std::process::id());
    let clock_id = format!("joshi-hot-lease-{}", std::process::id());
    fs::create_dir_all(&options.root)?;

    let mut store = SqliteStore::open(catalog_config(&options.root)?, StoreMode::SingleWriter)?;
    store.migrate(utc_now()?)?;

    // Phase 1: census.
    let helius = HeliusConfig::mainnet(CredentialFile(options.key_file.clone()));
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    let client = HeliusHttpClient::at_startup(&helius, INLINE_BLOB_MAX_BYTES)?;
    let census_reads = runtime.block_on(census_reads(&client, options, process_start))?;
    drop(client);
    let census_frames_at = utc_now()?;
    let census_receipt = commit_census_frames(
        &mut store,
        census_reads,
        &namespace,
        &clock_id,
        census_frames_at,
        elapsed_nanos(process_start)?,
    )?;

    let payloads = retained_http_payloads(&store)?;
    let universe = derive_mint_universe(&payloads)?;
    let universe_digest = universe.digest()?;
    fs::write(
        options.root.join(format!("{namespace}-mint-universe.json")),
        universe.canonical_bytes()?,
    )?;
    let promoted = match &options.subject {
        Some(subject) => universe
            .mints
            .iter()
            .find(|sighting| &sighting.mint == subject)
            .ok_or("--subject is not a member of the derived census universe")?
            .clone(),
        None => universe
            .deterministic_promotion()
            .ok_or("the census derived no eligible mint; nothing can be promoted")?
            .clone(),
    };

    let census_coverage = census_coverage_id(&namespace)?;
    let census_coverage_at = utc_now()?;
    let coverage_receipt = commit_census_coverage(
        &mut store,
        &census_coverage,
        &clock_id,
        census_coverage_at,
        elapsed_nanos(process_start)?,
    )?;
    let census_commit = commit_seq_of(&coverage_receipt.commit_seq)?;

    // Phase 2: promotion against an exact measurement of this machine.
    let sampled_at = utc_now()?;
    let measurement = measure(
        &options.root,
        ResourceCeilings::local_workstation(u64::try_from(helius.ingress_capacity)?),
        // Nothing is queued: the lease has not opened its ingress yet, and saying otherwise
        // would invent pressure.
        IngressOccupancy {
            records_used: 0,
            buffer_bytes_used: 0,
        },
        sampled_at,
    )?;
    fs::write(
        options.root.join(format!("{namespace}-resources.json")),
        measurement.canonical_bytes()?,
    )?;
    let resources = measurement.snapshot()?;

    let window_us = options
        .window_seconds
        .checked_mul(1_000_000)
        .ok_or("--window-seconds overflows")?;
    let policy = policy_config(window_us, options)?;
    fs::write(
        options.root.join(format!("{namespace}-policy.json")),
        serde_json::to_vec(&policy)?,
    )?;
    let evaluated_at = utc_now()?;
    let intent = build_intent(
        &namespace,
        &promoted.mint,
        &policy,
        &universe,
        &universe_digest,
        &payloads,
        &census_coverage,
        census_coverage_at,
        census_commit,
        commit_seq_of(&census_receipt.commit_seq)?,
        census_frames_at,
        evaluated_at,
        window_us,
        options,
    )?;
    let journal = PolicyJournal::new(vec![HotScopeRecordV1::Intent(intent.clone())])?;
    let evaluation = PolicyEvaluationV1 {
        decision_occurrence_id: StableString::new(format!("decision-{namespace}"))?,
        evaluated_at,
        policy: policy.clone(),
        resources: resources.clone(),
        collector_generations: vec![CollectorGeneration {
            source_key: StableString::new(SOURCE_KEY)?,
            generation: WireU64::new(1),
            availability: SourceAvailability::Healthy,
            // The only health fact this run holds about the provider is that the census reads
            // it just made over HTTP were accepted with the same credential. That is provider
            // reachability, not a prior WebSocket session, and the link says so by name.
            evidence: vec![EvidenceLink {
                kind: EvidenceKind::SourceHealth,
                id: StableString::new(format!(
                    "provider-http-reachability:{}",
                    census_receipt.store_admission_digest
                ))?,
                digest: None,
                available_at: census_frames_at,
                commit_seq: Some(commit_seq_of(&census_receipt.commit_seq)?),
            }],
        }],
    };
    let decision = evaluate(&journal, &evaluation)?;
    let subject = ScopeSubject {
        kind: SubjectKind::Mint,
        key: StableString::new(promoted.mint.clone())?,
    };
    let terms = promote_one(&decision, &subject)?;

    // Phase 3: one connection, one filtered subscription, one bounded window.
    let subscription = HeliusSubscription::PumpProgramLogs {
        program: promoted.mint.clone(),
        commitment: COMMITMENT.to_owned(),
    };
    let run = runtime.block_on(run_hot_lease(
        &helius,
        terms.clone(),
        namespace.clone(),
        subscription,
        process_start,
    ))?;
    drop(runtime);

    let persisted_at = utc_now()?;
    let retention = commit_lease(
        &mut store,
        &run.ledger,
        &LeaseCommitContext {
            subject_key: promoted.mint.clone(),
            request_fingerprint_material: format!(
                "transport=websocket;method=logsSubscribe;mentions={};commitment={COMMITMENT}",
                promoted.mint
            ),
            persisted_at,
            writer_clock_id: clock_id.clone(),
            committed_mono_ns: elapsed_nanos(process_start)?,
            max_observations_per_batch: MAX_OBSERVATIONS_PER_BATCH,
        },
    )?;
    let durable_bytes = durable_bytes_of(&retention);
    let source_exit_reason = run.source_exit_reason.clone();
    let connections_opened = run.connections_opened;
    let (ledger, settlement) = settle_lease(run, durable_bytes)?;

    // Phase 4: the writer is gone; read the lease back out of the reopened catalog.
    drop(store);
    let readback = read_lease(
        &catalog_config(&options.root)?,
        &retention.coverage_id,
        READBACK_PAYLOAD_LIMIT,
    )?;

    Ok(serde_json::to_string_pretty(&render(
        &namespace,
        &promoted.mint,
        &universe,
        &universe_digest,
        &measurement,
        &terms,
        &ledger,
        &retention,
        &settlement,
        &readback,
        source_exit_reason.as_deref(),
        connections_opened,
        &census_receipt,
    ))?)
}

#[allow(clippy::too_many_arguments)] // One receipt names every phase; a struct would only rename.
fn render(
    namespace: &str,
    mint: &str,
    universe: &MintUniverseV1,
    universe_digest: &str,
    measurement: &ResourceMeasurementV1,
    terms: &joshi_acquisition_policy::HotLeaseTermsV1,
    ledger: &joshi_supervisor::hot_lease::LeaseLedger,
    retention: &LeaseRetentionReceiptV1,
    settlement: &LeaseSettlementV1,
    readback: &LeaseReadbackV1,
    source_exit_reason: Option<&str>,
    connections_opened: u64,
    census_receipt: &PublicStoreReceiptV1,
) -> Value {
    json!({
        "contract": RECEIPT_CONTRACT,
        "schemaVersion": "1",
        "authority": "read_only_no_execution",
        "namespace": namespace,
        "census": {
            "batchDigest": census_receipt.batch_digest.to_string(),
            "commitSeq": census_receipt.commit_seq,
            "retainedObservations": census_receipt.admitted.observations,
            "eligibleSubjectCount": universe.subject_count().to_string(),
            "eligibleUniverseDigest": universe_digest,
            "payloadsWithMints": universe.payloads_with_mints.to_string(),
            "excluded": universe.excluded,
        },
        "resources": {
            "sampledAt": measurement.sampled_at.to_string(),
            "measuredPath": measurement.measured_path,
            "diskFreeBytes": measurement.disk_free_bytes.get().to_string(),
            "diskFloorBytes": measurement.ceilings.disk_floor_bytes.to_string(),
            "retainedBytesToday": measurement.retained_bytes_today.get().to_string(),
            "retainedFilesToday": measurement.retained_files_today.get().to_string(),
            "measurementDigest": measurement.digest().unwrap_or_default(),
            "pressureStage": terms.pressure_stage,
        },
        "lease": {
            "subject": mint,
            "subjectKind": "mint",
            "sourceKey": terms.source_key.as_str(),
            "operationKey": terms.operation_key.as_str(),
            "subscription": "logsSubscribe",
            "mentionsFilter": [mint],
            "commitment": COMMITMENT,
            "scopeRecordContract": DESIRED_CONTRACT,
            "scopeRecordId": terms.scope_record_id.as_str(),
            "degradations": terms.degradations,
            "openedAt": terms.opened_at.to_string(),
            "expiresAt": terms.expires_at.to_string(),
            "windowMs": terms.window_ms().to_string(),
            "maxConnections": terms.max_connections.get().to_string(),
            "connectionsOpened": connections_opened.to_string(),
            "maxFrames": terms.max_frames.get().to_string(),
            "maxIngressBytes": terms.max_ingress_bytes.get().to_string(),
            "subscriptionId": ledger.subscription_id().map(|value| value.to_string()),
            "subscribedAtUnixMs": ledger.subscribed_at_unix_ms().map(|value| value.to_string()),
            "closedAtUnixMs": ledger.closed_unix_ms().map(|value| value.to_string()),
            "stop": ledger.stop(),
            "sourceExitReason": source_exit_reason,
            "providerErrors": ledger.provider_errors(),
            "inboundFrames": ledger.inbound_frames().to_string(),
            "notifications": ledger.notifications().to_string(),
            "ingressBytes": ledger.ingress_bytes().to_string(),
            "observedMs": ledger.observed_ms().to_string(),
        },
        "gaps": ledger.gaps(),
        "retention": retention,
        "settlement": settlement,
        "readback": readback,
    })
}

async fn census_reads(
    client: &HeliusHttpClient,
    options: &Options,
    process_start: Instant,
) -> Result<Vec<CensusRead>, Box<dyn Error>> {
    let mut reads = Vec::new();
    let mut sequence = 0_u64;
    sequence += 1;
    reads.push(
        one_read(
            client,
            sequence,
            process_start,
            &SolanaReadRequest::new(
                SolanaReadMethod::GetSlot,
                json!([{ "commitment": COMMITMENT }]),
            ),
            format!("method=getSlot;commitment={COMMITMENT}"),
        )
        .await?,
    );
    sequence += 1;
    let signatures = one_read(
        client,
        sequence,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetSignaturesForAddress,
            json!([PUMP_PROGRAM, { "limit": options.census_signatures, "commitment": COMMITMENT }]),
        ),
        format!(
            "method=getSignaturesForAddress;address={PUMP_PROGRAM};limit={};commitment={COMMITMENT}",
            options.census_signatures
        ),
    )
    .await?;
    let selected = first_signatures(&signatures.frame, options.census_transactions as usize);
    reads.push(signatures);
    if selected.is_empty() {
        return Err("the signature page named no signature to read".into());
    }
    for signature in selected {
        sequence += 1;
        reads.push(
            one_read(
                client,
                sequence,
                process_start,
                &SolanaReadRequest::new(
                    SolanaReadMethod::GetTransaction,
                    json!([signature, {
                        "encoding": "json",
                        "commitment": COMMITMENT,
                        "maxSupportedTransactionVersion": 0
                    }]),
                ),
                format!(
                    "method=getTransaction;signature={signature};commitment={COMMITMENT};encoding=json"
                ),
            )
            .await?,
        );
    }
    Ok(reads)
}

struct CensusRead {
    frame: RawSourceFrame,
    method: SolanaReadMethod,
    fingerprint_material: String,
    started_at_millis: i64,
    started_mono_ns: u64,
    received_mono_ns: u64,
}

async fn one_read(
    client: &HeliusHttpClient,
    sequence: u64,
    process_start: Instant,
    request: &SolanaReadRequest,
    fingerprint_material: String,
) -> Result<CensusRead, Box<dyn Error>> {
    let method = request.method;
    let started_at_millis = unix_millis(now())?;
    let started_mono_ns = elapsed_nanos(process_start)?;
    let (mut frame, _rate_limit) = client
        .request(request, UnixMillis(started_at_millis), sequence)
        .await?;
    let received_mono_ns = elapsed_nanos(process_start)?;
    frame.received_at = UnixMillis(unix_millis(now())?);
    if frame.http_status != Some(200) {
        return Err(format!(
            "Helius rejected the {} read with HTTP status {:?}; authenticated URL omitted",
            method.as_str(),
            frame.http_status
        )
        .into());
    }
    if let Ok(value) = serde_json::from_slice::<Value>(&frame.body)
        && value.get("error").is_some()
    {
        return Err(format!("Helius {} returned a JSON-RPC error", method.as_str()).into());
    }
    Ok(CensusRead {
        frame,
        method,
        fingerprint_material,
        started_at_millis,
        started_mono_ns,
        received_mono_ns,
    })
}

fn commit_census_frames(
    store: &mut SqliteStore,
    reads: Vec<CensusRead>,
    namespace: &str,
    clock_id: &str,
    committed_at: UtcTimestamp,
    committed_mono_ns: u64,
) -> Result<PublicStoreReceiptV1, Box<dyn Error>> {
    let mut frames = Vec::with_capacity(reads.len());
    for read in reads {
        let started = utc_from_millis(read.started_at_millis)?;
        frames.push(SourceFrameInput {
            context: EvidenceContext {
                occurrence_namespace: format!("census-{namespace}"),
                redacted_request_fingerprint_material: read.fingerprint_material,
                parent_acquisition_id: None,
                locator: LogicalSourceLocator::HeliusHttp {
                    method: read.method.as_str(),
                },
                source_variant: OpenVariant::known(format!(
                    "solana_rpc_response:{}",
                    read.method.as_str()
                ))?,
                source_cursor: None,
                source_events: Vec::new(),
                // The census reads are retained as opaque evidence; no provider clock is
                // asserted for any of them here.
                provider_event_time: ProviderEventTime::Missing {
                    reason: "census read retains the response without asserting a provider clock"
                        .to_owned(),
                },
                chain_slot: None,
                transaction_index: None,
                instruction_path: Vec::new(),
                log_index: None,
                finality: None,
                acquisition_started_at: started,
                requested_at: Some(started),
                monotonic_clock_id: clock_id.to_owned(),
                acquisition_started_monotonic_ns: read.started_mono_ns,
                received_monotonic_ns: read.received_mono_ns,
                persisted_at: committed_at,
            },
            frame: read.frame,
        });
    }
    let batch = source_frames(
        frames,
        Vec::new(),
        Vec::new(),
        StableString::new(format!("census-frames-{namespace}"))?,
        committed_at,
        StableString::new(clock_id)?,
        committed_mono_ns,
    )?;
    Ok(batch.commit(store)?)
}

fn commit_census_coverage(
    store: &mut SqliteStore,
    coverage_id: &CoverageId,
    clock_id: &str,
    committed_at: UtcTimestamp,
    committed_mono_ns: u64,
) -> Result<PublicStoreReceiptV1, Box<dyn Error>> {
    let scope = CoverageScope {
        source_id: DomainSourceId::new("helius.http.solana.v1")?,
        family: OpenVariant::known("market_census")?,
        // The census closes over the Pump program's recent activity, not over one subject.
        subject: None,
    };
    let window = CoverageWindow {
        coverage_id: coverage_id.clone(),
        scope,
        lower: Boundary::Wall {
            value: committed_at,
        },
        upper: Some(Boundary::Wall {
            value: committed_at,
        }),
        state: OpenVariant::known("closed")?,
        available_at: committed_at,
    };
    // A closed instant window: this census is one bounded read, not a standing sweep.
    let batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(format!("census-coverage-{}", coverage_id.as_str()))?,
        drafts: vec![EvidenceDraft::CoverageWindow(window)],
        source_events: Vec::new(),
        cursor_advances: Vec::new(),
        registrations: vec![http_source_registration()?],
        policy: AdmissionPolicy::public_source()?,
        committed_at,
        writer_clock_id: StableString::new(clock_id)?,
        committed_mono_ns,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })?;
    Ok(batch.commit(store)?)
}

/// The exact registration `joshi_admission::source_frames` emits for a Helius HTTP frame.
fn http_source_registration() -> Result<SourceRegistration, Box<dyn Error>> {
    let source_id = DomainSourceId::new("helius.http.solana.v1")?;
    let collector_build = env!("CARGO_PKG_VERSION");
    let material = format!(
        "joshi.source.registration.v1\0{}\0read_only_market_source\0{ADAPTER_CONTRACT_VERSION}\0{collector_build}",
        source_id.as_str()
    );
    Ok(SourceRegistration {
        source_id,
        namespace: StableString::new("read_only_market_source")?,
        contract_version: StableString::new(ADAPTER_CONTRACT_VERSION)?,
        collector_build: StableString::new(collector_build)?,
        configuration_digest: ValueDigest::new(
            joshi_admission::Sha256Digest::of_bytes(material.as_bytes()).to_string(),
        )?,
    })
}

fn retained_http_payloads(store: &SqliteStore) -> Result<Vec<RetainedPayload>, Box<dyn Error>> {
    let source_id = DomainSourceId::new("helius.http.solana.v1")?;
    let Some(found) =
        store.source_observations_as_known(&source_id, None, READBACK_PAYLOAD_LIMIT)?
    else {
        return Err(
            "the census committed no retained observation to derive a universe from".into(),
        );
    };
    Ok(found
        .observations
        .into_iter()
        .map(|observation| {
            (
                observation.observation_id.as_str().to_owned(),
                observation.payload,
            )
        })
        .collect())
}

fn policy_config(window_us: u64, options: &Options) -> Result<PolicyConfigV1, Box<dyn Error>> {
    let material = format!(
        "joshi.hot_lease.policy/v1\0{SOURCE_KEY}\0{OPERATION_KEY}\0{window_us}\0{}\0{}",
        options.max_ingress_bytes, options.max_frames
    );
    let digest = format!("sha256:{:x}", Sha256::digest(material.as_bytes()));
    Ok(PolicyConfigV1 {
        policy_id: StableString::new("joshi-hot-lease-s4")?,
        policy_version: StableString::new("1")?,
        config_digest: ValueDigest::new(digest)?,
        // Exactly one hot subject of any kind. This is the whole point of the slice.
        max_hot_mints: WireU64::new(1),
        max_hot_wallets: WireU64::new(1),
        max_other_subjects: WireU64::new(1),
        shortened_hot_ttl_us: WireU64::new(window_us),
        degraded_social_refresh_us: WireU64::new(30_000_000),
        source_policies: vec![SourcePolicyV1 {
            source_key: StableString::new(SOURCE_KEY)?,
            operation_keys: vec![StableString::new(OPERATION_KEY)?],
            maximum_budget: BudgetEnvelope {
                max_requests: WireU64::new(1),
                max_pages: WireU64::new(options.max_frames),
                max_response_bytes: WireU64::new(options.max_ingress_bytes),
                max_provider_credits: WireU64::new(options.max_frames),
                provider_currency: Vec::new(),
                chain_native: Vec::new(),
            },
            native_units_authorized: false,
        }],
    })
}

#[allow(clippy::too_many_arguments)] // The intent closes over every clock and cutoff it names.
#[allow(clippy::too_many_lines)] // Every field of one validated intent belongs in one place.
fn build_intent(
    namespace: &str,
    mint: &str,
    policy: &PolicyConfigV1,
    universe: &MintUniverseV1,
    universe_digest: &str,
    payloads: &[RetainedPayload],
    census_coverage: &CoverageId,
    census_available_through: UtcTimestamp,
    census_commit: WireU64,
    frames_commit: WireU64,
    frames_available_at: UtcTimestamp,
    evaluated_at: UtcTimestamp,
    window_us: u64,
    options: &Options,
) -> Result<HotScopeIntentV1, Box<dyn Error>> {
    let policy_occurrence_id = StableString::new(format!("policy-occurrence-{namespace}"))?;
    let artifact_id = StableString::new(format!("census-universe:{universe_digest}"))?;
    let mut evidence = vec![
        EvidenceLink {
            kind: EvidenceKind::PolicyOccurrence,
            id: policy_occurrence_id.clone(),
            digest: Some(policy.config_digest.clone()),
            // The policy bytes were fixed before this commit; the sequence is a knowledge-order
            // bound on when they were known, not a claim that they are a catalog row.
            available_at: census_available_through,
            commit_seq: Some(census_commit),
        },
        EvidenceLink {
            kind: EvidenceKind::Artifact,
            id: artifact_id.clone(),
            digest: Some(ValueDigest::new(universe_digest.to_owned())?),
            available_at: census_available_through,
            commit_seq: Some(census_commit),
        },
        EvidenceLink {
            kind: EvidenceKind::Coverage,
            id: StableString::new(census_coverage.as_str())?,
            digest: None,
            available_at: census_available_through,
            commit_seq: Some(census_commit),
        },
    ];
    let mut observation_evidence: Vec<EvidenceLink> = payloads
        .iter()
        .map(|(observation_id, _)| {
            Ok::<_, Box<dyn Error>>(EvidenceLink {
                kind: EvidenceKind::Observation,
                id: StableString::new(observation_id.clone())?,
                digest: None,
                available_at: frames_available_at,
                commit_seq: Some(frames_commit),
            })
        })
        .collect::<Result<_, _>>()?;
    observation_evidence.sort();
    observation_evidence.dedup();
    evidence.extend(observation_evidence.iter().cloned());
    evidence.sort();
    evidence.dedup();

    let mut coverage_evidence = vec![EvidenceLink {
        kind: EvidenceKind::Coverage,
        id: StableString::new(census_coverage.as_str())?,
        digest: None,
        available_at: census_available_through,
        commit_seq: Some(census_commit),
    }];
    coverage_evidence.sort();

    let denominator = CensusDenominatorRef {
        census_id: StableString::new(format!("census-{namespace}"))?,
        kind: CensusKind::IndependentChainProvider,
        eligible_membership_artifact_id: artifact_id,
        eligible_universe_digest: ValueDigest::new(universe_digest.to_owned())?,
        eligible_subject_count: WireU64::new(universe.subject_count()),
        as_of: AsOfCutoff {
            available_through: census_available_through,
            commit_through: Some(census_commit),
        },
        evidence: observation_evidence,
        coverage_evidence,
        parity_receipt_id: None,
    };

    let expires_at = UtcTimestamp::new(
        evaluated_at
            .as_datetime()
            .checked_add(time::Duration::microseconds(i64::try_from(window_us)?))
            .ok_or("lease expiry overflows")?,
    )?;
    Ok(HotScopeIntentV1 {
        head: PolicyRecordHead {
            contract: StableString::new(INTENT_CONTRACT)?,
            schema_version: WireU64::new(1),
            record_id: StableString::new(format!("intent-record-{namespace}"))?,
            record_ordinal: WireU64::new(1),
            recorded_at: evaluated_at,
            predecessor_record_id: None,
        },
        intent_id: StableString::new(format!("intent-{namespace}"))?,
        subject: ScopeSubject {
            kind: SubjectKind::Mint,
            key: StableString::new(mint)?,
        },
        opened_at: census_available_through,
        expires_at,
        last_justified_at: census_available_through,
        requesting_occurrence_id: StableString::new(format!("census-promotion-{namespace}"))?,
        scene_id: None,
        policy_occurrence_id,
        policy_config_digest: policy.config_digest.clone(),
        as_of: AsOfCutoff {
            available_through: census_available_through,
            commit_through: Some(census_commit),
        },
        authority: StableString::new("read_only_no_execution")?,
        // No operator gesture exists yet (that is slice S3), so the subject is named by a stated
        // deterministic rule over the census and the record says exactly that.
        activation: ActivationAuthority::DeterministicRule {
            rule_id: StableString::new("joshi.hot_lease.deterministic_census_promotion")?,
            rule_version: StableString::new("v1")?,
        },
        reasons: vec![IntentReason {
            kind: IntentReasonKind::DeterministicCensusRule,
            reason_id: StableString::new(format!("reason-{namespace}"))?,
            justified_at: census_available_through,
            evidence,
        }],
        census_denominators: vec![denominator],
        requested_sources: vec![SourceScopeRequest {
            source_key: StableString::new(SOURCE_KEY)?,
            operation_key: StableString::new(OPERATION_KEY)?,
            source_family: SourceFamily::HeliusPublicChain,
            fidelity: Fidelity {
                exact_public_bodies: true,
                exact_private_bodies_optional: false,
                media: MediaFidelity::None,
                refresh_interval_us: None,
            },
            budget: BudgetEnvelope {
                max_requests: WireU64::new(1),
                max_pages: WireU64::new(options.max_frames),
                max_response_bytes: WireU64::new(options.max_ingress_bytes),
                max_provider_credits: WireU64::new(options.max_frames),
                provider_currency: Vec::new(),
                chain_native: Vec::new(),
            },
        }],
    })
}

fn durable_bytes_of(retention: &LeaseRetentionReceiptV1) -> u64 {
    retention
        .observation_batches
        .iter()
        .chain(retention.coverage_batches.iter())
        .filter_map(|receipt| receipt.admitted.raw_bytes.parse::<u64>().ok())
        .fold(0_u64, u64::saturating_add)
}

fn first_signatures(frame: &RawSourceFrame, wanted: usize) -> Vec<String> {
    let Ok(value) = serde_json::from_slice::<Value>(&frame.body) else {
        return Vec::new();
    };
    value
        .get("result")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|row| row.get("signature").and_then(Value::as_str))
                .take(wanted)
                .map(ToOwned::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

fn catalog_config(root: &Path) -> Result<StoreConfig, Box<dyn Error>> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: INLINE_BLOB_MAX_BYTES,
        busy_timeout: BUSY_TIMEOUT,
        catalog_id: StableString::new(CATALOG_ID)?,
        max_observations_per_batch: MAX_OBSERVATIONS_PER_BATCH,
        max_raw_bytes_per_batch: MAX_RAW_BYTES_PER_BATCH,
    })
}

fn now() -> OffsetDateTime {
    OffsetDateTime::now_utc()
}

fn utc_now() -> Result<UtcTimestamp, Box<dyn Error>> {
    let value = now();
    let nanosecond = value.nanosecond();
    Ok(UtcTimestamp::new(
        value.replace_nanosecond(nanosecond - nanosecond % 1_000)?,
    )?)
}

fn unix_millis(value: OffsetDateTime) -> Result<i64, Box<dyn Error>> {
    Ok(i64::try_from(value.unix_timestamp_nanos() / 1_000_000)?)
}

fn utc_from_millis(millis: i64) -> Result<UtcTimestamp, Box<dyn Error>> {
    Ok(UtcTimestamp::new(
        OffsetDateTime::from_unix_timestamp_nanos(i128::from(millis) * 1_000_000)?,
    )?)
}

fn elapsed_nanos(process_start: Instant) -> Result<u64, Box<dyn Error>> {
    Ok(u64::try_from(process_start.elapsed().as_nanos())?)
}
