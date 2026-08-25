//! The availability clock: WHEN a callout became visible, as distinct from when it occurred.
//!
//! ```text
//! availability_clock run     --config ops/availability.toml [--minutes n] [--mints <csv>]
//! availability_clock analyse --run-dir state/availability/<run-id>
//! ```
//!
//! Every callout study so far has had to caveat the same missing instant: the provider states an
//! occurrence clock (`createdAt`) and nothing anywhere states when the fact became KNOWABLE to a
//! consumer. This process measures that instant two ways at once, live, for a small watched mint
//! set:
//!
//! 1. the per-community push socket (`wss://api.coin-communities.xyz/.../ws?ticket=...`), whose
//!    frame ARRIVAL instant — stamped monotonic + wall, the same discipline as acquisition
//!    envelopes — is an UPPER BOUND on availability (the fact was available no later than this;
//!    the true instant is earlier and unobserved), and
//! 2. the REST `community_callouts` poll on the keeper's own hot cadence, whose next-fetch
//!    arrival is when a poll-or-lose consumer would actually first hold the fact.
//!
//! The difference between the two, per callout, is the availability gap the polling cadence
//! actually pays; a callout on the socket that never reaches a later poll is what the fixed
//! newest-50 window actually loses.
//!
//! # Process boundary
//!
//! A SEPARATE process from the keeper, writing its own durable record under `state/availability/`.
//! It never opens the keeper's catalog, never touches the keeper's writer lock, and reads only the
//! keeper's config and hot-requests file (both re-read every tick, keeper-style: a broken edit
//! keeps the last good values with a heartbeat note). Read-only routes plus the read-only ws
//! subscription; no posting, no likes, no moderation acts; the wallet signs only the printable
//! authentication challenge, inside `joshi-pump-api`'s guarded signer.
//!
//! # Reconnect-and-restate discipline (ported from `coin_tape_live.rs` v2 receipts)
//!
//! Each socket connection is its own SESSION with its own claimed coverage window; the holes are
//! durable gaps naming their cause; sessions plus gaps tile the run window exactly
//! (`covered + unobserved == planned`, by construction of the complement walk). A REFUSAL at the
//! ticket mint or the upgrade handshake is terminal and never retried; a provider that accepted a
//! socket and then hiccuped is reconnected to under a bounded doubling backoff. One deliberate
//! deviation from the tape recorder, stated rather than hidden: a `429` at the FIRST connect is
//! retried like weather rather than aborting the run, because the shared product bucket is
//! measured to saturate routinely and a first-mint `429` is the bucket speaking, not the provider
//! refusing this subscription.
//!
//! # Clocks — the record contract's heart
//!
//! * Arrival: wall UTC with six-digit microseconds plus monotonic nanoseconds under a named clock
//!   id, stamped by this process at receive. THE ARRIVAL INSTANT IS THE AVAILABILITY UPPER BOUND,
//!   never the occurrence instant, and after a coverage gap it does not even bound tightly.
//! * Provider occurrence claim: `createdAt` is retained VERBATIM as text. On this service it is
//!   ISO-8601 UTC WITH MICROSECONDS, a different clock family from the epoch-millisecond callout
//!   routes on frontend-api-v3; nothing here converts silently, and every derived duration in the
//!   analysis names the cross-clock caveat.
//!
//! # Budget
//!
//! Everything this process sends toward the community origin — handshake POSTs, refreshes, ticket
//! mints, REST polls — shares the provider's ~1 rps GLOBAL product-key bucket with every pump.fun
//! visitor. One request at a time through a single pacer, minimum-gap spaced, `429`-aware with
//! doubling backoff, with an absolute run-total ceiling; the spend is ledgered per kind in the
//! receipt.

use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fs,
    io::Write as _,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use base64::Engine as _;
use clap::{Parser, Subcommand};
use futures_util::{SinkExt as _, StreamExt as _};
use joshi_pump_api::{
    ClientConfig, CommunityAuthError, CommunitySession, CommunitySessionProvider,
    CommunityWalletSigner, FetchOutcome, IdentityStore, LogicalRequest, NoSession, PumpApiClient,
    RequestParameters, RouteId, RouteSpec, SessionProvider,
};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest as _, Sha256};
use time::OffsetDateTime;
use tokio_tungstenite::tungstenite::{Message, client::IntoClientRequest as _};

const EVENTS_CONTRACT: &str = "joshi.availability.events.v1";
const RECEIPT_CONTRACT: &str = "joshi.availability.run_receipt.v1";
const ANALYSIS_CONTRACT: &str = "joshi.availability.analysis.v1";
const HOT_REQUESTS_CONTRACT: &str = "joshi.attention.hot_requests.v1";
/// The one client->server frame the protocol names. Nothing else is ever sent on a socket.
const PING_BODY: &str = r#"{"eventType":"ping"}"#;
/// The community push channel's provider clock family, restated on every frame record so the
/// unit-mismatch trap (ISO-8601 micros here, epoch millis on frontend-api-v3 callout routes)
/// stays declared beside every value it could bite.
const PROVIDER_CLOCK_NOTE: &str = "createdAt retained verbatim: ISO-8601 UTC with microseconds (coin-communities family); \
     DISTINCT from the epoch-millisecond clocks on frontend-api-v3 callout routes; never joined \
     or converted silently";
const ARRIVAL_CLOCK_NOTE: &str = "arrival is the instant this process received the frame: an UPPER BOUND on availability, \
     never the occurrence instant; after a coverage gap it does not even bound tightly";
/// Wall-versus-monotonic disagreement, inside one connection, read as a host suspend.
const SUSPEND_SKEW_MICROS: i64 = 5_000_000;
/// Ceiling on verbatim bytes retained per ws frame; longer frames keep a prefix plus digest.
const FRAME_RETAIN_MAX_BYTES: usize = 512 * 1024;
/// The head of a chain spent minting, connecting, and asking before the provider's first word.
const CAUSE_AWAITING_FIRST_LIVENESS: &str = "awaiting_first_liveness";
/// Time spent between sockets: backoff, ticket mint, handshake.
const CAUSE_BACKOFF_WAIT: &str = "backoff_wait";
/// How often the watch inputs are re-read and the heartbeat rewritten.
const TICK_SECONDS: u64 = 30;
const MAX_CONFIG_BYTES: u64 = 256 * 1024;

type Failure = Box<dyn Error>;

fn main() {
    if let Err(error) = dispatch(Cli::parse()) {
        eprintln!("availability_clock failed: {error}");
        std::process::exit(1);
    }
}

fn dispatch(cli: Cli) -> Result<(), Failure> {
    match cli.command {
        Command::Run {
            config,
            minutes,
            mints,
        } => {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()?;
            let receipt = runtime.block_on(run(&config, minutes, mints.as_deref()))?;
            println!("{receipt}");
        }
        Command::Analyse { run_dir } => println!("{}", analyse(&run_dir)?),
    }
    Ok(())
}

#[derive(Debug, Parser)]
#[command(name = "availability_clock")]
#[command(about = "Measure WHEN community callouts become visible: ws arrival vs REST poll")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// One bounded live run: sockets + comparison polls, everything durable under the state root.
    Run {
        /// Availability config file; see ops/availability.toml.
        #[arg(long)]
        config: PathBuf,
        /// Planned run length. The wall clock is the only open-ended budget this replaces.
        #[arg(long, default_value_t = 150)]
        minutes: u64,
        /// Comma-separated mint override; absent means hot-requests + keeper watch set.
        #[arg(long)]
        mints: Option<String>,
    },
    /// Reopen one run's durable record and derive the availability-gap distribution from it.
    Analyse {
        #[arg(long = "run-dir")]
        run_dir: PathBuf,
    },
}

