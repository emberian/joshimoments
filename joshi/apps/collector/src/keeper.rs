//! The keeper: a long-running loop of bounded acquisition cycles that keeps one catalog alive.
//!
//! Everything the keeper lands goes through the machinery that already exists — the wallet sweep
//! through `live.rs`'s Helius read path and `commit_reads`, the candle and trade taps through the
//! pump product-read admission in `joshi-pump-adapter` — into one durable catalog this process is
//! the single writer of (the store's writer lease enforces that structurally). What is new here
//! is only the loop: cadence, self-enforced request budgets, rate-limit backoff, an explicit
//! durable record for every cycle that ran and every tap that failed or was skipped, and a
//! heartbeat file so anything can ask "is the keeper alive and when did it last land data".
//!
//! A keeper that quietly stopped is worse than no keeper, because an unchanging catalog must be
//! distinguishable from an unchanging market. So: every cycle that attempts anything commits a
//! coverage window naming its outcome; every failed or deferred tap becomes a coverage gap with
//! its window; budget exhaustion and backoff are durable records, not silences; and the heartbeat
//! is rewritten every tick whether or not anything was due.

use std::{
    collections::BTreeMap,
    error::Error,
    fs::{self, File, OpenOptions},
    io::Write as _,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};

use joshi_admission::{
    AdmissionPolicy, PublicStoreReceiptV1, Sha256Digest, SourceDraftBatch, source_drafts,
};
use joshi_domain::{CoverageId, OpenVariant, SourceId, StableString, UtcTimestamp, ValueDigest};
use joshi_evidence::{Boundary, CoverageGap, CoverageScope, CoverageWindow, EvidenceDraft};
use joshi_pump_adapter::{
    PreparedProductRead, ProductReadInput, close_receipt, prepare_direct_product_read,
    prepare_trades_backfill_page,
};
use joshi_pump_api::{
    AuthenticatedPathDecision, ClientConfig, FetchOutcome, IdentityStore, LogicalRequest,
    NoSession, PumpApiClient, RequestParameters, RouteId, SchemaTrustOutcome, SessionProvider,
};
use joshi_sources::{
    CredentialFile, HeliusConfig, HeliusHttpClient, SolanaReadMethod, SolanaReadRequest,
};
use joshi_store::{SourceRegistration, SqliteStore, StoreConfig, StoreMode};
use serde::{Deserialize, Serialize};
use serde_json::json;
use time::OffsetDateTime;

use crate::live::{
    CapturedRead, DEFAULT_HELIUS_KEY_PATH, INLINE_BLOB_MAX_BYTES, ReadBudget, commit_reads,
    elapsed_nanos, ensure_provider_accepted, first_signatures, perform_one,
    validate_base58_address,
};

const HEARTBEAT_CONTRACT: &str = "joshi.keeper.heartbeat.v1";
/// The keeper's own coverage source: cycle windows and skip/failure gaps hang from this identity,
/// so a cycle that landed nothing still has something durable to say.
const KEEPER_SOURCE_ID: &str = "joshi.keeper.runtime.v1";
const KEEPER_CYCLE_CONTRACT: &str = "joshi.keeper.cycle.v1";
// The store indexes coverage families against a closed vocabulary (census/hot/manual/
// fixture). The keeper is the hot lane — subjects leased hot on a cadence — and its scopes
// stay distinguishable through the keeper source id and per-tap subjects.
const KEEPER_COVERAGE_FAMILY: &str = "hot_lane";
const KEEPER_CATALOG_ID: &str = "joshi-keeper";

const DEFAULT_TICK_SECONDS: u64 = 30;
const DEFAULT_BACKOFF_INITIAL_SECONDS: u64 = 120;
const DEFAULT_BACKOFF_MAX_SECONDS: u64 = 3_600;
const DEFAULT_SIGNATURE_LIMIT: u32 = 10;
const DEFAULT_WALLET_TRANSACTIONS: u32 = 3;
const DEFAULT_CANDLES_INTERVAL: &str = "1s";
const DEFAULT_CANDLES_LIMIT: u32 = 1_000;
const DEFAULT_TRADES_LIMIT: u32 = 100;
/// Cadences are minutes, not seconds: this loop spends Ember's API quota unattended.
const MINIMUM_CADENCE_SECONDS: u64 = 60;
const MAX_CONFIG_BYTES: u64 = 256 * 1024;
const MAX_HEARTBEAT_BYTES: u64 = 4 * 1024 * 1024;
const LOG_MAX_BYTES: u64 = 4 * 1024 * 1024;
/// Provider intervals the candle route accepts; the provider enumerates these in its 400 body.
const CANDLE_INTERVALS: [&str; 12] = [
    "1s", "15s", "30s", "1m", "5m", "15m", "30m", "1h", "4h", "6h", "12h", "24h",
];
/// One pump response ceiling. `MAX_DIRECT_INGRESS_BYTES` is 2 MiB and the outcome envelope holds
/// the body base64-encoded, so a 1 MiB body ceiling (~1.37 MiB encoded) always fits admission.
const PUMP_RESPONSE_LIMIT_BYTES: usize = 1024 * 1024;
const PUMP_REQUEST_TIMEOUT: Duration = Duration::from_secs(20);

const SESSION_REASON_CODE: &str =
    "no_documented_authenticated_get_read_route_for_present_credential";
const SESSION_DETAIL: &str = "This keeper cycle read an undocumented public product route that the Pump web client itself \
     calls anonymously, with no session provider configured. Its shape is observed rather than \
     described, so the schema-trust decision beside this note governs whether anything derived \
     from it may be trusted. No pump.fun user session was available, so no authenticated product \
     route was attempted.";

type Failure = Box<dyn Error>;

/// Arguments of one keeper occurrence.
#[derive(Debug)]
pub(crate) struct KeeperOptions {
    pub(crate) config: PathBuf,
    /// Stop cleanly after this many acquisition cycles. Absent means run until a signal.
    pub(crate) max_cycles: Option<u64>,
}

