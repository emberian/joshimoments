//! One bounded Pump / `PumpSwap` program census, from the live source edge to the sole catalog.
//!
//! The census reads two program addresses through the same authenticated Helius edge that
//! [`crate::live`] owns, and it names exactly one subject relation:
//!
//! > this mint appears in the token balances of a transaction whose resolved account keys include
//! > this program address.
//!
//! That is all a `getSignaturesForAddress` page plus a `getTransaction` body can support. It is
//! not a launch, not a migration, not a trade, not a price, and not the whole activity of the
//! mint. Where the transaction body additionally names the program as an instruction program ID
//! the census records that as separate, derived evidence; where the encoding cannot resolve an
//! instruction's program account the census records `unresolved`, never a guess.
//!
//! Every read is bounded twice before a socket opens: a worst-case
//! [`joshi_supervisor::BudgetLedger`] permit, and an fsynced supervisor attempt reservation. Every
//! read is resolved afterwards: settled against the ledger, and either sealed into the local spool
//! as durable evidence or abandoned as an explicit durable gap.

use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

use joshi_admission::{
    AdmissionBatch, AdmissionPolicy, PublicStoreReceiptV1, SourceDraftBatch, SourceFrameInput,
    source_drafts, source_frames,
};
use joshi_domain::{CoverageId, OpenVariant, StableString, UtcTimestamp};
use joshi_evidence::{Boundary, CoverageGap, CoverageScope, CoverageWindow, EvidenceDraft};
use joshi_sources::{
    CredentialFile, HeliusConfig, HeliusHttpClient, SolanaReadMethod, SolanaReadRequest,
};
use joshi_spool::ProtectionDomainId;
use joshi_store::{SqliteStore, StoreMode};
use joshi_supervisor::{
    AttemptBudgetClaim, AttemptBudgetUsage, AttemptKind, BudgetLedger, OperationKey,
    ProtectionProfile, ReservationRequest, RunBudgetLimits, SourceKey, Supervisor,
    SupervisorConfig, ingest::physical_size::ingest_physical_bound, prepare_evidence_batch,
};
use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest as _, Sha256};
use time::OffsetDateTime;

use crate::live::{
    CapturedRead, ReadBudget, catalog_config, elapsed_nanos, ensure_provider_accepted,
    evidence_context, now_utc, open_catalog, perform_one, read_summary, retained_payload,
    unix_millis, validate_base58_address,
};

/// Official Pump program address. Naming it here is a request parameter, never a claim about it.
pub(crate) const PUMP_PROGRAM: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
/// Official `PumpSwap` program address.
pub(crate) const PUMPSWAP_PROGRAM: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";

const CENSUS_RECEIPT_CONTRACT: &str = "joshi.collector.census_receipt.v1";
const CENSUS_RUN_CONTRACT: &str = "joshi.collector.census_run_registration.v1";
const CENSUS_READBACK_CONTRACT: &str = "joshi.collector.census_readback.v1";
const CENSUS_POLICY_CONTRACT: &str = "joshi.collector.census_run_registration.v1";
const AUTHORITY: &str = "read_only_no_execution";
const DOMAIN_SOURCE_ID: &str = "helius.http.solana.v1";
const COVERAGE_FAMILY: &str = "market_census";
const PROTECTION_DOMAIN: &str = "public-solana-census";
/// The one relation this census asserts. It is a property of the retained transaction bytes, not
/// of which signature page happened to list the transaction, so the run's rendering and a later
/// store-only rendering derive it identically.
const SUBJECT_RELATION: &str = "mint appears in the token balances of a transaction whose resolved account keys include this program address";
const MAX_SIGNATURE_LIMIT: u32 = 1_000;
const MAX_PROGRAMS: usize = 8;
/// Ingress ceiling for one census read. A `getSignaturesForAddress` page of at most 1,000 rows and
/// a single `getTransaction` body both sit far below this; a response longer than this is one the
/// physical retention derivation below would not fit in a single spool segment, so it is abandoned
/// unread rather than parsed.
const CENSUS_MAX_RESPONSE_BYTES: u64 = 1024 * 1024;
const ATTEMPT_MAX_ELAPSED_MS: u64 = 60_000;
const RUN_MAX_ELAPSED_MS: u64 = 15 * 60_000;

/// Every argument of one bounded census occurrence.
#[derive(Debug)]
pub(crate) struct CensusOptions {
    pub(crate) root: PathBuf,
    pub(crate) programs: Vec<String>,
    pub(crate) signature_limit: u32,
    pub(crate) transactions_per_program: u32,
    pub(crate) max_requests: u32,
    pub(crate) key_file: PathBuf,
}

/// The exact bytes that register this census run. Digest-closed and retained beside the catalog.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CensusRunRegistrationV1 {
    contract: &'static str,
    schema_version: u64,
    run_id: String,
    collector_build: &'static str,
    /// This run performs authenticated read-only HTTP. It is not an offline fixture run.
    provider_execution: &'static str,
    authority: &'static str,
    source_id: &'static str,
    subject_relation: &'static str,
    programs: Vec<String>,
    signature_page_limit: u32,
    transactions_per_program: u32,
    max_provider_requests: u32,
    budget: RunBudgetLimits,
}

/// One signature row exactly as the provider listed it.
#[derive(Clone, Debug)]
struct ListedSignature {
    signature: String,
    slot: Option<u64>,
}

/// Per-program census bookkeeping. Every count here is a denominator, never an estimate.
#[derive(Debug)]
struct ProgramCensus {
    address: String,
    reached: bool,
    listed: Vec<ListedSignature>,
    page_was_full: bool,
    sampled: Vec<String>,
    unsampled: Vec<ListedSignature>,
    transactions_with_result: u32,
}

impl ProgramCensus {
    fn new(address: String) -> Self {
        Self {
            address,
            reached: false,
            listed: Vec::new(),
            page_was_full: false,
            sampled: Vec::new(),
            unsampled: Vec::new(),
            transactions_with_result: 0,
        }
    }
}

/// How the retained transaction bytes relate this program to this mint's transaction.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum ProgramRelation {
    /// An instruction in the retained body names this program as its program account.
    InstructionProgramId,
    /// The program is among the resolved account keys, but no retained instruction names it.
    AccountKeyOnly,
    /// An instruction index could not be resolved against the retained keys.
    UnresolvedInstructionIndex,
    /// The program does not appear among the resolved account keys of the retained body.
    AbsentFromAccountKeys,
}

impl ProgramRelation {
    const fn as_str(self) -> &'static str {
        match self {
            Self::InstructionProgramId => "instruction_program_id",
            Self::AccountKeyOnly => "account_key_only",
            Self::UnresolvedInstructionIndex => "unresolved_instruction_index",
            Self::AbsentFromAccountKeys => "absent_from_account_keys",
        }
    }
}

/// One census subject: a mint, and exactly what was observed about it.
#[derive(Debug, Default)]
struct MintCensus {
    signatures: BTreeSet<String>,
    programs: BTreeSet<String>,
    relations: BTreeSet<&'static str>,
    lowest_slot: Option<u64>,
    highest_slot: Option<u64>,
}

impl MintCensus {
    fn record(
        &mut self,
        signature: &str,
        program: &str,
        relation: ProgramRelation,
        slot: Option<u64>,
    ) {
        self.signatures.insert(signature.to_owned());
        self.programs.insert(program.to_owned());
        self.relations.insert(relation.as_str());
        if let Some(slot) = slot {
            self.lowest_slot = Some(self.lowest_slot.map_or(slot, |current| current.min(slot)));
            self.highest_slot = Some(self.highest_slot.map_or(slot, |current| current.max(slot)));
        }
    }
}

/// A gap detected during the run, before it is given an identity and a parent window.
#[derive(Debug)]
struct DetectedGap {
    subject: Option<String>,
    reason: String,
    lower: Boundary,
    upper: Option<Boundary>,
}

/// Everything one census run observed, plus every place it stopped short.
struct CensusState {
    programs: Vec<ProgramCensus>,
    mints: BTreeMap<String, MintCensus>,
    gaps: Vec<DetectedGap>,
    tip_slot: Option<u64>,
    reads: Vec<CapturedRead>,
    commits: Vec<Value>,
    reservations: Vec<Value>,
    terminal_failure: Option<String>,
}

