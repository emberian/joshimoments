use crate::model::{
    AcquisitionRecord, AssertionDraft, AssertionRecord, BlobRecord, BlobRef, Committed,
    CoverageGap, CoverageRecovery, CoverageWindow, EvidenceDraft, EvidenceIdentity,
    ObservationDraft, ObservationRecord,
};
use joshi_domain::{
    AcquisitionId, AssertionId, BlobId, CommitSeq, CoverageId, ObservationId, SourceAsOf, SourceId,
    WireU64,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

const DEFAULT_MAX_PAYLOAD_BYTES: u64 = 16 * 1024 * 1024;

/// Whether an append advanced knowledge order or matched an existing record exactly.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AppendStatus {
    /// A new immutable record was accepted.
    Accepted,
    /// The exact same identity and value were already present.
    Idempotent,
}

/// Result of an idempotent append.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CommitReceipt {
    /// Existing or newly allocated durable knowledge order.
    pub commit_seq: CommitSeq,
    /// New append or exact replay.
    pub status: AppendStatus,
    /// Stable identity at the append boundary.
    pub identity: EvidenceIdentity,
}

/// Point-in-time immutable catalog contents used by offline replay and later store adapters.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct CatalogSnapshot {
    /// Highest represented local commit.
    pub commit_seq: CommitSeq,
    /// Acquisition occurrences, independently addressable from observations.
    pub acquisitions: Vec<Committed<AcquisitionRecord>>,
    /// Content-addressed exact bytes referenced by represented observations.
    pub blobs: Vec<Committed<BlobRecord>>,
    /// Observation occurrences; duplicate bytes never collapse these rows.
    pub observations: Vec<Committed<ObservationRecord>>,
    /// Versioned claims over evidence.
    pub assertions: Vec<Committed<AssertionRecord>>,
    /// Positive coverage claims.
    pub coverage_windows: Vec<Committed<CoverageWindow>>,
    /// Explicit scoped missing/degraded coverage.
    pub coverage_gaps: Vec<Committed<CoverageGap>>,
    /// Append-only recovery knowledge for earlier gaps.
    pub coverage_recoveries: Vec<Committed<CoverageRecovery>>,
}

impl CatalogSnapshot {
    /// Returns the as-known catalog at `cutoff`, hiding later acquisitions and assertions.
    #[must_use]
    pub fn at_commit(&self, cutoff: CommitSeq) -> Self {
        let effective_cutoff = cutoff.min(self.commit_seq);
        let observations = retained_through(&self.observations, effective_cutoff);
        let acquisition_ids = observations
            .iter()
            .map(|record| record.value.acquisition_id.clone())
            .collect::<BTreeSet<_>>();
        let blob_ids = observations
            .iter()
            .map(|record| record.value.blob.blob_id.clone())
            .collect::<BTreeSet<_>>();

        Self {
            commit_seq: effective_cutoff,
            acquisitions: self
                .acquisitions
                .iter()
                .filter(|record| {
                    record.commit_seq <= effective_cutoff
                        && acquisition_ids.contains(&record.value.acquisition_id)
                })
                .cloned()
                .collect(),
            blobs: self
                .blobs
                .iter()
                .filter(|record| {
                    record.commit_seq <= effective_cutoff
                        && blob_ids.contains(&record.value.reference.blob_id)
                })
                .cloned()
                .collect(),
            observations,
            assertions: retained_through(&self.assertions, effective_cutoff),
            coverage_windows: retained_through(&self.coverage_windows, effective_cutoff),
            coverage_gaps: retained_through(&self.coverage_gaps, effective_cutoff),
            coverage_recoveries: retained_through(&self.coverage_recoveries, effective_cutoff),
        }
    }

    /// Derives per-source watermarks without pretending they share a source-native clock.
    #[must_use]
    pub fn source_watermarks(&self) -> BTreeMap<SourceId, SourceAsOf> {
        let mut watermarks: BTreeMap<SourceId, SourceAsOf> = BTreeMap::new();
        let acquisitions = self
            .acquisitions
            .iter()
            .map(|record| (&record.value.acquisition_id, &record.value))
            .collect::<BTreeMap<_, _>>();
        for observation in &self.observations {
            let Some(acquisition) = acquisitions.get(&observation.value.acquisition_id) else {
                continue;
            };
            let candidate = SourceAsOf::without_cursors(
                observation.commit_seq,
                // Descriptive source cursors are never promoted to authority. Only scoped cursor
                // advances committed atomically with evidence may populate this vector in a
                // durable store.
                Some(observation.value.timing.received_at),
            );
            match watermarks.get(&acquisition.source_id) {
                Some(existing) if existing.delivered_through() >= candidate.delivered_through() => {
                }
                _ => {
                    watermarks.insert(acquisition.source_id.clone(), candidate);
                }
            }
        }
        watermarks
    }
}

