//! Durable-progress and sampled-resource adapters plus append-only degradation history.

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};

use crate::model::validate_resource_observation;
use crate::{
    AUTHORITY_CEILING, DegradationCause, DegradationStage, OperationalError, RecoveryState,
    ResourceKind, Result, SourceFamily, StatusClass,
};

/// Versioned durable progress contract. This is a query projection, never a writer capability.
pub const DURABLE_PROGRESS_CONTRACT: &str = "joshi.operational.durable_progress/v1";
/// Versioned sampled-resource contract. Samples have no durable commit field by design.
pub const RESOURCE_SAMPLE_CONTRACT: &str = "joshi.operational.resource_sample/v1";
/// Versioned append-only operational transition contract.
pub const STATUS_TRANSITION_CONTRACT: &str = "joshi.operational.status_transition/v1";
/// Versioned bounded status-view contract.
pub const STATUS_VIEW_CONTRACT: &str = "joshi.operational.status_view/v1";

/// Maximum durable progress rows in one status view.
pub const MAX_DURABLE_PROGRESS: usize = 512;
/// Maximum explicitly sampled resource rows in one status view.
pub const MAX_RESOURCE_SAMPLES: usize = 256;
/// Maximum append-only status transitions in one status view.
pub const MAX_STATUS_TRANSITIONS: usize = 512;

/// Qualification carried by this pure crate's status projections.
///
/// The only public qualification is intentionally unverified: store-resolved rows are supplied
/// by an integration owner, but this crate cannot turn caller-authored DTOs into an operational
/// recovery witness.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationalQualificationV1 {
    Unverified,
}

/// Durable subsystem milestone; a health sample cannot impersonate any of these.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableProgressKind {
    Receipt,
    Cursor,
    Gap,
    Publication,
    Export,
    Import,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableProgressState {
    Pending,
    Committed,
    Open,
    Closed,
    Refused,
}

/// Exact durable progress read from the store/spool/publication/export owner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UnverifiedDurableProgressV1 {
    pub contract: String,
    pub progress_id: StableString,
    pub kind: DurableProgressKind,
    pub scope_id: StableString,
    pub source_family: Option<SourceFamily>,
    pub state: DurableProgressState,
    pub durable_commit: Option<CommitSeq>,
    pub content_digest: Option<StableString>,
    pub observed_at: UtcTimestamp,
    pub authority: String,
}

/// Compatibility name for [`UnverifiedDurableProgressV1`]. It remains explicitly unverified.
pub type DurableProgressV1 = UnverifiedDurableProgressV1;

impl UnverifiedDurableProgressV1 {
    /// Returns the only qualification this pure progress adapter can provide.
    #[must_use]
    pub const fn qualification(&self) -> OperationalQualificationV1 {
        OperationalQualificationV1::Unverified
    }

    /// Constructs a read-only projection from a store-resolved durable occurrence.
    ///
    /// The constructor fixes the contract and authority. It does not acknowledge work,
    /// advance a cursor, or publish an artifact; callers must supply the commit returned by the
    /// authoritative owner.
    /// # Errors
    ///
    /// Returns an error when the supplied occurrence does not have the exact durable closure
    /// required by its state and kind.
    #[allow(clippy::too_many_arguments)]
    pub fn from_store_resolved(
        progress_id: StableString,
        kind: DurableProgressKind,
        scope_id: StableString,
        source_family: Option<SourceFamily>,
        state: DurableProgressState,
        durable_commit: Option<CommitSeq>,
        content_digest: Option<StableString>,
        observed_at: UtcTimestamp,
    ) -> Result<Self> {
        let value = Self {
            contract: DURABLE_PROGRESS_CONTRACT.to_owned(),
            progress_id,
            kind,
            scope_id,
            source_family,
            state,
            durable_commit,
            content_digest,
            observed_at,
            authority: AUTHORITY_CEILING.to_owned(),
        };
        value.validate()?;
        Ok(value)
    }

