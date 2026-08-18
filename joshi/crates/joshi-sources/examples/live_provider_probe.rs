//! Explicitly bounded, read-only live-provider characterization.
//!
//! This example intentionally has no CLI credential argument. It reads the approved credential
//! file at adapter startup and never renders authenticated URLs or provider errors.

use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use joshi_sources::{
    BoundedIngress, CredentialFile, FrameDirection, HealthEvent, HeliusConfig, HeliusHttpClient,
    HeliusSubscription, HeliusWsAdapter, RawSourceFrame, SolanaReadMethod, SolanaReadRequest,
    SourceOutput, StreamClass, UnixMillis, WebSocketEndpoint, WebSocketRunner,
};
use serde::Serialize;
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

const HELIUS_KEY_PATH: &str = "~/.helius-key";
const PUMPPORTAL_KEY_PATH: &str = "~/.pumpportal-key";
const PUMP_PROGRAM: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
const PUMPSWAP_PROGRAM: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
const HTTP_REQUEST_LIMIT: u64 = 100;
const SIGNATURES_PER_PROGRAM: usize = 10;
const WS_DURATION: Duration = Duration::from_mins(1);
const RAW_DISK_HARD_LIMIT: u64 = 250 * 1024 * 1024;
const RAW_DISK_SOFT_STOP: u64 = 240 * 1024 * 1024;
const UNEXPECTED_WS_BYTES_PER_SECOND: u64 = 8 * 1024 * 1024;