fn retained_through<T: Clone>(values: &[Committed<T>], cutoff: CommitSeq) -> Vec<Committed<T>> {
    values
        .iter()
        .filter(|record| record.commit_seq <= cutoff)
        .cloned()
        .collect()
}

/// Deterministic append-only fixture catalog behind one writer.
#[derive(Debug)]
pub struct InMemoryCatalog {
    commit_seq: CommitSeq,
    max_payload_bytes: u64,
    acquisitions: BTreeMap<AcquisitionId, Committed<AcquisitionRecord>>,
    blobs: BTreeMap<BlobId, Committed<BlobRecord>>,
    observations: BTreeMap<ObservationId, Committed<ObservationRecord>>,
    assertions: BTreeMap<AssertionId, Committed<AssertionRecord>>,
    coverage_windows: BTreeMap<CoverageId, Committed<CoverageWindow>>,
    coverage_gaps: BTreeMap<CoverageId, Committed<CoverageGap>>,
    coverage_recoveries: BTreeMap<CoverageId, Committed<CoverageRecovery>>,
}

impl Default for InMemoryCatalog {
    fn default() -> Self {
        Self::new(DEFAULT_MAX_PAYLOAD_BYTES)
    }
}

impl InMemoryCatalog {
    /// Creates a catalog with an explicit per-observation payload bound.
    #[must_use]
    pub fn new(max_payload_bytes: u64) -> Self {
        Self {
            commit_seq: CommitSeq::ZERO,
            max_payload_bytes,
            acquisitions: BTreeMap::new(),
            blobs: BTreeMap::new(),
            observations: BTreeMap::new(),
            assertions: BTreeMap::new(),
            coverage_windows: BTreeMap::new(),
            coverage_gaps: BTreeMap::new(),
            coverage_recoveries: BTreeMap::new(),
        }
    }

    /// Appends one record atomically under fixture semantics.
    ///
    /// # Errors
    ///
    /// Returns an error before mutation for oversized payloads, conflicting immutable identities,
    /// missing assertion evidence, generated identity failures, or sequence exhaustion.
    pub fn append(&mut self, draft: EvidenceDraft) -> Result<CommitReceipt, CatalogError> {
        match draft {
            EvidenceDraft::Observation(draft) => self.append_observation(draft),
            EvidenceDraft::Assertion(assertion) => self.append_assertion(assertion),
            EvidenceDraft::CoverageWindow(window) => self.append_coverage_window(window),
            EvidenceDraft::CoverageGap(gap) => self.append_coverage_gap(gap),
            EvidenceDraft::CoverageRecovery(recovery) => self.append_coverage_recovery(recovery),
        }
    }

