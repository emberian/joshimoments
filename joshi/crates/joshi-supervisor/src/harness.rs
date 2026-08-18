use crate::{
    AttemptKind, OperationKey, PendingSegment, ProtectionProfile, QueueClass, ReservationRequest,
    Result, RetryDecision, RetryTrigger, SourceIngressError, SourceKey, SourceOutputAdapter,
    Supervisor, SupervisorError,
};
use bytes::Bytes;
use joshi_domain::{
    BatchDigest, OpenVariant, SourceId as DomainSourceId, StableString, UtcTimestamp, ValueDigest,
};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch, EvidenceDraft};
use joshi_sources::{
    ContentType, EvidenceContext, LogicalSourceLocator, ProviderEventTime, RawSourceFrame,
    SourceId, SourceOutput, StreamClass, Transport, UnixMillis,
};
use joshi_spool::{EvidenceBatchEntry, ProtectionDomainId, SpoolEntry};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::time::Duration;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FakeProviderSchedule {
    pub contract: String,
    pub duration_seconds: u64,
    pub frame_interval_seconds: u64,
    pub disconnect_every_frames: Option<u64>,
    pub retryable_failure_every_frames: Option<u64>,
    pub duplicate_every_frames: Option<u64>,
    pub payload_bytes: usize,
    pub realtime: bool,
}

