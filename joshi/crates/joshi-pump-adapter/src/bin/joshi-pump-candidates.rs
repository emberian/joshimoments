//! Sweep, wait, sweep, join on mint, rank what moved. A CANDIDATE FINDER, not a signal.
//!
//! This binary turns the one-off measurement that motivated it into something repeatable: two
//! passes over `/coins?sort=last_trade_timestamp&order=DESC` separated by a known window, joined
//! on mint, ranked by absolute market-cap move, with the provider's own peak and — if terms are
//! supplied — a realised one-hour volume from `/coins/search-unrestricted` beside each row.
//!
//! Every page it uses must be PROMOTED by a row-projection review before a single row of it can
//! reach the ranking. A refused page is counted in the slate's census and contributes nothing, so
//! a thin slate is always distinguishable from a quiet market.
//!
//! It constructs, signs and submits nothing. Every route it can reach is a `GET`.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use joshi_pump_adapter::candidates::{Sweep, find_candidates};
use joshi_pump_api::{
    ClientConfig, FetchOutcome, IdentityStore, LogicalRequest, NoSession, PumpApiClient,
    RequestParameters, RouteId, RouteSpec, RowProjectionReviewV1, SessionProvider,
    normalize_with_row_projection,
};

#[derive(Debug, Parser)]
#[command(name = "joshi-pump-candidates")]
#[command(about = "Two discovery sweeps joined on mint: a crackle CANDIDATE finder, not a signal")]
struct Cli {
    /// Durable working root for acquisition identity reservations.
    #[arg(long)]
    state_dir: PathBuf,
    /// Row-projection review that must promote every discovery page before its rows are used.
    #[arg(long)]
    discovery_review: PathBuf,
    /// Row-projection review for the flow sweep. Required when `--term` is given.
    #[arg(long)]
    search_review: Option<PathBuf>,
    /// Pages per sweep. `/coins` clamps `limit` to 70, so page N is offset 70*N.
    #[arg(long, default_value_t = 5)]
    pages: usize,
    /// Seconds between the two sweeps. This is the window every percentage is measured over.
    #[arg(long, default_value_t = 90)]
    wait_seconds: u64,
    /// Search term for the flow sweep. Repeat for each term; each costs one request.
    #[arg(long = "term")]
    terms: Vec<String>,
    /// Most candidates to print. The census counts every one that was ranked.
    #[arg(long, default_value_t = 25)]
    limit: usize,
    /// Hard ceiling on HTTP requests this process may make.
    #[arg(long, default_value_t = 40)]
    request_budget: usize,
    /// Directory to write every exact fetch outcome into, so these reads can be admitted later.
    #[arg(long)]
    keep_outcomes: Option<PathBuf>,
}

#[tokio::main]
async fn main() {
    if let Err(error) = run(Cli::parse()).await {
        eprintln!("joshi-pump-candidates: {error}");
        std::process::exit(2);
    }
}