// ---------------------------------------------------------------------------
// Configuration. Ember edits ops/keeper.toml; v2 will derive the watch set from held coins.
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct KeeperConfigFile {
    /// Keeper state root. The catalog directory is `<root>/catalog`.
    root: String,
    /// Owner-only Helius credential file for the wallet sweep. Pump product routes are free.
    key_file: Option<String>,
    budgets: BudgetsSection,
    wallet: Option<WalletSection>,
    taps: TapsSection,
    #[serde(default)]
    mints: Vec<MintSection>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BudgetsSection {
    per_cycle_requests: u32,
    per_day_requests: u32,
    tick_seconds: Option<u64>,
    backoff_initial_seconds: Option<u64>,
    backoff_max_seconds: Option<u64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WalletSection {
    address: String,
    cadence_minutes: u64,
    signature_limit: Option<u32>,
    transactions: Option<u32>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TapsSection {
    candles_review: String,
    trades_review: String,
    candles_interval: Option<String>,
    candles_limit: Option<u32>,
    trades_limit: Option<u32>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MintSection {
    mint: String,
    label: Option<String>,
    taps: Vec<String>,
    candles_cadence_minutes: Option<u64>,
    trades_cadence_minutes: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum TapKind {
    Wallet {
        signature_limit: u32,
        transactions: u32,
    },
    Candles,
    Trades,
}

impl TapKind {
    const fn name(&self) -> &'static str {
        match self {
            Self::Wallet { .. } => "wallet",
            Self::Candles => "candles",
            Self::Trades => "trades",
        }
    }
}

#[derive(Clone, Debug)]
struct Tap {
    kind: TapKind,
    /// Wallet address or SPL mint.
    subject: String,
    label: Option<String>,
    cadence_seconds: u64,
    /// Hard request ceiling for one occurrence of this tap.
    cost: u32,
}

impl Tap {
    fn key(&self) -> String {
        format!("{}:{}", self.kind.name(), self.subject)
    }
}

/// A validated keeper configuration with every path resolved and every review already read.
struct KeeperConfig {
    root: PathBuf,
    key_file: PathBuf,
    per_cycle_requests: u32,
    per_day_requests: u32,
    tick: Duration,
    backoff_initial_seconds: u64,
    backoff_max_seconds: u64,
    candles_interval: String,
    candles_limit: u32,
    trades_limit: u32,
    candles_review: Vec<u8>,
    trades_review: Vec<u8>,
    taps: Vec<Tap>,
}

fn resolve(base: &Path, value: &str) -> PathBuf {
    let path = Path::new(value);
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    }
}

fn read_bounded_file(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, Failure> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("{label} {} is unreadable: {error}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!("{label} {} is not a regular file", path.display()).into());
    }
    if metadata.len() > maximum {
        return Err(format!(
            "{label} {} exceeds the {maximum}-byte bound",
            path.display()
        )
        .into());
    }
    Ok(fs::read(path)?)
}

#[allow(clippy::too_many_lines)] // Every refusal the config surface makes is stated in one place.
fn load_config(path: &Path) -> Result<KeeperConfig, Failure> {
    let bytes = read_bounded_file(path, MAX_CONFIG_BYTES, "keeper config")?;
    let text = std::str::from_utf8(&bytes).map_err(|_| "keeper config is not UTF-8")?;
    let file: KeeperConfigFile = toml::from_str(text)?;
    let base = path
        .parent()
        .map_or_else(|| PathBuf::from("."), Path::to_path_buf);

    if file.budgets.per_cycle_requests == 0 || file.budgets.per_day_requests == 0 {
        return Err(
            "budgets.per_cycle_requests and budgets.per_day_requests must be positive".into(),
        );
    }
    if file.budgets.per_day_requests < file.budgets.per_cycle_requests {
        return Err("budgets.per_day_requests must be at least budgets.per_cycle_requests".into());
    }
    let tick_seconds = file.budgets.tick_seconds.unwrap_or(DEFAULT_TICK_SECONDS);
    if tick_seconds == 0 {
        return Err("budgets.tick_seconds must be positive".into());
    }
    let backoff_initial_seconds = file
        .budgets
        .backoff_initial_seconds
        .unwrap_or(DEFAULT_BACKOFF_INITIAL_SECONDS);
    let backoff_max_seconds = file
        .budgets
        .backoff_max_seconds
        .unwrap_or(DEFAULT_BACKOFF_MAX_SECONDS);
    if backoff_initial_seconds == 0 || backoff_max_seconds < backoff_initial_seconds {
        return Err("backoff seconds must be positive and the maximum at least the initial".into());
    }

    let candles_interval = file
        .taps
        .candles_interval
        .unwrap_or_else(|| DEFAULT_CANDLES_INTERVAL.to_owned());
    if !CANDLE_INTERVALS.contains(&candles_interval.as_str()) {
        return Err(format!(
            "taps.candles_interval {candles_interval:?} is not one the provider accepts: {CANDLE_INTERVALS:?}"
        )
        .into());
    }
    let candles_limit = file.taps.candles_limit.unwrap_or(DEFAULT_CANDLES_LIMIT);
    if candles_limit == 0 || candles_limit > 1_000 {
        return Err("taps.candles_limit must be between 1 and 1000".into());
    }
    let trades_limit = file.taps.trades_limit.unwrap_or(DEFAULT_TRADES_LIMIT);
    if trades_limit == 0 || trades_limit > 100 {
        return Err("taps.trades_limit must be between 1 and 100".into());
    }
    let candles_review = read_bounded_file(
        &resolve(&base, &file.taps.candles_review),
        MAX_CONFIG_BYTES,
        "taps.candles_review",
    )?;
    let trades_review = read_bounded_file(
        &resolve(&base, &file.taps.trades_review),
        MAX_CONFIG_BYTES,
        "taps.trades_review",
    )?;

    let mut taps = Vec::new();
    if let Some(wallet) = &file.wallet {
        validate_base58_address(&wallet.address, "wallet.address")?;
        require_gentle_cadence("wallet.cadence_minutes", wallet.cadence_minutes)?;
        let signature_limit = wallet.signature_limit.unwrap_or(DEFAULT_SIGNATURE_LIMIT);
        if signature_limit == 0 || signature_limit > 100 {
            return Err("wallet.signature_limit must be between 1 and 100".into());
        }
        let transactions = wallet.transactions.unwrap_or(DEFAULT_WALLET_TRANSACTIONS);
        if transactions == 0 || transactions > 25 {
            return Err("wallet.transactions must be between 1 and 25".into());
        }
        taps.push(Tap {
            kind: TapKind::Wallet {
                signature_limit,
                transactions,
            },
            subject: wallet.address.clone(),
            label: None,
            cadence_seconds: wallet.cadence_minutes * 60,
            cost: 1 + transactions,
        });
    }
    for mint in &file.mints {
        validate_base58_address(&mint.mint, "mints.mint")?;
        if mint.taps.is_empty() {
            return Err(format!("mint {} names no taps", mint.mint).into());
        }
        for tap in &mint.taps {
            match tap.as_str() {
                "candles" => {
                    let cadence = mint.candles_cadence_minutes.ok_or_else(|| {
                        format!("mint {} needs candles_cadence_minutes", mint.mint)
                    })?;
                    require_gentle_cadence("candles_cadence_minutes", cadence)?;
                    taps.push(Tap {
                        kind: TapKind::Candles,
                        subject: mint.mint.clone(),
                        label: mint.label.clone(),
                        cadence_seconds: cadence * 60,
                        cost: 1,
                    });
                }
                "trades" => {
                    let cadence = mint.trades_cadence_minutes.ok_or_else(|| {
                        format!("mint {} needs trades_cadence_minutes", mint.mint)
                    })?;
                    require_gentle_cadence("trades_cadence_minutes", cadence)?;
                    taps.push(Tap {
                        kind: TapKind::Trades,
                        subject: mint.mint.clone(),
                        label: mint.label.clone(),
                        cadence_seconds: cadence * 60,
                        cost: 1,
                    });
                }
                other => {
                    return Err(format!(
                        "mint {} names unknown tap {other:?}; taps are \"candles\" and \"trades\"",
                        mint.mint
                    )
                    .into());
                }
            }
        }
    }
    if taps.is_empty() {
        return Err("the keeper config names no wallet and no mint taps; nothing to keep".into());
    }
    let mut seen = std::collections::BTreeSet::new();
    for tap in &taps {
        if !seen.insert(tap.key()) {
            return Err(format!("tap {} is configured twice", tap.key()).into());
        }
    }
    let heaviest = taps.iter().map(|tap| tap.cost).max().unwrap_or(1);
    if file.budgets.per_cycle_requests < heaviest {
        return Err(format!(
            "budgets.per_cycle_requests {} cannot afford the heaviest configured tap ({heaviest} requests)",
            file.budgets.per_cycle_requests
        )
        .into());
    }

    Ok(KeeperConfig {
        root: resolve(&base, &file.root),
        key_file: file.key_file.as_deref().map_or_else(
            || PathBuf::from(DEFAULT_HELIUS_KEY_PATH),
            |value| resolve(&base, value),
        ),
        per_cycle_requests: file.budgets.per_cycle_requests,
        per_day_requests: file.budgets.per_day_requests,
        tick: Duration::from_secs(tick_seconds),
        backoff_initial_seconds,
        backoff_max_seconds,
        candles_interval,
        candles_limit,
        trades_limit,
        candles_review,
        trades_review,
        taps,
    })
}

fn require_gentle_cadence(field: &str, minutes: u64) -> Result<(), Failure> {
    if minutes == 0 || minutes.saturating_mul(60) < MINIMUM_CADENCE_SECONDS {
        return Err(format!(
            "{field} must be at least one minute; the keeper is polite by construction"
        )
        .into());
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Heartbeat: the durable operational memory and the "is it alive" answer.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TapClock {
    last_attempt_at: Option<String>,
    last_success_at: Option<String>,
    last_commit_seq: Option<String>,
    /// Wallet only: the newest swept signature. Operational memory, never cursor authority.
    newest_wallet_signature: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TapSummary {
    tap: String,
    status: String,
    requests: u32,
    commit_seq: Option<String>,
    schema_trust: Option<String>,
    throttled: bool,
    detail: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CycleRecord {
    ordinal: u64,
    started_at: String,
    ended_at: String,
    requests_used: u32,
    taps: Vec<TapSummary>,
    gaps_recorded: u32,
    closure_commit_seq: Option<String>,
    state: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ShutdownRecord {
    at: String,
    reason: String,
}

/// The whole heartbeat. Unknown fields are tolerated on read so an older keeper build can still
/// adopt a newer file's memory instead of resetting the day budget.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct HeartbeatV1 {
    contract: String,
    pid: u32,
    run_tag: String,
    started_at: String,
    state: String,
    last_write_at: String,
    utc_day: String,
    day_requests_used: u32,
    day_request_budget: u32,
    cycle_ordinal: u64,
    consecutive_throttles: u32,
    backoff_until: Option<String>,
    tap_clocks: BTreeMap<String, TapClock>,
    last_cycle: Option<CycleRecord>,
    catalog_root: String,
    config_path: String,
    note: Option<String>,
    shutdown: Option<ShutdownRecord>,
}

fn write_heartbeat(path: &Path, heartbeat: &HeartbeatV1) -> Result<(), Failure> {
    let bytes = serde_json::to_vec_pretty(heartbeat)?;
    let temporary = path.with_extension("json.tmp");
    let mut file = File::create(&temporary)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, path)?;
    Ok(())
}

fn read_heartbeat(path: &Path) -> Option<HeartbeatV1> {
    let bytes = read_bounded_file(path, MAX_HEARTBEAT_BYTES, "keeper heartbeat").ok()?;
    serde_json::from_slice(&bytes).ok()
}

// ---------------------------------------------------------------------------
// Clocks and scheduling.
// ---------------------------------------------------------------------------

fn format_six(value: OffsetDateTime) -> Result<String, Failure> {
    Ok(value.format(time::macros::format_description!(
        "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
    ))?)
}

/// Truncate to the store's microsecond boundary and wrap as a shared timestamp.
fn wall(value: OffsetDateTime) -> Result<UtcTimestamp, Failure> {
    let nanosecond = value.nanosecond();
    Ok(UtcTimestamp::new(
        value.replace_nanosecond(nanosecond - nanosecond % 1_000)?,
    )?)
}

fn utc_day(value: OffsetDateTime) -> String {
    format!(
        "{:04}-{:02}-{:02}",
        value.year(),
        u8::from(value.month()),
        value.day()
    )
}

fn next_utc_midnight(value: OffsetDateTime) -> Result<OffsetDateTime, Failure> {
    value
        .replace_time(time::Time::MIDNIGHT)
        .checked_add(time::Duration::days(1))
        .ok_or_else(|| "day arithmetic overflowed".into())
}

fn parse_instant(value: &str) -> Option<OffsetDateTime> {
    value
        .parse::<UtcTimestamp>()
        .ok()
        .map(UtcTimestamp::as_datetime)
}

/// A tap is due when it has never been attempted or its cadence has elapsed since the last
/// attempt. Failed attempts also wait out the cadence: a failing provider is not retried at tick
/// rate.
fn tap_due(tap: &Tap, clocks: &BTreeMap<String, TapClock>, now: OffsetDateTime) -> bool {
    let Some(clock) = clocks.get(&tap.key()) else {
        return true;
    };
    let Some(last) = clock.last_attempt_at.as_deref().and_then(parse_instant) else {
        return true;
    };
    let Ok(cadence) = i64::try_from(tap.cadence_seconds) else {
        return false;
    };
    now >= last + time::Duration::seconds(cadence)
}

/// Exponential backoff from the first throttle, capped. `consecutive` counts throttled cycles.
fn backoff_seconds(consecutive: u32, initial: u64, maximum: u64) -> u64 {
    let doublings = consecutive.saturating_sub(1).min(16);
    initial.saturating_mul(1_u64 << doublings).min(maximum)
}

/// Which of the page's signatures are new since the remembered newest one, and whether the
/// remembered signature was still on the page (if it was not, and the page was full, older
/// activity may have scrolled past the page boundary unswept).
fn new_signatures_since<'a>(rows: &'a [String], remembered: Option<&str>) -> (&'a [String], bool) {
    match remembered {
        None => (rows, true),
        Some(known) => rows
            .iter()
            .position(|signature| signature == known)
            .map_or((rows, false), |position| (&rows[..position], true)),
    }
}

// ---------------------------------------------------------------------------
// Bounded log file: append with one rotated generation, never unbounded.
// ---------------------------------------------------------------------------

struct BoundedLog {
    path: PathBuf,
    max_bytes: u64,
}

impl BoundedLog {
    fn line(&self, message: &str) {
        if let Err(error) = self.append(message) {
            eprintln!("keeper: log write failed: {error}");
        }
    }

    fn append(&self, message: &str) -> Result<(), Failure> {
        if let Ok(metadata) = fs::metadata(&self.path)
            && metadata.len() >= self.max_bytes
        {
            // One rotated generation bounds the total at twice the ceiling.
            let _ = fs::rename(&self.path, self.path.with_extension("log.old"));
        }
        let stamp = format_six(OffsetDateTime::now_utc())?;
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        writeln!(file, "{stamp} {message}")?;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Durable cycle closure: one coverage window per attempted cycle, one gap per defect.
// ---------------------------------------------------------------------------

/// One explicit defect of one cycle: a failed tap, a deferred tap, a budget or backoff idle.
#[derive(Clone, Debug)]
struct CycleGap {
    /// Tap subject, or `None` for a cycle-wide condition.
    subject: Option<String>,
    reason: String,
    lower: Boundary,
    upper: Option<Boundary>,
}

fn keeper_scope(subject: Option<&str>) -> Result<CoverageScope, Failure> {
    Ok(CoverageScope {
        source_id: SourceId::new(KEEPER_SOURCE_ID)?,
        family: OpenVariant::known(KEEPER_COVERAGE_FAMILY)?,
        subject: subject.map(StableString::new).transpose()?,
    })
}

fn keeper_registration() -> Result<SourceRegistration, Failure> {
    let build = env!("CARGO_PKG_VERSION");
    let material = format!(
        "joshi.source.registration.v1\0{KEEPER_SOURCE_ID}\0keeper_runtime\0{KEEPER_CYCLE_CONTRACT}\0{build}"
    );
    Ok(SourceRegistration {
        source_id: SourceId::new(KEEPER_SOURCE_ID)?,
        namespace: StableString::new("keeper_runtime")?,
        contract_version: StableString::new(KEEPER_CYCLE_CONTRACT)?,
        collector_build: StableString::new(build)?,
        configuration_digest: ValueDigest::new(
            Sha256Digest::of_bytes(material.as_bytes()).to_string(),
        )?,
    })
}

/// Everything one durable cycle receipt states: the window, its outcome label, and every defect.
struct CycleClosure<'a> {
    run_tag: &'a str,
    ordinal: u64,
    started: UtcTimestamp,
    ended: UtcTimestamp,
    state: &'a str,
    gaps: &'a [CycleGap],
    clock_id: &'a str,
    process_start: Instant,
}

fn commit_cycle_closure(
    store: &mut SqliteStore,
    closure: &CycleClosure<'_>,
) -> Result<PublicStoreReceiptV1, Failure> {
    let CycleClosure {
        run_tag,
        ordinal,
        started,
        ended,
        state,
        gaps,
        clock_id,
        process_start,
    } = *closure;
    let coverage_id = CoverageId::new(format!("coverage-{run_tag}-cycle-{ordinal:06}"))?;
    let mut drafts = vec![EvidenceDraft::CoverageWindow(CoverageWindow {
        coverage_id: coverage_id.clone(),
        scope: keeper_scope(None)?,
        lower: Boundary::Wall { value: started },
        upper: Some(Boundary::Wall { value: ended }),
        state: OpenVariant::known(state)?,
        available_at: ended,
    })];
    for (index, gap) in gaps.iter().enumerate() {
        drafts.push(EvidenceDraft::CoverageGap(CoverageGap {
            gap_id: CoverageId::new(format!("gap-{run_tag}-cycle-{ordinal:06}-{index:02}"))?,
            coverage_id: coverage_id.clone(),
            scope: keeper_scope(gap.subject.as_deref())?,
            lower: gap.lower.clone(),
            upper: gap.upper.clone(),
            reason: OpenVariant::known(gap.reason.clone())?,
            detected_at: ended,
        }));
    }
    let batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(format!("{run_tag}-cycle-{ordinal:06}-closure"))?,
        drafts,
        source_events: Vec::new(),
        cursor_advances: Vec::new(),
        registrations: vec![keeper_registration()?],
        policy: AdmissionPolicy::public_source()?,
        committed_at: ended,
        writer_clock_id: StableString::new(clock_id)?,
        committed_mono_ns: elapsed_nanos(process_start)?,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })?;
    Ok(batch.commit(store)?)
}

// ---------------------------------------------------------------------------
// Pump taps: one bounded read through the existing product-read admission.
// ---------------------------------------------------------------------------

struct AdmittedPumpRead {
    receipt: PublicStoreReceiptV1,
    prepared: PreparedProductRead,
    completed: bool,
}

/// Admit one exact serialized fetch outcome through the shared pump product-read path. A failed
/// outcome is still admitted — the attempt envelope and the client's own coverage gaps become
/// durable — through the page-tolerant entry the trades backfill uses for exactly this reason.
fn admit_pump_outcome_bytes(
    store: &mut SqliteStore,
    outcome_bytes: &[u8],
    review_bytes: &[u8],
    process_start: Instant,
) -> Result<AdmittedPumpRead, Failure> {
    let outcome: FetchOutcome = serde_json::from_slice(outcome_bytes)?;
    let decided_at = format_six(OffsetDateTime::now_utc())?;
    let batch_id = format!(
        "batch:keeper-pump:{}",
        outcome
            .request_group_id
            .trim_start_matches("reqgrp:pump-api:")
    );
    let input = ProductReadInput {
        outcome_bytes,
        review_bytes: Some(review_bytes),
        authenticated_path: AuthenticatedPathDecision::NotPerformed,
        session_reason_code: SESSION_REASON_CODE,
        session_detail: SESSION_DETAIL,
        durable_batch_id: &batch_id,
        committed_at: decided_at.parse::<UtcTimestamp>()?,
        committed_monotonic_ns: elapsed_nanos(process_start)?.max(1),
        decided_at: &decided_at,
    };
    let prepared = if outcome.completed {
        prepare_direct_product_read(&input)?
    } else {
        prepare_trades_backfill_page(&input, None)?
    };
    let receipt = prepared.prepared.admission_batch().commit(store)?;
    close_receipt(&prepared.prepared, &receipt)?;
    Ok(AdmittedPumpRead {
        receipt,
        prepared,
        completed: outcome.completed,
    })
}

/// What one tap occurrence did, in the cycle's own vocabulary.
struct TapRun {
    status: &'static str,
    requests: u32,
    commit_seq: Option<String>,
    schema_trust: Option<String>,
    throttled: bool,
    success: bool,
    detail: Option<String>,
    gaps: Vec<CycleGap>,
    newest_wallet_signature: Option<String>,
}

fn failed_tap_window(
    clock: Option<&TapClock>,
    now: UtcTimestamp,
) -> Result<(Boundary, Option<Boundary>), Failure> {
    let lower = match clock.and_then(|value| value.last_success_at.as_deref()) {
        Some(last) => Boundary::Wall {
            value: last.parse::<UtcTimestamp>()?,
        },
        None => Boundary::Unknown {
            reason: OpenVariant::known(
                "this tap has no prior successful landing in keeper memory",
            )?,
        },
    };
    Ok((lower, Some(Boundary::Wall { value: now })))
}

#[allow(clippy::too_many_lines)] // One tap's whole fetch/admit/describe walk stays together.
async fn run_pump_tap(
    tap: &Tap,
    config: &KeeperConfig,
    store: &mut SqliteStore,
    identity: &IdentityStore,
    clock: Option<&TapClock>,
    process_start: Instant,
) -> Result<TapRun, Failure> {
    let (route, review_bytes) = match tap.kind {
        TapKind::Candles => (RouteId::Candles, config.candles_review.as_slice()),
        TapKind::Trades => (RouteId::Trades, config.trades_review.as_slice()),
        TapKind::Wallet { .. } => return Err("wallet tap dispatched to the pump path".into()),
    };
    let mut query = BTreeMap::new();
    match tap.kind {
        TapKind::Candles => {
            query.insert("interval".to_owned(), config.candles_interval.clone());
            query.insert("limit".to_owned(), config.candles_limit.to_string());
        }
        TapKind::Trades => {
            query.insert("limit".to_owned(), config.trades_limit.to_string());
        }
        TapKind::Wallet { .. } => {}
    }
    let mut client_config = ClientConfig {
        request_budget: 1,
        // One attempt, no internal retries: backoff is the keeper's job and is durable there.
        maximum_attempts: 1,
        response_limit_bytes: PUMP_RESPONSE_LIMIT_BYTES,
        request_timeout: PUMP_REQUEST_TIMEOUT,
        ..ClientConfig::default()
    };
    client_config.enabled_routes = [route].into_iter().collect();
    let sessions: Arc<dyn SessionProvider> = Arc::new(NoSession);
    let now = wall(OffsetDateTime::now_utc())?;
    let client = match PumpApiClient::new(client_config, identity.clone(), sessions) {
        Ok(client) => client,
        Err(error) => {
            let (lower, upper) = failed_tap_window(clock, now)?;
            return Ok(TapRun {
                status: "failed_before_request",
                requests: 0,
                commit_seq: None,
                schema_trust: None,
                throttled: false,
                success: false,
                detail: Some(error.to_string()),
                gaps: vec![CycleGap {
                    subject: Some(tap.key()),
                    reason: "pump_client_unavailable".to_owned(),
                    lower,
                    upper,
                }],
                newest_wallet_signature: None,
            });
        }
    };
    let request = LogicalRequest {
        route,
        parameters: RequestParameters {
            path: [("mint".to_owned(), tap.subject.clone())]
                .into_iter()
                .collect(),
            query,
        },
    };
    let outcome = match client.fetch(&request).await {
        Ok(outcome) => outcome,
        Err(error) => {
            // Refusals here happen before a request leaves the process (route/parameter/identity
            // problems); the transport failures the budget cares about are captured inside a
            // returned outcome instead.
            let (lower, upper) = failed_tap_window(clock, now)?;
            return Ok(TapRun {
                status: "failed_before_request",
                requests: 0,
                commit_seq: None,
                schema_trust: None,
                throttled: false,
                success: false,
                detail: Some(error.to_string()),
                gaps: vec![CycleGap {
                    subject: Some(tap.key()),
                    reason: "pump_request_not_performed".to_owned(),
                    lower,
                    upper,
                }],
                newest_wallet_signature: None,
            });
        }
    };
    let throttled = outcome
        .coverage_gaps
        .iter()
        .any(|gap| gap.reason == "rate_limit_exhausted")
        || outcome
            .attempts
            .iter()
            .any(|attempt| attempt.http_status == Some(429));
    let outcome_bytes = serde_json::to_vec(&outcome)?;
    let admitted = admit_pump_outcome_bytes(store, &outcome_bytes, review_bytes, process_start)?;
    admitted
        .prepared
        .prepared
        .acknowledge_direct(identity, &admitted.receipt)?;
    let trust = format!("{:?}", admitted.prepared.decision.outcome).to_ascii_lowercase();
    let promoted = admitted.prepared.decision.outcome == SchemaTrustOutcome::Promoted;
    let status = if !admitted.completed {
        // The client's own coverage gap rows for this read were just committed with the attempt
        // envelope, so the durable record of the failure already exists; nothing is duplicated.
        "retained_failed_read"
    } else if promoted {
        "committed_promoted"
    } else {
        "committed_quarantined"
    };
    Ok(TapRun {
        status,
        requests: 1,
        commit_seq: Some(admitted.receipt.commit_seq.clone()),
        schema_trust: Some(trust),
        throttled,
        success: admitted.completed,
        detail: None,
        gaps: Vec::new(),
        newest_wallet_signature: None,
    })
}

// ---------------------------------------------------------------------------
// Wallet tap: the ingest-live read path, made incremental by remembered newest signature.
// ---------------------------------------------------------------------------

struct WalletSweepFacts {
    throttled: bool,
    newest_signature: Option<String>,
    hydrated: usize,
    new_rows: usize,
}

// The sweep owns nothing — every buffer stays with the caller so a mid-sweep provider error
// still leaves the frames it landed committable — and its budget/throttle/gap decisions read as
// one walk.
#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
async fn sweep_wallet(
    client: &HeliusHttpClient,
    address: &str,
    signature_limit: u32,
    transactions_cap: u32,
    remembered: Option<&str>,
    budget: &mut ReadBudget,
    reads: &mut Vec<CapturedRead>,
    gaps: &mut Vec<CycleGap>,
    tap_key: &str,
    process_start: Instant,
) -> Result<WalletSweepFacts, Failure> {
    let mut sequence = 1_u64;
    let page = perform_one(
        client,
        budget,
        sequence,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetSignaturesForAddress,
            json!([address, { "limit": signature_limit, "commitment": "finalized" }]),
        ),
        format!(
            "method=getSignaturesForAddress;address={address};limit={signature_limit};commitment=finalized"
        ),
    )
    .await?;
    if page.rate_limit.is_some() {
        // A throttle ends the sweep immediately; an accepted body is still worth retaining.
        if ensure_provider_accepted(&page).is_ok() {
            reads.push(page);
        }
        return Ok(WalletSweepFacts {
            throttled: true,
            newest_signature: None,
            hydrated: 0,
            new_rows: 0,
        });
    }
    ensure_provider_accepted(&page)?;
    let rows = first_signatures(&page.frame, usize::MAX);
    let newest_signature = rows.first().cloned();
    let (new_rows, memory_seen) = new_signatures_since(&rows, remembered);
    let new_rows = new_rows.to_vec();
    let page_full = u32::try_from(rows.len()).unwrap_or(u32::MAX) >= signature_limit;
    reads.push(page);
    if !memory_seen
        && page_full
        && let Some(known) = remembered
    {
        // The remembered signature scrolled off a full page: activity between the page's oldest
        // row and the last swept point may exist and was not listed.
        gaps.push(CycleGap {
            subject: Some(tap_key.to_owned()),
            reason: "wallet_signature_page_hit_limit_before_known_signature".to_owned(),
            lower: Boundary::SourceCursor {
                value: StableString::new(format!("signature:{known}"))?,
            },
            upper: rows
                .last()
                .map(|oldest| {
                    Ok::<_, Failure>(Boundary::SourceCursor {
                        value: StableString::new(format!("signature:{oldest}"))?,
                    })
                })
                .transpose()?,
        });
    }
    let mut hydrated = 0_usize;
    let mut throttled = false;
    for signature in &new_rows {
        if hydrated >= transactions_cap as usize || budget.remaining() == 0 {
            break;
        }
        sequence += 1;
        let transaction = perform_one(
            client,
            budget,
            sequence,
            process_start,
            &SolanaReadRequest::new(
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
            format!(
                "method=getTransaction;signature={signature};commitment=finalized;encoding=json"
            ),
        )
        .await?;
        let hit = transaction.rate_limit.is_some();
        ensure_provider_accepted(&transaction)?;
        reads.push(transaction);
        hydrated += 1;
        if hit {
            throttled = true;
            break;
        }
    }
    if hydrated < new_rows.len() {
        // Whatever stopped hydration — the per-tap cap, the budget, a throttle — the rest of the
        // listed activity was seen and not fetched, and the catalog says so.
        let newest_unhydrated = &new_rows[hydrated];
        let oldest_unhydrated = new_rows.last().unwrap_or(newest_unhydrated);
        gaps.push(CycleGap {
            subject: Some(tap_key.to_owned()),
            reason: "listed_signatures_were_not_hydrated".to_owned(),
            lower: Boundary::SourceCursor {
                value: StableString::new(format!("signature:{oldest_unhydrated}"))?,
            },
            upper: Some(Boundary::SourceCursor {
                value: StableString::new(format!("signature:{newest_unhydrated}"))?,
            }),
        });
    }
    Ok(WalletSweepFacts {
        throttled,
        newest_signature,
        hydrated,
        new_rows: new_rows.len(),
    })
}

/// The identifiers of the cycle a tap runs inside, for batch naming and monotonic stamps.
#[derive(Clone, Copy)]
struct CycleStamp<'a> {
    run_tag: &'a str,
    ordinal: u64,
    clock_id: &'a str,
    process_start: Instant,
}

#[allow(clippy::too_many_lines)] // Partial-commit and failure handling belong beside the sweep.
async fn run_wallet_tap(
    tap: &Tap,
    config: &KeeperConfig,
    store: &mut SqliteStore,
    clock: Option<&TapClock>,
    ceiling: u32,
    stamp: CycleStamp<'_>,
) -> Result<TapRun, Failure> {
    let TapKind::Wallet {
        signature_limit,
        transactions,
    } = tap.kind
    else {
        return Err("pump tap dispatched to the wallet path".into());
    };
    let now = wall(OffsetDateTime::now_utc())?;
    let mut budget = ReadBudget::new(ceiling);
    let mut reads: Vec<CapturedRead> = Vec::new();
    let mut gaps: Vec<CycleGap> = Vec::new();
    let client = match HeliusHttpClient::at_startup(
        &HeliusConfig::mainnet(CredentialFile(config.key_file.clone())),
        INLINE_BLOB_MAX_BYTES,
    ) {
        Ok(client) => client,
        Err(error) => {
            let (lower, upper) = failed_tap_window(clock, now)?;
            return Ok(TapRun {
                status: "failed_before_request",
                requests: 0,
                commit_seq: None,
                schema_trust: None,
                throttled: false,
                success: false,
                detail: Some(error.to_string()),
                gaps: vec![CycleGap {
                    subject: Some(tap.key()),
                    reason: "wallet_credential_unavailable".to_owned(),
                    lower,
                    upper,
                }],
                newest_wallet_signature: None,
            });
        }
    };
    let swept = sweep_wallet(
        &client,
        &tap.subject,
        signature_limit,
        transactions,
        clock.and_then(|value| value.newest_wallet_signature.as_deref()),
        &mut budget,
        &mut reads,
        &mut gaps,
        &tap.key(),
        stamp.process_start,
    )
    .await;
    drop(client);
    let requests = ceiling.saturating_sub(budget.remaining());
    // Whatever the sweep concluded, the frames it did land are retained: partial evidence with an
    // explicit gap beats discarded evidence.
    let commit_seq = if reads.is_empty() {
        None
    } else {
        let namespace = format!("{}-wallet-{:06}", stamp.run_tag, stamp.ordinal);
        let receipt = commit_reads(
            store,
            &reads,
            &namespace,
            stamp.clock_id,
            stamp.process_start,
        )?;
        Some(receipt.commit_seq)
    };
    match swept {
        Ok(facts) => Ok(TapRun {
            status: if facts.throttled {
                "throttled"
            } else if facts.new_rows == 0 {
                "committed_no_new_activity"
            } else {
                "committed"
            },
            requests,
            commit_seq,
            schema_trust: None,
            throttled: facts.throttled,
            success: !facts.throttled,
            detail: Some(format!(
                "newRows={} hydrated={}",
                facts.new_rows, facts.hydrated
            )),
            gaps,
            newest_wallet_signature: facts.newest_signature,
        }),
        Err(error) => {
            let (lower, upper) = failed_tap_window(clock, now)?;
            gaps.push(CycleGap {
                subject: Some(tap.key()),
                reason: "wallet_read_failed".to_owned(),
                lower,
                upper,
            });
            Ok(TapRun {
                status: "failed",
                requests,
                commit_seq,
                schema_trust: None,
                throttled: false,
                success: false,
                detail: Some(error.to_string()),
                gaps,
                newest_wallet_signature: None,
            })
        }
    }
}

// ---------------------------------------------------------------------------
// The keeper loop.
// ---------------------------------------------------------------------------

fn keeper_store_config(root: &Path) -> Result<StoreConfig, Failure> {
    let catalog = root.join("catalog");
    Ok(StoreConfig {
        catalog_path: catalog.join("catalog.sqlite"),
        blob_root: catalog.join("blobs"),
        export_root: catalog.join("exports"),
        inline_blob_max_bytes: INLINE_BLOB_MAX_BYTES,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new(KEEPER_CATALOG_ID)?,
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 64 * 1024 * 1024,
    })
}

struct Keeper {
    config: KeeperConfig,
    config_path: PathBuf,
    store: SqliteStore,
    identity: IdentityStore,
    heartbeat_path: PathBuf,
    heartbeat: HeartbeatV1,
    log: BoundedLog,
    process_start: Instant,
    run_tag: String,
    clock_id: String,
}

fn fresh_heartbeat(
    config: &KeeperConfig,
    config_path: &Path,
    run_tag: &str,
    started_at: &str,
    now: OffsetDateTime,
) -> HeartbeatV1 {
    HeartbeatV1 {
        contract: HEARTBEAT_CONTRACT.to_owned(),
        pid: std::process::id(),
        run_tag: run_tag.to_owned(),
        started_at: started_at.to_owned(),
        state: "running".to_owned(),
        last_write_at: started_at.to_owned(),
        utc_day: utc_day(now),
        day_requests_used: 0,
        day_request_budget: config.per_day_requests,
        cycle_ordinal: 0,
        consecutive_throttles: 0,
        backoff_until: None,
        tap_clocks: BTreeMap::new(),
        last_cycle: None,
        catalog_root: config.root.join("catalog").display().to_string(),
        config_path: config_path.display().to_string(),
        note: None,
        shutdown: None,
    }
}

/// Adopt what an earlier keeper wrote down: tap cadence memory always; day usage, throttle state
/// and the cycle ordinal when the file speaks about today. Anything unreadable resets with a note
/// rather than silently — a reset day budget spends more, never less honestly.
fn adopt_heartbeat(
    mut fresh: HeartbeatV1,
    previous: Option<HeartbeatV1>,
    now: OffsetDateTime,
) -> HeartbeatV1 {
    let Some(previous) = previous else {
        fresh.note = Some(
            "no readable prior heartbeat; tap cadence memory and day usage start empty".to_owned(),
        );
        return fresh;
    };
    fresh.tap_clocks = previous.tap_clocks;
    fresh.cycle_ordinal = previous.cycle_ordinal;
    if previous.utc_day == utc_day(now) {
        fresh.day_requests_used = previous.day_requests_used;
        fresh.consecutive_throttles = previous.consecutive_throttles;
        fresh.backoff_until = previous.backoff_until;
        if previous.state == "day_budget_idle" {
            fresh.state = previous.state;
        }
    }
    fresh
}

pub(crate) fn run_keeper(options: &KeeperOptions) -> Result<String, Failure> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(keeper_main(options))
}

#[allow(clippy::too_many_lines)] // The loop's states and its shutdown are one legible walk.
async fn keeper_main(options: &KeeperOptions) -> Result<String, Failure> {
    let process_start = Instant::now();
    let config_path = options
        .config
        .canonicalize()
        .map_err(|error| format!("keeper config {}: {error}", options.config.display()))?;
    let config = load_config(&config_path)?;
    fs::create_dir_all(&config.root)?;
    let log = BoundedLog {
        path: config.root.join("keeper.log"),
        max_bytes: LOG_MAX_BYTES,
    };
    let started_wall = OffsetDateTime::now_utc();
    let started_at = format_six(started_wall)?;
    let run_tag = format!(
        "keeper-{}-{}",
        std::process::id(),
        crate::live::unix_millis(started_wall)?
    );
    let clock_id = format!("joshi-keeper-{}", std::process::id());

    // Open the single-writer catalog before anything else: the writer lease *is* the single
    // writer discipline, and a keeper that cannot write must fail here, not after a read.
    let mut store = SqliteStore::open(keeper_store_config(&config.root)?, StoreMode::SingleWriter)?;
    let migration = store.migrate(wall(OffsetDateTime::now_utc())?)?;
    let identity = IdentityStore::open(config.root.join("identity"))?;

    let heartbeat_path = config.root.join("heartbeat.json");
    let previous = read_heartbeat(&heartbeat_path);
    let mut keeper = Keeper {
        heartbeat: adopt_heartbeat(
            fresh_heartbeat(&config, &config_path, &run_tag, &started_at, started_wall),
            previous,
            started_wall,
        ),
        config,
        config_path,
        store,
        identity,
        heartbeat_path,
        log,
        process_start,
        run_tag,
        clock_id,
    };
    write_heartbeat(&keeper.heartbeat_path, &keeper.heartbeat)?;
    keeper.log.line(&format!(
        "keeper started pid={} runTag={} taps={} appliedMigrations={} catalog={}",
        std::process::id(),
        keeper.run_tag,
        keeper.config.taps.len(),
        migration.applied.len(),
        keeper.heartbeat.catalog_root,
    ));

    let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let mut sigint = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())?;
    let mut cycles_run = 0_u64;
    let mut shutdown_reason: Option<String> = None;

    while shutdown_reason.is_none() {
        let now = OffsetDateTime::now_utc();
        // UTC day rollover restores a spent budget and leaves day-idle.
        if keeper.heartbeat.utc_day != utc_day(now) {
            keeper.heartbeat.utc_day = utc_day(now);
            keeper.heartbeat.day_requests_used = 0;
            if keeper.heartbeat.state == "day_budget_idle" {
                "running".clone_into(&mut keeper.heartbeat.state);
                keeper
                    .log
                    .line("utc day rolled over; leaving day-budget idle");
            }
        }
        // Ember edits the config while the keeper runs; a broken edit keeps the last good one.
        match load_config(&keeper.config_path) {
            Ok(reloaded) => {
                if reloaded.root == keeper.config.root {
                    keeper.heartbeat.day_request_budget = reloaded.per_day_requests;
                    keeper.config = reloaded;
                    keeper.heartbeat.note = None;
                } else {
                    keeper.heartbeat.note = Some(
                        "config root changed; a root move needs a restart, keeping the old config"
                            .to_owned(),
                    );
                }
            }
            Err(error) => {
                let note = format!("config reload failed, keeping the last good config: {error}");
                keeper.log.line(&note);
                keeper.heartbeat.note = Some(note);
            }
        }
        let in_backoff = keeper
            .heartbeat
            .backoff_until
            .as_deref()
            .and_then(parse_instant)
            .is_some_and(|until| now < until);
        if !in_backoff && keeper.heartbeat.state == "backoff" {
            "running".clone_into(&mut keeper.heartbeat.state);
            keeper.log.line("rate-limit backoff elapsed; resuming");
        }
        if !in_backoff && keeper.heartbeat.state != "day_budget_idle" {
            let due: Vec<Tap> = keeper
                .config
                .taps
                .iter()
                .filter(|tap| tap_due(tap, &keeper.heartbeat.tap_clocks, now))
                .cloned()
                .collect();
            if !due.is_empty() {
                let interrupted = keeper.cycle(due, &mut sigterm, &mut sigint).await?;
                cycles_run += 1;
                if let Some(signal) = interrupted {
                    shutdown_reason = Some(signal.to_owned());
                }
                if options
                    .max_cycles
                    .is_some_and(|maximum| cycles_run >= maximum)
                {
                    shutdown_reason.get_or_insert_with(|| "max_cycles".to_owned());
                }
            }
        }
        keeper.heartbeat.last_write_at = format_six(OffsetDateTime::now_utc())?;
        write_heartbeat(&keeper.heartbeat_path, &keeper.heartbeat)?;
        if shutdown_reason.is_some() {
            break;
        }
        tokio::select! {
            () = tokio::time::sleep(keeper.config.tick) => {}
            _ = sigterm.recv() => { shutdown_reason = Some("SIGTERM".to_owned()); }
            _ = sigint.recv() => { shutdown_reason = Some("SIGINT".to_owned()); }
        }
    }

    let reason = shutdown_reason.unwrap_or_else(|| "unknown".to_owned());
    let ended_at = format_six(OffsetDateTime::now_utc())?;
    "shutdown".clone_into(&mut keeper.heartbeat.state);
    keeper.heartbeat.shutdown = Some(ShutdownRecord {
        at: ended_at.clone(),
        reason: reason.clone(),
    });
    keeper.heartbeat.last_write_at.clone_from(&ended_at);
    write_heartbeat(&keeper.heartbeat_path, &keeper.heartbeat)?;
    keeper.log.line(&format!(
        "keeper stopped reason={reason} cycles={cycles_run}"
    ));
    drop(keeper.store);
    Ok(serde_json::to_string_pretty(&json!({
        "contract": "joshi.keeper.run_summary.v1",
        "runTag": keeper.run_tag,
        "startedAt": started_at,
        "endedAt": ended_at,
        "cycles": cycles_run,
        "shutdownReason": reason,
        "heartbeat": keeper.heartbeat_path.display().to_string(),
        "catalogRoot": keeper.heartbeat.catalog_root,
        "lastCycle": keeper.heartbeat.last_cycle,
    }))?)
}

/// Poll for an already-delivered signal without waiting. Used between taps so a shutdown request
/// interrupts the cycle at a commit boundary rather than mid-read.
async fn pending_signal(
    sigterm: &mut tokio::signal::unix::Signal,
    sigint: &mut tokio::signal::unix::Signal,
) -> Option<&'static str> {
    tokio::select! {
        biased;
        _ = sigterm.recv() => Some("SIGTERM"),
        _ = sigint.recv() => Some("SIGINT"),
        () = std::future::ready(()) => None,
    }
}