/// Run one bounded census and durably retain everything it observed and everything it missed.
///
/// # Errors
///
/// Returns a sanitized error for an invalid argument, an unreadable credential, or any durable
/// store, spool, supervisor or admission failure. No error carries the authenticated endpoint or
/// the credential. A provider read that fails after I/O began is *not* an error: it is recorded as
/// a terminal explicit gap, and the partial census still commits.
pub(crate) fn run_census(options: &CensusOptions) -> Result<String, Box<dyn Error>> {
    let programs = validated_programs(options)?;
    let process_start = Instant::now();
    let run_id = census_run_id()?;
    let limits = run_budget_limits(options.max_requests)?;
    let registration = CensusRunRegistrationV1 {
        contract: CENSUS_RUN_CONTRACT,
        schema_version: 1,
        run_id: run_id.clone(),
        collector_build: env!("CARGO_PKG_VERSION"),
        provider_execution: "live_http_read_only",
        authority: AUTHORITY,
        source_id: DOMAIN_SOURCE_ID,
        subject_relation: SUBJECT_RELATION,
        programs: programs.clone(),
        signature_page_limit: options.signature_limit,
        transactions_per_program: options.transactions_per_program,
        max_provider_requests: options.max_requests,
        budget: limits,
    };
    let registration_bytes = serde_json::to_vec(&registration)?;
    let registration_digest = sha256_hex(&registration_bytes);
    let registration_path = write_run_registration(&options.root, &run_id, &registration_bytes)?;

    // Take the writer lease and reach the current schema before a socket opens: a read that
    // cannot be durably retained is not evidence, and failing first costs the provider nothing.
    let mut store = open_catalog(&options.root, StoreMode::SingleWriter)?;
    let migration = store.migrate(now_utc()?)?;
    let mut supervisor = Supervisor::open(census_supervisor_config(&options.root))?;
    supervisor.reconcile_startup(now_utc()?)?;
    let mut ledger = BudgetLedger::new(limits, 0)?;

    let helius = HeliusConfig::mainnet(CredentialFile(options.key_file.clone()));
    let client = HeliusHttpClient::at_startup(&helius, CENSUS_MAX_RESPONSE_BYTES)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let context = CensusContext {
        options,
        programs: &programs,
        run_id: &run_id,
        registration_bytes: &registration_bytes,
        process_start,
    };
    let mut state = runtime.block_on(collect(
        &client,
        &mut store,
        &mut supervisor,
        &mut ledger,
        &context,
    ))?;
    drop(runtime);
    drop(client);

    let coverage = commit_coverage(
        &mut store,
        &mut supervisor,
        &mut state,
        &context,
        &registration_bytes,
    )?;
    let snapshot = ledger.snapshot(elapsed_millis(process_start)?);
    let health = supervisor.health()?;
    let rendered = json!({
        "contract": CENSUS_RECEIPT_CONTRACT,
        "runId": run_id,
        "runRegistrationContract": CENSUS_RUN_CONTRACT,
        "runRegistrationDigest": registration_digest,
        "runRegistrationPath": registration_path.display().to_string(),
        "subjectRelation": SUBJECT_RELATION,
        "catalogRoot": options.root.display().to_string(),
        "catalogSchema": store.catalog_schema()?.as_str(),
        "appliedMigrations": migration.applied.len(),
        "supervisorInstallationId": supervisor.installation_id(),
        "supervisorReadySegments": health.ready_segments,
        "supervisorAbandonedAttempts": health.abandoned_attempts,
        "supervisorLifecycle": health.lifecycle,
        "observedFinalizedTipSlot": state.tip_slot,
        "providerRequests": state.reads.len(),
        "providerRequestBudget": options.max_requests,
        "providerResponseBytes": response_bytes(&state),
        "budget": serde_json::to_value(snapshot)?,
        "terminalFailure": state.terminal_failure,
        "reservations": state.reservations,
        "commits": state.commits,
        "coverageCommit": coverage.commit,
        "coverageWindows": coverage.windows,
        "coverageGaps": coverage.gaps,
        "programs": program_denominators(&state),
        "mints": rendered_mints(&state),
        "explicitUnknowns": explicit_unknowns(&state),
        "reads": state.reads.iter().map(read_summary).collect::<Vec<_>>(),
    });
    Ok(serde_json::to_string_pretty(&rendered)?)
}

/// Immutable per-run context shared by every step of the read loop.
struct CensusContext<'a> {
    options: &'a CensusOptions,
    programs: &'a [String],
    run_id: &'a str,
    registration_bytes: &'a [u8],
    process_start: Instant,
}

impl CensusContext<'_> {
    fn namespace(&self) -> String {
        format!("collector-census-{}", self.run_id)
    }
}

fn census_clock_id() -> String {
    format!("joshi-collector-census-{}", std::process::id())
}

async fn collect(
    client: &HeliusHttpClient,
    store: &mut SqliteStore,
    supervisor: &mut Supervisor,
    ledger: &mut BudgetLedger,
    context: &CensusContext<'_>,
) -> Result<CensusState, Box<dyn Error>> {
    let mut state = CensusState {
        programs: context
            .programs
            .iter()
            .map(|address| ProgramCensus::new(address.clone()))
            .collect(),
        mints: BTreeMap::new(),
        gaps: Vec::new(),
        tip_slot: None,
        reads: Vec::new(),
        commits: Vec::new(),
        reservations: Vec::new(),
        terminal_failure: None,
    };
    let mut budget = ReadBudget::new(context.options.max_requests);
    let mut sequence = 0_u64;

    sequence += 1;
    let tip = perform_bounded_read(
        &mut ReadPlane {
            client,
            store,
            supervisor,
            ledger,
            budget: &mut budget,
            state: &mut state,
            context,
        },
        BoundedRead {
            sequence,
            subject: None,
            operation: "getSlot",
            request: SolanaReadRequest::new(
                SolanaReadMethod::GetSlot,
                json!([{ "commitment": "finalized" }]),
            ),
            fingerprint_material: "method=getSlot;commitment=finalized".to_owned(),
            source_cursor: None,
        },
    )
    .await?;
    let Some(tip) = tip else {
        return Ok(state);
    };
    state.tip_slot = serde_json::from_slice::<Value>(&state.reads[tip].frame.body)
        .ok()
        .and_then(|value| value.get("result").and_then(Value::as_u64));

    for index in 0..state.programs.len() {
        let mut plane = ReadPlane {
            client,
            store,
            supervisor,
            ledger,
            budget: &mut budget,
            state: &mut state,
            context,
        };
        if !census_one_program(&mut plane, index, &mut sequence).await? {
            return Ok(state);
        }
    }
    record_sampling_gaps(&mut state)?;
    Ok(state)
}

/// Everything one bounded read needs to reserve, read, settle and durably resolve itself.
struct ReadPlane<'a> {
    client: &'a HeliusHttpClient,
    store: &'a mut SqliteStore,
    supervisor: &'a mut Supervisor,
    ledger: &'a mut BudgetLedger,
    budget: &'a mut ReadBudget,
    state: &'a mut CensusState,
    context: &'a CensusContext<'a>,
}

/// Census one program: one signature page, then a bounded hydration of its head.
///
/// Returns `false` when the census must stop; every stop leaves an explicit gap behind it.
async fn census_one_program(
    plane: &mut ReadPlane<'_>,
    index: usize,
    sequence: &mut u64,
) -> Result<bool, Box<dyn Error>> {
    let address = plane.state.programs[index].address.clone();
    if plane.budget.remaining() == 0 {
        plane.state.gaps.push(DetectedGap {
            subject: Some(address),
            reason: "program_not_reached_before_request_budget_exhausted".to_owned(),
            lower: unknown_boundary("no signature page was requested for this program")?,
            upper: Some(unknown_boundary(
                "no signature page was requested for this program",
            )?),
        });
        return Ok(true);
    }
    *sequence += 1;
    let signature_limit = plane.context.options.signature_limit;
    let page = perform_bounded_read(
        plane,
        BoundedRead {
            sequence: *sequence,
            subject: Some(address.clone()),
            operation: "getSignaturesForAddress",
            request: SolanaReadRequest::new(
                SolanaReadMethod::GetSignaturesForAddress,
                json!([address, { "limit": signature_limit, "commitment": "finalized" }]),
            ),
            fingerprint_material: format!(
                "method=getSignaturesForAddress;address={address};limit={signature_limit};commitment=finalized"
            ),
            source_cursor: None,
        },
    )
    .await?;
    let Some(page) = page else {
        return Ok(false);
    };
    let listed = listed_signatures(&plane.state.reads[page].frame.body);
    // The page's own oldest signature is the source-native cursor for its next page. It is
    // recorded as observed cursor text, and is never promoted to durable cursor authority.
    if let Some(oldest) = listed.last() {
        plane.state.reads[page].source_cursor = Some(format!("signature:{}", oldest.signature));
    }
    let wanted =
        usize::try_from(plane.context.options.transactions_per_program).unwrap_or(usize::MAX);
    let sampled: Vec<String> = listed
        .iter()
        .take(wanted)
        .map(|row| row.signature.clone())
        .collect();
    {
        let program = &mut plane.state.programs[index];
        program.reached = true;
        program.page_was_full = u32::try_from(listed.len()).unwrap_or(u32::MAX) >= signature_limit;
        program.unsampled = listed.iter().skip(sampled.len()).cloned().collect();
        program.sampled.clone_from(&sampled);
        program.listed = listed;
    }
    for signature in sampled {
        if plane.budget.remaining() == 0 {
            break;
        }
        *sequence += 1;
        let read = perform_bounded_read(
            plane,
            BoundedRead {
                sequence: *sequence,
                subject: Some(address.clone()),
                operation: "getTransaction",
                request: SolanaReadRequest::new(
                    SolanaReadMethod::GetTransaction,
                    json!([
                        signature,
                        {
                            "encoding": "json",
                            "commitment": "finalized",
                            "maxSupportedTransactionVersion": 0
                        }
                    ]),
                ),
                fingerprint_material: format!(
                    "method=getTransaction;signature={signature};commitment=finalized;encoding=json"
                ),
                source_cursor: Some(format!("signature:{signature}")),
            },
        )
        .await?;
        let Some(read) = read else {
            return Ok(false);
        };
        let body = plane.state.reads[read].frame.body.clone();
        absorb_transaction(plane.state, index, &address, &signature, &body)?;
        if plane.state.reads[read].rate_limit.is_some() {
            // A rate-limit signal ends the run. Retrying a throttled provider in a loop is
            // exactly the behavior the bounded budget exists to prevent.
            plane.state.terminal_failure =
                Some("provider signalled rate limiting; census stopped".to_owned());
            record_remaining_program_gaps(plane.state, index)?;
            return Ok(false);
        }
    }
    Ok(true)
}

