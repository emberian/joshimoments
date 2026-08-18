use crate::model::{
    ArtifactKind, BudgetKind, Component, GapKind, HealthReadiness, MetricName, MetricUnit,
    OperationalHealthV1, QuarantineClass, ResourceKind, SourceFamily, StatusClass, SupervisorPhase,
};
use crate::pressure::{DrainAssessment, RecoveryDrainWindowV1, assess_recovery_drain};
use crate::{OperationalError, Result};
use joshi_domain::{UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};

/// Finite-cardinality operational metric batch contract.
pub const METRIC_BATCH_CONTRACT: &str = "joshi.operational.metrics/v1";
const MAX_METRICS: usize = 512;

/// One metric whose entire label space is represented by closed enums.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetricSampleV1 {
    pub name: MetricName,
    pub component: Component,
    pub source_family: Option<SourceFamily>,
    pub status_class: Option<StatusClass>,
    pub resource_kind: Option<ResourceKind>,
    pub budget_kind: Option<BudgetKind>,
    pub artifact_kind: Option<ArtifactKind>,
    pub gap_kind: Option<GapKind>,
    pub quarantine_class: Option<QuarantineClass>,
    pub value: WireU64,
    pub unit: MetricUnit,
}

type MetricKey = (
    MetricName,
    Component,
    Option<SourceFamily>,
    Option<StatusClass>,
    Option<ResourceKind>,
    Option<BudgetKind>,
    Option<ArtifactKind>,
    Option<GapKind>,
    Option<QuarantineClass>,
);

impl MetricSampleV1 {
    fn key(&self) -> MetricKey {
        (
            self.name,
            self.component,
            self.source_family,
            self.status_class,
            self.resource_kind,
            self.budget_kind,
            self.artifact_kind,
            self.gap_kind,
            self.quarantine_class,
        )
    }

    fn validate(&self) -> Result<()> {
        let label_count = [
            self.source_family.is_some(),
            self.status_class.is_some(),
            self.resource_kind.is_some(),
            self.budget_kind.is_some(),
            self.artifact_kind.is_some(),
            self.gap_kind.is_some(),
            self.quarantine_class.is_some(),
        ]
        .into_iter()
        .filter(|value| *value)
        .count();
        match self.name {
            MetricName::CurrentGeneration
            | MetricName::LastReservationAgeMilliseconds
            | MetricName::LastDurableFrameAgeMilliseconds
            | MetricName::PendingReservationCount
            | MetricName::RetryCount
            | MetricName::NextRetryDelayMilliseconds => {
                if self.source_family.is_none()
                    || self.component != Component::Source
                    || self.resource_kind.is_some()
                    || self.budget_kind.is_some()
                    || self.artifact_kind.is_some()
                    || self.gap_kind.is_some()
                    || self.quarantine_class.is_some()
                {
                    return Err(OperationalError::Invalid(
                        "source metric has an invalid finite label set",
                    ));
                }
            }
            MetricName::ArtifactAgeMilliseconds => {
                if self.artifact_kind.is_none() || label_count > 2 {
                    return Err(OperationalError::Invalid(
                        "artifact age requires only artifact/status labels",
                    ));
                }
            }
            MetricName::ResourceObserved | MetricName::ResourceLimit => {
                if self.resource_kind.is_none() || label_count > 2 {
                    return Err(OperationalError::Invalid(
                        "resource metric requires only resource/status labels",
                    ));
                }
            }
            MetricName::BudgetRemaining => {
                if self.budget_kind.is_none() || label_count > 2 {
                    return Err(OperationalError::Invalid(
                        "budget metric requires only budget/status labels",
                    ));
                }
            }
            MetricName::OpenGapCount => {
                if self.gap_kind.is_none() || label_count != 1 {
                    return Err(OperationalError::Invalid(
                        "gap metric requires exactly one finite gap-kind label",
                    ));
                }
            }
            MetricName::QuarantineCount => {
                if self.quarantine_class.is_none() || label_count != 1 {
                    return Err(OperationalError::Invalid(
                        "quarantine metric requires exactly one finite class label",
                    ));
                }
            }
            _ => {
                if self.source_family.is_some()
                    || self.resource_kind.is_some()
                    || self.budget_kind.is_some()
                    || self.artifact_kind.is_some()
                    || self.gap_kind.is_some()
                    || self.quarantine_class.is_some()
                {
                    return Err(OperationalError::Invalid(
                        "unscoped metric contains an unrelated label",
                    ));
                }
            }
        }
        Ok(())
    }
}

