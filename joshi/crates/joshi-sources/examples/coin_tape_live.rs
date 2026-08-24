//! One coin's trade tape at EVENT resolution, retained under budgets this process enforces.
//!
//! ```text
//! coin_tape_live record  --root <dir> --mints <csv> [--seconds n] [--max-frames n]
//!                        [--max-bytes n] [--inactivity-seconds n] [--key-file <path>]
//!                        [--reconnect-attempts n] [--reconnect-backoff-seconds n]
//!                        [--reconnect-backoff-cap-seconds n]
//! coin_tape_live analyse --root <dir> [--bucket-seconds 60] [--trades <fetch-outcome.json>]...
//! ```
//!
//! `record` holds a `PumpPortal` trade subscription for the planned window and retains every
//! inbound frame — trades, acknowledgements, provider control, anything — as exact bytes through
//! the ordinary source-admission path. Three budgets bound it and this process checks all three
//! itself rather than trusting the transport: a wall-clock ceiling, a frame ceiling and a byte
//! ceiling. The frame and byte ceilings span the whole run; the inactivity ceiling is judged per
//! connection, because it asks whether THIS socket is still delivering.
//!
//! Holding the window takes more than one socket. MEASURED 2026-08-23: a funded 40-minute session
//! streamed 1690 frames and the provider closed the socket 72 seconds before the planned end.
//! A provider that accepted the subscription and then hiccuped is reconnected to, under a doubling
//! bounded backoff; each connection is its own SESSION with its own coverage window, and the span
//! between the last thing a dying socket proved and the next socket's first word is a durable
//! coverage GAP naming its cause. This feed exposes no replay cursor, so a gap is unrecoverable
//! and is written down rather than smoothed over.
//!
//! The distinction that decides whether to reconnect is REFUSAL versus HICCUP. A provider that
//! answers the subscription with a refusal — what an unfunded key gets — is never retried: it
//! already said no, and re-asking is hammering. A refusal arriving on a RECONNECT (accepted
//! earlier, refused now, which is what a plan expiring mid-run looks like) also terminates, under
//! its own distinct reason.
//!
//! `analyse` reopens the catalog read-only in a later process and answers, from the retained bytes
//! alone: what a frame carries, what clock it carries, whether its `txType` label is derivable
//! from the frame itself, and the maximum drawdown visible at event resolution against the maximum
//! drawdown a fixed-width candle series over the same window could have shown.
//!
//! It constructs no transaction, signs nothing and submits nothing. `subscribeTokenTrade` is a
//! read subscription; no trading method is ever sent.

use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use bytes::Bytes;
use futures_util::{Sink, SinkExt, Stream, StreamExt};
use joshi_admission::{
    AdmissionPolicy, PublicStoreReceiptV1, Sha256Digest, SourceDraftBatch, SourceFrameInput,
    source_drafts, source_frames,
};
use joshi_domain::{
    CoverageId, OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp, ValueDigest,
};
use joshi_evidence::{Boundary, CoverageGap, CoverageScope, CoverageWindow, EvidenceDraft};
use joshi_sources::{
    ADAPTER_CONTRACT_VERSION, ContentType, EvidenceContext, FrameDirection, LogicalSourceLocator,
    ProviderEventTime, PumpPortalFrameKind, RawSourceFrame, RetainedFrameEnvelope, SourceId,
    StreamClass, Transport, UnixMillis, classify_pumpportal_frame,
};
use joshi_store::{
    DurableSourceObservation, SourceRegistration, SqliteStore, StoreConfig, StoreMode, VerifyDepth,
};
use serde_json::{Value, json};
use time::OffsetDateTime;
use tokio_tungstenite::tungstenite::Message;

const ENDPOINT: &str = "wss://pumpportal.fun/api/data";
const SOURCE_ID: &str = "pumpportal.websocket.data.v1";
const SOURCE_NAMESPACE: &str = "read_only_market_source";
/// The durable catalog indexes coverage by level and recognises exactly two families. A per-coin
/// trade subscription is a leased hot scope, so it claims coverage under the same family a Helius
/// hot lease does rather than inventing a third the index cannot rank.
const COVERAGE_FAMILY: &str = "hot_lane";
const CATALOG_ID: &str = "joshi-coin-tape";
const FEED_LOCATOR: &str = "subscribeTokenTrade";
const INLINE_BLOB_MAX_BYTES: u64 = 4 * 1024 * 1024;
const MAX_OBSERVATIONS_PER_BATCH: usize = 64;
const MAX_RAW_BYTES_PER_BATCH: u64 = 64 * 1024 * 1024;
const BUSY_TIMEOUT: Duration = Duration::from_secs(5);
const READBACK_LIMIT: usize = 200_000;
const SEVERITY_DEGRADED: &str = "degraded";
const SEVERITY_SCOPE_STOPPED: &str = "scope_stopped";
/// Wall-versus-monotonic disagreement, inside one connection, that this run reads as a suspend
/// rather than a slow loop.
const SUSPEND_SKEW_MILLIS: i64 = 5_000;
/// The head of the planned window spent connecting and asking, before the provider's first word.
const CAUSE_AWAITING_FIRST_LIVENESS: &str = "awaiting_first_liveness";
/// Time spent between sockets: the backoff, the handshake and the re-subscription.
const CAUSE_BACKOFF_WAIT: &str = "backoff_wait";

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let command = arguments.first().ok_or_else(usage)?.clone();
    let root = PathBuf::from(flag(&arguments, "--root").ok_or_else(usage)?);
    match command.as_str() {
        "record" => {
            let mints = flag(&arguments, "--mints").ok_or_else(usage)?;
            let budget = Budget {
                seconds: parse_flag(&arguments, "--seconds", 300)?,
                max_frames: parse_flag(&arguments, "--max-frames", 20_000)?,
                max_bytes: parse_flag(&arguments, "--max-bytes", 32 * 1024 * 1024)?,
                inactivity_seconds: parse_flag(&arguments, "--inactivity-seconds", 45)?,
            };
            let policy = ReconnectPolicy {
                max_attempts: parse_flag(&arguments, "--reconnect-attempts", 6_u32)?,
                initial_backoff: Duration::from_secs(parse_flag(
                    &arguments,
                    "--reconnect-backoff-seconds",
                    2_u64,
                )?),
                max_backoff: Duration::from_secs(parse_flag(
                    &arguments,
                    "--reconnect-backoff-cap-seconds",
                    60_u64,
                )?),
            };
            let key_file = flag(&arguments, "--key-file").map(PathBuf::from);
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?;
            println!(
                "{}",
                runtime.block_on(record(&root, &mints, budget, policy, key_file.as_deref()))?
            );
        }
        "analyse" => {
            let bucket = parse_flag(&arguments, "--bucket-seconds", 60)?;
            let trades = repeated_flag(&arguments, "--trades");
            println!("{}", analyse(&root, bucket, &trades)?);
        }
        _ => return Err(usage()),
    }
    Ok(())
}

fn usage() -> Box<dyn Error> {
    "usage: coin_tape_live <record|analyse> --root <dir> [--mints <csv>] [--seconds n] \
     [--max-frames n] [--max-bytes n] [--inactivity-seconds n] [--key-file <path>] \
     [--reconnect-attempts n] [--reconnect-backoff-seconds n] \
     [--reconnect-backoff-cap-seconds n] [--bucket-seconds n] [--trades <fetch-outcome.json>]"
        .into()
}

fn flag(arguments: &[String], name: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == name)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

fn repeated_flag(arguments: &[String], name: &str) -> Vec<String> {
    arguments
        .iter()
        .enumerate()
        .filter(|(_, value)| value.as_str() == name)
        .filter_map(|(index, _)| arguments.get(index + 1).cloned())
        .collect()
}

fn parse_flag<T: std::str::FromStr>(
    arguments: &[String],
    name: &str,
    default: T,
) -> Result<T, Box<dyn Error>>
where
    T::Err: std::fmt::Display,
{
    match flag(arguments, name) {
        None => Ok(default),
        Some(value) => value
            .parse::<T>()
            .map_err(|error| format!("invalid {name}: {error}").into()),
    }
}

#[derive(Clone, Copy, Debug)]
struct Budget {
    seconds: u64,
    max_frames: usize,
    max_bytes: usize,
    /// Longest silence this run treats as a live-but-quiet socket rather than a dead one.
    inactivity_seconds: u64,
}

/// A bounded, doubling wait between reconnect attempts.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ReconnectPolicy {
    /// Longest run of CONSECUTIVE failed attempts tolerated. Zero forbids reconnecting at all,
    /// which is exactly the one-shot recorder this grew out of. The count is consecutive rather
    /// than cumulative because a connection that actually delivered frames is evidence the
    /// provider is serving us again, and a churning provider is still bounded by the wall clock.
    max_attempts: u32,
    initial_backoff: Duration,
    max_backoff: Duration,
}

impl ReconnectPolicy {
    /// Wait before the `attempt`-th consecutive try, 1-based: the initial wait doubled once per
    /// earlier consecutive failure, clamped to the ceiling.
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

/// Why ONE connection ended. This is not why the run ended: most of these are survivable.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SessionEnd {
    /// The wall clock reached the planned end while this connection was healthy.
    PlannedWindowReached,
    FrameBudget,
    ByteBudget,
    ProviderClosedSocket,
    TransportError,
    /// Nothing proved this socket alive for longer than the inactivity ceiling. MEASURED THE HARD
    /// WAY: a first run left a half-open socket after the host suspended, and `next()` simply
    /// never returned again. From inside the loop that is indistinguishable from a market that
    /// went quiet, so the connection is abandoned rather than left to accumulate an unobserved
    /// window it would later report as coverage.
    InactivityCeiling,
    /// The host's wall clock ran ahead of its monotonic clock, which means this process was
    /// suspended. Everything between the last liveness and the resume instant is unobserved, and
    /// the socket that survived a suspend is almost certainly half-open.
    HostSuspended,
    /// The provider answered the subscription with a refusal instead of an acknowledgement.
    /// MEASURED 2026-08-22: a keyless connection is refused with "'subscribeTokenTrade' ...
    /// only available when connecting with an API key funded with at least 0.02 SOL". A window
    /// after that frame is not quiet, it is unsubscribed.
    SubscriptionRefused,
    /// A reconnect attempt could not establish a socket at all. No session ran; this exists so the
    /// same decision function counts the attempt and spaces the next one.
    ConnectFailed,
}

impl SessionEnd {
    /// The run-level stop this end forces, or `None` when the run may reconnect and go on.
    ///
    /// The refusal arms are the whole reconnect/refusal distinction: a provider that ACCEPTED the
    /// subscription and then dropped the socket is a hiccup and is retried; a provider that
    /// ANSWERED WITH A REFUSAL said no, and re-asking is hammering. A refusal that arrives on a
    /// reconnect — accepted at the start of the run, refused now — is the shape of a plan expiring
    /// mid-run, and terminates under its own reason so the receipt cannot confuse the two.
    const fn terminal(self, first_session: bool) -> Option<RunStop> {
        match self {
            Self::PlannedWindowReached => Some(RunStop::WallClockBudget),
            Self::FrameBudget => Some(RunStop::FrameBudget),
            Self::ByteBudget => Some(RunStop::ByteBudget),
            Self::SubscriptionRefused if first_session => Some(RunStop::SubscriptionRefused),
            Self::SubscriptionRefused => Some(RunStop::SubscriptionRefusedOnReconnect),
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
            Self::InactivityCeiling => "no_frame_within_inactivity_ceiling",
            Self::HostSuspended => "host_suspended_during_window",
            Self::SubscriptionRefused => "provider_refused_subscription",
            Self::ConnectFailed => "reconnect_handshake_failed",
        }
    }
}

