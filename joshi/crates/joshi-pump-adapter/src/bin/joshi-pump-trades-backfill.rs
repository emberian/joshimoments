//! Walk one mint's trade history backwards under budgets this process enforces itself, retaining
//! every page's exact bytes, and stop at a reason that is written down rather than implied.
//!
//! This exists because the candle route cannot reach the past. It returns one newest-anchored
//! window of at most 1000 gap-compressed bars and its `before` argument was measured inert, so on
//! a coin that trades every second it is permanently about seventeen minutes wide. The trade
//! route can reach the past, because `pagination.nextCursor` is the exclusive keyset
//! `slotIndexId-epochMillis` of the last row it returned.
//!
//! Two budgets bound the walk and both are checked here rather than trusted to the transport: a
//! hard request ceiling and a hard wall-clock ceiling. Exhausting either is a recorded stop, not
//! a silent truncation. The same is true of a provider refusal, an unreviewed page shape, and a
//! page that overlaps the one before it.
//!
//! It constructs, signs, and submits nothing.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use clap::Parser;
use joshi_domain::{StableString, UtcTimestamp};
use joshi_pump_adapter::{
    Adjacency, PageFacts, PreparedProductRead, ProductReadInput, TRADES_BACKFILL_WALK_V1,
    TradesBackfillPageV1, TradesBackfillWalkV1, WalkStop, backfill, close_receipt, page_record,
    prepare_trades_backfill_page, requests_per_hour_of_tape, span_millis,
};
use joshi_pump_api::{
    AuthenticatedPathDecision, ClientConfig, FetchOutcome, IdentityStore, LogicalRequest,
    NoSession, PumpApiClient, RequestParameters, RouteId, RouteSpec, SchemaTrustOutcome,
    SessionProvider, client::sha256,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};
use serde::Serialize;

#[derive(Debug, Parser)]
#[command(name = "joshi-pump-trades-backfill")]
#[command(about = "Walk one mint's trade history backwards under hard budgets, retaining bytes")]
struct Cli {
    /// SPL mint whose trade history to walk.
    #[arg(long)]
    mint: String,
    /// Durable working root: identity reservations, catalog, blobs, exports.
    #[arg(long)]
    state_dir: PathBuf,
    /// Reviewed-schema artifact for the trades route. Without it every page quarantines and the
    /// walk stops on the first one, which is the correct behaviour rather than a degraded mode.
    #[arg(long)]
    review: Option<PathBuf>,
    /// Rows per page to ask the provider for.
    #[arg(long, default_value_t = 500)]
    page_limit: u32,
    /// Hard ceiling on provider requests for the whole walk.
    #[arg(long, default_value_t = 8)]
    request_budget: usize,
    /// Hard ceiling on wall-clock seconds for the whole walk, enforced by this process.
    #[arg(long, default_value_t = 120)]
    wall_budget_seconds: u64,
    /// Hard ceiling on pages, independent of the request budget.
    #[arg(long, default_value_t = 64)]
    max_pages: usize,
    /// Stop once a page reaches back to this canonical six-digit UTC instant.
    #[arg(long)]
    stop_before: Option<String>,
    /// Begin the walk at this canonical six-digit UTC instant instead of at the newest page.
    ///
    /// The trades cursor is a random-access seek, measured 2026-08-22 and recorded in the route
    /// catalog: the provider does not validate the `slotIndexId` prefix, so an all-zero prefix
    /// with an epoch-millisecond suffix returns the newest rows strictly before that instant.
    /// Seeking past the beginning of a mint's retained history returns the terminal page shape,
    /// which the reviewed schema refuses, and the walk stops there with the refusal written down.
    #[arg(long)]
    seek: Option<String>,
    /// Write the walk record here as well as to the store.
    #[arg(long)]
    emit_walk: Option<PathBuf>,
}

#[tokio::main]
async fn main() {
    if let Err(error) = run(Cli::parse()).await {
        eprintln!("joshi-pump-trades-backfill: {error}");
        std::process::exit(2);
    }
}

