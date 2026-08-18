//! Strict direct-Pump and companion ingress closure at the durable admission boundary.
//!
//! Source ingress bytes, canonical logical batch bytes, physical-policy bytes, and the store
//! admission digest are deliberately separate digest domains. This crate owns no HTTP endpoint,
//! source credential, session broker, wallet key, or economic action.

use std::collections::{BTreeMap, BTreeSet};

use joshi_admission::{
    AdmissionBatch, AdmissionPolicy, CompanionAdmission, CompanionReceiptV1, PublicStatus,
    PublicStoreReceiptV1, PumpAdmission, Sha256Digest, SourceDraftBatch,
    acknowledge_pump_reservations, admit_companion, admit_pump_outcome, parse_companion,
    source_drafts, strict_json,
};
use joshi_domain::{
    AcquisitionClocks, AcquisitionId, ObservationId, OpenVariant, RequestFingerprint, SourceId,
    StableString, UtcTimestamp, ValueDigest, WireU64,
};
use joshi_evidence::{
    AcquisitionRecord, EvidenceDraft, MonotonicReading, ObservationDraft, ObservationEventTime,
    ObservationMetadata, ObservationTiming,
};
use joshi_pump_api::{
    FetchOutcome, IdentityStore, ParityInputV2, ParityReportV2, PromotionReportV1, PromotionRunV1,
    compare_v2, evaluate_promotion,
};
use joshi_spool::EvidenceBatchEntry;
use joshi_store::SourceRegistration;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const PUMP_POLICY_CONTRACT: &str = "joshi.pump_source.physical_policy.v1";
pub const PUMP_RECEIPT_CONTRACT: &str = "joshi.pump_source.admission_receipt.v1";
pub const PUMP_MEASUREMENT_RECEIPT_CONTRACT: &str = "joshi.pump_source.measurement_receipt.v1";
pub const MAX_DIRECT_INGRESS_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_PUBLIC_RECEIPT_BYTES: usize = 128 * 1024;
pub const PARITY_MEASUREMENT_SOURCE: &str = "pump.parity.measurement.v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PumpSourceKind {
    DirectPumpApi,
    PumpCompanion,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ByteClosureV1 {
    pub digest: Sha256Digest,
    pub bytes: String,
}

