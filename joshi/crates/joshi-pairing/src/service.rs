use std::collections::BTreeMap;

use crate::{
    ExchangedPairing, IssuedPairing, PairingConfig, PairingError, PairingOccurrence,
    PairingOccurrenceKind, PairingOrigin, PairingScope, PairingSessionDescriptor, SecretCapability,
    SecretCode, identity, occurrence,
};

/// Entropy is injected so production can use an OS source while fixtures remain deterministic.
///
/// Production route/store owners must supply an OS-backed implementation. This pure crate never
/// opens an entropy device itself, so a deterministic implementation cannot accidentally become
/// the production default.
pub trait Entropy {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError>;
}

/// A caller-supplied monotonic millisecond clock. The service never reads wall-clock time.
pub trait MonotonicClock {
    fn now_ms(&mut self) -> Result<u64, PairingError>;
}

/// Deterministic test clock; production callers must provide a monotonic process clock.
#[cfg(test)]
#[derive(Clone, Copy, Debug)]
pub struct TestClock {
    now: u64,
}

#[cfg(test)]
impl TestClock {
    #[must_use]
    pub const fn new(now: u64) -> Self {
        Self { now }
    }
    pub fn advance(&mut self, delta_ms: u64) -> Result<(), PairingError> {
        self.now = self
            .now
            .checked_add(delta_ms)
            .ok_or(PairingError::InvalidConfig)?;
        Ok(())
    }
}

#[cfg(test)]
impl MonotonicClock for TestClock {
    fn now_ms(&mut self) -> Result<u64, PairingError> {
        Ok(self.now)
    }
}

