use std::{fmt, str::FromStr};

use joshi_domain::{StableString, UtcTimestamp};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};
use sha2::{Digest as _, Sha256};
use zeroize::Zeroizing;

use crate::{
    PAIRING_OCCURRENCE_CONTRACT, PAIRING_SCHEMA_VERSION, PAIRING_SESSION_CONTRACT, PairingError,
};

pub const PAIRING_CODE_ALPHABET: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";
pub const PAIRING_CODE_BYTES: usize = 20;
pub const PAIRING_CODE_TEXT_LENGTH: usize = 45;
pub const PAIRING_CAPABILITY_BYTES: usize = 32;
pub const PAIRING_CAPABILITY_PREFIX: &str = "jpc1_";

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

/// Ordinary read/evidence scopes. Transaction, signing, wallet and execution scopes do not exist.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PairingScope {
    CockpitRead,
    OperatorEvidenceWrite,
    PresentationEvidenceWrite,
    ReplayRead,
}

/// A durable restart epoch with an exact decimal-string wire representation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PairingEpoch(u64);

impl PairingEpoch {
    pub fn new(value: u64) -> Result<Self, PairingError> {
        if value == 0 {
            return Err(PairingError::InvalidEpoch);
        }
        Ok(Self(value))
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

impl Serialize for PairingEpoch {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for PairingEpoch {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        if value.is_empty()
            || value == "0"
            || value.starts_with('0')
            || !value.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(de::Error::custom(
                "pairing epoch must be a canonical positive decimal string",
            ));
        }
        value
            .parse::<u64>()
            .map_err(de::Error::custom)
            .and_then(|value| Self::new(value).map_err(de::Error::custom))
    }
}

/// A process-relative monotonic tick. Its string wire form cannot be confused with UTC display time.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct MonotonicMillis(u64);

impl MonotonicMillis {
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }

    pub fn checked_add(self, delta: u64) -> Result<Self, PairingError> {
        self.0
            .checked_add(delta)
            .map(Self)
            .ok_or(PairingError::InvalidConfig)
    }
}

impl Serialize for MonotonicMillis {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for MonotonicMillis {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        if value.is_empty()
            || value.len() > 1 && value.starts_with('0')
            || !value.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(de::Error::custom(
                "monotonic milliseconds must be a canonical decimal string",
            ));
        }
        value.parse::<u64>().map(Self).map_err(de::Error::custom)
    }
}

/// A separately typed wall instant for display/audit and conservative durable rate restart.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct PairingWallInstant(UtcTimestamp);

impl PairingWallInstant {
    #[must_use]
    pub const fn new(value: UtcTimestamp) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> UtcTimestamp {
        self.0
    }

    pub fn checked_add_ms(self, milliseconds: u64) -> Result<Self, PairingError> {
        let milliseconds = i64::try_from(milliseconds).map_err(|_| PairingError::InvalidConfig)?;
        let value = self
            .0
            .as_datetime()
            .checked_add(time::Duration::milliseconds(milliseconds))
            .ok_or(PairingError::InvalidWallClock)?;
        UtcTimestamp::new(value)
            .map(Self)
            .map_err(|_| PairingError::InvalidWallClock)
    }

    /// Whole milliseconds until a later wall instant. Sub-millisecond residue expires early.
    pub fn milliseconds_until(self, later: Self) -> Result<u64, PairingError> {
        let delta = later.0.as_datetime() - self.0.as_datetime();
        if delta.is_negative() {
            return Err(PairingError::ClockRollback);
        }
        u64::try_from(delta.whole_milliseconds()).map_err(|_| PairingError::InvalidWallClock)
    }
}

impl FromStr for PairingWallInstant {
    type Err = PairingError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        value
            .parse::<UtcTimestamp>()
            .map(Self)
            .map_err(|_| PairingError::InvalidWallClock)
    }
}

/// One coherent clock sample. Only `monotonic_ms` controls expiry or authorization.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PairingClockSample {
    pub monotonic_ms: MonotonicMillis,
    pub observed_at: PairingWallInstant,
}