// ---------------------------------------------------------------------------
// Configuration: this consumer's own file (strict), the keeper's file (tolerant).
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct AvailabilityConfigFile {
    keeper_config: String,
    root: String,
    wallet_key_file: String,
    sockets: SocketsSection,
    rest_poll: RestPollSection,
    budgets: BudgetsSection,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SocketsSection {
    max_concurrent: usize,
    ping_interval_seconds: u64,
    inactivity_ceiling_seconds: u64,
    reconnect_max_attempts: u32,
    reconnect_backoff_initial_seconds: u64,
    reconnect_backoff_cap_seconds: u64,
    /// Per-mint inbound ceilings; absent means the generous defaults below.
    max_frames: Option<usize>,
    max_bytes: Option<usize>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RestPollSection {
    cadence_minutes: u64,
    first_poll_delay_seconds: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BudgetsSection {
    min_gap_seconds: u64,
    max_bucket_requests: u32,
}

/// The loaded config with every relative path resolved against the config file's directory.
#[derive(Clone, Debug)]
struct AvailabilityConfig {
    config_path: PathBuf,
    keeper_config: PathBuf,
    root: PathBuf,
    wallet_key_file: PathBuf,
    sockets: SocketsSection,
    rest_poll: RestPollSection,
    budgets: BudgetsSection,
}

fn load_config(path: &Path) -> Result<AvailabilityConfig, Failure> {
    let bytes = read_bounded(path, MAX_CONFIG_BYTES, "availability config")?;
    let file: AvailabilityConfigFile = toml::from_str(std::str::from_utf8(&bytes)?)?;
    let base = path.parent().unwrap_or_else(|| Path::new("."));
    if file.sockets.max_concurrent == 0 || file.sockets.max_concurrent > 3 {
        return Err(
            "sockets.max_concurrent must be 1..=3: each socket costs ticket mints and \
                    reconnect weather against the shared global bucket"
                .into(),
        );
    }
    if file.sockets.inactivity_ceiling_seconds <= file.sockets.ping_interval_seconds {
        return Err(
            "sockets.inactivity_ceiling_seconds must exceed ping_interval_seconds, or \
                    every quiet community reads as a dead socket"
                .into(),
        );
    }
    if file.budgets.min_gap_seconds == 0 {
        return Err(
            "budgets.min_gap_seconds must be at least 1: the product bucket is a shared \
                    ~1 rps GLOBAL budget"
                .into(),
        );
    }
    Ok(AvailabilityConfig {
        config_path: path.to_path_buf(),
        keeper_config: base.join(&file.keeper_config),
        root: base.join(&file.root),
        wallet_key_file: PathBuf::from(&file.wallet_key_file),
        sockets: file.sockets,
        rest_poll: file.rest_poll,
        budgets: file.budgets,
    })
}

/// The subset of the keeper's config this consumer reads, parsed TOLERANTLY: the keeper's own
/// parser is `deny_unknown_fields` over the whole file, but this reader is a guest and must keep
/// working as the keeper's config grows.
#[derive(Debug, Deserialize)]
struct KeeperConfigSubset {
    root: Option<String>,
    community_key_file: Option<String>,
    #[serde(default)]
    mints: Vec<KeeperMintSubset>,
}

#[derive(Debug, Deserialize)]
struct KeeperMintSubset {
    mint: Option<String>,
    label: Option<String>,
    #[serde(default)]
    taps: Vec<String>,
}

/// What the keeper's config contributes: the community product key path, the hot-requests file
/// location, and the watch-set mints that already tap community callouts.
#[derive(Clone, Debug, Eq, PartialEq)]
struct KeeperInputs {
    community_key_file: PathBuf,
    hot_requests_file: PathBuf,
    watch_mints: Vec<(String, Option<String>)>,
}

fn read_keeper_inputs(path: &Path) -> Result<KeeperInputs, Failure> {
    let bytes = read_bounded(path, MAX_CONFIG_BYTES, "keeper config")?;
    let subset: KeeperConfigSubset = toml::from_str(std::str::from_utf8(&bytes)?)?;
    let base = path.parent().unwrap_or_else(|| Path::new("."));
    let root = subset
        .root
        .as_deref()
        .ok_or("keeper config names no root")?;
    let key = subset
        .community_key_file
        .as_deref()
        .ok_or("keeper config names no community_key_file")?;
    let watch_mints = subset
        .mints
        .into_iter()
        .filter(|entry| entry.taps.iter().any(|tap| tap == "community_callouts"))
        .filter_map(|entry| entry.mint.map(|mint| (mint, entry.label)))
        .collect();
    Ok(KeeperInputs {
        community_key_file: base.join(key),
        hot_requests_file: base.join(root).join("hot-requests.json"),
        watch_mints,
    })
}

/// One entry of the hot-requests file, tolerant exactly like the keeper's reader: the file is
/// core's, and unknown fields must never break this guest.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct HotEntry {
    mint: Option<String>,
    expires_at: Option<String>,
    #[serde(flatten)]
    _rest: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct HotFile {
    contract: Option<String>,
    #[serde(default)]
    requests: Vec<HotEntry>,
    #[serde(flatten)]
    _rest: BTreeMap<String, Value>,
}

/// Unexpired hot mints, freshest expiry first. A missing file is an empty set (the keeper treats
/// it the same); a malformed file or wrong contract is an error the caller downgrades to
/// last-good-with-a-note.
fn read_hot_mints(path: &Path, now: OffsetDateTime) -> Result<Vec<String>, Failure> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let bytes = read_bounded(path, MAX_CONFIG_BYTES, "hot-requests file")?;
    let file: HotFile = serde_json::from_slice(&bytes)?;
    if file.contract.as_deref() != Some(HOT_REQUESTS_CONTRACT) {
        return Err(format!(
            "hot-requests file states contract {:?}, not {HOT_REQUESTS_CONTRACT}",
            file.contract
        )
        .into());
    }
    let mut live: Vec<(OffsetDateTime, String)> = Vec::new();
    for entry in file.requests {
        let (Some(mint), Some(expires)) = (entry.mint, entry.expires_at) else {
            continue;
        };
        let Ok(expiry) =
            OffsetDateTime::parse(&expires, &time::format_description::well_known::Rfc3339)
        else {
            continue;
        };
        if expiry > now {
            live.push((expiry, mint));
        }
    }
    live.sort_by_key(|(expiry, _)| std::cmp::Reverse(*expiry));
    Ok(live.into_iter().map(|(_, mint)| mint).collect())
}

/// The watch set: hot mints first (freshest attention first), then the keeper watch set's
/// community mints in file order, deduplicated, capped.
fn derive_watch_set(hot: &[String], watch: &[(String, Option<String>)], cap: usize) -> Vec<String> {
    let mut seen = BTreeSet::new();
    let mut set = Vec::new();
    for mint in hot
        .iter()
        .cloned()
        .chain(watch.iter().map(|(mint, _)| mint.clone()))
    {
        if set.len() >= cap {
            break;
        }
        if seen.insert(mint.clone()) {
            set.push(mint);
        }
    }
    set
}

// ---------------------------------------------------------------------------
// Clocks and the durable record.
// ---------------------------------------------------------------------------

const WALL_FORMAT: &[time::format_description::BorrowedFormatItem<'static>] = time::macros::format_description!(
    "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
);

fn wall_string(at: OffsetDateTime) -> Result<String, Failure> {
    Ok(at.format(WALL_FORMAT)?)
}

fn unix_micros(at: OffsetDateTime) -> Result<i64, Failure> {
    Ok(i64::try_from(at.unix_timestamp_nanos() / 1_000)?)
}

/// The run's clock authority: one monotonic origin, one named clock id, stamped onto every record
/// exactly the way acquisition envelopes stamp theirs.
struct RunClock {
    process_start: Instant,
    clock_id: String,
}

impl RunClock {
    fn new(run_id: &str) -> Self {
        Self {
            process_start: Instant::now(),
            clock_id: format!("mono:availability:{}:{run_id}", std::process::id()),
        }
    }

    fn stamp(&self) -> Result<(String, i64, u64), Failure> {
        let wall = OffsetDateTime::now_utc();
        let mono = u64::try_from(self.process_start.elapsed().as_nanos())?;
        Ok((wall_string(wall)?, unix_micros(wall)?, mono))
    }
}

/// The append-only durable record: one JSON value per line, fsynced per append, so a crash keeps
/// every acknowledged line and at worst truncates a half-written tail the reader skips.
struct Recorder {
    file: fs::File,
}

impl Recorder {
    fn open(path: &Path) -> Result<Self, Failure> {
        let file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?;
        Ok(Self { file })
    }

    fn append(&mut self, value: &Value) -> Result<(), Failure> {
        let mut line = serde_json::to_vec(value)?;
        line.push(b'\n');
        self.file.write_all(&line)?;
        self.file.sync_data()?;
        Ok(())
    }
}

/// Shared handle: the std mutex is held only across the synchronous write+fsync, never an await.
#[derive(Clone)]
struct Journal {
    recorder: Arc<Mutex<Recorder>>,
    clock: Arc<RunClock>,
}

impl Journal {
    fn record(&self, mut value: Value) -> Result<(), Failure> {
        let (wall, micros, mono) = self.clock.stamp()?;
        if let Some(object) = value.as_object_mut() {
            object.insert("recordedAt".to_owned(), json!(wall));
            object.insert("recordedAtUnixUs".to_owned(), json!(micros));
            object.insert("recordedMonotonicNs".to_owned(), json!(mono.to_string()));
        }
        self.recorder
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .append(&value)
    }
}

/// Write a whole document durably under the pending/rename idiom.
fn write_renamed(path: &Path, value: &Value) -> Result<(), Failure> {
    let pending = path.with_extension("pending");
    let bytes = serde_json::to_vec_pretty(value)?;
    let mut file = fs::File::create(&pending)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&pending, path)?;
    Ok(())
}

// ---------------------------------------------------------------------------
// The shared-bucket pacer and spend ledger.
// ---------------------------------------------------------------------------

/// Everything sent toward the community origin goes through here, one request at a time: a
/// minimum gap, a doubling `429` backoff, and an absolute run-total ceiling. The ledger counts
/// spend per kind so the receipt can restate the whole bill.
struct BucketPacer {
    state: tokio::sync::Mutex<PacerState>,
    min_gap: Duration,
    ceiling: u32,
    /// No reservation may START past this instant. MEASURED 2026-08-25 (run T062645Z): without
    /// it, three weathering chains held queued reservations whose 10-minute backoffs stacked
    /// ~50 minutes past the planned end, so teardown overran the window and spent throttled
    /// mints after the run was over. A reservation past the deadline is refused as spend
    /// exhaustion — the window is over, and the chain answers with its wall-clock stop.
    deadline: Instant,
}

struct PacerState {
    next_allowed: Instant,
    backoff: Duration,
    spent: u32,
    by_kind: BTreeMap<String, u32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PacerRefusal {
    /// The absolute run-total request ceiling is reached.
    CeilingReached,
    /// The reservation would start after the planned window; nothing may spend it.
    WindowOver,
}

/// How a pacer refusal reads as a session end: a spent ceiling is the budget speaking, a
/// past-deadline slot is the planned window having ended.
const fn pacer_end(refusal: PacerRefusal) -> SessionEnd {
    match refusal {
        PacerRefusal::CeilingReached => SessionEnd::SpendExhausted,
        PacerRefusal::WindowOver => SessionEnd::PlannedWindowReached,
    }
}

impl BucketPacer {
    fn new(min_gap: Duration, ceiling: u32, deadline: Instant) -> Self {
        Self {
            state: tokio::sync::Mutex::new(PacerState {
                next_allowed: Instant::now(),
                backoff: Duration::ZERO,
                spent: 0,
                by_kind: BTreeMap::new(),
            }),
            min_gap,
            ceiling,
            deadline,
        }
    }

    /// Wait until the bucket allows `count` more requests of `kind`, then charge them. The lock
    /// is held only to reserve the slot; the wait happens outside it.
    async fn acquire(&self, kind: &str, count: u32) -> Result<(), PacerRefusal> {
        let wait_until = {
            let mut state = self.state.lock().await;
            if state.spent.saturating_add(count) > self.ceiling {
                return Err(PacerRefusal::CeilingReached);
            }
            let start = state.next_allowed.max(Instant::now()) + state.backoff;
            if start > self.deadline {
                // The slot would begin after the planned window: nothing may spend it. Nothing
                // was charged and the queue is left untouched.
                return Err(PacerRefusal::WindowOver);
            }
            state.spent += count;
            *state.by_kind.entry(kind.to_owned()).or_insert(0) += count;
            state.next_allowed = start + self.min_gap.saturating_mul(count);
            start
        };
        tokio::time::sleep_until(tokio::time::Instant::from_std(wait_until)).await;
        Ok(())
    }

    /// Feed the outcome back: a throttle doubles the shared backoff (capped at ten minutes), a
    /// success clears it.
    async fn report(&self, throttled: bool) {
        let mut state = self.state.lock().await;
        if throttled {
            state.backoff = state
                .backoff
                .max(Duration::from_secs(5))
                .saturating_mul(2)
                .min(Duration::from_mins(10));
        } else {
            state.backoff = Duration::ZERO;
        }
    }

    async fn ledger(&self) -> (u32, BTreeMap<String, u32>) {
        let state = self.state.lock().await;
        (state.spent, state.by_kind.clone())
    }
}

// ---------------------------------------------------------------------------
// The session chain: why one connection ended, why the whole chain stopped.
// ---------------------------------------------------------------------------

/// Why ONE connection (or one attempt to make one) ended. Most of these are survivable.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SessionEnd {
    PlannedWindowReached,
    FrameBudget,
    ByteBudget,
    ProviderClosedSocket,
    TransportError,
    InactivityCeiling,
    HostSuspended,
    /// The ticket mint answered with a non-`429` `4xx`: a refusal, never retried.
    TicketRefused,
    /// The websocket upgrade itself answered with a non-`429` `4xx`: a refusal, never retried.
    UpgradeRefused,
    /// The refresh token died and a full re-login was itself refused. The wallet said the words
    /// and the service said no; nothing here retries that.
    AuthRefused,
    /// A ticket mint or handshake failed retryably (transport, `5xx`, or `429` weather).
    ConnectFailed,
    /// The run-total bucket ceiling was reached; stopping is the budget speaking, not the socket.
    SpendExhausted,
    /// The operator (or the service manager) signalled the run to stop.
    RunSignalled,
}

impl SessionEnd {
    const fn terminal(self, first_session: bool) -> Option<RunStop> {
        match self {
            Self::PlannedWindowReached => Some(RunStop::WallClockBudget),
            Self::FrameBudget => Some(RunStop::FrameBudget),
            Self::ByteBudget => Some(RunStop::ByteBudget),
            Self::TicketRefused | Self::UpgradeRefused if first_session => {
                Some(RunStop::RefusedAtHandshake)
            }
            Self::TicketRefused | Self::UpgradeRefused => Some(RunStop::RefusedOnReconnect),
            Self::AuthRefused => Some(RunStop::AuthRefused),
            Self::SpendExhausted => Some(RunStop::SpendExhausted),
            Self::RunSignalled => Some(RunStop::Signalled),
            Self::ProviderClosedSocket
            | Self::TransportError
            | Self::InactivityCeiling
            | Self::HostSuspended
            | Self::ConnectFailed => None,
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::PlannedWindowReached => "wall_clock_budget_exhausted",
            Self::FrameBudget => "frame_budget_exhausted",
            Self::ByteBudget => "byte_budget_exhausted",
            Self::ProviderClosedSocket => "provider_closed_socket_before_planned_end",
            Self::TransportError => "transport_error_before_planned_end",
            Self::InactivityCeiling => "no_liveness_within_inactivity_ceiling",
            Self::HostSuspended => "host_suspended_during_window",
            Self::TicketRefused => "provider_refused_ws_ticket",
            Self::UpgradeRefused => "provider_refused_ws_upgrade",
            Self::AuthRefused => "auth_refused_after_session_cleared",
            Self::ConnectFailed => "connect_attempt_failed",
            Self::SpendExhausted => "bucket_spend_ceiling_reached",
            Self::RunSignalled => "run_signalled_to_stop",
        }
    }
}

/// Why one mint's whole chained run stopped. Every stop is one of these; none is a silence.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RunStop {
    WallClockBudget,
    FrameBudget,
    ByteBudget,
    RefusedAtHandshake,
    RefusedOnReconnect,
    AuthRefused,
    ReconnectAttemptsExhausted,
    SpendExhausted,
    Signalled,
    /// This process could not stamp or durably record what it was seeing. Running on with an
    /// unrecorded window would be silent loss, so the chain stops under its own name.
    LocalRecordFault,
}

impl RunStop {
    const fn as_str(self) -> &'static str {
        match self {
            Self::WallClockBudget => "wall_clock_budget_exhausted",
            Self::FrameBudget => "frame_budget_exhausted",
            Self::ByteBudget => "byte_budget_exhausted",
            Self::RefusedAtHandshake => "provider_refused_at_handshake",
            Self::RefusedOnReconnect => "provider_refused_on_reconnect",
            Self::AuthRefused => "auth_refused_after_session_cleared",
            Self::ReconnectAttemptsExhausted => "reconnect_attempts_exhausted",
            Self::SpendExhausted => "bucket_spend_ceiling_reached",
            Self::Signalled => "run_signalled_to_stop",
            Self::LocalRecordFault => "local_record_fault",
        }
    }

    /// What kept the tail of the window unobserved when the chain stopped with a hole open.
    const fn trailing_cause(self) -> &'static str {
        match self {
            Self::WallClockBudget => CAUSE_BACKOFF_WAIT,
            other => other.as_str(),
        }
    }
}

/// A bounded, doubling wait between reconnect attempts, ported from the tape recorder.
#[derive(Clone, Copy, Debug)]
struct ReconnectPolicy {
    max_attempts: u32,
    initial_backoff: Duration,
    max_backoff: Duration,
}