/// Canonically ordered metric batch derived from one validated health snapshot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetricBatchV1 {
    pub contract: String,
    pub observed_at: UtcTimestamp,
    pub samples: Vec<MetricSampleV1>,
}

impl MetricBatchV1 {
    /// Validates the fixed contract, bound, exact ordering, uniqueness, and label grammar.
    ///
    /// # Errors
    ///
    /// Refuses open-cardinality or mismatched dimensions and duplicate/unsorted series.
    pub fn validate(&self) -> Result<()> {
        if self.contract != METRIC_BATCH_CONTRACT {
            return Err(OperationalError::Contract {
                expected: METRIC_BATCH_CONTRACT,
                received: self.contract.clone(),
            });
        }
        if self.samples.len() > MAX_METRICS {
            return Err(OperationalError::BoundExceeded {
                field: "metricSamples",
                maximum: u64::try_from(MAX_METRICS).unwrap_or(u64::MAX),
            });
        }
        let mut prior = None;
        for sample in &self.samples {
            sample.validate()?;
            let key = sample.key();
            if prior.as_ref().is_some_and(|value| value >= &key) {
                return Err(OperationalError::Invalid(
                    "metric samples must be strictly sorted and unique by finite key",
                ));
            }
            prior = Some(key);
        }
        Ok(())
    }

    /// Builds finite-cardinality metrics from a semantically valid health snapshot.
    ///
    /// # Errors
    ///
    /// Returns an error when the health snapshot or produced metric grammar is invalid.
    pub fn from_health(
        health: &OperationalHealthV1,
        health_contract: &'static str,
    ) -> Result<Self> {
        Self::from_health_and_recovery(health, health_contract, None, None)
    }