type Failure = Box<dyn std::error::Error>;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WalkReceipt {
    contract: &'static str,
    authority: &'static str,
    walk: TradesBackfillWalkV1,
    committed_batches: Vec<String>,
    reopened_integrity: String,
    reopened_external_blobs_checked: String,
    walk_semantic_key: String,
    walk_readback_assertion_id: Option<String>,
    /// The instant the walk was asked to begin before, when it did not begin at the newest page.
    /// The first page's `request_cursor_fingerprint` in the walk record is the seek cursor's.
    seek_instant: Option<String>,
    oldest_page_body_path: Option<String>,
    oldest_page_bytes_equal_response: bool,
    /// Set when the walk stopped on something a person has to look at before it resumes.
    needs_human: Option<&'static str>,
}

#[allow(clippy::too_many_lines)] // The whole walk, its budgets and its stop reasons stay together.
async fn run(cli: Cli) -> Result<(), Failure> {
    let route = RouteId::Trades;
    let spec = RouteSpec::for_id(route);
    if !spec.collection_enabled {
        return Err("route trades is not marked collectable in the pinned catalog".into());
    }
    if cli.page_limit == 0 || cli.request_budget == 0 || cli.max_pages == 0 {
        return Err("every budget must allow at least one page".into());
    }
    let horizon = cli
        .stop_before
        .as_deref()
        .map(str::parse::<UtcTimestamp>)
        .transpose()?;
    let seek = cli
        .seek
        .as_deref()
        .map(str::parse::<UtcTimestamp>)
        .transpose()?;
    if let (Some(horizon), Some(seek)) = (horizon, seek)
        && horizon.as_datetime() >= seek.as_datetime()
    {
        return Err("--stop-before must be strictly earlier than --seek".into());
    }
    let seek_cursor = seek.map(|instant| {
        let millis = instant.as_datetime().unix_timestamp_nanos() / 1_000_000;
        format!("{:026}-{millis}", 0)
    });
    let review_bytes = cli.review.as_deref().map(fs::read).transpose()?;

    let mut config = ClientConfig {
        request_budget: cli.request_budget,
        // One attempt per page. A retried page would spend budget the walk cannot account for
        // against a specific cursor, and a walk whose cost is not attributable is not a
        // measurement of cost.
        maximum_attempts: 1,
        response_limit_bytes: 4 * 1024 * 1024,
        request_timeout: Duration::from_secs(20),
        ..ClientConfig::default()
    };
    config.enabled_routes = [route].into_iter().collect();

    let identity = IdentityStore::open(cli.state_dir.join("identity"))?;
    let sessions: Arc<dyn SessionProvider> = Arc::new(NoSession);
    let client = PumpApiClient::new(config, identity.clone(), sessions)?;

    let started = Instant::now();
    let started_at = now_utc()?;
    let walk_id = format!(
        "walk:pump-trades:{}:{}",
        sha256(cli.mint.as_bytes()).trim_start_matches("sha256:"),
        started_at.replace([':', '.', '-'], "")
    );

    let mut store = SqliteStore::open(store_config(&cli.state_dir)?, StoreMode::SingleWriter)?;
    store.migrate(started_at.parse::<UtcTimestamp>()?)?;

    let mut pages: Vec<TradesBackfillPageV1> = Vec::new();
    let mut committed_batches: Vec<String> = Vec::new();
    let mut previous: Option<PageFacts> = None;
    let mut cursor: Option<String> = seek_cursor;
    let mut requests_used: u32 = 0;
    let mut rows_retained: u64 = 0;
    let mut newest_event_time: Option<String> = None;
    let mut oldest_event_time: Option<String> = None;
    let mut oldest_body: Option<(String, Vec<u8>)> = None;
    let mut unreviewed_fingerprint: Option<String> = None;

    let stop = loop {
        let mut query = BTreeMap::from([("limit".to_owned(), cli.page_limit.to_string())]);
        if let Some(cursor) = cursor.as_deref() {
            query.insert("cursor".to_owned(), cursor.to_owned());
        }
        let request = LogicalRequest {
            route,
            parameters: RequestParameters {
                path: [("mint".to_owned(), cli.mint.clone())]
                    .into_iter()
                    .collect(),
                query,
            },
        };
        let outcome: FetchOutcome = client.fetch(&request).await?;
        requests_used += 1;
        let outcome_bytes = serde_json::to_vec(&outcome)?;
        let decided_at = now_utc()?;
        let ordinal = pages.len();

        // Prepare once with no walk record to learn what this page is. This is a pure function of
        // the retained bytes, so preparing it again below with the walk attached cannot disagree.
        let batch_id = format!(
            "batch:pump-trades-backfill:{}",
            outcome
                .request_group_id
                .trim_start_matches("reqgrp:pump-api:")
        );
        let input = ProductReadInput {
            outcome_bytes: &outcome_bytes,
            review_bytes: review_bytes.as_deref(),
            authenticated_path: AuthenticatedPathDecision::NotPerformed,
            session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
            session_detail: SESSION_DETAIL,
            durable_batch_id: &batch_id,
            committed_at: decided_at.parse::<UtcTimestamp>()?,
            committed_monotonic_ns: 1,
            decided_at: &decided_at,
        };
        let looked = prepare_trades_backfill_page(&input, None)?;
        let promoted = looked.decision.outcome == SchemaTrustOutcome::Promoted;
        let facts = if promoted {
            looked
                .acquisition
                .body
                .exact_bytes()
                .map(|bytes| PageFacts::from_promoted_bytes(&bytes))
                .transpose()?
        } else {
            None
        };
        let adjacency = facts.as_ref().map_or(Adjacency::NotComparable, |facts| {
            facts.adjacency_to(previous.as_ref())
        });
        pages.push(page_record(
            ordinal,
            &looked.acquisition,
            &looked.decision,
            facts.as_ref(),
            adjacency,
            cursor.as_deref().map(|value| sha256(value.as_bytes())),
        ));

        if let Some(facts) = facts.as_ref() {
            rows_retained += facts.rows as u64;
            if newest_event_time.is_none() && facts.rows > 0 {
                newest_event_time = Some(facts.newest_event_time.clone());
            }
            if facts.rows > 0 {
                oldest_event_time = Some(facts.oldest_event_time.clone());
                if let (Some(blob), Some(bytes)) = (
                    looked.acquisition.body.blob_id().map(str::to_owned),
                    looked.acquisition.body.exact_bytes(),
                ) {
                    oldest_body = Some((blob, bytes));
                }
            }
        }

        // Everything that could end the walk, evaluated on the page we just read. The decision
        // tree itself lives in the library so it can be tested without spending a request.
        if !promoted {
            unreviewed_fingerprint.clone_from(&looked.decision.observed_schema_fingerprint);
        }
        let horizon_reached = match (horizon, facts.as_ref()) {
            (Some(horizon), Some(facts)) if facts.rows > 0 => {
                backfill::at_or_before(&facts.oldest_event_time, horizon)?
            }
            _ => false,
        };
        let stop = backfill::classify_stop(
            backfill::PageVerdict {
                promoted,
                http_status: looked.acquisition.http_status,
                trust_reason: &looked.decision.reason_code,
                facts: facts.as_ref(),
                adjacency,
                horizon_reached,
            },
            backfill::WalkBudgets {
                pages_so_far: pages.len(),
                max_pages: cli.max_pages,
                requests_used,
                request_budget: cli.request_budget,
                elapsed_ms: started.elapsed().as_millis(),
                wall_budget_ms: u128::from(cli.wall_budget_seconds) * 1_000,
            },
        );

        if let Some(stop) = stop {
            let walk = assemble(
                &cli,
                &walk_id,
                &started_at,
                &now_utc()?,
                requests_used,
                started.elapsed(),
                &pages,
                rows_retained,
                newest_event_time.clone(),
                oldest_event_time.clone(),
                stop,
                unreviewed_fingerprint.clone(),
            )?;
            let closing = prepare_trades_backfill_page(&input, Some(&walk))?;
            commit_page(&mut store, &closing, &identity, &mut committed_batches)?;
            break walk;
        }

        commit_page(&mut store, &looked, &identity, &mut committed_batches)?;
        cursor = facts.as_ref().and_then(|facts| facts.next_cursor.clone());
        previous = facts;
    };

    drop(store);

    if let Some(path) = cli.emit_walk.as_deref() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, serde_json::to_vec_pretty(&stop)?)?;
    }

    let reopened = SqliteStore::open(store_config(&cli.state_dir)?, StoreMode::ReadOnly)?;
    let verification = reopened.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" || verification.foreign_key_defects != 0 {
        return Err("reopened catalog failed verification".into());
    }
    let key = stop.semantic_key();
    let rows = reopened.effective_assertions_as_known(&key, verification.max_commit_seq)?;
    let readback = rows.first().map(|row| row.assertion_id.to_string());
    if readback.is_none() {
        return Err(format!("walk record {key} did not survive the restart").into());
    }
    drop(reopened);

    let mut oldest_page_body_path = None;
    let mut oldest_equal = false;
    if let Some((blob, bytes)) = oldest_body.as_ref() {
        let path = external_blob_path(&cli.state_dir, "public_source", blob)?;
        oldest_equal = fs::read(&path)? == *bytes;
        oldest_page_body_path = Some(path.display().to_string());
        if !oldest_equal {
            return Err("the oldest retained page does not read back byte-for-byte".into());
        }
    }

    let receipt = WalkReceipt {
        contract: "joshi.pump_trades_backfill_run.v1",
        authority: "read_only_no_execution",
        walk_semantic_key: key,
        needs_human: stop.stop.needs_review().then_some(
            "the walk stopped on a page shape or a cursor behaviour that a person must review \
             before this walk is resumed or a review is widened",
        ),
        walk: stop,
        committed_batches,
        seek_instant: cli.seek.clone(),
        reopened_integrity: verification.integrity,
        reopened_external_blobs_checked: verification.external_artifacts_checked.to_string(),
        walk_readback_assertion_id: readback,
        oldest_page_body_path,
        oldest_page_bytes_equal_response: oldest_equal,
    };
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