impl Keeper {
    #[allow(clippy::too_many_lines)] // Budgets, taps, gaps and the closure are one decision walk.
    async fn cycle(
        &mut self,
        due: Vec<Tap>,
        sigterm: &mut tokio::signal::unix::Signal,
        sigint: &mut tokio::signal::unix::Signal,
    ) -> Result<Option<&'static str>, Failure> {
        let cycle_started_wall = OffsetDateTime::now_utc();
        let cycle_started = wall(cycle_started_wall)?;
        let started_at = format_six(cycle_started_wall)?;
        self.heartbeat.cycle_ordinal += 1;
        let ordinal = self.heartbeat.cycle_ordinal;
        let mut used = 0_u32;
        let mut gaps: Vec<CycleGap> = Vec::new();
        let mut summaries: Vec<TapSummary> = Vec::new();
        let mut throttled_any = false;
        let mut any_success = false;
        let mut day_idle_entered = false;
        let mut interrupted: Option<&'static str> = None;

        for tap in &due {
            if interrupted.is_none() {
                interrupted = pending_signal(sigterm, sigint).await;
            }
            let now = wall(OffsetDateTime::now_utc())?;
            let key = tap.key();
            if let Some(signal) = interrupted {
                let (lower, upper) = failed_tap_window(self.heartbeat.tap_clocks.get(&key), now)?;
                gaps.push(CycleGap {
                    subject: Some(key.clone()),
                    reason: "keeper_shutdown_before_tap".to_owned(),
                    lower,
                    upper,
                });
                summaries.push(TapSummary {
                    tap: key,
                    status: format!("skipped_shutdown_{signal}"),
                    requests: 0,
                    commit_seq: None,
                    schema_trust: None,
                    throttled: false,
                    detail: None,
                });
                continue;
            }
            if throttled_any {
                let (lower, upper) = failed_tap_window(self.heartbeat.tap_clocks.get(&key), now)?;
                gaps.push(CycleGap {
                    subject: Some(key.clone()),
                    reason: "skipped_after_rate_limit_signal".to_owned(),
                    lower,
                    upper,
                });
                summaries.push(TapSummary {
                    tap: key,
                    status: "skipped_after_throttle".to_owned(),
                    requests: 0,
                    commit_seq: None,
                    schema_trust: None,
                    throttled: false,
                    detail: None,
                });
                continue;
            }
            if self.heartbeat.day_requests_used.saturating_add(tap.cost)
                > self.config.per_day_requests
            {
                day_idle_entered = true;
                let (lower, upper) = failed_tap_window(self.heartbeat.tap_clocks.get(&key), now)?;
                gaps.push(CycleGap {
                    subject: Some(key.clone()),
                    reason: "per_day_request_budget_exhausted".to_owned(),
                    lower,
                    upper,
                });
                summaries.push(TapSummary {
                    tap: key,
                    status: "skipped_day_budget".to_owned(),
                    requests: 0,
                    commit_seq: None,
                    schema_trust: None,
                    throttled: false,
                    detail: None,
                });
                continue;
            }
            if used.saturating_add(tap.cost) > self.config.per_cycle_requests {
                // Deferred, not dropped: the tap stays due and the next cycle affords it first.
                let (lower, upper) = failed_tap_window(self.heartbeat.tap_clocks.get(&key), now)?;
                gaps.push(CycleGap {
                    subject: Some(key.clone()),
                    reason: "deferred_by_per_cycle_request_budget".to_owned(),
                    lower,
                    upper,
                });
                summaries.push(TapSummary {
                    tap: key,
                    status: "deferred_cycle_budget".to_owned(),
                    requests: 0,
                    commit_seq: None,
                    schema_trust: None,
                    throttled: false,
                    detail: None,
                });
                continue;
            }

            let clock = self.heartbeat.tap_clocks.get(&key).cloned();
            let run = match tap.kind {
                TapKind::Wallet { .. } => {
                    run_wallet_tap(
                        tap,
                        &self.config,
                        &mut self.store,
                        clock.as_ref(),
                        tap.cost,
                        CycleStamp {
                            run_tag: &self.run_tag,
                            ordinal,
                            clock_id: &self.clock_id,
                            process_start: self.process_start,
                        },
                    )
                    .await?
                }
                TapKind::Candles | TapKind::Trades => {
                    run_pump_tap(
                        tap,
                        &self.config,
                        &mut self.store,
                        &self.identity,
                        clock.as_ref(),
                        self.process_start,
                    )
                    .await?
                }
            };
            used = used.saturating_add(run.requests);
            self.heartbeat.day_requests_used = self
                .heartbeat
                .day_requests_used
                .saturating_add(run.requests);
            let attempt_at = format_six(OffsetDateTime::now_utc())?;
            let entry = self.heartbeat.tap_clocks.entry(key.clone()).or_default();
            entry.last_attempt_at = Some(attempt_at.clone());
            if run.success {
                entry.last_success_at = Some(attempt_at);
                any_success = true;
            }
            if let Some(seq) = &run.commit_seq {
                entry.last_commit_seq = Some(seq.clone());
            }
            if let Some(newest) = &run.newest_wallet_signature {
                entry.newest_wallet_signature = Some(newest.clone());
            }
            throttled_any |= run.throttled;
            gaps.extend(run.gaps.iter().cloned());
            let label = tap
                .label
                .as_deref()
                .map_or_else(String::new, |value| format!(" ({value})"));
            self.log.line(&format!(
                "cycle {ordinal} tap {key}{label}: {} requests={} commitSeq={} {}",
                run.status,
                run.requests,
                run.commit_seq.as_deref().unwrap_or("-"),
                run.detail.as_deref().unwrap_or(""),
            ));
            summaries.push(TapSummary {
                tap: key,
                status: run.status.to_owned(),
                requests: run.requests,
                commit_seq: run.commit_seq,
                schema_trust: run.schema_trust,
                throttled: run.throttled,
                detail: run.detail,
            });
        }