impl ReconnectPolicy {
    fn backoff(self, attempt: u32) -> Duration {
        let factor = 1_u32
            .checked_shl(attempt.saturating_sub(1))
            .unwrap_or(u32::MAX);
        self.initial_backoff
            .checked_mul(factor)
            .unwrap_or(self.max_backoff)
            .min(self.max_backoff)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Next {
    Reconnect { attempt: u32, backoff: Duration },
    Stop(RunStop),
}

fn next_step(
    policy: ReconnectPolicy,
    end: SessionEnd,
    first_session: bool,
    consecutive_failures: u32,
    remaining: Duration,
) -> Next {
    if let Some(stop) = end.terminal(first_session) {
        return Next::Stop(stop);
    }
    if remaining.is_zero() {
        return Next::Stop(RunStop::WallClockBudget);
    }
    let attempt = consecutive_failures.saturating_add(1);
    if attempt > policy.max_attempts {
        return Next::Stop(RunStop::ReconnectAttemptsExhausted);
    }
    Next::Reconnect {
        attempt,
        backoff: policy.backoff(attempt).min(remaining),
    }
}

/// What one connection did and what it can vouch for, in wall microseconds.
#[derive(Clone, Copy, Debug)]
struct SessionOutcome {
    epoch: u64,
    opened_at_us: i64,
    closed_at_us: i64,
    first_liveness_us: Option<i64>,
    last_liveness_us: Option<i64>,
    inbound_frames: usize,
    inbound_bytes: usize,
    pings_sent: usize,
    end: SessionEnd,
}

impl SessionOutcome {
    /// The interval this connection honestly vouches for, ported from the tape recorder: a
    /// planned stop vouches through the stop, a fault vouches only to its last liveness, and a
    /// connection the provider never spoke on claims a zero-width window.
    fn claimed(&self, planned_end_us: i64) -> (i64, i64) {
        let Some(lower) = self.first_liveness_us else {
            return (self.opened_at_us, self.opened_at_us);
        };
        let upper = match self.end {
            SessionEnd::PlannedWindowReached | SessionEnd::RunSignalled => {
                self.closed_at_us.min(planned_end_us)
            }
            SessionEnd::FrameBudget | SessionEnd::ByteBudget | SessionEnd::SpendExhausted => {
                self.closed_at_us
            }
            _ => self.last_liveness_us.unwrap_or(lower),
        };
        (lower, upper.max(lower))
    }
}

/// One interval of the window nothing could vouch for, and what made it so.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Unobserved {
    lower_us: i64,
    upper_us: i64,
    cause: &'static str,
    /// The session whose claim this gap hangs off, when one exists at all.
    anchor: Option<usize>,
}

/// The complement walk, ported: every interval the coverage cursor had to jump, split at the
/// closing instant of the connection that opened it, merged where cause and boundary agree. A
/// chain with no sessions at all yields one gap covering the whole window under the stop's cause.
fn unobserved_spans(
    sessions: &[SessionOutcome],
    opened_at_us: i64,
    effective_end_us: i64,
    stop: RunStop,
) -> Vec<Unobserved> {
    if sessions.is_empty() {
        if opened_at_us >= effective_end_us {
            return Vec::new();
        }
        return vec![Unobserved {
            lower_us: opened_at_us,
            upper_us: effective_end_us,
            cause: stop.trailing_cause(),
            anchor: None,
        }];
    }
    let mut spans: Vec<Unobserved> = Vec::new();
    let mut cursor = opened_at_us;
    let mut previous: Option<(usize, &SessionOutcome)> = None;
    for (index, session) in sessions.iter().enumerate() {
        let (lower, upper) = session.claimed(effective_end_us);
        let (anchor, close, fault) = match previous {
            None => (index, None, CAUSE_AWAITING_FIRST_LIVENESS),
            Some((earlier, earlier_session)) => (
                earlier,
                Some(earlier_session.closed_at_us),
                earlier_session.end.as_str(),
            ),
        };
        split_unobserved(
            &mut spans,
            cursor,
            lower.min(effective_end_us),
            close,
            fault,
            CAUSE_BACKOFF_WAIT,
            anchor,
        );
        cursor = cursor.max(upper.min(effective_end_us));
        previous = Some((index, session));
    }
    if let Some((index, session)) = previous {
        split_unobserved(
            &mut spans,
            cursor,
            effective_end_us,
            Some(session.closed_at_us),
            session.end.as_str(),
            stop.trailing_cause(),
            index,
        );
    }
    merge_adjacent(spans)
}

#[allow(clippy::too_many_arguments)] // Every boundary of the claim is named explicitly.
fn split_unobserved(
    spans: &mut Vec<Unobserved>,
    from: i64,
    to: i64,
    close: Option<i64>,
    fault: &'static str,
    between_sockets: &'static str,
    anchor: usize,
) {
    if from >= to {
        return;
    }
    let mut push = |lower: i64, upper: i64, cause: &'static str| {
        spans.push(Unobserved {
            lower_us: lower,
            upper_us: upper,
            cause,
            anchor: Some(anchor),
        });
    };
    match close {
        Some(close) if close <= from => push(from, to, between_sockets),
        Some(close) if close < to => {
            push(from, close, fault);
            push(close, to, between_sockets);
        }
        _ => push(from, to, fault),
    }
}

fn merge_adjacent(spans: Vec<Unobserved>) -> Vec<Unobserved> {
    let mut merged: Vec<Unobserved> = Vec::with_capacity(spans.len());
    for span in spans {
        match merged.last_mut() {
            Some(last) if last.upper_us == span.lower_us && last.cause == span.cause => {
                last.upper_us = span.upper_us;
            }
            _ => merged.push(span),
        }
    }
    merged
}

// ---------------------------------------------------------------------------
// Frame classification: what the socket said, and the occurrence claim inside it.
// ---------------------------------------------------------------------------

/// The provider's occurrence claim as this frame states it: an id to join on, the verbatim
/// `createdAt` text, and where in the frame they were found — a claim about the frame, never a
/// conversion of it.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct FrameClaim {
    id: Option<String>,
    created_at_raw: Option<String>,
    parent_callout_id: Option<String>,
    path: Option<&'static str>,
}

fn classify_frame(body: &[u8]) -> (String, FrameClaim) {
    let Ok(value) = serde_json::from_slice::<Value>(body) else {
        return ("malformed".to_owned(), FrameClaim::default());
    };
    let event_type = value
        .get("eventType")
        .and_then(Value::as_str)
        .map_or_else(|| "unclassified".to_owned(), ToOwned::to_owned);
    (event_type, extract_claim(&value))
}

/// Search the places the payload object plausibly sits. The extraction is best-effort and says
/// where it looked; the verbatim bytes are retained beside it so nothing rests on this guess.
fn extract_claim(value: &Value) -> FrameClaim {
    const PATHS: [(&str, &[&str]); 6] = [
        ("data.callout", &["data", "callout"]),
        ("data.message", &["data", "message"]),
        ("data", &["data"]),
        ("callout", &["callout"]),
        ("message", &["message"]),
        (".", &[]),
    ];
    for (name, steps) in PATHS {
        let mut cursor = value;
        let mut found = true;
        for step in steps {
            if let Some(next) = cursor.get(step) {
                cursor = next;
            } else {
                found = false;
                break;
            }
        }
        if !found {
            continue;
        }
        let id = cursor.get("id").and_then(Value::as_str);
        let created = cursor.get("createdAt").and_then(Value::as_str);
        if id.is_some() || created.is_some() {
            return FrameClaim {
                id: id.map(ToOwned::to_owned),
                created_at_raw: created.map(ToOwned::to_owned),
                parent_callout_id: cursor
                    .get("parentCalloutId")
                    .and_then(Value::as_str)
                    .map(ToOwned::to_owned),
                path: Some(name),
            };
        }
    }
    FrameClaim::default()
}

// ---------------------------------------------------------------------------
// The live run.
// ---------------------------------------------------------------------------

/// Everything the per-mint chain and poll tasks share.
struct Shared {
    journal: Journal,
    pacer: BucketPacer,
    provider: CommunitySessionProvider,
    signer: CommunityWalletSigner,
    product_key: String,
    stop: tokio::sync::watch::Receiver<bool>,
    run_deadline: Instant,
    planned_end_us: i64,
    sockets: SocketsSection,
}

impl Shared {
    /// Make the session live again, pacing only when a network exchange is actually needed. A
    /// dead refresh token gets ONE full re-login; a refusal there is the terminal
    /// [`SessionEnd::AuthRefused`].
    async fn ensure_session(&self) -> Result<(), SessionEnd> {
        if self.provider.is_live() {
            return Ok(());
        }
        self.pacer.acquire("refresh", 1).await.map_err(pacer_end)?;
        match self.provider.ensure_fresh().await {
            Ok(()) => {
                self.pacer.report(false).await;
                self.journal_auth("refresh_ok", None);
                Ok(())
            }
            Err(CommunityAuthError::SessionCleared) => {
                self.journal_auth("session_cleared", None);
                self.pacer.acquire("login", 2).await.map_err(pacer_end)?;
                match CommunitySession::login(&self.signer, &self.product_key).await {
                    Ok(session) => {
                        // Not a rework of the provider: a fresh login replaces the cleared
                        // session wholesale through the same provider the run holds.
                        self.install(session);
                        self.pacer.report(false).await;
                        self.journal_auth("relogin_ok", None);
                        Ok(())
                    }
                    Err(error) => {
                        let status = auth_status(&error);
                        self.journal_auth("relogin_refused", status);
                        if status == Some(429) {
                            self.pacer.report(true).await;
                            Err(SessionEnd::ConnectFailed)
                        } else {
                            Err(SessionEnd::AuthRefused)
                        }
                    }
                }
            }
            Err(error) => {
                let status = auth_status(&error);
                self.journal_auth("refresh_failed", status);
                self.pacer.report(status == Some(429)).await;
                Err(SessionEnd::ConnectFailed)
            }
        }
    }

    fn install(&self, session: CommunitySession) {
        self.provider.replace(session);
    }

    fn journal_auth(&self, event: &str, status: Option<u16>) {
        let _ = self.journal.record(json!({
            "kind": "auth",
            "event": event,
            "httpStatus": status,
        }));
    }
}

/// Best-effort status out of an auth error, for the ledger; secrets never ride these.
const fn auth_status(error: &CommunityAuthError) -> Option<u16> {
    match error {
        CommunityAuthError::ChallengeRejected(status)
        | CommunityAuthError::VerifyRejected(status)
        | CommunityAuthError::RefreshRejected(status)
        | CommunityAuthError::TicketRejected(status) => Some(*status),
        _ => None,
    }
}

type Socket =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

/// Mint a ticket and open one socket for one mint. Refusals, weather, and auth death come back
/// as the [`SessionEnd`] the chain's `next_step` decides on. The connect URL carries the ticket,
/// so no error from this function ever quotes the provider's words or the URL.
async fn connect_socket(shared: &Shared, mint: &str) -> Result<(Socket, u16), SessionEnd> {
    for attempt in 0..2_u8 {
        shared.ensure_session().await?;
        // ONE acquisition covers the mint AND the upgrade, so they run back-to-back: the ticket
        // is single-use and MEASURED to go stale within seconds (2026-08-25 04:27Z: a ticket
        // minted `ok` was 401-refused at the upgrade after ~20 s queued behind other lanes'
        // pacer slots, while a back-to-back mint+connect got 101). Queueing the upgrade
        // separately behind the shared pacer is what created that hole.
        shared
            .pacer
            .acquire("ticket_and_upgrade", 2)
            .await
            .map_err(pacer_end)?;
        let minted = shared.provider.mint_ws_ticket(mint).await;
        let ticket = match minted {
            Ok(ticket) => {
                shared.pacer.report(false).await;
                shared.journal_ticket(mint, "ok", None);
                ticket
            }
            Err(CommunityAuthError::TicketRejected(429)) => {
                shared.pacer.report(true).await;
                shared.journal_ticket(mint, "throttled", Some(429));
                return Err(SessionEnd::ConnectFailed);
            }
            Err(CommunityAuthError::TicketRejected(status @ (401 | 403))) => {
                shared.journal_ticket(mint, "unauthorized", Some(status));
                if attempt == 0 {
                    // The reactive path: mark the bearer clock-dead so ensure_session refreshes,
                    // then try once more. A second refusal is the provider's answer.
                    shared
                        .provider
                        .invalidate(RouteSpec::for_id(RouteId::CommunityMe));
                    continue;
                }
                return Err(SessionEnd::TicketRefused);
            }
            Err(CommunityAuthError::TicketRejected(status)) if status >= 500 => {
                shared.pacer.report(false).await;
                shared.journal_ticket(mint, "provider_error", Some(status));
                return Err(SessionEnd::ConnectFailed);
            }
            Err(CommunityAuthError::TicketRejected(status)) => {
                shared.journal_ticket(mint, "refused", Some(status));
                return Err(SessionEnd::TicketRefused);
            }
            Err(CommunityAuthError::NotLive) => {
                if attempt == 0 {
                    continue;
                }
                return Err(SessionEnd::ConnectFailed);
            }
            Err(error) => {
                shared.journal_ticket(mint, "transport_failed", auth_status(&error));
                return Err(SessionEnd::ConnectFailed);
            }
        };
        let url = ticket.socket_url(mint).map_err(|_| {
            // Only a non-mint-shaped subject reaches this arm, and subjects were validated at
            // watch-set derivation; refuse rather than guess.
            SessionEnd::TicketRefused
        })?;
        let mut request = url
            .into_client_request()
            .map_err(|_| SessionEnd::ConnectFailed)?;
        let headers = request.headers_mut();
        headers.insert(
            "Origin",
            "https://pump.fun"
                .parse()
                .map_err(|_| SessionEnd::ConnectFailed)?,
        );
        headers.insert(
            "User-Agent",
            "joshi-availability/0.1 read-only personal accessibility client"
                .parse()
                .map_err(|_| SessionEnd::ConnectFailed)?,
        );
        match tokio_tungstenite::connect_async(request).await {
            Ok((socket, response)) => {
                shared.pacer.report(false).await;
                return Ok((socket, response.status().as_u16()));
            }
            Err(tokio_tungstenite::tungstenite::Error::Http(response)) => {
                let status = response.status().as_u16();
                shared.pacer.report(status == 429).await;
                shared.journal_ticket(mint, "upgrade_rejected", Some(status));
                if status == 429 || status >= 500 {
                    return Err(SessionEnd::ConnectFailed);
                }
                // A 401/403 at the upgrade with a JUST-MINTED ticket is the single-use ticket
                // having gone stale in transit, not the provider refusing this subscription —
                // the mint itself is where a real authorization refusal answers (and is
                // terminal above). Retry with a FRESH ticket under the ordinary reconnect
                // bound. Any other 4xx (a malformed ask, a gone community) is a refusal.
                if status == 401 || status == 403 {
                    return Err(SessionEnd::ConnectFailed);
                }
                return Err(SessionEnd::UpgradeRefused);
            }
            Err(_) => {
                // The error text may quote the URL, which carries the ticket: state the class only.
                shared.pacer.report(false).await;
                shared.journal_ticket(mint, "connect_transport_failed", None);
                return Err(SessionEnd::ConnectFailed);
            }
        }
    }
    Err(SessionEnd::ConnectFailed)
}