const SESSION_DETAIL: &str = "This walk read an undocumented public product route that the Pump web client itself calls \
     anonymously, with no session provider configured. Its shape is observed rather than \
     described, so the schema-trust decision beside this note governs whether anything derived \
     from it may be trusted. No pump.fun user session was available, so no authenticated product \
     route was attempted.";

fn commit_page(
    store: &mut SqliteStore,
    prepared: &PreparedProductRead,
    identity: &IdentityStore,
    committed: &mut Vec<String>,
) -> Result<(), Failure> {
    let receipt = prepared.prepared.admission_batch().commit(store)?;
    let closed = close_receipt(&prepared.prepared, &receipt)?;
    prepared.prepared.acknowledge_direct(identity, &receipt)?;
    committed.push(closed.durable_batch_id);
    Ok(())
}

#[allow(clippy::too_many_arguments)] // Every total in the record is derived at one visible place.
fn assemble(
    cli: &Cli,
    walk_id: &str,
    started_at: &str,
    ended_at: &str,
    requests_used: u32,
    elapsed: Duration,
    pages: &[TradesBackfillPageV1],
    rows_retained: u64,
    newest_event_time: Option<String>,
    oldest_event_time: Option<String>,
    stop: WalkStop,
    unreviewed_schema_fingerprint: Option<String>,
) -> Result<TradesBackfillWalkV1, Failure> {
    let covered_span_ms = match (newest_event_time.as_deref(), oldest_event_time.as_deref()) {
        (Some(newest), Some(oldest)) => Some(span_millis(newest, oldest)?),
        _ => None,
    };
    let walk = TradesBackfillWalkV1 {
        contract: TRADES_BACKFILL_WALK_V1.to_owned(),
        schema_version: "1".to_owned(),
        walk_id: walk_id.to_owned(),
        route_id: RouteId::Trades.to_string(),
        catalog_version: joshi_pump_api::ROUTE_CATALOG.to_owned(),
        subject_kind: "spl_mint".to_owned(),
        subject: cli.mint.clone(),
        page_limit: cli.page_limit.to_string(),
        started_at: started_at.to_owned(),
        ended_at: ended_at.to_owned(),
        requests_used: requests_used.to_string(),
        request_budget: cli.request_budget.to_string(),
        elapsed_ms: elapsed.as_millis().to_string(),
        wall_budget_ms: (cli.wall_budget_seconds * 1_000).to_string(),
        pages_attempted: pages.len().to_string(),
        pages_promoted: pages
            .iter()
            .filter(|page| page.schema_trust_outcome == "promoted")
            .count()
            .to_string(),
        rows_retained: rows_retained.to_string(),
        newest_event_time,
        oldest_event_time,
        covered_span_ms: covered_span_ms.map(|value| value.to_string()),
        requests_per_hour_of_tape: covered_span_ms
            .and_then(|span| requests_per_hour_of_tape(requests_used, span)),
        stop,
        stop_detail: stop_detail(stop).to_owned(),
        unreviewed_schema_fingerprint,
        pages: pages.to_vec(),
    };
    walk.validate()?;
    Ok(walk)
}

