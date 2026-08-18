use std::collections::BTreeMap;

use crate::{
    ExchangedPairing, IssuedPairing, MonotonicMillis, PAIRING_CAPABILITY_BYTES,
    PAIRING_CAPABILITY_PREFIX, PAIRING_CODE_ALPHABET, PAIRING_CODE_BYTES, PairingClockSample,
    PairingConfig, PairingConsumeOutcome, PairingError, PairingOccurrence, PairingOccurrenceKind,
    PairingOrigin, PairingScope, PairingSessionDescriptor, RejectedPairingAttempt,
    SecretCapability, SecretCode, identity, occurrence, pairing_epoch_occurrence_id,
};

/// Entropy is injected at the pure boundary; production route owners must use an OS source.
pub trait Entropy: Send {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError>;
}

/// One server-owned monotonic/security and wall/display clock sample.
pub trait PairingClock: Send {
    fn sample(&mut self) -> Result<PairingClockSample, PairingError>;
}

/// Store-resolved state for one fixed, origin-bound rate window during restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingRateWindowBootstrap {
    pub window_id: Option<joshi_domain::StableString>,
    pub used: u32,
    pub expires_at: Option<crate::PairingWallInstant>,
}

/// Durable rate state required before a production registry may start a new epoch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingRateBootstrap {
    pub last_observed_at: crate::PairingWallInstant,
    pub attempt: PairingRateWindowBootstrap,
    pub issue: PairingRateWindowBootstrap,
}

/// Deterministic test clock; it is absent from production builds.
#[cfg(test)]
#[derive(Clone, Copy, Debug)]
pub struct TestClock {
    monotonic_ms: u64,
    wall: crate::PairingWallInstant,
}

#[cfg(test)]
impl TestClock {
    #[must_use]
    pub const fn new(monotonic_ms: u64, wall: crate::PairingWallInstant) -> Self {
        Self { monotonic_ms, wall }
    }

    pub fn advance(&mut self, delta_ms: u64) -> Result<(), PairingError> {
        self.monotonic_ms = self
            .monotonic_ms
            .checked_add(delta_ms)
            .ok_or(PairingError::InvalidConfig)?;
        self.wall = self.wall.checked_add_ms(delta_ms)?;
        Ok(())
    }

    pub fn set_monotonic(&mut self, value: u64) {
        self.monotonic_ms = value;
    }

    pub fn set_wall(&mut self, value: crate::PairingWallInstant) {
        self.wall = value;
    }
}

#[cfg(test)]
impl PairingClock for TestClock {
    fn sample(&mut self) -> Result<PairingClockSample, PairingError> {
        Ok(PairingClockSample {
            monotonic_ms: MonotonicMillis::new(self.monotonic_ms),
            observed_at: self.wall,
        })
    }
}

/// A deterministic test-only entropy source.
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
            self.state ^= self.state >> 12;
            self.state ^= self.state << 25;
            self.state ^= self.state >> 27;
            *byte = self.state.to_le_bytes()[0];
        }
        Ok(())
    }
}