/// Bounded service policy. The validation maxima are protocol ceilings, not suggestions.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PairingConfig {
    pub code_ttl_ms: u64,
    pub session_ttl_ms: u64,
    pub max_active_codes: usize,
    pub max_live_sessions: usize,
    pub max_failed_attempts: u32,
    pub attempt_window_ms: u64,
    pub max_issued_per_window: u32,
    pub issue_window_ms: u64,
}

impl Default for PairingConfig {
    fn default() -> Self {
        Self {
            code_ttl_ms: 120_000,
            session_ttl_ms: 900_000,
            max_active_codes: 4,
            max_live_sessions: 8,
            max_failed_attempts: 5,
            attempt_window_ms: 60_000,
            max_issued_per_window: 4,
            issue_window_ms: 60_000,
        }
    }
}

impl PairingConfig {
    pub fn validate(self) -> Result<(), PairingError> {
        if !(30_000..=300_000).contains(&self.code_ttl_ms)
            || !(60_000..=3_600_000).contains(&self.session_ttl_ms)
            || !(1..=8).contains(&self.max_active_codes)
            || !(1..=16).contains(&self.max_live_sessions)
            || !(1..=8).contains(&self.max_failed_attempts)
            || !(10_000..=300_000).contains(&self.attempt_window_ms)
            || !(1..=8).contains(&self.max_issued_per_window)
            || !(10_000..=300_000).contains(&self.issue_window_ms)
        {
            return Err(PairingError::InvalidConfig);
        }
        Ok(())
    }
}

/// A canonical 160-bit one-time code grouped for human transfer. It never implements serde.
pub struct SecretCode(Zeroizing<Vec<u8>>);

impl SecretCode {
    pub(crate) fn from_bytes(bytes: Vec<u8>) -> Self {
        Self(Zeroizing::new(bytes))
    }

    pub fn parse(value: &str) -> Result<Self, PairingError> {
        if value.len() != PAIRING_CODE_TEXT_LENGTH || !value.starts_with("JOSHI-") {
            return Err(PairingError::MalformedSecret);
        }
        let groups: Vec<_> = value[6..].split('-').collect();
        if groups.len() != 8
            || groups.iter().any(|group| group.len() != 4)
            || groups
                .iter()
                .flat_map(|group| group.bytes())
                .any(|byte| !PAIRING_CODE_ALPHABET.contains(&byte))
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
        std::str::from_utf8(&self.0).expect("pairing code is canonical ASCII")
    }
}

impl fmt::Debug for SecretCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("[REDACTED_PAIRING_CODE]")
    }
}

/// A memory-only session capability in a namespace disjoint from one-time codes.
pub struct SecretCapability(Zeroizing<Vec<u8>>);

impl SecretCapability {
    pub(crate) fn from_bytes(bytes: Vec<u8>) -> Self {
        Self(Zeroizing::new(bytes))
    }