fn stop_detail(stop: WalkStop) -> &'static str {
    match stop {
        WalkStop::RequestBudgetExhausted => {
            "the walk spent its whole request ceiling; older history exists and was not read"
        }
        WalkStop::WallClockBudgetExhausted => {
            "the walk reached its wall-clock ceiling; older history exists and was not read"
        }
        WalkStop::PageBudgetExhausted => {
            "the walk reached its page ceiling; older history exists and was not read"
        }
        WalkStop::HorizonReached => {
            "the walk reached the instant the caller asked it to stop before"
        }
        WalkStop::ProviderReportedNoMore => {
            "the provider's own hasMore said there is nothing older on this route"
        }
        WalkStop::CursorAbsent => {
            "a promoted page carried no continuation cursor, so nothing older can be asked for"
        }
        WalkStop::SchemaRefusedPendingReview => {
            "a page's structural shape is not the reviewed one; the bytes are retained and \
             quarantined, and widening the review is a human decision this walk did not take"
        }
        WalkStop::ProviderRefused => {
            "the provider did not return a usable success body for this page"
        }
        WalkStop::PageOverlappedPrevious => {
            "a page returned a row the previous page had already returned, so the continuation \
             cursor is not the exclusive keyset it was measured to be"
        }
        WalkStop::EmptyPage => "a promoted page carried no rows",
    }
}

fn external_blob_path(
    state_dir: &Path,
    retention_class: &str,
    blob_id: &str,
) -> Result<PathBuf, Failure> {
    let digest = blob_id
        .strip_prefix("sha256:")
        .ok_or("blob identity is not a sha256 digest")?;
    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("blob identity is not a 64-character hex digest".into());
    }
    Ok(state_dir
        .join("blobs")
        .join(retention_class)
        .join("sha256")
        .join(&digest[0..2])
        .join(&digest[2..4])
        .join(format!("{digest}.blob")))
}

fn store_config(root: &Path) -> Result<StoreConfig, Failure> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 0,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new("joshi-pump-trades-backfill")?,
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 16 * 1024 * 1024,
    })
}

fn now_utc() -> Result<String, Failure> {
    Ok(
        time::OffsetDateTime::now_utc().format(time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ))?,
    )
}
