use crate::{
    FactProtection, MARKET_STATE_SNAPSHOT_CONTRACT, MarketStateSnapshotV1, READ_ONLY_AUTHORITY,
};
use joshi_domain::{StableString, ValueDigest};
use joshi_store::{ArtifactProtectionClass, SourceFactArtifactCapability, SourceFactFamily};
use sha2::{Digest as _, Sha256};
use thiserror::Error;

/// Failure preparing exact accepted bytes for the V7 source/fact artifact transaction.
#[derive(Debug, Error)]
pub enum StoreArtifactError {
    #[error("market-state snapshot contract or authority is invalid")]
    InvalidSnapshot,
    #[error("market-state snapshot has no effective input closure")]
    EmptyInputClosure,
    #[error("public artifact protection cannot contain private/restricted fact evidence")]
    ProtectionMismatch,
    #[error("market-state snapshot JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("store capability rejected the exact artifact: {0}")]
    Store(#[from] joshi_store::StoreError),
}

/// Builds the exact private capability required by `commit_source_fact_artifact_v1`.
///
/// The caller still owns the store transaction and operational commit context. This function
/// neither opens a store nor commits a row.
///
/// # Errors
///
/// Refuses an invalid/empty snapshot, a public classification over private evidence, JSON
/// serialization failure, digest boundary failure, or store capability validation failure.
pub fn snapshot_store_capability(
    snapshot: &MarketStateSnapshotV1,
    protection: ArtifactProtectionClass,
) -> Result<SourceFactArtifactCapability, StoreArtifactError> {
    if snapshot.contract.as_str() != MARKET_STATE_SNAPSHOT_CONTRACT
        || snapshot.authority.as_str() != READ_ONLY_AUTHORITY
    {
        return Err(StoreArtifactError::InvalidSnapshot);
    }
    let Some(maximum_input_available_at) = snapshot
        .input_closure
        .iter()
        .map(|input| input.available_at)
        .max()
    else {
        return Err(StoreArtifactError::EmptyInputClosure);
    };
    if snapshot.input_closure.iter().any(|input| {
        input.available_commit > snapshot.cut.known_by_commit
            || input.available_at > snapshot.cut.known_by
    }) {
        return Err(StoreArtifactError::InvalidSnapshot);
    }
    let contains_private = snapshot
        .input_closure
        .iter()
        .any(|input| input.evidence.protection != FactProtection::PublicIntegrity);
    if contains_private && protection == ArtifactProtectionClass::PublicIntegrity {
        return Err(StoreArtifactError::ProtectionMismatch);
    }
    let bytes = serde_json::to_vec(snapshot)?;
    let input_closure_bytes = serde_json::to_vec(&snapshot.input_closure)?;
    SourceFactArtifactCapability::new(
        snapshot.artifact_id.clone(),
        SourceFactFamily::MarketState,
        static_stable(MARKET_STATE_SNAPSHOT_CONTRACT),
        1,
        digest(&bytes),
        bytes,
        digest(&input_closure_bytes),
        snapshot.cut.known_by_commit,
        maximum_input_available_at,
        protection,
    )
    .map_err(StoreArtifactError::from)
}

fn digest(bytes: &[u8]) -> ValueDigest {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .unwrap_or_else(|_| unreachable!("SHA-256 wire digest is valid"))
}

fn static_stable(value: &'static str) -> StableString {
    StableString::new(value).unwrap_or_else(|_| unreachable!("static stable string is valid"))
}
