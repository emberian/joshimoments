//! Retention of one hot lease through the same durable admission path the census opened.
//!
//! Frames go in exactly as they arrived, through `joshi_admission::source_frames`. The lease's
//! coverage claim and every unobserved interval go in through `joshi_admission::source_drafts`,
//! which is the same entry point `source_frames` itself calls. Nothing here reserializes or
//! summarizes a provider payload, and no interval reaches the catalog without both boundaries.

use joshi_admission::{
    AdmissionPolicy, PublicStoreReceiptV1, Sha256Digest, SourceDraftBatch, SourceFrameInput,
    source_drafts, source_frames,
};
use joshi_domain::{
    CoverageId, OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp, ValueDigest,
};
use joshi_evidence::{Boundary, CoverageGap, CoverageScope, CoverageWindow, EvidenceDraft};
use joshi_sources::{
    ADAPTER_CONTRACT_VERSION, EvidenceContext, FrameDirection, LogicalSourceLocator,
    ProviderEventTime,
};
use joshi_store::{SourceRegistration, SqliteStore};
use serde::{Deserialize, Serialize};

use crate::{
    Result, SupervisorError,
    hot_lease::ledger::{LeaseLedger, SEVERITY_DEGRADED, SEVERITY_SCOPE_STOPPED},
};

/// Stable wire contract of one lease retention receipt.
pub const LEASE_RETENTION_CONTRACT: &str = "joshi.supervisor.hot_lease_retention/v1";

/// Durable source identity every Helius WebSocket frame is admitted under.
pub const WEBSOCKET_SOURCE_ID: &str = "helius.websocket.solana.v1";
/// Durable source namespace `joshi_admission` registers that source in.
pub const WEBSOCKET_SOURCE_NAMESPACE: &str = "read_only_market_source";
/// Coverage family that makes this a leased hot scope rather than a census sweep.
pub const HOT_LANE_FAMILY: &str = "hot_lane";
/// Provider subscription method this lease speaks. It appears in the redacted locator.
pub const SUBSCRIPTION_METHOD: &str = "logsSubscribe";

/// What one lease durably retained.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LeaseRetentionReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub coverage_id: String,
    pub gap_ids: Vec<String>,
    pub observation_batches: Vec<PublicStoreReceiptV1>,
    pub coverage_batches: Vec<PublicStoreReceiptV1>,
    pub retained_observations: u64,
    pub retained_payload_bytes: u64,
}

/// Everything one lease commit needs that the ledger itself has no authority to invent.
#[derive(Clone, Debug)]
pub struct LeaseCommitContext {
    /// Exact subject key the subscription filtered on.
    pub subject_key: String,
    /// Redacted, credential-free description of the subscription request.
    pub request_fingerprint_material: String,
    /// Local wall clock at which these bytes became durable.
    pub persisted_at: UtcTimestamp,
    /// Writer monotonic clock identity.
    pub writer_clock_id: String,
    /// Writer monotonic reading at commit.
    pub committed_mono_ns: u64,
    /// Observations admitted atomically in one batch.
    pub max_observations_per_batch: usize,
}