/// Narrow state-machine waist for a route/store coordinator.
pub trait PairingSessionPort {
    fn issue_code(
        &mut self,
        clock: &mut dyn PairingClock,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError>;

    fn consume_code(
        &mut self,
        code: &SecretCode,
        origin: &PairingOrigin,
        clock: &mut dyn PairingClock,
    ) -> Result<PairingConsumeOutcome, PairingError>;

    fn authorize_capability(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        clock: &mut dyn PairingClock,
    ) -> Result<PairingAuthorizationOutcome, PairingError>;
}

/// Authorization result that never drops expiry occurrences from the sampled transition.
#[derive(Debug)]
pub enum PairingAuthorizationOutcome {
    Authorized {
        descriptor: PairingSessionDescriptor,
        occurrences: Vec<PairingOccurrence>,
    },
    Rejected {
        error: PairingError,
        occurrences: Vec<PairingOccurrence>,
    },
}

struct CodeRecord {
    issue_id: joshi_domain::StableString,
    issued_occurrence_id: joshi_domain::StableString,
    code: SecretCode,
    expires_at_monotonic_ms: MonotonicMillis,
    scopes: Vec<PairingScope>,
}

struct SessionRecord {
    consumed_occurrence_id: joshi_domain::StableString,
    descriptor: PairingSessionDescriptor,
    expires_at_monotonic_ms: MonotonicMillis,
    capability: SecretCapability,
}

/// Service-owned, zeroizing registry. It is deliberately not serializable or restart-persistent.
pub struct PairingRegistry<E: Entropy> {
    origin: PairingOrigin,
    epoch: u64,
    config: PairingConfig,
    entropy: E,
    next_ordinal: u64,
    epoch_occurrence_id: joshi_domain::StableString,
    codes: BTreeMap<String, CodeRecord>,
    sessions: BTreeMap<String, SessionRecord>,
    failed_attempts: u32,
    failed_window_id: Option<joshi_domain::StableString>,
    failed_window_started_ms: MonotonicMillis,
    failed_window_deadline_ms: MonotonicMillis,
    failed_window_expires_at: Option<crate::PairingWallInstant>,
    issued_in_window: u32,
    issue_window_id: Option<joshi_domain::StableString>,
    issue_window_started_ms: MonotonicMillis,
    issue_window_deadline_ms: MonotonicMillis,
    issue_window_expires_at: Option<crate::PairingWallInstant>,
    last_now_ms: Option<MonotonicMillis>,
    last_observed_at: Option<crate::PairingWallInstant>,
}

impl<E: Entropy> PairingRegistry<E> {
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
        let epoch_occurrence_id = pairing_epoch_occurrence_id(&origin, epoch);
        Ok(Self {
            origin,
            epoch,
            config,
            entropy,
            next_ordinal: 0,
            epoch_occurrence_id,
            codes: BTreeMap::new(),
            sessions: BTreeMap::new(),
            failed_attempts: 0,
            failed_window_id: None,
            failed_window_started_ms: MonotonicMillis::new(0),
            failed_window_deadline_ms: MonotonicMillis::new(0),
            failed_window_expires_at: None,
            issued_in_window: 0,
            issue_window_id: None,
            issue_window_started_ms: MonotonicMillis::new(0),
            issue_window_deadline_ms: MonotonicMillis::new(0),
            issue_window_expires_at: None,
            last_now_ms: None,
            last_observed_at: None,
        })
    }

    /// Initialize after exact durable epoch/readback, carrying rate budgets and used ordinals.
    pub fn new_after_durable_epoch(
        origin: PairingOrigin,
        epoch: u64,
        config: PairingConfig,
        entropy: E,
        next_ordinal: u64,
        sample: PairingClockSample,
        rate: PairingRateBootstrap,
    ) -> Result<Self, PairingError> {
        let mut registry = Self::new(origin, epoch, config, entropy)?;
        if rate.last_observed_at > sample.observed_at {
            return Err(PairingError::ClockRollback);
        }
        let (failed_attempts, failed_deadline) =
            bootstrap_window(&rate.attempt, config.max_failed_attempts, sample)?;
        let (issued_in_window, issue_deadline) =
            bootstrap_window(&rate.issue, config.max_issued_per_window, sample)?;
        registry.next_ordinal = next_ordinal;
        registry.failed_attempts = failed_attempts;
        registry.failed_window_id = rate.attempt.window_id;
        registry.failed_window_started_ms = sample.monotonic_ms;
        registry.failed_window_deadline_ms = failed_deadline;
        registry.failed_window_expires_at = rate.attempt.expires_at;
        registry.issued_in_window = issued_in_window;
        registry.issue_window_id = rate.issue.window_id;
        registry.issue_window_started_ms = sample.monotonic_ms;
        registry.issue_window_deadline_ms = issue_deadline;
        registry.issue_window_expires_at = rate.issue.expires_at;
        registry.last_now_ms = Some(sample.monotonic_ms);
        registry.last_observed_at = Some(sample.observed_at);
        Ok(registry)
    }

    #[must_use]
    pub fn epoch(&self) -> u64 {
        self.epoch
    }

    #[must_use]
    pub fn origin(&self) -> &PairingOrigin {
        &self.origin
    }