    /// Builds health metrics and, when supplied, fixed-window recovery arrival/drain metrics.
    ///
    /// # Errors
    ///
    /// Refuses a recovery window without its target, an empty-backlog target evaluation, or an
    /// inconsistent recovery balance.
    #[allow(clippy::too_many_lines)] // One deterministic projection keeps the metric vocabulary auditable.
    pub fn from_health_and_recovery(
        health: &OperationalHealthV1,
        health_contract: &'static str,
        recovery: Option<&RecoveryDrainWindowV1>,
        minimum_drain_to_arrival_ppm: Option<WireU64>,
    ) -> Result<Self> {
        health.validate(health_contract)?;
        let mut samples = Vec::new();
        push(
            &mut samples,
            MetricName::ReadinessCode,
            Component::Supervisor,
            readiness_code(health.readiness),
            MetricUnit::Code,
        );
        push(
            &mut samples,
            MetricName::SupervisorPhaseCode,
            Component::Supervisor,
            phase_code(health.supervisor.phase),
            MetricUnit::Code,
        );
        push(
            &mut samples,
            MetricName::RestartCount,
            Component::Supervisor,
            health.supervisor.restart_count.get(),
            MetricUnit::Count,
        );
        push(
            &mut samples,
            MetricName::ShutdownDeadlineExceededCount,
            Component::Supervisor,
            health.supervisor.shutdown_deadline_exceeded_count.get(),
            MetricUnit::Count,
        );
        for source in &health.sources {
            for (name, value, unit) in [
                (
                    MetricName::CurrentGeneration,
                    source.generation_sequence.get(),
                    MetricUnit::Count,
                ),
                (
                    MetricName::PendingReservationCount,
                    source.pending_reservations.get(),
                    MetricUnit::Count,
                ),
                (
                    MetricName::RetryCount,
                    source.retry_count.get(),
                    MetricUnit::Count,
                ),
            ] {
                samples.push(MetricSampleV1 {
                    name,
                    component: Component::Source,
                    source_family: Some(source.source_family),
                    status_class: Some(source.status),
                    resource_kind: None,
                    budget_kind: None,
                    artifact_kind: None,
                    gap_kind: None,
                    quarantine_class: None,
                    value: WireU64::new(value),
                    unit,
                });
            }
            for (name, value) in [
                (
                    MetricName::LastReservationAgeMilliseconds,
                    source.last_reservation_age_ms,
                ),
                (
                    MetricName::LastDurableFrameAgeMilliseconds,
                    source.last_durable_frame_age_ms,
                ),
                (
                    MetricName::NextRetryDelayMilliseconds,
                    source.next_retry_delay_ms,
                ),
            ] {
                if let Some(value) = value {
                    samples.push(MetricSampleV1 {
                        name,
                        component: Component::Source,
                        source_family: Some(source.source_family),
                        status_class: Some(source.status),
                        resource_kind: None,
                        budget_kind: None,
                        artifact_kind: None,
                        gap_kind: None,
                        quarantine_class: None,
                        value,
                        unit: MetricUnit::Milliseconds,
                    });
                }
            }
        }
        push_queue_spool_catalog(&mut samples, health);
        if let Some(replica) = &health.replica {
            for (name, value, unit) in [
                (
                    MetricName::ReplicaGeneration,
                    replica.generation_sequence.get(),
                    MetricUnit::Count,
                ),
                (
                    MetricName::ReplicaUnackedBytes,
                    replica.unacked_bytes.get(),
                    MetricUnit::Bytes,
                ),
            ] {
                push(&mut samples, name, Component::Replica, value, unit);
            }
            push_optional(
                &mut samples,
                MetricName::ReplicaOldestUnackedAgeMilliseconds,
                Component::Replica,
                replica.oldest_unacked_age_ms,
            );
            push_optional(
                &mut samples,
                MetricName::ReplicaAckLagMilliseconds,
                Component::Replica,
                replica.ack_lag_ms,
            );
        }
        let mut gap_counts = std::collections::BTreeMap::new();
        for gap in &health.coverage.open_gaps {
            *gap_counts.entry(gap.kind).or_insert(0_u64) += 1;
        }
        for (kind, value) in gap_counts {
            samples.push(MetricSampleV1 {
                name: MetricName::OpenGapCount,
                component: Component::Catalog,
                source_family: None,
                status_class: None,
                resource_kind: None,
                budget_kind: None,
                artifact_kind: None,
                gap_kind: Some(kind),
                quarantine_class: None,
                value: WireU64::new(value),
                unit: MetricUnit::Count,
            });
        }
        for row in &health.quarantine {
            samples.push(MetricSampleV1 {
                name: MetricName::QuarantineCount,
                component: Component::Normalizer,
                source_family: None,
                status_class: None,
                resource_kind: None,
                budget_kind: None,
                artifact_kind: None,
                gap_kind: None,
                quarantine_class: Some(row.class),
                value: row.count,
                unit: MetricUnit::Count,
            });
        }
        for artifact in &health.artifacts {
            if let Some(age) = artifact.age_ms {
                samples.push(MetricSampleV1 {
                    name: MetricName::ArtifactAgeMilliseconds,
                    component: artifact_component(artifact.kind),
                    source_family: None,
                    status_class: Some(artifact.status),
                    resource_kind: None,
                    budget_kind: None,
                    artifact_kind: Some(artifact.kind),
                    gap_kind: None,
                    quarantine_class: None,
                    value: age,
                    unit: MetricUnit::Milliseconds,
                });
            }
        }
        for resource in &health.resources {
            let unit = resource_unit(resource.kind);
            for (name, value) in [
                (MetricName::ResourceObserved, resource.observed),
                (MetricName::ResourceLimit, resource.limit_or_floor),
            ] {
                samples.push(MetricSampleV1 {
                    name,
                    component: Component::Host,
                    source_family: None,
                    status_class: Some(resource.status),
                    resource_kind: Some(resource.kind),
                    budget_kind: None,
                    artifact_kind: None,
                    gap_kind: None,
                    quarantine_class: None,
                    value,
                    unit,
                });
            }
        }
        for budget in &health.budgets {
            samples.push(MetricSampleV1 {
                name: MetricName::BudgetRemaining,
                component: Component::Supervisor,
                source_family: None,
                status_class: Some(budget.status),
                resource_kind: None,
                budget_kind: Some(budget.kind),
                artifact_kind: None,
                gap_kind: None,
                quarantine_class: None,
                value: budget.remaining,
                unit: match budget.unit {
                    crate::BudgetUnit::Count => MetricUnit::Count,
                    crate::BudgetUnit::Bytes => MetricUnit::Bytes,
                    crate::BudgetUnit::Credits => MetricUnit::Credits,
                    crate::BudgetUnit::NativeAtoms => MetricUnit::NativeAtoms,
                    crate::BudgetUnit::CurrencyMinorUnits => MetricUnit::CurrencyMinorUnits,
                },
            });
        }
        match (recovery, minimum_drain_to_arrival_ppm) {
            (Some(window), Some(target)) => {
                if assess_recovery_drain(window, target)? == DrainAssessment::NotApplicableNoBacklog
                {
                    return Err(OperationalError::Invalid(
                        "recovery drain metrics require a nonzero starting backlog",
                    ));
                }
                for (name, value, unit) in [
                    (
                        MetricName::RecoveryArrivalRecords,
                        window.admitted_arrival_records.get(),
                        MetricUnit::Count,
                    ),
                    (
                        MetricName::RecoveryDrainRecords,
                        window.durably_drained_records.get(),
                        MetricUnit::Count,
                    ),
                    (
                        MetricName::RecoveryBacklogRecords,
                        window.backlog_end_records.get(),
                        MetricUnit::Count,
                    ),
                    (
                        MetricName::RecoveryArrivalBytes,
                        window.admitted_arrival_bytes.get(),
                        MetricUnit::Bytes,
                    ),
                    (
                        MetricName::RecoveryDrainBytes,
                        window.durably_drained_bytes.get(),
                        MetricUnit::Bytes,
                    ),
                    (
                        MetricName::RecoveryBacklogBytes,
                        window.backlog_end_bytes.get(),
                        MetricUnit::Bytes,
                    ),
                ] {
                    push(&mut samples, name, Component::Catalog, value, unit);
                }
            }
            (None, None) => {}
            _ => {
                return Err(OperationalError::Invalid(
                    "recovery metrics require both a window and drain target",
                ));
            }
        }
        samples.sort_by_key(MetricSampleV1::key);
        let batch = Self {
            contract: METRIC_BATCH_CONTRACT.to_owned(),
            observed_at: health.observed_at,
            samples,
        };
        batch.validate()?;
        Ok(batch)
    }
}

