//! Executing one hot lease: one connection, one filtered subscription, one bounded window.
//!
//! The lease reserves its worst case from a run budget before any socket is opened, opens exactly
//! one Helius WebSocket connection carrying exactly one filtered subscription, reads until the
//! first exhausted ceiling, drains what the source had already read, and stops. Settlement is a
//! separate step so that the durable byte cost is known before the permit is returned.

use std::time::{Duration, Instant};

use joshi_acquisition_policy::HotLeaseTermsV1;
use joshi_sources::{
    BoundedIngress, HeliusConfig, HeliusSubscription, HeliusWsAdapter, SourceOutput, StreamClass,
    UnixMillis, WebSocketEndpoint, WebSocketExit, WebSocketRunner,
};
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc::Receiver;
use tokio_util::sync::CancellationToken;

use crate::{
    AttemptBudgetClaim, AttemptBudgetUsage, BudgetDimension, BudgetLedger, BudgetPermit,
    BudgetSnapshot, Result, RunBudgetLimits, SupervisorError,
    hot_lease::ledger::{LeaseLedger, LeaseSignal, LeaseStop},
};

/// Stable wire contract of one lease settlement.
pub const LEASE_SETTLEMENT_CONTRACT: &str = "joshi.supervisor.hot_lease_settlement/v1";

/// Milliseconds of in-flight overshoot the run budget allows past the leased window so that the
/// final drain and the socket close are inside the reservation rather than beyond it.
pub const LEASE_DRAIN_GRACE_MS: u64 = 5_000;

/// Hard ingress-rate ceiling for one lease, in bytes per second.
///
/// The only high-fidelity capture this project has taken measured unabridged two-program
/// `logsSubscribe` traffic at 11,943,303 bytes in 5.979 seconds, about 2.00 MB/s. A single-subject
/// filtered subscription must stay well under that; this ceiling is set at twice the measured
/// two-program rate so that a lease which somehow reaches it is a budget fact, not noise.
pub const LEASE_MAX_INGRESS_BYTES_PER_SECOND: u64 = 4 * 1024 * 1024;

/// Durable bytes reserved per ingress byte.
///
/// The retained frame envelope encodes the provider body as a JSON array of byte values, so one
/// ingress byte becomes several durable bytes. Eight is the reserved worst case.
pub const DURABLE_BYTES_PER_INGRESS_BYTE: u64 = 8;

/// How long the drain waits for outputs the source had already read before the stop.
const DRAIN_TIMEOUT: Duration = Duration::from_millis(2_500);

/// Exact settlement of one lease's reserved worst case against what it actually used.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LeaseSettlementV1 {
    pub contract: &'static str,
    pub schema_version: u64,
    pub claimed: AttemptBudgetClaim,
    pub used: AttemptBudgetUsage,
    pub snapshot: BudgetSnapshot,
    /// The first dimension the settlement found exceeded, when any was.
    pub violation: Option<BudgetDimension>,
}

/// One executed lease, before settlement.
#[derive(Debug)]
pub struct HotLeaseRun {
    pub ledger: LeaseLedger,
    pub budget: BudgetLedger,
    pub permit: BudgetPermit,
    /// Wall milliseconds from reservation to the socket being done.
    pub elapsed_ms: u64,
    /// Connections this run actually opened. The lease's ceiling is a maximum, not a quota.
    pub connections_opened: u64,
    /// Exit reason the source runner reported, when the runner finished before the drain gave up.
    pub source_exit_reason: Option<String>,
}