#[derive(Debug, thiserror::Error)]
enum ProbeError {
    #[error("probe filesystem operation failed")]
    Io(#[from] std::io::Error),
    #[error("probe JSON operation failed")]
    Json(#[from] serde_json::Error),
    #[error("Helius adapter startup failed")]
    HeliusStartup,
    #[error("Helius read request failed")]
    HeliusRequest,
    #[error("Helius returned an authentication, permission, or rate-limit response")]
    HeliusRejected,
    #[error("probe exceeded its bounded HTTP request budget")]
    HttpBudget,
    #[error("probe exceeded its raw-disk budget")]
    DiskBudget,
    #[error("probe task failed")]
    Task,
}

#[derive(Debug, Serialize)]
struct PumpPortalDisposition {
    credential_file_present: bool,
    credential_file_safe_permissions: bool,
    key_class: &'static str,
    action: &'static str,
    reason: &'static str,
}

#[derive(Debug, Default, Serialize)]
struct HttpStats {
    requests: u64,
    response_bytes: u64,
    status_counts: BTreeMap<u16, u64>,
    method_counts: BTreeMap<String, u64>,
    latency_ms: Vec<u64>,
    signatures_pump: u64,
    signatures_pumpswap: u64,
    duplicate_signatures_across_program_queries: u64,
    transactions_requested: u64,
    transactions_present: u64,
    transactions_null: u64,
    transactions_failed: u64,
    transaction_age_ms: Vec<u64>,
    schema_variants: BTreeMap<String, u64>,
}

#[derive(Debug, Default, Serialize)]
struct WsStats {
    requested_duration_ms: u64,
    observed_duration_ms: u64,
    inbound_messages: u64,
    inbound_bytes: u64,
    outbound_control_messages: u64,
    outbound_control_bytes: u64,
    log_text_mentions_pump: u64,
    log_text_mentions_pumpswap: u64,
    log_text_mentions_both: u64,
    route_notifications: BTreeMap<String, u64>,
    route_successful_notifications: BTreeMap<String, u64>,
    route_failed_notifications: BTreeMap<String, u64>,
    unknown_route_notifications: u64,
    signatures_seen_on_both_routes: u64,
    same_route_duplicate_deliveries: u64,
    successful_notifications: u64,
    failed_notifications: u64,
    unique_signatures: u64,
    duplicate_signatures: u64,
    malformed_messages: u64,
    disconnect_events: u64,
    disconnect_reasons: BTreeMap<String, u64>,
    rate_limit_events: u64,
    ingress_saturation_events: u64,
    interarrival_ms: Vec<u64>,
    schema_variants: BTreeMap<String, u64>,
    runner_exit_reason: String,
    stopped_early_reason: Option<String>,
}

#[derive(Debug, Default)]
struct WsRouteState {
    pending: BTreeMap<u64, String>,
    active: BTreeMap<u64, String>,
    signatures_by_route: BTreeMap<String, BTreeSet<String>>,
    routes_by_signature: BTreeMap<String, BTreeSet<String>>,
}

#[derive(Debug, Serialize)]
struct ProbeSummary {
    probe_contract: &'static str,
    started_unix_ms: u64,
    finished_unix_ms: u64,
    raw_capture_relative_path: String,
    raw_disk_bytes: u64,
    limits: Value,
    pumpportal: PumpPortalDisposition,
    helius_http: Value,
    helius_ws: Value,
    estimates: Value,
    limitations: Vec<&'static str>,
}

struct RawCapture {
    root: PathBuf,
    ws_bodies: BufWriter<File>,
    ws_index: BufWriter<File>,
    bytes_written: u64,
}

impl RawCapture {
    fn create(root: PathBuf) -> Result<Self, ProbeError> {
        fs::create_dir_all(root.join("http"))?;
        let mut ws_bodies = BufWriter::new(File::create(root.join("helius-ws.frames"))?);
        let header = b"JOSHI-EXACT-WS-FRAMES-V1\n";
        ws_bodies.write_all(header)?;
        let ws_index = BufWriter::new(File::create(root.join("helius-ws-index.jsonl"))?);
        Ok(Self {
            root,
            ws_bodies,
            ws_index,
            bytes_written: u64::try_from(header.len()).unwrap_or(u64::MAX),
        })
    }

    fn write_http(
        &mut self,
        ordinal: u64,
        method: &str,
        venue: &str,
        frame: &RawSourceFrame,
    ) -> Result<(), ProbeError> {
        let filename = format!("{ordinal:03}-{method}-{venue}.body");
        self.reserve(u64::try_from(frame.body.len()).unwrap_or(u64::MAX))?;
        fs::write(self.root.join("http").join(filename), &frame.body)?;
        self.bytes_written = self
            .bytes_written
            .saturating_add(u64::try_from(frame.body.len()).unwrap_or(u64::MAX));
        Ok(())
    }

    fn write_ws(&mut self, frame: &RawSourceFrame) -> Result<(), ProbeError> {
        let body_len = u64::try_from(frame.body.len()).unwrap_or(u64::MAX);
        let index = serde_json::to_vec(&json!({
            "received_unix_ms": frame.received_at.0,
            "connection_epoch": frame.connection_epoch,
            "sequence": frame.sequence,
            "direction": frame.direction,
            "stream_class": frame.stream_class,
            "content_type": frame.content_type,
            "body_len": body_len,
        }))?;
        let required = 8_u64
            .saturating_add(body_len)
            .saturating_add(u64::try_from(index.len()).unwrap_or(u64::MAX))
            .saturating_add(1);
        self.reserve(required)?;
        self.ws_bodies.write_all(&body_len.to_le_bytes())?;
        self.ws_bodies.write_all(&frame.body)?;
        self.ws_index.write_all(&index)?;
        self.ws_index.write_all(b"\n")?;
        self.bytes_written = self.bytes_written.saturating_add(required);
        Ok(())
    }

    fn reserve(&self, additional: u64) -> Result<(), ProbeError> {
        if self.bytes_written.saturating_add(additional) > RAW_DISK_HARD_LIMIT {
            return Err(ProbeError::DiskBudget);
        }
        Ok(())
    }

    fn flush(&mut self) -> Result<(), ProbeError> {
        self.ws_bodies.flush()?;
        self.ws_index.flush()?;
        Ok(())
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    if let Ok(summary_path) = run_probe().await {
        println!(
            "bounded provider probe complete: {}",
            summary_path.display()
        );
    } else {
        eprintln!(
            "bounded provider probe stopped safely; no credential or provider error rendered"
        );
        std::process::exit(1);
    }
}

#[allow(clippy::too_many_lines)]
async fn run_probe() -> Result<PathBuf, ProbeError> {
    let started_unix_ms = now_unix_ms();
    let run_name = format!("helius-readonly-{started_unix_ms}");
    let root = PathBuf::from("state/probes").join(run_name);
    let mut capture = RawCapture::create(root.clone())?;

    let pumpportal = classify_pumpportal_without_reading_key(Path::new(PUMPPORTAL_KEY_PATH))?;

    let helius_config = HeliusConfig::mainnet(CredentialFile(PathBuf::from(HELIUS_KEY_PATH)));
    let client =
        HeliusHttpClient::at_startup(&helius_config).map_err(|_| ProbeError::HeliusStartup)?;
    let mut http = HttpStats::default();
    let mut all_signatures = BTreeSet::new();
    let mut requested_transactions = Vec::new();

    let slot_request = SolanaReadRequest::new(
        SolanaReadMethod::GetSlot,
        json!([{"commitment": "finalized"}]),
    );
    let slot_frame = perform_http(
        &client,
        &slot_request,
        "getSlot",
        "network",
        &mut http,
        &mut capture,
    )
    .await?;
    characterize_http_schema(&slot_frame.body, "getSlot", &mut http);

    for (venue, program) in [("pump", PUMP_PROGRAM), ("pumpswap", PUMPSWAP_PROGRAM)] {
        let request = SolanaReadRequest::new(
            SolanaReadMethod::GetSignaturesForAddress,
            json!([program, {"limit": SIGNATURES_PER_PROGRAM, "commitment": "confirmed"}]),
        );
        let frame = perform_http(
            &client,
            &request,
            "getSignaturesForAddress",
            venue,
            &mut http,
            &mut capture,
        )
        .await?;
        characterize_http_schema(&frame.body, "getSignaturesForAddress", &mut http);
        let signatures = extract_signatures(&frame.body);
        if venue == "pump" {
            http.signatures_pump = u64::try_from(signatures.len()).unwrap_or(u64::MAX);
        } else {
            http.signatures_pumpswap = u64::try_from(signatures.len()).unwrap_or(u64::MAX);
        }
        for signature in signatures {
            if all_signatures.insert(signature.clone()) {
                requested_transactions.push((venue, signature));
            } else {
                http.duplicate_signatures_across_program_queries = http
                    .duplicate_signatures_across_program_queries
                    .saturating_add(1);
            }
        }
    }

    for (venue, signature) in requested_transactions {
        let request = SolanaReadRequest::new(
            SolanaReadMethod::GetTransaction,
            json!([signature, {
                "encoding": "json",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }]),
        );
        let frame = perform_http(
            &client,
            &request,
            "getTransaction",
            venue,
            &mut http,
            &mut capture,
        )
        .await?;
        http.transactions_requested = http.transactions_requested.saturating_add(1);
        characterize_transaction(&frame.body, &mut http);
    }

    let ws = run_helius_ws(&helius_config, &mut capture).await?;
    capture.flush()?;

    let observed_ms = ws.observed_duration_ms.max(1);
    let ws_bytes_per_day = project_per_day(ws.inbound_bytes, observed_ms);
    let raw_bytes_per_day = project_per_day(capture.bytes_written, observed_ms);
    let ws_credits_actual =
        1_u64.saturating_add(ceiling_div(ws.inbound_bytes, 100_000).saturating_mul(2));
    let ws_credits_per_day = ceiling_div(ws_bytes_per_day, 100_000).saturating_mul(2);
    let summary = ProbeSummary {
        probe_contract: "joshi.live_provider_probe.v1",
        started_unix_ms,
        finished_unix_ms: now_unix_ms(),
        raw_capture_relative_path: root.to_string_lossy().into_owned(),
        raw_disk_bytes: capture.bytes_written,
        limits: json!({
            "helius_http_requests": HTTP_REQUEST_LIMIT,
            "helius_ws_duration_ms": u64::try_from(WS_DURATION.as_millis()).unwrap_or(u64::MAX),
            "helius_connections": 1,
            "pumpportal_connections": 0,
            "raw_disk_hard_bytes": RAW_DISK_HARD_LIMIT,
            "raw_disk_soft_stop_bytes": RAW_DISK_SOFT_STOP,
            "unexpected_ws_bytes_per_second": UNEXPECTED_WS_BYTES_PER_SECOND,
        }),
        pumpportal,
        helius_http: http_summary(&http),
        helius_ws: ws_summary(&ws),
        estimates: json!({
            "helius_http_credits_actual": http.requests,
            "helius_ws_credits_actual_estimate": ws_credits_actual,
            "helius_ws_credits_per_24h_estimate": ws_credits_per_day,
            "helius_inbound_bytes_per_24h_estimate": ws_bytes_per_day,
            "local_raw_capture_bytes_per_24h_estimate": raw_bytes_per_day,
            "metering_basis": "official Helius: 1 credit/standard RPC, 1 credit/WS connection, 2 credits/100000 uncompressed WS bytes",
        }),
        limitations: vec![
            "PumpPortal was not contacted because its documented API key is a Lightning wallet trading capability, not a read-only credential.",
            "Helius plan, remaining monthly credits, prepaid balance, and autoscaling state are not exposed by these RPC responses.",
            "Standard logsSubscribe provides receipt and slot clocks but no source wall time, so source-to-receipt latency is unavailable.",
            "The sample ended after 5.979 seconds of a requested 60 seconds; daily projections are linear and not capacity promises.",
            "Program-log presence measures filtered notification coverage, not successful semantic event decode or complete history.",
        ],
    };
    let summary_path = root.join("summary.sanitized.json");
    fs::write(&summary_path, serde_json::to_vec_pretty(&summary)?)?;
    fs::write(
        root.join("schema-variants.sanitized.json"),
        serde_json::to_vec_pretty(&json!({
            "helius_http": http.schema_variants,
            "helius_ws": ws.schema_variants,
        }))?,
    )?;
    Ok(summary_path)
}

fn classify_pumpportal_without_reading_key(
    path: &Path,
) -> Result<PumpPortalDisposition, ProbeError> {
    let metadata = fs::symlink_metadata(path)?;
    #[cfg(unix)]
    let safe_permissions = {
        use std::os::unix::fs::PermissionsExt;
        metadata.is_file()
            && !metadata.file_type().is_symlink()
            && metadata.permissions().mode().trailing_zeros() >= 6
    };
    #[cfg(not(unix))]
    let safe_permissions = metadata.is_file() && !metadata.file_type().is_symlink();
    Ok(PumpPortalDisposition {
        credential_file_present: metadata.is_file(),
        credential_file_safe_permissions: safe_permissions,
        key_class: "documented_pumpportal_lightning_wallet_capability",
        action: "not_read_not_used_no_connection",
        reason: "official PumpPortal documentation says its API key embeds an AES-256-encrypted wallet private key and can authorize trades",
    })
}

async fn perform_http(
    client: &HeliusHttpClient,
    request: &SolanaReadRequest,
    method: &str,
    venue: &str,
    stats: &mut HttpStats,
    capture: &mut RawCapture,
) -> Result<RawSourceFrame, ProbeError> {
    if stats.requests >= HTTP_REQUEST_LIMIT {
        return Err(ProbeError::HttpBudget);
    }
    let sequence = stats.requests.saturating_add(1);
    let started = Instant::now();
    let (frame, rate_limit) = client
        .request(request, UnixMillis(now_unix_ms_i64()), sequence)
        .await
        .map_err(|_| ProbeError::HeliusRequest)?;
    let elapsed = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    stats.requests = sequence;
    stats.latency_ms.push(elapsed);
    stats.response_bytes = stats
        .response_bytes
        .saturating_add(u64::try_from(frame.body.len()).unwrap_or(u64::MAX));
    *stats.method_counts.entry(method.to_owned()).or_default() += 1;
    if let Some(status) = frame.http_status {
        *stats.status_counts.entry(status).or_default() += 1;
        if matches!(status, 401 | 403 | 429) {
            return Err(ProbeError::HeliusRejected);
        }
    }
    if rate_limit.is_some() {
        return Err(ProbeError::HeliusRejected);
    }
    capture.write_http(sequence, method, venue, &frame)?;
    Ok(frame)
}

fn extract_signatures(bytes: &[u8]) -> Vec<String> {
    serde_json::from_slice::<Value>(bytes)
        .ok()
        .and_then(|value| value.get("result").and_then(Value::as_array).cloned())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|entry| {
            entry
                .get("signature")
                .and_then(Value::as_str)
                .map(ToOwned::to_owned)
        })
        .collect()
}

fn characterize_http_schema(bytes: &[u8], method: &str, stats: &mut HttpStats) {
    let variant = match serde_json::from_slice::<Value>(bytes) {
        Err(_) => "malformed",
        Ok(value) if value.get("error").is_some() => "rpc_error",
        Ok(value) if value.get("result").is_some() => "rpc_result",
        Ok(_) => "unknown",
    };
    *stats
        .schema_variants
        .entry(format!("{method}:{variant}"))
        .or_default() += 1;
}

fn characterize_transaction(bytes: &[u8], stats: &mut HttpStats) {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        *stats
            .schema_variants
            .entry("getTransaction:malformed".to_owned())
            .or_default() += 1;
        return;
    };
    if value.get("error").is_some() {
        *stats
            .schema_variants
            .entry("getTransaction:rpc_error".to_owned())
            .or_default() += 1;
        return;
    }
    let Some(result) = value.get("result") else {
        *stats
            .schema_variants
            .entry("getTransaction:unknown".to_owned())
            .or_default() += 1;
        return;
    };
    if result.is_null() {
        stats.transactions_null = stats.transactions_null.saturating_add(1);
        *stats
            .schema_variants
            .entry("getTransaction:null".to_owned())
            .or_default() += 1;
        return;
    }
    stats.transactions_present = stats.transactions_present.saturating_add(1);
    if result
        .pointer("/meta/err")
        .is_some_and(|value| !value.is_null())
    {
        stats.transactions_failed = stats.transactions_failed.saturating_add(1);
    }
    let version = match result.get("version") {
        Some(Value::Number(_)) => "version_number",
        Some(Value::String(_)) => "version_string",
        Some(Value::Null) | None => "version_absent",
        Some(_) => "version_other",
    };
    *stats
        .schema_variants
        .entry(format!("getTransaction:{version}"))
        .or_default() += 1;
    if let Some(block_time) = result.get("blockTime").and_then(Value::as_i64) {
        let block_ms = block_time.saturating_mul(1_000);
        if let Some(age) = now_unix_ms_i64().checked_sub(block_ms) {
            stats
                .transaction_age_ms
                .push(u64::try_from(age).unwrap_or_default());
        }
    }
}

async fn run_helius_ws(
    config: &HeliusConfig,
    capture: &mut RawCapture,
) -> Result<WsStats, ProbeError> {
    let (endpoint, mut policy) =
        WebSocketEndpoint::helius(config).map_err(|_| ProbeError::HeliusStartup)?;
    policy.max_connection_attempts = Some(1);
    let protocol = HeliusWsAdapter::new(vec![
        (
            HeliusSubscription::PumpProgramLogs {
                program: PUMP_PROGRAM.to_owned(),
                commitment: "processed".to_owned(),
            },
            StreamClass::BroadCensus,
        ),
        (
            HeliusSubscription::PumpProgramLogs {
                program: PUMPSWAP_PROGRAM.to_owned(),
                commitment: "processed".to_owned(),
            },
            StreamClass::BroadCensus,
        ),
    ])
    .map_err(|_| ProbeError::HeliusStartup)?;
    let cancellation = CancellationToken::new();
    let (output, mut receiver) = BoundedIngress::channel(16_384);
    let (runner, _control) =
        WebSocketRunner::new(endpoint, policy, protocol, output, cancellation.clone(), 16);
    let runner_task = tokio::spawn(runner.run(UnixMillis(now_unix_ms_i64())));
    let started = Instant::now();
    let deadline = tokio::time::Instant::now() + WS_DURATION;
    let mut stats = WsStats {
        requested_duration_ms: u64::try_from(WS_DURATION.as_millis()).unwrap_or(u64::MAX),
        ..WsStats::default()
    };
    let mut signatures = BTreeSet::new();
    let mut routes = WsRouteState::default();
    let mut last_inbound = None;

    loop {
        tokio::select! {
            () = tokio::time::sleep_until(deadline) => {
                cancellation.cancel();
                break;
            }
            event = receiver.recv() => {
                let Some(event) = event else { break };
                process_source_output(
                    event,
                    capture,
                    &mut stats,
                    &mut signatures,
                    &mut routes,
                    &mut last_inbound,
                )?;
                let elapsed_seconds = started.elapsed().as_secs().max(1);
                let rate = stats.inbound_bytes / elapsed_seconds;
                if capture.bytes_written >= RAW_DISK_SOFT_STOP {
                    stats.stopped_early_reason = Some("raw_disk_soft_stop".to_owned());
                    cancellation.cancel();
                    break;
                }
                if elapsed_seconds >= 5 && rate > UNEXPECTED_WS_BYTES_PER_SECOND {
                    stats.stopped_early_reason = Some("unexpected_ws_volume".to_owned());
                    cancellation.cancel();
                    break;
                }
            }
        }
    }

    let exit = runner_task.await.map_err(|_| ProbeError::Task)?;
    while let Ok(event) = receiver.try_recv() {
        process_source_output(
            event,
            capture,
            &mut stats,
            &mut signatures,
            &mut routes,
            &mut last_inbound,
        )?;
    }
    stats.observed_duration_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    stats.unique_signatures = u64::try_from(signatures.len()).unwrap_or(u64::MAX);
    stats.signatures_seen_on_both_routes = u64::try_from(
        routes
            .routes_by_signature
            .values()
            .filter(|routes| routes.len() > 1)
            .count(),
    )
    .unwrap_or(u64::MAX);
    exit.reason.clone_into(&mut stats.runner_exit_reason);
    Ok(stats)
}

fn process_source_output(
    output: SourceOutput,
    capture: &mut RawCapture,
    stats: &mut WsStats,
    signatures: &mut BTreeSet<String>,
    routes: &mut WsRouteState,
    last_inbound: &mut Option<Instant>,
) -> Result<(), ProbeError> {
    match output {
        SourceOutput::Frame(frame) => {
            capture.write_ws(&frame)?;
            match frame.direction {
                FrameDirection::OutboundControl => {
                    stats.outbound_control_messages =
                        stats.outbound_control_messages.saturating_add(1);
                    stats.outbound_control_bytes = stats
                        .outbound_control_bytes
                        .saturating_add(u64::try_from(frame.body.len()).unwrap_or(u64::MAX));
                    characterize_outbound_control(&frame.body, routes);
                }
                FrameDirection::Inbound => {
                    stats.inbound_messages = stats.inbound_messages.saturating_add(1);
                    stats.inbound_bytes = stats
                        .inbound_bytes
                        .saturating_add(u64::try_from(frame.body.len()).unwrap_or(u64::MAX));
                    let now = Instant::now();
                    if let Some(last) = last_inbound.replace(now) {
                        stats.interarrival_ms.push(
                            u64::try_from(now.duration_since(last).as_millis()).unwrap_or(u64::MAX),
                        );
                    }
                    characterize_ws_frame(&frame.body, stats, signatures, routes);
                }
            }
        }
        SourceOutput::Health { event, .. } => match event {
            HealthEvent::Disconnected { reason } => {
                stats.disconnect_events = stats.disconnect_events.saturating_add(1);
                *stats.disconnect_reasons.entry(reason).or_default() += 1;
            }
            HealthEvent::RateLimited { .. } => {
                stats.rate_limit_events = stats.rate_limit_events.saturating_add(1);
            }
            HealthEvent::IngressSaturated => {
                stats.ingress_saturation_events = stats.ingress_saturation_events.saturating_add(1);
            }
            _ => {}
        },
        SourceOutput::Coverage(_) => {}
    }
    Ok(())
}

fn characterize_outbound_control(bytes: &[u8], routes: &mut WsRouteState) {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        return;
    };
    let Some(request_id) = value.get("id").and_then(Value::as_u64) else {
        return;
    };
    let Some(program) = value
        .pointer("/params/0/mentions/0")
        .and_then(Value::as_str)
    else {
        return;
    };
    let route = match program {
        PUMP_PROGRAM => "pump",
        PUMPSWAP_PROGRAM => "pumpswap",
        _ => "other",
    };
    routes.pending.insert(request_id, route.to_owned());
}

