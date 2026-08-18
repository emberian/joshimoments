use crate::{BookError, Result};
use joshi_domain::ValueDigest;
use serde::{Serialize, de::DeserializeOwned};
use sha2::{Digest, Sha256};

/// An immutable value together with its canonical semantic bytes and exact digest.
#[derive(Clone, Debug)]
pub struct ValidatedArtifact<T> {
    value: T,
    exact_bytes: Vec<u8>,
    semantic_digest: ValueDigest,
}

impl<T> ValidatedArtifact<T> {
    pub(crate) fn new(value: T, exact_bytes: Vec<u8>) -> Result<Self> {
        let semantic_digest = digest_bytes(&exact_bytes)?;
        Ok(Self {
            value,
            exact_bytes,
            semantic_digest,
        })
    }

    /// Returns the validated typed value.
    #[must_use]
    pub const fn value(&self) -> &T {
        &self.value
    }

    /// Returns the exact canonical bytes, including the one trailing newline.
    #[must_use]
    pub fn exact_bytes(&self) -> &[u8] {
        &self.exact_bytes
    }

    /// Returns the digest of the exact canonical bytes.
    #[must_use]
    pub const fn semantic_digest(&self) -> &ValueDigest {
        &self.semantic_digest
    }
}

/// Serializes a typed contract to its one compact JSON representation plus a trailing newline.
///
/// # Errors
///
/// Returns an error when serialization fails.
pub fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

pub(crate) fn decode_canonical<T: DeserializeOwned + Serialize>(
    bytes: &[u8],
) -> Result<(T, Vec<u8>)> {
    let value: T = serde_json::from_slice(bytes)?;
    let canonical = canonical_bytes(&value)?;
    if bytes != canonical {
        return Err(BookError::NonCanonical);
    }
    Ok((value, canonical))
}

/// Computes an algorithm-qualified digest of exact bytes.
///
/// # Errors
///
/// Returns an error only if the shared digest wrapper unexpectedly rejects the qualified value.
pub fn digest_bytes(bytes: &[u8]) -> Result<ValueDigest> {
    let digest = Sha256::digest(bytes);
    let mut hex = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut hex, "{byte:02x}").expect("writing to String cannot fail");
    }
    Ok(ValueDigest::new(format!("sha256:{hex}"))?)
}