/// Build the run budget one lease preregisters before opening anything.
///
/// # Errors
///
/// Refuses terms whose window or ceilings cannot form a valid finite envelope.
pub fn lease_run_budget(terms: &HotLeaseTermsV1) -> Result<RunBudgetLimits> {
    let window_ms = terms.window_ms();
    if window_ms == 0 {
        return Err(SupervisorError::InvalidValue(
            "hot lease window must be at least one millisecond".into(),
        ));
    }
    let elapsed_ceiling = window_ms.saturating_add(LEASE_DRAIN_GRACE_MS);
    let limits = RunBudgetLimits {
        maximum_requests: terms.max_connections.get().max(1),
        // Pages are settled by exact equality, so this lease declares none and enforces its own
        // frame ceiling in the ledger instead.
        maximum_pages: 0,
        maximum_ingress_bytes: terms.max_ingress_bytes.get(),
        maximum_durable_bytes: terms
            .max_ingress_bytes
            .get()
            .saturating_mul(DURABLE_BYTES_PER_INGRESS_BYTE),
        maximum_provider_credits: terms.max_provider_credits.get(),
        maximum_ingress_bytes_per_second: Some(LEASE_MAX_INGRESS_BYTES_PER_SECOND),
        maximum_elapsed_ms: elapsed_ceiling,
        maximum_in_flight_attempts: 1,
        maximum_in_flight_elapsed_overshoot_ms: elapsed_ceiling,
    };
    limits.validate()?;
    Ok(limits)
}

/// The worst case one lease connection claims before any socket is opened.
#[must_use]
pub fn lease_attempt_claim(limits: RunBudgetLimits) -> AttemptBudgetClaim {
    AttemptBudgetClaim {
        requests: 1,
        pages: 0,
        maximum_ingress_bytes: limits.maximum_ingress_bytes,
        maximum_durable_bytes: limits.maximum_durable_bytes,
        maximum_provider_credits: limits.maximum_provider_credits,
        maximum_ingress_bytes_per_second: limits.maximum_ingress_bytes_per_second,
        maximum_elapsed_ms: limits.maximum_elapsed_ms,
    }
}

/// Open exactly one filtered subscription for the leased window and stop at the first ceiling.
///
/// # Errors
///
/// Returns an error when the endpoint or credential is invalid, the subscription is malformed,
/// the run budget refuses the reservation, or a retained frame cannot be measured.
pub async fn run_hot_lease(
    config: &HeliusConfig,
    terms: HotLeaseTermsV1,
    namespace: String,
    subscription: HeliusSubscription,
    process_start: Instant,
) -> Result<HotLeaseRun> {
    let limits = lease_run_budget(&terms)?;
    let claim = lease_attempt_claim(limits);
    let started = Instant::now();
    let mut budget = BudgetLedger::new(limits, 0)?;
    let permit = budget.reserve(claim, 0)?;

    let window = Duration::from_millis(terms.window_ms());
    let (endpoint, mut policy) = WebSocketEndpoint::helius(config)
        .map_err(|error| SupervisorError::InvalidConfig(error.to_string()))?;
    // Exactly one connection. A reconnect would be a second subscription this lease never
    // reserved, and its own unobserved interval; the lease stops and says so instead.
    policy.max_connection_attempts = Some(1);
    // A quiet subject must not be mistaken for a dead socket inside the leased window.
    policy.inactivity_timeout = window.saturating_add(Duration::from_millis(LEASE_DRAIN_GRACE_MS));

    let adapter = HeliusWsAdapter::new(vec![(subscription, StreamClass::LeasedHot)])
        .map_err(|error| SupervisorError::InvalidValue(error.message))?;
    let (ingress, mut receiver) = BoundedIngress::channel(config.ingress_capacity);
    let cancellation = CancellationToken::new();
    let (runner, _control) =
        WebSocketRunner::new(endpoint, policy, adapter, ingress, cancellation.clone(), 1);

    let opened_unix_ms = now_millis();
    let mut ledger = LeaseLedger::open(terms, namespace, opened_unix_ms)?;
    let handle = tokio::spawn(runner.run(UnixMillis(opened_unix_ms)));

    let deadline = tokio::time::Instant::now() + window;
    let stop = read_until_ceiling(&mut ledger, &mut receiver, deadline, process_start).await?;
    cancellation.cancel();
    // Everything the source already read belongs to this lease even though the lease is over.
    drain(&mut ledger, &mut receiver, process_start).await?;

    let exit = tokio::time::timeout(DRAIN_TIMEOUT, handle).await;
    let source_exit_reason = match exit {
        Ok(Ok(WebSocketExit { reason, .. })) => Some(reason.to_owned()),
        Ok(Err(_)) => Some("source_runner_task_failed".to_owned()),
        Err(_) => None,
    };
    ledger.close(now_millis(), stop);

    let elapsed_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    Ok(HotLeaseRun {
        ledger,
        budget,
        permit,
        elapsed_ms,
        connections_opened: 1,
        source_exit_reason,
    })
}