    fn append_observation(
        &mut self,
        draft: ObservationDraft,
    ) -> Result<CommitReceipt, CatalogError> {
        Self::validate_observation_contract(&draft)?;
        let unique_source_events = draft
            .observation
            .source_events
            .iter()
            .map(|link| (&link.source_event_id, &link.relation.discriminator))
            .collect::<BTreeSet<_>>();
        if unique_source_events.len() != draft.observation.source_events.len() {
            return Err(CatalogError::DuplicateSourceEventLink(
                draft.observation.observation_id.clone(),
            ));
        }
        let payload_len =
            u64::try_from(draft.payload.len()).map_err(|_| CatalogError::PayloadLengthOverflow)?;
        if payload_len > self.max_payload_bytes {
            return Err(CatalogError::PayloadTooLarge {
                actual: payload_len,
                maximum: self.max_payload_bytes,
            });
        }

        let blob_id = sha256_blob_id(&draft.payload)?;
        let blob = BlobRecord {
            reference: BlobRef {
                blob_id: blob_id.clone(),
                byte_len: WireU64::new(payload_len),
            },
            bytes: draft.payload,
        };
        let observation = ObservationRecord {
            acquisition_id: draft.acquisition.acquisition_id.clone(),
            observation_id: draft.observation.observation_id.clone(),
            acquisition_ordinal: draft.observation.acquisition_ordinal,
            observation_kind: draft.observation.observation_kind,
            source_events: draft.observation.source_events,
            blob: blob.reference.clone(),
            media_type: draft.observation.media_type.clone(),
            source_variant: draft.observation.source_variant,
            event_time: draft.observation.event_time,
            chain: draft.observation.chain,
            source_cursor: draft.observation.source_cursor,
            timing: draft.observation.timing,
            parse_disposition: draft.observation.parse_disposition,
            quality_code: draft.observation.quality_code,
        };

        if let Some(existing) = self.observations.get(&observation.observation_id) {
            if existing.value == observation
                && self
                    .acquisitions
                    .get(&draft.acquisition.acquisition_id)
                    .is_some_and(|value| value.value == draft.acquisition)
                && self
                    .blobs
                    .get(&blob_id)
                    .is_some_and(|value| value.value == blob)
            {
                return Ok(CommitReceipt {
                    commit_seq: existing.commit_seq,
                    status: AppendStatus::Idempotent,
                    identity: EvidenceIdentity::Observation(observation.observation_id.clone()),
                });
            }
            return Err(identity_conflict(
                "observation",
                observation.observation_id.as_str(),
            ));
        }
        if self.observations.values().any(|existing| {
            existing.value.acquisition_id == observation.acquisition_id
                && existing.value.acquisition_ordinal == observation.acquisition_ordinal
        }) {
            return Err(CatalogError::DuplicateAcquisitionOrdinal {
                acquisition_id: observation.acquisition_id,
                ordinal: observation.acquisition_ordinal,
            });
        }
        self.validate_acquisition_and_blob(&draft.acquisition, &blob_id, &blob)?;

        let commit_seq = self.next_commit()?;
        self.acquisitions
            .entry(draft.acquisition.acquisition_id.clone())
            .or_insert_with(|| Committed {
                commit_seq,
                value: draft.acquisition,
            });
        self.blobs.entry(blob_id).or_insert_with(|| Committed {
            commit_seq,
            value: blob,
        });
        self.observations.insert(
            observation.observation_id.clone(),
            Committed {
                commit_seq,
                value: observation.clone(),
            },
        );
        Ok(CommitReceipt {
            commit_seq,
            status: AppendStatus::Accepted,
            identity: EvidenceIdentity::Observation(observation.observation_id),
        })
    }

    fn validate_acquisition_and_blob(
        &self,
        acquisition: &AcquisitionRecord,
        blob_id: &BlobId,
        blob: &BlobRecord,
    ) -> Result<(), CatalogError> {
        if let Some(existing) = self.acquisitions.get(&acquisition.acquisition_id)
            && existing.value != *acquisition
        {
            return Err(identity_conflict(
                "acquisition",
                acquisition.acquisition_id.as_str(),
            ));
        }
        if let Some(existing) = self.blobs.get(blob_id)
            && existing.value != *blob
        {
            return Err(identity_conflict("blob", blob_id.as_str()));
        }
        Ok(())
    }

    fn validate_observation_contract(draft: &ObservationDraft) -> Result<(), CatalogError> {
        let acquisition = &draft.acquisition;
        let observation = &draft.observation;
        if acquisition.parent_acquisition_id.as_ref() == Some(&acquisition.acquisition_id) {
            return Err(CatalogError::SelfParentAcquisition(
                acquisition.acquisition_id.clone(),
            ));
        }
        if !is_sha256_identifier(acquisition.request_fingerprint.as_str()) {
            return Err(CatalogError::InvalidRequestFingerprint(
                acquisition.request_fingerprint.to_string(),
            ));
        }
        if acquisition
            .clocks
            .requested_at
            .is_some_and(|requested| requested > acquisition.clocks.received_at)
            || acquisition.clocks.persisted_at < acquisition.clocks.received_at
            || acquisition.started_at > observation.timing.received_at
            || observation.timing.persisted_at < observation.timing.received_at
            || observation.timing.available_at < observation.timing.persisted_at
        {
            return Err(CatalogError::InvalidObservationTiming);
        }
        let elapsed_and_domain_match = acquisition.clocks.monotonic_elapsed_ns.is_some()
            == acquisition.clocks.monotonic_domain.is_some();
        if !elapsed_and_domain_match {
            return Err(CatalogError::IncompleteMonotonicClock);
        }
        if let (Some(started), Some(domain)) = (
            acquisition.started_monotonic.as_ref(),
            acquisition.clocks.monotonic_domain.as_ref(),
        ) && started.clock_id != *domain
        {
            return Err(CatalogError::IncompleteMonotonicClock);
        }
        if acquisition.clocks.monotonic_elapsed_ns.is_some()
            && acquisition.started_monotonic.is_none()
        {
            return Err(CatalogError::IncompleteMonotonicClock);
        }
        if let Some(started) = &acquisition.started_monotonic
            && started.clock_id == observation.timing.received_monotonic.clock_id
            && started.nanoseconds > observation.timing.received_monotonic.nanoseconds
        {
            return Err(CatalogError::InvalidObservationTiming);
        }

        let event_time = &observation.event_time;
        let has_complete_interval = event_time.lower.is_some()
            && event_time.upper.is_some()
            && event_time.precision_us.is_some()
            && event_time.lower < event_time.upper;
        let has_no_interval = event_time.lower.is_none()
            && event_time.upper.is_none()
            && event_time.precision_us.is_none();
        match event_time.status.discriminator.as_str() {
            "exact" | "bounded" if !has_complete_interval => {
                return Err(CatalogError::InvalidObservationEventTime);
            }
            "source_missing" | "not_applicable" if !has_no_interval => {
                return Err(CatalogError::InvalidObservationEventTime);
            }
            _ => {}
        }
        if event_time.status.discriminator.as_str() == "exact"
            && let (Some(lower), Some(upper), Some(precision)) =
                (event_time.lower, event_time.upper, event_time.precision_us)
            && u64::try_from((upper.as_datetime() - lower.as_datetime()).whole_microseconds()).ok()
                != Some(precision.get())
        {
            return Err(CatalogError::InvalidObservationEventTime);
        }
        Ok(())
    }