/// Why the whole chained run stopped. Every stop is one of these; none of them is a silence.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RunStop {
    WallClockBudget,
    FrameBudget,
    ByteBudget,
    SubscriptionRefused,
    /// Accepted earlier in this run, refused on a later connection. A plan that expired mid-run
    /// looks exactly like this, and it is NOT the same event as being refused at the door.
    SubscriptionRefusedOnReconnect,
    ReconnectAttemptsExhausted,
}

impl RunStop {
    const fn as_str(self) -> &'static str {
        match self {
            Self::WallClockBudget => "wall_clock_budget_exhausted",
            Self::FrameBudget => "frame_budget_exhausted",
            Self::ByteBudget => "byte_budget_exhausted",
            Self::SubscriptionRefused => "provider_refused_subscription",
            Self::SubscriptionRefusedOnReconnect => "provider_refused_subscription_on_reconnect",
            Self::ReconnectAttemptsExhausted => "reconnect_attempts_exhausted",
        }
    }

    /// Whether the run stayed on the job until the wall clock the caller named ran out.
    ///
    /// This is NOT a claim that the window was fully observed: a run can reach its planned end
    /// while waiting out a backoff, and then this is true and a gap still stands. Read it with
    /// `totals.unobservedMillis`, never on its own.
    const fn planned_window_completed(self) -> bool {
        matches!(self, Self::WallClockBudget)
    }

    /// What kept the tail of the planned window unobserved. Reaching the planned end with a hole
    /// still open means the run spent that tail between sockets.
    const fn trailing_cause(self) -> &'static str {
        match self {
            Self::WallClockBudget => CAUSE_BACKOFF_WAIT,
            other => other.as_str(),
        }
    }
}

/// What the run does after one connection ends.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Next {
    Reconnect { attempt: u32, backoff: Duration },
    Stop(RunStop),
}

/// The reconnect policy itself, with nothing else attached: given how a connection ended, how many
/// consecutive attempts have already failed and how much of the planned window is left, either
/// name the next attempt and its wait or name the run's terminal stop.
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
        // Never wait past the window the caller asked for: an attempt that could only land after
        // the planned end is not an attempt, it is an overrun.
        backoff: policy.backoff(attempt).min(remaining),
    }
}

struct Captured {
    frame: RawSourceFrame,
    mono_ns: u64,
}

/// One poll of a live socket, in the terms the session loop reasons about rather than the
/// transport's. `Quiet` is the absence of an answer within the poll window, which is deliberately
/// NOT liveness: whether a silence is a quiet market, a dead socket or a suspended host is decided
/// against the clocks at the top of the next iteration.
enum WirePoll {
    /// Bytes to retain, exactly as they arrived.
    Frame(Bytes),
    /// The socket proved itself alive without delivering anything retainable — a websocket ping or
    /// pong. It carries no JSON body, so it feeds the inactivity clock and is counted, not stored.
    Alive,
    Quiet,
    Closed,
    Failed,
}

/// The one seam the session loop reaches the network through, so the reconnect and coverage
/// behaviour can be driven by a scripted transport in the tests below.
trait Wire {
    async fn send_subscription(&mut self, text: String) -> Result<(), ()>;
    async fn poll_within(&mut self, within: Duration) -> WirePoll;
}

/// The live socket behind that seam.
struct SocketWire<S>(S);

impl<S, E> Wire for SocketWire<S>
where
    S: Stream<Item = Result<Message, E>> + Sink<Message> + Unpin,
{
    async fn send_subscription(&mut self, text: String) -> Result<(), ()> {
        // The error is discarded rather than reported: the endpoint this socket was built from
        // carries the credential, and a transport error is free to quote the request it failed on.
        self.0
            .send(Message::Text(text.into()))
            .await
            .map_err(|_| ())
    }

    async fn poll_within(&mut self, within: Duration) -> WirePoll {
        match tokio::time::timeout(within, self.0.next()).await {
            Err(_) => WirePoll::Quiet,
            Ok(None) => WirePoll::Closed,
            Ok(Some(Err(_))) => WirePoll::Failed,
            Ok(Some(Ok(message))) => match message {
                Message::Text(text) => WirePoll::Frame(Bytes::from(text.as_bytes().to_vec())),
                Message::Binary(binary) => WirePoll::Frame(Bytes::from(binary.to_vec())),
                Message::Close(_) => WirePoll::Closed,
                Message::Ping(_) | Message::Pong(_) => WirePoll::Alive,
                Message::Frame(_) => WirePoll::Quiet,
            },
        }
    }
}

/// Run-wide tape state: the frames captured so far, the total order they arrived in across every
/// connection, and the sink that makes them durable. Sessions share one of these, so the frame and
/// byte budgets span the whole chained run and the sequence never restarts.
struct Tape<'a> {
    process_start: Instant,
    pending: Vec<Captured>,
    sequence: u64,
    frames: usize,
    bytes: usize,
    batches: usize,
    commit: &'a mut dyn FnMut(Vec<Captured>, usize) -> Result<(), Box<dyn Error>>,
}

impl<'a> Tape<'a> {
    fn new(
        process_start: Instant,
        commit: &'a mut dyn FnMut(Vec<Captured>, usize) -> Result<(), Box<dyn Error>>,
    ) -> Self {
        Self {
            process_start,
            pending: Vec::new(),
            sequence: 0,
            frames: 0,
            bytes: 0,
            batches: 0,
            commit,
        }
    }

    fn push(&mut self, frame: RawSourceFrame) -> Result<(), Box<dyn Error>> {
        if frame.direction == FrameDirection::Inbound {
            self.frames += 1;
            self.bytes += frame.body.len();
        }
        self.pending.push(Captured {
            frame,
            mono_ns: u64::try_from(self.process_start.elapsed().as_nanos())?,
        });
        self.sequence += 1;
        if self.pending.len() >= MAX_OBSERVATIONS_PER_BATCH {
            self.flush()?;
        }
        Ok(())
    }

    fn flush(&mut self) -> Result<(), Box<dyn Error>> {
        if self.pending.is_empty() {
            return Ok(());
        }
        (self.commit)(std::mem::take(&mut self.pending), self.batches)?;
        self.batches += 1;
        Ok(())
    }
}

/// The bounds one connection is judged against.
#[derive(Clone, Copy, Debug)]
struct SessionLimits {
    /// Monotonic instant the planned window ends, taken at process start.
    deadline: Instant,
    /// The same instant on the wall clock, so the two can be compared against each other.
    planned_end_millis: i64,
    inactivity: Duration,
    /// Run-wide, not per connection.
    max_frames: usize,
    max_bytes: usize,
}

/// What one connection did and what it can vouch for.
#[derive(Clone, Copy, Debug)]
struct SessionOutcome {
    epoch: u64,
    handshake_status: u16,
    opened_at_millis: i64,
    closed_at_millis: i64,
    /// First proof the provider was speaking on this socket. Coverage starts here, not at connect:
    /// the handshake and the subscription round trip observed nothing.
    first_liveness_millis: Option<i64>,
    last_liveness_millis: Option<i64>,
    last_frame_millis: Option<i64>,
    inbound_frames: usize,
    inbound_bytes: usize,
    transport_pings: usize,
    end: SessionEnd,
}

impl SessionOutcome {
    /// The interval this connection can honestly vouch for, as `(lower, upper)` wall milliseconds.
    ///
    /// A connection that stopped because the recorder told it to was reading a healthy socket right
    /// up to that instant, so it vouches through the stop. A connection that ended on a FAULT
    /// cannot vouch for anything after its last proof of liveness: between that proof and the close
    /// the socket may already have been dead, and a half-open socket is indistinguishable from a
    /// quiet market. A refused subscription vouches for nothing at all — it was never subscribed —
    /// so it claims a zero-width window, which is the shape of a claim that says nothing.
    fn claimed(&self, planned_end_millis: i64) -> (i64, i64) {
        // A connection the provider never said a word on claims nothing, however it ended — a
        // socket that opened as the planned end arrived has proved no coverage by outliving it.
        let Some(lower) = self.first_liveness_millis else {
            return (self.opened_at_millis, self.opened_at_millis);
        };
        let upper = match self.end {
            SessionEnd::PlannedWindowReached => planned_end_millis,
            SessionEnd::FrameBudget | SessionEnd::ByteBudget => self.closed_at_millis,
            SessionEnd::SubscriptionRefused => lower,
            _ => self.last_liveness_millis.unwrap_or(lower),
        };
        (lower, upper.max(lower))
    }
}

/// Retain the exact bytes of the ask this connection made, under this connection's own epoch, so
/// the catalog states which subjects each socket claimed coverage of without any later reader
/// taking that on trust from a filename.
fn retain_subscription(
    tape: &mut Tape<'_>,
    subscription: &[u8],
    epoch: u64,
    sent_at: i64,
) -> Result<(), Box<dyn Error>> {
    tape.push(RawSourceFrame {
        contract_version: ADAPTER_CONTRACT_VERSION.to_owned(),
        source: SourceId::PumpPortalWebSocket,
        transport: Transport::WebSocket,
        stream_class: StreamClass::LeasedHot,
        direction: FrameDirection::OutboundControl,
        content_type: ContentType::Json,
        received_at: UnixMillis(sent_at),
        connection_epoch: epoch,
        sequence: tape.sequence,
        http_status: None,
        safe_headers: Vec::new(),
        body: Bytes::from(subscription.to_vec()),
    })
}

/// Hold one connection for as long as it is useful, retaining every frame it delivers.
///
/// Every budget is re-checked at the top of each iteration against BOTH clocks, because a
/// monotonic deadline silently stretches across a host suspend and a wall clock alone cannot tell
/// a suspend from a slow loop.
async fn run_session<W: Wire>(
    wire: &mut W,
    tape: &mut Tape<'_>,
    subscription: &[u8],
    epoch: u64,
    handshake_status: u16,
    limits: SessionLimits,
) -> Result<SessionOutcome, Box<dyn Error>> {
    let opened_at_millis = now_millis()?;
    let session_mono = Instant::now();
    let mut outcome = SessionOutcome {
        epoch,
        handshake_status,
        opened_at_millis,
        closed_at_millis: opened_at_millis,
        first_liveness_millis: None,
        last_liveness_millis: None,
        last_frame_millis: None,
        inbound_frames: 0,
        inbound_bytes: 0,
        transport_pings: 0,
        end: SessionEnd::TransportError,
    };

    // The ask is retained only after the send succeeded; an unsent ask was never made.
    if wire
        .send_subscription(String::from_utf8(subscription.to_vec())?)
        .await
        .is_err()
    {
        outcome.closed_at_millis = now_millis()?;
        return Ok(outcome);
    }
    let sent_at = now_millis()?;
    retain_subscription(tape, subscription, epoch, sent_at)?;

    let inactivity_millis = i64::try_from(limits.inactivity.as_millis())?;
    let end = loop {
        if tape.frames >= limits.max_frames {
            break SessionEnd::FrameBudget;
        }
        if tape.bytes >= limits.max_bytes {
            break SessionEnd::ByteBudget;
        }
        let now = now_millis()?;
        let wall_elapsed = now - opened_at_millis;
        let mono_elapsed = i64::try_from(session_mono.elapsed().as_millis())?;
        if wall_elapsed - mono_elapsed > SUSPEND_SKEW_MILLIS {
            break SessionEnd::HostSuspended;
        }
        if now >= limits.planned_end_millis {
            break SessionEnd::PlannedWindowReached;
        }
        if now - outcome.last_liveness_millis.unwrap_or(sent_at) > inactivity_millis {
            break SessionEnd::InactivityCeiling;
        }
        let remaining = limits
            .deadline
            .saturating_duration_since(Instant::now())
            .min(limits.inactivity);
        if remaining.is_zero() {
            break SessionEnd::PlannedWindowReached;
        }
        let body = match wire.poll_within(remaining).await {
            WirePoll::Quiet => continue,
            WirePoll::Closed => break SessionEnd::ProviderClosedSocket,
            WirePoll::Failed => break SessionEnd::TransportError,
            WirePoll::Alive => {
                outcome.transport_pings += 1;
                let at = now_millis()?;
                outcome.first_liveness_millis.get_or_insert(at);
                outcome.last_liveness_millis = Some(at);
                continue;
            }
            WirePoll::Frame(body) => body,
        };
        let received = now_millis()?;
        outcome.first_liveness_millis.get_or_insert(received);
        outcome.last_liveness_millis = Some(received);
        outcome.last_frame_millis = Some(received);
        outcome.inbound_frames += 1;
        outcome.inbound_bytes += body.len();
        let refused = classify_pumpportal_frame(&body).kind
            == PumpPortalFrameKind::AuthenticationOrFundingRejected;
        tape.push(RawSourceFrame::inbound_websocket(
            SourceId::PumpPortalWebSocket,
            StreamClass::LeasedHot,
            UnixMillis(received),
            epoch,
            tape.sequence,
            ContentType::Json,
            body,
        ))?;
        // The refusal frame is retained first, then the connection ends: waiting out the
        // inactivity ceiling after this frame would let the coverage claim swallow a window the
        // provider had already said it would never serve.
        if refused {
            break SessionEnd::SubscriptionRefused;
        }
    };
    outcome.closed_at_millis = now_millis()?;
    outcome.end = end;
    Ok(outcome)
}