// Keeping the finite metric mapping in one flat table makes label/cardinality review auditable.
#[allow(clippy::too_many_lines)]
fn push_queue_spool_catalog(samples: &mut Vec<MetricSampleV1>, health: &OperationalHealthV1) {
    for (name, component, value, unit) in [
        (
            MetricName::QueueRecordCount,
            Component::EvidenceQueue,
            health.evidence_queue.records.used.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::QueueMaximumRecords,
            Component::EvidenceQueue,
            health.evidence_queue.records.maximum.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::QueueByteCount,
            Component::EvidenceQueue,
            health.evidence_queue.bytes.used.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::QueueMaximumBytes,
            Component::EvidenceQueue,
            health.evidence_queue.bytes.maximum.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::QueueControlReserveRecords,
            Component::EvidenceQueue,
            health.evidence_queue.records.control_reserve.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::QueueControlReserveBytes,
            Component::EvidenceQueue,
            health.evidence_queue.bytes.control_reserve.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::SaturationCount,
            Component::EvidenceQueue,
            health.evidence_queue.saturation.incident_count.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::SpoolReadySegmentCount,
            Component::Spool,
            health.spool.ready_segment_count.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::SpoolReadyBytes,
            Component::Spool,
            health.spool.ready_bytes.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::SpoolUsedBytes,
            Component::Spool,
            health.spool.used_bytes.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::SpoolMaximumBytes,
            Component::Spool,
            health.spool.maximum_bytes.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::SpoolControlReserveBytes,
            Component::Spool,
            health.spool.control_reserve_bytes.get(),
            MetricUnit::Bytes,
        ),
        (
            MetricName::SpoolDegradedCode,
            Component::Spool,
            u64::from(health.spool.degraded),
            MetricUnit::Code,
        ),
        (
            MetricName::CatalogUnackedSegmentCount,
            Component::Catalog,
            health.catalog.unacked_segment_count.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::CatalogUnackedBatchCount,
            Component::Catalog,
            health.catalog.unacked_batch_count.get(),
            MetricUnit::Count,
        ),
        (
            MetricName::CatalogUnackedBytes,
            Component::Catalog,
            health.catalog.unacked_bytes.get(),
            MetricUnit::Bytes,
        ),
    ] {
        push(samples, name, component, value, unit);
    }
    push_optional(
        samples,
        MetricName::SpoolOldestAgeMilliseconds,
        Component::Spool,
        health.spool.oldest_ready_age_ms,
    );
    push_optional(
        samples,
        MetricName::CatalogOldestUnackedAgeMilliseconds,
        Component::Catalog,
        health.catalog.oldest_unacked_age_ms,
    );
    push_optional(
        samples,
        MetricName::CatalogLastExactAckAgeMilliseconds,
        Component::Catalog,
        health.catalog.last_exact_ack_age_ms,
    );
    push(
        samples,
        MetricName::DriftCount,
        Component::Normalizer,
        health.normalizer_drift_count.get(),
        MetricUnit::Count,
    );
}