        let cycle_ended_wall = OffsetDateTime::now_utc();
        let cycle_ended = wall(cycle_ended_wall)?;
        if day_idle_entered {
            "day_budget_idle".clone_into(&mut self.heartbeat.state);
            gaps.push(CycleGap {
                subject: None,
                reason: "keeper_day_budget_idle_until_utc_midnight".to_owned(),
                lower: Boundary::Wall { value: cycle_ended },
                upper: Some(Boundary::Wall {
                    value: wall(next_utc_midnight(cycle_ended_wall)?)?,
                }),
            });
            self.log.line(&format!(
                "per-day request budget exhausted ({} used of {}); idling until UTC midnight",
                self.heartbeat.day_requests_used, self.config.per_day_requests
            ));
        }
        if throttled_any {
            self.heartbeat.consecutive_throttles =
                self.heartbeat.consecutive_throttles.saturating_add(1);
            let seconds = backoff_seconds(
                self.heartbeat.consecutive_throttles,
                self.config.backoff_initial_seconds,
                self.config.backoff_max_seconds,
            );
            let until = cycle_ended_wall + time::Duration::seconds(i64::try_from(seconds)?);
            self.heartbeat.backoff_until = Some(format_six(until)?);
            "backoff".clone_into(&mut self.heartbeat.state);
            gaps.push(CycleGap {
                subject: None,
                reason: "provider_rate_limit_backoff".to_owned(),
                lower: Boundary::Wall { value: cycle_ended },
                upper: Some(Boundary::Wall {
                    value: wall(until)?,
                }),
            });
            self.log.line(&format!(
                "provider rate-limit signal; backing off {seconds}s (consecutive={})",
                self.heartbeat.consecutive_throttles
            ));
        } else if any_success {
            self.heartbeat.consecutive_throttles = 0;
            self.heartbeat.backoff_until = None;
        }