/// One reconnect attempt as the receipt states it: which consecutive try it was, what it was
/// answering, how long it waited first, and whether a socket came back.
fn reconnect_record(
    attempt: u32,
    after: &str,
    backoff: Duration,
    outcome: &str,
    handshake_status: Option<u16>,
    at_millis: i64,
) -> Value {
    json!({
        "attempt": attempt,
        "afterEndReason": after,
        "backoffMs": u64::try_from(backoff.as_millis()).unwrap_or(u64::MAX),
        "outcome": outcome,
        "handshakeStatus": handshake_status,
        "atUnixMs": at_millis,
    })
}

/// One interval of the planned window this run could not vouch for, and what made it so.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Unobserved {
    lower_millis: i64,
    upper_millis: i64,
    cause: &'static str,
    /// Index of the session whose coverage window this gap hangs from.
    anchor: usize,
}

/// Everything in the planned window that no connection could vouch for, in order.
///
/// The walk is a complement: it carries a cursor through the sessions' claims and writes down every
/// interval the cursor had to jump. Each jump is split at the instant the connection that opened it
/// actually closed, because those two halves have different causes — before it the socket was
/// faulting or silent while still nominally ours, after it this process was between sockets.
fn unobserved_spans(
    sessions: &[SessionOutcome],
    run_opened_at_millis: i64,
    planned_end_millis: i64,
    stop: RunStop,
) -> Vec<Unobserved> {
    let mut spans: Vec<Unobserved> = Vec::new();
    let mut cursor = run_opened_at_millis;
    let mut previous: Option<(usize, &SessionOutcome)> = None;
    for (index, session) in sessions.iter().enumerate() {
        let (lower, upper) = session.claimed(planned_end_millis);
        let (anchor, close, fault) = match previous {
            None => (index, None, CAUSE_AWAITING_FIRST_LIVENESS),
            Some((earlier, session)) => (
                earlier,
                Some(session.closed_at_millis),
                session.end.as_str(),
            ),
        };
        split_unobserved(
            &mut spans,
            cursor,
            lower,
            close,
            fault,
            CAUSE_BACKOFF_WAIT,
            anchor,
        );
        cursor = cursor.max(upper);
        previous = Some((index, session));
    }
    if let Some((index, session)) = previous {
        split_unobserved(
            &mut spans,
            cursor,
            planned_end_millis,
            Some(session.closed_at_millis),
            session.end.as_str(),
            stop.trailing_cause(),
            index,
        );
    }
    merge_adjacent(spans)
}

/// Write one unobserved interval down, split at `close` into the half the connection was still
/// nominally ours and the half spent between sockets.
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
    let mut push = |lower, upper, cause| {
        spans.push(Unobserved {
            lower_millis: lower,
            upper_millis: upper,
            cause,
            anchor,
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

/// Fold touching intervals that name the same cause into one, so the receipt does not report the
/// same unbroken silence twice under one name.
fn merge_adjacent(spans: Vec<Unobserved>) -> Vec<Unobserved> {
    let mut merged: Vec<Unobserved> = Vec::with_capacity(spans.len());
    for span in spans {
        match merged.last_mut() {
            Some(last) if last.upper_millis == span.lower_millis && last.cause == span.cause => {
                last.upper_millis = span.upper_millis;
            }
            _ => merged.push(span),
        }
    }
    merged
}

#[allow(clippy::too_many_lines)] // One bounded connect/record/retain/gap walk, kept in one place.
async fn record(
    root: &Path,
    mints: &str,
    budget: Budget,
    policy: ReconnectPolicy,
    key_file: Option<&Path>,
) -> Result<String, Box<dyn Error>> {
    let keys: Vec<String> = mints
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect();
    if keys.is_empty() {
        return Err("record needs at least one mint".into());
    }
    let process_start = Instant::now();
    let opened_at_millis = now_millis()?;
    let namespace = format!("tape-{opened_at_millis}");
    let clock_id = format!("mono:coin-tape:{}:{opened_at_millis}", std::process::id());
    let planned_end_millis = opened_at_millis
        .checked_add(i64::try_from(budget.seconds)?.saturating_mul(1_000))
        .ok_or("planned window end overflows the wall clock")?;

    // The credential is read from a 0600 file, never from a flag, and never rendered. It is
    // attached only when explicitly named, because PumpPortal documents this key as carrying
    // wallet-signing authority; a keyless connection is the default for that reason. It is read
    // ONCE and held for the run: a reconnect re-presents what this run was launched with rather
    // than picking up whatever landed in the file since.
    let endpoint = match key_file {
        None => ENDPOINT.to_owned(),
        Some(path) => {
            let key = fs::read_to_string(path)?.trim().to_owned();
            if key.is_empty() {
                return Err("the named credential file is empty".into());
            }
            format!("{ENDPOINT}?api-key={key}")
        }
    };
    // The FIRST connect is not retried. Reconnect is for a provider that accepted this run and
    // then hiccuped; a run that never got a socket at all has nothing to restate.
    let (mut socket, response) = match tokio_tungstenite::connect_async(endpoint.clone()).await {
        Ok(value) => value,
        // The endpoint carries the credential as a query parameter and a transport error is free
        // to quote the request it failed on, so a keyed run states the failure without its words.
        Err(error) if key_file.is_none() => {
            return Err(format!("the initial connect failed: {error}").into());
        }
        Err(_) => return Err("the initial connect failed while a credential was attached".into()),
    };
    let mut handshake_status = response.status().as_u16();

    let mut store = SqliteStore::open(catalog_config(root)?, StoreMode::SingleWriter)?;
    store.migrate(now_utc()?)?;

    // A coverage subject and a request fingerprint are 512-byte wire strings, and a subscription
    // to sixteen mints does not fit in one. The subject therefore names the key SET by digest and
    // by count; the exact key list is retained verbatim as the outbound subscription frame, so
    // nothing is lost and no later reader has to take the membership from a file name.
    let key_digest = Sha256Digest::of_bytes(keys.join(",").as_bytes()).to_string();
    let subject = format!("keys={}:{key_digest}", keys.len());
    let fingerprint_material = format!("pumpportal:{FEED_LOCATOR}:{subject}");
    let subscribe = json!({"method": "subscribeTokenTrade", "keys": keys});
    let subscribe_bytes = serde_json::to_vec(&subscribe)?;

    let deadline = process_start + Duration::from_secs(budget.seconds);
    let limits = SessionLimits {
        deadline,
        planned_end_millis,
        inactivity: Duration::from_secs(budget.inactivity_seconds),
        max_frames: budget.max_frames,
        max_bytes: budget.max_bytes,
    };
    let mut sessions: Vec<SessionOutcome> = Vec::new();
    let mut reconnects: Vec<Value> = Vec::new();
    let (stop, total_frames, total_bytes, total_batches) = {
        let mut commit = |captured: Vec<Captured>, chunk: usize| -> Result<(), Box<dyn Error>> {
            commit_frames(
                &mut store,
                captured,
                &namespace,
                &clock_id,
                &fingerprint_material,
                chunk,
                process_start,
            )?;
            Ok(())
        };
        let mut tape = Tape::new(process_start, &mut commit);
        let mut consecutive_failures = 0_u32;
        let stop = 'run: loop {
            let epoch = u64::try_from(sessions.len())? + 1;
            let mut wire = SocketWire(socket);
            let outcome = run_session(
                &mut wire,
                &mut tape,
                &subscribe_bytes,
                epoch,
                handshake_status,
                limits,
            )
            .await?;
            // The dying socket is closed here rather than at the end of the run: a reconnect
            // should not hold a second subscription open beside the one it is replacing.
            drop(wire);
            eprintln!(
                "coin_tape_live: session {epoch} ended after {} inbound frames: {}",
                outcome.inbound_frames,
                outcome.end.as_str()
            );
            // A connection that actually delivered frames is proof the provider is serving this
            // run again, so the consecutive-failure count starts over from it.
            if outcome.inbound_frames > 0 {
                consecutive_failures = 0;
            }
            let mut end = outcome.end;
            let first_session = sessions.is_empty();
            sessions.push(outcome);
            loop {
                let remaining = deadline.saturating_duration_since(Instant::now());
                let (attempt, backoff) =
                    match next_step(policy, end, first_session, consecutive_failures, remaining) {
                        Next::Stop(stop) => break 'run stop,
                        Next::Reconnect { attempt, backoff } => (attempt, backoff),
                    };
                consecutive_failures = attempt;
                eprintln!(
                    "coin_tape_live: reconnect attempt {attempt}/{} in {:.1}s",
                    policy.max_attempts,
                    backoff.as_secs_f64()
                );
                tokio::time::sleep(backoff).await;
                if Instant::now() >= deadline {
                    break 'run RunStop::WallClockBudget;
                }
                // The provider's own words are withheld here for the same reason as above: the
                // endpoint this attempt was built from carries the credential.
                let after = end.as_str();
                let established = tokio_tungstenite::connect_async(endpoint.clone())
                    .await
                    .ok();
                if let Some((next_socket, response)) = established {
                    socket = next_socket;
                    handshake_status = response.status().as_u16();
                    let at = now_millis()?;
                    reconnects.push(reconnect_record(
                        attempt,
                        after,
                        backoff,
                        "connected",
                        Some(handshake_status),
                        at,
                    ));
                    break;
                }
                let at = now_millis()?;
                reconnects.push(reconnect_record(
                    attempt,
                    after,
                    backoff,
                    "connect_failed",
                    None,
                    at,
                ));
                end = SessionEnd::ConnectFailed;
            }
        };
        // Say why before doing anything that could fail, so a later refusal cannot hide the stop.
        eprintln!(
            "coin_tape_live: stopped after {} sessions and {} inbound frames: {}",
            sessions.len(),
            tape.frames,
            stop.as_str()
        );
        tape.flush()?;
        (stop, tape.frames, tape.bytes, tape.batches)
    };
    let closed_at_millis = now_millis()?;
    let spans = unobserved_spans(&sessions, opened_at_millis, planned_end_millis, stop);
    let (coverage_ids, gap_ids) = commit_coverage(
        &mut store,
        &namespace,
        &clock_id,
        &subject,
        planned_end_millis,
        &sessions,
        &spans,
        process_start,
    )?;
    drop(store);

    // Restart read-back: a fresh handle, a full integrity check, and the retained bytes counted
    // out of the catalog rather than out of the buffers that were just dropped.
    let reopened = SqliteStore::open(catalog_config(root)?, StoreMode::ReadOnly)?;
    let verification = reopened.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" || verification.foreign_key_defects != 0 {
        return Err("reopened catalog failed verification".into());
    }
    let stored = read_tape(&reopened)?;
    let stored_from_this_run: Vec<&DurableSourceObservation> = stored
        .iter()
        .filter(|observation| {
            observation
                .acquisition_id
                .as_str()
                .contains(&format!(":{namespace}:"))
        })
        .collect();
    let readback_bytes: usize = stored_from_this_run
        .iter()
        .map(|observation| observation.payload.len())
        .sum();
    drop(reopened);

    let claimed_millis: i64 = sessions
        .iter()
        .map(|session| {
            let (lower, upper) = session.claimed(planned_end_millis);
            upper - lower
        })
        .sum();
    let unobserved_millis: i64 = spans
        .iter()
        .map(|span| span.upper_millis - span.lower_millis)
        .sum();
    Ok(serde_json::to_string_pretty(&json!({
        "contract": "joshi.coin_tape.record_receipt.v2",
        "endpointHost": "pumpportal.fun",
        "credentialAttached": key_file.is_some(),
        "namespace": namespace,
        "subjects": keys,
        "budget": {
            "wallClockSeconds": budget.seconds,
            "maxInboundFrames": budget.max_frames,
            "maxInboundBytes": budget.max_bytes,
            "inactivityCeilingSeconds": budget.inactivity_seconds,
        },
        "reconnect": {
            "maxConsecutiveAttempts": policy.max_attempts,
            "initialBackoffSeconds": policy.initial_backoff.as_secs_f64(),
            "maxBackoffSeconds": policy.max_backoff.as_secs_f64(),
            "attempts": reconnects,
        },
        "openedAtUnixMs": opened_at_millis,
        "plannedEndUnixMs": planned_end_millis,
        "closedAtUnixMs": closed_at_millis,
        "stopReason": stop.as_str(),
        "plannedWindowCompleted": stop.planned_window_completed(),
        "plannedWindowCompletedMeans": "the wall clock the caller named ran out; it is NOT a claim \
                                        that the window was fully observed, which is what \
                                        totals.unobservedMillis states",
        "sessions": sessions.iter().zip(&coverage_ids).map(|(session, coverage_id)| {
            let (lower, upper) = session.claimed(planned_end_millis);
            json!({
                "connectionEpoch": session.epoch,
                "handshakeStatus": session.handshake_status,
                "openedAtUnixMs": session.opened_at_millis,
                "closedAtUnixMs": session.closed_at_millis,
                "firstLivenessAtUnixMs": session.first_liveness_millis,
                "lastLivenessAtUnixMs": session.last_liveness_millis,
                "lastFrameAtUnixMs": session.last_frame_millis,
                "inboundFrames": session.inbound_frames,
                "inboundBytes": session.inbound_bytes,
                "transportPings": session.transport_pings,
                "endReason": session.end.as_str(),
                "coverageId": coverage_id,
                "claimedWindowUnixMs": [lower, upper],
            })
        }).collect::<Vec<_>>(),
        "gaps": spans.iter().zip(&gap_ids).map(|(span, gap_id)| json!({
            "gapId": gap_id,
            "reason": span.cause,
            "lowerUnixMs": span.lower_millis,
            "upperUnixMs": span.upper_millis,
            "millis": span.upper_millis - span.lower_millis,
            "recoverable": false,
        })).collect::<Vec<_>>(),
        "totals": {
            "sessions": sessions.len(),
            "inboundFrames": total_frames,
            "inboundBytes": total_bytes,
            "observationBatches": total_batches,
            "transportPings": sessions.iter().map(|session| session.transport_pings).sum::<usize>(),
            "plannedMillis": planned_end_millis - opened_at_millis,
            "claimedMillis": claimed_millis,
            "unobservedMillis": unobserved_millis,
        },
        "restartReadback": {
            "integrity": verification.integrity,
            "observationsFromThisRun": stored_from_this_run.len(),
            "retainedPayloadBytes": readback_bytes,
        },
    }))?)
}

fn commit_frames(
    store: &mut SqliteStore,
    captured: Vec<Captured>,
    namespace: &str,
    clock_id: &str,
    fingerprint_material: &str,
    chunk_index: usize,
    process_start: Instant,
) -> Result<PublicStoreReceiptV1, Box<dyn Error>> {
    let persisted_at = now_utc()?;
    let mut frames = Vec::with_capacity(captured.len());
    for item in captured {
        let received_at = utc_from_millis(item.frame.received_at.0)?;
        let outbound = item.frame.direction == FrameDirection::OutboundControl;
        let variant = if outbound {
            "pumpportal_subscription_request".to_owned()
        } else {
            format!("pumpportal_{}", frame_kind(&item.frame.body))
        };
        frames.push(SourceFrameInput {
            frame: item.frame,
            context: EvidenceContext {
                occurrence_namespace: namespace.to_owned(),
                redacted_request_fingerprint_material: fingerprint_material.to_owned(),
                parent_acquisition_id: None,
                locator: LogicalSourceLocator::PumpPortalWebSocket { feed: FEED_LOCATOR },
                source_variant: OpenVariant::known(variant)?,
                source_cursor: None,
                source_events: Vec::new(),
                // MEASURED: a PumpPortal trade frame carries no timestamp, no blockTime and no
                // slot. The only clock any frame of this feed has is our own receive instant, so
                // no provider event time is asserted and the absence is written down as a reason
                // rather than backfilled with the receive clock.
                provider_event_time: ProviderEventTime::Missing {
                    reason: "pumpportal data frame states no provider event clock or slot"
                        .to_owned(),
                },
                chain_slot: None,
                transaction_index: None,
                instruction_path: Vec::new(),
                log_index: None,
                finality: None,
                acquisition_started_at: received_at,
                requested_at: outbound.then_some(received_at),
                monotonic_clock_id: clock_id.to_owned(),
                acquisition_started_monotonic_ns: item.mono_ns,
                received_monotonic_ns: item.mono_ns,
                persisted_at,
            },
        });
    }
    let batch = source_frames(
        frames,
        Vec::new(),
        Vec::new(),
        StableString::new(format!("{namespace}-frames-{chunk_index:05}"))?,
        persisted_at,
        StableString::new(clock_id)?,
        u64::try_from(process_start.elapsed().as_nanos())?,
    )?;
    Ok(batch.commit(store)?)
}

fn frame_kind(body: &[u8]) -> &'static str {
    match classify_pumpportal_frame(body).kind {
        PumpPortalFrameKind::NewToken => "new_token",
        PumpPortalFrameKind::Migration => "migration",
        PumpPortalFrameKind::Trade => "trade",
        PumpPortalFrameKind::Acknowledgement => "acknowledgement",
        PumpPortalFrameKind::AuthenticationOrFundingRejected => "authentication_rejected",
        PumpPortalFrameKind::ProviderControl => "provider_control",
        PumpPortalFrameKind::UnknownEvent => "unknown_event",
        PumpPortalFrameKind::Malformed => "malformed",
    }
}