fn push(
    samples: &mut Vec<MetricSampleV1>,
    name: MetricName,
    component: Component,
    value: u64,
    unit: MetricUnit,
) {
    samples.push(MetricSampleV1 {
        name,
        component,
        source_family: None,
        status_class: None,
        resource_kind: None,
        budget_kind: None,
        artifact_kind: None,
        gap_kind: None,
        quarantine_class: None,
        value: WireU64::new(value),
        unit,
    });
}

fn push_optional(
    samples: &mut Vec<MetricSampleV1>,
    name: MetricName,
    component: Component,
    value: Option<WireU64>,
) {
    if let Some(value) = value {
        push(
            samples,
            name,
            component,
            value.get(),
            MetricUnit::Milliseconds,
        );
    }
}

const fn readiness_code(value: HealthReadiness) -> u64 {
    match value {
        HealthReadiness::Ready => 0,
        HealthReadiness::Degraded => 1,
        HealthReadiness::NotReady => 2,
        HealthReadiness::Stopped => 3,
    }
}

const fn phase_code(value: SupervisorPhase) -> u64 {
    match value {
        SupervisorPhase::Starting => 0,
        SupervisorPhase::Running => 1,
        SupervisorPhase::Draining => 2,
        SupervisorPhase::Stopping => 3,
        SupervisorPhase::Stopped => 4,
        SupervisorPhase::Failed => 5,
    }
}

const fn artifact_component(value: ArtifactKind) -> Component {
    match value {
        ArtifactKind::Projection => Component::Projection,
        ArtifactKind::GlassPresentation | ArtifactKind::GlassCommandCapture => Component::Glass,
        ArtifactKind::ExportSnapshot => Component::Export,
        ArtifactKind::AnalysisArtifact => Component::Analysis,
    }
}

const fn resource_unit(value: ResourceKind) -> MetricUnit {
    match value {
        ResourceKind::CpuMillicores => MetricUnit::Millicores,
        ResourceKind::RssBytes | ResourceKind::DiskFreeBytes => MetricUnit::Bytes,
        ResourceKind::FileDescriptors => MetricUnit::Count,
        ResourceKind::DiskFreeInodes => MetricUnit::Inodes,
        ResourceKind::ClockOffsetAbsMilliseconds => MetricUnit::Milliseconds,
    }
}