/// Retain every frame, then the lease's coverage claim and every unobserved interval.
///
/// Frames are committed first so that the coverage claim is later knowledge than the evidence it
/// describes. Gaps are partitioned by severity because the durable admission policy carries one
/// severity per batch, and an interval the scope stopped covering is not merely degraded.
///
/// # Errors
///
/// Returns an error when a frame cannot be losslessly adapted, a boundary is unrepresentable, or
/// the durable store refuses a batch.
pub fn commit_lease(
    store: &mut SqliteStore,
    ledger: &LeaseLedger,
    context: &LeaseCommitContext,
) -> Result<LeaseRetentionReceiptV1> {
    if context.max_observations_per_batch == 0 {
        return Err(SupervisorError::InvalidConfig(
            "a retention batch must admit at least one observation".into(),
        ));
    }
    let closed_at = ledger.closed_unix_ms().ok_or_else(|| {
        SupervisorError::InvalidState("a lease must be closed before it is retained".into())
    })?;

    let mut observation_batches = Vec::new();
    let mut retained_observations = 0_u64;
    let mut retained_payload_bytes = 0_u64;
    for (chunk_index, chunk) in ledger
        .frames()
        .chunks(context.max_observations_per_batch)
        .enumerate()
    {
        let mut frames = Vec::with_capacity(chunk.len());
        for retained in chunk {
            let received_at = utc_from_millis(retained.frame.received_at.0)?;
            let outbound = retained.frame.direction == FrameDirection::OutboundControl;
            frames.push(SourceFrameInput {
                frame: retained.frame.clone(),
                context: EvidenceContext {
                    occurrence_namespace: ledger.namespace().to_owned(),
                    redacted_request_fingerprint_material: context
                        .request_fingerprint_material
                        .clone(),
                    // Stream frames have no intra-batch parent: nothing in this lease caused a
                    // later frame to be delivered.
                    parent_acquisition_id: None,
                    locator: LogicalSourceLocator::HeliusWebSocket {
                        subscription: SUBSCRIPTION_METHOD,
                    },
                    source_variant: OpenVariant::known(retained.variant)?,
                    source_cursor: retained.slot.map(|slot| format!("slot:{slot}")),
                    source_events: Vec::new(),
                    // A logs notification names a slot, not a clock. No provider event time is
                    // asserted for any frame this lease retained.
                    provider_event_time: ProviderEventTime::Missing {
                        reason: "logsSubscribe frame states no provider event clock".to_owned(),
                    },
                    chain_slot: retained.slot,
                    transaction_index: None,
                    instruction_path: Vec::new(),
                    log_index: None,
                    // Commitment is a property of the subscription request; no delivered frame
                    // restates it, so no finality is asserted about the retained observation.
                    finality: None,
                    // A pushed frame has no request instant of its own: the acquisition begins
                    // when the frame arrives.
                    acquisition_started_at: received_at,
                    requested_at: outbound.then_some(received_at),
                    monotonic_clock_id: context.writer_clock_id.clone(),
                    acquisition_started_monotonic_ns: retained.accepted_mono_ns,
                    received_monotonic_ns: retained.accepted_mono_ns,
                    persisted_at: context.persisted_at,
                },
            });
            retained_payload_bytes = retained_payload_bytes
                .saturating_add(u64::try_from(retained.frame.body.len()).unwrap_or(u64::MAX));
        }
        let count = u64::try_from(frames.len()).unwrap_or(u64::MAX);
        let batch = source_frames(
            frames,
            // No source event and no cursor advance: this lease can name no natural key it did
            // not invent, and an observed slot is not authority to advance a durable cursor.
            Vec::new(),
            Vec::new(),
            StableString::new(format!(
                "lease-frames-{}-{chunk_index:04}",
                ledger.namespace()
            ))?,
            context.persisted_at,
            StableString::new(context.writer_clock_id.clone())?,
            context
                .committed_mono_ns
                .saturating_add(u64::try_from(chunk_index).unwrap_or_default()),
        )?;
        observation_batches.push(batch.commit(store)?);
        retained_observations = retained_observations.saturating_add(count);
    }
    let (coverage_id, gap_ids, coverage_batches) =
        commit_coverage(store, ledger, context, closed_at)?;

    Ok(LeaseRetentionReceiptV1 {
        contract: LEASE_RETENTION_CONTRACT.to_owned(),
        schema_version: 1,
        coverage_id,
        gap_ids,
        observation_batches,
        coverage_batches,
        retained_observations,
        retained_payload_bytes,
    })
}

