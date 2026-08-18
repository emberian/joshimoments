use std::fmt;

use joshi_domain::StableString;
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

use crate::{
    PAIRING_OCCURRENCE_CONTRACT, PAIRING_SCHEMA_VERSION, PAIRING_SESSION_CONTRACT, PairingError,
};

/// A canonical exact origin; no route or host suffix matching is permitted.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct PairingOrigin(StableString);

impl PairingOrigin {
    pub fn new(value: impl Into<String>) -> Result<Self, PairingError> {
        let value = value.into();
        let valid_scheme = value.starts_with("http://") || value.starts_with("https://");
        let authority = value
            .split_once("://")
            .map(|(_, rest)| rest)
            .unwrap_or_default();
        if !valid_scheme || authority.contains(['/', '?', '#', '@', '\\']) {
            return Err(PairingError::InvalidOrigin);
        }
        if authority.is_empty()
            || authority.contains(':') && authority.ends_with(':')
            || authority.contains(' ')
        {
            return Err(PairingError::InvalidOrigin);
        }
        StableString::new(value)
            .map(Self)
            .map_err(|_| PairingError::InvalidOrigin)
    }
    #[must_use]
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

/// Ordinary read-only product scopes. Prospective launch scopes are intentionally absent.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PairingScope {
    CockpitRead,
    OperatorEvidenceWrite,
    PresentationEvidenceWrite,
    ReplayRead,
}

/// Bounded service policy; all attempts and expiries are caller-clocked integers.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PairingConfig {
    pub code_ttl_ms: u64,
    pub session_ttl_ms: u64,
    pub max_active_codes: usize,
    pub max_live_sessions: usize,
    pub max_failed_attempts: u32,
    pub attempt_window_ms: u64,
}

impl Default for PairingConfig {
    fn default() -> Self {
        Self {
            code_ttl_ms: 120_000,
            session_ttl_ms: 3_600_000,
            max_active_codes: 8,
            max_live_sessions: 8,
            max_failed_attempts: 12,
            attempt_window_ms: 60_000,
        }
    }
}

impl PairingConfig {
    pub fn validate(self) -> Result<(), PairingError> {
        if self.code_ttl_ms == 0
            || self.session_ttl_ms == 0
            || self.max_active_codes == 0
            || self.max_live_sessions == 0
            || self.max_failed_attempts == 0
            || self.attempt_window_ms == 0
        {
            return Err(PairingError::InvalidConfig);
        }
        Ok(())
    }
}

/// Memory-only secret code. It has no serde representation and its Debug output is redacted.
pub struct SecretCode(Zeroizing<Vec<u8>>);

impl SecretCode {
    pub(crate) fn from_bytes(bytes: Vec<u8>) -> Self {
        Self(Zeroizing::new(bytes))
    }
    pub fn from_hex(value: &str) -> Result<Self, PairingError> {
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err(PairingError::MalformedSecret);
        }
        Ok(Self::from_bytes(value.as_bytes().to_vec()))
    }
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
    #[must_use]
    pub fn as_str(&self) -> &str {
        std::str::from_utf8(&self.0).expect("pairing secret is ASCII hex")
    }
}

impl fmt::Debug for SecretCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("[REDACTED_PAIRING_CODE]")
    }
}

/// Memory-only session capability; never serialized or included in occurrence metadata.
pub struct SecretCapability(Zeroizing<Vec<u8>>);

