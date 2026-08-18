use crate::{AUTHORITY_CEILING, REPLAY_CONTRACT_VERSION, Result};
use joshi_spool::{
    LocalSpool, ProtectionMetadata, SegmentClosure, SegmentProtector, SpoolEntry, inspect_segment,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeMap, sync::Arc};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplaySegment {
    pub closure: SegmentClosure,
    pub protection: String,
    pub evidence_batches: u64,
    pub control_entries: u64,
    pub plaintext_verified: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplayManifest {
    pub contract: String,
    pub segments: Vec<ReplaySegment>,
    pub ordered_closure_digest: String,
    pub exact_segment_bytes: u64,
    pub evidence_batches: u64,
    pub control_entries: u64,
    pub opaque_private_segments: u64,
    pub authority: String,
}

/// Verify a local spool without any provider, catalog, remote host, or listener. Private
/// ciphertext closure is still verified when a decryption key is intentionally unavailable.
///
/// # Errors
///
/// Refuses corrupt segment envelopes or plaintext/authentication failures when a key is supplied.
pub fn replay_spool(
    spool: &LocalSpool,
    protectors: &BTreeMap<String, Arc<SegmentProtector>>,
) -> Result<ReplayManifest> {
    let mut segments = Vec::new();
    let mut digest = Sha256::new();
    let mut exact_segment_bytes = 0_u64;
    let mut evidence_batches = 0_u64;
    let mut control_entries = 0_u64;
    let mut opaque_private_segments = 0_u64;
    for closure in spool.list_segments()? {
        let bytes = spool.read_segment(&closure)?;
        exact_segment_bytes = exact_segment_bytes
            .checked_add(closure.exact_segment.byte_len)
            .ok_or_else(|| {
                crate::SupervisorError::InvalidValue("replay byte sum overflow".into())
            })?;
        digest.update(closure.segment_id.as_str().as_bytes());
        digest.update(b"\0");
        digest.update(closure.exact_segment.digest.as_bytes());
        digest.update(b"\0");
        digest.update(closure.exact_segment.byte_len.to_be_bytes());
        let inspected = inspect_segment(&bytes)?;
        let protection = match &inspected.header.protection {
            ProtectionMetadata::PublicIntegrity => "public_integrity",
            ProtectionMetadata::AuthenticatedPrivate { .. } => "authenticated_private",
        }
        .to_owned();
        let protector = match &inspected.header.protection {
            ProtectionMetadata::PublicIntegrity => None,
            ProtectionMetadata::AuthenticatedPrivate { key_id, .. } => {
                protectors.get(key_id).map(AsRef::as_ref)
            }
        };
        let (segment_batches, segment_control, plaintext_verified) = if matches!(
            inspected.header.protection,
            ProtectionMetadata::PublicIntegrity
        ) || protector.is_some()
        {
            let entries = joshi_spool::decode_segment(&bytes, protector)?;
            let batches = u64::try_from(
                entries
                    .iter()
                    .filter(|entry| matches!(entry, SpoolEntry::EvidenceBatch(_)))
                    .count(),
            )
            .unwrap_or(u64::MAX);
            let controls = u64::try_from(entries.len())
                .unwrap_or(u64::MAX)
                .saturating_sub(batches);
            (batches, controls, true)
        } else {
            opaque_private_segments = opaque_private_segments.saturating_add(1);
            (0, 0, false)
        };
        evidence_batches = evidence_batches.saturating_add(segment_batches);
        control_entries = control_entries.saturating_add(segment_control);
        segments.push(ReplaySegment {
            closure,
            protection,
            evidence_batches: segment_batches,
            control_entries: segment_control,
            plaintext_verified,
        });
    }
    Ok(ReplayManifest {
        contract: REPLAY_CONTRACT_VERSION.into(),
        segments,
        ordered_closure_digest: format!("sha256:{:x}", digest.finalize()),
        exact_segment_bytes,
        evidence_batches,
        control_entries,
        opaque_private_segments,
        authority: AUTHORITY_CEILING.into(),
    })
}
