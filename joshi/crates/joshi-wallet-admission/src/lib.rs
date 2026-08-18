//! Typed receipt-gated admission from retained public-chain frames into immutable wallet topology.
//!
//! This crate contains no provider client, private key, signer, transaction builder, or submitter.
//! It connects existing read-only acquisition and pure topology contracts to the real single-writer
//! store. Source-normalized facts are deliberately held behind [`PreparedWalletAdmission`] until a
//! validated durable receipt closes their exact observation and coverage provenance.

#![forbid(unsafe_code)]

use joshi_admission::{
    AdmissionBatch, AdmissionError, AdmissionPolicy, PublicStoreReceiptV1, SourceDraftBatch,
    source_drafts,
};
use joshi_domain::{
    BatchDigest, CommitSeq, CoverageId, CursorId, OpenVariant, SourceEventId, StableString,
    UtcTimestamp, ValueDigest, WireU64,
};
use joshi_evidence::{
    Boundary, CoverageScope, CoverageWindow, CursorAdvance, EvidenceDraft, ObservationSourceEvent,
    SourceEventRecord,
};
use joshi_sources::{EvidenceContext, RawSourceFrame};
use joshi_store::{JustifiedCursor, SourceRegistration, SqliteStore};
use joshi_wallet_source::{
    AcquisitionResponseContext, EnhancedProjection, NormalizationError, NormalizedWalletBatch,
    PinnedDecodeResult, PinnedDecoderError, RawTransactionFact, TopologyAdapterError,
    apply_pinned_protocol_decoder, normalize_frame, to_topology_facts,
};
use joshi_wallet_topology::{
    CoverageBindingError, ReducerConfig, SnapshotRequest, StoreCoverageReceipt,
    TOPOLOGY_CONTRACT_VERSION, TopologyError, TopologyFact, TopologyInput, TopologyReducer,
    TopologySnapshot,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Exact durable-batch and coverage metadata supplied by the single-writer owner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WalletAdmissionMetadata {
    pub batch_id: StableString,
    pub coverage_id: CoverageId,
    pub coverage_family: OpenVariant,
    pub coverage_subject: Option<StableString>,
    pub predecessor_cursor_id: Option<CursorId>,
    pub committed_at: UtcTimestamp,
    pub writer_clock_id: StableString,
    pub committed_mono_ns: WireU64,
    pub writer_build: StableString,
}

/// One offline-capable source response and its non-secret semantic context.
#[derive(Debug)]
pub struct WalletAdmissionRequest {
    pub frame: RawSourceFrame,
    pub evidence_context: EvidenceContext,
    pub response_context: AcquisitionResponseContext,
    pub metadata: WalletAdmissionMetadata,
}

/// Receipt-gated object. Its normalized facts, cursor candidate, and topology projection are
/// intentionally private until [`PreparedWalletAdmission::commit`] succeeds.
pub struct PreparedWalletAdmission {
    admission: AdmissionBatch,
    source_id: joshi_domain::SourceId,
    observation_id: joshi_domain::ObservationId,
    raw_body_digest: ValueDigest,
    raw_body_len: WireU64,
    normalized: NormalizedWalletBatch,
    pinned_decodes: Vec<PinnedDecodeResult>,
    topology_facts: Vec<TopologyFact>,
    coverage_ids: Vec<CoverageId>,
    cursor_id: Option<CursorId>,
}

/// Immutable admitted output. Vendor-enhanced claims remain a separate quarantine collection and
/// are never inputs to `topology_snapshot`.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AdmittedWalletTopology {
    pub receipt: PublicStoreReceiptV1,
    pub raw_body_digest: ValueDigest,
    pub raw_body_len: WireU64,
    pub observation_id: joshi_domain::ObservationId,
    pub transaction_facts: Vec<RawTransactionFact>,
    pub pinned_decodes: Vec<PinnedDecodeResult>,
    pub quarantined_enhanced_projections: Vec<EnhancedProjection>,
    pub topology_facts: Vec<TopologyFact>,
    pub verified_coverage_ids: Vec<CoverageId>,
    pub coverage_receipts: Vec<StoreCoverageReceipt>,
    pub justified_cursor: Option<JustifiedCursor>,
    pub topology_snapshot: TopologySnapshot,
    pub topology_snapshot_digest: ValueDigest,
    #[serde(skip)]
    verified_history: VerifiedTopologyHistory,
}

/// Opaque topology history whose facts all originated from earlier receipt-gated admissions.
///
/// It is intentionally not serializable or constructible outside this crate. Recovering history
/// from a stored artifact will require a future typed store readback adapter, not trusting JSON.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedTopologyHistory {
    catalog_id: StableString,
    through_commit_seq: CommitSeq,
    facts: Vec<TopologyFact>,
    coverage_receipts: Vec<StoreCoverageReceipt>,
}