impl ByteClosureV1 {
    fn of(bytes: &[u8]) -> Self {
        Self {
            digest: Sha256Digest::of_bytes(bytes),
            bytes: bytes.len().to_string(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PumpIngressClosureV1 {
    pub source_kind: PumpSourceKind,
    pub ingress_contract: String,
    pub ingress_id: String,
    pub exact_ingress: ByteClosureV1,
    /// A source-declared semantic digest when the source protocol supplies one. This is not the
    /// digest of received HTTP bytes and is never compared to the durable logical digest.
    pub source_declared_digest: Option<Sha256Digest>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PolicyEntryV1 {
    retention_class: String,
    content_encoding: Option<String>,
    force_external: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PumpPhysicalPolicyV1 {
    contract: String,
    observation_storage: BTreeMap<String, PolicyEntryV1>,
    coverage_gap_severity: BTreeMap<String, String>,
    committed_at: String,
    writer_clock_id: String,
    committed_monotonic_ns: String,
    writer_build: String,
}

enum SourceAdmission {
    Direct(PumpAdmission),
    Companion(CompanionAdmission),
}

/// One prepared source batch. Exact bytes are intentionally omitted from `Debug` and public DTOs;
/// callers may borrow them only to append the same bytes to the local protected spool.
pub struct PreparedPumpAdmission {
    source: SourceAdmission,
    ingress: PumpIngressClosureV1,
    exact_ingress_bytes: Vec<u8>,
    exact_batch_bytes: Vec<u8>,
    exact_policy_bytes: Vec<u8>,
    exact_batch: ByteClosureV1,
    exact_policy: ByteClosureV1,
    acquisition_ids: Vec<String>,
    gap_ids: Vec<String>,
}

impl PreparedPumpAdmission {
    #[must_use]
    pub fn source_kind(&self) -> PumpSourceKind {
        self.ingress.source_kind
    }

    #[must_use]
    pub fn ingress(&self) -> &PumpIngressClosureV1 {
        &self.ingress
    }

    #[must_use]
    pub fn admission_batch(&self) -> &AdmissionBatch {
        match &self.source {
            SourceAdmission::Direct(value) => &value.batch,
            SourceAdmission::Companion(value) => &value.batch,
        }
    }

    #[must_use]
    pub fn exact_ingress_bytes(&self) -> &[u8] {
        &self.exact_ingress_bytes
    }

    #[must_use]
    pub fn exact_batch_bytes(&self) -> &[u8] {
        &self.exact_batch_bytes
    }

    #[must_use]
    pub fn exact_policy_bytes(&self) -> &[u8] {
        &self.exact_policy_bytes
    }

    /// Build the exact spool entry. Supplying a store admission digest is valid only after the
    /// matching catalog receipt has been verified by [`close_receipt`].
    ///
    /// # Errors
    ///
    /// Returns an error if exact bytes, the logical digest, or policy closure disagree.
    pub fn spool_entry(
        &self,
        store_admission_digest: Option<&ValueDigest>,
    ) -> Result<EvidenceBatchEntry, PumpAdapterError> {
        EvidenceBatchEntry::from_exact_bytes(
            &self.admission_batch().store.evidence,
            self.exact_batch_bytes.clone(),
            PUMP_POLICY_CONTRACT,
            self.exact_policy_bytes.clone(),
            store_admission_digest,
        )
        .map_err(|error| PumpAdapterError::Spool(error.to_string()))
    }

    /// Produce the extension-facing receipt for companion ingress after the same exact catalog
    /// receipt has closed. Direct ingress has no browser ACK contract.
    ///
    /// # Errors
    ///
    /// Returns an error for direct ingress or any source/store closure mismatch.
    pub fn companion_receipt(
        &self,
        receipt: &PublicStoreReceiptV1,
    ) -> Result<CompanionReceiptV1, PumpAdapterError> {
        let SourceAdmission::Companion(admission) = &self.source else {
            return Err(PumpAdapterError::Contract(
                "direct Pump ingress has no companion receipt".into(),
            ));
        };
        CompanionReceiptV1::from_committed(admission, receipt)
            .map_err(|error| PumpAdapterError::Admission(error.to_string()))
    }

    /// Acknowledge restart-safe direct-client occurrence reservations only after exact closure.
    ///
    /// # Errors
    ///
    /// Returns an error for companion ingress or a mismatching receipt/reservation.
    pub fn acknowledge_direct(
        &self,
        identities: &IdentityStore,
        receipt: &PublicStoreReceiptV1,
    ) -> Result<(), PumpAdapterError> {
        let SourceAdmission::Direct(admission) = &self.source else {
            return Err(PumpAdapterError::Contract(
                "companion ingress has no direct-client reservation".into(),
            ));
        };
        acknowledge_pump_reservations(identities, admission, receipt)
            .map_err(|error| PumpAdapterError::Admission(error.to_string()))
    }
}

/// Strictly parse exact direct-client ingress bytes and prepare their durable/spool closure.
///
/// # Errors
///
/// Returns an error for oversized, duplicate-key, dangerous-key, unknown-field, source-contract,
/// clock, body, coverage, or canonical admission failures.
pub fn prepare_direct(
    bytes: &[u8],
    durable_batch_id: &str,
    committed_at: UtcTimestamp,
    committed_monotonic_ns: u64,
) -> Result<PreparedPumpAdmission, PumpAdapterError> {
    let outcome: FetchOutcome = strict_json::parse(bytes, MAX_DIRECT_INGRESS_BYTES)
        .map_err(|error| PumpAdapterError::Strict(error.to_string()))?;
    let ingress = PumpIngressClosureV1 {
        source_kind: PumpSourceKind::DirectPumpApi,
        ingress_contract: outcome.contract.clone(),
        ingress_id: outcome.request_group_id.clone(),
        exact_ingress: ByteClosureV1::of(bytes),
        source_declared_digest: None,
    };
    let admission = admit_pump_outcome(
        &outcome,
        durable_batch_id,
        committed_at,
        committed_monotonic_ns,
    )
    .map_err(|error| PumpAdapterError::Admission(error.to_string()))?;
    prepared(SourceAdmission::Direct(admission), ingress, bytes)
}

/// Strictly parse exact companion batch bytes and prepare their durable/spool closure.
///
/// # Errors
///
/// Returns an error for oversized, ambiguous, source-digest, boundary, evidence, or canonical
/// admission failures.
pub fn prepare_companion(
    bytes: &[u8],
    committed_at: UtcTimestamp,
    committed_monotonic_ns: u64,
    writer_clock_id: &str,
) -> Result<PreparedPumpAdmission, PumpAdapterError> {
    let parsed =
        parse_companion(bytes).map_err(|error| PumpAdapterError::Admission(error.to_string()))?;
    let ingress = PumpIngressClosureV1 {
        source_kind: PumpSourceKind::PumpCompanion,
        ingress_contract: joshi_admission::COMPANION_BATCH_CONTRACT.into(),
        ingress_id: parsed.ingress_batch_id().into(),
        exact_ingress: ByteClosureV1::of(bytes),
        source_declared_digest: Some(parsed.ingress_digest().clone()),
    };
    let admission = admit_companion(
        parsed,
        committed_at,
        committed_monotonic_ns,
        writer_clock_id,
    )
    .map_err(|error| PumpAdapterError::Admission(error.to_string()))?;
    prepared(SourceAdmission::Companion(admission), ingress, bytes)
}

/// Exact private evidence for one re-derived V2 parity comparison. No mismatch is promoted to a
/// fact; the two exact input envelopes and exact generated report are retained as observations.
pub struct PreparedParityMeasurement {
    pub batch: AdmissionBatch,
    pub report: ParityReportV2,
    pub report_bytes: Vec<u8>,
    exact: ExactAdmissionMaterial,
}

/// Exact promotion evaluation prepared for durable admission. It remains measurement evidence,
/// not authority to add a route to census or start a collector.
pub struct PreparedPromotionMeasurement {
    pub batch: AdmissionBatch,
    pub report: PromotionReportV1,
    pub report_bytes: Vec<u8>,
    exact: ExactAdmissionMaterial,
}

struct ExactAdmissionMaterial {
    batch_bytes: Vec<u8>,
    policy_bytes: Vec<u8>,
    batch_closure: ByteClosureV1,
    policy_closure: ByteClosureV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PumpMeasurementReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub measurement_kind: String,
    pub artifact_contract: String,
    pub exact_artifact: ByteClosureV1,
    pub durable_batch_id: String,
    pub durable_logical_digest: Sha256Digest,
    pub exact_batch: ByteClosureV1,
    pub policy_contract: String,
    pub exact_policy: ByteClosureV1,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub store_admission_digest: Sha256Digest,
    pub status: PublicStatus,
    pub from_commit_seq: String,
    pub through_commit_seq: String,
    pub committed_acquisition_ids: Vec<String>,
    pub committed_gap_ids: Vec<String>,
}

impl PreparedParityMeasurement {
    /// Build the exact private spool entry for this parity measurement.
    ///
    /// # Errors
    ///
    /// Returns an error if the retained exact batch/policy bytes no longer close the batch.
    pub fn spool_entry(
        &self,
        store_admission_digest: Option<&ValueDigest>,
    ) -> Result<EvidenceBatchEntry, PumpAdapterError> {
        measurement_spool_entry(&self.batch, &self.exact, store_admission_digest)
    }

    /// Close the parity artifact against the exact public store receipt.
    ///
    /// # Errors
    ///
    /// Returns an error if any durable identity, digest, count, gap, or commit range differs.
    pub fn close_receipt(
        &self,
        receipt: &PublicStoreReceiptV1,
    ) -> Result<PumpMeasurementReceiptV1, PumpAdapterError> {
        close_measurement_receipt(
            "parity_v2",
            "joshi.pump_api.parity_report.v2",
            &self.report_bytes,
            &self.batch,
            &self.exact,
            receipt,
        )
    }
}

impl PreparedPromotionMeasurement {
    /// Build the exact private spool entry for this promotion measurement.
    ///
    /// # Errors
    ///
    /// Returns an error if the retained exact batch/policy bytes no longer close the batch.
    pub fn spool_entry(
        &self,
        store_admission_digest: Option<&ValueDigest>,
    ) -> Result<EvidenceBatchEntry, PumpAdapterError> {
        measurement_spool_entry(&self.batch, &self.exact, store_admission_digest)
    }

    /// Close the promotion artifact against the exact public store receipt.
    ///
    /// # Errors
    ///
    /// Returns an error if any durable identity, digest, count, gap, or commit range differs.
    pub fn close_receipt(
        &self,
        receipt: &PublicStoreReceiptV1,
    ) -> Result<PumpMeasurementReceiptV1, PumpAdapterError> {
        close_measurement_receipt(
            "promotion_v1",
            "joshi.pump_api.promotion_report.v1",
            &self.report_bytes,
            &self.batch,
            &self.exact,
            receipt,
        )
    }
}

/// Strictly re-evaluate an exact promotion run and retain both run and report as private evidence.
///
/// # Errors
///
/// Returns an error for ambiguous/oversized input or invalid durable evidence construction.
#[allow(clippy::too_many_lines)] // One constructor keeps the evidence occurrence closure visible.
pub fn prepare_promotion_measurement(
    run_bytes: &[u8],
    durable_batch_id: &str,
    committed_at: UtcTimestamp,
    committed_monotonic_ns: u64,
    writer_clock_id: &str,
) -> Result<PreparedPromotionMeasurement, PumpAdapterError> {
    let run: PromotionRunV1 = strict_json::parse(run_bytes, MAX_DIRECT_INGRESS_BYTES)
        .map_err(|error| PumpAdapterError::Strict(error.to_string()))?;
    let report = evaluate_promotion(&run);
    let report_bytes = serde_json::to_vec(&report)?;
    let content = Sha256Digest::of_bytes([run_bytes, report_bytes.as_slice()].concat().as_slice());
    let source_id = SourceId::new("pump.promotion.measurement.v1")
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    let writer_clock = StableString::new(writer_clock_id)
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    let quality_code = if report.disposition == "promotable_continuous_direct_source" {
        None
    } else {
        Some(
            StableString::new("not_promoted")
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        )
    };
    let acquisition = AcquisitionRecord {
        acquisition_id: AcquisitionId::new(format!(
            "acq:pump-promotion:{}",
            content.as_str().trim_start_matches("sha256:")
        ))
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        source_id: source_id.clone(),
        acquisition_kind: OpenVariant::known("manual")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        transport_kind: OpenVariant::known("operator")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        parent_acquisition_id: None,
        request_fingerprint: RequestFingerprint::new(Sha256Digest::of_bytes(run_bytes).to_string())
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        contract_version: StableString::new("joshi.pump_api.promotion_report.v1")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        started_at: committed_at,
        started_monotonic: Some(MonotonicReading {
            clock_id: writer_clock.clone(),
            nanoseconds: WireU64::new(committed_monotonic_ns),
        }),
        source_locator: Some(
            StableString::new("local:pump-promotion-measurement")
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        ),
        source_cursor: Some(
            StableString::new(run.run_id.clone())
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        ),
        clocks: AcquisitionClocks {
            requested_at: None,
            received_at: committed_at,
            persisted_at: committed_at,
            monotonic_elapsed_ns: Some(WireU64::new(0)),
            monotonic_domain: Some(writer_clock.clone()),
        },
    };
    let mut drafts = Vec::new();
    for (ordinal, (variant, payload)) in [
        ("promotion_run", run_bytes.to_vec()),
        ("promotion_report", report_bytes.clone()),
    ]
    .into_iter()
    .enumerate()
    {
        drafts.push(EvidenceDraft::Observation(ObservationDraft {
            acquisition: acquisition.clone(),
            observation: ObservationMetadata {
                observation_id: ObservationId::new(format!(
                    "obs:pump-promotion:{}:{ordinal}",
                    content.as_str().trim_start_matches("sha256:")
                ))
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                acquisition_ordinal: WireU64::new(ordinal as u64),
                observation_kind: OpenVariant::known("snapshot")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                source_events: Vec::new(),
                source_variant: OpenVariant::known(variant)
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                event_time: ObservationEventTime {
                    status: OpenVariant::known("not_applicable")
                        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                    lower: None,
                    upper: None,
                    precision_us: None,
                },
                chain: None,
                source_cursor: Some(
                    StableString::new(run.run_id.clone())
                        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                ),
                timing: ObservationTiming {
                    received_at: committed_at,
                    received_monotonic: MonotonicReading {
                        clock_id: writer_clock.clone(),
                        nanoseconds: WireU64::new(committed_monotonic_ns),
                    },
                    persisted_at: committed_at,
                    available_at: committed_at,
                },
                parse_disposition: OpenVariant::known("decoded")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                quality_code: quality_code.clone(),
                media_type: StableString::new("application/json")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
            },
            payload,
        }));
    }
    let registration = SourceRegistration {
        source_id,
        namespace: StableString::new("pump_promotion_measurement")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        contract_version: StableString::new("joshi.pump_api.promotion_report.v1")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        collector_build: StableString::new(env!("CARGO_PKG_VERSION"))
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        configuration_digest: ValueDigest::new(
            Sha256Digest::of_bytes(b"joshi.pump_adapter.promotion_measurement.v1").to_string(),
        )
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
    };
    let batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(durable_batch_id)
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        drafts,
        source_events: Vec::new(),
        cursor_advances: Vec::new(),
        registrations: vec![registration],
        policy: AdmissionPolicy::authenticated_private()
            .map_err(|error| PumpAdapterError::Admission(error.to_string()))?,
        committed_at,
        writer_clock_id: writer_clock,
        committed_mono_ns: committed_monotonic_ns,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
    })
    .map_err(|error| PumpAdapterError::Admission(error.to_string()))?;
    let exact = exact_admission_material(&batch)?;
    Ok(PreparedPromotionMeasurement {
        batch,
        report,
        report_bytes,
        exact,
    })
}

/// Strictly parse both exact parity inputs, re-derive the report, and prepare private admission.
///
/// # Errors
///
/// Returns an error for ambiguous/oversized input, invalid clocks/identities, or durable evidence
/// construction failure. An incomparable or mismatching report is still admitted as evidence.
#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
pub fn prepare_parity_measurement(
    companion_bytes: &[u8],
    direct_bytes: &[u8],
    durable_batch_id: &str,
    committed_at: UtcTimestamp,
    committed_monotonic_ns: u64,
    writer_clock_id: &str,
    maximum_pair_skew_us: u64,
    maximum_mismatches: usize,
) -> Result<PreparedParityMeasurement, PumpAdapterError> {
    let companion: ParityInputV2 = strict_json::parse(companion_bytes, MAX_DIRECT_INGRESS_BYTES)
        .map_err(|error| PumpAdapterError::Strict(error.to_string()))?;
    let direct: ParityInputV2 = strict_json::parse(direct_bytes, MAX_DIRECT_INGRESS_BYTES)
        .map_err(|error| PumpAdapterError::Strict(error.to_string()))?;
    let report = compare_v2(
        &companion,
        &direct,
        maximum_pair_skew_us,
        maximum_mismatches,
    );
    let report_bytes = serde_json::to_vec(&report)?;
    let source_id = SourceId::new(PARITY_MEASUREMENT_SOURCE)
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    let writer_clock = StableString::new(writer_clock_id)
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    let report_received_at = if companion.received_at >= direct.received_at {
        &companion.received_at
    } else {
        &direct.received_at
    }
    .parse::<UtcTimestamp>()
    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
    let quality_code = if report.precondition_failures.is_empty() {
        None
    } else {
        Some(
            StableString::new("incomparable_retained")
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        )
    };
    let occurrence = Sha256Digest::of_bytes(
        format!(
            "{}\n{}\n{}",
            report.pair_id, companion.blob_id, direct.blob_id
        )
        .as_bytes(),
    );
    let measurement_acquisition =
        |side: &str, input: &ParityInputV2| -> Result<AcquisitionRecord, PumpAdapterError> {
            let started_at = input
                .started_at
                .parse::<UtcTimestamp>()
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
            let received_at = input
                .received_at
                .parse::<UtcTimestamp>()
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?;
            Ok(AcquisitionRecord {
                acquisition_id: AcquisitionId::new(format!(
                    "acq:pump-parity:{}:{side}",
                    occurrence.as_str().trim_start_matches("sha256:")
                ))
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                source_id: source_id.clone(),
                acquisition_kind: OpenVariant::known("manual")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                transport_kind: OpenVariant::known("operator")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                parent_acquisition_id: None,
                request_fingerprint: RequestFingerprint::new(input.request_fingerprint.clone())
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                contract_version: StableString::new("joshi.pump_api.parity_report.v2")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                started_at,
                started_monotonic: None,
                source_locator: Some(
                    StableString::new(format!(
                        "local:pump-parity-measurement:{side}:{}",
                        input.source_acquisition_id
                    ))
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                ),
                source_cursor: Some(
                    StableString::new(report.pair_id.clone())
                        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                ),
                clocks: AcquisitionClocks {
                    requested_at: None,
                    received_at,
                    persisted_at: committed_at,
                    monotonic_elapsed_ns: None,
                    monotonic_domain: None,
                },
            })
        };
    let companion_acquisition = measurement_acquisition("companion", &companion)?;
    let direct_acquisition = measurement_acquisition("direct", &direct)?;
    let payloads = [
        (
            companion_acquisition,
            0_u64,
            "companion_parity_input",
            companion_bytes.to_vec(),
        ),
        (
            direct_acquisition.clone(),
            0_u64,
            "direct_parity_input",
            direct_bytes.to_vec(),
        ),
        (
            direct_acquisition,
            1_u64,
            "parity_report",
            report_bytes.clone(),
        ),
    ];
    let mut drafts = Vec::new();
    for (index, (acquisition, ordinal, variant, payload)) in payloads.into_iter().enumerate() {
        drafts.push(EvidenceDraft::Observation(ObservationDraft {
            acquisition,
            observation: ObservationMetadata {
                observation_id: ObservationId::new(format!(
                    "obs:pump-parity:{}:{index}",
                    occurrence.as_str().trim_start_matches("sha256:")
                ))
                .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                acquisition_ordinal: WireU64::new(ordinal),
                observation_kind: OpenVariant::known("snapshot")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                source_events: Vec::new(),
                source_variant: OpenVariant::known(variant)
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                event_time: ObservationEventTime {
                    status: OpenVariant::known("not_applicable")
                        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                    lower: None,
                    upper: None,
                    precision_us: None,
                },
                chain: None,
                source_cursor: Some(
                    StableString::new(report.pair_id.clone())
                        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                ),
                timing: ObservationTiming {
                    received_at: report_received_at,
                    received_monotonic: MonotonicReading {
                        clock_id: writer_clock.clone(),
                        nanoseconds: WireU64::new(committed_monotonic_ns),
                    },
                    persisted_at: committed_at,
                    available_at: committed_at,
                },
                parse_disposition: OpenVariant::known("decoded")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
                quality_code: quality_code.clone(),
                media_type: StableString::new("application/json")
                    .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
            },
            payload,
        }));
    }
    let registration = SourceRegistration {
        source_id,
        namespace: StableString::new("pump_parity_measurement")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        contract_version: StableString::new("joshi.pump_api.parity_report.v2")
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        collector_build: StableString::new(env!("CARGO_PKG_VERSION"))
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        configuration_digest: ValueDigest::new(
            Sha256Digest::of_bytes(b"joshi.pump_adapter.parity_measurement.v1").to_string(),
        )
        .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
    };
    let batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(durable_batch_id)
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
        drafts,
        source_events: Vec::new(),
        cursor_advances: Vec::new(),
        registrations: vec![registration],
        policy: AdmissionPolicy::authenticated_private()
            .map_err(|error| PumpAdapterError::Admission(error.to_string()))?,
        committed_at,
        writer_clock_id: writer_clock,
        committed_mono_ns: committed_monotonic_ns,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))
            .map_err(|error| PumpAdapterError::Contract(error.to_string()))?,
    })
    .map_err(|error| PumpAdapterError::Admission(error.to_string()))?;
    let exact = exact_admission_material(&batch)?;
    Ok(PreparedParityMeasurement {
        batch,
        report,
        report_bytes,
        exact,
    })
}