        let state = if interrupted.is_some() {
            "keeper_cycle_interrupted_by_shutdown"
        } else if throttled_any {
            "keeper_cycle_entered_rate_limit_backoff"
        } else if day_idle_entered {
            "keeper_cycle_entered_day_budget_idle"
        } else {
            "keeper_cycle_completed"
        };
        let closure = commit_cycle_closure(
            &mut self.store,
            &CycleClosure {
                run_tag: &self.run_tag,
                ordinal,
                started: cycle_started,
                ended: cycle_ended,
                state,
                gaps: &gaps,
                clock_id: &self.clock_id,
                process_start: self.process_start,
            },
        )?;
        self.log.line(&format!(
            "cycle {ordinal} closed: state={state} requests={used} gaps={} closureCommitSeq={}",
            gaps.len(),
            closure.commit_seq
        ));
        self.heartbeat.last_cycle = Some(CycleRecord {
            ordinal,
            started_at,
            ended_at: format_six(cycle_ended_wall)?,
            requests_used: used,
            taps: summaries,
            gaps_recorded: u32::try_from(gaps.len()).unwrap_or(u32::MAX),
            closure_commit_seq: Some(closure.commit_seq),
            state: state.to_owned(),
        });
        Ok(interrupted)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::{Connection, OpenFlags};

