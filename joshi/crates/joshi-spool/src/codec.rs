use crate::{
    ByteClosure, DiskSegment, EntryDescriptor, ProtectionMetadata, ProtectionRequest, Result,
    SPOOL_CONTRACT_VERSION, SegmentClosure, SegmentHeader, SegmentId, SegmentProtector, SpoolEntry,
    SpoolError, model,
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use joshi_domain::UtcTimestamp;
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct HeaderAad<'a> {
    contract: &'a str,
    segment_id: &'a SegmentId,
    created_at: UtcTimestamp,
    domain: &'a crate::ProtectionDomainId,
    protection: &'a ProtectionMetadata,
    entries: &'a [EntryDescriptor],
    source_occurrences: &'a [crate::SourceOccurrence],
    body: &'a ByteClosure,
}

struct EncodedBody {
    bytes: Vec<u8>,
    descriptors: Vec<EntryDescriptor>,
    source_occurrences: Vec<crate::SourceOccurrence>,
}

/// Builds deterministic length-framed entry bytes and seals them according to one protection
/// domain. Bounds are enforced again when the segment is admitted to a local spool.
///
/// # Errors
///
/// Returns an error for malformed entries, cross-domain control records, unavailable keys, nonce
/// reuse, authentication failure, overflow, or serialization failure.
pub fn encode_segment(
    segment_id: SegmentId,
    created_at: UtcTimestamp,
    entries: &[SpoolEntry],
    protection: &ProtectionRequest,
    protector: Option<&SegmentProtector>,
) -> Result<(Vec<u8>, SegmentClosure)> {
    if entries.is_empty() {
        return Err(SpoolError::Invalid(
            "a segment must contain an entry".into(),
        ));
    }

    let encoded = encode_entries(entries, protection.domain())?;
    let domain = protection.domain().clone();
    let protection_metadata = metadata(protection);
    let body_closure = ByteClosure::of(&encoded.bytes);
    let aad = serde_json::to_vec(&HeaderAad {
        contract: SPOOL_CONTRACT_VERSION,
        segment_id: &segment_id,
        created_at,
        domain: &domain,
        protection: &protection_metadata,
        entries: &encoded.descriptors,
        source_occurrences: &encoded.source_occurrences,
        body: &body_closure,
    })?;
    let sealed_body_bytes = protect_body(protection, protector, &aad, &encoded.bytes)?;
    let sealed_body = ByteClosure::of(&sealed_body_bytes);
    let protection_class = protection_metadata.class();
    let envelope = DiskSegment {
        header: SegmentHeader {
            contract: model::contract_header(),
            segment_id: segment_id.clone(),
            created_at,
            domain: domain.clone(),
            protection: protection_metadata,
            entries: encoded.descriptors,
            source_occurrences: encoded.source_occurrences,
            body: body_closure,
            sealed_body,
        },
        sealed_body_bytes,
    };
    let bytes = serde_json::to_vec(&envelope)?;
    let closure = SegmentClosure {
        segment_id,
        domain,
        protection_class,
        exact_segment: ByteClosure::of(&bytes),
    };
    Ok((bytes, closure))
}

fn encode_entries(
    entries: &[SpoolEntry],
    domain: &crate::ProtectionDomainId,
) -> Result<EncodedBody> {
    let mut body = Vec::new();
    let mut descriptors = Vec::with_capacity(entries.len());
    for (ordinal, entry) in entries.iter().enumerate() {
        match entry {
            SpoolEntry::EvidenceBatch(batch) => model::validate_batch_entry(batch)?,
            SpoolEntry::Retention(record) if &record.domain != domain => {
                return Err(SpoolError::Invalid(
                    "retention record domain differs from physical segment domain".into(),
                ));
            }
            SpoolEntry::Deletion(record) if &record.domain != domain => {
                return Err(SpoolError::Invalid(
                    "deletion record domain differs from physical segment domain".into(),
                ));
            }
            _ => {}
        }
        let bytes = serde_json::to_vec(entry)?;
        let length = u64::try_from(bytes.len())
            .map_err(|_| SpoolError::BoundExceeded("entry byte length".into()))?;
        body.extend_from_slice(&length.to_be_bytes());
        body.extend_from_slice(&bytes);
        descriptors.push(EntryDescriptor {
            ordinal: u64::try_from(ordinal)
                .map_err(|_| SpoolError::BoundExceeded("entry ordinal".into()))?,
            kind: entry.kind().into(),
            occurrence_id: entry.occurrence_id(),
            exact_entry: ByteClosure::of(&bytes),
            batch: match entry {
                SpoolEntry::EvidenceBatch(value) => Some(value.closure.clone()),
                _ => None,
            },
        });
    }
    Ok(EncodedBody {
        bytes: body,
        descriptors,
        source_occurrences: model::source_occurrences(entries),
    })
}