    /// Compatibility alias for [`Self::from_store_resolved`]. This remains a query-only DTO
    /// constructor and does not mint a store receipt or advance owner state.
    ///
    /// # Errors
    ///
    /// Returns an error when the supplied store-resolved fields fail durable-progress validation.
    #[deprecated(note = "use from_store_resolved to make the query-only boundary explicit")]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        progress_id: StableString,
        kind: DurableProgressKind,
        scope_id: StableString,
        source_family: Option<SourceFamily>,
        state: DurableProgressState,
        durable_commit: Option<CommitSeq>,
        content_digest: Option<StableString>,
        observed_at: UtcTimestamp,
    ) -> Result<Self> {
        Self::from_store_resolved(
            progress_id,
            kind,
            scope_id,
            source_family,
            state,
            durable_commit,
            content_digest,
            observed_at,
        )
    }

    /// Validates durable progress without granting an ACK, cursor, publication, or readiness
    /// capability.
    ///
    /// # Errors
    ///
    /// Refuses wrong contract/authority, missing durable commits for non-pending state, or a
    /// digest/state mismatch.
    pub fn validate(&self) -> Result<()> {
        if self.contract != DURABLE_PROGRESS_CONTRACT {
            return Err(OperationalError::Contract {
                expected: DURABLE_PROGRESS_CONTRACT,
                received: self.contract.clone(),
            });
        }
        if self.authority != AUTHORITY_CEILING {
            return Err(OperationalError::Invalid("durable progress authority"));
        }
        if self.state == DurableProgressState::Pending
            && (self.durable_commit.is_some() || self.content_digest.is_some())
        {
            return Err(OperationalError::Invalid(
                "pending progress cannot have a commit or content digest",
            ));
        }
        if self.state != DurableProgressState::Pending && self.durable_commit.is_none() {
            return Err(OperationalError::Invalid(
                "durable progress state requires a commit",
            ));
        }
        if matches!(
            self.state,
            DurableProgressState::Committed | DurableProgressState::Closed
        ) && self.content_digest.is_none()
        {
            return Err(OperationalError::Invalid(
                "committed or closed progress requires a content digest",
            ));
        }
        if matches!(
            self.kind,
            DurableProgressKind::Cursor | DurableProgressKind::Gap
        ) && self.source_family.is_none()
        {
            return Err(OperationalError::Invalid(
                "cursor and gap progress require a source family",
            ));
        }
        Ok(())
    }
}

/// Explicit host/runtime sample. It is not durable evidence and cannot advance any cursor.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceSampleV1 {
    pub contract: String,
    pub sample_id: StableString,
    pub kind: ResourceKind,
    pub observed: WireU64,
    pub limit_or_floor: WireU64,
    pub status: StatusClass,
    pub sampled_at: UtcTimestamp,
    pub sample_clock_id: StableString,
}

impl ResourceSampleV1 {
    /// Constructs an explicitly sampled observation. No durable authority is accepted or
    /// generated by this adapter.
    ///
    /// # Errors
    ///
    /// Returns an error when the sample contract or sample clock is invalid.
    pub fn new(
        sample_id: StableString,
        kind: ResourceKind,
        observed: WireU64,
        limit_or_floor: WireU64,
        status: StatusClass,
        sampled_at: UtcTimestamp,
        sample_clock_id: StableString,
    ) -> Result<Self> {
        let value = Self {
            contract: RESOURCE_SAMPLE_CONTRACT.to_owned(),
            sample_id,
            kind,
            observed,
            limit_or_floor,
            status,
            sampled_at,
            sample_clock_id,
        };
        value.validate()?;
        Ok(value)
    }

    /// # Errors
    ///
    /// Refuses wrong contract, missing sample clock, or an observation inconsistent with its
    /// limit/floor.
    pub fn validate(&self) -> Result<()> {
        if self.contract != RESOURCE_SAMPLE_CONTRACT {
            return Err(OperationalError::Invalid("resource sample contract"));
        }
        if self.sample_clock_id.as_str().is_empty() {
            return Err(OperationalError::Invalid("resource sample clock"));
        }
        validate_resource_observation(self.kind, self.observed, self.limit_or_floor, self.status)?;
        Ok(())
    }
}

/// Common append-only transition header. IDs are occurrences, not content digests.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TransitionHeadV1 {
    pub contract: String,
    pub record_id: StableString,
    pub ordinal: WireU64,
    pub predecessor_record_id: Option<StableString>,
    pub recorded_at: UtcTimestamp,
    pub scope_id: StableString,
    pub source_family: Option<SourceFamily>,
    pub authority: String,
}