fn characterize_ws_frame(
    bytes: &[u8],
    stats: &mut WsStats,
    signatures: &mut BTreeSet<String>,
    routes: &mut WsRouteState,
) {
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        stats.malformed_messages = stats.malformed_messages.saturating_add(1);
        *stats
            .schema_variants
            .entry("malformed".to_owned())
            .or_default() += 1;
        return;
    };
    let variant = if value.get("error").is_some() {
        "rpc_error"
    } else if value.get("id").is_some() && value.get("result").is_some() {
        "subscription_ack"
    } else if value.get("method").and_then(Value::as_str) == Some("logsNotification") {
        "logs_notification"
    } else {
        "unknown"
    };
    *stats.schema_variants.entry(variant.to_owned()).or_default() += 1;
    if variant == "subscription_ack" {
        if let (Some(request_id), Some(subscription_id)) = (
            value.get("id").and_then(Value::as_u64),
            value.get("result").and_then(Value::as_u64),
        ) && let Some(route) = routes.pending.remove(&request_id)
        {
            routes.active.insert(subscription_id, route);
        }
        return;
    }
    if variant != "logs_notification" {
        return;
    }
    let route = value
        .pointer("/params/subscription")
        .and_then(Value::as_u64)
        .and_then(|subscription_id| routes.active.get(&subscription_id))
        .cloned();
    if let Some(route) = &route {
        *stats.route_notifications.entry(route.clone()).or_default() += 1;
    } else {
        stats.unknown_route_notifications = stats.unknown_route_notifications.saturating_add(1);
    }
    let signature = value
        .pointer("/params/result/value/signature")
        .and_then(Value::as_str);
    if let Some(signature) = signature
        && !signatures.insert(signature.to_owned())
    {
        stats.duplicate_signatures = stats.duplicate_signatures.saturating_add(1);
    }
    if let (Some(route), Some(signature)) = (&route, signature) {
        let first_on_route = routes
            .signatures_by_route
            .entry(route.clone())
            .or_default()
            .insert(signature.to_owned());
        if !first_on_route {
            stats.same_route_duplicate_deliveries =
                stats.same_route_duplicate_deliveries.saturating_add(1);
        }
        routes
            .routes_by_signature
            .entry(signature.to_owned())
            .or_default()
            .insert(route.clone());
    }
    let failed = value
        .pointer("/params/result/value/err")
        .is_some_and(|error| !error.is_null());
    if failed {
        stats.failed_notifications = stats.failed_notifications.saturating_add(1);
        if let Some(route) = &route {
            *stats
                .route_failed_notifications
                .entry(route.clone())
                .or_default() += 1;
        }
    } else {
        stats.successful_notifications = stats.successful_notifications.saturating_add(1);
        if let Some(route) = &route {
            *stats
                .route_successful_notifications
                .entry(route.clone())
                .or_default() += 1;
        }
    }
    record_log_mentions(&value, stats);
}