fn metadata(protection: &ProtectionRequest) -> ProtectionMetadata {
    match protection {
        ProtectionRequest::Public { .. } => ProtectionMetadata::PublicIntegrity,
        ProtectionRequest::AuthenticatedPrivate { key_id, nonce, .. } => {
            ProtectionMetadata::AuthenticatedPrivate {
                algorithm: "chacha20_poly1305.v1".into(),
                key_id: key_id.clone(),
                nonce_base64: STANDARD.encode(nonce),
            }
        }
    }
}

fn protect_body(
    protection: &ProtectionRequest,
    protector: Option<&SegmentProtector>,
    aad: &[u8],
    body: &[u8],
) -> Result<Vec<u8>> {
    match protection {
        ProtectionRequest::Public { .. } => Ok(body.to_vec()),
        ProtectionRequest::AuthenticatedPrivate {
            domain,
            key_id,
            nonce,
        } => {
            let protector = protector.ok_or_else(|| SpoolError::MissingKey {
                key_id: key_id.clone(),
                domain: domain.clone(),
            })?;
            if protector.key_id() != key_id {
                return Err(SpoolError::MissingKey {
                    key_id: key_id.clone(),
                    domain: domain.clone(),
                });
            }
            protector.seal(domain, *nonce, aad, body)
        }
    }
}

/// Parses and verifies the public/ciphertext envelope without requiring decryption keys.
///
/// # Errors
///
/// Returns an error when JSON, contract, ciphertext closure, entry order, or occurrence ordering
/// is invalid.
pub fn inspect_segment(bytes: &[u8]) -> Result<DiskSegment> {
    let segment: DiskSegment = serde_json::from_slice(bytes)?;
    if segment.header.contract != SPOOL_CONTRACT_VERSION {
        return Err(SpoolError::Invalid(format!(
            "unsupported segment contract {}",
            segment.header.contract
        )));
    }
    segment
        .header
        .sealed_body
        .verify(&segment.sealed_body_bytes)?;
    if segment.header.entries.is_empty()
        || segment
            .header
            .entries
            .iter()
            .enumerate()
            .any(|(ordinal, entry)| entry.ordinal != u64::try_from(ordinal).unwrap_or(u64::MAX))
    {
        return Err(SpoolError::Integrity(
            "entry descriptors are empty, unordered, or non-contiguous".into(),
        ));
    }
    if segment
        .header
        .source_occurrences
        .windows(2)
        .any(|pair| pair[0] >= pair[1])
    {
        return Err(SpoolError::Integrity(
            "source occurrence closure is not strictly ordered".into(),
        ));
    }
    Ok(segment)
}

/// Verifies and opens a segment, then checks every framed entry against the ordered header closure.
///
/// # Errors
///
/// Returns an error for any envelope, AEAD, body, frame, entry, batch, domain, or occurrence
/// closure mismatch, including a missing private key.
pub fn decode_segment(
    bytes: &[u8],
    protector: Option<&SegmentProtector>,
) -> Result<Vec<SpoolEntry>> {
    let segment = inspect_segment(bytes)?;
    let aad = serde_json::to_vec(&HeaderAad {
        contract: &segment.header.contract,
        segment_id: &segment.header.segment_id,
        created_at: segment.header.created_at,
        domain: &segment.header.domain,
        protection: &segment.header.protection,
        entries: &segment.header.entries,
        source_occurrences: &segment.header.source_occurrences,
        body: &segment.header.body,
    })?;
    let body = match &segment.header.protection {
        ProtectionMetadata::PublicIntegrity => segment.sealed_body_bytes,
        ProtectionMetadata::AuthenticatedPrivate {
            algorithm,
            key_id,
            nonce_base64,
        } => {
            if algorithm != "chacha20_poly1305.v1" {
                return Err(SpoolError::Invalid(format!(
                    "unsupported protection algorithm {algorithm}"
                )));
            }
            let nonce = decode_nonce(nonce_base64)?;
            let protector = protector.ok_or_else(|| SpoolError::MissingKey {
                key_id: key_id.clone(),
                domain: segment.header.domain.clone(),
            })?;
            protector.open(
                &segment.header.domain,
                key_id,
                nonce,
                &aad,
                &segment.sealed_body_bytes,
            )?
        }
    };
    segment.header.body.verify(&body)?;
    let entries = decode_entries(&body, &segment.header.entries)?;
    if model::source_occurrences(&entries) != segment.header.source_occurrences {
        return Err(SpoolError::Integrity(
            "source occurrence closure differs from exact entries".into(),
        ));
    }
    for entry in &entries {
        match entry {
            SpoolEntry::Retention(record) if record.domain != segment.header.domain => {
                return Err(SpoolError::Integrity(
                    "retention record crosses protection domains".into(),
                ));
            }
            SpoolEntry::Deletion(record) if record.domain != segment.header.domain => {
                return Err(SpoolError::Integrity(
                    "deletion record crosses protection domains".into(),
                ));
            }
            _ => {}
        }
    }
    Ok(entries)
}

