use crate::{AdmissionError, PublicStoreReceiptV1, Sha256Digest};
#[cfg(feature = "source-edges")]
use joshi_domain::OpenVariant;
use joshi_domain::{BatchDigest, StableString, UtcTimestamp, ValueDigest};
use joshi_evidence::{CursorAdvance, DurableIngestBatch, EvidenceDraft, SourceEventRecord};
use joshi_store::{ObservationStorage, SourceRegistration, SqliteStore, StoreIngestBatch};
use std::collections::BTreeMap;

#[cfg(feature = "source-edges")]
#[derive(Clone, Debug)]
pub struct SourceFrameInput {
    pub frame: joshi_sources::RawSourceFrame,
    pub context: joshi_sources::EvidenceContext,
}

pub const DURABLE_CONTRACT: &str = "joshi.durable_ingest_batch.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmissionPolicy {
    pub retention_class: StableString,
    pub content_encoding: Option<StableString>,
    pub force_external: bool,
    pub gap_severity: StableString,
}

impl AdmissionPolicy {
    /// Build the physical policy for public, unauthenticated source evidence.
    ///
    /// # Errors
    ///
    /// Returns an error if a policy label violates the stable wire-string contract.
    pub fn public_source() -> Result<Self, AdmissionError> {
        Ok(Self {
            retention_class: StableString::new("public_source")?,
            content_encoding: None,
            force_external: false,
            gap_severity: StableString::new("degraded")?,
        })
    }

    /// Build the physically isolated policy for authenticated private evidence.
    ///
    /// # Errors
    ///
    /// Returns an error if a policy label violates the stable wire-string contract.
    pub fn authenticated_private() -> Result<Self, AdmissionError> {
        Ok(Self {
            retention_class: StableString::new("app_private")?,
            content_encoding: None,
            force_external: true,
            gap_severity: StableString::new("degraded")?,
        })
    }
}

#[derive(Clone, Debug)]
pub struct SourceDraftBatch {
    pub batch_id: StableString,
    pub drafts: Vec<EvidenceDraft>,
    pub source_events: Vec<SourceEventRecord>,
    pub cursor_advances: Vec<CursorAdvance>,
    pub registrations: Vec<SourceRegistration>,
    pub policy: AdmissionPolicy,
    pub committed_at: UtcTimestamp,
    pub writer_clock_id: StableString,
    pub committed_mono_ns: u64,
    pub writer_build: StableString,
}

#[derive(Clone, Debug)]
pub struct AdmissionBatch {
    pub registrations: Vec<SourceRegistration>,
    pub store: StoreIngestBatch,
}

impl AdmissionBatch {
    /// Register sources, atomically commit the batch, and validate its public receipt closure.
    ///
    /// # Errors
    ///
    /// Returns an error for source-registration, durable-store, or receipt-closure failures.
    pub fn commit(&self, store: &mut SqliteStore) -> Result<PublicStoreReceiptV1, AdmissionError> {
        for registration in &self.registrations {
            store.register_source(registration)?;
        }
        let receipt = store.commit_ingest(&self.store)?;
        PublicStoreReceiptV1::from_committed(&receipt, &self.store.evidence)
    }
}

/// Normalize source-owned drafts into the one sorted, versioned durable ingest boundary.
///
/// # Errors
///
/// Returns an error if an identity, policy, or canonical batch digest cannot be represented.
pub fn source_drafts(input: SourceDraftBatch) -> Result<AdmissionBatch, AdmissionError> {
    let mut observations = Vec::new();
    let mut assertions = Vec::new();
    let mut coverage_windows = Vec::new();
    let mut coverage_gaps = Vec::new();
    let mut coverage_recoveries = Vec::new();
    for draft in input.drafts {
        match draft {
            EvidenceDraft::Observation(value) => observations.push(value),
            EvidenceDraft::Assertion(value) => assertions.push(value),
            EvidenceDraft::CoverageWindow(value) => coverage_windows.push(value),
            EvidenceDraft::CoverageGap(value) => coverage_gaps.push(value),
            EvidenceDraft::CoverageRecovery(value) => coverage_recoveries.push(value),
        }
    }
    observations.sort_by(|left, right| {
        (
            &left.acquisition.acquisition_id,
            left.observation.acquisition_ordinal,
            &left.observation.observation_id,
        )
            .cmp(&(
                &right.acquisition.acquisition_id,
                right.observation.acquisition_ordinal,
                &right.observation.observation_id,
            ))
    });
    assertions.sort_by(|left, right| left.assertion_id.cmp(&right.assertion_id));
    coverage_windows.sort_by(|left, right| left.coverage_id.cmp(&right.coverage_id));
    coverage_gaps.sort_by(|left, right| left.gap_id.cmp(&right.gap_id));
    coverage_recoveries.sort_by(|left, right| left.recovery_id.cmp(&right.recovery_id));
    let mut source_events = input.source_events;
    source_events.sort_by(|left, right| left.source_event_id.cmp(&right.source_event_id));
    let mut cursor_advances = input.cursor_advances;
    cursor_advances.sort_by(|left, right| left.cursor_id.cmp(&right.cursor_id));

    let mut observation_storage = BTreeMap::new();
    for observation in &observations {
        observation_storage.insert(
            observation.observation.observation_id.as_str().to_owned(),
            ObservationStorage {
                retention_class: input.policy.retention_class.clone(),
                content_encoding: input.policy.content_encoding.clone(),
                force_external: input.policy.force_external,
            },
        );
    }
    let coverage_gap_severity = coverage_gaps
        .iter()
        .map(|gap| {
            (
                gap.gap_id.as_str().to_owned(),
                input.policy.gap_severity.clone(),
            )
        })
        .collect();
    let placeholder = BatchDigest::new(format!("sha256:{}", "0".repeat(64)))?;
    let evidence = DurableIngestBatch {
        contract_version: StableString::new(DURABLE_CONTRACT)?,
        batch_id: input.batch_id,
        expected_digest: placeholder,
        observations,
        source_events,
        assertions,
        coverage_windows,
        coverage_gaps,
        coverage_recoveries,
        cursor_advances,
    };
    let mut store_batch = StoreIngestBatch {
        evidence,
        observation_storage,
        coverage_gap_severity,
        committed_at: input.committed_at,
        writer_clock_id: input.writer_clock_id,
        committed_mono_ns: input.committed_mono_ns,
        writer_build: input.writer_build,
    };
    store_batch.evidence.expected_digest =
        SqliteStore::canonical_batch_digest(&store_batch.evidence)?;
    Ok(AdmissionBatch {
        registrations: input.registrations,
        store: store_batch,
    })
}