impl Shared {
    fn journal_ticket(&self, mint: &str, outcome: &str, status: Option<u16>) {
        let _ = self.journal.record(json!({
            "kind": "ticket_mint",
            "mint": mint,
            "outcome": outcome,
            "httpStatus": status,
        }));
    }
}

/// Run-wide (per mint) tape counters shared across that mint's sessions.
struct ChainTape {
    frames: usize,
    bytes: usize,
    pings: usize,
    sequence: u64,
    max_frames: usize,
    max_bytes: usize,
}

/// Hold one socket for as long as it is useful, retaining every inbound frame with both clocks.
/// Budgets are re-checked every iteration against BOTH clocks, exactly as the tape recorder does.
#[allow(clippy::too_many_lines)] // One connection's whole poll/stamp/retain walk stays together.
async fn run_socket_session(
    socket: &mut Socket,
    shared: &Shared,
    mint: &str,
    epoch: u64,
    tape: &mut ChainTape,
) -> Result<SessionOutcome, Failure> {
    let opened_wall = OffsetDateTime::now_utc();
    let opened_at_us = unix_micros(opened_wall)?;
    let session_mono = Instant::now();
    let mut stop = shared.stop.clone();
    let ping_interval = Duration::from_secs(shared.sockets.ping_interval_seconds);
    let inactivity_us = i64::try_from(shared.sockets.inactivity_ceiling_seconds)? * 1_000_000;
    let mut next_ping = Instant::now() + ping_interval;
    let mut outcome = SessionOutcome {
        epoch,
        opened_at_us,
        closed_at_us: opened_at_us,
        first_liveness_us: None,
        last_liveness_us: None,
        inbound_frames: 0,
        inbound_bytes: 0,
        pings_sent: 0,
        end: SessionEnd::TransportError,
    };
    let end = loop {
        if tape.frames >= tape.max_frames {
            break SessionEnd::FrameBudget;
        }
        if tape.bytes >= tape.max_bytes {
            break SessionEnd::ByteBudget;
        }
        if *stop.borrow() {
            break SessionEnd::RunSignalled;
        }
        let now_us = unix_micros(OffsetDateTime::now_utc())?;
        let wall_elapsed_us = now_us - opened_at_us;
        let mono_elapsed_us = i64::try_from(session_mono.elapsed().as_micros())?;
        if wall_elapsed_us - mono_elapsed_us > SUSPEND_SKEW_MICROS {
            break SessionEnd::HostSuspended;
        }
        if now_us >= shared.planned_end_us {
            break SessionEnd::PlannedWindowReached;
        }
        if now_us - outcome.last_liveness_us.unwrap_or(opened_at_us) > inactivity_us {
            break SessionEnd::InactivityCeiling;
        }
        if Instant::now() >= next_ping {
            // Two probes ride together. The app-level ping is the protocol's own keepalive (the
            // only client->server frame); MEASURED 2026-08-25: on a quiet community it elicits
            // NOTHING back, so it cannot prove the socket alive. The transport-level ws Ping
            // can: RFC 6455 obliges the peer to answer Pong, which the poll arm counts as
            // liveness — so the inactivity ceiling fires only on a socket that stopped
            // answering the transport itself, never on a market that merely went quiet.
            if socket.send(Message::Text(PING_BODY.into())).await.is_err()
                || socket.send(Message::Ping(Vec::new().into())).await.is_err()
            {
                break SessionEnd::TransportError;
            }
            tape.pings += 1;
            outcome.pings_sent += 1;
            next_ping = Instant::now() + ping_interval;
            shared.journal.record(json!({
                "kind": "ping_sent",
                "mint": mint,
                "epoch": epoch,
            }))?;
            continue;
        }
        let wait = shared
            .run_deadline
            .saturating_duration_since(Instant::now())
            .min(next_ping.saturating_duration_since(Instant::now()))
            .min(Duration::from_secs(1));
        let polled = tokio::select! {
            biased;
            _ = stop.changed() => None,
            message = tokio::time::timeout(wait.max(Duration::from_millis(10)), socket.next()) => {
                Some(message)
            }
        };
        let Some(polled) = polled else {
            break SessionEnd::RunSignalled;
        };
        let message = match polled {
            Err(_) => continue, // quiet poll window; liveness is judged at the loop head
            Ok(None) => break SessionEnd::ProviderClosedSocket,
            Ok(Some(Err(_))) => break SessionEnd::TransportError,
            Ok(Some(Ok(message))) => message,
        };
        let body: Vec<u8> = match message {
            Message::Text(text) => text.as_bytes().to_vec(),
            Message::Binary(binary) => binary.to_vec(),
            Message::Close(_) => break SessionEnd::ProviderClosedSocket,
            Message::Ping(_) | Message::Pong(_) => {
                let at = unix_micros(OffsetDateTime::now_utc())?;
                outcome.first_liveness_us.get_or_insert(at);
                outcome.last_liveness_us = Some(at);
                continue;
            }
            Message::Frame(_) => continue,
        };
        let arrival_wall = OffsetDateTime::now_utc();
        let arrival_us = unix_micros(arrival_wall)?;
        let arrival_mono = u64::try_from(shared.journal.clock.process_start.elapsed().as_nanos())?;
        outcome.first_liveness_us.get_or_insert(arrival_us);
        outcome.last_liveness_us = Some(arrival_us);
        outcome.inbound_frames += 1;
        outcome.inbound_bytes += body.len();
        tape.frames += 1;
        tape.bytes += body.len();
        tape.sequence += 1;
        let (event_type, claim) = classify_frame(&body);
        let digest = format!("sha256:{:x}", Sha256::digest(&body));
        let engine = base64::engine::general_purpose::STANDARD;
        let (raw_key, raw_value, truncated) = if body.len() <= FRAME_RETAIN_MAX_BYTES {
            ("rawBase64", engine.encode(&body), false)
        } else {
            (
                "rawPrefixBase64",
                engine.encode(&body[..FRAME_RETAIN_MAX_BYTES]),
                true,
            )
        };
        shared.journal.record(json!({
            "kind": "frame",
            "mint": mint,
            "epoch": epoch,
            "sequence": tape.sequence,
            "eventType": event_type,
            "arrivalWall": wall_string(arrival_wall)?,
            "arrivalUnixUs": arrival_us,
            "arrivalMonotonicNs": arrival_mono.to_string(),
            "arrivalClockId": shared.journal.clock.clock_id,
            "arrivalClockNote": ARRIVAL_CLOCK_NOTE,
            "byteLength": body.len(),
            "sha256": digest,
            raw_key: raw_value,
            "truncated": truncated,
            "claim": {
                "id": claim.id,
                "createdAtRaw": claim.created_at_raw,
                "parentCalloutId": claim.parent_callout_id,
                "extractedFrom": claim.path,
                "clockNote": PROVIDER_CLOCK_NOTE,
            },
        }))?;
    };
    outcome.closed_at_us = unix_micros(OffsetDateTime::now_utc())?;
    outcome.end = end;
    Ok(outcome)
}

/// Everything one mint's chained run produced, for the receipt.
struct MintReport {
    mint: String,
    attached_at_us: i64,
    stop: RunStop,
    sessions: Vec<SessionOutcome>,
    spans: Vec<Unobserved>,
    reconnects: Vec<Value>,
    frames: usize,
    bytes: usize,
    pings: usize,
}

/// One mint's whole chained run: ticket, socket, session, reconnect-or-stop, gaps tiling the
/// window exactly. The planned end is the RUN's planned end; a chain attached late (a mint going
/// hot mid-run) tiles only its own window.
#[allow(clippy::too_many_lines)] // The chain walk mirrors the tape recorder's, kept in one place.
async fn run_mint_chain(shared: Arc<Shared>, mint: String, policy: ReconnectPolicy) -> MintReport {
    let attached_at_us = unix_micros(OffsetDateTime::now_utc()).unwrap_or(shared.planned_end_us);
    let mut sessions: Vec<SessionOutcome> = Vec::new();
    let mut reconnects: Vec<Value> = Vec::new();
    let mut tape = ChainTape {
        frames: 0,
        bytes: 0,
        pings: 0,
        sequence: 0,
        max_frames: shared.sockets.max_frames.unwrap_or(50_000),
        max_bytes: shared.sockets.max_bytes.unwrap_or(64 * 1024 * 1024),
    };
    let mut consecutive_failures = 0_u32;
    let mut stop_watch = shared.stop.clone();
    let stop = 'chain: loop {
        if *stop_watch.borrow() {
            break RunStop::Signalled;
        }
        let end = match connect_socket(&shared, &mint).await {
            Err(end) => end,
            Ok((mut socket, handshake_status)) => {
                let epoch = u64::try_from(sessions.len()).unwrap_or(u64::MAX) + 1;
                let _ = shared.journal.record(json!({
                    "kind": "session_open",
                    "mint": mint,
                    "epoch": epoch,
                    "handshakeStatus": handshake_status,
                }));
                let outcome =
                    match run_socket_session(&mut socket, &shared, &mint, epoch, &mut tape).await {
                        Ok(outcome) => outcome,
                        Err(error) => {
                            // A local stamping/journal failure, not the provider: close the
                            // socket, write the reason, and stop this chain rather than run on
                            // with an unrecorded window.
                            let _ = shared.journal.record(json!({
                                "kind": "chain_error",
                                "mint": mint,
                                "detail": error.to_string(),
                            }));
                            break 'chain RunStop::LocalRecordFault;
                        }
                    };
                drop(socket);
                let (claim_lower, claim_upper) = outcome.claimed(shared.planned_end_us);
                let _ = shared.journal.record(json!({
                    "kind": "session_close",
                    "mint": mint,
                    "epoch": epoch,
                    "endReason": outcome.end.as_str(),
                    "openedAtUnixUs": outcome.opened_at_us,
                    "closedAtUnixUs": outcome.closed_at_us,
                    "firstLivenessUnixUs": outcome.first_liveness_us,
                    "lastLivenessUnixUs": outcome.last_liveness_us,
                    "inboundFrames": outcome.inbound_frames,
                    "inboundBytes": outcome.inbound_bytes,
                    "pingsSent": outcome.pings_sent,
                    "claimedWindowUnixUs": [claim_lower, claim_upper],
                }));
                if outcome.inbound_frames > 0 {
                    consecutive_failures = 0;
                }
                let end = outcome.end;
                sessions.push(outcome);
                end
            }
        };
        let remaining = shared
            .run_deadline
            .saturating_duration_since(Instant::now());
        let (attempt, backoff) = match next_step(
            policy,
            end,
            sessions.is_empty(),
            consecutive_failures,
            remaining,
        ) {
            Next::Stop(stop) => break stop,
            Next::Reconnect { attempt, backoff } => (attempt, backoff),
        };
        consecutive_failures = attempt;
        reconnects.push(json!({
            "attempt": attempt,
            "afterEndReason": end.as_str(),
            "backoffMs": u64::try_from(backoff.as_millis()).unwrap_or(u64::MAX),
        }));
        let _ = shared.journal.record(json!({
            "kind": "reconnect",
            "mint": mint,
            "attempt": attempt,
            "afterEndReason": end.as_str(),
            "backoffMs": u64::try_from(backoff.as_millis()).unwrap_or(u64::MAX),
        }));
        tokio::select! {
            biased;
            _ = stop_watch.changed() => break RunStop::Signalled,
            () = tokio::time::sleep(backoff) => {}
        }
    };
    let spans = unobserved_spans(&sessions, attached_at_us, shared.planned_end_us, stop);
    for span in &spans {
        let _ = shared.journal.record(json!({
            "kind": "gap",
            "mint": mint,
            "lowerUnixUs": span.lower_us,
            "upperUnixUs": span.upper_us,
            "micros": span.upper_us - span.lower_us,
            "cause": span.cause,
            "anchorSession": span.anchor,
            "recoverable": false,
        }));
    }
    let _ = shared.journal.record(json!({
        "kind": "chain_close",
        "mint": mint,
        "stopReason": stop.as_str(),
        "sessions": sessions.len(),
        "frames": tape.frames,
        "bytes": tape.bytes,
    }));
    MintReport {
        mint,
        attached_at_us,
        stop,
        sessions,
        spans,
        reconnects,
        frames: tape.frames,
        bytes: tape.bytes,
        pings: tape.pings,
    }
}