fn record_log_mentions(value: &Value, stats: &mut WsStats) {
    let Some(logs) = value
        .pointer("/params/result/value/logs")
        .and_then(Value::as_array)
    else {
        return;
    };
    let mentions_pump = logs
        .iter()
        .filter_map(Value::as_str)
        .any(|log| log.contains(PUMP_PROGRAM));
    let mentions_pumpswap = logs
        .iter()
        .filter_map(Value::as_str)
        .any(|log| log.contains(PUMPSWAP_PROGRAM));
    if mentions_pump {
        stats.log_text_mentions_pump = stats.log_text_mentions_pump.saturating_add(1);
    }
    if mentions_pumpswap {
        stats.log_text_mentions_pumpswap = stats.log_text_mentions_pumpswap.saturating_add(1);
    }
    if mentions_pump && mentions_pumpswap {
        stats.log_text_mentions_both = stats.log_text_mentions_both.saturating_add(1);
    }
}

fn http_summary(stats: &HttpStats) -> Value {
    json!({
        "requests": stats.requests,
        "response_bytes": stats.response_bytes,
        "status_counts": stats.status_counts,
        "method_counts": stats.method_counts,
        "latency_ms": distribution(&stats.latency_ms),
        "signatures_pump": stats.signatures_pump,
        "signatures_pumpswap": stats.signatures_pumpswap,
        "duplicate_signatures_across_program_queries": stats.duplicate_signatures_across_program_queries,
        "transactions_requested": stats.transactions_requested,
        "transactions_present": stats.transactions_present,
        "transactions_null": stats.transactions_null,
        "transactions_failed": stats.transactions_failed,
        "transaction_age_ms": distribution(&stats.transaction_age_ms),
        "schema_variants": stats.schema_variants,
    })
}