/// Everything one bounded provider read needs, assembled before any reservation is taken.
struct BoundedRead {
    sequence: u64,
    subject: Option<String>,
    operation: &'static str,
    request: SolanaReadRequest,
    fingerprint_material: String,
    source_cursor: Option<String>,
}

/// What a settled read left behind: exact retained bytes, or an exact reason it has none.
enum SettledRead {
    Retained(Box<CapturedRead>),
    Failed {
        reason: &'static str,
        message: String,
    },
}

/// Reserve, read, settle, and durably resolve exactly one provider request.
///
/// Returns the index of the retained read, or `None` when the read produced no evidence. A
/// failure is never retried: it settles conservatively, abandons the reservation as a durable
/// spool gap, records an explicit coverage gap, and stops the census.
async fn perform_bounded_read(
    plane: &mut ReadPlane<'_>,
    read: BoundedRead,
) -> Result<Option<usize>, Box<dyn Error>> {
    let claim = attempt_claim()?;
    // Worst-case capacity first, then a durable attempt identity, and only then a socket.
    let permit = plane
        .ledger
        .reserve(claim, elapsed_millis(plane.context.process_start)?)?;
    let reservation = plane.supervisor.reserve(
        ReservationRequest {
            source_key: SourceKey::new(DOMAIN_SOURCE_ID)?,
            operation_key: OperationKey::new(read.operation)?,
            kind: AttemptKind::HttpRequest,
            scope: coverage_scope(read.subject.as_deref())?,
            lower: Boundary::Wall { value: now_utc()? },
            protection: ProtectionProfile::PublicIntegrity {
                domain: ProtectionDomainId::new(PROTECTION_DOMAIN)?,
            },
            // No Wave 5 run reference is asserted. A live authenticated HTTP run cannot be
            // described by a registration whose only execution mode is `offline_fixture_only`,
            // and a false document is worse than an absent one. See this slice's report.
            run: None,
            execution_claim: None,
            provider_plan: None,
        },
        now_utc()?,
    )?;
    let started = Instant::now();
    let outcome = perform_one(
        plane.client,
        plane.budget,
        read.sequence,
        plane.context.process_start,
        &read.request,
        read.fingerprint_material,
    )
    .await;
    let elapsed_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    let settled = settle_read(plane.ledger, permit, claim, outcome, elapsed_ms)?;

    match settled {
        SettledRead::Retained(mut captured) => {
            captured.source_cursor = read.source_cursor;
            let committed = commit_read(plane.store, &captured, plane.context, read.sequence)?;
            let segment = seal_to_spool(
                plane.supervisor,
                &reservation,
                &committed.batch,
                plane.context.registration_bytes,
            )?;
            plane.state.reservations.push(reservation_summary(
                &reservation,
                read.operation,
                &format!("durable_spool_segment:{segment}"),
            ));
            plane.state.commits.push(committed.rendered);
            plane.state.reads.push(*captured);
            Ok(Some(plane.state.reads.len() - 1))
        }
        SettledRead::Failed { reason, message } => {
            plane
                .supervisor
                .abandon(&reservation, OpenVariant::known(reason)?, now_utc()?)?;
            plane.state.reservations.push(reservation_summary(
                &reservation,
                read.operation,
                &format!("abandoned:{reason}"),
            ));
            plane.state.gaps.push(DetectedGap {
                subject: read.subject,
                reason: reason.to_owned(),
                lower: unknown_boundary("the read failed after provider I/O began")?,
                upper: Some(unknown_boundary(
                    "the read failed after provider I/O began",
                )?),
            });
            plane.state.terminal_failure = Some(message);
            Ok(None)
        }
    }
}

/// Return the permit before deciding anything else. A failed read still consumed its request.
fn settle_read(
    ledger: &mut BudgetLedger,
    permit: joshi_supervisor::BudgetPermit,
    claim: AttemptBudgetClaim,
    outcome: Result<CapturedRead, Box<dyn Error>>,
    elapsed_ms: u64,
) -> Result<SettledRead, Box<dyn Error>> {
    let captured = match outcome {
        Ok(captured) => captured,
        Err(error) => {
            ledger.settle(permit, conservative_usage(claim, 0, elapsed_ms))?;
            return Ok(SettledRead::Failed {
                reason: "provider_read_failed",
                message: error.to_string(),
            });
        }
    };
    let body_bytes = u64::try_from(captured.frame.body.len())?;
    if let Err(error) = ensure_provider_accepted(&captured) {
        ledger.settle(permit, conservative_usage(claim, body_bytes, elapsed_ms))?;
        return Ok(SettledRead::Failed {
            reason: "provider_rejected_read",
            message: error.to_string(),
        });
    }
    ledger.settle(
        permit,
        AttemptBudgetUsage {
            requests: 1,
            pages: 1,
            ingress_bytes: body_bytes,
            // The durable cost of this page is bounded by the physical derivation the claim
            // reserved; the exact retained length is reported by the commit receipt.
            durable_bytes: claim.maximum_durable_bytes.min(retained_bound(body_bytes)?),
            provider_credits: 0,
            elapsed_ms,
        },
    )?;
    Ok(SettledRead::Retained(Box::new(captured)))
}

/// Worst-case physical local cost of retaining one response body of this length.
fn retained_bound(body_bytes: u64) -> Result<u64, Box<dyn Error>> {
    Ok(ingest_physical_bound(body_bytes)?.max_segment_bytes())
}

/// The pre-I/O claim for one census read, derived from the encoders rather than guessed.
fn attempt_claim() -> Result<AttemptBudgetClaim, Box<dyn Error>> {
    Ok(AttemptBudgetClaim {
        requests: 1,
        pages: 1,
        maximum_ingress_bytes: CENSUS_MAX_RESPONSE_BYTES,
        maximum_durable_bytes: retained_bound(CENSUS_MAX_RESPONSE_BYTES)?,
        maximum_provider_credits: 0,
        maximum_ingress_bytes_per_second: None,
        maximum_elapsed_ms: ATTEMPT_MAX_ELAPSED_MS,
    })
}

const fn conservative_usage(
    claim: AttemptBudgetClaim,
    observed_bytes: u64,
    elapsed_ms: u64,
) -> AttemptBudgetUsage {
    AttemptBudgetUsage {
        requests: 1,
        pages: 1,
        ingress_bytes: observed_bytes,
        durable_bytes: 0,
        provider_credits: 0,
        elapsed_ms: if elapsed_ms > claim.maximum_elapsed_ms {
            claim.maximum_elapsed_ms
        } else {
            elapsed_ms
        },
    }
}

/// One committed batch and the receipt fields worth rendering for it.
struct CommittedRead {
    batch: AdmissionBatch,
    rendered: Value,
}

fn commit_read(
    store: &mut SqliteStore,
    read: &CapturedRead,
    context: &CensusContext<'_>,
    sequence: u64,
) -> Result<CommittedRead, Box<dyn Error>> {
    let namespace = context.namespace();
    let clock_id = census_clock_id();
    let persisted_at = now_utc()?;
    let batch = source_frames(
        vec![SourceFrameInput {
            frame: read.frame.clone(),
            context: evidence_context(read, &namespace, &clock_id, persisted_at)?,
        }],
        Vec::new(),
        Vec::new(),
        StableString::new(format!("{}-read-{sequence:04}", context.run_id))?,
        now_utc()?,
        StableString::new(clock_id)?,
        elapsed_nanos(context.process_start)?,
    )?;
    let receipt = batch.commit(store)?;
    Ok(CommittedRead {
        rendered: rendered_commit(&receipt),
        batch,
    })
}

fn seal_to_spool(
    supervisor: &mut Supervisor,
    reservation: &joshi_supervisor::AttemptReservation,
    batch: &AdmissionBatch,
    registration_bytes: &[u8],
) -> Result<String, Box<dyn Error>> {
    let exact = serde_json::to_vec(&batch.store.evidence)?;
    let pending = prepare_evidence_batch(
        reservation.clone(),
        &batch.store.evidence,
        exact,
        CENSUS_POLICY_CONTRACT,
        registration_bytes.to_vec(),
    )?;
    supervisor
        .try_enqueue(pending)
        .map_err(|_| "census spool queue is saturated")?;
    let receipt = supervisor
        .drain_one(now_utc()?)?
        .ok_or("census spool drain produced no receipt")?;
    Ok(receipt.segment_id)
}

/// Coverage rows, once every read has resolved: what was observed, and every bounded edge.
struct CommittedCoverage {
    commit: Value,
    windows: Vec<Value>,
    gaps: Vec<Value>,
}