/// Retain what each connection claims and every interval of the planned window nothing claimed.
///
/// Each connection gets its OWN coverage window, so a later reader who consults the windows alone
/// can never be told this run observed a stretch it did not; the holes between them are separate
/// gap records, each naming its cause. The windows go in one batch EACH because the catalog keys a
/// window on `(source, scope, opening commit)` and every session here shares one scope: two windows
/// in one batch would collide. The gaps go in a final batch, after every window they reference
/// exists, under the severity that says a scope stopped.
#[allow(clippy::too_many_arguments)] // Every boundary of the claim is named explicitly.
fn commit_coverage(
    store: &mut SqliteStore,
    namespace: &str,
    clock_id: &str,
    subject: &str,
    planned_end_millis: i64,
    sessions: &[SessionOutcome],
    spans: &[Unobserved],
    process_start: Instant,
) -> Result<(Vec<String>, Vec<String>), Box<dyn Error>> {
    let persisted_at = now_utc()?;
    let scope = CoverageScope {
        source_id: DomainSourceId::new(SOURCE_ID)?,
        family: OpenVariant::known(COVERAGE_FAMILY)?,
        subject: Some(StableString::new(subject)?),
    };
    let mut mono = u64::try_from(process_start.elapsed().as_nanos())?;
    let mut coverage_ids = Vec::with_capacity(sessions.len());
    for session in sessions {
        let (lower, upper) = session.claimed(planned_end_millis);
        let coverage_id = CoverageId::new(format!("coverage-{namespace}-s{:03}", session.epoch))?;
        coverage_ids.push(coverage_id.as_str().to_owned());
        let window = CoverageWindow {
            coverage_id,
            scope: scope.clone(),
            lower: Boundary::Wall {
                value: utc_from_millis(lower)?,
            },
            // A zero-width upper is not an accident: a connection that was refused, or that never
            // heard a word, claims exactly nothing and says so in the shape of its own window.
            upper: Some(Boundary::Wall {
                value: utc_from_millis(upper)?,
            }),
            state: OpenVariant::known("closed")?,
            available_at: persisted_at,
        };
        mono = mono.saturating_add(1);
        commit_drafts(
            store,
            format!("{namespace}-coverage-s{:03}", session.epoch),
            vec![EvidenceDraft::CoverageWindow(window)],
            SEVERITY_DEGRADED,
            clock_id,
            persisted_at,
            mono,
        )?;
    }

    let mut gap_ids = Vec::with_capacity(spans.len());
    let mut gaps = Vec::with_capacity(spans.len());
    for (index, span) in spans.iter().enumerate() {
        let anchor = coverage_ids
            .get(span.anchor)
            .ok_or("an unobserved span named a session that does not exist")?;
        let gap_id = format!("gap-{namespace}-{index:03}-{}", span.cause);
        gap_ids.push(gap_id.clone());
        gaps.push(EvidenceDraft::CoverageGap(CoverageGap {
            gap_id: CoverageId::new(gap_id)?,
            coverage_id: CoverageId::new(anchor.clone())?,
            scope: scope.clone(),
            lower: Boundary::Wall {
                value: utc_from_millis(span.lower_millis)?,
            },
            upper: Some(Boundary::Wall {
                value: utc_from_millis(span.upper_millis)?,
            }),
            // This feed exposes no replay cursor and no historical backfill, so the interval below
            // is not merely late: it is unrecoverable, and no later run can ever close it.
            reason: OpenVariant::known(span.cause)?,
            detected_at: persisted_at,
        }));
    }
    if !gaps.is_empty() {
        mono = mono.saturating_add(1);
        commit_drafts(
            store,
            format!("{namespace}-coverage-gaps"),
            gaps,
            SEVERITY_SCOPE_STOPPED,
            clock_id,
            persisted_at,
            mono,
        )?;
    }
    Ok((coverage_ids, gap_ids))
}

/// One coverage batch through the ordinary source-admission path.
fn commit_drafts(
    store: &mut SqliteStore,
    batch_id: String,
    drafts: Vec<EvidenceDraft>,
    severity: &str,
    clock_id: &str,
    persisted_at: UtcTimestamp,
    mono: u64,
) -> Result<(), Box<dyn Error>> {
    let batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(batch_id)?,
        drafts,
        source_events: Vec::new(),
        cursor_advances: Vec::new(),
        registrations: vec![tape_source_registration()?],
        policy: AdmissionPolicy {
            retention_class: StableString::new("public_source")?,
            content_encoding: None,
            force_external: false,
            gap_severity: StableString::new(severity)?,
        },
        committed_at: persisted_at,
        writer_clock_id: StableString::new(clock_id)?,
        committed_mono_ns: mono,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })?;
    batch.commit(store)?;
    Ok(())
}