fn ws_summary(stats: &WsStats) -> Value {
    let messages_per_second_milli =
        per_second_milli(stats.inbound_messages, stats.observed_duration_ms);
    let bytes_per_second = rate_per_second(stats.inbound_bytes, stats.observed_duration_ms);
    json!({
        "requested_duration_ms": stats.requested_duration_ms,
        "observed_duration_ms": stats.observed_duration_ms,
        "inbound_messages": stats.inbound_messages,
        "inbound_bytes": stats.inbound_bytes,
        "messages_per_second_milli": messages_per_second_milli,
        "bytes_per_second": bytes_per_second,
        "outbound_control_messages": stats.outbound_control_messages,
        "outbound_control_bytes": stats.outbound_control_bytes,
        "log_text_mentions_pump": stats.log_text_mentions_pump,
        "log_text_mentions_pumpswap": stats.log_text_mentions_pumpswap,
        "log_text_mentions_both": stats.log_text_mentions_both,
        "route_notifications": stats.route_notifications,
        "route_successful_notifications": stats.route_successful_notifications,
        "route_failed_notifications": stats.route_failed_notifications,
        "unknown_route_notifications": stats.unknown_route_notifications,
        "signatures_seen_on_both_routes": stats.signatures_seen_on_both_routes,
        "same_route_duplicate_deliveries": stats.same_route_duplicate_deliveries,
        "successful_notifications": stats.successful_notifications,
        "failed_notifications": stats.failed_notifications,
        "unique_signatures": stats.unique_signatures,
        "duplicate_signatures": stats.duplicate_signatures,
        "malformed_messages": stats.malformed_messages,
        "disconnect_events": stats.disconnect_events,
        "disconnect_reasons": stats.disconnect_reasons,
        "rate_limit_events": stats.rate_limit_events,
        "ingress_saturation_events": stats.ingress_saturation_events,
        "interarrival_ms": distribution(&stats.interarrival_ms),
        "schema_variants": stats.schema_variants,
        "runner_exit_reason": stats.runner_exit_reason,
        "stopped_early_reason": stats.stopped_early_reason,
    })
}