fn commit_coverage(
    store: &mut SqliteStore,
    supervisor: &mut Supervisor,
    state: &mut CensusState,
    context: &CensusContext<'_>,
    registration_bytes: &[u8],
) -> Result<CommittedCoverage, Box<dyn Error>> {
    if state.commits.is_empty() {
        // Coverage rows reference a registered source. Nothing was retained, so nothing is
        // claimed: the receipt says so instead of inventing a window over an empty run.
        return Ok(CommittedCoverage {
            commit: json!({
                "committed": false,
                "because": "no provider read reached the catalog, so no source is registered to scope coverage against",
            }),
            windows: Vec::new(),
            gaps: Vec::new(),
        });
    }
    let available_at = now_utc()?;
    let built = build_windows(state, context, available_at)?;
    let (windows, run_coverage_id, program_windows) =
        (built.windows, built.run_coverage_id, built.program_windows);

    let mut gaps: Vec<CoverageGap> = Vec::new();
    for (ordinal, detected) in state.gaps.iter().enumerate() {
        let coverage_id = detected
            .subject
            .as_ref()
            .and_then(|subject| program_windows.get(subject))
            .unwrap_or(&run_coverage_id)
            .clone();
        gaps.push(CoverageGap {
            gap_id: CoverageId::new(format!("gap-{}-{ordinal:03}", context.run_id))?,
            coverage_id,
            scope: coverage_scope(detected.subject.as_deref())?,
            lower: detected.lower.clone(),
            upper: detected.upper.clone(),
            reason: OpenVariant::known(detected.reason.clone())?,
            detected_at: available_at,
        });
    }

    let rendered_windows = windows.iter().map(rendered_window).collect::<Vec<_>>();
    let rendered_gaps = gaps.iter().map(rendered_gap).collect::<Vec<_>>();
    let drafts = windows
        .into_iter()
        .map(EvidenceDraft::CoverageWindow)
        .chain(gaps.into_iter().map(EvidenceDraft::CoverageGap))
        .collect::<Vec<_>>();
    let clock_id = census_clock_id();
    let batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(format!("{}-coverage", context.run_id))?,
        drafts,
        source_events: Vec::new(),
        cursor_advances: Vec::new(),
        // The source row this coverage references is registered by the committed read batches;
        // `commit_coverage` refuses to run before one exists rather than registering a second
        // configuration for the same source identity.
        registrations: Vec::new(),
        policy: AdmissionPolicy::public_source()?,
        committed_at: now_utc()?,
        writer_clock_id: StableString::new(clock_id)?,
        committed_mono_ns: elapsed_nanos(context.process_start)?,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })?;
    let receipt = batch.commit(store)?;

    // The coverage batch is resolved through the same durable path as every read: its own
    // pre-I/O-shaped reservation, sealed into the spool, never left pending.
    let reservation = supervisor.reserve(
        ReservationRequest {
            source_key: SourceKey::new(DOMAIN_SOURCE_ID)?,
            operation_key: OperationKey::new("censusCoverageClosure")?,
            kind: AttemptKind::ControlWrite,
            scope: coverage_scope(None)?,
            lower: Boundary::Wall {
                value: run_lower(context)?,
            },
            protection: ProtectionProfile::PublicIntegrity {
                domain: ProtectionDomainId::new(PROTECTION_DOMAIN)?,
            },
            run: None,
            execution_claim: None,
            provider_plan: None,
        },
        now_utc()?,
    )?;
    let segment = seal_to_spool(supervisor, &reservation, &batch, registration_bytes)?;
    state.reservations.push(reservation_summary(
        &reservation,
        "censusCoverageClosure",
        &format!("durable_spool_segment:{segment}"),
    ));
    Ok(CommittedCoverage {
        commit: rendered_commit(&receipt),
        windows: rendered_windows,
        gaps: rendered_gaps,
    })
}

/// The coverage windows this run can defend, and the identities its gaps hang from.
struct BuiltWindows {
    windows: Vec<CoverageWindow>,
    run_coverage_id: CoverageId,
    program_windows: BTreeMap<String, CoverageId>,
}

/// Bound each window by what the provider actually returned, never by a wall-clock guess about
/// the chain. The per-program bounds are the exact newest and oldest signatures of its page; the
/// run-wide window is a local interval and says so in its clock tag.
fn build_windows(
    state: &CensusState,
    context: &CensusContext<'_>,
    available_at: UtcTimestamp,
) -> Result<BuiltWindows, Box<dyn Error>> {
    let run_window = CoverageWindow {
        coverage_id: CoverageId::new(format!("coverage-{}-run", context.run_id))?,
        scope: coverage_scope(None)?,
        lower: Boundary::Wall {
            value: run_lower(context)?,
        },
        upper: Some(Boundary::Wall {
            value: available_at,
        }),
        state: OpenVariant::known("bounded_local_census_interval")?,
        available_at,
    };
    let run_coverage_id = run_window.coverage_id.clone();
    let mut windows = vec![run_window];
    let mut program_windows: BTreeMap<String, CoverageId> = BTreeMap::new();
    for (index, program) in state.programs.iter().enumerate() {
        if !program.reached {
            continue;
        }
        let coverage_id =
            CoverageId::new(format!("coverage-{}-program-{index:02}", context.run_id))?;
        let (lower, upper, observed) = if let (Some(newest), Some(oldest)) =
            (program.listed.first(), program.listed.last())
        {
            (
                Boundary::SourceCursor {
                    value: StableString::new(format!("signature:{}", oldest.signature))?,
                },
                Some(Boundary::SourceCursor {
                    value: StableString::new(format!("signature:{}", newest.signature))?,
                }),
                true,
            )
        } else {
            (
                unknown_boundary("provider returned no signature for this address in this page")?,
                None,
                false,
            )
        };
        program_windows.insert(program.address.clone(), coverage_id.clone());
        windows.push(CoverageWindow {
            coverage_id,
            scope: coverage_scope(Some(&program.address))?,
            lower,
            upper,
            state: OpenVariant::known(if observed {
                "bounded_signature_page_observed"
            } else {
                "empty_signature_page_observed"
            })?,
            available_at,
        });
    }
    Ok(BuiltWindows {
        windows,
        run_coverage_id,
        program_windows,
    })
}

fn record_sampling_gaps(state: &mut CensusState) -> Result<(), Box<dyn Error>> {
    let mut detected = Vec::new();
    for program in &state.programs {
        if !program.reached {
            continue;
        }
        if program.page_was_full
            && let Some(oldest) = program.listed.last()
        {
            detected.push(DetectedGap {
                subject: Some(program.address.clone()),
                reason: "signature_page_hit_its_requested_limit".to_owned(),
                lower: unknown_boundary("no older signature cursor was requested")?,
                upper: Some(Boundary::SourceCursor {
                    value: StableString::new(format!("signature:{}", oldest.signature))?,
                }),
            });
        }
        if let (Some(newest), Some(oldest)) = (program.unsampled.first(), program.unsampled.last())
        {
            detected.push(DetectedGap {
                subject: Some(program.address.clone()),
                reason: "listed_signatures_were_not_hydrated".to_owned(),
                lower: Boundary::SourceCursor {
                    value: StableString::new(format!("signature:{}", oldest.signature))?,
                },
                upper: Some(Boundary::SourceCursor {
                    value: StableString::new(format!("signature:{}", newest.signature))?,
                }),
            });
        }
    }
    state.gaps.extend(detected);
    Ok(())
}

fn record_remaining_program_gaps(
    state: &mut CensusState,
    from_index: usize,
) -> Result<(), Box<dyn Error>> {
    let mut detected = Vec::new();
    for program in state.programs.iter().skip(from_index + 1) {
        detected.push(DetectedGap {
            subject: Some(program.address.clone()),
            reason: "program_not_reached_before_census_stopped".to_owned(),
            lower: unknown_boundary("no signature page was requested for this program")?,
            upper: Some(unknown_boundary(
                "no signature page was requested for this program",
            )?),
        });
    }
    state.gaps.extend(detected);
    record_sampling_gaps(state)
}

fn absorb_transaction(
    state: &mut CensusState,
    program_index: usize,
    page_program: &str,
    signature: &str,
    body: &[u8],
) -> Result<(), Box<dyn Error>> {
    let Ok(value) = serde_json::from_slice::<Value>(body) else {
        return Ok(());
    };
    let Some(result) = value.get("result").filter(|value| !value.is_null()) else {
        // A signature the provider listed and then did not return is an exact, single-signature
        // hole, not an absence of activity.
        state.gaps.push(DetectedGap {
            subject: Some(page_program.to_owned()),
            reason: "listed_signature_returned_no_transaction".to_owned(),
            lower: Boundary::SourceCursor {
                value: StableString::new(format!("signature:{signature}"))?,
            },
            upper: Some(Boundary::SourceCursor {
                value: StableString::new(format!("signature:{signature}"))?,
            }),
        });
        return Ok(());
    };
    state.programs[program_index].transactions_with_result = state.programs[program_index]
        .transactions_with_result
        .saturating_add(1);
    let slot = result.get("slot").and_then(Value::as_u64);
    let mints = transaction_mints(result);
    // Every censused program is checked against the retained keys, not just the one whose page
    // listed this signature. The page is how the transaction was found; the keys are what the
    // bytes say about it, and only the second is a relation a later reader can re-derive.
    let addresses: Vec<String> = state
        .programs
        .iter()
        .map(|program| program.address.clone())
        .collect();
    for address in &addresses {
        let relation = program_relation(result, address);
        if relation == ProgramRelation::AbsentFromAccountKeys {
            continue;
        }
        for mint in &mints {
            state
                .mints
                .entry(mint.clone())
                .or_default()
                .record(signature, address, relation, slot);
        }
    }
    if program_relation(result, page_program) == ProgramRelation::AbsentFromAccountKeys {
        // The provider returned this signature for this address and the body does not name the
        // address among its resolved keys. Nothing is asserted either way; the exact signature is
        // recorded as a hole so the discrepancy is visible rather than silently dropped.
        state.gaps.push(DetectedGap {
            subject: Some(page_program.to_owned()),
            reason: "returned_transaction_does_not_name_the_program_in_its_resolved_keys"
                .to_owned(),
            lower: Boundary::SourceCursor {
                value: StableString::new(format!("signature:{signature}"))?,
            },
            upper: Some(Boundary::SourceCursor {
                value: StableString::new(format!("signature:{signature}"))?,
            }),
        });
    }
    Ok(())
}