/// The exact registration `joshi_admission::source_frames` emits for a `PumpPortal` frame.
///
/// A coverage claim can outlive its evidence — a window that received nothing still owes an exact
/// gap — so the coverage batch must be able to register the source on its own.
fn tape_source_registration() -> Result<SourceRegistration, Box<dyn Error>> {
    let source_id = DomainSourceId::new(SOURCE_ID)?;
    let collector_build = env!("CARGO_PKG_VERSION");
    let material = format!(
        "joshi.source.registration.v1\0{}\0{SOURCE_NAMESPACE}\0{ADAPTER_CONTRACT_VERSION}\0{collector_build}",
        source_id.as_str()
    );
    Ok(SourceRegistration {
        source_id,
        namespace: StableString::new(SOURCE_NAMESPACE)?,
        contract_version: StableString::new(ADAPTER_CONTRACT_VERSION)?,
        collector_build: StableString::new(collector_build)?,
        configuration_digest: ValueDigest::new(
            Sha256Digest::of_bytes(material.as_bytes()).to_string(),
        )?,
    })
}

fn read_tape(store: &SqliteStore) -> Result<Vec<DurableSourceObservation>, Box<dyn Error>> {
    let source_id = DomainSourceId::new(SOURCE_ID)?;
    let Some(stored) = store.source_observations_as_known(&source_id, None, READBACK_LIMIT)? else {
        return Ok(Vec::new());
    };
    if stored.truncated {
        return Err("the catalog holds more tape frames than this read-back asked for".into());
    }
    Ok(stored.observations)
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

fn now_utc() -> Result<UtcTimestamp, Box<dyn Error>> {
    let value = OffsetDateTime::now_utc();
    let nanosecond = value.nanosecond();
    Ok(UtcTimestamp::new(
        value.replace_nanosecond(nanosecond - nanosecond % 1_000)?,
    )?)
}

fn now_millis() -> Result<i64, Box<dyn Error>> {
    Ok(i64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn utc_from_millis(millis: i64) -> Result<UtcTimestamp, Box<dyn Error>> {
    Ok(UtcTimestamp::new(
        OffsetDateTime::from_unix_timestamp_nanos(i128::from(millis) * 1_000_000)?,
    )?)
}

// ---------------------------------------------------------------------------------------------
// Analysis. Everything below reads ONLY what came back out of the reopened catalog.
// ---------------------------------------------------------------------------------------------

/// One retained inbound frame, in the total order the socket delivered it.
struct TapeFrame {
    sequence: u64,
    received_at_millis: i64,
    body: Vec<u8>,
    value: Option<Value>,
}

/// One trade event, as the frame itself states it.
struct TradeEvent {
    sequence: u64,
    received_at_millis: i64,
    signature: String,
    label: String,
    sol_amount: f64,
    token_amount: f64,
    /// Post-trade SOL-side reserves, from whichever pair the frame states.
    virtual_sol: f64,
    /// Post-trade token-side reserves, from the same pair.
    virtual_tokens: f64,
    /// Which reserve pair the frame stated. MEASURED 2026-08-22: a `pool:"pump"` frame carries
    /// `vSolInBondingCurve`/`vTokensInBondingCurve`; a `pool:"pump-amm"` frame carries
    /// `solInPool`/`tokensInPool` instead. Both are post-trade constant-product reserves.
    reserve_basis: &'static str,
    pool: String,
}

impl TradeEvent {
    /// SOL per token implied by the post-trade reserve pair the frame states, which is exact
    /// arithmetic on two numbers the provider supplied rather than a price it asserted.
    fn price(&self) -> f64 {
        self.virtual_sol / self.virtual_tokens
    }

    /// Direction derived from the frame ALONE, with no neighbour and no provider label.
    ///
    /// Both the pump bonding curve and the pump-swap AMM are constant products. A frame states
    /// the post-trade reserves and the two amounts that moved, so the pre-trade reserves are
    /// recoverable under each hypothesis and only the true one comes close to reproducing the
    /// post-trade product. `None` means neither hypothesis fitted well enough to name, which is
    /// reported as an unknown rather than guessed.
    fn derived_direction(&self) -> (Option<&'static str>, f64) {
        let after = self.virtual_sol * self.virtual_tokens;
        if after <= 0.0 {
            return (None, f64::INFINITY);
        }
        let buy_product =
            (self.virtual_sol - self.sol_amount) * (self.virtual_tokens + self.token_amount);
        let sell_product =
            (self.virtual_sol + self.sol_amount) * (self.virtual_tokens - self.token_amount);
        let buy_error = ((buy_product - after) / after).abs();
        let sell_error = ((sell_product - after) / after).abs();
        let (name, error, other) = if buy_error <= sell_error {
            ("buy", buy_error, sell_error)
        } else {
            ("sell", sell_error, buy_error)
        };
        // The venue charges a fee on the SOL leg, so neither hypothesis reproduces the product
        // exactly, and the gap between the hypotheses is of order the trade size relative to the
        // reserves. MEASURED 2026-08-22: in a deep pump-amm pool that gap collapses — the two
        // errors sat within 3x of each other on 799 of 800 live frames — so a name is only given
        // when the losing hypothesis misses by at least three times the winning one. Anything
        // tighter is a coin flip wearing a conclusion, and is reported as undecidable instead.
        if error > 0.01 || other < error * 3.0 {
            (None, error)
        } else {
            (Some(name), error)
        }
    }
}

#[allow(clippy::too_many_lines)] // One report; splitting it would scatter the measured semantics.
fn analyse(root: &Path, bucket_seconds: u64, trades: &[String]) -> Result<String, Box<dyn Error>> {
    let store = SqliteStore::open(catalog_config(root)?, StoreMode::ReadOnly)?;
    let verification = store.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" {
        return Err("reopened catalog failed verification".into());
    }
    let stored = read_tape(&store)?;
    if stored.is_empty() {
        return Err("the catalog holds no tape frames; an empty read is not an empty tape".into());
    }

    let mut subjects: BTreeSet<String> = BTreeSet::new();
    let mut inbound: Vec<TapeFrame> = Vec::new();
    let mut outbound = 0_usize;
    for observation in &stored {
        let envelope: RetainedFrameEnvelope = serde_json::from_slice(&observation.payload)?;
        let sequence = trailing_sequence(observation.acquisition_id.as_str())?;
        if envelope.direction == FrameDirection::OutboundControl {
            outbound += 1;
            if let Ok(value) = serde_json::from_slice::<Value>(&envelope.body) {
                for key in value["keys"].as_array().into_iter().flatten() {
                    if let Some(key) = key.as_str() {
                        subjects.insert(key.to_owned());
                    }
                }
            }
            continue;
        }
        let value = serde_json::from_slice::<Value>(&envelope.body).ok();
        inbound.push(TapeFrame {
            sequence,
            received_at_millis: millis_of(observation.received_at),
            body: envelope.body,
            value,
        });
    }
    inbound.sort_by_key(|frame| frame.sequence);

    // Frame anatomy, by kind, over exactly the bytes that were retained.
    let mut kind_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut kind_bytes: BTreeMap<String, usize> = BTreeMap::new();
    let mut trade_key_presence: BTreeMap<String, usize> = BTreeMap::new();
    let mut clock_key_presence: BTreeMap<String, usize> = BTreeMap::new();
    let mut per_mint: BTreeMap<String, Vec<TradeEvent>> = BTreeMap::new();
    let mut signatures: BTreeMap<String, usize> = BTreeMap::new();
    let mut trade_frames = 0_usize;
    for frame in &inbound {
        let kind = frame_kind(&frame.body).to_owned();
        *kind_counts.entry(kind.clone()).or_default() += 1;
        *kind_bytes.entry(kind.clone()).or_default() += frame.body.len();
        let Some(value) = frame.value.as_ref() else {
            continue;
        };
        for candidate in [
            "timestamp",
            "blockTime",
            "block_time",
            "eventTime",
            "time",
            "slot",
        ] {
            if value.get(candidate).is_some_and(|value| !value.is_null()) {
                *clock_key_presence.entry(candidate.to_owned()).or_default() += 1;
            }
        }
        if kind != "trade" {
            continue;
        }
        trade_frames += 1;
        for key in value.as_object().into_iter().flatten().map(|(key, _)| key) {
            *trade_key_presence.entry(key.clone()).or_default() += 1;
        }
        let (Some(mint), Some(signature)) = (
            value["mint"].as_str().map(ToOwned::to_owned),
            value["signature"].as_str().map(ToOwned::to_owned),
        ) else {
            continue;
        };
        *signatures.entry(signature.clone()).or_default() += 1;
        let (Some(label), Some(sol_amount), Some(token_amount)) = (
            value["txType"].as_str().map(ToOwned::to_owned),
            value["solAmount"].as_f64(),
            value["tokenAmount"].as_f64(),
        ) else {
            continue;
        };
        let reserves = value["vSolInBondingCurve"]
            .as_f64()
            .zip(value["vTokensInBondingCurve"].as_f64())
            .map(|(sol, tokens)| (sol, tokens, "bonding_curve"))
            .or_else(|| {
                value["solInPool"]
                    .as_f64()
                    .zip(value["tokensInPool"].as_f64())
                    .map(|(sol, tokens)| (sol, tokens, "amm_pool"))
            });
        let Some((virtual_sol, virtual_tokens, reserve_basis)) = reserves else {
            continue;
        };
        per_mint.entry(mint).or_default().push(TradeEvent {
            sequence: frame.sequence,
            received_at_millis: frame.received_at_millis,
            signature,
            label,
            sol_amount,
            token_amount,
            virtual_sol,
            virtual_tokens,
            reserve_basis,
            pool: value["pool"].as_str().unwrap_or("unstated").to_owned(),
        });
    }

    // Is the provider's `txType` label derivable from the frame it rides on?
    let mut label_agreements = 0_usize;
    let mut label_disagreements = 0_usize;
    let mut label_undecidable = 0_usize;
    let mut fit_errors: Vec<f64> = Vec::new();
    for event in per_mint.values().flatten() {
        let (derived, error) = event.derived_direction();
        match derived {
            None => label_undecidable += 1,
            Some(direction) if direction == event.label => {
                label_agreements += 1;
                fit_errors.push(error);
            }
            Some(_) => label_disagreements += 1,
        }
    }

    let window = inbound
        .first()
        .zip(inbound.last())
        .map(|(first, last)| (first.received_at_millis, last.received_at_millis));
    let observed_seconds = window
        .map(|(first, last)| wall_span_seconds(first, last))
        .unwrap_or_default();

    // Bind each retained swap-api page to a tape coin by signature intersection alone: a
    // signature is globally unique, so one shared signature proves which coin the page is about,
    // and a page sharing none stays unbound rather than being trusted from a file name.
    let pages = swap_api_pages(trades)?;
    let mut bound: BTreeMap<&str, Vec<usize>> = BTreeMap::new();
    let mut unbound_pages: Vec<Value> = Vec::new();
    for (index, page) in pages.iter().enumerate() {
        let page_txs: BTreeSet<&str> = page.rows.iter().map(|row| row.tx.as_str()).collect();
        let best = per_mint
            .iter()
            .map(|(mint, events)| {
                let overlap = events
                    .iter()
                    .filter(|event| page_txs.contains(event.signature.as_str()))
                    .count();
                (overlap, mint.as_str())
            })
            .max();
        match best {
            Some((overlap, mint)) if overlap > 0 => {
                bound.entry(mint).or_default().push(index);
            }
            _ => unbound_pages.push(json!({
                "path": page.path,
                "rows": page.rows.len(),
                "reason": "no signature shared with any tape coin; nothing to compare",
            })),
        }
    }

    let mut coins = Vec::new();
    for (mint, events) in &per_mint {
        let coin_pages: Vec<&SwapApiPage> = bound
            .get(mint.as_str())
            .map(|indexes| indexes.iter().map(|index| &pages[*index]).collect())
            .unwrap_or_default();
        coins.push(coin_report(mint, events, bucket_seconds, &coin_pages)?);
    }

    Ok(serde_json::to_string_pretty(&json!({
        "contract": "joshi.coin_tape.analysis.v1",
        "readFrom": "reopened durable catalog, read-only",
        "catalogIntegrity": verification.integrity,
        "retainedObservations": stored.len(),
        "outboundControlFrames": outbound,
        "inboundFrames": inbound.len(),
        "subscribedSubjects": subjects,
        "observedWindowUnixMs": window.map(|(first, last)| json!([first, last])),
        "observedSeconds": observed_seconds,
        "inboundFramesPerSecond": (observed_seconds > 0.0)
            .then(|| count_as_f64(inbound.len()) / observed_seconds),
        // A recording that reconnected did not watch this span continuously, and these bytes
        // cannot say where the holes were. One outbound control frame is one connection, so
        // outboundControlFrames above 1 means the span below has durable gaps in it; their exact
        // intervals live in the coverage records the record run committed beside these frames.
        "observedWindowIsContinuous": outbound <= 1,
        "frameKindCounts": kind_counts,
        "frameKindBytes": kind_bytes,
        "tradeFrameLeafPresence": trade_key_presence,
        "tradeFrames": trade_frames,
        "clock": {
            "providerClockKeysSeen": clock_key_presence,
            "statement": if clock_key_presence.is_empty() {
                "MEASURED: no trade frame of this feed carried a timestamp, a blockTime or a slot. \
                 The tape's only time axis is our own receive instant, which is arrival at this \
                 socket and not the instant the trade landed on chain."
            } else {
                "a provider clock key was present; see providerClockKeysSeen"
            },
        },
        "direction": {
            "providerLabel": "txType",
            "derivationRule": "constant-product back-solve of the pre-trade reserves under each \
                               hypothesis, using only the one frame; a name needs the losing \
                               hypothesis to miss by 3x the winning one, else undecidable",
            "agreements": label_agreements,
            "disagreements": label_disagreements,
            "undecidable": label_undecidable,
            "medianFitError": median(&mut fit_errors),
        },
        "duplicateSignatures": signatures.values().filter(|count| **count > 1).count(),
        "distinctSignatures": signatures.len(),
        "bucketSeconds": bucket_seconds,
        "swapApiUnboundPages": unbound_pages,
        "coins": coins,
    }))?)
}

/// The drawdown answer for one coin, at event resolution and at candle resolution.
fn coin_report(
    mint: &str,
    events: &[TradeEvent],
    bucket_seconds: u64,
    swap_api: &[&SwapApiPage],
) -> Result<Value, Box<dyn Error>> {
    let prices: Vec<f64> = events.iter().map(TradeEvent::price).collect();
    let event_drawdown = running_peak_drawdown(&prices);
    let entry_drawdown = prices
        .first()
        .map(|first| {
            prices
                .iter()
                .map(|price| (first - price) / first)
                .fold(0.0_f64, f64::max)
        })
        .unwrap_or_default();

    // Bucket the same events on their arrival instant. This is exactly the operation a fixed-width
    // candle series performs, and it is performed here on the tape's own events so that the two
    // numbers differ only by resolution and not by which trades each instrument saw.
    let width = i64::try_from(bucket_seconds)?.max(1) * 1_000;
    let mut buckets: BTreeMap<i64, (f64, f64, f64, f64, usize)> = BTreeMap::new();
    for (event, price) in events.iter().zip(&prices) {
        let key = event.received_at_millis.div_euclid(width);
        buckets
            .entry(key)
            .and_modify(|bucket| {
                bucket.1 = bucket.1.max(*price);
                bucket.2 = bucket.2.min(*price);
                bucket.3 = *price;
                bucket.4 += 1;
            })
            .or_insert((*price, *price, *price, *price, 1));
    }
    let closes: Vec<f64> = buckets.values().map(|bucket| bucket.3).collect();
    let close_drawdown = running_peak_drawdown(&closes);
    // What a candlestick could suggest: peak of the highs so far against this bar's low. It is an
    // UPPER bound, never the realised path — a bar states no order between its own high and low.
    let mut peak = f64::MIN;
    let mut ohlc_bound = 0.0_f64;
    for bucket in buckets.values() {
        peak = peak.max(bucket.1);
        if peak > 0.0 {
            ohlc_bound = ohlc_bound.max((peak - bucket.2) / peak);
        }
    }

    let buys = events.iter().filter(|event| event.label == "buy").count();
    let pools: BTreeSet<&str> = events.iter().map(|event| event.pool.as_str()).collect();
    let reserve_bases: BTreeSet<&str> = events.iter().map(|event| event.reserve_basis).collect();

    // Where one frame cannot name a direction, two can verify the provider's labels: if the
    // reserves are post-trade, a buy must raise the SOL reserve by its own solAmount and a sell
    // lower it, frame over frame. MEASURED 2026-08-22: 1688 of 1721 live pump-amm pairs fit this
    // evolution and none fit the pre-trade alternative, which is also the proof the stated
    // reserves are post-trade. Pairs straddling a venue migration are not comparable.
    let mut evolution_pairs = 0_usize;
    let mut evolution_consistent = 0_usize;
    for pair in events.windows(2) {
        let (previous, next) = (&pair[0], &pair[1]);
        if previous.reserve_basis != next.reserve_basis {
            continue;
        }
        let signed = if next.label == "buy" {
            next.sol_amount
        } else {
            -next.sol_amount
        };
        let predicted = previous.virtual_sol + signed;
        let scale = next.sol_amount.max(previous.sol_amount).max(1e-9);
        evolution_pairs += 1;
        if (next.virtual_sol - predicted).abs() < 0.05 * scale {
            evolution_consistent += 1;
        }
    }
    // Arrival order is the tape's only order. It is checked rather than assumed.
    let out_of_order = events
        .windows(2)
        .filter(|pair| pair[1].sequence <= pair[0].sequence)
        .count();
    let tape_signatures: BTreeSet<&str> = events
        .iter()
        .map(|event| event.signature.as_str())
        .collect();
    Ok(json!({
        "mint": mint,
        "events": events.len(),
        "buys": buys,
        "sells": events.len() - buys,
        "pools": pools,
        "reserveBases": reserve_bases,
        "firstEventUnixMs": events.first().map(|event| event.received_at_millis),
        "lastEventUnixMs": events.last().map(|event| event.received_at_millis),
        "firstPriceSolPerToken": prices.first(),
        "lastPriceSolPerToken": prices.last(),
        "eventResolutionMaxDrawdown": event_drawdown,
        "drawdownFromFirstObservedEvent": entry_drawdown,
        "bucketCount": buckets.len(),
        "bucketCloseMaxDrawdown": close_drawdown,
        "bucketOhlcUpperBound": ohlc_bound,
        "eventsPerBucket": buckets.values().map(|bucket| bucket.4).collect::<Vec<_>>(),
        "arrivalOrderInversions": out_of_order,
        "reserveEvolutionPairs": evolution_pairs,
        "reserveEvolutionConsistentWithLabels": evolution_consistent,
        "distinctTapeSignatures": tape_signatures.len(),
        "swapApiComparison": swap_api_comparison(events, swap_api),
    }))
}

fn running_peak_drawdown(prices: &[f64]) -> f64 {
    let mut peak = f64::MIN;
    let mut worst = 0.0_f64;
    for price in prices {
        peak = peak.max(*price);
        if peak > 0.0 {
            worst = worst.max((peak - price) / peak);
        }
    }
    worst
}

/// Milliseconds between two receipts inside one bounded recording: integer-exact in f64,
/// because a recording bounded to hours sits far below the 2^52 mantissa ceiling.
#[allow(clippy::cast_precision_loss)]
fn wall_span_seconds(first_millis: i64, last_millis: i64) -> f64 {
    (last_millis - first_millis) as f64 / 1_000.0
}

/// A frame count as f64 for a rate; bounded recordings hold far fewer than 2^52 frames.
#[allow(clippy::cast_precision_loss)]
fn count_as_f64(count: usize) -> f64 {
    count as f64
}

fn median(values: &mut [f64]) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    Some(values[values.len() / 2])
}

/// One `/v2/trades` row as the retained page states it.
///
/// MEASURED 2026-08-22: a row carries no `mint` field, its `timestamp` is an RFC 3339 string,
/// its amounts are decimal strings, and its `tx` is the transaction signature. The page as a
/// whole therefore names no coin; only its signatures can say which coin it is about.
struct SwapApiRow {
    tx: String,
    timestamp_unix_ms: i64,
    label: Option<String>,
    amount_sol: Option<f64>,
    program: Option<String>,
}

/// One retained swap-api trades page, read from a `joshi.pump_api.fetch_outcome.v1` envelope.
///
/// The envelopes are read as artifacts rather than through the pump client, because this crate
/// deliberately does not depend on it. Only the retained bytes are consulted.
struct SwapApiPage {
    path: String,
    fetched_received_at: Option<String>,
    rows: Vec<SwapApiRow>,
    rows_unreadable: usize,
}

fn swap_api_pages(paths: &[String]) -> Result<Vec<SwapApiPage>, Box<dyn Error>> {
    use base64::Engine as _;
    let mut pages = Vec::new();
    for path in paths {
        let outcome: Value = serde_json::from_slice(&fs::read(path)?)?;
        let attempt = outcome["attempts"]
            .as_array()
            .and_then(|attempts| attempts.last())
            .ok_or("fetch outcome carries no attempt")?;
        let encoded = attempt["body"]["bytesBase64"]
            .as_str()
            .ok_or("fetch outcome retains no exact body")?;
        let bytes = base64::engine::general_purpose::STANDARD.decode(encoded)?;
        let body: Value = serde_json::from_slice(&bytes)?;
        let mut rows = Vec::new();
        let mut rows_unreadable = 0_usize;
        for row in body["trades"].as_array().into_iter().flatten() {
            let (Some(tx), Some(timestamp_unix_ms)) = (row["tx"].as_str(), row_unix_ms(row)) else {
                rows_unreadable += 1;
                continue;
            };
            rows.push(SwapApiRow {
                tx: tx.to_owned(),
                timestamp_unix_ms,
                label: row["type"].as_str().map(ToOwned::to_owned),
                amount_sol: decimal_field(&row["amountSol"]),
                program: row["program"].as_str().map(ToOwned::to_owned),
            });
        }
        pages.push(SwapApiPage {
            path: path.clone(),
            fetched_received_at: attempt["clocks"]["receivedAt"]
                .as_str()
                .map(ToOwned::to_owned),
            rows,
            rows_unreadable,
        });
    }
    Ok(pages)
}

/// The trades route states `timestamp` as an RFC 3339 string; an epoch-millisecond number is
/// accepted too. Anything else is an unreadable clock, counted rather than guessed.
fn row_unix_ms(row: &Value) -> Option<i64> {
    if let Some(millis) = row["timestamp"].as_i64() {
        return Some(millis);
    }
    let parsed = OffsetDateTime::parse(
        row["timestamp"].as_str()?,
        &time::format_description::well_known::Rfc3339,
    )
    .ok()?;
    i64::try_from(parsed.unix_timestamp_nanos() / 1_000_000).ok()
}

/// The route states amounts as decimal strings; a bare number is accepted too.
fn decimal_field(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .or_else(|| value.as_str().and_then(|text| text.parse().ok()))
}

/// Tape vs swap-api page(s) for one coin, judged only inside the interval both instruments claim.
///
/// The API `timestamp` is the provider's own assertion — whether it anchors to chain time or to
/// the indexer's receipt is not stated by the route — so the deltas here are cross-source clock
/// offsets, not chain latency. Each side of the overlap window is filtered on its OWN clock.
fn swap_api_comparison(events: &[TradeEvent], pages: &[&SwapApiPage]) -> Option<Value> {
    if pages.is_empty() {
        return None;
    }
    // De-duplicated by signature on both sides: one transaction can hold several fills.
    let mut api_rows: BTreeMap<&str, &SwapApiRow> = BTreeMap::new();
    let mut api_multi_fill = 0_usize;
    for row in pages.iter().flat_map(|page| page.rows.iter()) {
        if api_rows.insert(row.tx.as_str(), row).is_some() {
            api_multi_fill += 1;
        }
    }
    let mut tape_events: BTreeMap<&str, &TradeEvent> = BTreeMap::new();
    for event in events {
        tape_events.entry(event.signature.as_str()).or_insert(event);
    }
    let api_span = fold_span(api_rows.values().map(|row| row.timestamp_unix_ms))?;
    let tape_span = (
        events.first()?.received_at_millis,
        events.last()?.received_at_millis,
    );
    let lower = api_span.0.max(tape_span.0);
    let upper = api_span.1.min(tape_span.1);

    let mut deltas: Vec<f64> = Vec::new();
    let mut label_disagreements = 0_usize;
    let mut amount_diffs: Vec<f64> = Vec::new();
    for (signature, event) in &tape_events {
        let Some(row) = api_rows.get(signature) else {
            continue;
        };
        deltas.push(millis_delta(
            event.received_at_millis,
            row.timestamp_unix_ms,
        ));
        if row
            .label
            .as_deref()
            .is_some_and(|label| label != event.label)
        {
            label_disagreements += 1;
        }
        if let Some(api_sol) = row.amount_sol
            && api_sol > 0.0
        {
            amount_diffs.push(((event.sol_amount - api_sol) / api_sol).abs());
        }
    }
    let matched = deltas.len();
    let tape_only = tape_events
        .iter()
        .filter(|(signature, event)| {
            (lower..=upper).contains(&event.received_at_millis)
                && !api_rows.contains_key(*signature)
        })
        .count();
    let api_only = api_rows
        .iter()
        .filter(|(signature, row)| {
            (lower..=upper).contains(&row.timestamp_unix_ms)
                && !tape_events.contains_key(*signature)
        })
        .count();
    let programs: BTreeSet<&str> = api_rows
        .values()
        .filter_map(|row| row.program.as_deref())
        .collect();
    let delta_span = fold_span(deltas.iter().copied());
    Some(json!({
        "pages": pages.iter().map(|page| json!({
            "path": page.path,
            "fetchedReceivedAt": page.fetched_received_at,
            "rows": page.rows.len(),
            "rowsUnreadable": page.rows_unreadable,
        })).collect::<Vec<_>>(),
        "binding": "signature intersection; no file name or request label was trusted",
        "apiDistinctSignatures": api_rows.len(),
        "apiMultiFillRows": api_multi_fill,
        "apiRowSpanUnixMs": [api_span.0, api_span.1],
        "overlapWindowUnixMs": [lower, upper],
        "matchedSignatures": matched,
        "tapeOnlyInOverlap": tape_only,
        "apiOnlyInOverlap": api_only,
        "apiPrograms": programs,
        "arrivalMinusApiClockMs": {
            "caveat": "tape receive clock minus the provider's asserted row clock; the route \
                       quantises its clock, so each delta carries that quantum, and the anchor \
                       of the provider clock (chain vs indexer) is unstated",
            "count": matched,
            "median": median(&mut deltas),
            "minMax": delta_span,
        },
        "labelDisagreements": label_disagreements,
        "solAmountRelativeDiff": {
            "count": amount_diffs.len(),
            "median": median(&mut amount_diffs),
            "max": fold_span(amount_diffs.iter().copied()).map(|(_, hi)| hi),
        },
    }))
}

/// Difference of two epoch-millisecond instants as f64; bounded recordings sit far below 2^52.
#[allow(clippy::cast_precision_loss)]
fn millis_delta(left: i64, right: i64) -> f64 {
    (left - right) as f64
}

/// Smallest and largest of an iterator, in one pass, `None` for an empty one.
fn fold_span<T: PartialOrd + Copy>(values: impl Iterator<Item = T>) -> Option<(T, T)> {
    values.fold(None, |span, value| {
        let (lo, hi) = span.unwrap_or((value, value));
        Some((
            if value < lo { value } else { lo },
            if value > hi { value } else { hi },
        ))
    })
}

fn trailing_sequence(acquisition_id: &str) -> Result<u64, Box<dyn Error>> {
    acquisition_id
        .rsplit(':')
        .next()
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or_else(|| "retained acquisition id states no frame sequence".into())
}

fn millis_of(value: UtcTimestamp) -> i64 {
    i64::try_from(value.as_datetime().unix_timestamp_nanos() / 1_000_000).unwrap_or_default()
}

// ---------------------------------------------------------------------------------------------
// The reconnect policy and the coverage walk, driven by a scripted transport. These are the parts
// a live run cannot be relied on to exercise: a provider hiccup happens when it happens, and a
// funded key is refused only on the night the plan lapses.
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::{
        CAUSE_AWAITING_FIRST_LIVENESS, CAUSE_BACKOFF_WAIT, Captured, Next, ReconnectPolicy,
        RunStop, SessionEnd, SessionLimits, SessionOutcome, Tape, Unobserved, Wire, WirePoll,
        next_step, now_millis, run_session, unobserved_spans,
    };
    use bytes::Bytes;
    use std::{
        collections::VecDeque,
        error::Error,
        time::{Duration, Instant},
    };

    const REFUSAL: &[u8] = br#"{"message":"'subscribeTokenTrade' is only available when connecting with an API key funded with at least 0.02 SOL"}"#;
    const ACK: &[u8] = br#"{"message":"Successfully subscribed to token trades."}"#;
    const TRADE: &[u8] = br#"{"signature":"s1","mint":"m1","txType":"buy","solAmount":1.0}"#;

    fn policy() -> ReconnectPolicy {
        ReconnectPolicy {
            max_attempts: 3,
            initial_backoff: Duration::from_secs(2),
            max_backoff: Duration::from_mins(1),
        }
    }

    #[test]
    fn the_backoff_doubles_from_its_start_and_stops_at_the_ceiling() {
        let policy = policy();
        let waits: Vec<u64> = (1..=8).map(|n| policy.backoff(n).as_secs()).collect();
        assert_eq!(waits, vec![2, 4, 8, 16, 32, 60, 60, 60]);
        // A caller who asks for an absurd run of attempts still gets the ceiling, not an overflow.
        assert_eq!(policy.backoff(u32::MAX), Duration::from_mins(1));
    }

    #[test]
    fn a_refusal_at_the_door_is_terminal_and_is_never_retried() {
        let step = next_step(
            policy(),
            SessionEnd::SubscriptionRefused,
            true,
            0,
            Duration::from_mins(10),
        );
        assert_eq!(step, Next::Stop(RunStop::SubscriptionRefused));
    }

    #[test]
    fn a_refusal_on_a_reconnect_is_terminal_under_its_own_distinct_reason() {
        // Accepted at the start of the run, refused now: the shape of a plan expiring mid-run. It
        // must not be retried, and it must not be reported as having been refused at the door.
        let step = next_step(
            policy(),
            SessionEnd::SubscriptionRefused,
            false,
            0,
            Duration::from_mins(10),
        );
        assert_eq!(step, Next::Stop(RunStop::SubscriptionRefusedOnReconnect));
        assert_ne!(
            RunStop::SubscriptionRefusedOnReconnect.as_str(),
            RunStop::SubscriptionRefused.as_str()
        );
    }

    #[test]
    fn a_hiccup_reconnects_while_the_window_and_the_attempts_last() {
        let hiccups = [
            SessionEnd::ProviderClosedSocket,
            SessionEnd::TransportError,
            SessionEnd::InactivityCeiling,
            SessionEnd::HostSuspended,
            SessionEnd::ConnectFailed,
        ];
        for end in hiccups {
            let step = next_step(policy(), end, false, 0, Duration::from_mins(10));
            assert_eq!(
                step,
                Next::Reconnect {
                    attempt: 1,
                    backoff: Duration::from_secs(2)
                },
                "{end:?} is survivable"
            );
        }
        assert_eq!(
            next_step(
                policy(),
                SessionEnd::ProviderClosedSocket,
                false,
                2,
                Duration::from_mins(10)
            ),
            Next::Reconnect {
                attempt: 3,
                backoff: Duration::from_secs(8)
            }
        );
    }

    #[test]
    fn consecutive_attempts_are_capped_and_the_wait_never_outruns_the_window() {
        assert_eq!(
            next_step(
                policy(),
                SessionEnd::ProviderClosedSocket,
                false,
                3,
                Duration::from_mins(10)
            ),
            Next::Stop(RunStop::ReconnectAttemptsExhausted)
        );
        // A backoff that would land after the planned end is clamped to what is left of it.
        assert_eq!(
            next_step(
                policy(),
                SessionEnd::ProviderClosedSocket,
                false,
                2,
                Duration::from_millis(1_500)
            ),
            Next::Reconnect {
                attempt: 3,
                backoff: Duration::from_millis(1_500)
            }
        );
        assert_eq!(
            next_step(
                policy(),
                SessionEnd::ProviderClosedSocket,
                false,
                0,
                Duration::ZERO
            ),
            Next::Stop(RunStop::WallClockBudget)
        );
    }

    #[test]
    fn a_budget_stop_ends_the_run_rather_than_opening_another_socket() {
        for (end, stop) in [
            (SessionEnd::PlannedWindowReached, RunStop::WallClockBudget),
            (SessionEnd::FrameBudget, RunStop::FrameBudget),
            (SessionEnd::ByteBudget, RunStop::ByteBudget),
        ] {
            assert_eq!(
                next_step(policy(), end, false, 0, Duration::from_mins(10)),
                Next::Stop(stop)
            );
        }
        // Only the wall clock running out means the run stayed on the job to the end it promised.
        assert!(RunStop::WallClockBudget.planned_window_completed());
        assert!(!RunStop::FrameBudget.planned_window_completed());
        assert!(!RunStop::ReconnectAttemptsExhausted.planned_window_completed());
    }

    #[test]
    fn reconnecting_is_refused_outright_when_the_policy_allows_no_attempts() {
        let policy = ReconnectPolicy {
            max_attempts: 0,
            ..policy()
        };
        assert_eq!(
            next_step(
                policy,
                SessionEnd::ProviderClosedSocket,
                true,
                0,
                Duration::from_mins(10)
            ),
            Next::Stop(RunStop::ReconnectAttemptsExhausted)
        );
    }

    // -- the session loop against a scripted transport -----------------------------------------

    struct ScriptedWire {
        send_fails: bool,
        script: VecDeque<WirePoll>,
    }

    impl ScriptedWire {
        fn new(script: Vec<WirePoll>) -> Self {
            Self {
                send_fails: false,
                script: script.into(),
            }
        }
    }

    impl Wire for ScriptedWire {
        async fn send_subscription(&mut self, _text: String) -> Result<(), ()> {
            if self.send_fails { Err(()) } else { Ok(()) }
        }

        async fn poll_within(&mut self, _within: Duration) -> WirePoll {
            self.script.pop_front().unwrap_or(WirePoll::Closed)
        }
    }

    fn limits(max_frames: usize) -> SessionLimits {
        SessionLimits {
            deadline: Instant::now() + Duration::from_mins(10),
            planned_end_millis: now_millis().expect("a wall clock") + 600_000,
            inactivity: Duration::from_secs(45),
            max_frames,
            max_bytes: 1 << 20,
        }
    }

    /// Run one scripted connection and hand back what it decided and what it retained.
    async fn drive(
        wire: &mut ScriptedWire,
        limits: SessionLimits,
    ) -> (SessionOutcome, Vec<String>) {
        let mut retained: Vec<String> = Vec::new();
        let outcome = {
            let mut commit =
                |captured: Vec<Captured>, _chunk: usize| -> Result<(), Box<dyn Error>> {
                    retained.extend(
                        captured
                            .into_iter()
                            .map(|item| String::from_utf8_lossy(&item.frame.body).into_owned()),
                    );
                    Ok(())
                };
            let mut tape = Tape::new(Instant::now(), &mut commit);
            let outcome = run_session(wire, &mut tape, b"{\"method\":\"x\"}", 1, 101, limits)
                .await
                .expect("the session loop");
            tape.flush().expect("the retained frames");
            outcome
        };
        (outcome, retained)
    }

    #[tokio::test]
    async fn a_provider_close_ends_the_connection_after_everything_it_delivered_is_retained() {
        let mut wire = ScriptedWire::new(vec![
            WirePoll::Frame(Bytes::from_static(ACK)),
            WirePoll::Frame(Bytes::from_static(TRADE)),
            WirePoll::Closed,
        ]);
        let (outcome, retained) = drive(&mut wire, limits(1_000)).await;
        assert_eq!(outcome.end, SessionEnd::ProviderClosedSocket);
        assert_eq!(outcome.inbound_frames, 2);
        assert_eq!(outcome.inbound_bytes, ACK.len() + TRADE.len());
        // The ask and both answers, in the order they crossed the socket.
        assert_eq!(retained.len(), 3);
        assert!(retained[0].contains("method"));
        assert!(outcome.first_liveness_millis.is_some());
        assert_eq!(outcome.last_frame_millis, outcome.last_liveness_millis);
    }

    #[tokio::test]
    async fn a_transport_error_ends_the_connection_and_is_not_confused_with_a_close() {
        let mut wire = ScriptedWire::new(vec![
            WirePoll::Frame(Bytes::from_static(ACK)),
            WirePoll::Failed,
        ]);
        let (outcome, retained) = drive(&mut wire, limits(1_000)).await;
        assert_eq!(outcome.end, SessionEnd::TransportError);
        assert_eq!(retained.len(), 2);
    }

    #[tokio::test]
    async fn a_refusal_is_retained_before_the_connection_stops_on_it() {
        let mut wire = ScriptedWire::new(vec![WirePoll::Frame(Bytes::from_static(REFUSAL))]);
        let (outcome, retained) = drive(&mut wire, limits(1_000)).await;
        assert_eq!(outcome.end, SessionEnd::SubscriptionRefused);
        assert_eq!(outcome.inbound_frames, 1);
        // The provider's exact words survive: the receipt never has to paraphrase the refusal.
        assert_eq!(retained.len(), 2);
        assert!(retained[1].contains("0.02 SOL"));
        // And it claims nothing, however long the socket stayed open afterwards.
        let (lower, upper) = outcome.claimed(outcome.closed_at_millis + 60_000);
        assert_eq!(lower, upper);
    }

    #[tokio::test]
    async fn a_websocket_ping_is_liveness_and_is_not_a_frame() {
        let mut wire = ScriptedWire::new(vec![
            WirePoll::Alive,
            WirePoll::Frame(Bytes::from_static(TRADE)),
            WirePoll::Closed,
        ]);
        let (outcome, retained) = drive(&mut wire, limits(1_000)).await;
        assert_eq!(outcome.transport_pings, 1);
        assert_eq!(outcome.inbound_frames, 1);
        assert_eq!(retained.len(), 2);
        // Liveness began at the ping, before any frame arrived.
        assert!(outcome.first_liveness_millis <= outcome.last_frame_millis);
    }

    #[tokio::test]
    async fn a_send_that_never_left_retains_no_ask_and_reads_as_a_transport_fault() {
        let mut wire = ScriptedWire::new(vec![WirePoll::Frame(Bytes::from_static(ACK))]);
        wire.send_fails = true;
        let (outcome, retained) = drive(&mut wire, limits(1_000)).await;
        assert_eq!(outcome.end, SessionEnd::TransportError);
        assert!(retained.is_empty(), "an unsent ask was never made");
    }

    #[tokio::test]
    async fn the_frame_budget_spans_the_whole_chained_run_and_not_one_connection() {
        let mut retained = 0_usize;
        let mut commit = |captured: Vec<Captured>, _chunk: usize| -> Result<(), Box<dyn Error>> {
            retained += captured.len();
            Ok(())
        };
        let mut tape = Tape::new(Instant::now(), &mut commit);
        let limits = limits(1);
        let mut first = ScriptedWire::new(vec![
            WirePoll::Frame(Bytes::from_static(ACK)),
            WirePoll::Frame(Bytes::from_static(TRADE)),
        ]);
        let one = run_session(&mut first, &mut tape, b"{}", 1, 101, limits)
            .await
            .expect("the first connection");
        assert_eq!(one.end, SessionEnd::FrameBudget);
        assert_eq!(one.inbound_frames, 1);

        // The next connection inherits the spent budget rather than starting over on it.
        let mut second = ScriptedWire::new(vec![WirePoll::Frame(Bytes::from_static(TRADE))]);
        let two = run_session(&mut second, &mut tape, b"{}", 2, 101, limits)
            .await
            .expect("the second connection");
        assert_eq!(two.end, SessionEnd::FrameBudget);
        assert_eq!(two.inbound_frames, 0);
        // And the total order never restarts: two asks and one answer, sequenced 0, 1, 2.
        assert_eq!(tape.sequence, 3);
        tape.flush().expect("the retained frames");
        assert_eq!(retained, 3);
    }

    // -- the coverage walk ---------------------------------------------------------------------

    fn ended(
        epoch: u64,
        open: i64,
        close: i64,
        liveness: Option<(i64, i64)>,
        end: SessionEnd,
    ) -> SessionOutcome {
        SessionOutcome {
            epoch,
            handshake_status: 101,
            opened_at_millis: open,
            closed_at_millis: close,
            first_liveness_millis: liveness.map(|(first, _)| first),
            last_liveness_millis: liveness.map(|(_, last)| last),
            last_frame_millis: liveness.map(|(_, last)| last),
            inbound_frames: usize::from(liveness.is_some()),
            inbound_bytes: 0,
            transport_pings: 0,
            end,
        }
    }

    fn told(spans: &[Unobserved]) -> Vec<(i64, i64, &'static str)> {
        spans
            .iter()
            .map(|span| (span.lower_millis, span.upper_millis, span.cause))
            .collect()
    }

    /// Every claim plus every gap must add back up to exactly the window the caller asked for.
    fn tiles(sessions: &[SessionOutcome], spans: &[Unobserved], open: i64, planned_end: i64) {
        let claimed: i64 = sessions
            .iter()
            .map(|session| {
                let (lower, upper) = session.claimed(planned_end);
                upper - lower
            })
            .sum();
        let unobserved: i64 = spans
            .iter()
            .map(|span| span.upper_millis - span.lower_millis)
            .sum();
        assert_eq!(claimed + unobserved, planned_end - open);
    }

    #[test]
    fn an_undisturbed_run_owns_only_the_seconds_it_spent_getting_connected() {
        let sessions = [ended(
            1,
            1_050,
            61_002,
            Some((1_300, 60_900)),
            SessionEnd::PlannedWindowReached,
        )];
        let spans = unobserved_spans(&sessions, 1_000, 61_000, RunStop::WallClockBudget);
        assert_eq!(
            told(&spans),
            vec![(1_000, 1_300, CAUSE_AWAITING_FIRST_LIVENESS)]
        );
        tiles(&sessions, &spans, 1_000, 61_000);
    }

    #[test]
    fn a_hiccup_and_a_reconnect_leave_two_named_holes_that_meet_exactly() {
        let sessions = [
            ended(
                1,
                10,
                20_000,
                Some((300, 19_500)),
                SessionEnd::ProviderClosedSocket,
            ),
            ended(
                2,
                22_100,
                60_005,
                Some((22_400, 59_900)),
                SessionEnd::PlannedWindowReached,
            ),
        ];
        let spans = unobserved_spans(&sessions, 0, 60_000, RunStop::WallClockBudget);
        assert_eq!(
            told(&spans),
            vec![
                (0, 300, CAUSE_AWAITING_FIRST_LIVENESS),
                // Nothing after the dying socket's last word may be claimed, even though the
                // socket was nominally still ours for another half second.
                (19_500, 20_000, "provider_closed_socket_before_planned_end"),
                (20_000, 22_400, CAUSE_BACKOFF_WAIT),
            ]
        );
        // Both connections keep their own claim; the second hangs its gaps off the first.
        assert_eq!(spans[1].anchor, 0);
        assert_eq!(spans[2].anchor, 0);
        tiles(&sessions, &spans, 0, 60_000);
    }

    #[test]
    fn a_refused_run_nets_to_no_coverage_at_all() {
        let sessions = [ended(
            1,
            10,
            400,
            Some((350, 350)),
            SessionEnd::SubscriptionRefused,
        )];
        let spans = unobserved_spans(&sessions, 0, 60_000, RunStop::SubscriptionRefused);
        assert_eq!(
            told(&spans),
            vec![
                (0, 350, CAUSE_AWAITING_FIRST_LIVENESS),
                (350, 60_000, "provider_refused_subscription"),
            ]
        );
        let unobserved: i64 = spans
            .iter()
            .map(|span| span.upper_millis - span.lower_millis)
            .sum();
        assert_eq!(unobserved, 60_000, "the whole planned window is a gap");
    }

    #[test]
    fn a_budget_stop_names_the_tail_it_chose_not_to_watch() {
        let sessions = [ended(
            1,
            10,
            30_000,
            Some((300, 29_900)),
            SessionEnd::FrameBudget,
        )];
        let spans = unobserved_spans(&sessions, 0, 60_000, RunStop::FrameBudget);
        assert_eq!(
            told(&spans),
            vec![
                (0, 300, CAUSE_AWAITING_FIRST_LIVENESS),
                (30_000, 60_000, "frame_budget_exhausted"),
            ]
        );
        tiles(&sessions, &spans, 0, 60_000);
    }

    #[test]
    fn reaching_the_planned_end_inside_a_backoff_is_completed_and_still_holed() {
        let sessions = [ended(
            1,
            10,
            55_000,
            Some((300, 54_000)),
            SessionEnd::TransportError,
        )];
        let spans = unobserved_spans(&sessions, 0, 60_000, RunStop::WallClockBudget);
        assert_eq!(
            told(&spans),
            vec![
                (0, 300, CAUSE_AWAITING_FIRST_LIVENESS),
                (54_000, 55_000, "transport_error_before_planned_end"),
                (55_000, 60_000, CAUSE_BACKOFF_WAIT),
            ]
        );
        // The clock genuinely ran out, and six seconds of the window were never watched. Both are
        // true at once, which is why one flag can never stand in for the other.
        assert!(RunStop::WallClockBudget.planned_window_completed());
        tiles(&sessions, &spans, 0, 60_000);
    }

    #[test]
    fn a_socket_that_opened_as_the_window_closed_cannot_claim_the_window() {
        // It reached the planned end, which is the arm that vouches all the way to it — but it
        // never heard the provider, so it has proved nothing and must claim nothing.
        let silent = ended(1, 59_990, 60_003, None, SessionEnd::PlannedWindowReached);
        assert_eq!(silent.claimed(60_000), (59_990, 59_990));
    }

    #[test]
    fn a_connection_that_never_heard_a_word_claims_nothing_and_widens_the_hole() {
        let sessions = [
            ended(
                1,
                10,
                20_000,
                Some((300, 19_500)),
                SessionEnd::ProviderClosedSocket,
            ),
            // Connected, asked, and was answered by nothing until the inactivity ceiling.
            ended(2, 22_000, 67_000, None, SessionEnd::InactivityCeiling),
        ];
        let spans = unobserved_spans(&sessions, 0, 90_000, RunStop::ReconnectAttemptsExhausted);
        assert_eq!(
            told(&spans),
            vec![
                (0, 300, CAUSE_AWAITING_FIRST_LIVENESS),
                (19_500, 20_000, "provider_closed_socket_before_planned_end"),
                (20_000, 22_000, CAUSE_BACKOFF_WAIT),
                (22_000, 67_000, "no_frame_within_inactivity_ceiling"),
                (67_000, 90_000, "reconnect_attempts_exhausted"),
            ]
        );
        tiles(&sessions, &spans, 0, 90_000);
    }
}
