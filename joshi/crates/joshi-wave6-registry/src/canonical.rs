//! Exact canonical byte and digest handling.

use joshi_domain::ValueDigest;
use serde::{Serialize, de::DeserializeOwned};
use sha2::{Digest, Sha256};

use crate::{RegistryError, Result, SemanticCeilingV1, Wave6ProgramRegistrationV1};

/// A validated fixture registration and its exact document bytes.
///
/// This object intentionally has no durable receipt, commit sequence, or promotion method.
#[derive(Clone, Debug)]
pub struct ValidatedProgramRegistration {
    value: Wave6ProgramRegistrationV1,
    exact_bytes: Vec<u8>,
    document_digest: ValueDigest,
}

impl ValidatedProgramRegistration {
    /// Returns the validated fixture registration.
    #[must_use]
    pub const fn value(&self) -> &Wave6ProgramRegistrationV1 {
        &self.value
    }

    /// Returns exact canonical bytes including one trailing newline.
    #[must_use]
    pub fn exact_bytes(&self) -> &[u8] {
        &self.exact_bytes
    }

    /// Returns the digest of the full canonical document bytes.
    #[must_use]
    pub const fn document_digest(&self) -> &ValueDigest {
        &self.document_digest
    }

    /// Public validation can never raise the fixture-only ceiling.
    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

/// Serializes a value to compact JSON with exactly one trailing newline.
///
/// # Errors
///
/// Returns an error when JSON serialization fails.
pub fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn decode_canonical<T: DeserializeOwned + Serialize>(bytes: &[u8]) -> Result<T> {
    let value = serde_json::from_slice(bytes)?;
    if canonical_bytes(&value)? != bytes {
        return Err(RegistryError::NonCanonical);
    }
    Ok(value)
}

/// Computes an algorithm-qualified SHA-256 digest over exact bytes.
///
/// # Errors
///
/// Returns an error only if the shared stable digest wrapper rejects the generated value.
pub fn digest_bytes(bytes: &[u8]) -> Result<ValueDigest> {
    let hex = format!("{:x}", Sha256::digest(bytes));
    ValueDigest::new(format!("sha256:{hex}"))
        .map_err(|error| RegistryError::Identity(error.to_string()))
}

/// Strictly parses and validates exact canonical registration bytes.
///
/// # Errors
///
/// Refuses unknown fields, noncanonical JSON, invalid collections/policy, or digest mismatch.
pub fn parse_program_registration_exact(bytes: &[u8]) -> Result<ValidatedProgramRegistration> {
    let value: Wave6ProgramRegistrationV1 = decode_canonical(bytes)?;
    value.validate()?;
    let document_digest = digest_bytes(bytes)?;
    Ok(ValidatedProgramRegistration {
        value,
        exact_bytes: bytes.to_vec(),
        document_digest,
    })
}