    fn append_assertion(
        &mut self,
        assertion: AssertionDraft,
    ) -> Result<CommitReceipt, CatalogError> {
        for evidence in &assertion.evidence {
            if !self.observations.contains_key(&evidence.observation_id) {
                return Err(CatalogError::MissingObservation(
                    evidence.observation_id.clone(),
                ));
            }
        }
        if !assertion.extension.is_object() {
            return Err(CatalogError::AssertionValueMustBeObject);
        }
        validate_sha256_value_digest(assertion.value_digest.as_str())?;
        if let (Some(lower), Some(upper)) = (assertion.valid_time.lower, assertion.valid_time.upper)
            && lower >= upper
        {
            return Err(CatalogError::InvalidEventValidInterval);
        }
        if assertion.valid_time.lower.is_some() != assertion.valid_time.upper.is_some() {
            return Err(CatalogError::InvalidEventValidInterval);
        }
        if let Some(superseded_id) = &assertion.supersedes_assertion_id {
            let superseded = self
                .assertions
                .get(superseded_id)
                .ok_or_else(|| CatalogError::MissingAssertion(superseded_id.clone()))?;
            if superseded.value.assertion.semantic_key != assertion.semantic_key {
                return Err(CatalogError::SupersessionSemanticKeyMismatch);
            }
        }
        let record = AssertionRecord {
            assertion: assertion.clone(),
        };
        if let Some(existing) = self.assertions.get(&assertion.assertion_id) {
            return same_or_conflict(
                existing,
                &record,
                EvidenceIdentity::Assertion(assertion.assertion_id),
                "assertion",
            );
        }
        let commit_seq = self.next_commit()?;
        self.assertions.insert(
            assertion.assertion_id.clone(),
            Committed {
                commit_seq,
                value: record,
            },
        );
        Ok(CommitReceipt {
            commit_seq,
            status: AppendStatus::Accepted,
            identity: EvidenceIdentity::Assertion(assertion.assertion_id),
        })
    }

    fn append_coverage_window(
        &mut self,
        window: CoverageWindow,
    ) -> Result<CommitReceipt, CatalogError> {
        if let Some(existing) = self.coverage_windows.get(&window.coverage_id) {
            return same_or_conflict(
                existing,
                &window,
                EvidenceIdentity::CoverageWindow(window.coverage_id.clone()),
                "coverage_window",
            );
        }
        self.ensure_new_coverage_identity(&window.coverage_id)?;
        let commit_seq = self.next_commit()?;
        self.coverage_windows.insert(
            window.coverage_id.clone(),
            Committed {
                commit_seq,
                value: window.clone(),
            },
        );
        Ok(CommitReceipt {
            commit_seq,
            status: AppendStatus::Accepted,
            identity: EvidenceIdentity::CoverageWindow(window.coverage_id),
        })
    }