/// The comparison lane: the REST `community_callouts` window on the keeper's hot cadence, through
/// the ordinary catalog client so every poll is stamped with envelope clocks and retained exact.
async fn run_rest_poller(
    shared: Arc<Shared>,
    client: Arc<PumpApiClient>,
    identity: IdentityStore,
    mint: String,
    cadence: Duration,
    first_delay: Duration,
) -> Value {
    let mut stop = shared.stop.clone();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut ordinal = 0_u64;
    let mut fetched = 0_u64;
    let mut failed = 0_u64;
    let mut next_poll = Instant::now() + first_delay;
    loop {
        if *stop.borrow() || Instant::now() >= shared.run_deadline {
            break;
        }
        let wait = next_poll.saturating_duration_since(Instant::now()).min(
            shared
                .run_deadline
                .saturating_duration_since(Instant::now()),
        );
        tokio::select! {
            biased;
            _ = stop.changed() => break,
            () = tokio::time::sleep(wait) => {}
        }
        if *stop.borrow() || Instant::now() >= shared.run_deadline {
            break;
        }
        next_poll += cadence;
        ordinal += 1;
        if shared.pacer.acquire("rest_poll", 1).await.is_err() {
            let _ = shared.journal.record(json!({
                "kind": "rest_poll",
                "mint": mint,
                "ordinal": ordinal,
                "outcome": "spend_exhausted",
            }));
            break;
        }
        let request = LogicalRequest {
            route: RouteId::CommunityCallouts,
            parameters: RequestParameters {
                path: [("mint".to_owned(), mint.clone())].into_iter().collect(),
                query: BTreeMap::new(),
            },
        };
        match client.fetch(&request).await {
            Ok(outcome) => {
                let record = rest_poll_record(&mint, ordinal, &outcome, &mut seen);
                let throttled = record
                    .get("httpStatus")
                    .and_then(Value::as_u64)
                    .is_some_and(|status| status == 429);
                shared.pacer.report(throttled).await;
                if record
                    .get("outcome")
                    .and_then(Value::as_str)
                    .is_some_and(|value| value == "fetched")
                {
                    fetched += 1;
                } else {
                    failed += 1;
                }
                let written = shared.journal.record(record);
                if written.is_ok() {
                    for attempt in &outcome.attempts {
                        let _ = identity.acknowledge_id(&attempt.acquisition_id);
                    }
                }
            }
            Err(error) => {
                failed += 1;
                shared.pacer.report(false).await;
                let _ = shared.journal.record(json!({
                    "kind": "rest_poll",
                    "mint": mint,
                    "ordinal": ordinal,
                    "outcome": "client_refused",
                    "detail": error.to_string(),
                }));
            }
        }
    }
    json!({
        "mint": mint,
        "polls": ordinal,
        "fetched": fetched,
        "failed": failed,
        "distinctIdsSeen": seen.len(),
    })
}

/// Shape one poll's durable record: envelope clocks restated, the whole fetch outcome retained
/// (exact bytes ride inside it), and the window's rows parsed beside it for the join.
fn rest_poll_record(
    mint: &str,
    ordinal: u64,
    outcome: &FetchOutcome,
    seen: &mut BTreeSet<String>,
) -> Value {
    let attempt = outcome.attempts.last();
    let status = attempt.and_then(|acquisition| acquisition.http_status);
    let received_at = attempt.map(|acquisition| acquisition.clocks.received_at.clone());
    let received_us = received_at
        .as_deref()
        .and_then(|text| parse_service_instant(text).ok());
    let mut rows = Vec::new();
    let mut new_ids = Vec::new();
    let fetched = outcome.completed && status.is_some_and(|status| (200..300).contains(&status));
    if fetched
        && let Some(body) = attempt.and_then(|acquisition| acquisition.body.exact_bytes())
        && let Ok(value) = serde_json::from_slice::<Value>(&body)
    {
        for row in value
            .get("callouts")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let id = row.get("id").and_then(Value::as_str).map(ToOwned::to_owned);
            if let Some(id) = &id
                && seen.insert(id.clone())
            {
                new_ids.push(id.clone());
            }
            rows.push(json!({
                "id": id,
                "createdAtRaw": row.get("createdAt").and_then(Value::as_str),
                "likeCount": row.get("likeCount").and_then(Value::as_i64),
                "replyCount": row.get("replyCount").and_then(Value::as_i64),
            }));
        }
    }
    json!({
        "kind": "rest_poll",
        "mint": mint,
        "ordinal": ordinal,
        "outcome": if fetched { "fetched" } else { "failed" },
        "httpStatus": status,
        "receivedAt": received_at,
        "receivedAtUnixUs": received_us,
        "rowCount": rows.len(),
        "rows": rows,
        "newIds": new_ids,
        "clockNote": PROVIDER_CLOCK_NOTE,
        "fetchOutcome": serde_json::to_value(outcome).unwrap_or(Value::Null),
    })
}

/// Parse a service-format UTC instant (RFC3339 with fractional seconds) to unix microseconds.
/// Used for OUR envelope clocks, and — only inside the analysis, with the cross-clock caveat
/// restated — for the provider's `createdAt` claims.
fn parse_service_instant(text: &str) -> Result<i64, Failure> {
    let parsed = OffsetDateTime::parse(text, &time::format_description::well_known::Rfc3339)?;
    unix_micros(parsed)
}

/// A watch-set subject must be shaped like a public mint before it lands in a URL path.
fn mint_shaped(subject: &str) -> bool {
    (32..=44).contains(&subject.len())
        && subject
            .chars()
            .all(|character| character.is_ascii_alphanumeric())
}

// ---------------------------------------------------------------------------
// Orchestration.
// ---------------------------------------------------------------------------

/// Mutable run state the tick task and the drain loop share: which mints are attached, and the
/// join handles of every spawned lane.
#[derive(Default)]
struct RunState {
    attached: BTreeSet<String>,
    chain_handles: Vec<tokio::task::JoinHandle<MintReport>>,
    poll_handles: Vec<tokio::task::JoinHandle<Value>>,
    watch_note: Option<String>,
}

/// Attach one mint: one socket chain plus one comparison poller, both durably journaled.
fn attach_mint(
    state: &mut RunState,
    shared: &Arc<Shared>,
    client: &Arc<PumpApiClient>,
    identity: &IdentityStore,
    rest_poll: &RestPollSection,
    policy: ReconnectPolicy,
    mint: &str,
) {
    if !mint_shaped(mint) {
        state.watch_note = Some(format!("refused non-mint-shaped watch subject {mint:?}"));
        return;
    }
    if !state.attached.insert(mint.to_owned()) {
        return;
    }
    let _ = shared.journal.record(json!({
        "kind": "watch_attach",
        "mint": mint,
    }));
    state.chain_handles.push(tokio::spawn(run_mint_chain(
        Arc::clone(shared),
        mint.to_owned(),
        policy,
    )));
    state.poll_handles.push(tokio::spawn(run_rest_poller(
        Arc::clone(shared),
        Arc::clone(client),
        identity.clone(),
        mint.to_owned(),
        Duration::from_secs(rest_poll.cadence_minutes * 60),
        Duration::from_secs(rest_poll.first_poll_delay_seconds),
    )));
}

/// The keeper-style tick: re-read the watch inputs, attach newly hot mints while slots are free,
/// rewrite the heartbeat. A broken re-read keeps the last good values and says so.
#[allow(clippy::too_many_arguments)] // The tick names everything it may touch, explicitly.
async fn run_tick(
    shared: Arc<Shared>,
    state: Arc<Mutex<RunState>>,
    client: Arc<PumpApiClient>,
    identity: IdentityStore,
    config_path: PathBuf,
    run_dir: PathBuf,
    policy: ReconnectPolicy,
    mints_overridden: bool,
) {
    let mut stop = shared.stop.clone();
    let mut last_good: Option<(AvailabilityConfig, KeeperInputs)> = None;
    loop {
        if *stop.borrow() || Instant::now() >= shared.run_deadline {
            break;
        }
        let mut note: Option<String> = None;
        if mints_overridden {
            note = Some("watch set fixed by --mints; hot-requests not consulted".to_owned());
        } else {
            let reread = load_config(&config_path).and_then(|config| {
                let inputs = read_keeper_inputs(&config.keeper_config)?;
                Ok((config, inputs))
            });
            match reread {
                Ok(pair) => last_good = Some(pair),
                Err(error) => {
                    note = Some(format!("config re-read failed, keeping last good: {error}"));
                }
            }
            if let Some((config, inputs)) = &last_good {
                let hot = match read_hot_mints(&inputs.hot_requests_file, OffsetDateTime::now_utc())
                {
                    Ok(hot) => hot,
                    Err(error) => {
                        note = Some(format!(
                            "hot-requests read failed, treating as empty: {error}"
                        ));
                        Vec::new()
                    }
                };
                let watch =
                    derive_watch_set(&hot, &inputs.watch_mints, config.sockets.max_concurrent);
                let mut state = state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                for mint in &watch {
                    if state.attached.len() >= config.sockets.max_concurrent {
                        break;
                    }
                    attach_mint(
                        &mut state,
                        &shared,
                        &client,
                        &identity,
                        &config.rest_poll,
                        policy,
                        mint,
                    );
                }
                if note.is_none() {
                    note = state.watch_note.take();
                }
            }
        }
        let (spent, by_kind) = shared.pacer.ledger().await;
        let attached: Vec<String> = {
            let state = state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.attached.iter().cloned().collect()
        };
        let heartbeat = json!({
            "writtenAt": wall_string(OffsetDateTime::now_utc()).unwrap_or_default(),
            "attachedMints": attached,
            "bucketSpend": spent,
            "bucketSpendByKind": by_kind,
            "note": note,
        });
        let _ = write_renamed(&run_dir.join("heartbeat.json"), &heartbeat);
        tokio::select! {
            biased;
            _ = stop.changed() => break,
            () = tokio::time::sleep(Duration::from_secs(TICK_SECONDS)) => {}
        }
    }
}

