//! One mint's crackle measurement: the venue fee it has to clear, and how often it cleared it.
//!
//! Both inputs are exact `FetchOutcome` envelopes as the source-edge client wrote them, and both
//! must promote against their reviewed schema before a number comes out. That is the point of the
//! gate: an unreviewed body produces a refusal here, never a number with a caveat attached.
//!
//! It reads files and prints a report. It performs no network I/O and constructs nothing.

use std::fs;
use std::path::{Path, PathBuf};

use clap::Parser;
use joshi_pump_adapter::{CrackleReportV1, crackle, crackle_report};
use joshi_pump_api::{
    Acquisition, FetchOutcome, SchemaReviewV1, SchemaTrustDecisionV1, decide_schema_trust,
};

#[derive(Debug, Parser)]
#[command(name = "joshi-pump-crackle")]
#[command(about = "Measure one mint's fee floor and the excursions that cleared it")]
struct Cli {
    /// SPL mint these two reads describe. Both are checked to be the same subject upstream.
    #[arg(long)]
    mint: String,
    /// Exact candle-window fetch outcome.
    #[arg(long)]
    candles: PathBuf,
    /// Exact trade-page fetch outcome.
    #[arg(long)]
    trades: PathBuf,
    /// Reviewed schema for the candle route.
    #[arg(long)]
    review_candles: PathBuf,
    /// Reviewed schema for the trade route.
    #[arg(long)]
    review_trades: PathBuf,
    /// Cap on how long either leg of one excursion may take, in milliseconds.
    #[arg(long, default_value_t = crackle::DEFAULT_LEG_CAP_MS)]
    leg_cap_ms: i64,
    /// Write the report here as well as printing it.
    #[arg(long)]
    emit: Option<PathBuf>,
}

type Failure = Box<dyn std::error::Error>;

fn main() {
    if let Err(error) = run(&Cli::parse()) {
        eprintln!("joshi-pump-crackle: {error}");
        std::process::exit(2);
    }
}

fn run(cli: &Cli) -> Result<(), Failure> {
    let decided_at = now_utc()?;
    let (candles, candles_decision) = promoted(&cli.candles, &cli.review_candles, &decided_at)?;
    let (trades, trades_decision) = promoted(&cli.trades, &cli.review_trades, &decided_at)?;
    let report: CrackleReportV1 = crackle_report(
        (&trades, &trades_decision),
        (&candles, &candles_decision),
        &cli.mint,
        &decided_at,
        cli.leg_cap_ms,
    )?;
    let rendered = serde_json::to_string_pretty(&report)?;
    if let Some(path) = cli.emit.as_deref() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, rendered.as_bytes())?;
    }
    println!("{rendered}");
    Ok(())
}

/// Load one exact fetch outcome and decide its schema trust before anything reads its numbers.
fn promoted(
    outcome: &Path,
    review: &Path,
    decided_at: &str,
) -> Result<(Acquisition, SchemaTrustDecisionV1), Failure> {
    let outcome: FetchOutcome = serde_json::from_slice(&fs::read(outcome)?)?;
    let acquisition = outcome
        .attempts
        .last()
        .cloned()
        .ok_or("fetch outcome carries no attempt")?;
    let review = SchemaReviewV1::from_slice(&fs::read(review)?)?;
    let decision = decide_schema_trust(&acquisition, Some(&review), decided_at)?;
    if !decision.promoted() {
        return Err(format!(
            "{} did not promote: {} ({})",
            acquisition.route_id,
            decision.reason_code,
            decision
                .observed_schema_fingerprint
                .as_deref()
                .unwrap_or("no fingerprint")
        )
        .into());
    }
    Ok((acquisition, decision))
}

fn now_utc() -> Result<String, Failure> {
    Ok(
        time::OffsetDateTime::now_utc().format(time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ))?,
    )
}