    fn append_coverage_gap(&mut self, gap: CoverageGap) -> Result<CommitReceipt, CatalogError> {
        if !self.coverage_windows.contains_key(&gap.coverage_id) {
            return Err(CatalogError::MissingCoverageWindow(gap.coverage_id));
        }
        if let Some(existing) = self.coverage_gaps.get(&gap.gap_id) {
            return same_or_conflict(
                existing,
                &gap,
                EvidenceIdentity::CoverageGap(gap.gap_id.clone()),
                "coverage_gap",
            );
        }
        self.ensure_new_coverage_identity(&gap.gap_id)?;
        let commit_seq = self.next_commit()?;
        self.coverage_gaps.insert(
            gap.gap_id.clone(),
            Committed {
                commit_seq,
                value: gap.clone(),
            },
        );
        Ok(CommitReceipt {
            commit_seq,
            status: AppendStatus::Accepted,
            identity: EvidenceIdentity::CoverageGap(gap.gap_id),
        })
    }

    fn append_coverage_recovery(
        &mut self,
        recovery: CoverageRecovery,
    ) -> Result<CommitReceipt, CatalogError> {
        let gap = self
            .coverage_gaps
            .get(&recovery.gap_id)
            .ok_or_else(|| CatalogError::MissingCoverageGap(recovery.gap_id.clone()))?;
        if recovery.available_at <= gap.value.detected_at {
            return Err(CatalogError::RecoveryDoesNotFollowGap);
        }
        if matches!(
            recovery.status.discriminator.as_str(),
            "partial" | "complete"
        ) && recovery.evidence.is_empty()
        {
            return Err(CatalogError::RecoveryMissingEvidence);
        }
        if recovery.evidence.iter().collect::<BTreeSet<_>>().len() != recovery.evidence.len() {
            return Err(CatalogError::RecoveryDuplicateEvidence);
        }
        for evidence_id in &recovery.evidence {
            let observation = self
                .observations
                .get(evidence_id)
                .ok_or_else(|| CatalogError::MissingObservation(evidence_id.clone()))?;
            if let Some(acquisition_id) = &recovery.acquisition_id
                && observation.value.acquisition_id != *acquisition_id
            {
                return Err(CatalogError::RecoveryEvidenceAcquisitionMismatch);
            }
        }
        if let Some(existing) = self.coverage_recoveries.get(&recovery.recovery_id) {
            return same_or_conflict(
                existing,
                &recovery,
                EvidenceIdentity::CoverageRecovery(recovery.recovery_id.clone()),
                "coverage_recovery",
            );
        }
        self.ensure_new_coverage_identity(&recovery.recovery_id)?;
        let commit_seq = self.next_commit()?;
        self.coverage_recoveries.insert(
            recovery.recovery_id.clone(),
            Committed {
                commit_seq,
                value: recovery.clone(),
            },
        );
        Ok(CommitReceipt {
            commit_seq,
            status: AppendStatus::Accepted,
            identity: EvidenceIdentity::CoverageRecovery(recovery.recovery_id),
        })
    }

    /// Produces a stable commit-ordered snapshot.
    #[must_use]
    pub fn snapshot(&self) -> CatalogSnapshot {
        CatalogSnapshot {
            commit_seq: self.commit_seq,
            acquisitions: committed_values(&self.acquisitions),
            blobs: committed_values(&self.blobs),
            observations: committed_values(&self.observations),
            assertions: committed_values(&self.assertions),
            coverage_windows: committed_values(&self.coverage_windows),
            coverage_gaps: committed_values(&self.coverage_gaps),
            coverage_recoveries: committed_values(&self.coverage_recoveries),
        }
    }

    fn next_commit(&mut self) -> Result<CommitSeq, CatalogError> {
        let next = self
            .commit_seq
            .checked_next()
            .ok_or(CatalogError::CommitSequenceExhausted)?;
        self.commit_seq = next;
        Ok(next)
    }

    fn ensure_new_coverage_identity(&self, id: &CoverageId) -> Result<(), CatalogError> {
        if self.coverage_windows.contains_key(id)
            || self.coverage_gaps.contains_key(id)
            || self.coverage_recoveries.contains_key(id)
        {
            return Err(identity_conflict("coverage", id.as_str()));
        }
        Ok(())
    }
}

fn committed_values<K: Ord, T: Clone>(values: &BTreeMap<K, Committed<T>>) -> Vec<Committed<T>> {
    let mut records = values.values().cloned().collect::<Vec<_>>();
    records.sort_by_key(|record| record.commit_seq);
    records
}

