//! Live authenticated Solana reads joined to the one durable catalog boundary.
//!
//! This module owns the only network path in the collector. The Helius credential is read exactly
//! once, while constructing the adapter, is never rendered, and is never written anywhere. Every
//! retained observation is the exact provider response body inside the shared retained-frame
//! envelope; nothing here reserializes, summarizes, or interprets a provider payload.

use std::{
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use joshi_admission::{PublicStoreReceiptV1, SourceFrameInput, source_frames};
use joshi_domain::{OpenVariant, StableString, UtcTimestamp};
use joshi_sources::{
    CredentialFile, EvidenceContext, HeliusConfig, HeliusHttpClient, LogicalSourceLocator,
    ProviderEventTime, RateLimitSignal, RawSourceFrame, RetainedFrameEnvelope, SolanaReadMethod,
    SolanaReadRequest, UnixMillis,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use rusqlite::{Connection, OpenFlags, OptionalExtension as _};
use serde_json::{Value, json};
use time::OffsetDateTime;

/// Default owner-only credential file. Never rendered, never copied, never logged.
pub(crate) const DEFAULT_HELIUS_KEY_PATH: &str = "~/.helius-key";

const LIVE_INGEST_RECEIPT_CONTRACT: &str = "joshi.collector.live_ingest_receipt.v1";
const LIVE_READBACK_CONTRACT: &str = "joshi.collector.live_readback.v1";
const CATALOG_ID: &str = "joshi-collector-live";
pub(crate) const INLINE_BLOB_MAX_BYTES: u64 = 4 * 1024 * 1024;
const MAX_OBSERVATIONS_PER_BATCH: usize = 64;
const MAX_RAW_BYTES_PER_BATCH: u64 = 64 * 1024 * 1024;
const BUSY_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_SIGNATURE_LIMIT: u32 = 1_000;
const PREVIEW_CHARS: usize = 160;

/// Every argument of one bounded live ingest occurrence.
#[derive(Debug)]
pub(crate) struct LiveIngestOptions {
    pub(crate) root: PathBuf,
    pub(crate) wallet: String,
    pub(crate) limit: u32,
    pub(crate) max_requests: u32,
    pub(crate) transactions: u32,
    pub(crate) key_file: PathBuf,
}

/// One completed provider read: the exact frame plus the local clocks that bracket it.
pub(crate) struct CapturedRead {
    pub(crate) frame: RawSourceFrame,
    pub(crate) method: SolanaReadMethod,
    pub(crate) fingerprint_material: String,
    pub(crate) started_at_millis: i64,
    pub(crate) started_mono_ns: u64,
    pub(crate) received_mono_ns: u64,
    pub(crate) rate_limit: Option<RateLimitSignal>,
    /// Source-native cursor text observed alongside this record; never cursor authority.
    pub(crate) source_cursor: Option<String>,
}

/// A hard request ceiling. Exhaustion is an error, never a silent truncation of a planned read.
pub(crate) struct ReadBudget {
    limit: u32,
    used: u32,
}

impl ReadBudget {
    pub(crate) const fn new(limit: u32) -> Self {
        Self { limit, used: 0 }
    }

    pub(crate) const fn remaining(&self) -> u32 {
        self.limit.saturating_sub(self.used)
    }

    pub(crate) fn claim(&mut self) -> Result<(), Box<dyn Error>> {
        if self.used >= self.limit {
            return Err(format!(
                "live ingest exhausted its hard budget of {} provider requests",
                self.limit
            )
            .into());
        }
        self.used += 1;
        Ok(())
    }
}

/// Perform the bounded live read sequence and commit it through the shared admission path.
///
/// # Errors
///
/// Returns a sanitized error for an invalid argument, an unreadable credential, a rejected or
/// failed provider read, or any durable-store or admission failure. No error carries the
/// authenticated endpoint or the credential.
pub(crate) fn ingest_live(options: &LiveIngestOptions) -> Result<String, Box<dyn Error>> {
    validate_wallet(&options.wallet)?;
    if options.limit == 0 || options.limit > MAX_SIGNATURE_LIMIT {
        return Err(format!("--limit must be between 1 and {MAX_SIGNATURE_LIMIT}").into());
    }
    if options.max_requests < 2 {
        return Err("--max-requests must allow at least the slot and signature reads".into());
    }

    let process_start = Instant::now();
    let namespace = run_namespace()?;
    let clock_id = format!("joshi-collector-live-{}", std::process::id());

    // Take the writer lease and reach the current schema before opening a network connection: a
    // read we cannot durably retain is not evidence, and failing first costs the provider nothing.
    let mut store = open_catalog(&options.root, StoreMode::SingleWriter)?;
    let migration = store.migrate(now_utc()?)?;

    let helius = HeliusConfig::mainnet(CredentialFile(options.key_file.clone()));
    // The client is constructed with the ceiling every response it reads is abandoned at. This
    // collector's sink is the SQLite catalog rather than the supervisor's local spool, so the
    // bound that belongs here is the catalog's own inline-blob boundary: a response longer than
    // this could not be retained as one inline payload, and reading it is work spent on bytes
    // there is nowhere to put. Before this ceiling existed the read was unbounded, and an
    // unbounded parse of hostile input was measured in this repository at 294 MB peak RSS.
    let client = HeliusHttpClient::at_startup(&helius, INLINE_BLOB_MAX_BYTES)?;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let (reads, requests_used) =
        runtime.block_on(perform_reads(&client, options, process_start))?;
    drop(runtime);
    drop(client);

    let response_bytes: u64 = reads
        .iter()
        .map(|read| u64::try_from(read.frame.body.len()).unwrap_or(u64::MAX))
        .sum();
    let receipt = commit_reads(&mut store, &reads, &namespace, &clock_id, process_start)?;

    let rendered = json!({
        "contract": LIVE_INGEST_RECEIPT_CONTRACT,
        "catalogRoot": options.root.display().to_string(),
        "catalogSchema": receipt.catalog_schema,
        "appliedMigrations": migration.applied.len(),
        "occurrenceNamespace": namespace,
        "batchId": receipt.batch_id,
        "commitSeq": receipt.commit_seq,
        "status": receipt.status,
        "observations": receipt.admitted.observations,
        "acquisitions": receipt.admitted.acquisitions,
        "rawBlobs": receipt.admitted.raw_blobs,
        "retainedPayloadBytes": receipt.admitted.raw_bytes,
        "providerRequests": requests_used,
        "providerRequestBudget": options.max_requests,
        "providerBudgetExhausted": requests_used >= options.max_requests,
        "providerResponseBytes": response_bytes,
        "storeAdmissionDigest": receipt.store_admission_digest,
        "batchDigest": receipt.batch_digest,
        "acquisitionIds": receipt.acquisition_ids,
        "reads": reads.iter().map(read_summary).collect::<Vec<_>>(),
    });
    Ok(serde_json::to_string_pretty(&rendered)?)
}

/// Reopen an existing catalog read-only and prove one retained observation payload byte-for-byte.
///
/// # Errors
///
/// Returns an error when the catalog is absent, is not a Joshi catalog, holds no observation, or
/// when a retained external payload cannot be read back.
pub(crate) fn store_readback(root: &Path) -> Result<String, Box<dyn Error>> {
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
    let observations: i64 =
        connection.query_row("SELECT COUNT(*) FROM observation", [], |row| row.get(0))?;
    let acquisitions: i64 =
        connection.query_row("SELECT COUNT(*) FROM acquisition", [], |row| row.get(0))?;
    let commits: i64 =
        connection.query_row("SELECT COUNT(*) FROM ingest_commit", [], |row| row.get(0))?;
    let first = connection
        .query_row(
            "SELECT o.observation_id, o.source_id, o.commit_seq, o.received_wall_us,
                    b.storage_mode, b.content_length, b.inline_bytes, b.relative_path
             FROM observation o JOIN blob b ON b.blob_id = o.blob_id
             ORDER BY o.commit_seq, o.intra_commit_seq LIMIT 1",
            [],
            |row| {
                Ok(StoredObservationRow {
                    observation_id: row.get(0)?,
                    source_id: row.get(1)?,
                    commit_seq: row.get(2)?,
                    received_wall_us: row.get(3)?,
                    storage_mode: row.get(4)?,
                    content_length: row.get(5)?,
                    inline_bytes: row.get(6)?,
                    relative_path: row.get(7)?,
                })
            },
        )
        .optional()?;
    let Some(row) = first else {
        return Err("catalog holds no observation to read back".into());
    };
    let payload = retained_payload(
        &config,
        row.inline_bytes.as_ref(),
        row.relative_path.as_deref(),
    )?;
    let envelope: RetainedFrameEnvelope = serde_json::from_slice(&payload)?;
    let rendered = json!({
        "contract": LIVE_READBACK_CONTRACT,
        "catalogRoot": root.display().to_string(),
        "catalogSchema": schema.as_str(),
        "ingestCommits": commits,
        "acquisitionCount": acquisitions,
        "observationCount": observations,
        "firstObservation": {
            "observationId": row.observation_id,
            "sourceId": row.source_id,
            "commitSeq": row.commit_seq,
            "receivedWallMicros": row.received_wall_us,
            "storageMode": row.storage_mode,
            "retainedPayloadBytes": row.content_length,
            "readBackPayloadBytes": payload.len(),
            "envelopeVersion": envelope.envelope_version,
            "adapterContractVersion": envelope.adapter_contract_version,
            "httpStatus": envelope.http_status,
            "providerBodyBytes": envelope.body.len(),
            "providerBodyPreview": preview(&envelope.body),
        },
    });
    Ok(serde_json::to_string_pretty(&rendered)?)
}

pub(crate) struct StoredObservationRow {
    pub(crate) observation_id: String,
    pub(crate) source_id: String,
    pub(crate) commit_seq: i64,
    pub(crate) received_wall_us: i64,
    pub(crate) storage_mode: String,
    pub(crate) content_length: i64,
    pub(crate) inline_bytes: Option<Vec<u8>>,
    pub(crate) relative_path: Option<String>,
}

/// Read one retained blob back from wherever the catalog physically put it.
pub(crate) fn retained_payload(
    config: &StoreConfig,
    inline_bytes: Option<&Vec<u8>>,
    relative_path: Option<&str>,
) -> Result<Vec<u8>, Box<dyn Error>> {
    match (inline_bytes, relative_path) {
        (Some(bytes), _) => Ok(bytes.clone()),
        (None, Some(relative)) => {
            let path = config.blob_root.join(relative);
            Ok(fs::read(path)?)
        }
        (None, None) => Err("retained blob row names neither inline bytes nor a path".into()),
    }
}

fn preview(body: &[u8]) -> String {
    String::from_utf8_lossy(body)
        .chars()
        .filter(|value| !value.is_control())
        .take(PREVIEW_CHARS)
        .collect()
}

async fn perform_reads(
    client: &HeliusHttpClient,
    options: &LiveIngestOptions,
    process_start: Instant,
) -> Result<(Vec<CapturedRead>, u32), Box<dyn Error>> {
    let mut budget = ReadBudget::new(options.max_requests);
    let mut reads: Vec<CapturedRead> = Vec::new();
    let mut sequence = 0_u64;

    sequence += 1;
    let slot = perform_one(
        client,
        &mut budget,
        sequence,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetSlot,
            json!([{ "commitment": "finalized" }]),
        ),
        "method=getSlot;commitment=finalized".to_owned(),
    )
    .await?;
    ensure_provider_accepted(&slot)?;
    reads.push(slot);

    sequence += 1;
    let signatures = perform_one(
        client,
        &mut budget,
        sequence,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetSignaturesForAddress,
            json!([options.wallet, { "limit": options.limit, "commitment": "finalized" }]),
        ),
        format!(
            "method=getSignaturesForAddress;address={};limit={};commitment=finalized",
            options.wallet, options.limit
        ),
    )
    .await?;
    ensure_provider_accepted(&signatures)?;
    let wanted = usize::try_from(options.transactions).unwrap_or(usize::MAX);
    let selected = first_signatures(&signatures.frame, wanted);
    reads.push(signatures);

    for signature in selected {
        if budget.remaining() == 0 {
            break;
        }
        sequence += 1;
        let transaction = perform_one(
            client,
            &mut budget,
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
        ensure_provider_accepted(&transaction)?;
        let throttled = transaction.rate_limit.is_some();
        reads.push(transaction);
        // A rate-limit signal ends the run. Retrying a throttled provider in a loop is exactly
        // the behavior the bounded budget exists to prevent.
        if throttled {
            break;
        }
    }
    let used = budget.used;
    Ok((reads, used))
}

pub(crate) async fn perform_one(
    client: &HeliusHttpClient,
    budget: &mut ReadBudget,
    sequence: u64,
    process_start: Instant,
    request: &SolanaReadRequest,
    fingerprint_material: String,
) -> Result<CapturedRead, Box<dyn Error>> {
    budget.claim()?;
    let method = request.method;
    let started = OffsetDateTime::now_utc();
    let started_at_millis = unix_millis(started)?;
    let started_mono_ns = elapsed_nanos(process_start)?;
    // The adapter stamps `received_at` from the value supplied before the await, so the exact
    // response arrival is restamped here rather than reported as the request-issue instant.
    let (mut frame, rate_limit) = client
        .request(request, UnixMillis(started_at_millis), sequence)
        .await?;
    let received_mono_ns = elapsed_nanos(process_start)?;
    frame.received_at = UnixMillis(unix_millis(OffsetDateTime::now_utc())?);
    Ok(CapturedRead {
        frame,
        method,
        fingerprint_material,
        started_at_millis,
        started_mono_ns,
        received_mono_ns,
        rate_limit,
        source_cursor: None,
    })
}

pub(crate) fn commit_reads(
    store: &mut SqliteStore,
    reads: &[CapturedRead],
    namespace: &str,
    clock_id: &str,
    process_start: Instant,
) -> Result<PublicStoreReceiptV1, Box<dyn Error>> {
    if reads.is_empty() {
        return Err("live ingest produced no frame to commit".into());
    }
    let persisted_at = now_utc()?;
    let frames = reads
        .iter()
        .map(|read| {
            Ok(SourceFrameInput {
                frame: read.frame.clone(),
                context: evidence_context(read, namespace, clock_id, persisted_at)?,
            })
        })
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?;
    // No source event and no cursor advance: this run can name no natural key it did not invent,
    // and an observed slot is not an authority to advance a durable cursor.
    let batch = source_frames(
        frames,
        Vec::new(),
        Vec::new(),
        StableString::new(format!("batch-{namespace}"))?,
        now_utc()?,
        StableString::new(clock_id)?,
        elapsed_nanos(process_start)?,
    )?;
    Ok(batch.commit(store)?)
}

pub(crate) fn evidence_context(
    read: &CapturedRead,
    namespace: &str,
    clock_id: &str,
    persisted_at: UtcTimestamp,
) -> Result<EvidenceContext, Box<dyn Error>> {
    let parsed = serde_json::from_slice::<Value>(&read.frame.body).ok();
    let (provider_event_time, chain_slot) = event_time_and_location(read.method, parsed.as_ref())?;
    Ok(EvidenceContext {
        occurrence_namespace: namespace.to_owned(),
        redacted_request_fingerprint_material: read.fingerprint_material.clone(),
        // Intra-batch parent links are deliberately absent: the catalog inserts acquisitions in
        // lexicographic identity order under immediate foreign keys, and the sequence-numbered
        // identity scheme does not guarantee a parent sorts before its children.
        parent_acquisition_id: None,
        locator: LogicalSourceLocator::HeliusHttp {
            method: read.method.as_str(),
        },
        source_variant: OpenVariant::known(format!(
            "solana_rpc_response:{}",
            read.method.as_str()
        ))?,
        source_cursor: read.source_cursor.clone(),
        source_events: Vec::new(),
        provider_event_time,
        chain_slot,
        transaction_index: None,
        instruction_path: Vec::new(),
        log_index: None,
        // The finalized commitment is a property of the request. No response body restates it, so
        // no commitment is asserted about the retained observation.
        finality: None,
        acquisition_started_at: utc_from_millis(read.started_at_millis)?,
        requested_at: Some(utc_from_millis(read.started_at_millis)?),
        monotonic_clock_id: clock_id.to_owned(),
        acquisition_started_monotonic_ns: read.started_mono_ns,
        received_monotonic_ns: read.received_mono_ns,
        persisted_at,
    })
}

/// Read the provider clock and chain location only where the payload genuinely carries them.
fn event_time_and_location(
    method: SolanaReadMethod,
    parsed: Option<&Value>,
) -> Result<(ProviderEventTime, Option<u64>), Box<dyn Error>> {
    let missing = |reason: &str| ProviderEventTime::Missing {
        reason: reason.to_owned(),
    };
    match method {
        SolanaReadMethod::GetTransaction => {
            let slot = parsed
                .and_then(|value| value.pointer("/result/slot"))
                .and_then(Value::as_u64);
            let Some(seconds) = parsed
                .and_then(|value| value.pointer("/result/blockTime"))
                .and_then(Value::as_i64)
            else {
                return Ok((
                    missing("getTransaction result carries no blockTime for this signature"),
                    slot,
                ));
            };
            // `blockTime` is stated by the provider at whole-second granularity, so the retained
            // interval is the second it names and nothing narrower.
            let lower = OffsetDateTime::from_unix_timestamp(seconds)
                .map_err(|_| "provider blockTime is outside the supported range")?;
            let upper = lower
                .checked_add(time::Duration::seconds(1))
                .ok_or("provider blockTime interval overflowed")?;
            Ok((
                ProviderEventTime::Bounded {
                    lower: UtcTimestamp::new(lower)?,
                    upper: UtcTimestamp::new(upper)?,
                    precision_us: 1_000_000,
                },
                slot,
            ))
        }
        // A scalar tip slot names the node's position, not the chain location of this response,
        // and a signature page spans many slots. Neither is a location of the retained frame.
        SolanaReadMethod::GetSlot => Ok((
            missing("getSlot response carries no provider event clock"),
            None,
        )),
        SolanaReadMethod::GetSignaturesForAddress => Ok((
            missing("getSignaturesForAddress page carries no single provider event clock"),
            None,
        )),
        _ => Ok((
            missing("this read method states no provider event clock"),
            None,
        )),
    }
}

pub(crate) fn first_signatures(frame: &RawSourceFrame, wanted: usize) -> Vec<String> {
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

pub(crate) fn ensure_provider_accepted(read: &CapturedRead) -> Result<(), Box<dyn Error>> {
    let method = read.method.as_str();
    if read.frame.http_status != Some(200) {
        return Err(format!(
            "Helius rejected the {method} read with HTTP status {:?}; authenticated URL omitted",
            read.frame.http_status
        )
        .into());
    }
    let Ok(value) = serde_json::from_slice::<Value>(&read.frame.body) else {
        return Err(format!("Helius {method} response body was not JSON").into());
    };
    if let Some(error) = value.get("error") {
        let code = error.get("code").and_then(Value::as_i64);
        let message = error
            .get("message")
            .and_then(Value::as_str)
            .map_or_else(|| "[no message]".to_owned(), sanitized_provider_message);
        return Err(
            format!("Helius {method} returned JSON-RPC error code {code:?}: {message}").into(),
        );
    }
    Ok(())
}

/// Provider prose is never trusted to be credential-free, so anything endpoint-shaped is withheld.
fn sanitized_provider_message(value: &str) -> String {
    let lowered = value.to_ascii_lowercase();
    for needle in ["key", "token", "secret", "http", "helius-rpc.com"] {
        if lowered.contains(needle) {
            return "[provider message withheld: it referenced an endpoint or credential]"
                .to_owned();
        }
    }
    value
        .chars()
        .filter(|character| !character.is_control())
        .take(PREVIEW_CHARS)
        .collect()
}

pub(crate) fn read_summary(read: &CapturedRead) -> Value {
    json!({
        "method": read.method.as_str(),
        "sequence": read.frame.sequence,
        "httpStatus": read.frame.http_status,
        "responseBytes": read.frame.body.len(),
        "receivedUnixMillis": read.frame.received_at.0,
        "safeHeaders": read.frame.safe_headers.len(),
        "rateLimit": read.rate_limit,
    })
}

fn validate_wallet(value: &str) -> Result<(), Box<dyn Error>> {
    validate_base58_address(value, "--wallet")
}

/// A Solana address is exactly 32 base58-decoded bytes. Nothing else about it is asserted here.
pub(crate) fn validate_base58_address(value: &str, label: &str) -> Result<(), Box<dyn Error>> {
    let decoded = bs58::decode(value)
        .into_vec()
        .map_err(|_| format!("{label} is not valid base58"))?;
    if decoded.len() == 32 {
        Ok(())
    } else {
        Err(format!("{label} must decode to a 32-byte Solana address").into())
    }
}

pub(crate) fn open_catalog(root: &Path, mode: StoreMode) -> Result<SqliteStore, Box<dyn Error>> {
    Ok(SqliteStore::open(catalog_config(root)?, mode)?)
}

pub(crate) fn catalog_config(root: &Path) -> Result<StoreConfig, Box<dyn Error>> {
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

/// A per-occurrence namespace so equal bytes acquired twice still retain distinct identities.
fn run_namespace() -> Result<String, Box<dyn Error>> {
    let millis = unix_millis(OffsetDateTime::now_utc())?;
    Ok(format!(
        "collector-ingest-live-{millis}-{}",
        std::process::id()
    ))
}

pub(crate) fn now_utc() -> Result<UtcTimestamp, Box<dyn Error>> {
    Ok(UtcTimestamp::new(microsecond_aligned(
        OffsetDateTime::now_utc(),
    )?)?)
}

/// Truncate rather than round: the shared timestamp contract refuses sub-microsecond instants.
fn microsecond_aligned(value: OffsetDateTime) -> Result<OffsetDateTime, Box<dyn Error>> {
    let nanosecond = value.nanosecond();
    Ok(value.replace_nanosecond(nanosecond - nanosecond % 1_000)?)
}

pub(crate) fn unix_millis(value: OffsetDateTime) -> Result<i64, Box<dyn Error>> {
    Ok(i64::try_from(value.unix_timestamp_nanos() / 1_000_000)?)
}

fn utc_from_millis(millis: i64) -> Result<UtcTimestamp, Box<dyn Error>> {
    let value = OffsetDateTime::from_unix_timestamp_nanos(i128::from(millis) * 1_000_000)?;
    Ok(UtcTimestamp::new(value)?)
}

pub(crate) fn elapsed_nanos(process_start: Instant) -> Result<u64, Box<dyn Error>> {
    Ok(u64::try_from(process_start.elapsed().as_nanos())?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use bytes::Bytes;
    use joshi_sources::{
        ADAPTER_CONTRACT_VERSION, ContentType, FrameDirection, SourceId, Transport,
    };

    fn synthetic(method: SolanaReadMethod, sequence: u64, body: &'static str) -> CapturedRead {
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
                body: Bytes::from_static(body.as_bytes()),
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

    /// The whole wire without a network: exact frames become drafts, one batch, one durable
    /// commit, and a payload that reads back byte for byte.
    #[test]
    fn synthetic_frames_reach_the_durable_catalog_and_read_back_exactly() {
        let slot_body = r#"{"jsonrpc":"2.0","result":378123456,"id":1}"#;
        let transaction_body =
            r#"{"jsonrpc":"2.0","result":{"slot":378123400,"blockTime":1786882500},"id":2}"#;
        let reads = vec![
            synthetic(SolanaReadMethod::GetSlot, 1, slot_body),
            synthetic(SolanaReadMethod::GetTransaction, 2, transaction_body),
        ];
        let root = tempfile::tempdir().expect("temporary catalog root");
        let receipt = {
            let mut store =
                open_catalog(root.path(), StoreMode::SingleWriter).expect("catalog opens");
            store
                .migrate(now_utc().expect("clock"))
                .expect("migrations");
            commit_reads(
                &mut store,
                &reads,
                "collector-ingest-live-test",
                "joshi-collector-live-test",
                Instant::now(),
            )
            .expect("synthetic frames commit")
        };
        assert_eq!(receipt.admitted.observations, "2");
        assert_eq!(receipt.admitted.acquisitions, "2");
        assert_eq!(receipt.acquisition_ids.len(), 2);

        let rendered = store_readback(root.path()).expect("catalog reads back");
        let value: Value = serde_json::from_str(&rendered).expect("readback is JSON");
        assert_eq!(value["observationCount"], 2);
        let first = &value["firstObservation"];
        assert_eq!(first["providerBodyBytes"], slot_body.len());
        assert_eq!(first["providerBodyPreview"], slot_body);
        assert_eq!(first["httpStatus"], 200);
    }

    /// A `blockTime` is a real provider clock; a tip slot and a signature page are not.
    #[test]
    fn provider_clocks_are_claimed_only_where_the_payload_states_one() {
        let transaction: Value =
            serde_json::from_str(r#"{"result":{"slot":9,"blockTime":1786882500}}"#).expect("json");
        let (event_time, slot) =
            event_time_and_location(SolanaReadMethod::GetTransaction, Some(&transaction))
                .expect("event time");
        assert_eq!(slot, Some(9));
        assert!(matches!(event_time, ProviderEventTime::Bounded { .. }));

        let tip: Value = serde_json::from_str(r#"{"result":378123456}"#).expect("json");
        let (event_time, slot) =
            event_time_and_location(SolanaReadMethod::GetSlot, Some(&tip)).expect("event time");
        assert_eq!(slot, None);
        assert!(matches!(event_time, ProviderEventTime::Missing { .. }));

        let page: Value =
            serde_json::from_str(r#"{"result":[{"signature":"a","slot":8}]}"#).expect("json");
        let (event_time, slot) =
            event_time_and_location(SolanaReadMethod::GetSignaturesForAddress, Some(&page))
                .expect("event time");
        assert_eq!(slot, None);
        assert!(matches!(event_time, ProviderEventTime::Missing { .. }));
    }

    #[test]
    fn budget_is_a_hard_stop_rather_than_a_hint() {
        let mut budget = ReadBudget::new(2);
        budget.claim().expect("first request");
        budget.claim().expect("second request");
        assert_eq!(budget.remaining(), 0);
        assert!(budget.claim().is_err());
    }

    #[test]
    fn wallet_must_be_a_thirty_two_byte_base58_address() {
        validate_wallet("BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh").expect("fixture wallet");
        assert!(validate_wallet("not base58!").is_err());
        assert!(validate_wallet("abc").is_err());
    }

    #[test]
    fn provider_prose_that_names_an_endpoint_or_credential_is_withheld() {
        assert!(sanitized_provider_message("invalid api key supplied").starts_with("[provider"));
        assert!(
            sanitized_provider_message("https://mainnet.helius-rpc.com/?api-key=abc")
                .starts_with("[provider")
        );
        assert_eq!(
            sanitized_provider_message("Too many requests for a specific RPC call"),
            "Too many requests for a specific RPC call"
        );
    }

    #[test]
    fn rejected_reads_never_reach_the_durable_boundary() {
        let mut rejected = synthetic(SolanaReadMethod::GetSlot, 1, r#"{"result":1}"#);
        rejected.frame.http_status = Some(401);
        assert!(ensure_provider_accepted(&rejected).is_err());

        let rpc_error = synthetic(
            SolanaReadMethod::GetSlot,
            1,
            r#"{"jsonrpc":"2.0","error":{"code":-32005,"message":"Too many requests"},"id":1}"#,
        );
        assert!(ensure_provider_accepted(&rpc_error).is_err());
    }

    #[test]
    fn signature_selection_reads_only_the_provider_page() {
        let page = synthetic(
            SolanaReadMethod::GetSignaturesForAddress,
            1,
            r#"{"result":[{"signature":"one"},{"signature":"two"},{"signature":"three"}]}"#,
        );
        assert_eq!(first_signatures(&page.frame, 2), vec!["one", "two"]);
        let empty = synthetic(
            SolanaReadMethod::GetSignaturesForAddress,
            1,
            r#"{"result":[]}"#,
        );
        assert!(first_signatures(&empty.frame, 2).is_empty());
    }
}