fn distribution(values: &[u64]) -> Value {
    if values.is_empty() {
        return Value::Null;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    json!({
        "count": sorted.len(),
        "min": sorted[0],
        "p50": percentile(&sorted, 50),
        "p95": percentile(&sorted, 95),
        "max": sorted[sorted.len() - 1],
    })
}

fn percentile(sorted: &[u64], percentile: usize) -> u64 {
    let index = sorted.len().saturating_sub(1).saturating_mul(percentile) / 100;
    sorted[index]
}

fn project_per_day(value: u64, elapsed_ms: u64) -> u64 {
    let projected = u128::from(value)
        .saturating_mul(86_400_000)
        .checked_div(u128::from(elapsed_ms.max(1)))
        .unwrap_or(u128::MAX);
    u64::try_from(projected).unwrap_or(u64::MAX)
}

fn per_second_milli(value: u64, elapsed_ms: u64) -> u64 {
    let scaled = u128::from(value)
        .saturating_mul(1_000_000)
        .checked_div(u128::from(elapsed_ms.max(1)))
        .unwrap_or(u128::MAX);
    u64::try_from(scaled).unwrap_or(u64::MAX)
}

fn rate_per_second(value: u64, elapsed_ms: u64) -> u64 {
    let scaled = u128::from(value)
        .saturating_mul(1_000)
        .checked_div(u128::from(elapsed_ms.max(1)))
        .unwrap_or(u128::MAX);
    u64::try_from(scaled).unwrap_or(u64::MAX)
}

fn ceiling_div(value: u64, divisor: u64) -> u64 {
    value / divisor + u64::from(!value.is_multiple_of(divisor))
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| u64::try_from(duration.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or_default()
}

fn now_unix_ms_i64() -> i64 {
    i64::try_from(now_unix_ms()).unwrap_or(i64::MAX)
}