fn same_or_conflict<T: Eq>(
    existing: &Committed<T>,
    candidate: &T,
    identity: EvidenceIdentity,
    kind: &'static str,
) -> Result<CommitReceipt, CatalogError> {
    if existing.value == *candidate {
        Ok(CommitReceipt {
            commit_seq: existing.commit_seq,
            status: AppendStatus::Idempotent,
            identity,
        })
    } else {
        let rendered = match &identity {
            EvidenceIdentity::Observation(id) => id.as_str(),
            EvidenceIdentity::Assertion(id) => id.as_str(),
            EvidenceIdentity::CoverageWindow(id)
            | EvidenceIdentity::CoverageGap(id)
            | EvidenceIdentity::CoverageRecovery(id) => id.as_str(),
        };
        Err(identity_conflict(kind, rendered))
    }
}

fn sha256_blob_id(bytes: &[u8]) -> Result<BlobId, CatalogError> {
    let digest = Sha256::digest(bytes);
    BlobId::new(format!("sha256:{digest:x}")).map_err(CatalogError::InvalidBlobIdentity)
}

fn validate_sha256_value_digest(value: &str) -> Result<(), CatalogError> {
    if !is_sha256_identifier(value) {
        return Err(CatalogError::InvalidValueDigest(value.to_owned()));
    }
    Ok(())
}

fn is_sha256_identifier(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

fn identity_conflict(kind: &'static str, identity: &str) -> CatalogError {
    CatalogError::IdentityConflict {
        kind,
        identity: identity.to_owned(),
    }
}

/// A rejected append. Existing evidence remains unchanged.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum CatalogError {
    /// A repeated identity carried different immutable contents.
    #[error("conflicting {kind} identity: {identity}")]
    IdentityConflict {
        /// Identity namespace.
        kind: &'static str,
        /// Conflicting value.
        identity: String,
    },
    /// Assertions cannot cite evidence not present at their commit.
    #[error("assertion references missing observation: {0}")]
    MissingObservation(ObservationId),
    /// An observation repeated the same source-event link.
    #[error("observation contains duplicate source-event links: {0}")]
    DuplicateSourceEventLink(ObservationId),
    /// Two distinct observations claimed the same ordinal in one acquisition.
    #[error("duplicate acquisition ordinal {ordinal} for {acquisition_id}")]
    DuplicateAcquisitionOrdinal {
        /// Acquisition containing the collision.
        acquisition_id: AcquisitionId,
        /// Repeated ordinal.
        ordinal: WireU64,
    },
    /// Supersession must cite an assertion already known to the catalog.
    #[error("assertion supersedes missing assertion: {0}")]
    MissingAssertion(AssertionId),
    /// Correction history cannot jump between semantic keys.
    #[error("superseding assertion must preserve its semantic key")]
    SupersessionSemanticKeyMismatch,
    /// Assertion values are typed object contracts, not arbitrary JSON scalars.
    #[error("assertion extension value must be a JSON object")]
    AssertionValueMustBeObject,
    /// The asserted event-valid wall interval is incomplete or not increasing.
    #[error("assertion event-valid interval must have paired increasing bounds")]
    InvalidEventValidInterval,
    /// Assertion digest is not an algorithm-qualified lowercase SHA-256 value.
    #[error("invalid assertion value digest: {0}")]
    InvalidValueDigest(String),
    /// Redacted logical request fingerprint is not lowercase algorithm-qualified SHA-256.
    #[error("invalid request fingerprint: {0}")]
    InvalidRequestFingerprint(String),
    /// Acquisition lineage cannot point to itself.
    #[error("acquisition cannot be its own parent: {0}")]
    SelfParentAcquisition(AcquisitionId),
    /// Receipt, persistence, availability, or acquisition start clocks are out of order.
    #[error("observation local timing is not causally ordered")]
    InvalidObservationTiming,
    /// A monotonic duration without a domain (or vice versa) cannot be compared safely.
    #[error("monotonic elapsed time and clock domain must appear together")]
    IncompleteMonotonicClock,
    /// Event-time interval/status/precision fields disagree.
    #[error("observation event-time status and interval fields disagree")]
    InvalidObservationEventTime,
    /// A gap must refer to an already represented coverage window.
    #[error("coverage gap references missing window: {0}")]
    MissingCoverageWindow(CoverageId),
    /// Recovery must refer to an already represented immutable gap.
    #[error("coverage recovery references missing gap: {0}")]
    MissingCoverageGap(CoverageId),
    /// Recovery knowledge must arrive after gap detection.
    #[error("coverage recovery must be known after gap detection")]
    RecoveryDoesNotFollowGap,
    /// Partial/complete recovery requires explicit evidence.
    #[error("partial or complete coverage recovery requires evidence")]
    RecoveryMissingEvidence,
    /// Recovery evidence set must not contain duplicates.
    #[error("coverage recovery contains duplicate evidence")]
    RecoveryDuplicateEvidence,
    /// Named recovery acquisition must own every evidence observation.
    #[error("coverage recovery evidence does not belong to its named acquisition")]
    RecoveryEvidenceAcquisitionMismatch,
    /// Payload exceeds the configured evidence envelope bound.
    #[error("payload is {actual} bytes; maximum is {maximum} bytes")]
    PayloadTooLarge {
        /// Actual payload size.
        actual: u64,
        /// Configured maximum.
        maximum: u64,
    },
    /// Host `usize` could not be represented on the stable wire.
    #[error("payload length cannot be represented as u64")]
    PayloadLengthOverflow,
    /// The local commit sequence cannot advance further.
    #[error("commit sequence exhausted")]
    CommitSequenceExhausted,
    /// Internal hash output did not satisfy the stable identity contract.
    #[error("invalid generated blob identity: {0}")]
    InvalidBlobIdentity(joshi_domain::WireStringError),
}