/// Retain the lease's coverage claim and every interval of it that was not observed.
///
/// Gaps are partitioned by severity because the durable admission policy carries one severity per
/// batch, and an interval the scope stopped covering is not merely degraded.
fn commit_coverage(
    store: &mut SqliteStore,
    ledger: &LeaseLedger,
    context: &LeaseCommitContext,
    closed_at: i64,
) -> Result<(String, Vec<String>, Vec<PublicStoreReceiptV1>)> {
    let coverage_id = CoverageId::new(format!("coverage-{}", ledger.namespace()))?;
    let scope = CoverageScope {
        source_id: DomainSourceId::new(WEBSOCKET_SOURCE_ID)?,
        family: OpenVariant::known(HOT_LANE_FAMILY)?,
        subject: Some(StableString::new(context.subject_key.clone())?),
    };
    let window = CoverageWindow {
        coverage_id: coverage_id.clone(),
        scope: scope.clone(),
        lower: Boundary::Wall {
            value: utc_from_millis(ledger.opened_unix_ms())?,
        },
        upper: Some(Boundary::Wall {
            value: utc_from_millis(closed_at)?,
        }),
        state: OpenVariant::known("closed")?,
        available_at: context.persisted_at,
    };

    let mut coverage_batches = Vec::new();
    let mut gap_ids = Vec::new();
    for (severity_index, severity) in [SEVERITY_DEGRADED, SEVERITY_SCOPE_STOPPED]
        .into_iter()
        .enumerate()
    {
        let mut drafts = Vec::new();
        if severity_index == 0 {
            drafts.push(EvidenceDraft::CoverageWindow(window.clone()));
        }
        for gap in ledger.gaps().iter().filter(|gap| gap.severity == severity) {
            gap_ids.push(gap.gap_id.clone());
            drafts.push(EvidenceDraft::CoverageGap(CoverageGap {
                gap_id: CoverageId::new(gap.gap_id.clone())?,
                coverage_id: coverage_id.clone(),
                scope: scope.clone(),
                lower: Boundary::Wall {
                    value: utc_from_millis(gap.lower_unix_ms)?,
                },
                upper: Some(Boundary::Wall {
                    value: utc_from_millis(gap.upper_unix_ms)?,
                }),
                reason: OpenVariant::known(gap.reason.clone())?,
                detected_at: context.persisted_at,
            }));
        }
        if drafts.is_empty() {
            continue;
        }
        let batch = source_drafts(SourceDraftBatch {
            batch_id: StableString::new(format!(
                "lease-coverage-{}-{severity}",
                ledger.namespace()
            ))?,
            drafts,
            source_events: Vec::new(),
            cursor_advances: Vec::new(),
            registrations: vec![websocket_source_registration()?],
            policy: AdmissionPolicy {
                retention_class: StableString::new("public_source")?,
                content_encoding: None,
                force_external: false,
                gap_severity: StableString::new(severity)?,
            },
            committed_at: context.persisted_at,
            writer_clock_id: StableString::new(context.writer_clock_id.clone())?,
            committed_mono_ns: context
                .committed_mono_ns
                .saturating_add(1_000)
                .saturating_add(u64::try_from(severity_index).unwrap_or_default()),
            writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
        })?;
        coverage_batches.push(batch.commit(store)?);
    }

    Ok((coverage_id.as_str().to_owned(), gap_ids, coverage_batches))
}

/// The exact durable registration `joshi_admission::source_frames` emits for a Helius WebSocket
/// frame.
///
/// A coverage claim can outlive its evidence — a lease that never received a frame still owes an
/// exact gap — so the coverage batch must be able to register the source on its own. The recipe
/// is the versioned `joshi.source.registration.v1` material; `registration_matches_the_frame_path`
/// commits a real frame batch and then this registration into one catalog, so any drift surfaces
/// as an identity conflict instead of as silence.
///
/// # Errors
///
/// Returns an error when a registration wire value is invalid.
pub fn websocket_source_registration() -> Result<SourceRegistration> {
    let source_id = DomainSourceId::new(WEBSOCKET_SOURCE_ID)?;
    let collector_build = env!("CARGO_PKG_VERSION");
    let material = format!(
        "joshi.source.registration.v1\0{}\0{WEBSOCKET_SOURCE_NAMESPACE}\0{ADAPTER_CONTRACT_VERSION}\0{collector_build}",
        source_id.as_str()
    );
    Ok(SourceRegistration {
        source_id,
        namespace: StableString::new(WEBSOCKET_SOURCE_NAMESPACE)?,
        contract_version: StableString::new(ADAPTER_CONTRACT_VERSION)?,
        collector_build: StableString::new(collector_build)?,
        configuration_digest: ValueDigest::new(
            Sha256Digest::of_bytes(material.as_bytes()).to_string(),
        )?,
    })
}

/// Convert an exact Unix millisecond reading into a microsecond-aligned wire timestamp.
///
/// # Errors
///
/// Returns an error when the instant is outside the supported range.
pub fn utc_from_millis(millis: i64) -> Result<UtcTimestamp> {
    let value = time::OffsetDateTime::from_unix_timestamp_nanos(i128::from(millis) * 1_000_000)
        .map_err(|_| {
            SupervisorError::InvalidValue("wall instant is outside the supported range".into())
        })?;
    UtcTimestamp::new(value).map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}