fn prepared(
    source: SourceAdmission,
    ingress: PumpIngressClosureV1,
    exact_ingress_bytes: &[u8],
) -> Result<PreparedPumpAdmission, PumpAdapterError> {
    let admission = match &source {
        SourceAdmission::Direct(value) => &value.batch,
        SourceAdmission::Companion(value) => &value.batch,
    };
    let acquisition_ids = match &source {
        SourceAdmission::Direct(value) => value.acquisition_ids.clone(),
        SourceAdmission::Companion(value) => value.parsed.acquisition_ids(),
    };
    let gap_ids = match &source {
        SourceAdmission::Direct(value) => value.coverage_gap_ids.clone(),
        SourceAdmission::Companion(value) => value.parsed.gap_ids(),
    };
    let exact = exact_admission_material(admission)?;
    Ok(PreparedPumpAdmission {
        source,
        ingress,
        exact_ingress_bytes: exact_ingress_bytes.to_vec(),
        exact_batch: exact.batch_closure,
        exact_policy: exact.policy_closure,
        exact_batch_bytes: exact.batch_bytes,
        exact_policy_bytes: exact.policy_bytes,
        acquisition_ids,
        gap_ids,
    })
}

fn exact_admission_material(
    admission: &AdmissionBatch,
) -> Result<ExactAdmissionMaterial, PumpAdapterError> {
    let exact_batch_bytes = serde_json::to_vec(&admission.store.evidence)?;
    let policy = PumpPhysicalPolicyV1 {
        contract: PUMP_POLICY_CONTRACT.into(),
        observation_storage: admission
            .store
            .observation_storage
            .iter()
            .map(|(id, value)| {
                (
                    id.clone(),
                    PolicyEntryV1 {
                        retention_class: value.retention_class.as_str().into(),
                        content_encoding: value
                            .content_encoding
                            .as_ref()
                            .map(|item| item.as_str().into()),
                        force_external: value.force_external,
                    },
                )
            })
            .collect(),
        coverage_gap_severity: admission
            .store
            .coverage_gap_severity
            .iter()
            .map(|(id, value)| (id.clone(), value.as_str().into()))
            .collect(),
        committed_at: admission.store.committed_at.to_string(),
        writer_clock_id: admission.store.writer_clock_id.as_str().into(),
        committed_monotonic_ns: admission.store.committed_mono_ns.to_string(),
        writer_build: admission.store.writer_build.as_str().into(),
    };
    let exact_policy_bytes = serde_json::to_vec(&policy)?;
    // Exercise the spool decoder/closure before returning a prepared batch.
    EvidenceBatchEntry::from_exact_bytes(
        &admission.store.evidence,
        exact_batch_bytes.clone(),
        PUMP_POLICY_CONTRACT,
        exact_policy_bytes.clone(),
        None,
    )
    .map_err(|error| PumpAdapterError::Spool(error.to_string()))?;
    Ok(ExactAdmissionMaterial {
        batch_closure: ByteClosureV1::of(&exact_batch_bytes),
        policy_closure: ByteClosureV1::of(&exact_policy_bytes),
        batch_bytes: exact_batch_bytes,
        policy_bytes: exact_policy_bytes,
    })
}