/// Narrow adapter waist for a caller-owned route/store boundary. Implementations return only
/// non-secret session metadata; this crate supplies the in-memory implementation below.
pub trait PairingSessionPort {
    fn issue_code(
        &mut self,
        clock: &mut dyn MonotonicClock,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError>;
    fn consume_code(
        &mut self,
        code: &SecretCode,
        origin: &PairingOrigin,
        clock: &mut dyn MonotonicClock,
    ) -> Result<ExchangedPairing, PairingError>;
    fn authorize_capability(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        clock: &mut dyn MonotonicClock,
    ) -> Result<PairingSessionDescriptor, PairingError>;
    fn revoke_session(
        &mut self,
        session_id: &str,
        clock: &mut dyn MonotonicClock,
        reason: &str,
    ) -> Result<PairingOccurrence, PairingError>;
}

/// A deterministic test-only entropy source. It is deliberately absent from non-test builds.
#[cfg(test)]
#[derive(Clone, Debug)]
pub struct TestEntropy {
    state: u64,
}

#[cfg(test)]
impl TestEntropy {
    #[must_use]
    pub const fn new(seed: u8) -> Self {
        Self {
            state: (seed as u64) | 1,
        }
    }
}

#[cfg(test)]
impl Entropy for TestEntropy {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError> {
        for byte in bytes {
            // xorshift64* is deterministic test data, not a production entropy source. Its
            // non-zero state cycle avoids the old u8 wrap/repeated-secret failure.
            self.state ^= self.state >> 12;
            self.state ^= self.state << 25;
            self.state ^= self.state >> 27;
            *byte = self.state.to_le_bytes()[0];
        }
        Ok(())
    }
}

struct CodeRecord {
    issue_id: joshi_domain::StableString,
    code: SecretCode,
    expires_at_ms: u64,
    scopes: Vec<PairingScope>,
}

struct SessionRecord {
    descriptor: PairingSessionDescriptor,
    capability: SecretCapability,
}

/// Service-owned in-memory registry. It is deliberately not serializable or restart-persistent.
pub struct PairingRegistry<E: Entropy> {
    origin: PairingOrigin,
    epoch: u64,
    config: PairingConfig,
    entropy: E,
    next_ordinal: u64,
    codes: BTreeMap<String, CodeRecord>,
    sessions: BTreeMap<String, SessionRecord>,
    failed_attempts: u32,
    failed_window_started_ms: u64,
    last_now_ms: Option<u64>,
}

impl<E: Entropy> PairingRegistry<E> {
    pub fn issue_now<C: MonotonicClock>(
        &mut self,
        clock: &mut C,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError> {
        self.issue(clock.now_ms()?, scopes)
    }

    /// Expire live records using the only public time boundary: a monotonic clock adapter.
    pub fn expire_now<C: MonotonicClock>(
        &mut self,
        clock: &mut C,
    ) -> Result<Vec<PairingOccurrence>, PairingError> {
        self.expire(clock.now_ms()?)
    }

    /// Advance a service epoch through a monotonic clock adapter; raw transition time remains
    /// crate-private so route callers cannot manufacture a backward wall-clock transition.
    pub fn restart_now<C: MonotonicClock>(
        &mut self,
        new_epoch: u64,
        clock: &mut C,
    ) -> Result<Vec<PairingOccurrence>, PairingError> {
        self.restart(new_epoch, clock.now_ms()?)
    }

    pub fn new(
        origin: PairingOrigin,
        epoch: u64,
        config: PairingConfig,
        entropy: E,
    ) -> Result<Self, PairingError> {
        config.validate()?;
        if epoch == 0 {
            return Err(PairingError::InvalidEpoch);
        }
        Ok(Self {
            origin,
            epoch,
            config,
            entropy,
            next_ordinal: 0,
            codes: BTreeMap::new(),
            sessions: BTreeMap::new(),
            failed_attempts: 0,
            failed_window_started_ms: 0,
            last_now_ms: None,
        })
    }

    #[must_use]
    pub fn epoch(&self) -> u64 {
        self.epoch
    }

    /// Issue one code. Only non-secret occurrence metadata leaves the service boundary.
    pub(crate) fn issue(
        &mut self,
        now_ms: u64,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError> {
        self.observe_now(now_ms)?;
        if self.codes.len() >= self.config.max_active_codes {
            return Err(PairingError::RateLimited);
        }
        if scopes.is_empty() {
            return Err(PairingError::InvalidConfig);
        }
        let mut scopes = scopes;
        scopes.sort();
        scopes.dedup();
        self.next_ordinal = self
            .next_ordinal
            .checked_add(1)
            .ok_or(PairingError::Identity)?;
        let issue_id = identity("pair-issue", self.epoch, self.next_ordinal);
        let mut bytes = vec![0_u8; 32];
        self.entropy.fill(&mut bytes)?;
        let code_bytes = domain_separated_hex(&mut bytes, b'c');
        let code = SecretCode::from_bytes(code_bytes.clone());
        if self
            .codes
            .values()
            .any(|record| constant_time_equal(record.code.as_bytes(), code.as_bytes()))
        {
            bytes.fill(0);
            return Err(PairingError::DuplicateSecret);
        }
        bytes.fill(0);
        let expires = now_ms
            .checked_add(self.config.code_ttl_ms)
            .ok_or(PairingError::InvalidConfig)?;
        let occurrence = occurrence(
            identity("pair-occurrence", self.epoch, self.next_ordinal),
            PairingOccurrenceKind::Issued,
            Some(issue_id.clone()),
            None,
            self.origin.clone(),
            self.epoch,
            now_ms,
            None,
        );
        occurrence.validate()?;
        self.codes.insert(
            issue_id.as_str().to_owned(),
            CodeRecord {
                issue_id,
                code: SecretCode::from_bytes(code_bytes),
                expires_at_ms: expires,
                scopes,
            },
        );
        Ok(IssuedPairing {
            code,
            metadata: occurrence,
        })
    }

    /// Consume a code exactly once after exact-origin and epoch/expiry checks.
    pub(crate) fn consume(
        &mut self,
        code: &SecretCode,
        origin: &PairingOrigin,
        now_ms: u64,
    ) -> Result<ExchangedPairing, PairingError> {
        self.expire(now_ms)?;
        self.check_origin(origin)?;
        self.check_attempt_window(now_ms);
        if self.failed_attempts >= self.config.max_failed_attempts {
            return Err(PairingError::RateLimited);
        }
        let mut found: Option<String> = None;
        for (id, record) in &self.codes {
            if constant_time_equal(record.code.as_bytes(), code.as_bytes()) {
                found = Some(id.clone());
            }
        }
        let Some(issue_key) = found else {
            self.failed_attempts = self.failed_attempts.saturating_add(1);
            return if self.failed_attempts >= self.config.max_failed_attempts {
                Err(PairingError::RateLimited)
            } else {
                Err(PairingError::InvalidCode)
            };
        };
        if self.sessions.len() >= self.config.max_live_sessions {
            return Err(PairingError::RateLimited);
        }
        let record = self
            .codes
            .remove(&issue_key)
            .ok_or(PairingError::InvalidCode)?;
        self.next_ordinal = self
            .next_ordinal
            .checked_add(1)
            .ok_or(PairingError::Identity)?;
        let session_id = identity("pair-session", self.epoch, self.next_ordinal);
        let expires = now_ms
            .checked_add(self.config.session_ttl_ms)
            .ok_or(PairingError::InvalidConfig)?;
        let descriptor = PairingSessionDescriptor::new(
            session_id.clone(),
            self.origin.clone(),
            self.epoch,
            now_ms,
            expires,
            record.scopes.clone(),
        );
        descriptor.validate()?;
        let mut bytes = vec![0_u8; 32];
        self.entropy.fill(&mut bytes)?;
        let capability_bytes = domain_separated_hex(&mut bytes, b'p');
        bytes.fill(0);
        let capability = SecretCapability::from_bytes(capability_bytes);
        if self.sessions.values().any(|session| {
            constant_time_equal(session.capability.as_bytes(), capability.as_bytes())
        }) || self
            .codes
            .values()
            .any(|pending| constant_time_equal(pending.code.as_bytes(), capability.as_bytes()))
        {
            self.codes.insert(issue_key, record);
            return Err(PairingError::DuplicateSecret);
        }
        self.sessions.insert(
            session_id.as_str().to_owned(),
            SessionRecord {
                descriptor: descriptor.clone(),
                capability: SecretCapability::from_bytes(capability.as_bytes().to_vec()),
            },
        );
        let occurrence = occurrence(
            identity("pair-occurrence", self.epoch, self.next_ordinal),
            PairingOccurrenceKind::Consumed,
            Some(record.issue_id),
            Some(session_id),
            self.origin.clone(),
            self.epoch,
            now_ms,
            None,
        );
        occurrence.validate()?;
        Ok(ExchangedPairing {
            capability,
            descriptor,
            occurrence,
        })
    }

    /// Authorize an in-memory capability against exact origin, epoch, expiry and scope.
    pub(crate) fn authorize(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        now_ms: u64,
    ) -> Result<PairingSessionDescriptor, PairingError> {
        self.expire(now_ms)?;
        self.check_origin(origin)?;
        for record in self.sessions.values() {
            if constant_time_equal(record.capability.as_bytes(), capability.as_bytes()) {
                if !record.descriptor.scopes.contains(&scope) {
                    return Err(PairingError::ScopeDenied);
                }
                return Ok(record.descriptor.clone());
            }
        }
        Err(PairingError::InvalidSession)
    }

    pub(crate) fn revoke(
        &mut self,
        session_id: &str,
        now_ms: u64,
        reason: &str,
    ) -> Result<PairingOccurrence, PairingError> {
        self.observe_now(now_ms)?;
        let record = self
            .sessions
            .remove(session_id)
            .ok_or(PairingError::InvalidSession)?;
        let occurrence_id = self.next_occurrence_id()?;
        let value = occurrence(
            occurrence_id,
            PairingOccurrenceKind::Revoked,
            None,
            Some(record.descriptor.session_id),
            self.origin.clone(),
            self.epoch,
            now_ms,
            Some(joshi_domain::StableString::new(reason).map_err(|_| PairingError::Identity)?),
        );
        value.validate()?;
        Ok(value)
    }

    /// Expire codes/sessions and return only non-secret metadata.
    pub(crate) fn expire(&mut self, now_ms: u64) -> Result<Vec<PairingOccurrence>, PairingError> {
        self.observe_now(now_ms)?;
        let mut out = Vec::new();
        let expired_codes: Vec<_> = self
            .codes
            .iter()
            .filter(|(_, record)| record.expires_at_ms <= now_ms)
            .map(|(id, _)| id.clone())
            .collect();
        for id in expired_codes {
            if let Some(record) = self.codes.remove(&id) {
                let occurrence_id = self
                    .next_occurrence_id()
                ?;
                out.push(occurrence(
                    occurrence_id,
                    PairingOccurrenceKind::Expired,
                    Some(record.issue_id),
                    None,
                    self.origin.clone(),
                    self.epoch,
                    now_ms,
                    None,
                ));
            }
        }
        let expired_sessions: Vec<_> = self
            .sessions
            .iter()
            .filter(|(_, record)| record.descriptor.expires_at_ms <= now_ms)
            .map(|(id, _)| id.clone())
            .collect();
        for id in expired_sessions {
            if let Some(record) = self.sessions.remove(&id) {
                let occurrence_id = self
                    .next_occurrence_id()
                ?;
                out.push(occurrence(
                    occurrence_id,
                    PairingOccurrenceKind::Expired,
                    None,
                    Some(record.descriptor.session_id),
                    self.origin.clone(),
                    self.epoch,
                    now_ms,
                    None,
                ));
            }
        }
        Ok(out)
    }

    /// Invalidate every pre-restart code and session. Secret bytes are dropped/zeroized.
    pub(crate) fn restart(
        &mut self,
        new_epoch: u64,
        now_ms: u64,
    ) -> Result<Vec<PairingOccurrence>, PairingError> {
        self.observe_now(now_ms)?;
        if new_epoch <= self.epoch {
            return Err(PairingError::InvalidEpoch);
        }
        let mut out = Vec::new();
        for (_, record) in self.codes.split_off("") {
            let occurrence_id = self.next_occurrence_id()?;
            out.push(occurrence(
                occurrence_id,
                PairingOccurrenceKind::RestartInvalidated,
                Some(record.issue_id),
                None,
                self.origin.clone(),
                self.epoch,
                now_ms,
                None,
            ));
        }
        for (_, record) in self.sessions.split_off("") {
            let occurrence_id = self.next_occurrence_id()?;
            out.push(occurrence(
                occurrence_id,
                PairingOccurrenceKind::RestartInvalidated,
                None,
                Some(record.descriptor.session_id),
                self.origin.clone(),
                self.epoch,
                now_ms,
                None,
            ));
        }
        self.epoch = new_epoch;
        self.failed_attempts = 0;
        self.failed_window_started_ms = now_ms;
        Ok(out)
    }

    fn check_origin(&self, origin: &PairingOrigin) -> Result<(), PairingError> {
        if origin == &self.origin {
            Ok(())
        } else {
            Err(PairingError::OriginMismatch)
        }
    }
    fn next_occurrence_id(&mut self) -> Result<joshi_domain::StableString, PairingError> {
        self.next_ordinal = self
            .next_ordinal
            .checked_add(1)
            .ok_or(PairingError::Identity)?;
        Ok(identity("pair-occurrence", self.epoch, self.next_ordinal))
    }
    fn check_attempt_window(&mut self, now_ms: u64) {
        if now_ms - self.failed_window_started_ms >= self.config.attempt_window_ms {
            self.failed_attempts = 0;
            self.failed_window_started_ms = now_ms;
        }
    }

    fn observe_now(&mut self, now_ms: u64) -> Result<(), PairingError> {
        if self.last_now_ms.is_some_and(|previous| now_ms < previous) {
            return Err(PairingError::ClockRollback);
        }
        self.last_now_ms = Some(now_ms);
        Ok(())
    }
}

impl<E: Entropy> PairingSessionPort for PairingRegistry<E> {
    fn issue_code(
        &mut self,
        clock: &mut dyn MonotonicClock,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError> {
        self.issue(clock.now_ms()?, scopes)
    }
    fn consume_code(
        &mut self,
        code: &SecretCode,
        origin: &PairingOrigin,
        clock: &mut dyn MonotonicClock,
    ) -> Result<ExchangedPairing, PairingError> {
        self.consume(code, origin, clock.now_ms()?)
    }

    fn authorize_capability(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        clock: &mut dyn MonotonicClock,
    ) -> Result<PairingSessionDescriptor, PairingError> {
        self.authorize(capability, origin, scope, clock.now_ms()?)
    }

    fn revoke_session(
        &mut self,
        session_id: &str,
        clock: &mut dyn MonotonicClock,
        reason: &str,
    ) -> Result<PairingOccurrence, PairingError> {
        self.revoke(session_id, clock.now_ms()?, reason)
    }
}

fn hex_lower(bytes: &[u8]) -> Vec<u8> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = Vec::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize]);
        out.push(HEX[(byte & 15) as usize]);
    }
    out
}

/// Domain-tag secret material before hex encoding. A code and a capability generated from the
/// same entropy block cannot compare equal, while both remain 32 bytes of secret material.
fn domain_separated_hex(bytes: &mut [u8], domain: u8) -> Vec<u8> {
    bytes[0] ^= domain;
    hex_lower(bytes)
}

/// Constant-time comparison over the fixed maximum secret length; length is included in the mask.
#[must_use]
pub fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    let mut difference = left.len() ^ right.len();
    for index in 0..64 {
        difference |= usize::from(
            left.get(index).copied().unwrap_or(0) ^ right.get(index).copied().unwrap_or(0),
        );
    }
    difference == 0
}