#[cfg(test)]
mod tests {
    use super::InMemoryCatalog;
    use crate::model::{
        AcquisitionRecord, EvidenceDraft, MonotonicReading, ObservationDraft, ObservationEventTime,
        ObservationMetadata, ObservationTiming,
    };
    use joshi_domain::{
        AcquisitionClocks, AcquisitionId, CommitSeq, ObservationId, OpenVariant,
        RequestFingerprint, SourceId, StableString, UtcTimestamp, WireU64,
    };

    fn observation(acquisition: &str, observation: &str, payload: &[u8]) -> ObservationDraft {
        let timestamp = "2026-08-16T12:00:00.000000Z".parse::<UtcTimestamp>();
        assert!(timestamp.is_ok());
        let timestamp = timestamp.unwrap_or_else(|_| unreachable!());
        ObservationDraft {
            acquisition: AcquisitionRecord {
                acquisition_id: AcquisitionId::new(acquisition).unwrap_or_else(|_| unreachable!()),
                source_id: SourceId::new("fixture").unwrap_or_else(|_| unreachable!()),
                acquisition_kind: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                transport_kind: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                parent_acquisition_id: None,
                request_fingerprint: RequestFingerprint::new(format!("sha256:{}", "0".repeat(64)))
                    .unwrap_or_else(|_| unreachable!()),
                contract_version: StableString::new("v1").unwrap_or_else(|_| unreachable!()),
                started_at: timestamp,
                started_monotonic: Some(MonotonicReading {
                    clock_id: StableString::new("fixture-clock").unwrap_or_else(|_| unreachable!()),
                    nanoseconds: WireU64::new(0),
                }),
                source_locator: None,
                source_cursor: None,
                clocks: AcquisitionClocks {
                    requested_at: None,
                    received_at: timestamp,
                    persisted_at: timestamp,
                    monotonic_elapsed_ns: None,
                    monotonic_domain: None,
                },
            },
            observation: ObservationMetadata {
                observation_id: ObservationId::new(observation).unwrap_or_else(|_| unreachable!()),
                acquisition_ordinal: WireU64::new(0),
                observation_kind: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                source_events: Vec::new(),
                source_variant: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                event_time: ObservationEventTime {
                    status: OpenVariant::known("not_applicable").unwrap_or_else(|_| unreachable!()),
                    lower: None,
                    upper: None,
                    precision_us: None,
                },
                chain: None,
                source_cursor: None,
                timing: ObservationTiming {
                    received_at: timestamp,
                    received_monotonic: MonotonicReading {
                        clock_id: StableString::new("fixture-clock")
                            .unwrap_or_else(|_| unreachable!()),
                        nanoseconds: WireU64::new(1),
                    },
                    persisted_at: timestamp,
                    available_at: timestamp,
                },
                parse_disposition: OpenVariant::known("opaque").unwrap_or_else(|_| unreachable!()),
                quality_code: None,
                media_type: StableString::new("application/json")
                    .unwrap_or_else(|_| unreachable!()),
            },
            payload: payload.to_vec(),
        }
    }

