use crate::{ProtectionDomainId, Result, SpoolError};
use ring::aead::{self, Aad, LessSafeKey, Nonce, UnboundKey};
use std::{collections::BTreeSet, sync::Mutex};

/// Caller-owned 256-bit key material. The bytes are never serialized or included in `Debug`.
pub struct KeyMaterial {
    key_id: String,
    bytes: [u8; 32],
}

impl KeyMaterial {
    /// Creates key material under a non-secret stable identifier.
    ///
    /// # Errors
    ///
    /// Returns an error when the key identifier is empty, padded, or oversized.
    pub fn new(key_id: impl Into<String>, bytes: [u8; 32]) -> Result<Self> {
        let key_id = key_id.into();
        if key_id.is_empty() || key_id.len() > 255 || key_id.trim() != key_id {
            return Err(SpoolError::Invalid("invalid key identifier".into()));
        }
        Ok(Self { key_id, bytes })
    }
}

/// In-process AEAD provider. Persistent spool admission performs a second nonce-reuse check across
/// already durable segments, so restart does not weaken the uniqueness invariant.
pub struct SegmentProtector {
    key_id: String,
    key: LessSafeKey,
    used_nonces: Mutex<BTreeSet<(ProtectionDomainId, [u8; 12])>>,
}

impl SegmentProtector {
    /// Builds a ChaCha20-Poly1305 protector.
    ///
    /// # Errors
    ///
    /// Returns an error if the key material cannot initialize the AEAD implementation.
    pub fn new(material: KeyMaterial) -> Result<Self> {
        let key = UnboundKey::new(&aead::CHACHA20_POLY1305, &material.bytes)
            .map(LessSafeKey::new)
            .map_err(|_| SpoolError::Invalid("invalid AEAD key".into()))?;
        Ok(Self {
            key_id: material.key_id,
            key,
            used_nonces: Mutex::new(BTreeSet::new()),
        })
    }

    /// Returns the non-secret key identifier.
    #[must_use]
    pub fn key_id(&self) -> &str {
        &self.key_id
    }

    pub(crate) fn seal(
        &self,
        domain: &ProtectionDomainId,
        nonce_bytes: [u8; 12],
        aad: &[u8],
        plaintext: &[u8],
    ) -> Result<Vec<u8>> {
        {
            let mut used = self
                .used_nonces
                .lock()
                .map_err(|_| SpoolError::Invalid("nonce registry poisoned".into()))?;
            if !used.insert((domain.clone(), nonce_bytes)) {
                return Err(SpoolError::NonceReuse {
                    key_id: self.key_id.clone(),
                    domain: domain.clone(),
                });
            }
        }
        let mut output = plaintext.to_vec();
        self.key
            .seal_in_place_append_tag(
                Nonce::assume_unique_for_key(nonce_bytes),
                Aad::from(aad),
                &mut output,
            )
            .map_err(|_| SpoolError::Authentication)?;
        Ok(output)
    }

    pub(crate) fn open(
        &self,
        domain: &ProtectionDomainId,
        key_id: &str,
        nonce_bytes: [u8; 12],
        aad: &[u8],
        ciphertext: &[u8],
    ) -> Result<Vec<u8>> {
        if key_id != self.key_id {
            return Err(SpoolError::MissingKey {
                key_id: key_id.into(),
                domain: domain.clone(),
            });
        }
        let mut output = ciphertext.to_vec();
        let plaintext = self
            .key
            .open_in_place(
                Nonce::assume_unique_for_key(nonce_bytes),
                Aad::from(aad),
                &mut output,
            )
            .map_err(|_| SpoolError::Authentication)?;
        let length = plaintext.len();
        output.truncate(length);
        Ok(output)
    }
}