/// Read outputs until a ceiling is exhausted or the leased window elapses.
async fn read_until_ceiling(
    ledger: &mut LeaseLedger,
    receiver: &mut Receiver<SourceOutput>,
    deadline: tokio::time::Instant,
    process_start: Instant,
) -> Result<LeaseStop> {
    loop {
        tokio::select! {
            () = tokio::time::sleep_until(deadline) => return Ok(LeaseStop::WindowElapsed),
            item = receiver.recv() => {
                let Some(item) = item else {
                    return Ok(ledger.stop().cloned().unwrap_or(LeaseStop::RunnerExited {
                        reason: "source ingress closed".to_owned(),
                    }));
                };
                if ledger.accept(item, elapsed_nanos(process_start))? == LeaseSignal::Stop {
                    return Ok(ledger
                        .stop()
                        .cloned()
                        .unwrap_or(LeaseStop::IngressSaturated));
                }
            }
        }
    }
}

/// Accept every output the source had already produced before the cancellation landed.
async fn drain(
    ledger: &mut LeaseLedger,
    receiver: &mut Receiver<SourceOutput>,
    process_start: Instant,
) -> Result<()> {
    let until = tokio::time::Instant::now() + DRAIN_TIMEOUT;
    loop {
        let remaining = until.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            return Ok(());
        }
        match tokio::time::timeout(remaining, receiver.recv()).await {
            Ok(Some(item)) => {
                // The ledger may report Stop again; the lease is already over, so keep draining.
                let _ = ledger.accept(item, elapsed_nanos(process_start))?;
            }
            Ok(None) | Err(_) => return Ok(()),
        }
    }
}

/// Settle one lease's permit against exactly what it used.
///
/// Provider credits are charged at the reserved maximum: this boundary observes no provider
/// invoice, and charging the reserved worst case is the only direction that cannot understate.
///
/// # Errors
///
/// Returns an error when the permit is foreign; a dimension found exceeded is reported in the
/// settlement rather than raised, because the bytes were already read.
pub fn settle_lease(
    run: HotLeaseRun,
    durable_bytes: u64,
) -> Result<(LeaseLedger, LeaseSettlementV1)> {
    let HotLeaseRun {
        ledger,
        mut budget,
        permit,
        elapsed_ms,
        ..
    } = run;
    let claimed = permit.claim();
    let used = AttemptBudgetUsage {
        requests: 1,
        pages: 0,
        ingress_bytes: ledger.ingress_bytes(),
        durable_bytes,
        provider_credits: claimed.maximum_provider_credits,
        elapsed_ms,
    };
    let violation = budget.settlement_violation(&permit, used)?;
    match budget.settle(permit, used) {
        Ok(()) | Err(SupervisorError::AttemptBudgetExceeded) => {}
        Err(error) => return Err(error),
    }
    Ok((
        ledger,
        LeaseSettlementV1 {
            contract: LEASE_SETTLEMENT_CONTRACT,
            schema_version: 1,
            claimed,
            used,
            snapshot: budget.snapshot(elapsed_ms),
            violation,
        },
    ))
}

/// Local wall clock in Unix milliseconds.
#[must_use]
pub fn now_millis() -> i64 {
    let millis = time::OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000;
    i64::try_from(millis).unwrap_or(i64::MAX)
}

fn elapsed_nanos(process_start: Instant) -> u64 {
    u64::try_from(process_start.elapsed().as_nanos()).unwrap_or(u64::MAX)
}