impl FakeProviderSchedule {
    /// Validate a bounded deterministic schedule.
    ///
    /// # Errors
    ///
    /// Refuses zero/inconsistent duration, event cadence, or payload bounds.
    pub fn validate(&self) -> Result<()> {
        if self.contract != "joshi.supervisor.fake_provider_schedule.v1"
            || self.duration_seconds == 0
            || self.frame_interval_seconds == 0
            || self.frame_interval_seconds > self.duration_seconds
            || self.payload_bytes == 0
            || self.payload_bytes > 4 * 1024 * 1024
            || [
                self.disconnect_every_frames,
                self.retryable_failure_every_frames,
                self.duplicate_every_frames,
            ]
            .into_iter()
            .flatten()
            .any(|value| value == 0)
        {
            return Err(SupervisorError::InvalidConfig(
                "fake-provider schedule is invalid or unbounded".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FakeProviderReport {
    pub contract: String,
    pub virtual_duration_seconds: u64,
    pub realtime: bool,
    pub frames_durable: u64,
    pub duplicate_frames: u64,
    pub retry_decisions: u64,
    pub explicit_attempt_gaps: u64,
    pub connection_generations: u64,
    pub final_ready_segments: u64,
    pub final_replay_digest: String,
    pub false_cursor_advances: u64,
    pub shutdown: crate::ShutdownReport,
    pub authority: String,
}

pub struct FakeProviderHarness {
    schedule: FakeProviderSchedule,
}

impl FakeProviderHarness {
    /// Build a deterministic no-network provider harness.
    ///
    /// # Errors
    ///
    /// Refuses an invalid or unbounded schedule.
    pub fn new(schedule: FakeProviderSchedule) -> Result<Self> {
        schedule.validate()?;
        Ok(Self { schedule })
    }

    /// Run with a virtual clock by default, or wall-clock pacing when `realtime` is true. The
    /// provider seam is `SourceOutput`; no provider client or socket is constructed.
    ///
    /// # Errors
    ///
    /// Stops on the first reservation, queue, durability, replay, or shutdown failure.
    #[allow(clippy::too_many_lines)]
    pub fn run(
        &self,
        supervisor: &mut Supervisor,
        started_at: UtcTimestamp,
    ) -> Result<FakeProviderReport> {
        let frames = self.schedule.duration_seconds / self.schedule.frame_interval_seconds;
        let mut frames_durable = 0_u64;
        let mut duplicate_frames = 0_u64;
        let mut retry_decisions = 0_u64;
        let mut explicit_attempt_gaps = 0_u64;
        let mut connection_generations = 0_u64;
        let mut last_body = None;

        for sequence in 1..=frames {
            let elapsed = sequence.saturating_mul(self.schedule.frame_interval_seconds);
            let at = add_seconds(started_at, elapsed)?;
            if self.schedule.realtime {
                std::thread::sleep(Duration::from_secs(self.schedule.frame_interval_seconds));
            }

            if divisible(sequence, self.schedule.disconnect_every_frames) {
                let connection = supervisor.reserve(
                    request(AttemptKind::WebSocketConnection, at, "fake-websocket"),
                    at,
                )?;
                connection_generations = connection_generations.saturating_add(1);
                supervisor.decide_retry(&connection, RetryTrigger::Inactivity, None, at)?;
                supervisor.abandon(&connection, OpenVariant::known("fake_disconnect")?, at)?;
                explicit_attempt_gaps = explicit_attempt_gaps.saturating_add(1);
            }

            if divisible(sequence, self.schedule.retryable_failure_every_frames) {
                let operation = format!("fake-http-{sequence}");
                let failed =
                    supervisor.reserve(request(AttemptKind::HttpRequest, at, &operation), at)?;
                let decision = supervisor.decide_retry(
                    &failed,
                    RetryTrigger::ProviderUnavailable,
                    None,
                    at,
                )?;
                retry_decisions = retry_decisions.saturating_add(1);
                supervisor.abandon(&failed, OpenVariant::known("fake_retryable_failure")?, at)?;
                explicit_attempt_gaps = explicit_attempt_gaps.saturating_add(1);
                if matches!(decision, RetryDecision::Scheduled { .. }) {
                    let retry = supervisor.reserve_retry(&failed, at)?;
                    supervisor.abandon(&retry, OpenVariant::known("fake_retry_not_issued")?, at)?;
                    explicit_attempt_gaps = explicit_attempt_gaps.saturating_add(1);
                }
            }

            let reservation =
                supervisor.reserve(request(AttemptKind::Poll, at, "fake-poll"), at)?;
            let duplicate = divisible(sequence, self.schedule.duplicate_every_frames);
            let body = if duplicate {
                duplicate_frames = duplicate_frames.saturating_add(1);
                last_body
                    .clone()
                    .unwrap_or_else(|| payload(sequence, self.schedule.payload_bytes))
            } else {
                payload(sequence, self.schedule.payload_bytes)
            };
            last_body = Some(body.clone());
            let output = SourceOutput::Frame(RawSourceFrame {
                contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
                source: SourceId::Other("fake_provider".into()),
                transport: Transport::Fixture,
                stream_class: StreamClass::BroadCensus,
                direction: joshi_sources::FrameDirection::Inbound,
                content_type: ContentType::Json,
                received_at: unix_millis(at)?,
                connection_epoch: reservation.generation.get(),
                sequence,
                http_status: Some(200),
                safe_headers: Vec::new(),
                body: Bytes::from(body),
            });
            let mut adapter = FakeFrameAdapter { at, sequence };
            match supervisor.enqueue_source_output(&mut adapter, &reservation, output) {
                Ok(()) => {}
                Err(SourceIngressError::Saturated(item)) => {
                    supervisor.stop_saturated(item, at)?;
                    return Err(SupervisorError::InvalidState(
                        "fake-provider evidence queue saturated".into(),
                    ));
                }
                Err(SourceIngressError::Adapter(error)) => return Err(error),
            }
            match supervisor.drain_one(at) {
                Ok(Some(_)) => {}
                Ok(None) => {
                    return Err(SupervisorError::InvalidState(
                        "queued fake frame was not drained".into(),
                    ));
                }
                Err(
                    error @ (SupervisorError::DailySpoolBudget { .. }
                    | SupervisorError::Spool(joshi_spool::SpoolError::Degraded(_))),
                ) => {
                    supervisor.stop_front_for_pressure(
                        OpenVariant::known("spool_budget_pressure")?,
                        at,
                    )?;
                    return Err(error);
                }
                Err(error) => return Err(error),
            }
            frames_durable = frames_durable.saturating_add(1);
        }

        let ended_at = add_seconds(started_at, self.schedule.duration_seconds)?;
        let shutdown = supervisor.shutdown(ended_at)?;
        let replay = crate::replay_spool(supervisor.spool(), &std::collections::BTreeMap::new())?;
        Ok(FakeProviderReport {
            contract: "joshi.supervisor.fake_provider_report.v1".into(),
            virtual_duration_seconds: self.schedule.duration_seconds,
            realtime: self.schedule.realtime,
            frames_durable,
            duplicate_frames,
            retry_decisions,
            explicit_attempt_gaps,
            connection_generations,
            final_ready_segments: u64::try_from(replay.segments.len()).unwrap_or(u64::MAX),
            final_replay_digest: replay.ordered_closure_digest,
            false_cursor_advances: 0,
            shutdown,
            authority: crate::AUTHORITY_CEILING.into(),
        })
    }
}

fn request(kind: AttemptKind, at: UtcTimestamp, operation: &str) -> ReservationRequest {
    ReservationRequest {
        source_key: SourceKey::new("fake-provider").expect("fixed source key"),
        operation_key: OperationKey::new(operation).expect("fixed operation key"),
        kind,
        scope: CoverageScope {
            source_id: DomainSourceId::new("source.other.fake_provider").expect("fixed source ID"),
            family: OpenVariant::known("fake_provider").expect("fixed coverage family"),
            subject: None,
        },
        lower: Boundary::Wall { value: at },
        protection: ProtectionProfile::PublicIntegrity {
            domain: ProtectionDomainId::new("public-fake-provider")
                .expect("fixed protection domain"),
        },
        run: None,
        execution_claim: None,
        provider_plan: None,
    }
}

struct FakeFrameAdapter {
    at: UtcTimestamp,
    sequence: u64,
}

impl SourceOutputAdapter for FakeFrameAdapter {
    fn prepare(
        &mut self,
        reservation: &crate::AttemptReservation,
        output: SourceOutput,
    ) -> Result<PendingSegment> {
        let entry = adapt_output(output, reservation, self.at, self.sequence)?;
        PendingSegment::new(reservation.clone(), entry, QueueClass::Evidence)
    }
}

fn adapt_output(
    output: SourceOutput,
    reservation: &crate::AttemptReservation,
    at: UtcTimestamp,
    sequence: u64,
) -> Result<SpoolEntry> {
    let SourceOutput::Frame(frame) = output else {
        return Err(SupervisorError::InvalidValue(
            "fake harness expected a frame output".into(),
        ));
    };
    let draft = joshi_sources::observation_draft(
        frame,
        EvidenceContext {
            occurrence_namespace: reservation.installation_id.clone(),
            redacted_request_fingerprint_material: "fixture:fake-provider".into(),
            parent_acquisition_id: None,
            locator: LogicalSourceLocator::Fixture {
                name: "24h-fake-provider".into(),
            },
            source_variant: OpenVariant::known("fake_frame")?,
            source_cursor: None,
            source_events: Vec::new(),
            provider_event_time: ProviderEventTime::Missing {
                reason: "fixture_has_no_provider_event_clock".into(),
            },
            chain_slot: None,
            transaction_index: None,
            instruction_path: Vec::new(),
            log_index: None,
            finality: None,
            acquisition_started_at: reservation.reserved_at,
            requested_at: Some(reservation.reserved_at),
            monotonic_clock_id: format!("mono:{}", reservation.installation_id),
            acquisition_started_monotonic_ns: sequence.saturating_mul(1_000_000),
            received_monotonic_ns: sequence.saturating_mul(1_000_000).saturating_add(1),
            persisted_at: at,
        },
    )?;
    let EvidenceDraft::Observation(observation) = draft else {
        return Err(SupervisorError::InvalidValue(
            "source frame did not produce an observation".into(),
        ));
    };
    let mut batch = DurableIngestBatch {
        contract_version: StableString::new(joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION)?,
        batch_id: StableString::new(format!("batch:{}", reservation.reservation_id))?,
        expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))?,
        observations: vec![observation],
        source_events: Vec::new(),
        assertions: Vec::new(),
        coverage_windows: Vec::new(),
        coverage_gaps: Vec::new(),
        coverage_recoveries: Vec::new(),
        cursor_advances: Vec::new(),
    };
    batch.expected_digest = joshi_store::SqliteStore::canonical_batch_digest(&batch)
        .map_err(|error| SupervisorError::InvalidValue(error.to_string()))?;
    let policy =
        br#"{"observationStorage":{"fixture":"public_source"},"coverageGapSeverity":{}}"#.to_vec();
    let mut digest = Sha256::new();
    digest.update(b"joshi.supervisor.fake-admission.v1\0");
    digest.update(batch.expected_digest.as_str().as_bytes());
    digest.update(b"\0");
    digest.update(&policy);
    let admission = ValueDigest::new(format!("sha256:{:x}", digest.finalize()))?;
    Ok(SpoolEntry::EvidenceBatch(EvidenceBatchEntry::from_batch(
        &batch,
        "joshi.store.policy.v1",
        policy,
        Some(&admission),
    )?))
}

fn payload(sequence: u64, minimum_bytes: usize) -> Vec<u8> {
    let prefix = format!(r#"{{"sequence":"{sequence}","padding":""#);
    let suffix = b"\"}";
    let padding = minimum_bytes.saturating_sub(prefix.len() + suffix.len());
    let mut bytes = prefix.into_bytes();
    bytes.resize(bytes.len().saturating_add(padding), b'x');
    bytes.extend_from_slice(suffix);
    bytes
}

fn divisible(value: u64, divisor: Option<u64>) -> bool {
    divisor.is_some_and(|divisor| value.is_multiple_of(divisor))
}

fn add_seconds(value: UtcTimestamp, seconds: u64) -> Result<UtcTimestamp> {
    let seconds = i64::try_from(seconds)
        .map_err(|_| SupervisorError::InvalidValue("virtual time is too large".into()))?;
    let value = value
        .as_datetime()
        .checked_add(time::Duration::seconds(seconds))
        .ok_or_else(|| SupervisorError::InvalidValue("virtual time overflow".into()))?;
    UtcTimestamp::new(value).map_err(|error| SupervisorError::InvalidValue(error.to_string()))
}

fn unix_millis(value: UtcTimestamp) -> Result<UnixMillis> {
    let millis = value.as_datetime().unix_timestamp_nanos() / 1_000_000;
    i64::try_from(millis)
        .map(UnixMillis)
        .map_err(|_| SupervisorError::InvalidValue("timestamp is outside UnixMillis".into()))
}