#[allow(clippy::too_many_lines)] // One run's whole open/attach/wait/receipt walk stays together.
async fn run(
    config_path: &Path,
    minutes: u64,
    mints_override: Option<&str>,
) -> Result<String, Failure> {
    if minutes == 0 || minutes > 12 * 60 {
        return Err(
            "--minutes must be between 1 and 720: this is a bounded run, not a daemon".into(),
        );
    }
    let config = load_config(config_path)?;
    let keeper_inputs = read_keeper_inputs(&config.keeper_config)?;
    let opened_wall = OffsetDateTime::now_utc();
    let opened_at_us = unix_micros(opened_wall)?;
    let run_id = format!(
        "run-{}",
        opened_wall.format(time::macros::format_description!(
            "[year][month][day]T[hour][minute][second]Z"
        ))?
    );
    let run_dir = config.root.join(&run_id);
    fs::create_dir_all(&run_dir)?;
    let clock = Arc::new(RunClock::new(&run_id));
    let journal = Journal {
        recorder: Arc::new(Mutex::new(Recorder::open(&run_dir.join("events.jsonl"))?)),
        clock: Arc::clone(&clock),
    };

    // Watch set at launch. An override is a fixed set; otherwise hot-requests lead, keeper watch
    // mints follow, capped.
    let hot_note: Option<String>;
    let watch = if let Some(csv) = mints_override {
        hot_note = None;
        csv.split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
            .collect::<Vec<_>>()
    } else {
        let hot = match read_hot_mints(&keeper_inputs.hot_requests_file, opened_wall) {
            Ok(hot) => {
                hot_note = None;
                hot
            }
            Err(error) => {
                hot_note = Some(format!("hot-requests unreadable at launch: {error}"));
                Vec::new()
            }
        };
        derive_watch_set(
            &hot,
            &keeper_inputs.watch_mints,
            config.sockets.max_concurrent,
        )
    };
    if watch.is_empty() {
        return Err(
            "no watch mints: hot-requests is empty and the keeper watch set names no \
                    community_callouts taps"
                .into(),
        );
    }
    for mint in &watch {
        if !mint_shaped(mint) {
            return Err(format!("watch subject {mint:?} is not shaped like a public mint").into());
        }
    }

    let product_key = {
        let bytes = read_bounded(
            &keeper_inputs.community_key_file,
            4_096,
            "community key file",
        )?;
        let text = String::from_utf8(bytes).map_err(|_| "community key file is not UTF-8")?;
        let token = text.trim().to_owned();
        if token.is_empty() || token.contains(char::is_whitespace) {
            return Err("community key file must hold one non-empty token".into());
        }
        token
    };
    let signer = CommunityWalletSigner::from_file(&config.wallet_key_file)?;
    let planned_end_us = opened_at_us + i64::try_from(minutes)? * 60 * 1_000_000;
    let run_deadline = Instant::now() + Duration::from_secs(minutes * 60);
    let pacer = BucketPacer::new(
        Duration::from_secs(config.budgets.min_gap_seconds),
        config.budgets.max_bucket_requests,
        run_deadline,
    );

    journal.record(json!({
        "kind": "run_open",
        "contract": EVENTS_CONTRACT,
        "runId": run_id,
        "openedAt": wall_string(opened_wall)?,
        "openedAtUnixUs": opened_at_us,
        "plannedEndUnixUs": planned_end_us,
        "plannedMinutes": minutes,
        "clockId": clock.clock_id,
        "watch": watch,
        "watchOverridden": mints_override.is_some(),
        "watchNote": hot_note,
        "keeperConfig": config.keeper_config.display().to_string(),
        "walletAddress": signer.address(),
        "arrivalClockNote": ARRIVAL_CLOCK_NOTE,
        "providerClockNote": PROVIDER_CLOCK_NOTE,
        "budget": {
            "minGapSeconds": config.budgets.min_gap_seconds,
            "maxBucketRequests": config.budgets.max_bucket_requests,
        },
    }))?;

    // The handshake, under the same weather rules as everything else on the bucket: 429 and
    // transport failures retry bounded, a refusal is terminal and the run says so durably.
    let mut login_attempts = 0_u32;
    let session = loop {
        login_attempts += 1;
        if pacer.acquire("login", 2).await.is_err() {
            return Err(
                "bucket ceiling reached during login; raise budgets.max_bucket_requests".into(),
            );
        }
        match CommunitySession::login(&signer, &product_key).await {
            Ok(session) => {
                pacer.report(false).await;
                journal.record(json!({"kind": "auth", "event": "login_ok"}))?;
                break session;
            }
            Err(error) => {
                let status = auth_status(&error);
                journal.record(json!({
                    "kind": "auth",
                    "event": "login_failed",
                    "httpStatus": status,
                    "attempt": login_attempts,
                }))?;
                let weather = status == Some(429)
                    || matches!(error, CommunityAuthError::Transport(_))
                    || status.is_some_and(|value| value >= 500);
                pacer.report(status == Some(429)).await;
                // A refusal (the service saying no to THIS handshake) is terminal immediately.
                // Weather is different: the shared bucket is measured to saturate for an hour or
                // more at US prime time (the keeper's own community taps failed 03:17-04:17Z on
                // 2026-08-25), so weather gets a WALL-CLOCK allowance rather than an attempt
                // count — a bounded, backing-off ~16 requests over 45 minutes, after which an
                // overnight run concedes the window durably rather than hammering.
                let weather_allowance_spent =
                    clock.process_start.elapsed() > Duration::from_mins(45) || login_attempts >= 16;
                if !weather || weather_allowance_spent {
                    let reason = if weather {
                        "login_weather_allowance_exhausted"
                    } else {
                        "auth_refused_at_login"
                    };
                    let receipt =
                        refusal_receipt(&run_id, opened_at_us, status, reason, &pacer).await;
                    write_renamed(&run_dir.join("receipt.json"), &receipt)?;
                    return Ok(serde_json::to_string_pretty(&receipt)?);
                }
            }
        }
    };
    let provider = CommunitySessionProvider::new(session);

    let identity = IdentityStore::open(config.root.join("identity"))?;
    let mut client_config = ClientConfig {
        request_budget: usize::try_from(config.budgets.max_bucket_requests)?,
        maximum_attempts: 1,
        // The single BucketPacer is the pacing authority; the client's own per-host pacing would
        // only double-sleep behind it.
        minimum_host_interval: Duration::ZERO,
        ..ClientConfig::default()
    };
    client_config.enabled_routes = [RouteId::CommunityCallouts].into_iter().collect();
    client_config.shared_product_keys.insert(
        joshi_pump_api::community_origin().to_owned(),
        product_key.clone(),
    );
    let sessions: Arc<dyn SessionProvider> = Arc::new(NoSession);
    let client = Arc::new(PumpApiClient::new(
        client_config,
        identity.clone(),
        sessions,
    )?);

    let (stop_tx, stop_rx) = tokio::sync::watch::channel(false);
    let shared = Arc::new(Shared {
        journal: journal.clone(),
        pacer,
        provider,
        signer,
        product_key,
        stop: stop_rx,
        run_deadline,
        planned_end_us,
        sockets: config.sockets.clone(),
    });
    let policy = ReconnectPolicy {
        max_attempts: config.sockets.reconnect_max_attempts,
        initial_backoff: Duration::from_secs(config.sockets.reconnect_backoff_initial_seconds),
        max_backoff: Duration::from_secs(config.sockets.reconnect_backoff_cap_seconds),
    };

    let state = Arc::new(Mutex::new(RunState::default()));
    {
        let mut state = state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        for mint in &watch {
            attach_mint(
                &mut state,
                &shared,
                &client,
                &identity,
                &config.rest_poll,
                policy,
                mint,
            );
        }
    }
    let tick_handle = tokio::spawn(run_tick(
        Arc::clone(&shared),
        Arc::clone(&state),
        Arc::clone(&client),
        identity.clone(),
        config.config_path.clone(),
        run_dir.clone(),
        policy,
        mints_override.is_some(),
    ));

    // Wait out the planned window, or a signal, whichever first; then tell every lane to stop.
    let signalled = wait_for_end(run_deadline).await;
    let _ = stop_tx.send(true);

    // Drain every lane the tick may have added, until none remain.
    let mut mint_reports: Vec<MintReport> = Vec::new();
    let mut poll_summaries: Vec<Value> = Vec::new();
    loop {
        let (chains, polls) = {
            let mut state = state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            (
                std::mem::take(&mut state.chain_handles),
                std::mem::take(&mut state.poll_handles),
            )
        };
        if chains.is_empty() && polls.is_empty() {
            break;
        }
        for handle in chains {
            match handle.await {
                Ok(report) => mint_reports.push(report),
                Err(error) => {
                    journal.record(json!({
                        "kind": "chain_error",
                        "detail": format!("chain task join failed: {error}"),
                    }))?;
                }
            }
        }
        for handle in polls {
            match handle.await {
                Ok(summary) => poll_summaries.push(summary),
                Err(error) => {
                    journal.record(json!({
                        "kind": "chain_error",
                        "detail": format!("poll task join failed: {error}"),
                    }))?;
                }
            }
        }
    }
    let _ = tick_handle.await;

    let closed_wall = OffsetDateTime::now_utc();
    let (spent, by_kind) = shared.pacer.ledger().await;
    let receipt = build_receipt(
        &run_id,
        opened_at_us,
        planned_end_us,
        unix_micros(closed_wall)?,
        signalled,
        &mint_reports,
        &poll_summaries,
        spent,
        &by_kind,
        config.budgets.max_bucket_requests,
    );
    write_renamed(&run_dir.join("receipt.json"), &receipt)?;
    journal.record(json!({
        "kind": "run_close",
        "stopReason": if signalled { "run_signalled_to_stop" } else { "wall_clock_budget_exhausted" },
        "bucketSpend": spent,
    }))?;
    Ok(serde_json::to_string_pretty(&receipt)?)
}

/// True when a signal, not the planned window, ended the wait.
async fn wait_for_end(run_deadline: Instant) -> bool {
    let interrupt = tokio::signal::ctrl_c();
    #[cfg(unix)]
    {
        let Ok(mut terminate) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        else {
            tokio::select! {
                () = tokio::time::sleep_until(tokio::time::Instant::from_std(run_deadline)) => return false,
                _ = interrupt => return true,
            }
        };
        tokio::select! {
            () = tokio::time::sleep_until(tokio::time::Instant::from_std(run_deadline)) => false,
            _ = interrupt => true,
            _ = terminate.recv() => true,
        }
    }
    #[cfg(not(unix))]
    {
        tokio::select! {
            () = tokio::time::sleep_until(tokio::time::Instant::from_std(run_deadline)) => false,
            _ = interrupt => true,
        }
    }
}

/// The receipt of a run the handshake refused: short, durable, and honest about spend.
async fn refusal_receipt(
    run_id: &str,
    opened_at_us: i64,
    status: Option<u16>,
    reason: &str,
    pacer: &BucketPacer,
) -> Value {
    let (spent, by_kind) = pacer.ledger().await;
    json!({
        "contract": RECEIPT_CONTRACT,
        "runId": run_id,
        "openedAtUnixUs": opened_at_us,
        "stopReason": reason,
        "loginStatus": status,
        "mints": [],
        "spend": { "bucketRequests": spent, "byKind": by_kind },
    })
}

#[allow(clippy::too_many_arguments)] // Every receipt boundary is named explicitly.
fn build_receipt(
    run_id: &str,
    opened_at_us: i64,
    planned_end_us: i64,
    closed_at_us: i64,
    signalled: bool,
    mint_reports: &[MintReport],
    poll_summaries: &[Value],
    spent: u32,
    by_kind: &BTreeMap<String, u32>,
    ceiling: u32,
) -> Value {
    let mut mints = Vec::new();
    for report in mint_reports {
        let planned = planned_end_us - report.attached_at_us;
        let unobserved: i64 = report
            .spans
            .iter()
            .map(|span| span.upper_us - span.lower_us)
            .sum();
        let covered = planned - unobserved;
        let claimed_sum: i64 = report
            .sessions
            .iter()
            .map(|session| {
                let (lower, upper) = session.claimed(planned_end_us);
                upper - lower
            })
            .sum();
        mints.push(json!({
            "mint": report.mint,
            "attachedAtUnixUs": report.attached_at_us,
            "stopReason": report.stop.as_str(),
            "sessions": report.sessions.iter().map(|session| {
                let (lower, upper) = session.claimed(planned_end_us);
                json!({
                    "epoch": session.epoch,
                    "openedAtUnixUs": session.opened_at_us,
                    "closedAtUnixUs": session.closed_at_us,
                    "firstLivenessUnixUs": session.first_liveness_us,
                    "lastLivenessUnixUs": session.last_liveness_us,
                    "inboundFrames": session.inbound_frames,
                    "inboundBytes": session.inbound_bytes,
                    "pingsSent": session.pings_sent,
                    "endReason": session.end.as_str(),
                    "claimedWindowUnixUs": [lower, upper],
                })
            }).collect::<Vec<_>>(),
            "gaps": report.spans.iter().map(|span| json!({
                "lowerUnixUs": span.lower_us,
                "upperUnixUs": span.upper_us,
                "micros": span.upper_us - span.lower_us,
                "cause": span.cause,
                "recoverable": false,
            })).collect::<Vec<_>>(),
            "reconnects": report.reconnects,
            "totals": {
                "sessions": report.sessions.len(),
                "inboundFrames": report.frames,
                "inboundBytes": report.bytes,
                "pingsSent": report.pings,
                "plannedMicros": planned,
                "coveredMicros": covered,
                "unobservedMicros": unobserved,
                "claimedSumMicros": claimed_sum,
                // Holds by construction of the complement walk; restated so a later reader can
                // check it instead of trusting it.
                "tilingExact": covered + unobserved == planned,
            },
        }));
    }
    json!({
        "contract": RECEIPT_CONTRACT,
        "runId": run_id,
        "openedAtUnixUs": opened_at_us,
        "plannedEndUnixUs": planned_end_us,
        "closedAtUnixUs": closed_at_us,
        "stopReason": if signalled { "run_signalled_to_stop" } else { "wall_clock_budget_exhausted" },
        "arrivalClockNote": ARRIVAL_CLOCK_NOTE,
        "providerClockNote": PROVIDER_CLOCK_NOTE,
        "mints": mints,
        "restPolls": poll_summaries,
        "spend": {
            "bucketRequests": spent,
            "byKind": by_kind,
            "ceiling": ceiling,
            "note": "ticket_and_upgrade counts the mint AND the socket upgrade (the upgrade GET \
                     itself sends no x-api-key; it is charged conservatively)",
        },
    })
}

fn read_bounded(path: &Path, maximum_bytes: u64, label: &str) -> Result<Vec<u8>, Failure> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("{label} at {} unreadable: {error}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!("{label} at {} is not a regular file", path.display()).into());
    }
    if metadata.len() > maximum_bytes {
        return Err(format!(
            "{label} at {} exceeds the {maximum_bytes}-byte bound",
            path.display()
        )
        .into());
    }
    Ok(fs::read(path)?)
}

// ---------------------------------------------------------------------------
// The analysis: from the durable record alone, the first availability-gap distribution.
// ---------------------------------------------------------------------------

/// One ws first-arrival observation for one claimed id.
#[derive(Clone, Debug)]
struct WsFirst {
    arrival_us: i64,
    created_at_raw: Option<String>,
    event_type: String,
}

/// One fetched REST poll.
#[derive(Clone, Debug)]
struct PollObs {
    received_us: i64,
    ids: BTreeSet<String>,
    created_by_id: BTreeMap<String, String>,
}

#[derive(Default)]
struct MintEvidence {
    ws_first: BTreeMap<String, WsFirst>,
    polls: Vec<PollObs>,
    ws_first_liveness_us: Option<i64>,
    frames: u64,
}