pub(crate) fn exact_closure(bytes: &[u8]) -> Result<SegmentClosure> {
    let segment = inspect_segment(bytes)?;
    Ok(SegmentClosure {
        segment_id: segment.header.segment_id,
        domain: segment.header.domain,
        protection_class: segment.header.protection.class(),
        exact_segment: ByteClosure::of(bytes),
    })
}

pub(crate) fn verify_exact(bytes: &[u8], expected: &SegmentClosure) -> Result<DiskSegment> {
    expected.exact_segment.verify(bytes)?;
    let segment = inspect_segment(bytes)?;
    if segment.header.segment_id != expected.segment_id
        || segment.header.domain != expected.domain
        || segment.header.protection.class() != expected.protection_class
    {
        return Err(SpoolError::Integrity(
            "segment envelope does not match transfer closure".into(),
        ));
    }
    Ok(segment)
}

fn decode_entries(body: &[u8], descriptors: &[EntryDescriptor]) -> Result<Vec<SpoolEntry>> {
    let mut cursor = 0_usize;
    let mut entries = Vec::with_capacity(descriptors.len());
    for descriptor in descriptors {
        let length_bytes: [u8; 8] = body
            .get(cursor..cursor.saturating_add(8))
            .ok_or_else(|| SpoolError::Integrity("truncated entry frame length".into()))?
            .try_into()
            .map_err(|_| SpoolError::Integrity("invalid frame length".into()))?;
        cursor = cursor.saturating_add(8);
        let length = usize::try_from(u64::from_be_bytes(length_bytes))
            .map_err(|_| SpoolError::BoundExceeded("entry frame length".into()))?;
        let end = cursor
            .checked_add(length)
            .ok_or_else(|| SpoolError::BoundExceeded("entry frame end".into()))?;
        let exact = body
            .get(cursor..end)
            .ok_or_else(|| SpoolError::Integrity("truncated entry frame".into()))?;
        descriptor.exact_entry.verify(exact)?;
        let entry: SpoolEntry = serde_json::from_slice(exact)?;
        if entry.kind() != descriptor.kind || entry.occurrence_id() != descriptor.occurrence_id {
            return Err(SpoolError::Integrity(
                "entry descriptor does not match exact framed entry".into(),
            ));
        }
        if let SpoolEntry::EvidenceBatch(batch) = &entry {
            batch.closure.exact_batch.verify(&batch.exact_batch_bytes)?;
            batch
                .closure
                .exact_policy
                .verify(&batch.exact_policy_bytes)?;
            if descriptor.batch.as_ref() != Some(&batch.closure) {
                return Err(SpoolError::Integrity(
                    "batch closure differs between body and header".into(),
                ));
            }
            model::validate_batch_entry(batch)?;
        }
        entries.push(entry);
        cursor = end;
    }
    if cursor != body.len() {
        return Err(SpoolError::Integrity(
            "unframed bytes remain after final entry".into(),
        ));
    }
    Ok(entries)
}

fn decode_nonce(encoded: &str) -> Result<[u8; 12]> {
    STANDARD
        .decode(encoded)
        .map_err(|_| SpoolError::Invalid("nonce is not valid base64".into()))?
        .try_into()
        .map_err(|_| SpoolError::Invalid("nonce must be exactly 96 bits".into()))
}