/// Every mint named by the retained token-balance rows. Nothing is inferred from anything else.
fn transaction_mints(result: &Value) -> BTreeSet<String> {
    let mut mints = BTreeSet::new();
    for field in ["preTokenBalances", "postTokenBalances"] {
        let Some(rows) = result
            .pointer("/meta")
            .and_then(|meta| meta.get(field))
            .and_then(Value::as_array)
        else {
            continue;
        };
        for row in rows {
            if let Some(mint) = row.get("mint").and_then(Value::as_str) {
                mints.insert(mint.to_owned());
            }
        }
    }
    mints
}

/// Resolve the transaction's account keys exactly as the retained body states them, then say only
/// what those bytes support about this program's involvement.
fn program_relation(result: &Value, program: &str) -> ProgramRelation {
    let mut keys: Vec<&str> = Vec::new();
    if let Some(rows) = result
        .pointer("/transaction/message/accountKeys")
        .and_then(Value::as_array)
    {
        keys.extend(rows.iter().filter_map(Value::as_str));
    }
    for field in ["writable", "readonly"] {
        if let Some(rows) = result
            .pointer("/meta/loadedAddresses")
            .and_then(|loaded| loaded.get(field))
            .and_then(Value::as_array)
        {
            keys.extend(rows.iter().filter_map(Value::as_str));
        }
    }
    if !keys.contains(&program) {
        return ProgramRelation::AbsentFromAccountKeys;
    }
    let mut instruction_indices: Vec<u64> = Vec::new();
    if let Some(rows) = result
        .pointer("/transaction/message/instructions")
        .and_then(Value::as_array)
    {
        instruction_indices.extend(
            rows.iter()
                .filter_map(|row| row.get("programIdIndex").and_then(Value::as_u64)),
        );
    }
    if let Some(groups) = result
        .pointer("/meta/innerInstructions")
        .and_then(Value::as_array)
    {
        for group in groups {
            if let Some(rows) = group.get("instructions").and_then(Value::as_array) {
                instruction_indices.extend(
                    rows.iter()
                        .filter_map(|row| row.get("programIdIndex").and_then(Value::as_u64)),
                );
            }
        }
    }
    let mut unresolved = false;
    for index in instruction_indices {
        match usize::try_from(index)
            .ok()
            .and_then(|index| keys.get(index))
        {
            Some(key) if *key == program => return ProgramRelation::InstructionProgramId,
            Some(_) => {}
            None => unresolved = true,
        }
    }
    if unresolved {
        ProgramRelation::UnresolvedInstructionIndex
    } else {
        ProgramRelation::AccountKeyOnly
    }
}