/// Reopen one run's `events.jsonl` in a later process and derive, from the retained record
/// alone, the availability-gap distribution: per callout, the ws arrival (the availability upper
/// bound) against the first REST poll that carried it (when a poll-or-lose consumer would first
/// have held it).
#[allow(clippy::too_many_lines)] // One derivation, kept auditable in one place.
fn analyse(run_dir: &Path) -> Result<String, Failure> {
    let events_path = run_dir.join("events.jsonl");
    let text = fs::read_to_string(&events_path)
        .map_err(|error| format!("unable to read {}: {error}", events_path.display()))?;
    let mut evidence: BTreeMap<String, MintEvidence> = BTreeMap::new();
    let mut skipped_lines = 0_u64;
    for line in text.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            // A crash can truncate the final line; everything fsynced before it still counts.
            skipped_lines += 1;
            continue;
        };
        let kind = value.get("kind").and_then(Value::as_str).unwrap_or("");
        let mint = value.get("mint").and_then(Value::as_str).unwrap_or("");
        match kind {
            "frame" => {
                let entry = evidence.entry(mint.to_owned()).or_default();
                entry.frames += 1;
                let Some(arrival_us) = value.get("arrivalUnixUs").and_then(Value::as_i64) else {
                    continue;
                };
                entry.ws_first_liveness_us = Some(
                    entry
                        .ws_first_liveness_us
                        .map_or(arrival_us, |known| known.min(arrival_us)),
                );
                let claim = value.get("claim").cloned().unwrap_or(Value::Null);
                let Some(id) = claim.get("id").and_then(Value::as_str) else {
                    continue;
                };
                entry
                    .ws_first
                    .entry(id.to_owned())
                    .or_insert_with(|| WsFirst {
                        arrival_us,
                        created_at_raw: claim
                            .get("createdAtRaw")
                            .and_then(Value::as_str)
                            .map(ToOwned::to_owned),
                        event_type: value
                            .get("eventType")
                            .and_then(Value::as_str)
                            .unwrap_or("unclassified")
                            .to_owned(),
                    });
            }
            "session_close" => {
                let entry = evidence.entry(mint.to_owned()).or_default();
                if let Some(first) = value.get("firstLivenessUnixUs").and_then(Value::as_i64) {
                    entry.ws_first_liveness_us = Some(
                        entry
                            .ws_first_liveness_us
                            .map_or(first, |known| known.min(first)),
                    );
                }
            }
            "rest_poll" => {
                if value.get("outcome").and_then(Value::as_str) != Some("fetched") {
                    continue;
                }
                let Some(received_us) = value.get("receivedAtUnixUs").and_then(Value::as_i64)
                else {
                    continue;
                };
                let mut ids = BTreeSet::new();
                let mut created_by_id = BTreeMap::new();
                for row in value
                    .get("rows")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                {
                    if let Some(id) = row.get("id").and_then(Value::as_str) {
                        ids.insert(id.to_owned());
                        if let Some(created) = row.get("createdAtRaw").and_then(Value::as_str) {
                            created_by_id.insert(id.to_owned(), created.to_owned());
                        }
                    }
                }
                evidence
                    .entry(mint.to_owned())
                    .or_default()
                    .polls
                    .push(PollObs {
                        received_us,
                        ids,
                        created_by_id,
                    });
            }
            _ => {}
        }
    }

    let mut per_mint = Vec::new();
    let mut overall_rest_lag: Vec<i64> = Vec::new();
    let mut overall_claim_to_ws: Vec<i64> = Vec::new();
    for (mint, mut entry) in evidence {
        entry.polls.sort_by_key(|poll| poll.received_us);
        let mut rest_lag: Vec<i64> = Vec::new();
        let mut claim_to_ws: Vec<i64> = Vec::new();
        let mut both = 0_u64;
        let mut ws_only_polled_but_absent = 0_u64;
        let mut ws_only_run_ended = 0_u64;
        let mut rest_only_preexisting = 0_u64;
        let mut rest_only_missed_by_ws = 0_u64;
        let mut created_at_compared = 0_u64;
        let mut created_at_equal = 0_u64;
        let mut joined = Vec::new();

        let all_ids: BTreeSet<String> = entry
            .ws_first
            .keys()
            .cloned()
            .chain(entry.polls.iter().flat_map(|poll| poll.ids.iter().cloned()))
            .collect();
        for id in &all_ids {
            let ws = entry.ws_first.get(id);
            let first_poll = entry.polls.iter().find(|poll| poll.ids.contains(id));
            match (ws, first_poll) {
                (Some(ws), Some(poll)) => {
                    both += 1;
                    let lag = poll.received_us - ws.arrival_us;
                    rest_lag.push(lag);
                    overall_rest_lag.push(lag);
                    if let (Some(ws_created), Some(rest_created)) =
                        (ws.created_at_raw.as_deref(), poll.created_by_id.get(id))
                    {
                        created_at_compared += 1;
                        if ws_created == rest_created {
                            created_at_equal += 1;
                        }
                    }
                    if let Some(created_raw) = ws.created_at_raw.as_deref()
                        && let Ok(created_us) = parse_service_instant(created_raw)
                    {
                        claim_to_ws.push(ws.arrival_us - created_us);
                        overall_claim_to_ws.push(ws.arrival_us - created_us);
                    }
                    joined.push(json!({
                        "id": id,
                        "eventType": ws.event_type,
                        "wsArrivalUnixUs": ws.arrival_us,
                        "firstRestPollUnixUs": poll.received_us,
                        "restLagUs": lag,
                        "createdAtRaw": ws.created_at_raw,
                    }));
                }
                (Some(ws), None) => {
                    // Seen live on the socket, never in a poll. If a later poll happened and the
                    // id was absent, the fixed newest-50 window (or a non-callout event id)
                    // dropped it: the poll-or-lose loss, measured. Otherwise the run simply
                    // ended before the next poll could have carried it.
                    if entry
                        .polls
                        .iter()
                        .any(|poll| poll.received_us > ws.arrival_us)
                    {
                        ws_only_polled_but_absent += 1;
                    } else {
                        ws_only_run_ended += 1;
                    }
                }
                (None, Some(_)) => {
                    // Seen only by REST. A row whose provider-claimed createdAt precedes this
                    // mint's first ws liveness existed before coverage began (the baseline
                    // window), which is an exclusion, not a ws miss. The comparison crosses
                    // clock authorities and is declared as such.
                    let preexisting = first_poll
                        .and_then(|poll| poll.created_by_id.get(id))
                        .and_then(|created| parse_service_instant(created).ok())
                        .zip(entry.ws_first_liveness_us)
                        .is_some_and(|(created_us, first_liveness)| created_us < first_liveness);
                    if preexisting || entry.ws_first_liveness_us.is_none() {
                        rest_only_preexisting += 1;
                    } else {
                        rest_only_missed_by_ws += 1;
                    }
                }
                (None, None) => {}
            }
        }
        per_mint.push(json!({
            "mint": mint,
            "wsFrames": entry.frames,
            "restPollsFetched": entry.polls.len(),
            "calloutsBothWays": both,
            "restLagUs": stats(&mut rest_lag),
            "claimToWsArrivalUs": stats(&mut claim_to_ws),
            "wsOnly": {
                "polledButAbsent": ws_only_polled_but_absent,
                "runEndedBeforeNextPoll": ws_only_run_ended,
            },
            "restOnly": {
                "preexistingBeforeWsCoverage": rest_only_preexisting,
                "missedByWs": rest_only_missed_by_ws,
            },
            "createdAtAgreement": {
                "compared": created_at_compared,
                "equal": created_at_equal,
            },
            "joined": joined,
        }));
    }

    let analysis = json!({
        "contract": ANALYSIS_CONTRACT,
        "runDir": run_dir.display().to_string(),
        "skippedLines": skipped_lines,
        "perMint": per_mint,
        "overall": {
            "restLagUs": stats(&mut overall_rest_lag),
            "claimToWsArrivalUs": stats(&mut overall_claim_to_ws),
        },
        "caveats": [
            "restLagUs compares two instants stamped by THIS process's wall clock (ws frame \
             arrival vs REST poll receive): one clock authority, the honest number.",
            "claimToWsArrivalUs subtracts the PROVIDER's createdAt claim (ISO-8601 microseconds, \
             coin-communities clock) from OUR arrival wall clock: two clock authorities, so its \
             absolute value inherits both clocks' skew and is reported for shape, not truth.",
            "ws arrival is an availability UPPER BOUND: the fact was available no later than \
             this; after a coverage gap it does not even bound tightly.",
            "wsOnly.polledButAbsent conflates the newest-50 window rolling over with event ids \
             that are not callout rows (message/like ids); read it beside the eventType mix.",
            "a run whose receipt shows gaps must read this distribution as conditioned on \
             coverage: callouts occurring inside gaps are invisible to the ws side entirely.",
        ],
    });
    write_renamed(&run_dir.join("availability_analysis.json"), &analysis)?;
    Ok(serde_json::to_string_pretty(&analysis)?)
}

/// Order statistics over a duration sample. Sorts in place; an empty sample says so rather than
/// inventing zeros.
fn stats(values: &mut [i64]) -> Value {
    if values.is_empty() {
        return json!({ "n": 0 });
    }
    values.sort_unstable();
    let n = values.len();
    let sum: i128 = values.iter().map(|value| i128::from(*value)).sum();
    #[allow(clippy::cast_possible_truncation)] // mean of i64 samples fits i64
    let mean = (sum / i128::try_from(n).unwrap_or(1)) as i64;
    json!({
        "n": n,
        "minUs": values[0],
        "p10Us": percentile(values, 10),
        "p25Us": percentile(values, 25),
        "p50Us": percentile(values, 50),
        "p75Us": percentile(values, 75),
        "p90Us": percentile(values, 90),
        "maxUs": values[n - 1],
        "meanUs": mean,
    })
}

/// Nearest-rank percentile over a sorted, non-empty sample.
fn percentile(sorted: &[i64], hundredths: usize) -> i64 {
    let n = sorted.len();
    let rank = (n * hundredths).div_ceil(100).max(1);
    sorted[rank - 1]
}

#[cfg(test)]
mod tests {
    use super::*;

    const MINT_A: &str = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump";
    const MINT_B: &str = "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump";
    const MINT_C: &str = "257DpUEb5H11WRX5GHyYGcoUzZeA27W5DR74eYRbpump";

    fn policy() -> ReconnectPolicy {
        ReconnectPolicy {
            max_attempts: 3,
            initial_backoff: Duration::from_secs(2),
            max_backoff: Duration::from_secs(30),
        }
    }

    #[test]
    fn a_refusal_at_the_first_handshake_is_terminal_and_distinct_from_reconnect_refusal() {
        let first = next_step(
            policy(),
            SessionEnd::TicketRefused,
            true,
            0,
            Duration::from_mins(10),
        );
        assert_eq!(first, Next::Stop(RunStop::RefusedAtHandshake));
        let later = next_step(
            policy(),
            SessionEnd::UpgradeRefused,
            false,
            0,
            Duration::from_mins(10),
        );
        assert_eq!(later, Next::Stop(RunStop::RefusedOnReconnect));
    }

    #[test]
    fn hiccups_reconnect_until_the_consecutive_ceiling_and_never_past_the_window() {
        let step = next_step(
            policy(),
            SessionEnd::ProviderClosedSocket,
            false,
            0,
            Duration::from_mins(10),
        );
        assert_eq!(
            step,
            Next::Reconnect {
                attempt: 1,
                backoff: Duration::from_secs(2)
            }
        );
        // Backoff doubles per consecutive failure and clamps to the cap.
        assert_eq!(policy().backoff(1), Duration::from_secs(2));
        assert_eq!(policy().backoff(2), Duration::from_secs(4));
        assert_eq!(policy().backoff(10), Duration::from_secs(30));
        // A wait may never overrun the remaining window.
        let clamped = next_step(
            policy(),
            SessionEnd::TransportError,
            false,
            2,
            Duration::from_secs(1),
        );
        assert_eq!(
            clamped,
            Next::Reconnect {
                attempt: 3,
                backoff: Duration::from_secs(1)
            }
        );
        // The consecutive ceiling stops the run.
        let exhausted = next_step(
            policy(),
            SessionEnd::TransportError,
            false,
            3,
            Duration::from_mins(10),
        );
        assert_eq!(exhausted, Next::Stop(RunStop::ReconnectAttemptsExhausted));
        // No window left means no attempt, whatever the count.
        let done = next_step(
            policy(),
            SessionEnd::TransportError,
            false,
            0,
            Duration::ZERO,
        );
        assert_eq!(done, Next::Stop(RunStop::WallClockBudget));
    }

    fn session(
        epoch: u64,
        opened: i64,
        closed: i64,
        first: Option<i64>,
        last: Option<i64>,
        end: SessionEnd,
    ) -> SessionOutcome {
        SessionOutcome {
            epoch,
            opened_at_us: opened,
            closed_at_us: closed,
            first_liveness_us: first,
            last_liveness_us: last,
            inbound_frames: 0,
            inbound_bytes: 0,
            pings_sent: 0,
            end,
        }
    }

    #[test]
    fn a_faulting_session_vouches_only_to_its_last_liveness_and_a_silent_one_for_nothing() {
        let faulted = session(
            1,
            1_000,
            9_000,
            Some(2_000),
            Some(6_000),
            SessionEnd::TransportError,
        );
        assert_eq!(faulted.claimed(100_000), (2_000, 6_000));
        let planned = session(
            2,
            1_000,
            100_500,
            Some(2_000),
            Some(99_000),
            SessionEnd::PlannedWindowReached,
        );
        assert_eq!(planned.claimed(100_000), (2_000, 100_000));
        let silent = session(3, 1_000, 9_000, None, None, SessionEnd::InactivityCeiling);
        assert_eq!(silent.claimed(100_000), (1_000, 1_000));
    }

    #[test]
    fn gaps_tile_the_window_exactly_with_causes_split_at_the_close() {
        let sessions = vec![
            session(
                1,
                0,
                40_000,
                Some(10_000),
                Some(30_000),
                SessionEnd::TransportError,
            ),
            session(
                2,
                50_000,
                100_000,
                Some(60_000),
                Some(99_000),
                SessionEnd::PlannedWindowReached,
            ),
        ];
        let spans = unobserved_spans(&sessions, 0, 100_000, RunStop::WallClockBudget);
        // Session 1 claims [10_000,30_000] (fault: vouches only to its last liveness) and
        // session 2 claims [60_000,100_000]. The complement: [0,10_000) awaiting the first
        // liveness; [30_000,40_000) faulting-but-still-ours (before the close); [40_000,60_000)
        // between sockets (after the close, through the next session's first word).
        assert_eq!(spans.len(), 3);
        assert_eq!(
            (spans[0].lower_us, spans[0].upper_us, spans[0].cause),
            (0, 10_000, CAUSE_AWAITING_FIRST_LIVENESS)
        );
        assert_eq!(
            (spans[1].lower_us, spans[1].upper_us, spans[1].cause),
            (30_000, 40_000, "transport_error_before_planned_end")
        );
        assert_eq!(
            (spans[2].lower_us, spans[2].upper_us, spans[2].cause),
            (40_000, 60_000, CAUSE_BACKOFF_WAIT)
        );
        // The tiling identity: covered plus unobserved is exactly the window, and covered is
        // exactly the union of the claims.
        let unobserved: i64 = spans.iter().map(|span| span.upper_us - span.lower_us).sum();
        let covered = 100_000 - unobserved;
        let claimed_union = (30_000 - 10_000) + (100_000 - 60_000);
        assert_eq!(covered, claimed_union);
    }

