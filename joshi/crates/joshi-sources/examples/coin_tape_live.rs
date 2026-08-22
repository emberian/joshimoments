//! One coin's trade tape at EVENT resolution, retained under budgets this process enforces.
//!
//! ```text
//! coin_tape_live record  --root <dir> --mints <csv> [--seconds n] [--max-frames n]
//!                        [--max-bytes n] [--key-file <path>]
//! coin_tape_live analyse --root <dir> [--bucket-seconds 60] [--trades <fetch-outcome.json>]...
//! ```
//!
//! `record` opens ONE `PumpPortal` data socket, asks for the named mints' trades, and retains
//! every inbound frame — trades, acknowledgements, provider control, anything — as exact bytes
//! through the ordinary source-admission path. Three budgets bound it and this process checks all
//! three itself rather than trusting the transport: a wall-clock ceiling, a frame ceiling and a
//! byte ceiling. Exhausting one is a recorded stop. A socket that closes before the wall-clock
//! ceiling produces an explicit coverage GAP carrying the exact unobserved window, because this
//! feed exposes no replay cursor and therefore nothing can ever fill it in.
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
use futures_util::{SinkExt, StreamExt};
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
            let key_file = flag(&arguments, "--key-file").map(PathBuf::from);
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?;
            println!("{}", runtime.block_on(record(&root, &mints, budget, key_file.as_deref()))?);
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
     [--max-frames n] [--max-bytes n] [--key-file <path>] [--bucket-seconds n] \
     [--trades <fetch-outcome.json>]"
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

/// Why the recorder stopped. Every stop is one of these; none of them is a silence.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Stop {
    WallClockBudget,
    FrameBudget,
    ByteBudget,
    ProviderClosedSocket,
    TransportError,
    /// No frame for longer than the inactivity ceiling. MEASURED THE HARD WAY: a first run left a
    /// half-open socket after the host suspended, and `next()` simply never returned again. From
    /// inside the loop that is indistinguishable from a market that went quiet, so the tape has to
    /// stop and say so rather than sit there accumulating an unobserved window it will later
    /// report as coverage.
    InactivityCeiling,
    /// The host's wall clock ran ahead of its monotonic clock, which means this process was
    /// suspended. Everything between the last frame and the resume instant is unobserved.
    HostSuspended,
}

impl Stop {
    const fn as_str(self) -> &'static str {
        match self {
            Self::WallClockBudget => "wall_clock_budget_exhausted",
            Self::FrameBudget => "frame_budget_exhausted",
            Self::ByteBudget => "byte_budget_exhausted",
            Self::ProviderClosedSocket => "provider_closed_socket_before_planned_end",
            Self::TransportError => "transport_error_before_planned_end",
            Self::InactivityCeiling => "no_frame_within_inactivity_ceiling",
            Self::HostSuspended => "host_suspended_during_window",
        }
    }

    /// A budget stop covered the window it promised. Anything else left an unobserved tail.
    const fn planned_window_completed(self) -> bool {
        matches!(
            self,
            Self::WallClockBudget | Self::FrameBudget | Self::ByteBudget
        )
    }
}

struct Captured {
    frame: RawSourceFrame,
    mono_ns: u64,
}