fn listed_signatures(body: &[u8]) -> Vec<ListedSignature> {
    let Ok(value) = serde_json::from_slice::<Value>(body) else {
        return Vec::new();
    };
    value
        .get("result")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|row| {
                    Some(ListedSignature {
                        signature: row.get("signature").and_then(Value::as_str)?.to_owned(),
                        slot: row.get("slot").and_then(Value::as_u64),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

fn coverage_scope(subject: Option<&str>) -> Result<CoverageScope, Box<dyn Error>> {
    Ok(CoverageScope {
        source_id: joshi_domain::SourceId::new(DOMAIN_SOURCE_ID)?,
        family: OpenVariant::known(COVERAGE_FAMILY)?,
        subject: subject.map(StableString::new).transpose()?,
    })
}

fn unknown_boundary(reason: &str) -> Result<Boundary, Box<dyn Error>> {
    Ok(Boundary::Unknown {
        reason: OpenVariant::known(reason)?,
    })
}

fn rendered_commit(receipt: &PublicStoreReceiptV1) -> Value {
    json!({
        "batchId": receipt.batch_id,
        "commitSeq": receipt.commit_seq,
        "status": receipt.status,
        "observations": receipt.admitted.observations,
        "coverageWindows": receipt.admitted.coverage_windows,
        "coverageGaps": receipt.admitted.coverage_gaps,
        "retainedPayloadBytes": receipt.admitted.raw_bytes,
        "batchDigest": receipt.batch_digest,
        "storeAdmissionDigest": receipt.store_admission_digest,
        "gapOutcomes": receipt.gap_outcomes,
    })
}

fn rendered_window(window: &CoverageWindow) -> Value {
    json!({
        "coverageId": window.coverage_id.as_str(),
        "family": window.scope.family.discriminator.as_str(),
        "subject": window.scope.subject.as_ref().map(StableString::as_str),
        "state": window.state.discriminator.as_str(),
        "lower": window.lower,
        "upper": window.upper,
    })
}

fn rendered_gap(gap: &CoverageGap) -> Value {
    json!({
        "gapId": gap.gap_id.as_str(),
        "coverageId": gap.coverage_id.as_str(),
        "subject": gap.scope.subject.as_ref().map(StableString::as_str),
        "reason": gap.reason.discriminator.as_str(),
        "lower": gap.lower,
        "upper": gap.upper,
    })
}

fn reservation_summary(
    reservation: &joshi_supervisor::AttemptReservation,
    operation: &str,
    resolution: &str,
) -> Value {
    json!({
        "reservationId": reservation.reservation_id.as_str(),
        "operation": operation,
        "generation": reservation.generation.get(),
        "attemptOrdinal": reservation.attempt_ordinal,
        "authority": reservation.authority,
        "resolution": resolution,
    })
}

fn program_denominators(state: &CensusState) -> Vec<Value> {
    state
        .programs
        .iter()
        .map(|program| {
            json!({
                "programId": program.address,
                "signaturePageRequested": program.reached,
                "signaturesListed": program.listed.len(),
                "pageHitItsRequestedLimit": program.page_was_full,
                "transactionsRequested": program.sampled.len(),
                "transactionsWithResult": program.transactions_with_result,
                "signaturesListedButNotHydrated": program.unsampled.len(),
                "oldestListedSignature": program.listed.last().map(|row| row.signature.clone()),
                "newestListedSignature": program.listed.first().map(|row| row.signature.clone()),
                "lowestListedSlot": program.listed.iter().filter_map(|row| row.slot).min(),
                "highestListedSlot": program.listed.iter().filter_map(|row| row.slot).max(),
            })
        })
        .collect()
}

fn rendered_mints(state: &CensusState) -> Vec<Value> {
    state
        .mints
        .iter()
        .map(|(mint, census)| {
            json!({
                "mint": mint,
                "relation": SUBJECT_RELATION,
                "signatureCount": census.signatures.len(),
                "programs": census.programs,
                "programRelations": census.relations,
                "lowestObservedSlot": census.lowest_slot,
                "highestObservedSlot": census.highest_slot,
            })
        })
        .collect()
}

fn explicit_unknowns(state: &CensusState) -> Vec<Value> {
    let mut unknowns = vec![
        json!({
            "field": "mintTotalActivity",
            "value": "unknown",
            "because": "the census read a bounded signature page; it observed no denominator for a mint's whole history",
        }),
        json!({
            "field": "mintEconomicEvent",
            "value": "unknown",
            "because": "a token-balance row states a mint touched a transaction, not that it launched, migrated, traded or had a price",
        }),
        json!({
            "field": "budget.used.durableBytes",
            "value": "derived_worst_case_bound_not_measurement",
            "because": "settlement precedes the commit that would measure retention, so each read is charged the physical bound its response length derives",
        }),
        json!({
            "field": "observationFinality",
            "value": "requested_finalized_not_restated_by_body",
            "because": "commitment is a property of the request; no retained response body restates it",
        }),
    ];
    if state.tip_slot.is_none() {
        unknowns.push(json!({
            "field": "chainTipSlot",
            "value": "unknown",
            "because": "the getSlot response did not carry a scalar result this build could read",
        }));
    }
    if state
        .mints
        .values()
        .any(|census| census.relations.contains("unresolved_instruction_index"))
    {
        unknowns.push(json!({
            "field": "programInvocation",
            "value": "unresolved_instruction_index",
            "because": "an instruction named a program account index this build could not resolve from the retained keys",
        }));
    }
    unknowns
}

fn response_bytes(state: &CensusState) -> u64 {
    state
        .reads
        .iter()
        .map(|read| u64::try_from(read.frame.body.len()).unwrap_or(u64::MAX))
        .sum()
}

fn validated_programs(options: &CensusOptions) -> Result<Vec<String>, Box<dyn Error>> {
    if options.programs.is_empty() || options.programs.len() > MAX_PROGRAMS {
        return Err(format!("--program must be given between 1 and {MAX_PROGRAMS} times").into());
    }
    for program in &options.programs {
        validate_base58_address(program, "--program")?;
    }
    let unique = options.programs.iter().collect::<BTreeSet<_>>();
    if unique.len() != options.programs.len() {
        return Err("--program was repeated; each program is censused once".into());
    }
    if options.signature_limit == 0 || options.signature_limit > MAX_SIGNATURE_LIMIT {
        return Err(
            format!("--signature-limit must be between 1 and {MAX_SIGNATURE_LIMIT}").into(),
        );
    }
    let minimum = u32::try_from(options.programs.len())
        .unwrap_or(u32::MAX)
        .saturating_add(1);
    if options.max_requests < minimum {
        return Err(format!(
            "--max-requests must allow at least {minimum} requests: one tip read and one signature page per program"
        )
        .into());
    }
    Ok(options.programs.clone())
}

fn run_budget_limits(max_requests: u32) -> Result<RunBudgetLimits, Box<dyn Error>> {
    let requests = u64::from(max_requests);
    let claim = attempt_claim()?;
    Ok(RunBudgetLimits {
        maximum_requests: requests,
        maximum_pages: requests,
        maximum_ingress_bytes: requests.saturating_mul(claim.maximum_ingress_bytes),
        maximum_durable_bytes: requests.saturating_mul(claim.maximum_durable_bytes),
        maximum_provider_credits: 0,
        maximum_ingress_bytes_per_second: None,
        maximum_elapsed_ms: RUN_MAX_ELAPSED_MS,
        maximum_in_flight_attempts: 1,
        maximum_in_flight_elapsed_overshoot_ms: ATTEMPT_MAX_ELAPSED_MS,
    })
}

fn census_supervisor_config(root: &Path) -> SupervisorConfig {
    SupervisorConfig {
        spool: joshi_spool::SpoolConfig {
            root: root.join("supervisor").join("spool"),
            max_segment_bytes: 32 * 1024 * 1024,
            max_entries_per_segment: 256,
            max_total_bytes: 8 * 1024 * 1024 * 1024,
            control_reserve_bytes: 64 * 1024 * 1024,
            max_transfer_chunk_bytes: 1024 * 1024,
        },
        root: root.join("supervisor"),
        queue: joshi_supervisor::QueueLimits::default(),
        retry: joshi_supervisor::RetryPolicy::default(),
        shutdown_deadline: std::time::Duration::from_secs(30),
        maximum_spool_bytes_per_utc_day: 1024 * 1024 * 1024,
    }
}

fn write_run_registration(
    root: &Path,
    run_id: &str,
    bytes: &[u8],
) -> Result<PathBuf, Box<dyn Error>> {
    let directory = root.join("census-runs");
    fs::create_dir_all(&directory)?;
    let path = directory.join(format!("{run_id}.json"));
    fs::write(&path, bytes)?;
    Ok(path)
}

fn census_run_id() -> Result<String, Box<dyn Error>> {
    Ok(format!(
        "census-{}-{}",
        unix_millis(OffsetDateTime::now_utc())?,
        std::process::id()
    ))
}

fn run_lower(context: &CensusContext<'_>) -> Result<UtcTimestamp, Box<dyn Error>> {
    let elapsed =
        time::Duration::nanoseconds(i64::try_from(elapsed_nanos(context.process_start)?)?);
    let started = OffsetDateTime::now_utc()
        .checked_sub(elapsed)
        .ok_or("census start instant underflowed")?;
    let nanosecond = started.nanosecond();
    Ok(UtcTimestamp::new(
        started.replace_nanosecond(nanosecond - nanosecond % 1_000)?,
    )?)
}

fn elapsed_millis(process_start: Instant) -> Result<u64, Box<dyn Error>> {
    Ok(u64::try_from(process_start.elapsed().as_millis())?)
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("sha256:{:x}", hasher.finalize())
}

/// Reopen a census catalog read-only and re-derive the whole census from the retained bytes.
///
/// Nothing here reads the receipt the run printed. The programs come from the stored coverage
/// windows, the mints come from the stored provider bodies, and the gaps come from the stored gap
/// rows. If the run's numbers and this rendering disagree, this rendering is the one the store
/// can defend.
///
/// This renders the whole catalog, not one run. A catalog holding several census runs renders all
/// of their observations together; `observationsScanned` is the exact denominator it used.
///
/// # Errors
///
/// Returns an error when the catalog is absent, is not a Joshi catalog, or holds no census
/// coverage window.
pub(crate) fn census_readback(root: &Path) -> Result<String, Box<dyn Error>> {
    let config = catalog_config(root)?;
    let schema = {
        let store = SqliteStore::open(config.clone(), StoreMode::ReadOnly)?;
        store.catalog_schema()?
    };
    let connection = Connection::open_with_flags(
        &config.catalog_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.pragma_update(None, "query_only", "ON")?;

    let mut windows = Vec::new();
    let mut programs: BTreeSet<String> = BTreeSet::new();
    {
        let mut statement = connection.prepare(
            "SELECT w.coverage_id, w.source_id, w.coverage_level, w.opened_commit_seq,
                    c.scope_subject, c.lower_boundary_json, c.upper_boundary_json, c.state
             FROM coverage_window w JOIN coverage_window_contract c USING(coverage_id)
             WHERE w.scope_kind = ?1
             ORDER BY w.coverage_id",
        )?;
        let mut rows = statement.query([COVERAGE_FAMILY])?;
        while let Some(row) = rows.next()? {
            let subject: Option<String> = row.get(4)?;
            if let Some(subject) = subject.clone() {
                programs.insert(subject);
            }
            windows.push(json!({
                "coverageId": row.get::<_, String>(0)?,
                "sourceId": row.get::<_, String>(1)?,
                "coverageLevel": row.get::<_, String>(2)?,
                "openedCommitSeq": row.get::<_, i64>(3)?,
                "subject": subject,
                "lower": json_boundary(&row.get::<_, String>(5)?),
                "upper": row.get::<_, Option<String>>(6)?.as_deref().map(json_boundary),
                "state": row.get::<_, String>(7)?,
            }));
        }
    }
    if windows.is_empty() {
        return Err("catalog holds no market_census coverage window to read back".into());
    }

    let mut gaps = Vec::new();
    {
        let mut statement = connection.prepare(
            "SELECT g.gap_id, g.coverage_id, g.cause_code, g.severity, g.detected_commit_seq,
                    c.scope_subject, c.lower_boundary_json, c.upper_boundary_json
             FROM coverage_gap g JOIN coverage_gap_contract c USING(gap_id)
             WHERE c.scope_family = ?1
             ORDER BY g.gap_id",
        )?;
        let mut rows = statement.query([COVERAGE_FAMILY])?;
        while let Some(row) = rows.next()? {
            gaps.push(json!({
                "gapId": row.get::<_, String>(0)?,
                "coverageId": row.get::<_, String>(1)?,
                "reason": row.get::<_, String>(2)?,
                "severity": row.get::<_, String>(3)?,
                "detectedCommitSeq": row.get::<_, i64>(4)?,
                "subject": row.get::<_, Option<String>>(5)?,
                "lower": json_boundary(&row.get::<_, String>(6)?),
                "upper": row.get::<_, Option<String>>(7)?.as_deref().map(json_boundary),
            }));
        }
    }

    let derived = derive_mints_from_store(&connection, &config, &programs)?;
    let rendered = json!({
        "contract": CENSUS_READBACK_CONTRACT,
        "catalogRoot": root.display().to_string(),
        "catalogSchema": schema.as_str(),
        "subjectRelation": SUBJECT_RELATION,
        "programsFromCoverageWindows": programs,
        "observationsScanned": derived.observations_scanned,
        "transactionBodiesFound": derived.transaction_bodies,
        "coverageWindows": windows,
        "coverageGaps": gaps,
        "mints": derived.mints,
    });
    Ok(serde_json::to_string_pretty(&rendered)?)
}

struct DerivedMints {
    observations_scanned: u64,
    transaction_bodies: u64,
    mints: Vec<Value>,
}

fn derive_mints_from_store(
    connection: &Connection,
    config: &joshi_store::StoreConfig,
    programs: &BTreeSet<String>,
) -> Result<DerivedMints, Box<dyn Error>> {
    let mut statement = connection.prepare(
        "SELECT b.inline_bytes, b.relative_path
         FROM observation o JOIN blob b ON b.blob_id = o.blob_id
         ORDER BY o.commit_seq, o.intra_commit_seq",
    )?;
    let mut rows = statement.query([])?;
    let mut observations_scanned = 0_u64;
    let mut transaction_bodies = 0_u64;
    let mut mints: BTreeMap<String, MintCensus> = BTreeMap::new();
    while let Some(row) = rows.next()? {
        observations_scanned = observations_scanned.saturating_add(1);
        let inline: Option<Vec<u8>> = row.get(0)?;
        let relative: Option<String> = row.get(1)?;
        let payload = retained_payload(config, inline.as_ref(), relative.as_deref())?;
        let Ok(envelope) = serde_json::from_slice::<joshi_sources::RetainedFrameEnvelope>(&payload)
        else {
            continue;
        };
        let Ok(body) = serde_json::from_slice::<Value>(&envelope.body) else {
            continue;
        };
        let Some(result) = body.get("result").filter(|value| !value.is_null()) else {
            continue;
        };
        let Some(signature) = result
            .pointer("/transaction/signatures/0")
            .and_then(Value::as_str)
        else {
            continue;
        };
        transaction_bodies = transaction_bodies.saturating_add(1);
        let slot = result.get("slot").and_then(Value::as_u64);
        let observed = transaction_mints(result);
        if observed.is_empty() {
            continue;
        }
        for program in programs {
            let relation = program_relation(result, program);
            if relation == ProgramRelation::AbsentFromAccountKeys {
                continue;
            }
            for mint in &observed {
                mints
                    .entry(mint.clone())
                    .or_default()
                    .record(signature, program, relation, slot);
            }
        }
    }
    Ok(DerivedMints {
        observations_scanned,
        transaction_bodies,
        mints: mints
            .iter()
            .map(|(mint, census)| {
                json!({
                    "mint": mint,
                    "signatureCount": census.signatures.len(),
                    "programs": census.programs,
                    "programRelations": census.relations,
                    "lowestObservedSlot": census.lowest_slot,
                    "highestObservedSlot": census.highest_slot,
                })
            })
            .collect(),
    })
}

fn json_boundary(encoded: &str) -> Value {
    serde_json::from_str(encoded).unwrap_or_else(|_| Value::String(encoded.to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use bytes::Bytes;
    use joshi_sources::{
        ADAPTER_CONTRACT_VERSION, ContentType, FrameDirection, RawSourceFrame, SourceId, Transport,
        UnixMillis,
    };

    const FEE_PAYER: &str = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh";
    const MINT: &str = "5z3EqYQo9HiCEs3R84RCDMu2n7anpDMxRhdK8PSWmrRC";
    const OTHER: &str = "So11111111111111111111111111111111111111112";
    const SIGNATURE_ONE: &str =
        "5oJ9nAmHqZJTgZBpJhLh8pKxHhPvZUnaEVc1jqrpAF8s7Wd2qhKzvE8YWZ4Wc7CqzVFa6JzZq3s9d8mFa1BcDeF2";
    const SIGNATURE_TWO: &str =
        "3xLpTwQ7bYaXk9RgHUJZsMLm2NvKCEr4B6hVwPZ8dQFyTgS5nA1jKcHRuXWm7EYb9dVvJqLpZs4TrCn2GkMdXyZ1";

    fn synthetic(method: SolanaReadMethod, sequence: u64, body: String) -> CapturedRead {
        CapturedRead {
            frame: RawSourceFrame {
                contract_version: ADAPTER_CONTRACT_VERSION.to_owned(),
                source: SourceId::HeliusHttp,
                transport: Transport::Http,
                stream_class: method.stream_class(),
                direction: FrameDirection::Inbound,
                content_type: ContentType::Json,
                received_at: UnixMillis(1_786_882_538_124),
                connection_epoch: 0,
                sequence,
                http_status: Some(200),
                safe_headers: Vec::new(),
                body: Bytes::from(body),
            },
            method,
            fingerprint_material: format!("method={};synthetic", method.as_str()),
            started_at_millis: 1_786_882_538_000,
            started_mono_ns: sequence * 1_000,
            received_mono_ns: sequence * 1_000 + 500,
            rate_limit: None,
            source_cursor: None,
        }
    }

    fn signature_page() -> String {
        json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                { "signature": SIGNATURE_ONE, "slot": 440_345_530, "err": Value::Null },
                { "signature": SIGNATURE_TWO, "slot": 440_345_529, "err": Value::Null }
            ]
        })
        .to_string()
    }

    fn transaction_body(program: &str) -> String {
        json!({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "slot": 440_345_530,
                "blockTime": 1_786_882_500,
                "transaction": {
                    "signatures": [SIGNATURE_ONE],
                    "message": {
                        "accountKeys": [FEE_PAYER, program, OTHER],
                        "instructions": [{ "programIdIndex": 1, "accounts": [0], "data": "3Bxs" }]
                    }
                },
                "meta": {
                    "err": Value::Null,
                    "innerInstructions": [],
                    "preTokenBalances": [{ "accountIndex": 0, "mint": MINT }],
                    "postTokenBalances": [{ "accountIndex": 0, "mint": MINT }]
                }
            }
        })
        .to_string()
    }

    fn census_options(root: &Path) -> CensusOptions {
        CensusOptions {
            root: root.to_path_buf(),
            programs: vec![PUMP_PROGRAM.to_owned()],
            signature_limit: 2,
            transactions_per_program: 1,
            max_requests: 8,
            key_file: PathBuf::from("/nonexistent-key-never-read-in-this-test"),
        }
    }

    /// The whole census path without a socket: exact frames become durable observations under
    /// real supervisor reservations, coverage and gaps commit with exact boundaries, and a
    /// read-only reopen re-derives the same mint, the same count and the same gaps from the
    /// store alone.
    #[test]
    #[allow(clippy::too_many_lines)] // One test walks one whole census; splitting it hides it.
    fn synthetic_frames_reach_the_catalog_and_the_census_reads_back_from_the_store() {
        let root = tempfile::tempdir().expect("temporary catalog root");
        let options = census_options(root.path());
        let programs = validated_programs(&options).expect("programs validate");
        let run_id = "census-test-0001".to_owned();
        let registration_bytes =
            b"{\"contract\":\"joshi.collector.census_run_registration.v1\"}".to_vec();
        let context = CensusContext {
            options: &options,
            programs: &programs,
            run_id: &run_id,
            registration_bytes: &registration_bytes,
            process_start: Instant::now(),
        };
        let mut store = open_catalog(root.path(), StoreMode::SingleWriter).expect("catalog opens");
        store
            .migrate(now_utc().expect("clock"))
            .expect("migrations");
        let mut supervisor =
            Supervisor::open(census_supervisor_config(root.path())).expect("supervisor opens");
        supervisor
            .reconcile_startup(now_utc().expect("clock"))
            .expect("startup reconciles");

        let mut state = CensusState {
            programs: vec![ProgramCensus::new(PUMP_PROGRAM.to_owned())],
            mints: BTreeMap::new(),
            gaps: Vec::new(),
            tip_slot: Some(440_345_531),
            reads: Vec::new(),
            commits: Vec::new(),
            reservations: Vec::new(),
            terminal_failure: None,
        };

        let reads = [
            synthetic(
                SolanaReadMethod::GetSignaturesForAddress,
                1,
                signature_page(),
            ),
            synthetic(
                SolanaReadMethod::GetTransaction,
                2,
                transaction_body(PUMP_PROGRAM),
            ),
        ];
        for (index, read) in reads.iter().enumerate() {
            let sequence = u64::try_from(index).expect("small index") + 1;
            let committed =
                commit_read(&mut store, read, &context, sequence).expect("read commits");
            let reservation = supervisor
                .reserve(
                    ReservationRequest {
                        source_key: SourceKey::new(DOMAIN_SOURCE_ID).expect("source key"),
                        operation_key: OperationKey::new("syntheticCensusRead")
                            .expect("operation key"),
                        kind: AttemptKind::HttpRequest,
                        scope: coverage_scope(Some(PUMP_PROGRAM)).expect("scope"),
                        lower: Boundary::Wall {
                            value: now_utc().expect("clock"),
                        },
                        protection: ProtectionProfile::PublicIntegrity {
                            domain: ProtectionDomainId::new(PROTECTION_DOMAIN).expect("domain"),
                        },
                        run: None,
                        execution_claim: None,
                        provider_plan: None,
                    },
                    now_utc().expect("clock"),
                )
                .expect("reservation is fsynced before the batch is sealed");
            seal_to_spool(
                &mut supervisor,
                &reservation,
                &committed.batch,
                &registration_bytes,
            )
            .expect("batch seals into the spool");
            state.commits.push(committed.rendered);
        }

        let listed = listed_signatures(&reads[0].frame.body);
        assert_eq!(listed.len(), 2);
        {
            let program = &mut state.programs[0];
            program.reached = true;
            program.page_was_full = true;
            program.sampled = vec![SIGNATURE_ONE.to_owned()];
            program.unsampled = listed.iter().skip(1).cloned().collect();
            program.listed = listed;
        }
        let body = reads[1].frame.body.clone();
        absorb_transaction(&mut state, 0, PUMP_PROGRAM, SIGNATURE_ONE, &body)
            .expect("transaction absorbs");
        assert_eq!(state.mints.len(), 1);
        assert_eq!(
            state.mints[MINT]
                .relations
                .iter()
                .copied()
                .collect::<Vec<_>>(),
            vec!["instruction_program_id"]
        );
        record_sampling_gaps(&mut state).expect("sampling gaps");

        let coverage = commit_coverage(
            &mut store,
            &mut supervisor,
            &mut state,
            &context,
            &registration_bytes,
        )
        .expect("coverage commits");
        assert_eq!(coverage.windows.len(), 2);
        assert_eq!(coverage.gaps.len(), 2);
        drop(store);
        drop(supervisor);

        // Reopen read-only. Nothing below reads the run's own numbers.
        let rendered = census_readback(root.path()).expect("census reads back");
        let value: Value = serde_json::from_str(&rendered).expect("readback is JSON");
        assert_eq!(value["programsFromCoverageWindows"][0], PUMP_PROGRAM);
        assert_eq!(value["mints"][0]["mint"], MINT);
        assert_eq!(value["mints"][0]["signatureCount"], 1);
        assert_eq!(value["mints"][0]["lowestObservedSlot"], 440_345_530_u64);
        assert_eq!(
            value["mints"][0]["programRelations"][0],
            "instruction_program_id"
        );
        assert_eq!(value["transactionBodiesFound"], 1);

        let windows = value["coverageWindows"].as_array().expect("windows");
        let program_window = windows
            .iter()
            .find(|window| window["subject"] == PUMP_PROGRAM)
            .expect("the program window survived the restart");
        assert_eq!(program_window["state"], "bounded_signature_page_observed");
        assert_eq!(program_window["lower"]["clock"], "source_cursor");
        assert_eq!(
            program_window["lower"]["value"],
            format!("signature:{SIGNATURE_TWO}")
        );
        assert_eq!(
            program_window["upper"]["value"],
            format!("signature:{SIGNATURE_ONE}")
        );

        let gaps = value["coverageGaps"].as_array().expect("gaps");
        let reasons: BTreeSet<&str> = gaps
            .iter()
            .filter_map(|gap| gap["reason"].as_str())
            .collect();
        assert!(reasons.contains("signature_page_hit_its_requested_limit"));
        assert!(reasons.contains("listed_signatures_were_not_hydrated"));
        let unhydrated = gaps
            .iter()
            .find(|gap| gap["reason"] == "listed_signatures_were_not_hydrated")
            .expect("the unhydrated tail is named exactly");
        assert_eq!(
            unhydrated["lower"]["value"],
            format!("signature:{SIGNATURE_TWO}")
        );
        assert_eq!(
            unhydrated["upper"]["value"],
            format!("signature:{SIGNATURE_TWO}")
        );
        let limit_gap = gaps
            .iter()
            .find(|gap| gap["reason"] == "signature_page_hit_its_requested_limit")
            .expect("the page limit is named exactly");
        assert_eq!(limit_gap["lower"]["clock"], "unknown");
        assert_eq!(
            limit_gap["upper"]["value"],
            format!("signature:{SIGNATURE_TWO}")
        );
    }

    /// The census says only what the retained transaction bytes support about a program.
    #[test]
    fn program_involvement_is_read_from_the_bytes_and_never_assumed() {
        let invoked: Value = serde_json::from_str(&transaction_body(PUMP_PROGRAM)).expect("json");
        let result = invoked.get("result").expect("result");
        assert_eq!(
            program_relation(result, PUMP_PROGRAM),
            ProgramRelation::InstructionProgramId
        );
        assert_eq!(
            program_relation(result, PUMPSWAP_PROGRAM),
            ProgramRelation::AbsentFromAccountKeys
        );

        let mentioned = json!({
            "transaction": {
                "message": {
                    "accountKeys": [FEE_PAYER, PUMP_PROGRAM],
                    "instructions": [{ "programIdIndex": 0 }]
                }
            }
        });
        assert_eq!(
            program_relation(&mentioned, PUMP_PROGRAM),
            ProgramRelation::AccountKeyOnly
        );

        let beyond = json!({
            "transaction": {
                "message": {
                    "accountKeys": [FEE_PAYER, PUMP_PROGRAM],
                    "instructions": [{ "programIdIndex": 9 }]
                }
            }
        });
        assert_eq!(
            program_relation(&beyond, PUMP_PROGRAM),
            ProgramRelation::UnresolvedInstructionIndex
        );
    }

    /// A signature the provider listed and then did not return is an exact hole, not an absence.
    #[test]
    fn a_missing_transaction_result_becomes_a_single_signature_gap() {
        let mut state = CensusState {
            programs: vec![ProgramCensus::new(PUMP_PROGRAM.to_owned())],
            mints: BTreeMap::new(),
            gaps: Vec::new(),
            tip_slot: None,
            reads: Vec::new(),
            commits: Vec::new(),
            reservations: Vec::new(),
            terminal_failure: None,
        };
        let body = json!({ "jsonrpc": "2.0", "id": 1, "result": Value::Null }).to_string();
        absorb_transaction(&mut state, 0, PUMP_PROGRAM, SIGNATURE_ONE, body.as_bytes())
            .expect("null result absorbs");
        assert!(state.mints.is_empty());
        assert_eq!(state.programs[0].transactions_with_result, 0);
        assert_eq!(state.gaps.len(), 1);
        assert_eq!(
            state.gaps[0].reason,
            "listed_signature_returned_no_transaction"
        );
        assert!(matches!(state.gaps[0].lower, Boundary::SourceCursor { .. }));
    }

    /// A program is related to a mint by the retained keys, not by which page listed the
    /// signature: the run's rendering and a later store-only rendering must derive the same set.
    #[test]
    fn every_censused_program_is_checked_against_the_retained_keys() {
        let mut state = CensusState {
            programs: vec![
                ProgramCensus::new(PUMP_PROGRAM.to_owned()),
                ProgramCensus::new(PUMPSWAP_PROGRAM.to_owned()),
            ],
            mints: BTreeMap::new(),
            gaps: Vec::new(),
            tip_slot: None,
            reads: Vec::new(),
            commits: Vec::new(),
            reservations: Vec::new(),
            terminal_failure: None,
        };
        let body = json!({
            "result": {
                "slot": 440_672_542,
                "transaction": {
                    "signatures": [SIGNATURE_ONE],
                    "message": {
                        "accountKeys": [FEE_PAYER, PUMP_PROGRAM, PUMPSWAP_PROGRAM],
                        "instructions": [{ "programIdIndex": 2 }]
                    }
                },
                "meta": {
                    "postTokenBalances": [{ "accountIndex": 0, "mint": MINT }]
                }
            }
        })
        .to_string();
        // Found through the Pump page, but the bytes also name PumpSwap.
        absorb_transaction(&mut state, 0, PUMP_PROGRAM, SIGNATURE_ONE, body.as_bytes())
            .expect("absorbs");
        let census = &state.mints[MINT];
        assert_eq!(
            census.programs.iter().cloned().collect::<Vec<_>>(),
            vec![PUMP_PROGRAM.to_owned(), PUMPSWAP_PROGRAM.to_owned()]
        );
        assert!(state.gaps.is_empty());
    }

    /// A returned transaction that does not name the address it was returned for is a visible
    /// discrepancy, never a silent attribution.
    #[test]
    fn a_transaction_that_does_not_name_its_page_program_becomes_a_gap() {
        let mut state = CensusState {
            programs: vec![ProgramCensus::new(PUMP_PROGRAM.to_owned())],
            mints: BTreeMap::new(),
            gaps: Vec::new(),
            tip_slot: None,
            reads: Vec::new(),
            commits: Vec::new(),
            reservations: Vec::new(),
            terminal_failure: None,
        };
        let body = json!({
            "result": {
                "slot": 1,
                "transaction": {
                    "signatures": [SIGNATURE_ONE],
                    "message": { "accountKeys": [FEE_PAYER], "instructions": [] }
                },
                "meta": { "postTokenBalances": [{ "accountIndex": 0, "mint": MINT }] }
            }
        })
        .to_string();
        absorb_transaction(&mut state, 0, PUMP_PROGRAM, SIGNATURE_ONE, body.as_bytes())
            .expect("absorbs");
        assert!(state.mints.is_empty());
        assert_eq!(state.gaps.len(), 1);
        assert_eq!(
            state.gaps[0].reason,
            "returned_transaction_does_not_name_the_program_in_its_resolved_keys"
        );
    }

    /// Mints come from the token-balance rows and from nowhere else.
    #[test]
    fn mints_are_read_only_from_retained_token_balance_rows() {
        let value: Value = serde_json::from_str(&transaction_body(PUMP_PROGRAM)).expect("json");
        let result = value.get("result").expect("result");
        assert_eq!(
            transaction_mints(result).into_iter().collect::<Vec<_>>(),
            vec![MINT.to_owned()]
        );
        let bare = json!({ "slot": 1, "meta": { "err": Value::Null } });
        assert!(transaction_mints(&bare).is_empty());
    }

    /// The pre-I/O durable reservation is derived from the encoders, not from the body length.
    #[test]
    fn the_attempt_claim_reserves_the_derived_physical_cost() {
        let claim = attempt_claim().expect("claim");
        assert_eq!(claim.requests, 1);
        assert_eq!(claim.maximum_ingress_bytes, CENSUS_MAX_RESPONSE_BYTES);
        assert!(claim.maximum_durable_bytes > claim.maximum_ingress_bytes);
        claim.validate().expect("claim is a bounded single request");
        let limits = run_budget_limits(4).expect("limits");
        assert_eq!(limits.maximum_requests, 4);
        assert_eq!(
            limits.maximum_durable_bytes,
            4 * claim.maximum_durable_bytes
        );
    }

    /// Every census argument is refused before a credential is opened.
    #[test]
    fn census_arguments_are_refused_before_any_credential_is_read() {
        let root = tempfile::tempdir().expect("temporary root");
        let mut options = census_options(root.path());
        validated_programs(&options).expect("the default shape validates");

        options.programs = vec!["not base58!".to_owned()];
        assert!(validated_programs(&options).is_err());

        options.programs = vec![PUMP_PROGRAM.to_owned(), PUMP_PROGRAM.to_owned()];
        assert!(validated_programs(&options).is_err());

        options.programs = vec![PUMP_PROGRAM.to_owned(), PUMPSWAP_PROGRAM.to_owned()];
        options.max_requests = 2;
        assert!(validated_programs(&options).is_err());

        options.max_requests = 8;
        options.signature_limit = 0;
        assert!(validated_programs(&options).is_err());
    }
}