impl SecretCapability {
    pub(crate) fn from_bytes(bytes: Vec<u8>) -> Self {
        Self(Zeroizing::new(bytes))
    }
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
    #[must_use]
    pub fn as_str(&self) -> &str {
        std::str::from_utf8(&self.0).expect("pairing capability is ASCII hex")
    }
}
impl fmt::Debug for SecretCapability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("[REDACTED_PAIRING_CAPABILITY]")
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PairingSessionDescriptor {
    pub contract: StableString,
    pub schema_version: u16,
    pub session_id: StableString,
    pub origin: PairingOrigin,
    pub epoch: u64,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub scopes: Vec<PairingScope>,
    pub authority: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PairingOccurrence {
    pub contract: StableString,
    pub schema_version: u16,
    pub occurrence_id: StableString,
    pub kind: PairingOccurrenceKind,
    pub issue_id: Option<StableString>,
    pub session_id: Option<StableString>,
    pub origin: PairingOrigin,
    pub epoch: u64,
    pub at_ms: u64,
    pub reason: Option<StableString>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PairingOccurrenceKind {
    Issued,
    Consumed,
    Revoked,
    Expired,
    RestartInvalidated,
}

#[derive(Debug)]
pub struct IssuedPairing {
    pub code: SecretCode,
    pub metadata: PairingOccurrence,
}

#[derive(Debug)]
pub struct ExchangedPairing {
    pub capability: SecretCapability,
    pub descriptor: PairingSessionDescriptor,
    pub occurrence: PairingOccurrence,
}

impl PairingSessionDescriptor {
    pub fn validate(&self) -> Result<(), PairingError> {
        if PairingOrigin::new(self.origin.as_str())? != self.origin {
            return Err(PairingError::InvalidOrigin);
        }
        if self.contract.as_str() != PAIRING_SESSION_CONTRACT
            || self.schema_version != PAIRING_SCHEMA_VERSION
            || self.authority.as_str() != "read_only_no_execution"
            || self.expires_at_ms <= self.issued_at_ms
            || self.scopes.is_empty()
            || self.scopes.windows(2).any(|window| window[0] >= window[1])
        {
            return Err(PairingError::InvalidSession);
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PairingError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(|_| PairingError::Identity)
    }

    pub(crate) fn new(
        session_id: StableString,
        origin: PairingOrigin,
        epoch: u64,
        issued_at_ms: u64,
        expires_at_ms: u64,
        scopes: Vec<PairingScope>,
    ) -> Self {
        Self {
            contract: StableString::new(PAIRING_SESSION_CONTRACT).expect("static contract"),
            schema_version: PAIRING_SCHEMA_VERSION,
            session_id,
            origin,
            epoch,
            issued_at_ms,
            expires_at_ms,
            scopes,
            authority: StableString::new("read_only_no_execution").expect("static authority"),
        }
    }
}

impl PairingOccurrence {
    pub fn validate(&self) -> Result<(), PairingError> {
        if PairingOrigin::new(self.origin.as_str())? != self.origin {
            return Err(PairingError::InvalidOrigin);
        }
        if self.contract.as_str() != PAIRING_OCCURRENCE_CONTRACT
            || self.schema_version != PAIRING_SCHEMA_VERSION
            || self.epoch == 0
        {
            return Err(PairingError::Identity);
        }
        match self.kind {
            PairingOccurrenceKind::Issued => {
                if self.issue_id.is_none() || self.session_id.is_some() {
                    return Err(PairingError::Identity);
                }
            }
            PairingOccurrenceKind::Consumed => {
                if self.issue_id.is_none() || self.session_id.is_none() {
                    return Err(PairingError::Identity);
                }
            }
            PairingOccurrenceKind::Revoked => {
                if self.session_id.is_none() || self.reason.is_none() {
                    return Err(PairingError::Identity);
                }
            }
            PairingOccurrenceKind::Expired | PairingOccurrenceKind::RestartInvalidated => {
                if self.issue_id.is_none() == self.session_id.is_none() {
                    return Err(PairingError::Identity);
                }
            }
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PairingError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(|_| PairingError::Identity)
    }
}

pub fn parse_pairing_session_descriptor(
    bytes: &[u8],
) -> Result<PairingSessionDescriptor, PairingError> {
    let value: PairingSessionDescriptor =
        serde_json::from_slice(bytes).map_err(|_| PairingError::Identity)?;
    if value.canonical_bytes()? != bytes {
        return Err(PairingError::Identity);
    }
    Ok(value)
}

pub fn parse_pairing_occurrence(bytes: &[u8]) -> Result<PairingOccurrence, PairingError> {
    let value: PairingOccurrence =
        serde_json::from_slice(bytes).map_err(|_| PairingError::Identity)?;
    if value.canonical_bytes()? != bytes {
        return Err(PairingError::Identity);
    }
    Ok(value)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn occurrence(
    id: StableString,
    kind: PairingOccurrenceKind,
    issue_id: Option<StableString>,
    session_id: Option<StableString>,
    origin: PairingOrigin,
    epoch: u64,
    at_ms: u64,
    reason: Option<StableString>,
) -> PairingOccurrence {
    PairingOccurrence {
        contract: StableString::new(PAIRING_OCCURRENCE_CONTRACT).expect("static contract"),
        schema_version: PAIRING_SCHEMA_VERSION,
        occurrence_id: id,
        kind,
        issue_id,
        session_id,
        origin,
        epoch,
        at_ms,
        reason,
    }
}

pub(crate) fn identity(prefix: &str, epoch: u64, ordinal: u64) -> StableString {
    StableString::new(format!("{prefix}-{epoch}-{ordinal}")).expect("bounded pairing identity")
}