    pub fn parse(value: &str) -> Result<Self, PairingError> {
        let material = value
            .strip_prefix(PAIRING_CAPABILITY_PREFIX)
            .ok_or(PairingError::MalformedSecret)?;
        if material.len() != PAIRING_CAPABILITY_BYTES * 2
            || !material
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
        std::str::from_utf8(&self.0).expect("pairing capability is canonical ASCII")
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
    pub epoch: PairingEpoch,
    pub expires_at: PairingWallInstant,
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
    pub predecessor_occurrence_id: Option<StableString>,
    pub origin: PairingOrigin,
    pub epoch: PairingEpoch,
    pub at_monotonic_ms: MonotonicMillis,
    pub observed_at: PairingWallInstant,
    pub expires_at: Option<PairingWallInstant>,
    pub scopes: Vec<PairingScope>,
    pub rate_window_id: Option<StableString>,
    pub rate_window_expires_at: Option<PairingWallInstant>,
    pub failed_attempt_ordinal: Option<u32>,
    pub attempt_window_started_monotonic_ms: Option<MonotonicMillis>,
    pub reason: Option<StableString>,
    pub authority: StableString,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PairingOccurrenceKind {
    EpochStarted,
    Issued,
    AttemptRejected,
    Consumed,
    Revoked,
    Expired,
    RestartInvalidated,
}

#[derive(Debug)]
pub struct IssuedPairing {
    pub code: SecretCode,
    pub metadata: PairingOccurrence,
    pub prior_occurrences: Vec<PairingOccurrence>,
}

#[derive(Debug)]
pub struct ExchangedPairing {
    pub capability: SecretCapability,
    pub descriptor: PairingSessionDescriptor,
    pub occurrence: PairingOccurrence,
    pub prior_occurrences: Vec<PairingOccurrence>,
}

#[derive(Debug)]
pub struct RejectedPairingAttempt {
    pub error: PairingError,
    pub occurrence: PairingOccurrence,
    pub prior_occurrences: Vec<PairingOccurrence>,
}

#[derive(Debug)]
pub enum PairingConsumeOutcome {
    Exchanged(ExchangedPairing),
    Rejected(RejectedPairingAttempt),
}

impl PairingSessionDescriptor {
    pub fn validate(&self) -> Result<(), PairingError> {
        if PairingOrigin::new(self.origin.as_str())? != self.origin
            || self.contract.as_str() != PAIRING_SESSION_CONTRACT
            || self.schema_version != PAIRING_SCHEMA_VERSION
            || self.authority.as_str() != "read_only_no_execution"
            || self.epoch.get() == 0
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
        expires_at: PairingWallInstant,
        scopes: Vec<PairingScope>,
    ) -> Self {
        Self {
            contract: StableString::new(PAIRING_SESSION_CONTRACT).expect("static contract"),
            schema_version: PAIRING_SCHEMA_VERSION,
            session_id,
            origin,
            epoch: PairingEpoch::new(epoch).expect("validated nonzero epoch"),
            expires_at,
            scopes,
            authority: StableString::new("read_only_no_execution").expect("static authority"),
        }
    }
}

impl PairingOccurrence {
    pub fn validate(&self) -> Result<(), PairingError> {
        if PairingOrigin::new(self.origin.as_str())? != self.origin
            || self.contract.as_str() != PAIRING_OCCURRENCE_CONTRACT
            || self.schema_version != PAIRING_SCHEMA_VERSION
            || self.epoch.get() == 0
            || self.authority.as_str() != "read_only_pairing_exchange"
            || self.scopes.windows(2).any(|window| window[0] >= window[1])
        {
            return Err(PairingError::Identity);
        }
        let ordinary = self.failed_attempt_ordinal.is_none()
            && self.attempt_window_started_monotonic_ms.is_none();
        let no_rate_window = self.rate_window_id.is_none() && self.rate_window_expires_at.is_none();
        let epoch_occurrence_id = pairing_epoch_occurrence_id(&self.origin, self.epoch.get());
        let valid = match self.kind {
            PairingOccurrenceKind::EpochStarted => {
                self.occurrence_id == epoch_occurrence_id
                    && self.issue_id.is_none()
                    && self.session_id.is_none()
                    && self.predecessor_occurrence_id.is_none()
                    && self.expires_at.is_none()
                    && self.scopes.is_empty()
                    && self.reason.is_some()
                    && ordinary
                    && no_rate_window
            }
            PairingOccurrenceKind::Issued => {
                self.issue_id.is_some()
                    && self.session_id.is_none()
                    && self
                        .predecessor_occurrence_id
                        .as_ref()
                        .map(StableString::as_str)
                        == Some(epoch_occurrence_id.as_str())
                    && self
                        .expires_at
                        .is_some_and(|expiry| expiry > self.observed_at)
                    && !self.scopes.is_empty()
                    && self.rate_window_id.is_some()
                    && self
                        .rate_window_expires_at
                        .is_some_and(|expiry| expiry > self.observed_at)
                    && self.reason.is_none()
                    && ordinary
            }
            PairingOccurrenceKind::AttemptRejected => {
                self.issue_id.is_none()
                    && self.session_id.is_none()
                    && self
                        .predecessor_occurrence_id
                        .as_ref()
                        .map(StableString::as_str)
                        == Some(epoch_occurrence_id.as_str())
                    && self.expires_at.is_none()
                    && self.scopes.is_empty()
                    && self.rate_window_id.is_some()
                    && self
                        .rate_window_expires_at
                        .is_some_and(|expiry| expiry > self.observed_at)
                    && self
                        .failed_attempt_ordinal
                        .is_some_and(|ordinal| ordinal > 0)
                    && self.attempt_window_started_monotonic_ms.is_some()
                    && self.reason.is_some()
            }
            PairingOccurrenceKind::Consumed => {
                self.issue_id.is_some()
                    && self.session_id.is_some()
                    && self.predecessor_occurrence_id.is_some()
                    && self
                        .expires_at
                        .is_some_and(|expiry| expiry > self.observed_at)
                    && !self.scopes.is_empty()
                    && self.reason.is_none()
                    && ordinary
                    && no_rate_window
            }
            PairingOccurrenceKind::Revoked => {
                self.issue_id.is_none()
                    && self.session_id.is_some()
                    && self.predecessor_occurrence_id.is_some()
                    && self.expires_at.is_none()
                    && !self.scopes.is_empty()
                    && self.reason.is_some()
                    && ordinary
                    && no_rate_window
            }
            PairingOccurrenceKind::Expired | PairingOccurrenceKind::RestartInvalidated => {
                self.issue_id.is_none() != self.session_id.is_none()
                    && self.predecessor_occurrence_id.is_some()
                    && self.expires_at.is_none()
                    && !self.scopes.is_empty()
                    && self.reason.is_some()
                    && ordinary
                    && no_rate_window
            }
        };
        if !valid {
            return Err(PairingError::Identity);
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
    predecessor_occurrence_id: Option<StableString>,
    origin: PairingOrigin,
    epoch: u64,
    sample: PairingClockSample,
    expires_at: Option<PairingWallInstant>,
    scopes: Vec<PairingScope>,
    rate_window_id: Option<StableString>,
    rate_window_expires_at: Option<PairingWallInstant>,
    failed_attempt_ordinal: Option<u32>,
    attempt_window_started_monotonic_ms: Option<MonotonicMillis>,
    reason: Option<StableString>,
) -> PairingOccurrence {
    PairingOccurrence {
        contract: StableString::new(PAIRING_OCCURRENCE_CONTRACT).expect("static contract"),
        schema_version: PAIRING_SCHEMA_VERSION,
        occurrence_id: id,
        kind,
        issue_id,
        session_id,
        predecessor_occurrence_id,
        origin,
        epoch: PairingEpoch::new(epoch).expect("validated nonzero epoch"),
        at_monotonic_ms: sample.monotonic_ms,
        observed_at: sample.observed_at,
        expires_at,
        scopes,
        rate_window_id,
        rate_window_expires_at,
        failed_attempt_ordinal,
        attempt_window_started_monotonic_ms,
        reason,
        authority: StableString::new("read_only_pairing_exchange").expect("static authority"),
    }
}

pub(crate) fn identity(
    prefix: &str,
    origin: &PairingOrigin,
    epoch: u64,
    ordinal: u64,
) -> StableString {
    StableString::new(format!(
        "{prefix}-{}-{epoch}-{ordinal}",
        pairing_origin_tag(origin)
    ))
    .expect("bounded pairing identity")
}

/// Domain-separated lowercase SHA-256 of the exact UTF-8 origin for nonsecret identities.
#[must_use]
pub fn pairing_origin_tag(origin: &PairingOrigin) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"joshi.pairing.origin.v1\0");
    hasher.update(origin.as_str().as_bytes());
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        write!(out, "{byte:02x}").expect("writing to a string cannot fail");
    }
    out
}

/// Canonical globally unique epoch-root occurrence identity for one exact origin and epoch.
#[must_use]
pub fn pairing_epoch_occurrence_id(origin: &PairingOrigin, epoch: u64) -> StableString {
    StableString::new(format!("pair-epoch-{}-{epoch}", pairing_origin_tag(origin)))
        .expect("bounded pairing epoch identity")
}

/// Canonical runtime/restart occurrence identity for an origin, epoch, and nonzero ordinal.
#[must_use]
pub fn pairing_occurrence_id(origin: &PairingOrigin, epoch: u64, ordinal: u64) -> StableString {
    identity("pair-occurrence", origin, epoch, ordinal)
}
