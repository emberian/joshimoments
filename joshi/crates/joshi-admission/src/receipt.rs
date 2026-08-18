use crate::{AdmissionError, Sha256Digest};
use joshi_domain::{OpenVariant, StableString};
use joshi_evidence::{Boundary, CoverageScope, DurableIngestBatch};
use joshi_store::{DurableReceipt, IdempotencyStatus};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PublicStatus {
    Accepted,
    Idempotent,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicAdmittedCounts {
    pub acquisitions: String,
    pub raw_blobs: String,
    pub raw_bytes: String,
    pub observations: String,
    pub source_events: String,
    pub assertions: String,
    pub coverage_windows: String,
    pub coverage_gaps: String,
    pub coverage_recoveries: String,
    pub cursor_advances: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicCoverageScope {
    pub source_id: String,
    pub family: OpenVariant,
    pub subject: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "clock",
    rename_all = "snake_case",
    rename_all_fields = "camelCase"
)]
pub enum PublicBoundary {
    Wall { value: String },
    Commit { value: String },
    SourceCursor { value: String },
    Unknown { reason: OpenVariant },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicGapOutcome {
    pub gap_id: String,
    pub scope: PublicCoverageScope,
    pub lower: PublicBoundary,
    pub upper: Option<PublicBoundary>,
    pub outcome: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicStoreReceiptV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_id: String,
    pub catalog_schema: String,
    pub commit_seq: String,
    pub batch_id: String,
    pub batch_digest: Sha256Digest,
    pub store_admission_digest: Sha256Digest,
    pub status: PublicStatus,
    pub from_commit_seq: String,
    pub through_commit_seq: String,
    pub admitted: PublicAdmittedCounts,
    pub acquisition_ids: Vec<String>,
    pub gap_outcomes: Vec<PublicGapOutcome>,
}

impl PublicStoreReceiptV1 {
    /// Convert a structural store receipt to the closed public V1 receipt after exact verification.
    ///
    /// # Errors
    ///
    /// Returns an error if the structural receipt does not close the submitted batch exactly.
    #[allow(clippy::too_many_lines)] // One audit keeps all recursive receipt closure checks together.
    pub fn from_committed(
        receipt: &DurableReceipt,
        submitted: &DurableIngestBatch,
    ) -> Result<Self, AdmissionError> {
        if receipt.contract.as_str() != "joshi.store.ingest_receipt" || receipt.schema_version != 1
        {
            return Err(AdmissionError::Receipt(
                "unsupported structural receipt".into(),
            ));
        }
        if receipt.batch_id != submitted.batch_id
            || receipt.batch_digest != submitted.expected_digest
        {
            return Err(AdmissionError::Receipt(
                "receipt batch closure mismatch".into(),
            ));
        }
        if receipt.commit_seq != receipt.from_commit_seq
            || receipt.commit_seq != receipt.through_commit_seq
        {
            return Err(AdmissionError::Receipt(
                "V1 receipt commit range mismatch".into(),
            ));
        }
        let expected_acquisitions = submitted
            .observations
            .iter()
            .map(|item| item.acquisition.acquisition_id.as_str().to_owned())
            .collect::<BTreeSet<_>>();
        let actual_acquisitions = receipt
            .acquisition_ids
            .iter()
            .map(|value| value.as_str().to_owned())
            .collect::<BTreeSet<_>>();
        if expected_acquisitions != actual_acquisitions
            || receipt
                .acquisition_ids
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
        {
            return Err(AdmissionError::Receipt(
                "receipt acquisition closure mismatch".into(),
            ));
        }
        let expected_gaps = submitted
            .coverage_gaps
            .iter()
            .map(|gap| gap.gap_id.as_str().to_owned())
            .collect::<BTreeSet<_>>();
        let actual_gaps = receipt
            .gap_outcomes
            .iter()
            .map(|gap| gap.gap_id.as_str().to_owned())
            .collect::<BTreeSet<_>>();
        if expected_gaps != actual_gaps
            || receipt
                .gap_outcomes
                .windows(2)
                .any(|pair| pair[0].gap_id >= pair[1].gap_id)
        {
            return Err(AdmissionError::Receipt(
                "receipt gap closure mismatch".into(),
            ));
        }
        Ok(Self {
            contract: receipt.contract.as_str().to_owned(),
            schema_version: 1,
            catalog_id: receipt.catalog_id.as_str().to_owned(),
            catalog_schema: receipt.catalog_schema.as_str().to_owned(),
            commit_seq: receipt.commit_seq.get().to_string(),
            batch_id: receipt.batch_id.as_str().to_owned(),
            batch_digest: Sha256Digest::parse(receipt.batch_digest.as_str())?,
            store_admission_digest: Sha256Digest::parse(receipt.admission_digest.as_str())?,
            status: match receipt.status {
                IdempotencyStatus::Accepted => PublicStatus::Accepted,
                IdempotencyStatus::Idempotent => PublicStatus::Idempotent,
            },
            from_commit_seq: receipt.from_commit_seq.get().to_string(),
            through_commit_seq: receipt.through_commit_seq.get().to_string(),
            admitted: PublicAdmittedCounts {
                acquisitions: receipt.admitted.acquisitions.get().to_string(),
                raw_blobs: receipt.admitted.raw_blobs.get().to_string(),
                raw_bytes: receipt.admitted.raw_bytes.get().to_string(),
                observations: receipt.admitted.observations.get().to_string(),
                source_events: receipt.admitted.source_events.get().to_string(),
                assertions: receipt.admitted.assertions.get().to_string(),
                coverage_windows: receipt.admitted.coverage_windows.get().to_string(),
                coverage_gaps: receipt.admitted.coverage_gaps.get().to_string(),
                coverage_recoveries: receipt.admitted.coverage_recoveries.get().to_string(),
                cursor_advances: receipt.admitted.cursor_advances.get().to_string(),
            },
            acquisition_ids: receipt
                .acquisition_ids
                .iter()
                .map(ToString::to_string)
                .collect(),
            gap_outcomes: receipt
                .gap_outcomes
                .iter()
                .map(|gap| PublicGapOutcome {
                    gap_id: gap.gap_id.to_string(),
                    scope: scope(&gap.scope),
                    lower: boundary(&gap.lower),
                    upper: gap.upper.as_ref().map(boundary),
                    outcome: gap.outcome.as_str().to_owned(),
                })
                .collect(),
        })
    }
}

fn scope(value: &CoverageScope) -> PublicCoverageScope {
    PublicCoverageScope {
        source_id: value.source_id.to_string(),
        family: value.family.clone(),
        subject: value
            .subject
            .as_ref()
            .map(|value| value.as_str().to_owned()),
    }
}

fn boundary(value: &Boundary) -> PublicBoundary {
    match value {
        Boundary::Wall { value } => PublicBoundary::Wall {
            value: value.to_string(),
        },
        Boundary::Commit { value } => PublicBoundary::Commit {
            value: value.get().to_string(),
        },
        Boundary::SourceCursor { value } => PublicBoundary::SourceCursor {
            value: value.as_str().to_owned(),
        },
        Boundary::Unknown { reason } => PublicBoundary::Unknown {
            reason: reason.clone(),
        },
    }
}

#[allow(dead_code)]
fn _stable(value: &StableString) -> &str {
    value.as_str()
}