fn measurement_spool_entry(
    batch: &AdmissionBatch,
    exact: &ExactAdmissionMaterial,
    store_admission_digest: Option<&ValueDigest>,
) -> Result<EvidenceBatchEntry, PumpAdapterError> {
    EvidenceBatchEntry::from_exact_bytes(
        &batch.store.evidence,
        exact.batch_bytes.clone(),
        PUMP_POLICY_CONTRACT,
        exact.policy_bytes.clone(),
        store_admission_digest,
    )
    .map_err(|error| PumpAdapterError::Spool(error.to_string()))
}

fn close_measurement_receipt(
    measurement_kind: &str,
    artifact_contract: &str,
    artifact_bytes: &[u8],
    batch: &AdmissionBatch,
    exact: &ExactAdmissionMaterial,
    receipt: &PublicStoreReceiptV1,
) -> Result<PumpMeasurementReceiptV1, PumpAdapterError> {
    let evidence = &batch.store.evidence;
    let acquisition_ids = evidence
        .observations
        .iter()
        .map(|value| value.acquisition.acquisition_id.to_string())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let gap_ids = evidence
        .coverage_gaps
        .iter()
        .map(|value| value.gap_id.to_string())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    if receipt.contract != "joshi.store.ingest_receipt"
        || receipt.schema_version != 1
        || receipt.batch_id != evidence.batch_id.as_str()
        || receipt.batch_digest.as_str() != evidence.expected_digest.as_str()
        || receipt.acquisition_ids != acquisition_ids
        || receipt.commit_seq != receipt.from_commit_seq
        || receipt.from_commit_seq != receipt.through_commit_seq
    {
        return Err(PumpAdapterError::Receipt(
            "public store receipt does not close Pump measurement admission".into(),
        ));
    }
    let receipt_gaps = receipt
        .gap_outcomes
        .iter()
        .map(|value| value.gap_id.clone())
        .collect::<Vec<_>>();
    if receipt_gaps != gap_ids {
        return Err(PumpAdapterError::Receipt(
            "public store receipt measurement gap closure differs".into(),
        ));
    }
    let expected = measurement_spool_entry(batch, exact, None)?.closure.counts;
    let admitted = &receipt.admitted;
    let count_pairs = [
        (expected.acquisitions, admitted.acquisitions.as_str()),
        (expected.raw_blobs, admitted.raw_blobs.as_str()),
        (expected.raw_bytes, admitted.raw_bytes.as_str()),
        (expected.observations, admitted.observations.as_str()),
        (expected.source_events, admitted.source_events.as_str()),
        (expected.assertions, admitted.assertions.as_str()),
        (
            expected.coverage_windows,
            admitted.coverage_windows.as_str(),
        ),
        (expected.coverage_gaps, admitted.coverage_gaps.as_str()),
        (
            expected.coverage_recoveries,
            admitted.coverage_recoveries.as_str(),
        ),
        (expected.cursor_advances, admitted.cursor_advances.as_str()),
    ];
    if count_pairs
        .iter()
        .any(|(expected, actual)| expected.to_string() != *actual)
    {
        return Err(PumpAdapterError::Receipt(
            "public store receipt measurement admitted counts differ".into(),
        ));
    }
    Ok(PumpMeasurementReceiptV1 {
        contract: PUMP_MEASUREMENT_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        measurement_kind: measurement_kind.into(),
        artifact_contract: artifact_contract.into(),
        exact_artifact: ByteClosureV1::of(artifact_bytes),
        durable_batch_id: receipt.batch_id.clone(),
        durable_logical_digest: receipt.batch_digest.clone(),
        exact_batch: exact.batch_closure.clone(),
        policy_contract: PUMP_POLICY_CONTRACT.into(),
        exact_policy: exact.policy_closure.clone(),
        catalog_id: receipt.catalog_id.clone(),
        catalog_schema: receipt.catalog_schema.clone(),
        store_admission_digest: receipt.store_admission_digest.clone(),
        status: receipt.status.clone(),
        from_commit_seq: receipt.from_commit_seq.clone(),
        through_commit_seq: receipt.through_commit_seq.clone(),
        committed_acquisition_ids: acquisition_ids,
        committed_gap_ids: gap_ids,
    })
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PumpAdmissionReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub source_kind: PumpSourceKind,
    pub ingress_contract: String,
    pub ingress_id: String,
    pub exact_ingress: ByteClosureV1,
    pub source_declared_digest: Option<Sha256Digest>,
    pub durable_batch_id: String,
    pub durable_logical_digest: Sha256Digest,
    pub exact_batch: ByteClosureV1,
    pub policy_contract: String,
    pub exact_policy: ByteClosureV1,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub store_admission_digest: Sha256Digest,
    pub status: PublicStatus,
    pub from_commit_seq: String,
    pub through_commit_seq: String,
    pub committed_acquisition_ids: Vec<String>,
    pub committed_gap_ids: Vec<String>,
}