    #[test]
    fn a_chain_with_no_sessions_is_one_gap_under_the_stop_cause() {
        let spans = unobserved_spans(&[], 5_000, 20_000, RunStop::RefusedAtHandshake);
        assert_eq!(spans.len(), 1);
        assert_eq!(
            (spans[0].lower_us, spans[0].upper_us, spans[0].cause),
            (5_000, 20_000, "provider_refused_at_handshake")
        );
        assert_eq!(spans[0].anchor, None);
        assert!(unobserved_spans(&[], 20_000, 20_000, RunStop::WallClockBudget).is_empty());
    }

    #[test]
    fn adjacent_same_cause_spans_merge() {
        let merged = merge_adjacent(vec![
            Unobserved {
                lower_us: 0,
                upper_us: 10,
                cause: CAUSE_BACKOFF_WAIT,
                anchor: Some(0),
            },
            Unobserved {
                lower_us: 10,
                upper_us: 20,
                cause: CAUSE_BACKOFF_WAIT,
                anchor: Some(1),
            },
            Unobserved {
                lower_us: 20,
                upper_us: 30,
                cause: CAUSE_AWAITING_FIRST_LIVENESS,
                anchor: Some(1),
            },
        ]);
        assert_eq!(merged.len(), 2);
        assert_eq!((merged[0].lower_us, merged[0].upper_us), (0, 20));
    }

    #[test]
    fn frames_classify_by_event_type_and_surface_the_occurrence_claim() {
        let (kind, claim) = classify_frame(
            br#"{"eventType":"message_update","data":{"callout":{"id":"uuid-1","createdAt":"2026-08-25T01:02:03.123456Z","parentCalloutId":"uuid-0"}}}"#,
        );
        assert_eq!(kind, "message_update");
        assert_eq!(claim.id.as_deref(), Some("uuid-1"));
        assert_eq!(
            claim.created_at_raw.as_deref(),
            Some("2026-08-25T01:02:03.123456Z")
        );
        assert_eq!(claim.parent_callout_id.as_deref(), Some("uuid-0"));
        assert_eq!(claim.path, Some("data.callout"));

        let (kind, claim) = classify_frame(br#"{"eventType":"pong"}"#);
        assert_eq!(kind, "pong");
        assert_eq!(claim, FrameClaim::default());

        let (kind, _) = classify_frame(b"not json at all");
        assert_eq!(kind, "malformed");
        let (kind, claim) =
            classify_frame(br#"{"id":"top-level","createdAt":"2026-08-25T00:00:00.000001Z"}"#);
        assert_eq!(kind, "unclassified");
        assert_eq!(claim.path, Some("."));
    }

    #[test]
    fn the_watch_set_leads_with_hot_mints_dedupes_and_caps() {
        let hot = vec![MINT_C.to_owned(), MINT_A.to_owned()];
        let watch = vec![
            (MINT_A.to_owned(), Some("DREGG".to_owned())),
            (MINT_B.to_owned(), Some("SOLVE".to_owned())),
        ];
        let set = derive_watch_set(&hot, &watch, 3);
        assert_eq!(set, vec![MINT_C, MINT_A, MINT_B]);
        let capped = derive_watch_set(&hot, &watch, 2);
        assert_eq!(capped, vec![MINT_C, MINT_A]);
    }

    #[test]
    fn hot_requests_parse_tolerantly_filter_expiry_and_refuse_a_wrong_contract() {
        let dir = tempfile::tempdir().expect("a temp dir");
        let path = dir.path().join("hot-requests.json");
        let future = wall_string(OffsetDateTime::now_utc() + time::Duration::minutes(20))
            .expect("a formattable future instant");
        let body = format!(
            r#"{{"contract":"joshi.attention.hot_requests.v1","schemaVersion":1,
                "unknownTopLevel":true,
                "requests":[
                  {{"mint":"{MINT_C}","expiresAt":"{future}","unknownField":"tolerated"}},
                  {{"mint":"{MINT_A}","expiresAt":"2020-01-01T00:00:00.000000Z"}},
                  {{"mint":"{MINT_B}"}}
                ]}}"#
        );
        fs::write(&path, body).expect("written");
        let hot = read_hot_mints(&path, OffsetDateTime::now_utc()).expect("tolerant parse");
        assert_eq!(hot, vec![MINT_C]);

        fs::write(&path, r#"{"contract":"something.else.v9","requests":[]}"#).expect("written");
        assert!(read_hot_mints(&path, OffsetDateTime::now_utc()).is_err());
        assert!(
            read_hot_mints(&dir.path().join("absent.json"), OffsetDateTime::now_utc())
                .expect("a missing file is an empty set")
                .is_empty()
        );
    }

    #[test]
    fn the_keeper_config_is_read_tolerantly_for_exactly_what_this_consumer_needs() {
        let dir = tempfile::tempdir().expect("a temp dir");
        let path = dir.path().join("keeper.toml");
        fs::write(
            &path,
            format!(
                r#"
root = "../state/keeper"
key_file = "/nowhere/helius"
community_key_file = "/nowhere/cc-key"
some_future_key = "tolerated"

[budgets]
per_cycle_requests = 30
per_day_requests = 3500

[[mints]]
mint = "{MINT_A}"
label = "DREGG"
taps = ["candles", "community_callouts"]
candles_cadence_minutes = 10

[[mints]]
mint = "{MINT_B}"
taps = ["candles"]
"#
            ),
        )
        .expect("written");
        let inputs = read_keeper_inputs(&path).expect("tolerant read");
        assert_eq!(
            inputs.watch_mints,
            vec![(MINT_A.to_owned(), Some("DREGG".to_owned()))]
        );
        assert!(
            inputs
                .hot_requests_file
                .ends_with("state/keeper/hot-requests.json")
        );
        assert_eq!(inputs.community_key_file, PathBuf::from("/nowhere/cc-key"));
    }

    #[test]
    fn the_shipped_availability_config_parses_and_its_guards_hold() {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let shipped = manifest.join("../../ops/availability.toml");
        let config = load_config(&shipped).expect("the shipped config parses");
        assert!(config.sockets.max_concurrent <= 3);
        assert!(config.sockets.inactivity_ceiling_seconds > config.sockets.ping_interval_seconds);
        assert!(config.budgets.min_gap_seconds >= 1);
        assert!(config.keeper_config.ends_with("keeper.toml"));

        let dir = tempfile::tempdir().expect("a temp dir");
        let bad = dir.path().join("bad.toml");
        fs::write(
            &bad,
            r#"
keeper_config = "keeper.toml"
root = "../state/availability"
wallet_key_file = "/nowhere/wallet"
[sockets]
max_concurrent = 7
ping_interval_seconds = 25
inactivity_ceiling_seconds = 90
reconnect_max_attempts = 6
reconnect_backoff_initial_seconds = 2
reconnect_backoff_cap_seconds = 120
[rest_poll]
cadence_minutes = 10
first_poll_delay_seconds = 45
[budgets]
min_gap_seconds = 3
max_bucket_requests = 200
"#,
        )
        .expect("written");
        assert!(load_config(&bad).is_err(), "a 7-socket cap must be refused");
    }

    #[test]
    fn the_journal_appends_stamped_lines_that_read_back_whole() {
        let dir = tempfile::tempdir().expect("a temp dir");
        let path = dir.path().join("events.jsonl");
        let journal = Journal {
            recorder: Arc::new(Mutex::new(Recorder::open(&path).expect("opens"))),
            clock: Arc::new(RunClock::new("test")),
        };
        journal
            .record(json!({"kind": "run_open", "contract": EVENTS_CONTRACT}))
            .expect("first line");
        journal
            .record(json!({"kind": "frame", "mint": MINT_A}))
            .expect("second line");
        let text = fs::read_to_string(&path).expect("readable");
        let lines: Vec<Value> = text
            .lines()
            .map(|line| serde_json::from_str(line).expect("every line parses"))
            .collect();
        assert_eq!(lines.len(), 2);
        for line in &lines {
            assert!(line.get("recordedAtUnixUs").is_some());
            assert!(line.get("recordedMonotonicNs").is_some());
        }
    }

    #[test]
    fn wall_micros_format_and_parse_round_trip() {
        let micros = 1_787_619_256_218_057_i64; // 2026-08-25T00:54:16.218057Z
        let wall = OffsetDateTime::from_unix_timestamp_nanos(i128::from(micros) * 1_000)
            .expect("in range");
        let text = wall_string(wall).expect("formats");
        assert_eq!(text, "2026-08-25T00:54:16.218057Z");
        assert_eq!(parse_service_instant(&text).expect("parses"), micros);
    }

    #[test]
    fn percentiles_are_nearest_rank_and_empty_samples_say_so() {
        let mut values = vec![50, 10, 40, 30, 20];
        let rendered = stats(&mut values);
        assert_eq!(rendered["n"], 5);
        assert_eq!(rendered["minUs"], 10);
        assert_eq!(rendered["p50Us"], 30);
        assert_eq!(rendered["p90Us"], 50);
        assert_eq!(rendered["maxUs"], 50);
        assert_eq!(rendered["meanUs"], 30);
        assert_eq!(stats(&mut Vec::new())["n"], 0);
    }

    #[test]
    fn the_analysis_joins_ws_arrivals_to_the_first_poll_that_carried_them() {
        let dir = tempfile::tempdir().expect("a temp dir");
        let events = dir.path().join("events.jsonl");
        // A ws frame for callout-1 at t=1_000_000us; a first poll at t=2_000_000 that missed it
        // (window pre-refresh), a second at t=601_000_000 that carried it; callout-0 preexisting
        // (created before ws liveness, REST only); callout-2 ws-only though a later poll ran.
        let lines = [
            json!({"kind":"run_open","contract":EVENTS_CONTRACT}),
            json!({"kind":"session_close","mint":MINT_A,"firstLivenessUnixUs":900_000}),
            json!({"kind":"frame","mint":MINT_A,"eventType":"message_update",
                   "arrivalUnixUs":1_000_000,
                   "claim":{"id":"callout-1","createdAtRaw":"1970-01-01T00:00:00.950000Z"}}),
            json!({"kind":"frame","mint":MINT_A,"eventType":"message_update",
                   "arrivalUnixUs":3_000_000,
                   "claim":{"id":"callout-2","createdAtRaw":"1970-01-01T00:00:02.900000Z"}}),
            json!({"kind":"rest_poll","mint":MINT_A,"ordinal":1,"outcome":"fetched",
                   "receivedAtUnixUs":2_000_000,
                   "rows":[{"id":"callout-0","createdAtRaw":"1970-01-01T00:00:00.100000Z"}]}),
            json!({"kind":"rest_poll","mint":MINT_A,"ordinal":2,"outcome":"fetched",
                   "receivedAtUnixUs":601_000_000,
                   "rows":[{"id":"callout-0","createdAtRaw":"1970-01-01T00:00:00.100000Z"},
                            {"id":"callout-1","createdAtRaw":"1970-01-01T00:00:00.950000Z"}]}),
        ];
        let mut body = String::new();
        for line in &lines {
            body.push_str(&serde_json::to_string(line).expect("serializes"));
            body.push('\n');
        }
        fs::write(&events, body).expect("written");
        let rendered = analyse(dir.path()).expect("the analysis derives");
        let analysis: Value = serde_json::from_str(&rendered).expect("parses");
        let mint = &analysis["perMint"][0];
        assert_eq!(mint["mint"], MINT_A);
        assert_eq!(mint["calloutsBothWays"], 1);
        assert_eq!(mint["restLagUs"]["n"], 1);
        assert_eq!(mint["restLagUs"]["p50Us"], 600_000_000);
        assert_eq!(mint["wsOnly"]["polledButAbsent"], 1);
        assert_eq!(mint["wsOnly"]["runEndedBeforeNextPoll"], 0);
        assert_eq!(mint["restOnly"]["preexistingBeforeWsCoverage"], 1);
        assert_eq!(mint["restOnly"]["missedByWs"], 0);
        assert_eq!(mint["createdAtAgreement"]["compared"], 1);
        assert_eq!(mint["createdAtAgreement"]["equal"], 1);
        // The claim-to-arrival delta: 1_000_000 - 950_000, cross-clock.
        assert_eq!(mint["claimToWsArrivalUs"]["p50Us"], 50_000);
        // The derivation is durable beside the record.
        assert!(dir.path().join("availability_analysis.json").exists());
    }

    #[test]
    fn subjects_must_be_mint_shaped_before_they_reach_a_url() {
        assert!(mint_shaped(MINT_A));
        assert!(!mint_shaped(""));
        assert!(!mint_shaped("../smuggle"));
        assert!(!mint_shaped("with space padded to length xxxxxxxxxx"));
    }
}