/// Append-only degradation occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DegradationRecordV1 {
    pub head: TransitionHeadV1,
    pub stage: DegradationStage,
    pub causes: Vec<DegradationCause>,
}

/// Append-only recovery occurrence linked to one prior degradation occurrence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecoveryRecordV1 {
    pub head: TransitionHeadV1,
    pub degradation_record_id: StableString,
    pub state: RecoveryState,
    pub evidence_progress_id: Option<StableString>,
}

/// One append-only operational transition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum StatusTransitionV1 {
    Degradation(DegradationRecordV1),
    Recovery(RecoveryRecordV1),
}

impl StatusTransitionV1 {
    fn head(&self) -> &TransitionHeadV1 {
        match self {
            Self::Degradation(value) => &value.head,
            Self::Recovery(value) => &value.head,
        }
    }
    fn id(&self) -> &StableString {
        &self.head().record_id
    }
}

/// Restart-reconstructable append-only degradation/recovery journal.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct UnverifiedStatusJournal {
    records: Vec<StatusTransitionV1>,
}

/// Compatibility name for [`UnverifiedStatusJournal`].
pub type StatusJournal = UnverifiedStatusJournal;

impl UnverifiedStatusJournal {
    /// Returns the only qualification this pure journal adapter can provide.
    #[must_use]
    pub const fn qualification(&self) -> OperationalQualificationV1 {
        OperationalQualificationV1::Unverified
    }

    /// Reconstructs a journal from exact durable records.
    ///
    /// # Errors
    ///
    /// Refuses ordinal gaps, changed predecessors, duplicate IDs, stale timestamps, conflicting
    /// scopes, or recovery records that lack a prior degradation/evidence closure.
    pub fn new(records: Vec<StatusTransitionV1>) -> Result<Self> {
        let journal = Self { records };
        journal.validate()?;
        Ok(journal)
    }

    /// Returns the exact append order for restart readback.
    #[must_use]
    pub fn records(&self) -> &[StatusTransitionV1] {
        &self.records
    }

    /// Appends one exact occurrence, returning a new journal.
    ///
    /// # Errors
    ///
    /// Refuses any non-next ordinal, changed predecessor, duplicate occurrence, stale timestamp,
    /// or unclosed recovery transition.
    pub fn append(&self, record: StatusTransitionV1) -> Result<Self> {
        let mut records = self.records.clone();
        records.push(record);
        Self::new(records)
    }