async fn run(cli: Cli) -> Result<(), Box<dyn std::error::Error>> {
    if !cli.terms.is_empty() && cli.search_review.is_none() {
        return Err("--term needs --search-review; an ungated page may not reach a ranking".into());
    }
    let discovery = review(&cli.discovery_review, RouteId::DiscoveryCoins)?;
    let search = cli
        .search_review
        .as_deref()
        .map(|path| review(path, RouteId::CoinSearch))
        .transpose()?;

    let mut config = ClientConfig {
        request_budget: cli.request_budget,
        maximum_attempts: 1,
        response_limit_bytes: 2 * 1024 * 1024,
        request_timeout: Duration::from_secs(20),
        ..ClientConfig::default()
    };
    config.enabled_routes = [RouteId::DiscoveryCoins, RouteId::CoinSearch]
        .into_iter()
        .collect();
    let identity = IdentityStore::open(cli.state_dir.join("identity"))?;
    let sessions: Arc<dyn SessionProvider> = Arc::new(NoSession);
    let client = PumpApiClient::new(config, identity, sessions)?;

    let mut early = Sweep::new();
    sweep_discovery(&client, &discovery, cli.pages, &mut early, &cli, "early").await?;
    tokio::time::sleep(Duration::from_secs(cli.wait_seconds)).await;
    let mut late = Sweep::new();
    sweep_discovery(&client, &discovery, cli.pages, &mut late, &cli, "late").await?;

    let mut flow = Sweep::new();
    if let Some(search) = search.as_ref() {
        for term in &cli.terms {
            let outcome = fetch(
                &client,
                RouteId::CoinSearch,
                [
                    ("searchTerm".to_owned(), term.clone()),
                    ("limit".to_owned(), "100".to_owned()),
                ]
                .into_iter()
                .collect(),
            )
            .await?;
            absorb(&mut flow, &outcome, search, &cli, &format!("flow-{term}"))?;
        }
    }

    let slate = find_candidates(
        &early,
        &late,
        (!cli.terms.is_empty()).then_some(&flow),
        cli.limit,
    )?;
    println!("{}", serde_json::to_string_pretty(&slate)?);
    Ok(())
}

async fn sweep_discovery(
    client: &PumpApiClient,
    review: &RowProjectionReviewV1,
    pages: usize,
    sweep: &mut Sweep,
    cli: &Cli,
    label: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    for page in 0..pages.max(1) {
        let outcome = fetch(
            client,
            RouteId::DiscoveryCoins,
            [
                ("limit".to_owned(), "70".to_owned()),
                ("offset".to_owned(), (page * 70).to_string()),
                ("sort".to_owned(), "last_trade_timestamp".to_owned()),
                ("order".to_owned(), "DESC".to_owned()),
            ]
            .into_iter()
            .collect(),
        )
        .await?;
        absorb(sweep, &outcome, review, cli, &format!("{label}-{page}"))?;
    }
    Ok(())
}

async fn fetch(
    client: &PumpApiClient,
    route: RouteId,
    query: BTreeMap<String, String>,
) -> Result<FetchOutcome, Box<dyn std::error::Error>> {
    Ok(client
        .fetch(&LogicalRequest {
            route,
            parameters: RequestParameters {
                path: BTreeMap::new(),
                query,
            },
        })
        .await?)
}

/// Gate one page and fold it in. The normalization is what decides, not this function.
fn absorb(
    sweep: &mut Sweep,
    outcome: &FetchOutcome,
    review: &RowProjectionReviewV1,
    cli: &Cli,
    label: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(root) = cli.keep_outcomes.as_deref() {
        fs::create_dir_all(root)?;
        fs::write(
            root.join(format!("{label}.json")),
            serde_json::to_vec(outcome)?,
        )?;
    }
    let Some(acquisition) = outcome.attempts.last() else {
        eprintln!("page {label}: no attempt was made; it contributes nothing");
        return Ok(());
    };
    let normalization = normalize_with_row_projection(acquisition, review);
    if normalization.disposition != "accepted_provider_assertions" {
        // Loud, and counted. A refused page must never look like a quiet market.
        eprintln!(
            "page {label}: REFUSED by the row projection -- {}",
            normalization.fidelity_gaps.first().map_or_else(
                || "no reason recorded".to_owned(),
                |gap| format!("{}: {}", gap.code, gap.detail)
            )
        );
    }
    sweep.absorb(acquisition, &normalization);
    Ok(())
}

fn review(
    path: &Path,
    expected: RouteId,
) -> Result<RowProjectionReviewV1, Box<dyn std::error::Error>> {
    let review = RowProjectionReviewV1::from_slice(&fs::read(path)?)?;
    if review.route_id != expected.to_string() {
        return Err(format!(
            "row projection at {} reviews {}, not {expected}",
            path.display(),
            review.route_id
        )
        .into());
    }
    if !RouteSpec::for_id(expected).collection_enabled {
        return Err(format!("route {expected} is not collectable in the pinned catalog").into());
    }
    Ok(review)
}