    fn repo_path(relative: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join(relative)
    }

    /// The starter config Ember edits must parse, validate, and resolve its review artifacts.
    #[test]
    fn starter_config_parses_and_names_both_watched_mints_and_the_wallet() {
        let config = load_config(&repo_path("ops/keeper.toml")).expect("starter config loads");
        assert!(
            config
                .taps
                .iter()
                .any(|tap| matches!(tap.kind, TapKind::Wallet { .. })
                    && tap.subject == "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ")
        );
        for mint in [
            "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
            "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
        ] {
            assert!(
                config
                    .taps
                    .iter()
                    .any(|tap| tap.kind == TapKind::Candles && tap.subject == mint)
            );
            assert!(
                config
                    .taps
                    .iter()
                    .any(|tap| tap.kind == TapKind::Trades && tap.subject == mint)
            );
        }
        for tap in &config.taps {
            assert!(
                tap.cadence_seconds >= MINIMUM_CADENCE_SECONDS,
                "cadences are minutes"
            );
            assert!(tap.cost <= config.per_cycle_requests);
        }
        assert!(!config.candles_review.is_empty());
        assert!(!config.trades_review.is_empty());
    }

    #[test]
    fn config_refusals_are_stated_before_anything_runs() {
        let dir = tempfile::tempdir().expect("temp dir");
        let review = dir.path().join("review.json");
        fs::write(&review, b"{}").expect("review fixture");
        let write = |body: String| {
            let path = dir.path().join("keeper.toml");
            fs::write(&path, body).expect("config written");
            path
        };
        let base = |cadence: &str, taps: &str, budget: u32| {
            format!(
                "root = \"state\"\n[budgets]\nper_cycle_requests = {budget}\nper_day_requests = 100\n\
                 [taps]\ncandles_review = \"review.json\"\ntrades_review = \"review.json\"\n\
                 [[mints]]\nmint = \"XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump\"\n\
                 taps = [{taps}]\n{cadence}\n"
            )
        };
        // A cadence in seconds territory is refused: this loop is polite by construction.
        let refused = load_config(&write(base(
            "candles_cadence_minutes = 0",
            "\"candles\"",
            8,
        )));
        assert!(refused.is_err());
        // An unknown tap name is refused rather than ignored.
        let refused = load_config(&write(base(
            "candles_cadence_minutes = 5",
            "\"kandles\"",
            8,
        )));
        assert!(refused.is_err());
        // A cycle budget that cannot afford the heaviest tap is a standing lie; refused.
        let refused = load_config(&write(
            "root = \"state\"\n[budgets]\nper_cycle_requests = 2\nper_day_requests = 100\n\
             [wallet]\naddress = \"Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ\"\ncadence_minutes = 30\n\
             [taps]\ncandles_review = \"review.json\"\ntrades_review = \"review.json\"\n"
                .to_owned(),
        ));
        assert!(refused.is_err());
        // A mint that is not a 32-byte base58 address is refused.
        let refused = load_config(&write(
            base("candles_cadence_minutes = 5", "\"candles\"", 8)
                .replace("XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump", "not-base58!"),
        ));
        assert!(refused.is_err());
        // An interval the provider does not accept is refused before it costs a request.
        let refused = load_config(&write(
            "root = \"state\"\n[budgets]\nper_cycle_requests = 8\nper_day_requests = 100\n\
             [taps]\ncandles_review = \"review.json\"\ntrades_review = \"review.json\"\ncandles_interval = \"2s\"\n\
             [[mints]]\nmint = \"XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump\"\n\
             taps = [\"candles\"]\ncandles_cadence_minutes = 5\n"
                .to_owned(),
        ));
        assert!(refused.is_err());
    }