    /// Validates append-only identity and transition closure.
    ///
    /// # Errors
    ///
    /// Returns a strict operational-state refusal.
    #[allow(clippy::too_many_lines)] // Ordered journal validation is kept auditable in one pass.
    pub fn validate(&self) -> Result<()> {
        if self.records.len() > MAX_STATUS_TRANSITIONS {
            return Err(OperationalError::BoundExceeded {
                field: "statusTransitions",
                maximum: u64::try_from(MAX_STATUS_TRANSITIONS).unwrap_or(u64::MAX),
            });
        }
        let mut ids = BTreeSet::new();
        let mut degradations = BTreeMap::new();
        let mut recovered = BTreeSet::new();
        let mut prior_time = None;
        let mut journal_scope = None;
        let mut journal_source = None;
        let mut journal_source_initialized = false;
        for (index, record) in self.records.iter().enumerate() {
            let head = record.head();
            if head.contract != STATUS_TRANSITION_CONTRACT || head.authority != AUTHORITY_CEILING {
                return Err(OperationalError::Invalid(
                    "status transition contract or authority",
                ));
            }
            if let Some(scope) = &journal_scope {
                if scope != &head.scope_id {
                    return Err(OperationalError::Invalid(
                        "status transitions must use one scope",
                    ));
                }
            } else {
                journal_scope = Some(head.scope_id.clone());
            }
            if !journal_source_initialized {
                journal_source = Some(head.source_family);
                journal_source_initialized = true;
            } else if journal_source != Some(head.source_family) {
                return Err(OperationalError::Invalid(
                    "status transitions must use one source family",
                ));
            }
            let ordinal = u64::try_from(index + 1)
                .map_err(|_| OperationalError::Invalid("transition ordinal"))?;
            if head.ordinal.get() != ordinal || !ids.insert(head.record_id.clone()) {
                return Err(OperationalError::Invalid(
                    "status transition ordinal or duplicate ID",
                ));
            }
            if head.predecessor_record_id.as_ref()
                != index
                    .checked_sub(1)
                    .and_then(|prior| self.records.get(prior))
                    .map(StatusTransitionV1::id)
            {
                return Err(OperationalError::Invalid("status transition predecessor"));
            }
            if prior_time.is_some_and(|prior| head.recorded_at < prior) {
                return Err(OperationalError::Invalid("status transition time"));
            }
            prior_time = Some(head.recorded_at);
            match record {
                StatusTransitionV1::Degradation(value) => {
                    if value.stage == DegradationStage::FullFidelity
                        || value.causes.is_empty()
                        || !value.causes.windows(2).all(|pair| pair[0] < pair[1])
                        || degradations
                            .insert(
                                value.head.record_id.clone(),
                                (
                                    value.head.scope_id.clone(),
                                    value.head.source_family,
                                    value.head.recorded_at,
                                ),
                            )
                            .is_some()
                    {
                        return Err(OperationalError::Invalid("degradation causes or identity"));
                    }
                }
                StatusTransitionV1::Recovery(value) => {
                    let Some((scope_id, source_family, degraded_at)) =
                        degradations.get(&value.degradation_record_id)
                    else {
                        return Err(OperationalError::Invalid(
                            "recovery does not close one prior degradation",
                        ));
                    };
                    if scope_id != &value.head.scope_id
                        || source_family != &value.head.source_family
                        || value.head.recorded_at < *degraded_at
                        || !recovered.insert(value.degradation_record_id.clone())
                    {
                        return Err(OperationalError::Invalid(
                            "recovery does not close one prior degradation",
                        ));
                    }
                    if !matches!(
                        value.state,
                        RecoveryState::UnverifiedSemantic | RecoveryState::BlockedUnrecoverable
                    ) {
                        return Err(OperationalError::Invalid(
                            "public recovery records must be explicitly unverified or blocked",
                        ));
                    }
                    if value.state == RecoveryState::BlockedUnrecoverable
                        && value.evidence_progress_id.is_some()
                    {
                        return Err(OperationalError::Invalid(
                            "blocked recovery cannot claim evidence",
                        ));
                    }
                }
            }
        }
        Ok(())
    }
}
/// Bounded query projection joining durable milestones, sampled resources, and append-only status.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UnverifiedOperationalStatusViewV1 {
    pub contract: String,
    pub observed_at: UtcTimestamp,
    pub authority: String,
    pub durable_progress: Vec<DurableProgressV1>,
    pub resource_samples: Vec<ResourceSampleV1>,
    pub transitions: Vec<StatusTransitionV1>,
}

/// Compatibility name for [`UnverifiedOperationalStatusViewV1`].
pub type OperationalStatusViewV1 = UnverifiedOperationalStatusViewV1;

impl UnverifiedOperationalStatusViewV1 {
    /// Returns the only qualification this pure adapter can provide.
    #[must_use]
    pub const fn qualification(&self) -> OperationalQualificationV1 {
        OperationalQualificationV1::Unverified
    }
    /// Constructs and validates one bounded read-only status projection.
    ///
    /// # Errors
    ///
    /// Returns an error when any component is out of bounds, out of order, or fails its
    /// durability/sample/recovery closure.
    pub fn new(
        observed_at: UtcTimestamp,
        durable_progress: Vec<DurableProgressV1>,
        resource_samples: Vec<ResourceSampleV1>,
        transitions: Vec<StatusTransitionV1>,
    ) -> Result<Self> {
        let value = Self {
            contract: STATUS_VIEW_CONTRACT.to_owned(),
            observed_at,
            authority: AUTHORITY_CEILING.to_owned(),
            durable_progress,
            resource_samples,
            transitions,
        };
        value.validate()?;
        Ok(value)
    }