/// Validate the exact public store receipt and bind all source, spool, logical, and physical
/// digest domains into one Pump-specific closure.
///
/// # Errors
///
/// Returns an error if any batch/digest/acquisition/gap/commit identity differs.
pub fn close_receipt(
    prepared: &PreparedPumpAdmission,
    receipt: &PublicStoreReceiptV1,
) -> Result<PumpAdmissionReceiptV1, PumpAdapterError> {
    let evidence = &prepared.admission_batch().store.evidence;
    if receipt.contract != "joshi.store.ingest_receipt"
        || receipt.schema_version != 1
        || receipt.batch_id != evidence.batch_id.as_str()
        || receipt.batch_digest.as_str() != evidence.expected_digest.as_str()
        || receipt.acquisition_ids != prepared.acquisition_ids
        || receipt.commit_seq != receipt.from_commit_seq
        || receipt.from_commit_seq != receipt.through_commit_seq
    {
        return Err(PumpAdapterError::Receipt(
            "public store receipt does not close prepared Pump admission".into(),
        ));
    }
    let receipt_gaps = receipt
        .gap_outcomes
        .iter()
        .map(|value| value.gap_id.clone())
        .collect::<Vec<_>>();
    if receipt_gaps != prepared.gap_ids {
        return Err(PumpAdapterError::Receipt(
            "public store receipt gap closure differs".into(),
        ));
    }
    let expected = prepared.spool_entry(None)?.closure.counts;
    let admitted = &receipt.admitted;
    let count_pairs = [
        (expected.acquisitions, admitted.acquisitions.as_str()),
        (expected.raw_blobs, admitted.raw_blobs.as_str()),
        (expected.raw_bytes, admitted.raw_bytes.as_str()),
        (expected.observations, admitted.observations.as_str()),
        (expected.source_events, admitted.source_events.as_str()),
        (expected.assertions, admitted.assertions.as_str()),
        (
            expected.coverage_windows,
            admitted.coverage_windows.as_str(),
        ),
        (expected.coverage_gaps, admitted.coverage_gaps.as_str()),
        (
            expected.coverage_recoveries,
            admitted.coverage_recoveries.as_str(),
        ),
        (expected.cursor_advances, admitted.cursor_advances.as_str()),
    ];
    if count_pairs
        .iter()
        .any(|(expected, actual)| expected.to_string() != *actual)
    {
        return Err(PumpAdapterError::Receipt(
            "public store receipt admitted counts differ".into(),
        ));
    }
    Ok(PumpAdmissionReceiptV1 {
        contract: PUMP_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        source_kind: prepared.ingress.source_kind,
        ingress_contract: prepared.ingress.ingress_contract.clone(),
        ingress_id: prepared.ingress.ingress_id.clone(),
        exact_ingress: prepared.ingress.exact_ingress.clone(),
        source_declared_digest: prepared.ingress.source_declared_digest.clone(),
        durable_batch_id: receipt.batch_id.clone(),
        durable_logical_digest: receipt.batch_digest.clone(),
        exact_batch: prepared.exact_batch.clone(),
        policy_contract: PUMP_POLICY_CONTRACT.into(),
        exact_policy: prepared.exact_policy.clone(),
        catalog_id: receipt.catalog_id.clone(),
        catalog_schema: receipt.catalog_schema.clone(),
        store_admission_digest: receipt.store_admission_digest.clone(),
        status: receipt.status.clone(),
        from_commit_seq: receipt.from_commit_seq.clone(),
        through_commit_seq: receipt.through_commit_seq.clone(),
        committed_acquisition_ids: prepared.acquisition_ids.clone(),
        committed_gap_ids: prepared.gap_ids.clone(),
    })
}

/// Strictly decode a bounded public store receipt before applying [`close_receipt`].
///
/// # Errors
///
/// Returns an error for duplicate/dangerous/unknown keys, oversized JSON, or any closure mismatch.
pub fn close_receipt_bytes(
    prepared: &PreparedPumpAdmission,
    bytes: &[u8],
) -> Result<PumpAdmissionReceiptV1, PumpAdapterError> {
    let receipt: PublicStoreReceiptV1 = strict_json::parse(bytes, MAX_PUBLIC_RECEIPT_BYTES)
        .map_err(|error| PumpAdapterError::Strict(error.to_string()))?;
    close_receipt(prepared, &receipt)
}

#[derive(Debug, Error)]
pub enum PumpAdapterError {
    #[error("strict wire rejection: {0}")]
    Strict(String),
    #[error("source admission rejection: {0}")]
    Admission(String),
    #[error("spool closure rejection: {0}")]
    Spool(String),
    #[error("receipt closure rejection: {0}")]
    Receipt(String),
    #[error("adapter contract rejection: {0}")]
    Contract(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