/// Join exact Helius, Solana-public, or `PumpPortal` frames to the one durable batch boundary.
/// Source-event declarations and cursor advances remain explicit so the adapter cannot invent
/// natural keys or promote merely observed cursors to authority.
///
/// # Errors
///
/// Returns an error if a frame cannot be losslessly adapted or the batch contract is invalid.
#[cfg(feature = "source-edges")]
pub fn source_frames(
    frames: Vec<SourceFrameInput>,
    source_events: Vec<SourceEventRecord>,
    cursor_advances: Vec<CursorAdvance>,
    batch_id: StableString,
    committed_at: UtcTimestamp,
    writer_clock_id: StableString,
    committed_mono_ns: u64,
) -> Result<AdmissionBatch, AdmissionError> {
    let mut registrations = BTreeMap::new();
    let mut drafts = Vec::with_capacity(frames.len());
    for input in frames {
        let domain_id = match &input.frame.source {
            joshi_sources::SourceId::HeliusHttp => {
                joshi_domain::SourceId::new("helius.http.solana.v1")?
            }
            joshi_sources::SourceId::HeliusWebSocket => {
                joshi_domain::SourceId::new("helius.websocket.solana.v1")?
            }
            joshi_sources::SourceId::PumpPortalWebSocket => {
                joshi_domain::SourceId::new("pumpportal.websocket.data.v1")?
            }
            joshi_sources::SourceId::SolanaPublicHttp => {
                joshi_domain::SourceId::new("solana.public_http.v1")?
            }
            joshi_sources::SourceId::SolanaPublicWebSocket => {
                joshi_domain::SourceId::new("solana.public_websocket.v1")?
            }
            joshi_sources::SourceId::Other(value) => {
                joshi_domain::SourceId::new(format!("source.other.{value}"))?
            }
        };
        registrations
            .entry(domain_id.as_str().to_owned())
            .or_insert(source_registration(
                domain_id,
                "read_only_market_source",
                &input.frame.contract_version,
                env!("CARGO_PKG_VERSION"),
            )?);
        let mut draft = joshi_sources::observation_draft(input.frame, input.context)?;
        if let EvidenceDraft::Observation(observation) = &mut draft {
            // The source edge describes its concrete operation as an HTTP request or stream
            // frame. The durable schema keeps that distinction in transport/observation kind;
            // its acquisition-kind controlled vocabulary classifies both as live collection.
            observation.acquisition.acquisition_kind = OpenVariant::known("live")?;
        }
        drafts.push(draft);
    }
    source_drafts(SourceDraftBatch {
        batch_id,
        drafts,
        source_events,
        cursor_advances,
        registrations: registrations.into_values().collect(),
        policy: AdmissionPolicy::public_source()?,
        committed_at,
        writer_clock_id,
        committed_mono_ns,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })
}

/// Derive deterministic durable registration metadata for a source configuration.
///
/// # Errors
///
/// Returns an error if a source metadata field violates the stable wire contract.
pub fn source_registration(
    source_id: joshi_domain::SourceId,
    namespace: &str,
    contract_version: &str,
    collector_build: &str,
) -> Result<SourceRegistration, AdmissionError> {
    let material = format!(
        "joshi.source.registration.v1\0{}\0{namespace}\0{contract_version}\0{collector_build}",
        source_id.as_str()
    );
    Ok(SourceRegistration {
        source_id,
        namespace: StableString::new(namespace)?,
        contract_version: StableString::new(contract_version)?,
        collector_build: StableString::new(collector_build)?,
        configuration_digest: ValueDigest::new(
            Sha256Digest::of_bytes(material.as_bytes()).to_string(),
        )?,
    })
}