#[derive(Debug, thiserror::Error)]
pub enum WalletAdmissionError {
    #[error(transparent)]
    Admission(#[from] AdmissionError),
    #[error(transparent)]
    Normalization(#[from] NormalizationError),
    #[error(transparent)]
    Decoder(#[from] PinnedDecoderError),
    #[error(transparent)]
    TopologyAdapter(#[from] TopologyAdapterError),
    #[error(transparent)]
    Topology(#[from] TopologyError),
    #[error(transparent)]
    CoverageBinding(#[from] CoverageBindingError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error("wire identity or digest construction failed")]
    Wire,
    #[error("wallet admission coverage does not match its source response")]
    CoverageMismatch,
    #[error("wallet admission cannot close caller-supplied gap IDs without typed gap semantics")]
    UnsupportedGapClosure,
    #[error("receipt-gated cursor was not visible at the committed cutoff")]
    CursorClosure,
    #[error("receipt admitted counts do not close this wallet batch")]
    ReceiptCounts,
    #[error("snapshot serialization failed")]
    SnapshotSerialization,
    #[error("prior topology history belongs to a different durable catalog")]
    HistoryCatalogMismatch,
    #[error("prior topology history is later than the current durable receipt")]
    HistoryFutureCommit,
}

/// Normalize and stage one public-chain response without granting durable authority.
///
/// The returned type has no normalized-fact, topology, or cursor getters. It can only be consumed
/// by a successful single-writer commit.
///
/// # Errors
///
/// Refuses invalid evidence, normalization/decoder failures, mismatched coverage, untyped gap
/// references, or a durable-batch construction failure.
#[allow(clippy::too_many_lines)]
pub fn prepare_wallet_admission(
    request: WalletAdmissionRequest,
) -> Result<PreparedWalletAdmission, WalletAdmissionError> {
    let WalletAdmissionRequest {
        frame,
        evidence_context,
        response_context,
        metadata,
    } = request;
    let raw_body_len =
        WireU64::new(u64::try_from(frame.body.len()).map_err(|_| WalletAdmissionError::Wire)?);
    let raw_body_digest = value_digest(&frame.body)?;
    let mut output = normalize_frame(frame, evidence_context, &response_context)?;
    let expected_coverage = vec![metadata.coverage_id.clone()];
    let normalized_coverage = response_context
        .coverage_ids
        .iter()
        .map(|value| CoverageId::new(value.as_str()))
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| WalletAdmissionError::Wire)?;
    if normalized_coverage != expected_coverage {
        return Err(WalletAdmissionError::CoverageMismatch);
    }
    if !response_context.coverage_gap_ids.is_empty() {
        return Err(WalletAdmissionError::UnsupportedGapClosure);
    }
    let EvidenceDraft::Observation(observation) = &mut output.evidence else {
        unreachable!("wallet source normalization always retains an observation")
    };
    let source_id = observation.acquisition.source_id.clone();
    let observation_id = observation.observation.observation_id.clone();
    let acquisition_id = observation.acquisition.acquisition_id.clone();
    let mut source_events = Vec::new();
    for (ordinal, raw) in output.normalized.raw_transactions.iter_mut().enumerate() {
        let source_event_id = SourceEventId::new(format!(
            "{}.solana.transaction_event:{}",
            source_id, raw.transaction.signature
        ))
        .map_err(|_| WalletAdmissionError::Wire)?;
        raw.source_event_ids = vec![source_event_id.clone()];
        observation
            .observation
            .source_events
            .push(ObservationSourceEvent {
                source_event_id: source_event_id.clone(),
                relation: OpenVariant::known("contains").map_err(|_| WalletAdmissionError::Wire)?,
                event_ordinal: Some(
                    u64::try_from(ordinal)
                        .map_err(|_| WalletAdmissionError::Wire)?
                        .into(),
                ),
            });
        source_events.push(SourceEventRecord {
            source_event_id,
            source_id: source_id.clone(),
            namespace: StableString::new("solana.transaction")
                .map_err(|_| WalletAdmissionError::Wire)?,
            natural_key: raw.transaction.signature.clone(),
            source_order_key: Some(
                StableString::new(format!(
                    "{}:{}",
                    raw.transaction.slot,
                    raw.transaction
                        .transaction_index
                        .map_or_else(|| "unknown".to_owned(), |value| value.to_string())
                ))
                .map_err(|_| WalletAdmissionError::Wire)?,
            ),
            event_kind: OpenVariant::known("transaction")
                .map_err(|_| WalletAdmissionError::Wire)?,
        });
    }
    observation
        .observation
        .source_events
        .sort_by(|left, right| {
            (
                &left.source_event_id,
                &left.relation.discriminator,
                left.event_ordinal,
            )
                .cmp(&(
                    &right.source_event_id,
                    &right.relation.discriminator,
                    right.event_ordinal,
                ))
        });

    let scope = CoverageScope {
        source_id: source_id.clone(),
        family: metadata.coverage_family,
        subject: metadata.coverage_subject,
    };
    let lower = if let Some(value) = &response_context.cursor_before {
        Boundary::SourceCursor {
            value: value.clone(),
        }
    } else {
        Boundary::Unknown {
            reason: OpenVariant::known("request_start_unbounded")
                .map_err(|_| WalletAdmissionError::Wire)?,
        }
    };
    let upper = output
        .normalized
        .coverage
        .source_cursor_candidate
        .clone()
        .map(|value| Boundary::SourceCursor { value });
    let coverage_state = if output.normalized.coverage.page_exhausted {
        "complete"
    } else if upper.is_some() {
        "partial"
    } else {
        "open"
    };
    let coverage_window = CoverageWindow {
        coverage_id: metadata.coverage_id.clone(),
        scope: scope.clone(),
        lower,
        upper,
        state: OpenVariant::known(coverage_state).map_err(|_| WalletAdmissionError::Wire)?,
        available_at: response_context.available_at,
    };
    let (cursor_id, cursor_advances) = if let Some(candidate) =
        output.normalized.coverage.source_cursor_candidate.as_ref()
    {
        let cursor_id = CursorId::new(format!(
            "wallet.cursor:{}:{}",
            metadata.batch_id, metadata.coverage_id
        ))
        .map_err(|_| WalletAdmissionError::Wire)?;
        (
            Some(cursor_id.clone()),
            vec![CursorAdvance {
                cursor_id,
                scope: scope.clone(),
                cursor_kind: OpenVariant::known("page").map_err(|_| WalletAdmissionError::Wire)?,
                cursor_value: candidate.clone(),
                acquisition_id: acquisition_id.clone(),
                primary_observation_id: observation_id.clone(),
                evidence: vec![observation_id.clone()],
                predecessor_cursor_id: metadata.predecessor_cursor_id.clone(),
            }],
        )
    } else {
        (None, Vec::new())
    };

    let mut pinned_decodes = Vec::new();
    let mut topology_facts = Vec::new();
    for raw in &mut output.normalized.raw_transactions {
        pinned_decodes.extend(apply_pinned_protocol_decoder(raw)?);
        topology_facts.extend(to_topology_facts(raw)?);
    }
    let registration = registration(
        source_id.clone(),
        "read_only_wallet_chain",
        observation.acquisition.contract_version.as_str(),
        env!("CARGO_PKG_VERSION"),
    )?;
    let admission = source_drafts(SourceDraftBatch {
        batch_id: metadata.batch_id,
        drafts: vec![
            output.evidence.clone(),
            EvidenceDraft::CoverageWindow(coverage_window),
        ],
        source_events,
        cursor_advances,
        registrations: vec![registration],
        policy: AdmissionPolicy::public_source()?,
        committed_at: metadata.committed_at,
        writer_clock_id: metadata.writer_clock_id,
        committed_mono_ns: metadata.committed_mono_ns.get(),
        writer_build: metadata.writer_build,
    })?;
    Ok(PreparedWalletAdmission {
        admission,
        source_id,
        observation_id,
        raw_body_digest,
        raw_body_len,
        normalized: output.normalized,
        pinned_decodes,
        topology_facts,
        coverage_ids: expected_coverage,
        cursor_id,
    })
}

impl PreparedWalletAdmission {
    /// Commit exact evidence, then expose versioned facts and an immutable store-bound snapshot.
    ///
    /// Earlier topology facts are explicit input so corrections append a new version and snapshot;
    /// neither this adapter nor the reducer mutates a prior snapshot. The opaque history can only
    /// originate from an earlier receipt-gated admission in the same process/catalog lineage.
    ///
    /// # Errors
    ///
    /// Refuses a failed/invalid durable receipt, wrong-catalog or future history, cursor readback
    /// mismatch, reducer failure, coverage-closure mismatch, or snapshot digest failure.
    pub fn commit(
        self,
        store: &mut SqliteStore,
        reducer_config: ReducerConfig,
        snapshot_request: SnapshotRequest,
        earlier_history: Option<&VerifiedTopologyHistory>,
    ) -> Result<AdmittedWalletTopology, WalletAdmissionError> {
        let receipt = self.admission.commit(store)?;
        if receipt.admitted.observations != "1"
            || receipt.admitted.coverage_windows != self.coverage_ids.len().to_string()
        {
            return Err(WalletAdmissionError::ReceiptCounts);
        }
        let through_commit_seq = CommitSeq::new(
            receipt
                .through_commit_seq
                .parse()
                .map_err(|_| WalletAdmissionError::Wire)?,
        );
        let justified =
            store.justified_source_cursors_as_known(&self.source_id, through_commit_seq)?;
        let justified_cursor = match self.cursor_id.as_ref() {
            Some(expected) => Some(
                justified
                    .into_iter()
                    .find(|cursor| &cursor.cursor_id == expected)
                    .ok_or(WalletAdmissionError::CursorClosure)?,
            ),
            None => None,
        };
        let catalog_id =
            StableString::new(&receipt.catalog_id).map_err(|_| WalletAdmissionError::Wire)?;
        let (mut all_facts, mut coverage_receipts) = if let Some(history) = earlier_history {
            if history.catalog_id != catalog_id {
                return Err(WalletAdmissionError::HistoryCatalogMismatch);
            }
            if history.through_commit_seq > through_commit_seq {
                return Err(WalletAdmissionError::HistoryFutureCommit);
            }
            (history.facts.clone(), history.coverage_receipts.clone())
        } else {
            (Vec::new(), Vec::new())
        };
        all_facts.extend(self.topology_facts.clone());
        coverage_receipts.push(StoreCoverageReceipt {
            catalog_id: catalog_id.clone(),
            through_commit_seq,
            batch_id: StableString::new(&receipt.batch_id)
                .map_err(|_| WalletAdmissionError::Wire)?,
            batch_digest: BatchDigest::new(receipt.batch_digest.to_string())
                .map_err(|_| WalletAdmissionError::Wire)?,
            coverage_ids: self.coverage_ids.clone(),
        });
        let verified_coverage_ids = coverage_receipts
            .iter()
            .flat_map(|closure| closure.coverage_ids.iter().cloned())
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        let snapshot = TopologyReducer::new(reducer_config).snapshot(
            &TopologyInput {
                contract: StableString::new(TOPOLOGY_CONTRACT_VERSION)
                    .map_err(|_| WalletAdmissionError::Wire)?,
                facts: all_facts.clone(),
                hypotheses: Vec::new(),
            },
            snapshot_request,
        )?;
        let snapshot = snapshot.with_store_verified_coverage(coverage_receipts.clone())?;
        let snapshot_bytes = serde_json::to_vec(&snapshot)
            .map_err(|_| WalletAdmissionError::SnapshotSerialization)?;
        let topology_snapshot_digest = value_digest(&snapshot_bytes)?;
        Ok(AdmittedWalletTopology {
            receipt,
            raw_body_digest: self.raw_body_digest,
            raw_body_len: self.raw_body_len,
            observation_id: self.observation_id,
            transaction_facts: self.normalized.raw_transactions,
            pinned_decodes: self.pinned_decodes,
            quarantined_enhanced_projections: self.normalized.enhanced_projections,
            topology_facts: self.topology_facts,
            verified_coverage_ids,
            coverage_receipts: coverage_receipts.clone(),
            justified_cursor,
            topology_snapshot: snapshot,
            topology_snapshot_digest,
            verified_history: VerifiedTopologyHistory {
                catalog_id,
                through_commit_seq,
                facts: all_facts,
                coverage_receipts,
            },
        })
    }
}

impl AdmittedWalletTopology {
    /// Clone the opaque, receipt-derived fact history for a later correction/snapshot admission.
    #[must_use]
    pub fn verified_history(&self) -> VerifiedTopologyHistory {
        self.verified_history.clone()
    }
}

fn value_digest(bytes: &[u8]) -> Result<ValueDigest, WalletAdmissionError> {
    let digest = Sha256::digest(bytes);
    ValueDigest::new(format!("sha256:{digest:x}")).map_err(|_| WalletAdmissionError::Wire)
}

fn registration(
    source_id: joshi_domain::SourceId,
    namespace: &str,
    contract_version: &str,
    collector_build: &str,
) -> Result<SourceRegistration, WalletAdmissionError> {
    let material = format!(
        "joshi.source.registration.v1\0{}\0{namespace}\0{contract_version}\0{collector_build}",
        source_id.as_str()
    );
    Ok(SourceRegistration {
        source_id,
        namespace: StableString::new(namespace).map_err(|_| WalletAdmissionError::Wire)?,
        contract_version: StableString::new(contract_version)
            .map_err(|_| WalletAdmissionError::Wire)?,
        collector_build: StableString::new(collector_build)
            .map_err(|_| WalletAdmissionError::Wire)?,
        configuration_digest: value_digest(material.as_bytes())?,
    })
}