#[allow(clippy::too_many_lines)] // One bounded connect/record/retain/gap walk, kept in one place.
async fn record(
    root: &Path,
    mints: &str,
    budget: Budget,
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
    // wallet-signing authority; a keyless connection is the default for that reason.
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
    let (mut socket, response) = tokio_tungstenite::connect_async(endpoint).await?;
    let handshake_status = response.status().as_u16();

    let mut store = SqliteStore::open(catalog_config(root)?, StoreMode::SingleWriter)?;
    store.migrate(now_utc()?)?;

    // A coverage subject and a request fingerprint are 512-byte wire strings, and a subscription
    // to sixteen mints does not fit in one. The subject therefore names the key SET by digest and
    // by count; the exact key list is retained verbatim as the outbound subscription frame, so
    // nothing is lost and no later reader has to take the membership from a file name.
    let key_digest = Sha256Digest::of_bytes(keys.join(",").as_bytes()).to_string();
    let subject = format!("keys={}:{key_digest}", keys.len());
    let fingerprint_material = format!("pumpportal:{FEED_LOCATOR}:{subject}");
    let mut sequence = 0_u64;
    let mut pending: Vec<Captured> = Vec::new();
    let mut receipts: Vec<PublicStoreReceiptV1> = Vec::new();
    let mut chunk_index = 0_usize;

    // The subscription request itself is retained, so the catalog states which subjects this
    // window claims coverage of without any later reader taking that on trust from a filename.
    let subscribe = json!({"method": "subscribeTokenTrade", "keys": keys});
    let subscribe_bytes = serde_json::to_vec(&subscribe)?;
    let sent_at = now_millis()?;
    socket
        .send(Message::Text(
            String::from_utf8(subscribe_bytes.clone())?.into(),
        ))
        .await?;
    pending.push(Captured {
        frame: RawSourceFrame {
            contract_version: ADAPTER_CONTRACT_VERSION.to_owned(),
            source: SourceId::PumpPortalWebSocket,
            transport: Transport::WebSocket,
            stream_class: StreamClass::LeasedHot,
            direction: FrameDirection::OutboundControl,
            content_type: ContentType::Json,
            received_at: UnixMillis(sent_at),
            connection_epoch: 1,
            sequence,
            http_status: None,
            safe_headers: Vec::new(),
            body: Bytes::from(subscribe_bytes),
        },
        mono_ns: u64::try_from(process_start.elapsed().as_nanos())?,
    });
    sequence += 1;

    let loop_start = Instant::now();
    let deadline = loop_start + Duration::from_secs(budget.seconds);
    let mut inbound_frames = 0_usize;
    let mut inbound_bytes = 0_usize;
    let mut last_frame_millis = sent_at;
    let stop = loop {
        if inbound_frames >= budget.max_frames {
            break Stop::FrameBudget;
        }
        if inbound_bytes >= budget.max_bytes {
            break Stop::ByteBudget;
        }
        let now = now_millis()?;
        // A suspended host is an unobserved window, not a quiet one. The two clocks are compared
        // rather than trusted individually: a monotonic deadline silently stretches across a
        // suspend, and a wall clock alone cannot tell a suspend from a slow loop.
        let wall_elapsed = now - sent_at;
        let mono_elapsed = i64::try_from(loop_start.elapsed().as_millis())?;
        if wall_elapsed - mono_elapsed > 5_000 {
            break Stop::HostSuspended;
        }
        if now >= planned_end_millis {
            break Stop::WallClockBudget;
        }
        if now - last_frame_millis > i64::try_from(budget.inactivity_seconds)? * 1_000 {
            break Stop::InactivityCeiling;
        }
        let remaining = deadline
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(budget.inactivity_seconds));
        if remaining.is_zero() {
            break Stop::WallClockBudget;
        }
        let message = match tokio::time::timeout(remaining, socket.next()).await {
            // A timeout here is only ever a silence: which kind it was is decided at the top of
            // the next iteration, against both clocks.
            Err(_) => continue,
            Ok(None) => break Stop::ProviderClosedSocket,
            Ok(Some(Err(_))) => break Stop::TransportError,
            Ok(Some(Ok(message))) => message,
        };
        let body = match message {
            Message::Text(text) => Bytes::from(text.as_bytes().to_vec()),
            Message::Binary(binary) => Bytes::from(binary.to_vec()),
            Message::Close(_) => break Stop::ProviderClosedSocket,
            Message::Ping(_) | Message::Pong(_) | Message::Frame(_) => continue,
        };
        let received = now_millis()?;
        last_frame_millis = received;
        inbound_frames += 1;
        inbound_bytes += body.len();
        pending.push(Captured {
            frame: RawSourceFrame::inbound_websocket(
                SourceId::PumpPortalWebSocket,
                StreamClass::LeasedHot,
                UnixMillis(received),
                1,
                sequence,
                ContentType::Json,
                body,
            ),
            mono_ns: u64::try_from(process_start.elapsed().as_nanos())?,
        });
        sequence += 1;
        if pending.len() >= MAX_OBSERVATIONS_PER_BATCH {
            receipts.push(commit_frames(
                &mut store,
                std::mem::take(&mut pending),
                &namespace,
                &clock_id,
                &fingerprint_material,
                chunk_index,
                process_start,
            )?);
            chunk_index += 1;
        }
    };
    let closed_at_millis = now_millis()?;
    // Say why before doing anything that could fail, so a later refusal cannot hide the stop.
    eprintln!(
        "coin_tape_live: stopped after {inbound_frames} inbound frames: {}",
        stop.as_str()
    );
    if !pending.is_empty() {
        receipts.push(commit_frames(
            &mut store,
            std::mem::take(&mut pending),
            &namespace,
            &clock_id,
            &fingerprint_material,
            chunk_index,
            process_start,
        )?);
    }

    let coverage = commit_coverage(
        &mut store,
        &namespace,
        &clock_id,
        &subject,
        opened_at_millis,
        closed_at_millis,
        planned_end_millis,
        stop,
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

    Ok(serde_json::to_string_pretty(&json!({
        "contract": "joshi.coin_tape.record_receipt.v1",
        "endpointHost": "pumpportal.fun",
        "credentialAttached": key_file.is_some(),
        "handshakeStatus": handshake_status,
        "namespace": namespace,
        "subjects": keys,
        "budget": {
            "wallClockSeconds": budget.seconds,
            "maxInboundFrames": budget.max_frames,
            "maxInboundBytes": budget.max_bytes,
            "inactivityCeilingSeconds": budget.inactivity_seconds,
        },
        "openedAtUnixMs": opened_at_millis,
        "plannedEndUnixMs": planned_end_millis,
        "closedAtUnixMs": closed_at_millis,
        "lastFrameAtUnixMs": last_frame_millis,
        "stopReason": stop.as_str(),
        "plannedWindowCompleted": stop.planned_window_completed(),
        "inboundFrames": inbound_frames,
        "inboundBytes": inbound_bytes,
        "observationBatches": receipts.len(),
        "coverageId": coverage.0,
        "gapIds": coverage.1,
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

/// Retain the window this run claims, and the exact interval it promised but did not observe.
#[allow(clippy::too_many_arguments)] // Every boundary of the claim is named explicitly.
fn commit_coverage(
    store: &mut SqliteStore,
    namespace: &str,
    clock_id: &str,
    subject: &str,
    opened_at_millis: i64,
    closed_at_millis: i64,
    planned_end_millis: i64,
    stop: Stop,
    process_start: Instant,
) -> Result<(String, Vec<String>), Box<dyn Error>> {
    let persisted_at = now_utc()?;
    let coverage_id = CoverageId::new(format!("coverage-{namespace}"))?;
    let scope = CoverageScope {
        source_id: DomainSourceId::new(SOURCE_ID)?,
        family: OpenVariant::known(COVERAGE_FAMILY)?,
        subject: Some(StableString::new(subject)?),
    };
    let window = CoverageWindow {
        coverage_id: coverage_id.clone(),
        scope: scope.clone(),
        lower: Boundary::Wall {
            value: utc_from_millis(opened_at_millis)?,
        },
        upper: Some(Boundary::Wall {
            value: utc_from_millis(closed_at_millis)?,
        }),
        state: OpenVariant::known("closed")?,
        available_at: persisted_at,
    };
    let mut gap_ids = Vec::new();
    let mut gaps = Vec::new();
    if !stop.planned_window_completed() && closed_at_millis < planned_end_millis {
        let gap_id = format!("gap-{namespace}-unobserved-tail");
        gap_ids.push(gap_id.clone());
        gaps.push(CoverageGap {
            gap_id: CoverageId::new(gap_id)?,
            coverage_id: coverage_id.clone(),
            scope: scope.clone(),
            lower: Boundary::Wall {
                value: utc_from_millis(closed_at_millis)?,
            },
            upper: Some(Boundary::Wall {
                value: utc_from_millis(planned_end_millis)?,
            }),
            // This feed exposes no replay cursor and no historical backfill, so the interval below
            // is not merely late: it is unrecoverable, and no later run can ever close it.
            reason: OpenVariant::known(stop.as_str())?,
            detected_at: persisted_at,
        });
    }
    let mut mono = u64::try_from(process_start.elapsed().as_nanos())?;
    for (severity_index, severity) in [SEVERITY_DEGRADED, SEVERITY_SCOPE_STOPPED]
        .into_iter()
        .enumerate()
    {
        let mut drafts = Vec::new();
        if severity_index == 0 {
            drafts.push(EvidenceDraft::CoverageWindow(window.clone()));
        } else {
            drafts.extend(gaps.iter().cloned().map(EvidenceDraft::CoverageGap));
        }
        if drafts.is_empty() {
            continue;
        }
        mono = mono.saturating_add(1);
        let batch = source_drafts(SourceDraftBatch {
            batch_id: StableString::new(format!("{namespace}-coverage-{severity}"))?,
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
    }
    Ok((coverage_id.as_str().to_owned(), gap_ids))
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
    virtual_sol: f64,
    virtual_tokens: f64,
    pool: String,
}

impl TradeEvent {
    /// SOL per token implied by the curve state the frame states, which is exact arithmetic on
    /// two numbers the provider supplied rather than a price it asserted.
    fn price(&self) -> f64 {
        self.virtual_sol / self.virtual_tokens
    }

    /// Direction derived from the frame ALONE, with no neighbour and no provider label.
    ///
    /// A pump bonding curve is a constant product. A frame states the post-trade reserves and the
    /// two amounts that moved, so the pre-trade reserves are recoverable under each hypothesis and
    /// only the true one comes close to reproducing the post-trade product. `None` means neither
    /// hypothesis fitted well enough to name, which is reported as an unknown rather than guessed.
    fn derived_direction(&self) -> (Option<&'static str>, f64) {
        let after = self.virtual_sol * self.virtual_tokens;
        if after <= 0.0 {
            return (None, f64::INFINITY);
        }
        let buy = (self.virtual_sol - self.sol_amount) * (self.virtual_tokens + self.token_amount);
        let sell = (self.virtual_sol + self.sol_amount) * (self.virtual_tokens - self.token_amount);
        let buy_error = ((buy - after) / after).abs();
        let sell_error = ((sell - after) / after).abs();
        let (name, error) = if buy_error <= sell_error {
            ("buy", buy_error)
        } else {
            ("sell", sell_error)
        };
        // The curve charges a fee on the SOL leg, so neither hypothesis reproduces the product
        // exactly. One percent is far tighter than the gap between the two hypotheses, which is
        // of order the trade size relative to the reserves.
        if error > 0.01 {
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
        for candidate in ["timestamp", "blockTime", "block_time", "eventTime", "time", "slot"] {
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
        let (
            Some(label),
            Some(sol_amount),
            Some(token_amount),
            Some(virtual_sol),
            Some(virtual_tokens),
        ) = (
            value["txType"].as_str().map(ToOwned::to_owned),
            value["solAmount"].as_f64(),
            value["tokenAmount"].as_f64(),
            value["vSolInBondingCurve"].as_f64(),
            value["vTokensInBondingCurve"].as_f64(),
        )
        else {
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

    let window = inbound.first().zip(inbound.last()).map(|(first, last)| {
        (first.received_at_millis, last.received_at_millis)
    });
    let observed_seconds = window
        .map(|(first, last)| (last - first) as f64 / 1_000.0)
        .unwrap_or_default();

    let swap_api = swap_api_census(trades, window)?;

    let mut coins = Vec::new();
    for (mint, events) in &per_mint {
        coins.push(coin_report(mint, events, bucket_seconds, swap_api.get(mint))?);
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
            .then(|| inbound.len() as f64 / observed_seconds),
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
                               hypothesis, using only the one frame",
            "agreements": label_agreements,
            "disagreements": label_disagreements,
            "undecidable": label_undecidable,
            "medianFitError": median(&mut fit_errors),
        },
        "duplicateSignatures": signatures.values().filter(|count| **count > 1).count(),
        "distinctSignatures": signatures.len(),
        "bucketSeconds": bucket_seconds,
        "coins": coins,
    }))?)
}

/// The drawdown answer for one coin, at event resolution and at candle resolution.
fn coin_report(
    mint: &str,
    events: &[TradeEvent],
    bucket_seconds: u64,
    swap_api: Option<&SwapApiCensus>,
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
    // Arrival order is the tape's only order. It is checked rather than assumed.
    let out_of_order = events
        .windows(2)
        .filter(|pair| pair[1].sequence <= pair[0].sequence)
        .count();
    let tape_signatures: BTreeSet<&str> =
        events.iter().map(|event| event.signature.as_str()).collect();
    let overlap = swap_api.map(|census| {
        census
            .distinct_tx_in_window
            .iter()
            .filter(|tx| tape_signatures.contains(tx.as_str()))
            .count()
    });
    Ok(json!({
        "mint": mint,
        "events": events.len(),
        "buys": buys,
        "sells": events.len() - buys,
        "pools": pools,
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
        "distinctTapeSignatures": tape_signatures.len(),
        "swapApiComparison": swap_api.map(SwapApiCensus::render),
        "swapApiSignaturesAlsoOnTape": overlap,
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

fn median(values: &mut Vec<f64>) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    Some(values[values.len() / 2])
}

/// What the pump swap-api trade route said about the same mint over the same interval.
struct SwapApiCensus {
    rows: usize,
    rows_in_window: usize,
    distinct_tx_in_window: BTreeSet<String>,
    oldest_row_unix_ms: Option<i64>,
    newest_row_unix_ms: Option<i64>,
}

impl SwapApiCensus {
    fn render(&self) -> Value {
        json!({
            "rowsInPage": self.rows,
            "rowsWithinTapeWindow": self.rows_in_window,
            "distinctSignaturesWithinTapeWindow": self.distinct_tx_in_window.len(),
            "oldestRowUnixMs": self.oldest_row_unix_ms,
            "newestRowUnixMs": self.newest_row_unix_ms,
        })
    }
}

/// Read the exact retained body out of `joshi.pump_api.fetch_outcome.v1` envelopes.
///
/// The envelopes are read as artifacts rather than through the pump client, because this crate
/// deliberately does not depend on it. Only the retained bytes are consulted.
fn swap_api_census(
    paths: &[String],
    window: Option<(i64, i64)>,
) -> Result<BTreeMap<String, SwapApiCensus>, Box<dyn Error>> {
    use base64::Engine as _;
    let mut census = BTreeMap::new();
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
        let rows = body["trades"].as_array().cloned().unwrap_or_default();
        let mut mint = String::new();
        let mut in_window = 0_usize;
        let mut distinct = BTreeSet::new();
        let mut oldest = None;
        let mut newest = None;
        for row in &rows {
            if let Some(value) = row["mint"].as_str() {
                mint = value.to_owned();
            }
            let Some(timestamp) = row["timestamp"].as_i64() else {
                continue;
            };
            oldest = Some(oldest.map_or(timestamp, |value: i64| value.min(timestamp)));
            newest = Some(newest.map_or(timestamp, |value: i64| value.max(timestamp)));
            if let Some((lower, upper)) = window {
                if timestamp >= lower && timestamp <= upper {
                    in_window += 1;
                    if let Some(tx) = row["tx"].as_str() {
                        distinct.insert(tx.to_owned());
                    }
                }
            }
        }
        if mint.is_empty() {
            mint = format!("unnamed:{path}");
        }
        census.insert(
            mint,
            SwapApiCensus {
                rows: rows.len(),
                rows_in_window: in_window,
                distinct_tx_in_window: distinct,
                oldest_row_unix_ms: oldest,
                newest_row_unix_ms: newest,
            },
        );
    }
    Ok(census)
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