    #[test]
    fn cadence_is_measured_from_the_last_attempt_and_backoff_doubles_to_its_cap() {
        let tap = Tap {
            kind: TapKind::Candles,
            subject: "mint".to_owned(),
            label: None,
            cadence_seconds: 600,
            cost: 1,
        };
        let now = OffsetDateTime::from_unix_timestamp(1_786_882_538).expect("clock");
        let mut clocks = BTreeMap::new();
        assert!(tap_due(&tap, &clocks, now), "never-attempted taps are due");
        let recent = format_six(now - time::Duration::seconds(300)).expect("stamp");
        clocks.insert(
            tap.key(),
            TapClock {
                last_attempt_at: Some(recent),
                ..TapClock::default()
            },
        );
        assert!(
            !tap_due(&tap, &clocks, now),
            "inside the cadence nothing is due"
        );
        let stale = format_six(now - time::Duration::seconds(601)).expect("stamp");
        clocks.get_mut(&tap.key()).expect("clock").last_attempt_at = Some(stale);
        assert!(
            tap_due(&tap, &clocks, now),
            "past the cadence the tap is due"
        );

        assert_eq!(backoff_seconds(1, 120, 3_600), 120);
        assert_eq!(backoff_seconds(2, 120, 3_600), 240);
        assert_eq!(backoff_seconds(6, 120, 3_600), 3_600, "capped");
        assert_eq!(
            backoff_seconds(60, 120, 3_600),
            3_600,
            "shift stays bounded"
        );
    }