    pub fn issue_now(
        &mut self,
        clock: &mut dyn PairingClock,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError> {
        let sample = clock.sample()?;
        let prior_occurrences = self.expire(sample)?;
        self.check_issue_window(sample.monotonic_ms);
        if self.issued_in_window >= self.config.max_issued_per_window
            || self.codes.len() >= self.config.max_active_codes
        {
            return Err(PairingError::RateLimited);
        }
        if scopes.is_empty() {
            return Err(PairingError::InvalidConfig);
        }
        let mut scopes = scopes;
        scopes.sort();
        scopes.dedup();
        self.next_ordinal = self.next_ordinal()?;
        let issue_id = identity("pair-issue", &self.origin, self.epoch, self.next_ordinal);
        let occurrence_id = identity(
            "pair-occurrence",
            &self.origin,
            self.epoch,
            self.next_ordinal,
        );
        let mut entropy = vec![0_u8; PAIRING_CODE_BYTES];
        self.entropy.fill(&mut entropy)?;
        let code_bytes = human_code(&entropy);
        entropy.fill(0);
        let code = SecretCode::from_bytes(code_bytes.clone());
        if self
            .codes
            .values()
            .any(|record| constant_time_equal(record.code.as_bytes(), code.as_bytes()))
        {
            return Err(PairingError::DuplicateSecret);
        }
        let expires_at_monotonic_ms = sample.monotonic_ms.checked_add(self.config.code_ttl_ms)?;
        let expires_at = sample.observed_at.checked_add_ms(self.config.code_ttl_ms)?;
        if self.issue_window_id.is_none() {
            self.issue_window_id = Some(occurrence_id.clone());
            self.issue_window_expires_at = Some(
                sample
                    .observed_at
                    .checked_add_ms(self.config.issue_window_ms)?,
            );
        }
        let metadata = occurrence(
            occurrence_id.clone(),
            PairingOccurrenceKind::Issued,
            Some(issue_id.clone()),
            None,
            Some(self.epoch_occurrence_id.clone()),
            self.origin.clone(),
            self.epoch,
            sample,
            Some(expires_at),
            scopes.clone(),
            self.issue_window_id.clone(),
            self.issue_window_expires_at,
            None,
            None,
            None,
        );
        metadata.validate()?;
        self.codes.insert(
            issue_id.as_str().to_owned(),
            CodeRecord {
                issue_id,
                issued_occurrence_id: occurrence_id,
                code: SecretCode::from_bytes(code_bytes),
                expires_at_monotonic_ms,
                scopes,
            },
        );
        self.issued_in_window = self.issued_in_window.saturating_add(1);
        Ok(IssuedPairing {
            code,
            metadata,
            prior_occurrences,
        })
    }

    #[allow(clippy::too_many_lines)]
    pub fn consume_now(
        &mut self,
        code: &SecretCode,
        origin: &PairingOrigin,
        clock: &mut dyn PairingClock,
    ) -> Result<PairingConsumeOutcome, PairingError> {
        let sample = clock.sample()?;
        let prior_occurrences = self.expire(sample)?;
        self.check_origin(origin)?;
        self.check_attempt_window(sample.monotonic_ms);
        let issue_key = self.codes.iter().find_map(|(id, record)| {
            constant_time_equal(record.code.as_bytes(), code.as_bytes()).then(|| id.clone())
        });
        let Some(issue_key) = issue_key else {
            if self.failed_attempts >= self.config.max_failed_attempts {
                return Err(PairingError::RateLimited);
            }
            self.failed_attempts = self.failed_attempts.saturating_add(1);
            let error = if self.failed_attempts >= self.config.max_failed_attempts {
                PairingError::RateLimited
            } else {
                PairingError::InvalidCode
            };
            let occurrence = self.rejected_attempt(sample, &error)?;
            return Ok(PairingConsumeOutcome::Rejected(RejectedPairingAttempt {
                error,
                occurrence,
                prior_occurrences,
            }));
        };
        if self.failed_attempts >= self.config.max_failed_attempts
            || self.sessions.len() >= self.config.max_live_sessions
        {
            if self.failed_attempts < self.config.max_failed_attempts {
                self.failed_attempts = self.failed_attempts.saturating_add(1);
            }
            let occurrence = self.rejected_attempt(sample, &PairingError::RateLimited)?;
            return Ok(PairingConsumeOutcome::Rejected(RejectedPairingAttempt {
                error: PairingError::RateLimited,
                occurrence,
                prior_occurrences,
            }));
        }
        let record = self
            .codes
            .remove(&issue_key)
            .ok_or(PairingError::InvalidCode)?;
        self.next_ordinal = self.next_ordinal()?;
        let session_id = identity("pair-session", &self.origin, self.epoch, self.next_ordinal);
        let occurrence_id = identity(
            "pair-occurrence",
            &self.origin,
            self.epoch,
            self.next_ordinal,
        );
        let expires_at_monotonic_ms = sample
            .monotonic_ms
            .checked_add(self.config.session_ttl_ms)?;
        let expires_at = sample
            .observed_at
            .checked_add_ms(self.config.session_ttl_ms)?;
        let descriptor = PairingSessionDescriptor::new(
            session_id.clone(),
            self.origin.clone(),
            self.epoch,
            expires_at,
            record.scopes.clone(),
        );
        descriptor.validate()?;
        let mut entropy = vec![0_u8; PAIRING_CAPABILITY_BYTES];
        self.entropy.fill(&mut entropy)?;
        let capability_bytes = capability_text(&entropy);
        entropy.fill(0);
        let capability = SecretCapability::from_bytes(capability_bytes);
        if self.sessions.values().any(|session| {
            constant_time_equal(session.capability.as_bytes(), capability.as_bytes())
        }) {
            self.codes.insert(issue_key, record);
            return Err(PairingError::DuplicateSecret);
        }
        let occurrence = occurrence(
            occurrence_id.clone(),
            PairingOccurrenceKind::Consumed,
            Some(record.issue_id),
            Some(session_id.clone()),
            Some(record.issued_occurrence_id),
            self.origin.clone(),
            self.epoch,
            sample,
            Some(expires_at),
            record.scopes,
            None,
            None,
            None,
            None,
            None,
        );
        occurrence.validate()?;
        self.sessions.insert(
            session_id.as_str().to_owned(),
            SessionRecord {
                consumed_occurrence_id: occurrence_id,
                descriptor: descriptor.clone(),
                expires_at_monotonic_ms,
                capability: SecretCapability::from_bytes(capability.as_bytes().to_vec()),
            },
        );
        Ok(PairingConsumeOutcome::Exchanged(ExchangedPairing {
            capability,
            descriptor,
            occurrence,
            prior_occurrences,
        }))
    }

    /// Record a malformed-but-bounded exchange submission without retaining any submitted bytes.
    pub fn reject_attempt_now(
        &mut self,
        origin: &PairingOrigin,
        clock: &mut dyn PairingClock,
    ) -> Result<RejectedPairingAttempt, PairingError> {
        let sample = clock.sample()?;
        let prior_occurrences = self.expire(sample)?;
        self.check_origin(origin)?;
        self.check_attempt_window(sample.monotonic_ms);
        if self.failed_attempts >= self.config.max_failed_attempts {
            return Err(PairingError::RateLimited);
        }
        self.failed_attempts = self.failed_attempts.saturating_add(1);
        let error = if self.failed_attempts >= self.config.max_failed_attempts {
            PairingError::RateLimited
        } else {
            PairingError::InvalidCode
        };
        let occurrence = self.rejected_attempt(sample, &error)?;
        Ok(RejectedPairingAttempt {
            error,
            occurrence,
            prior_occurrences,
        })
    }

    #[cfg(test)]
    pub(crate) fn authorize_now(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        clock: &mut dyn PairingClock,
    ) -> Result<(PairingSessionDescriptor, Vec<PairingOccurrence>), PairingError> {
        match self.authorize_outcome_now(capability, origin, scope, clock)? {
            PairingAuthorizationOutcome::Authorized {
                descriptor,
                occurrences,
            } => Ok((descriptor, occurrences)),
            PairingAuthorizationOutcome::Rejected { error, .. } => Err(error),
        }
    }

    pub fn authorize_outcome_now(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        clock: &mut dyn PairingClock,
    ) -> Result<PairingAuthorizationOutcome, PairingError> {
        let sample = clock.sample()?;
        let expired = self.expire(sample)?;
        if let Err(error) = self.check_origin(origin) {
            return Ok(PairingAuthorizationOutcome::Rejected {
                error,
                occurrences: expired,
            });
        }
        for record in self.sessions.values() {
            if constant_time_equal(record.capability.as_bytes(), capability.as_bytes()) {
                if !record.descriptor.scopes.contains(&scope) {
                    return Ok(PairingAuthorizationOutcome::Rejected {
                        error: PairingError::ScopeDenied,
                        occurrences: expired,
                    });
                }
                return Ok(PairingAuthorizationOutcome::Authorized {
                    descriptor: record.descriptor.clone(),
                    occurrences: expired,
                });
            }
        }
        Ok(PairingAuthorizationOutcome::Rejected {
            error: PairingError::InvalidSession,
            occurrences: expired,
        })
    }

    pub fn revoke_now(
        &mut self,
        session_id: &str,
        clock: &mut dyn PairingClock,
        reason: &str,
    ) -> Result<PairingOccurrence, PairingError> {
        let sample = clock.sample()?;
        self.observe_sample(sample)?;
        let record = self
            .sessions
            .remove(session_id)
            .ok_or(PairingError::InvalidSession)?;
        let occurrence_id = self.next_occurrence_id()?;
        let expired = record.expires_at_monotonic_ms <= sample.monotonic_ms;
        let value = occurrence(
            occurrence_id,
            if expired {
                PairingOccurrenceKind::Expired
            } else {
                PairingOccurrenceKind::Revoked
            },
            None,
            Some(record.descriptor.session_id),
            Some(record.consumed_occurrence_id),
            self.origin.clone(),
            self.epoch,
            sample,
            None,
            record.descriptor.scopes,
            None,
            None,
            None,
            None,
            Some(if expired {
                joshi_domain::StableString::new("monotonic_expiry").expect("static reason")
            } else {
                joshi_domain::StableString::new(reason).map_err(|_| PairingError::Identity)?
            }),
        );
        value.validate()?;
        Ok(value)
    }

    pub fn expire_now(
        &mut self,
        clock: &mut dyn PairingClock,
    ) -> Result<Vec<PairingOccurrence>, PairingError> {
        self.expire(clock.sample()?)
    }

    pub fn restart_now(
        &mut self,
        new_epoch: u64,
        clock: &mut dyn PairingClock,
    ) -> Result<Vec<PairingOccurrence>, PairingError> {
        let sample = clock.sample()?;
        self.observe_sample(sample)?;
        if new_epoch <= self.epoch {
            return Err(PairingError::InvalidEpoch);
        }
        let codes = std::mem::take(&mut self.codes);
        let sessions = std::mem::take(&mut self.sessions);
        self.epoch = new_epoch;
        self.epoch_occurrence_id = pairing_epoch_occurrence_id(&self.origin, new_epoch);
        self.next_ordinal = 0;
        let mut out = Vec::new();
        for (_, record) in codes {
            let occurrence_id = self.next_occurrence_id()?;
            out.push(occurrence(
                occurrence_id,
                PairingOccurrenceKind::RestartInvalidated,
                Some(record.issue_id),
                None,
                Some(record.issued_occurrence_id),
                self.origin.clone(),
                self.epoch,
                sample,
                None,
                record.scopes,
                None,
                None,
                None,
                None,
                Some(joshi_domain::StableString::new("process_restart").expect("static reason")),
            ));
        }
        for (_, record) in sessions {
            let occurrence_id = self.next_occurrence_id()?;
            out.push(occurrence(
                occurrence_id,
                PairingOccurrenceKind::RestartInvalidated,
                None,
                Some(record.descriptor.session_id),
                Some(record.consumed_occurrence_id),
                self.origin.clone(),
                self.epoch,
                sample,
                None,
                record.descriptor.scopes,
                None,
                None,
                None,
                None,
                Some(joshi_domain::StableString::new("process_restart").expect("static reason")),
            ));
        }
        for value in &out {
            value.validate()?;
        }
        Ok(out)
    }

    /// Fail-closed compensation when durable issuance did not return an exact readback receipt.
    pub fn invalidate_issue(&mut self, issue_id: &str) -> bool {
        self.codes.remove(issue_id).is_some()
    }

    /// Fail-closed compensation when durable consume did not return an exact readback receipt.
    pub fn invalidate_session(&mut self, session_id: &str) -> bool {
        self.sessions.remove(session_id).is_some()
    }

    fn rejected_attempt(
        &mut self,
        sample: PairingClockSample,
        error: &PairingError,
    ) -> Result<PairingOccurrence, PairingError> {
        let occurrence_id = self.next_occurrence_id()?;
        if self.failed_window_id.is_none() {
            self.failed_window_id = Some(occurrence_id.clone());
            self.failed_window_expires_at = Some(
                sample
                    .observed_at
                    .checked_add_ms(self.config.attempt_window_ms)?,
            );
        }
        let reason = match error {
            PairingError::RateLimited => "rate_limited",
            _ => "invalid_code",
        };
        let value = occurrence(
            occurrence_id,
            PairingOccurrenceKind::AttemptRejected,
            None,
            None,
            Some(self.epoch_occurrence_id.clone()),
            self.origin.clone(),
            self.epoch,
            sample,
            None,
            Vec::new(),
            self.failed_window_id.clone(),
            self.failed_window_expires_at,
            Some(self.failed_attempts),
            Some(self.failed_window_started_ms),
            Some(joshi_domain::StableString::new(reason).expect("static reason")),
        );
        value.validate()?;
        Ok(value)
    }

    fn expire(
        &mut self,
        sample: PairingClockSample,
    ) -> Result<Vec<PairingOccurrence>, PairingError> {
        self.observe_sample(sample)?;
        let mut out = Vec::new();
        let expired_codes: Vec<_> = self
            .codes
            .iter()
            .filter(|(_, record)| record.expires_at_monotonic_ms <= sample.monotonic_ms)
            .map(|(id, _)| id.clone())
            .collect();
        for id in expired_codes {
            if let Some(record) = self.codes.remove(&id) {
                let occurrence_id = self.next_occurrence_id()?;
                out.push(occurrence(
                    occurrence_id,
                    PairingOccurrenceKind::Expired,
                    Some(record.issue_id),
                    None,
                    Some(record.issued_occurrence_id),
                    self.origin.clone(),
                    self.epoch,
                    sample,
                    None,
                    record.scopes,
                    None,
                    None,
                    None,
                    None,
                    Some(
                        joshi_domain::StableString::new("monotonic_expiry").expect("static reason"),
                    ),
                ));
            }
        }
        let expired_sessions: Vec<_> = self
            .sessions
            .iter()
            .filter(|(_, record)| record.expires_at_monotonic_ms <= sample.monotonic_ms)
            .map(|(id, _)| id.clone())
            .collect();
        for id in expired_sessions {
            if let Some(record) = self.sessions.remove(&id) {
                let occurrence_id = self.next_occurrence_id()?;
                out.push(occurrence(
                    occurrence_id,
                    PairingOccurrenceKind::Expired,
                    None,
                    Some(record.descriptor.session_id),
                    Some(record.consumed_occurrence_id),
                    self.origin.clone(),
                    self.epoch,
                    sample,
                    None,
                    record.descriptor.scopes,
                    None,
                    None,
                    None,
                    None,
                    Some(
                        joshi_domain::StableString::new("monotonic_expiry").expect("static reason"),
                    ),
                ));
            }
        }
        for value in &out {
            value.validate()?;
        }
        Ok(out)
    }

    fn check_origin(&self, origin: &PairingOrigin) -> Result<(), PairingError> {
        if origin == &self.origin {
            Ok(())
        } else {
            Err(PairingError::OriginMismatch)
        }
    }

    fn next_ordinal(&self) -> Result<u64, PairingError> {
        self.next_ordinal
            .checked_add(1)
            .ok_or(PairingError::Identity)
    }

    fn next_occurrence_id(&mut self) -> Result<joshi_domain::StableString, PairingError> {
        self.next_ordinal = self.next_ordinal()?;
        Ok(identity(
            "pair-occurrence",
            &self.origin,
            self.epoch,
            self.next_ordinal,
        ))
    }

    fn check_attempt_window(&mut self, now_ms: MonotonicMillis) {
        if now_ms >= self.failed_window_deadline_ms {
            self.failed_attempts = 0;
            self.failed_window_id = None;
            self.failed_window_started_ms = now_ms;
            self.failed_window_deadline_ms =
                MonotonicMillis::new(now_ms.get().saturating_add(self.config.attempt_window_ms));
            self.failed_window_expires_at = None;
        }
    }

    fn check_issue_window(&mut self, now_ms: MonotonicMillis) {
        if now_ms >= self.issue_window_deadline_ms {
            self.issued_in_window = 0;
            self.issue_window_id = None;
            self.issue_window_started_ms = now_ms;
            self.issue_window_deadline_ms =
                MonotonicMillis::new(now_ms.get().saturating_add(self.config.issue_window_ms));
            self.issue_window_expires_at = None;
        }
    }

    fn observe_now(&mut self, now_ms: MonotonicMillis) -> Result<(), PairingError> {
        if self.last_now_ms.is_some_and(|previous| now_ms < previous) {
            return Err(PairingError::ClockRollback);
        }
        self.last_now_ms = Some(now_ms);
        Ok(())
    }

    fn observe_sample(&mut self, sample: PairingClockSample) -> Result<(), PairingError> {
        if self
            .last_observed_at
            .is_some_and(|previous| sample.observed_at < previous)
        {
            return Err(PairingError::InvalidWallClock);
        }
        self.observe_now(sample.monotonic_ms)?;
        self.last_observed_at = Some(sample.observed_at);
        Ok(())
    }
}

impl<E: Entropy> PairingSessionPort for PairingRegistry<E> {
    fn issue_code(
        &mut self,
        clock: &mut dyn PairingClock,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, PairingError> {
        self.issue_now(clock, scopes)
    }

    fn consume_code(
        &mut self,
        code: &SecretCode,
        origin: &PairingOrigin,
        clock: &mut dyn PairingClock,
    ) -> Result<PairingConsumeOutcome, PairingError> {
        self.consume_now(code, origin, clock)
    }

    fn authorize_capability(
        &mut self,
        capability: &SecretCapability,
        origin: &PairingOrigin,
        scope: PairingScope,
        clock: &mut dyn PairingClock,
    ) -> Result<PairingAuthorizationOutcome, PairingError> {
        self.authorize_outcome_now(capability, origin, scope, clock)
    }
}

fn bootstrap_window(
    window: &PairingRateWindowBootstrap,
    limit: u32,
    sample: PairingClockSample,
) -> Result<(u32, MonotonicMillis), PairingError> {
    match (&window.window_id, window.used, window.expires_at) {
        (None, 0, None) => Ok((0, sample.monotonic_ms)),
        (Some(_), used, Some(expires_at)) if (1..=limit).contains(&used) => {
            if expires_at <= sample.observed_at {
                return Err(PairingError::InvalidConfig);
            }
            let remaining = sample.observed_at.milliseconds_until(expires_at)?;
            Ok((used, sample.monotonic_ms.checked_add(remaining)?))
        }
        _ => Err(PairingError::InvalidConfig),
    }
}

fn human_code(bytes: &[u8]) -> Vec<u8> {
    debug_assert_eq!(bytes.len(), PAIRING_CODE_BYTES);
    let mut symbols = Vec::with_capacity(32);
    let mut accumulator = 0_u32;
    let mut bits = 0_u8;
    for byte in bytes {
        accumulator = (accumulator << 8) | u32::from(*byte);
        bits += 8;
        while bits >= 5 {
            bits -= 5;
            symbols.push(PAIRING_CODE_ALPHABET[((accumulator >> bits) & 31) as usize]);
        }
    }
    debug_assert_eq!(bits, 0);
    let mut out = Vec::with_capacity(46);
    out.extend_from_slice(b"JOSHI");
    for group in symbols.chunks_exact(4) {
        out.push(b'-');
        out.extend_from_slice(group);
    }
    out
}

fn capability_text(bytes: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(PAIRING_CAPABILITY_PREFIX.len() + bytes.len() * 2);
    out.extend_from_slice(PAIRING_CAPABILITY_PREFIX.as_bytes());
    hex_lower_into(bytes, &mut out);
    out
}

fn hex_lower_into(bytes: &[u8], out: &mut Vec<u8>) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize]);
        out.push(HEX[(byte & 15) as usize]);
    }
}

/// Constant-time comparison over the maximum secret representation length, including length.
#[must_use]
pub fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    const MAX_SECRET_TEXT: usize = PAIRING_CAPABILITY_PREFIX.len() + PAIRING_CAPABILITY_BYTES * 2;
    let mut difference = left.len() ^ right.len();
    for index in 0..MAX_SECRET_TEXT {
        difference |= usize::from(
            left.get(index).copied().unwrap_or(0) ^ right.get(index).copied().unwrap_or(0),
        );
    }
    difference == 0
}