    #[test]
    fn equal_bytes_do_not_collapse_occurrences() {
        let mut catalog = InMemoryCatalog::default();
        let first = catalog.append(EvidenceDraft::Observation(observation(
            "acq-1", "obs-1", b"same",
        )));
        let mut second_draft = observation("acq-2", "obs-2", b"same");
        second_draft.observation.media_type =
            StableString::new("application/octet-stream").unwrap_or_else(|_| unreachable!());
        let second = catalog.append(EvidenceDraft::Observation(second_draft));
        assert!(first.is_ok());
        assert!(second.is_ok());
        let snapshot = catalog.snapshot();
        assert_eq!(snapshot.observations.len(), 2);
        assert_eq!(snapshot.blobs.len(), 1);
        assert_ne!(
            snapshot.observations[0].value.media_type,
            snapshot.observations[1].value.media_type
        );
    }

    #[test]
    fn exact_redelivery_is_idempotent_but_conflict_is_rejected() {
        let draft = observation("acq-1", "obs-1", b"first");
        let mut catalog = InMemoryCatalog::default();
        let first = catalog.append(EvidenceDraft::Observation(draft.clone()));
        let replay = catalog.append(EvidenceDraft::Observation(draft));
        let conflict = catalog.append(EvidenceDraft::Observation(observation(
            "acq-1", "obs-1", b"changed",
        )));
        assert!(first.is_ok());
        assert!(matches!(
            replay.map(|receipt| receipt.status),
            Ok(super::AppendStatus::Idempotent)
        ));
        assert!(matches!(
            conflict,
            Err(super::CatalogError::IdentityConflict { .. })
        ));
        assert_eq!(catalog.snapshot().commit_seq.get(), 1);
    }

    #[test]
    fn payload_bound_is_enforced_before_mutation() {
        let mut catalog = InMemoryCatalog::new(3);
        let result = catalog.append(EvidenceDraft::Observation(observation(
            "acq-1", "obs-1", b"four",
        )));
        assert!(matches!(
            result,
            Err(super::CatalogError::PayloadTooLarge { .. })
        ));
        assert_eq!(catalog.snapshot().commit_seq.get(), 0);
    }

    #[test]
    fn snapshot_and_as_known_query_preserve_commit_order() {
        let mut catalog = InMemoryCatalog::default();
        assert!(
            catalog
                .append(EvidenceDraft::Observation(observation(
                    "acq-z", "obs-z", b"first",
                )))
                .is_ok()
        );
        assert!(
            catalog
                .append(EvidenceDraft::Observation(observation(
                    "acq-a", "obs-a", b"second",
                )))
                .is_ok()
        );

        let snapshot = catalog.snapshot();
        let ids = snapshot
            .observations
            .iter()
            .map(|record| record.value.observation_id.as_str())
            .collect::<Vec<_>>();
        assert_eq!(ids, vec!["obs-z", "obs-a"]);
        assert_eq!(snapshot.at_commit(CommitSeq::new(1)).observations.len(), 1);
    }

    #[test]
    fn watermark_uses_observation_delivery_and_never_descriptive_cursor() {
        let mut first = observation("acq-shared", "obs-first", b"first");
        first.acquisition.source_cursor = Some(
            StableString::new("descriptive-not-authoritative").unwrap_or_else(|_| unreachable!()),
        );
        let mut second = first.clone();
        second.observation.observation_id =
            ObservationId::new("obs-second").unwrap_or_else(|_| unreachable!());
        second.observation.acquisition_ordinal = WireU64::new(1);
        second.payload = b"second".to_vec();

        let mut catalog = InMemoryCatalog::default();
        assert!(catalog.append(first.into()).is_ok());
        assert!(catalog.append(second.into()).is_ok());
        let snapshot = catalog.snapshot();
        let source_id = SourceId::new("fixture").unwrap_or_else(|_| unreachable!());
        let watermark = snapshot.source_watermarks().remove(&source_id);
        assert!(watermark.is_some());
        if let Some(watermark) = watermark {
            assert_eq!(watermark.delivered_through(), CommitSeq::new(2));
            assert!(watermark.cursors().is_empty());
        }
    }

    #[test]
    fn duplicate_acquisition_ordinal_is_rejected() {
        let mut catalog = InMemoryCatalog::default();
        assert!(
            catalog
                .append(observation("acq-shared", "obs-first", b"first").into())
                .is_ok()
        );
        let collision = catalog.append(observation("acq-shared", "obs-second", b"second").into());
        assert!(matches!(
            collision,
            Err(super::CatalogError::DuplicateAcquisitionOrdinal { .. })
        ));
    }
}