    #[test]
    fn wallet_sweep_memory_selects_only_new_signatures() {
        let rows: Vec<String> = ["e", "d", "c", "b", "a"]
            .iter()
            .map(|value| (*value).to_owned())
            .collect();
        let (new_rows, seen) = new_signatures_since(&rows, None);
        assert_eq!(new_rows.len(), 5, "first sweep takes the whole page");
        assert!(seen);
        let (new_rows, seen) = new_signatures_since(&rows, Some("c"));
        assert_eq!(new_rows, ["e".to_owned(), "d".to_owned()]);
        assert!(seen);
        let (new_rows, seen) = new_signatures_since(&rows, Some("zz"));
        assert_eq!(
            new_rows.len(),
            5,
            "memory off the page means the page is all new"
        );
        assert!(!seen, "and the caller records the possible gap");
    }

    #[test]
    fn day_rollover_resets_usage_and_a_same_day_restart_adopts_it() {
        let now = OffsetDateTime::from_unix_timestamp(1_786_882_538).expect("clock");
        let dir = tempfile::tempdir().expect("temp dir");
        let config = minimal_config(dir.path());
        let fresh = fresh_heartbeat(
            &config,
            Path::new("/config"),
            "run",
            "2026-08-22T00:00:00.000000Z",
            now,
        );
        let mut previous = fresh.clone();
        previous.day_requests_used = 77;
        previous.cycle_ordinal = 9;
        previous.utc_day = utc_day(now);
        previous
            .tap_clocks
            .insert("candles:mint".to_owned(), TapClock::default());
        let adopted = adopt_heartbeat(fresh.clone(), Some(previous.clone()), now);
        assert_eq!(
            adopted.day_requests_used, 77,
            "same-day restart keeps the spend"
        );
        assert_eq!(adopted.cycle_ordinal, 9);
        assert!(adopted.tap_clocks.contains_key("candles:mint"));
        previous.utc_day = "2026-08-21".to_owned();
        let rolled = adopt_heartbeat(fresh, Some(previous), now);
        assert_eq!(rolled.day_requests_used, 0, "a new day starts a new budget");
        assert!(
            rolled.tap_clocks.contains_key("candles:mint"),
            "cadence memory survives"
        );
        let absent = adopt_heartbeat(
            fresh_heartbeat(
                &config,
                Path::new("/config"),
                "run",
                "2026-08-22T00:00:00.000000Z",
                now,
            ),
            None,
            now,
        );
        assert!(
            absent.note.is_some(),
            "a missing heartbeat is said, not silent"
        );
    }

    #[test]
    fn heartbeat_is_replaced_atomically_and_reads_back() {
        let dir = tempfile::tempdir().expect("temp dir");
        let path = dir.path().join("heartbeat.json");
        let now = OffsetDateTime::from_unix_timestamp(1_786_882_538).expect("clock");
        let config = minimal_config(dir.path());
        let mut heartbeat = fresh_heartbeat(
            &config,
            Path::new("/config"),
            "run",
            "2026-08-22T00:00:00.000000Z",
            now,
        );
        heartbeat.day_requests_used = 5;
        write_heartbeat(&path, &heartbeat).expect("first write");
        heartbeat.day_requests_used = 6;
        write_heartbeat(&path, &heartbeat).expect("replacement write");
        let read = read_heartbeat(&path).expect("heartbeat reads back");
        assert_eq!(read.day_requests_used, 6);
        assert_eq!(read.contract, HEARTBEAT_CONTRACT);
        assert!(
            !path.with_extension("json.tmp").exists(),
            "no temp file lingers"
        );
    }

    /// A cycle that failed a tap and skipped another leaves one window and its explicit gaps in
    /// the durable catalog: an unchanging catalog is distinguishable from an unchanging market.
    #[test]
    fn cycle_closure_commits_a_window_and_every_gap() {
        let dir = tempfile::tempdir().expect("temp dir");
        let mut store = SqliteStore::open(
            keeper_store_config(dir.path()).expect("store config"),
            StoreMode::SingleWriter,
        )
        .expect("store opens");
        let started = wall(OffsetDateTime::from_unix_timestamp(1_786_882_000).expect("clock"))
            .expect("timestamp");
        let ended = wall(OffsetDateTime::from_unix_timestamp(1_786_882_060).expect("clock"))
            .expect("timestamp");
        store.migrate(started).expect("migrations");
        let gaps = vec![
            CycleGap {
                subject: Some("candles:mint".to_owned()),
                reason: "deferred_by_per_cycle_request_budget".to_owned(),
                lower: Boundary::Wall { value: started },
                upper: Some(Boundary::Wall { value: ended }),
            },
            CycleGap {
                subject: Some("wallet:addr".to_owned()),
                reason: "wallet_read_failed".to_owned(),
                lower: Boundary::Unknown {
                    reason: OpenVariant::known("no prior landing").expect("variant"),
                },
                upper: Some(Boundary::Wall { value: ended }),
            },
        ];
        let receipt = commit_cycle_closure(
            &mut store,
            &CycleClosure {
                run_tag: "keeper-test-1",
                ordinal: 1,
                started,
                ended,
                state: "keeper_cycle_completed",
                gaps: &gaps,
                clock_id: "clock-test",
                process_start: Instant::now(),
            },
        )
        .expect("closure commits");
        assert_eq!(receipt.admitted.coverage_windows, "1");
        assert_eq!(receipt.admitted.coverage_gaps, "2");
        let second = commit_cycle_closure(
            &mut store,
            &CycleClosure {
                run_tag: "keeper-test-1",
                ordinal: 2,
                started,
                ended,
                state: "keeper_cycle_completed",
                gaps: &[],
                clock_id: "clock-test",
                process_start: Instant::now(),
            },
        )
        .expect("second closure commits");
        assert!(
            second.commit_seq.parse::<i64>().expect("seq")
                > receipt.commit_seq.parse::<i64>().expect("seq"),
            "commit_seq advances cycle over cycle"
        );
        drop(store);
        let connection = Connection::open_with_flags(
            dir.path().join("catalog/catalog.sqlite"),
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("read-only reopen");
        let windows: i64 = connection
            .query_row("SELECT COUNT(*) FROM coverage_window", [], |row| row.get(0))
            .expect("windows");
        let gap_rows: i64 = connection
            .query_row("SELECT COUNT(*) FROM coverage_gap", [], |row| row.get(0))
            .expect("gaps");
        assert_eq!(windows, 2);
        assert_eq!(gap_rows, 2);
    }

    /// The pump tap is the existing product-read admission: a real captured outcome and its
    /// promoted review commit into the keeper catalog and read back with a schema-trust decision.
    #[test]
    fn a_captured_candle_outcome_commits_through_the_shared_admission_path() {
        let outcome_bytes = fs::read(repo_path(
            "crates/joshi-pump-api/fixtures/candles_live_outcome_v1.json",
        ))
        .expect("candles fixture");
        let review_bytes = fs::read(repo_path(
            "crates/joshi-pump-api/fixtures/schema_review_candles_v1.json",
        ))
        .expect("candles review");
        let dir = tempfile::tempdir().expect("temp dir");
        let mut store = SqliteStore::open(
            keeper_store_config(dir.path()).expect("store config"),
            StoreMode::SingleWriter,
        )
        .expect("store opens");
        store
            .migrate(wall(OffsetDateTime::now_utc()).expect("clock"))
            .expect("migrations");
        let admitted =
            admit_pump_outcome_bytes(&mut store, &outcome_bytes, &review_bytes, Instant::now())
                .expect("fixture admits");
        assert!(admitted.completed);
        assert_eq!(
            admitted.prepared.decision.outcome,
            SchemaTrustOutcome::Promoted
        );
        assert!(
            admitted
                .receipt
                .commit_seq
                .parse::<i64>()
                .expect("commit seq")
                >= 1
        );
        assert_ne!(admitted.receipt.admitted.observations, "0");
    }

    fn minimal_config(root: &Path) -> KeeperConfig {
        KeeperConfig {
            root: root.to_path_buf(),
            key_file: PathBuf::from(DEFAULT_HELIUS_KEY_PATH),
            per_cycle_requests: 8,
            per_day_requests: 100,
            tick: Duration::from_secs(30),
            backoff_initial_seconds: 120,
            backoff_max_seconds: 3_600,
            candles_interval: DEFAULT_CANDLES_INTERVAL.to_owned(),
            candles_limit: DEFAULT_CANDLES_LIMIT,
            trades_limit: DEFAULT_TRADES_LIMIT,
            candles_review: Vec::new(),
            trades_review: Vec::new(),
            taps: Vec::new(),
        }
    }
}
