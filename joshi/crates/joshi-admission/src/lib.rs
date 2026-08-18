//! Strict local admission joins between read-only source edges and the durable evidence store.
//!
//! This crate owns validation, digest separation, canonical public receipts, and source-specific
//! mapping. It contains no network client, wallet material, transaction builder, signer, or submitter.

mod batch;
mod companion;
mod digest;
pub mod operational;
#[cfg(feature = "source-edges")]
mod pump;
mod receipt;
pub mod strict_json;
pub mod wave5;
mod wave5_components;

pub use batch::{AdmissionBatch, AdmissionPolicy, SourceDraftBatch, source_drafts};
#[cfg(feature = "source-edges")]
pub use batch::{SourceFrameInput, source_frames};
pub use companion::{
    COMPANION_BATCH_CONTRACT, COMPANION_RECEIPT_CONTRACT, CompanionAdmission, CompanionReceiptV1,
    ParsedCompanionBatch, admit_companion, parse_companion,
};
pub use digest::{DigestError, Sha256Digest};
#[cfg(feature = "source-edges")]
pub use pump::{PumpAdmission, acknowledge_pump_reservations, admit_pump_outcome};
pub use receipt::{
    PublicAdmittedCounts, PublicBoundary, PublicCoverageScope, PublicGapOutcome, PublicStatus,
    PublicStoreReceiptV1,
};

use thiserror::Error;

#[derive(Debug, Error)]
pub enum AdmissionError {
    #[error(transparent)]
    Digest(#[from] DigestError),
    #[error(transparent)]
    StrictJson(#[from] strict_json::StrictJsonError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Integer(#[from] joshi_domain::WireIntegerError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    #[cfg(feature = "source-edges")]
    Source(#[from] joshi_sources::EvidenceAdapterError),
    #[error(transparent)]
    #[cfg(feature = "source-edges")]
    Identity(#[from] joshi_pump_api::identity::IdentityError),
    #[error("invalid admission contract: {0}")]
    Contract(String),
    #[error("invalid admission receipt: {0}")]
    Receipt(String),
    #[error("invalid source envelope: {0}")]
    SourceEnvelope(String),
}