    /// # Errors
    ///
    /// Refuses mixed authority, duplicate/conflicting durable progress, invalid samples, or an
    /// invalid append-only transition history.
    #[allow(clippy::too_many_lines)] // One view validator preserves the durable/sample separation.
    pub fn validate(&self) -> Result<()> {
        if self.contract != STATUS_VIEW_CONTRACT || self.authority != AUTHORITY_CEILING {
            return Err(OperationalError::Invalid(
                "status view contract or authority",
            ));
        }
        if self.durable_progress.len() > MAX_DURABLE_PROGRESS {
            return Err(OperationalError::BoundExceeded {
                field: "durableProgress",
                maximum: u64::try_from(MAX_DURABLE_PROGRESS).unwrap_or(u64::MAX),
            });
        }
        if self.resource_samples.len() > MAX_RESOURCE_SAMPLES {
            return Err(OperationalError::BoundExceeded {
                field: "resourceSamples",
                maximum: u64::try_from(MAX_RESOURCE_SAMPLES).unwrap_or(u64::MAX),
            });
        }
        let mut progress = BTreeSet::new();
        let mut prior_progress = None;
        for value in &self.durable_progress {
            value.validate()?;
            if value.observed_at > self.observed_at {
                return Err(OperationalError::Invalid(
                    "durable progress cannot be observed after the status view",
                ));
            }
            if !progress.insert(value.progress_id.clone()) {
                return Err(OperationalError::Invalid(
                    "conflicting durable progress occurrence",
                ));
            }
            if prior_progress
                .as_ref()
                .is_some_and(|prior| prior >= &value.progress_id)
            {
                return Err(OperationalError::Invalid(
                    "durable progress must be sorted by progress ID",
                ));
            }
            prior_progress = Some(value.progress_id.clone());
        }
        let mut samples = BTreeSet::new();
        for sample in &self.resource_samples {
            sample.validate()?;
            if sample.sampled_at > self.observed_at {
                return Err(OperationalError::Invalid(
                    "resource sample cannot be sampled after the status view",
                ));
            }
            if !samples.insert(sample.sample_id.clone()) {
                return Err(OperationalError::Invalid(
                    "resource samples must have unique sample IDs",
                ));
            }
        }
        let journal = StatusJournal::new(self.transitions.clone())?;
        let durable_by_id: BTreeMap<_, _> = self
            .durable_progress
            .iter()
            .map(|value| (value.progress_id.clone(), value))
            .collect();
        for transition in journal.records() {
            if transition.head().recorded_at > self.observed_at {
                return Err(OperationalError::Invalid(
                    "status transition is future-known",
                ));
            }
            if let StatusTransitionV1::Recovery(value) = transition
                && value.state == RecoveryState::UnverifiedSemantic
                && value.evidence_progress_id.is_some()
            {
                let evidence_id =
                    value
                        .evidence_progress_id
                        .as_ref()
                        .ok_or(OperationalError::Invalid(
                            "unverified recovery evidence must resolve when supplied",
                        ))?;
                let evidence = durable_by_id
                    .get(evidence_id)
                    .ok_or(OperationalError::Invalid(
                        "recovery evidence must resolve to durable progress",
                    ))?;
                let degradation_id = &value.degradation_record_id;
                let degradation_at = journal.records().iter().find_map(|record| match record {
                    StatusTransitionV1::Degradation(degradation)
                        if &degradation.head.record_id == degradation_id =>
                    {
                        Some(degradation.head.recorded_at)
                    }
                    _ => None,
                });
                let degradation_at = degradation_at.ok_or(OperationalError::Invalid(
                    "recovery degradation record must resolve",
                ))?;
                if evidence.state == DurableProgressState::Pending
                    || !matches!(
                        evidence.kind,
                        DurableProgressKind::Receipt
                            | DurableProgressKind::Cursor
                            | DurableProgressKind::Publication
                            | DurableProgressKind::Export
                            | DurableProgressKind::Import
                    )
                    || !matches!(
                        evidence.state,
                        DurableProgressState::Committed | DurableProgressState::Closed
                    )
                    || evidence.scope_id != value.head.scope_id
                    || evidence.source_family != value.head.source_family
                    || evidence.observed_at < degradation_at
                    || evidence.observed_at > value.head.recorded_at
                {
                    return Err(OperationalError::Invalid(
                        "recovery evidence scope, source, or clock mismatch",
                    ));
                }
            }
        }
        Ok(())
    }
}
