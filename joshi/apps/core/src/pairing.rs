//! Fail-closed ordinary pairing coordinator and same-origin exchange route.
//!
//! The route can only be constructed around a journal that has durably begun a new epoch. The
//! default [`crate::service::CoreService`] router does not mount it.

use std::{
    net::IpAddr,
    sync::{Arc, Mutex},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use axum::{
    Router,
    body::Bytes,
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, HeaderValue, StatusCode, Uri, header},
    response::{IntoResponse, Response},
    routing::post,
};
use joshi_admission::{Sha256Digest, strict_json};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_pairing::{
    Entropy, IssuedPairing, MonotonicMillis, PairingAuthorizationOutcome, PairingClock,
    PairingClockSample, PairingConfig, PairingConsumeOutcome, PairingEpoch, PairingError,
    PairingOccurrence, PairingOccurrenceKind, PairingOrigin, PairingRateBootstrap,
    PairingRateWindowBootstrap, PairingRegistry, PairingScope, PairingSessionDescriptor,
    PairingWallInstant, SecretCapability, SecretCode, pairing_occurrence_id,
    parse_pairing_occurrence,
};
use joshi_store::{
    PairingEpochReceipt as StorePairingEpochReceipt,
    PairingJournalReceipt as StorePairingJournalReceipt,
    PairingRateBootstrap as StorePairingRateBootstrap,
    PairingRatePolicyV1 as StorePairingRatePolicy, SqliteStore,
};
use serde::{Deserialize, Serialize};

const MAX_PAIRING_REQUEST_BYTES: usize = 4 * 1024;
const PAIRING_TOKEN_HEADER: &str = "x-joshi-pairing-token";
const SEC_FETCH_DEST_HEADER: &str = "sec-fetch-dest";
const SEC_FETCH_MODE_HEADER: &str = "sec-fetch-mode";
const SEC_FETCH_SITE_HEADER: &str = "sec-fetch-site";

/// Exact nonsecret bytes handed to the sole durable writer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingJournalEntry {
    pub occurrence_id: StableString,
    pub document_sha256: StableString,
    pub canonical_bytes: Vec<u8>,
}

/// A durable append receipt must carry exact readback bytes, not a caller-authored success flag.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingJournalReceipt {
    pub occurrence_id: StableString,
    pub document_sha256: StableString,
    pub readback_bytes: Vec<u8>,
    pub commit_seq: u64,
}

/// Store-owned epoch receipt. `epoch` must increase for an exact origin across every reopen.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingEpochReceipt {
    pub origin: PairingOrigin,
    pub epoch: u64,
    pub invalidated_issue_count: u32,
    pub invalidated_session_count: u32,
    pub next_ordinal: u64,
    pub invalidations: Vec<PairingJournalReceipt>,
    pub rate: PairingRateBootstrap,
    pub commit_seq: u64,
    pub epoch_occurrence: PairingJournalReceipt,
}

/// Neutral sole-writer port. `Ok` promises transaction commit plus exact post-commit readback.
pub trait PairingJournal: Send {
    /// Begin and read back a strictly higher exact-origin epoch, including its root occurrence.
    ///
    /// # Errors
    ///
    /// Returns an error unless epoch start and prior-live-state invalidation commit atomically.
    fn begin_epoch(
        &mut self,
        origin: &PairingOrigin,
        sample: PairingClockSample,
        config: PairingConfig,
    ) -> Result<PairingEpochReceipt, PairingJournalError>;

    /// Append all entries in one transaction and return their exact committed readbacks.
    ///
    /// # Errors
    ///
    /// Returns an error for any failed, partial, ambiguous, or mismatching durable append.
    fn append_atomically(
        &mut self,
        entries: &[PairingJournalEntry],
    ) -> Result<Vec<PairingJournalReceipt>, PairingJournalError>;
}

/// Sealed production journal binding. Only a reviewed in-crate store adapter may construct it.
///
/// There is intentionally no public constructor while the sole-store implementation is absent.
pub(crate) struct DurablePairingJournal(Box<dyn PairingJournal>);

struct SqlitePairingJournal {
    store: Arc<Mutex<SqliteStore>>,
    writer_build: StableString,
}

impl SqlitePairingJournal {
    fn new(store: Arc<Mutex<SqliteStore>>) -> Result<Self, PairingJournalError> {
        Ok(Self {
            store,
            writer_build: StableString::new("joshi-core-pairing-v1")
                .map_err(|_| PairingJournalError)?,
        })
    }

    fn context(
        store: &SqliteStore,
        writer_build: &StableString,
        namespace: &str,
        exact_preimage: &[u8],
    ) -> Result<joshi_store::Wave5CommitContext, PairingJournalError> {
        let digest = Sha256Digest::of_bytes(exact_preimage);
        let batch_id = StableString::new(format!(
            "pairing-{namespace}:{}",
            digest.as_str().trim_start_matches("sha256:")
        ))
        .map_err(|_| PairingJournalError)?;
        store
            .begin_wave5_commit(batch_id, writer_build.clone())
            .map_err(|_| PairingJournalError)
    }
}

impl DurablePairingJournal {
    #[cfg(test)]
    fn from_sqlite(store: SqliteStore) -> Result<Self, PairingJournalError> {
        Self::from_shared_sqlite(Arc::new(Mutex::new(store)))
    }

    fn from_shared_sqlite(store: Arc<Mutex<SqliteStore>>) -> Result<Self, PairingJournalError> {
        Ok(Self(Box::new(SqlitePairingJournal::new(store)?)))
    }

    #[cfg(test)]
    fn from_test(journal: Box<dyn PairingJournal>) -> Self {
        Self(journal)
    }
}

impl PairingJournal for SqlitePairingJournal {
    fn begin_epoch(
        &mut self,
        origin: &PairingOrigin,
        sample: PairingClockSample,
        config: PairingConfig,
    ) -> Result<PairingEpochReceipt, PairingJournalError> {
        let mut nonce = [0_u8; 32];
        getrandom::fill(&mut nonce).map_err(|_| PairingJournalError)?;
        let mut preimage = b"joshi.core.pairing.epoch-batch.v1\0".to_vec();
        preimage.extend_from_slice(origin.as_str().as_bytes());
        preimage.push(0);
        preimage.extend_from_slice(&nonce);
        let mut store = self.store.lock().map_err(|_| PairingJournalError)?;
        let context = Self::context(&store, &self.writer_build, "epoch", &preimage)?;
        let store_receipt = store
            .begin_pairing_epoch_v1(
                origin,
                sample,
                StorePairingRatePolicy {
                    max_failed_attempts: config.max_failed_attempts,
                    attempt_window_ms: config.attempt_window_ms,
                    max_issued_per_window: config.max_issued_per_window,
                    issue_window_ms: config.issue_window_ms,
                },
                &context,
            )
            .map_err(|_| PairingJournalError)?;
        core_epoch_receipt(store_receipt)
    }

    fn append_atomically(
        &mut self,
        entries: &[PairingJournalEntry],
    ) -> Result<Vec<PairingJournalReceipt>, PairingJournalError> {
        if entries.is_empty() {
            return Ok(Vec::new());
        }
        let mut preimage = b"joshi.core.pairing.append-batch.v1\0".to_vec();
        let mut documents = Vec::with_capacity(entries.len());
        for entry in entries {
            let length =
                u64::try_from(entry.canonical_bytes.len()).map_err(|_| PairingJournalError)?;
            preimage.extend_from_slice(&length.to_be_bytes());
            preimage.extend_from_slice(&entry.canonical_bytes);
            documents.push(entry.canonical_bytes.clone());
        }
        let mut store = self.store.lock().map_err(|_| PairingJournalError)?;
        let context = Self::context(&store, &self.writer_build, "append", &preimage)?;
        store
            .append_pairing_occurrences_v1(&documents, &context)
            .map_err(|_| PairingJournalError)?
            .iter()
            .map(core_journal_receipt)
            .collect()
    }
}

fn core_epoch_receipt(
    receipt: StorePairingEpochReceipt,
) -> Result<PairingEpochReceipt, PairingJournalError> {
    Ok(PairingEpochReceipt {
        origin: receipt.origin,
        epoch: receipt.epoch,
        invalidated_issue_count: receipt.invalidated_issue_count,
        invalidated_session_count: receipt.invalidated_session_count,
        next_ordinal: receipt.next_ordinal,
        invalidations: receipt
            .invalidations
            .iter()
            .map(core_journal_receipt)
            .collect::<Result<_, _>>()?,
        rate: core_rate_bootstrap(receipt.rate),
        commit_seq: receipt.commit_seq.get(),
        epoch_occurrence: core_journal_receipt(&receipt.epoch_occurrence)?,
    })
}

fn core_rate_bootstrap(rate: StorePairingRateBootstrap) -> PairingRateBootstrap {
    fn window(value: joshi_store::PairingRateWindowBootstrap) -> PairingRateWindowBootstrap {
        PairingRateWindowBootstrap {
            window_id: value.window_id,
            used: value.used,
            expires_at: value.expires_at,
        }
    }
    PairingRateBootstrap {
        last_observed_at: rate.last_observed_at,
        attempt: window(rate.attempt),
        issue: window(rate.issue),
    }
}

fn core_journal_receipt(
    receipt: &StorePairingJournalReceipt,
) -> Result<PairingJournalReceipt, PairingJournalError> {
    Ok(PairingJournalReceipt {
        occurrence_id: receipt.occurrence_id().clone(),
        document_sha256: StableString::new(receipt.document_digest().to_string())
            .map_err(|_| PairingJournalError)?,
        readback_bytes: receipt.readback_bytes().to_vec(),
        commit_seq: receipt.commit_seq().get(),
    })
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[error("durable pairing journal did not return an exact committed readback")]
pub struct PairingJournalError;

struct OsEntropy;

impl Entropy for OsEntropy {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError> {
        getrandom::fill(bytes).map_err(|_| PairingError::Entropy)
    }
}

struct ProcessPairingClock {
    started: Instant,
    wall_started: PairingWallInstant,
}

impl ProcessPairingClock {
    fn new() -> Result<Self, PairingError> {
        let wall_nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| PairingError::InvalidWallClock)?
            .as_nanos();
        let wall_micros = wall_nanos / 1_000;
        let wall_nanos = i128::try_from(wall_micros)
            .ok()
            .and_then(|value| value.checked_mul(1_000))
            .ok_or(PairingError::InvalidWallClock)?;
        let wall = time::OffsetDateTime::from_unix_timestamp_nanos(wall_nanos)
            .map_err(|_| PairingError::InvalidWallClock)?;
        let wall = UtcTimestamp::new(wall).map_err(|_| PairingError::InvalidWallClock)?;
        Ok(Self {
            started: Instant::now(),
            wall_started: PairingWallInstant::new(wall),
        })
    }
}

impl PairingClock for ProcessPairingClock {
    fn sample(&mut self) -> Result<PairingClockSample, PairingError> {
        let monotonic_ms = u64::try_from(self.started.elapsed().as_millis())
            .map_err(|_| PairingError::InvalidConfig)?;
        Ok(PairingClockSample {
            monotonic_ms: MonotonicMillis::new(monotonic_ms),
            observed_at: self.wall_started.checked_add_ms(monotonic_ms)?,
        })
    }
}

struct DynEntropy(Box<dyn Entropy>);

impl Entropy for DynEntropy {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError> {
        self.0.fill(bytes)
    }
}

struct DynClock(Box<dyn PairingClock>);

impl PairingClock for DynClock {
    fn sample(&mut self) -> Result<PairingClockSample, PairingError> {
        self.0.sample()
    }
}

struct Runtime {
    registry: PairingRegistry<DynEntropy>,
    clock: DynClock,
    journal: Box<dyn PairingJournal>,
    poisoned: bool,
}

/// Ordinary route/launcher state with a mandatory durable journal and private production clocks.
pub struct OrdinaryPairingService {
    origin: PairingOrigin,
    runtime: Mutex<Runtime>,
}

/// Pairing-specific authorization waist used by Core handlers when the sealed service is mounted.
pub(crate) trait PairingAuthorizer: Send + Sync {
    fn authorize(
        &self,
        capability_text: &str,
        origin_text: &str,
        scope: PairingScope,
    ) -> Result<PairingSessionDescriptor, OrdinaryPairingError>;
}

impl OrdinaryPairingService {
    pub(crate) fn configured_origin(&self) -> &PairingOrigin {
        &self.origin
    }
    /// Construct the only production variant: OS entropy, process clocks, and the sole `SQLite`
    /// writer adapter. No caller-implemented journal can reach this boundary.
    #[allow(dead_code)] // Mounted only by the G0 root harness after selecting its store.
    pub(crate) fn production(
        origin: PairingOrigin,
        config: PairingConfig,
        store: SqliteStore,
    ) -> Result<Self, OrdinaryPairingError> {
        Self::production_with_shared_store(origin, config, Arc::new(Mutex::new(store)))
    }

    pub(crate) fn production_with_shared_store(
        origin: PairingOrigin,
        config: PairingConfig,
        store: Arc<Mutex<SqliteStore>>,
    ) -> Result<Self, OrdinaryPairingError> {
        Self::initialize_durable(
            origin,
            config,
            DurablePairingJournal::from_shared_sqlite(store)?,
            Box::new(OsEntropy),
            Box::new(ProcessPairingClock::new()?),
        )
    }

    fn initialize_durable(
        origin: PairingOrigin,
        config: PairingConfig,
        journal: DurablePairingJournal,
        entropy: Box<dyn Entropy>,
        mut clock: Box<dyn PairingClock>,
    ) -> Result<Self, OrdinaryPairingError> {
        config.validate()?;
        let uri = origin
            .as_str()
            .parse::<Uri>()
            .map_err(|_| PairingError::InvalidOrigin)?;
        let authority = uri.authority().ok_or(PairingError::InvalidOrigin)?;
        if !exact_loopback_same_origin(origin.as_str(), authority.as_str()) {
            return Err(PairingError::InvalidOrigin.into());
        }
        let mut journal = journal.0;
        let sample = clock.sample()?;
        let epoch = journal.begin_epoch(&origin, sample, config)?;
        if epoch.origin != origin || epoch.epoch == 0 || epoch.commit_seq == 0 {
            return Err(OrdinaryPairingError::Journal(PairingJournalError));
        }
        let epoch_occurrence = parse_pairing_occurrence(&epoch.epoch_occurrence.readback_bytes)
            .map_err(|_| PairingJournalError)?;
        let epoch_entry = PairingJournalEntry {
            occurrence_id: epoch_occurrence.occurrence_id.clone(),
            document_sha256: StableString::new(
                Sha256Digest::of_bytes(&epoch.epoch_occurrence.readback_bytes).to_string(),
            )
            .map_err(|_| PairingJournalError)?,
            canonical_bytes: epoch.epoch_occurrence.readback_bytes.clone(),
        };
        if !receipt_matches_entry(&epoch.epoch_occurrence, &epoch_entry)
            || epoch_occurrence.kind != PairingOccurrenceKind::EpochStarted
            || epoch_occurrence.origin != origin
            || epoch_occurrence.epoch.get() != epoch.epoch
            || epoch_occurrence.at_monotonic_ms != sample.monotonic_ms
            || epoch_occurrence.observed_at != sample.observed_at
            || epoch.epoch_occurrence.commit_seq != epoch.commit_seq
        {
            return Err(OrdinaryPairingError::Journal(PairingJournalError));
        }
        verify_epoch_invalidations(&origin, sample, config, &epoch)?;
        let registry = PairingRegistry::new_after_durable_epoch(
            origin.clone(),
            epoch.epoch,
            config,
            DynEntropy(entropy),
            epoch.next_ordinal,
            sample,
            epoch.rate,
        )?;
        Ok(Self::from_registry_parts(origin, registry, clock, journal))
    }

    #[cfg(test)]
    fn from_initialized_parts(
        origin: PairingOrigin,
        config: PairingConfig,
        epoch: u64,
        entropy: Box<dyn Entropy>,
        clock: Box<dyn PairingClock>,
        journal: Box<dyn PairingJournal>,
    ) -> Result<Self, OrdinaryPairingError> {
        let registry = PairingRegistry::new(origin.clone(), epoch, config, DynEntropy(entropy))?;
        Ok(Self::from_registry_parts(origin, registry, clock, journal))
    }

    fn from_registry_parts(
        origin: PairingOrigin,
        registry: PairingRegistry<DynEntropy>,
        clock: Box<dyn PairingClock>,
        journal: Box<dyn PairingJournal>,
    ) -> Self {
        Self {
            origin,
            runtime: Mutex::new(Runtime {
                registry,
                clock: DynClock(clock),
                journal,
                poisoned: false,
            }),
        }
    }

    /// Launcher-only handoff. No HTTP issuance route exists.
    ///
    /// # Errors
    ///
    /// Fails closed for invalid policy/state, clock/entropy failure, writer failure, or any
    /// non-exact durable receipt. A failed call never leaves a usable new code.
    pub fn issue_code(
        &self,
        scopes: Vec<PairingScope>,
    ) -> Result<IssuedPairing, OrdinaryPairingError> {
        let mut runtime = self
            .runtime
            .lock()
            .map_err(|_| OrdinaryPairingError::Unavailable)?;
        let Runtime {
            registry,
            clock,
            journal,
            poisoned,
        } = &mut *runtime;
        if *poisoned {
            return Err(OrdinaryPairingError::Unavailable);
        }
        let issued = registry.issue_now(clock, scopes)?;
        let mut occurrences = issued.prior_occurrences.clone();
        occurrences.push(issued.metadata.clone());
        if persist_exact(journal.as_mut(), &occurrences).is_err() {
            if let Some(issue_id) = &issued.metadata.issue_id {
                registry.invalidate_issue(issue_id.as_str());
            }
            *poisoned = true;
            return Err(OrdinaryPairingError::Journal(PairingJournalError));
        }
        Ok(issued)
    }

    /// Revoke one live session, persisting the terminal occurrence before returning it.
    ///
    /// # Errors
    ///
    /// Fails closed if the session is absent/expired or exact durable readback is unavailable.
    pub fn revoke_session(
        &self,
        session_id: &str,
        reason: &str,
    ) -> Result<PairingOccurrence, OrdinaryPairingError> {
        let mut runtime = self
            .runtime
            .lock()
            .map_err(|_| OrdinaryPairingError::Unavailable)?;
        let Runtime {
            registry,
            clock,
            journal,
            poisoned,
        } = &mut *runtime;
        if *poisoned {
            return Err(OrdinaryPairingError::Unavailable);
        }
        let occurrence = registry.revoke_now(session_id, clock, reason)?;
        if persist_exact(journal.as_mut(), std::slice::from_ref(&occurrence)).is_err() {
            *poisoned = true;
            return Err(OrdinaryPairingError::Journal(PairingJournalError));
        }
        Ok(occurrence)
    }

    fn exchange(&self, code_text: &str) -> Result<Exchanged, OrdinaryPairingError> {
        let mut runtime = self
            .runtime
            .lock()
            .map_err(|_| OrdinaryPairingError::Unavailable)?;
        let Runtime {
            registry,
            clock,
            journal,
            poisoned,
        } = &mut *runtime;
        if *poisoned {
            return Err(OrdinaryPairingError::Unavailable);
        }
        let outcome = match SecretCode::parse(code_text) {
            Ok(code) => registry.consume_now(&code, &self.origin, clock)?,
            Err(PairingError::MalformedSecret) => {
                PairingConsumeOutcome::Rejected(registry.reject_attempt_now(&self.origin, clock)?)
            }
            Err(error) => return Err(error.into()),
        };
        match outcome {
            PairingConsumeOutcome::Exchanged(exchange) => {
                let mut occurrences = exchange.prior_occurrences.clone();
                occurrences.push(exchange.occurrence.clone());
                if persist_exact(journal.as_mut(), &occurrences).is_err() {
                    registry.invalidate_session(exchange.descriptor.session_id.as_str());
                    *poisoned = true;
                    return Err(OrdinaryPairingError::Journal(PairingJournalError));
                }
                Ok(Exchanged::Session {
                    capability: exchange.capability,
                    descriptor: exchange.descriptor,
                })
            }
            PairingConsumeOutcome::Rejected(rejection) => {
                let mut occurrences = rejection.prior_occurrences;
                occurrences.push(rejection.occurrence);
                if persist_exact(journal.as_mut(), &occurrences).is_err() {
                    *poisoned = true;
                    return Err(OrdinaryPairingError::Journal(PairingJournalError));
                }
                Ok(Exchanged::Rejected(rejection.error))
            }
        }
    }
}

impl PairingAuthorizer for OrdinaryPairingService {
    fn authorize(
        &self,
        capability_text: &str,
        origin_text: &str,
        scope: PairingScope,
    ) -> Result<PairingSessionDescriptor, OrdinaryPairingError> {
        let capability = SecretCapability::parse(capability_text)?;
        let origin = PairingOrigin::new(origin_text)?;
        let mut runtime = self
            .runtime
            .lock()
            .map_err(|_| OrdinaryPairingError::Unavailable)?;
        let Runtime {
            registry,
            clock,
            journal,
            poisoned,
        } = &mut *runtime;
        if *poisoned {
            return Err(OrdinaryPairingError::Unavailable);
        }
        let outcome = registry.authorize_outcome_now(&capability, &origin, scope, clock)?;
        let occurrences = match &outcome {
            PairingAuthorizationOutcome::Authorized { occurrences, .. }
            | PairingAuthorizationOutcome::Rejected { occurrences, .. } => occurrences,
        };
        if persist_exact(journal.as_mut(), occurrences).is_err() {
            *poisoned = true;
            return Err(OrdinaryPairingError::Journal(PairingJournalError));
        }
        match outcome {
            PairingAuthorizationOutcome::Authorized { descriptor, .. } => Ok(descriptor),
            PairingAuthorizationOutcome::Rejected { error, .. } => Err(error.into()),
        }
    }
}

fn persist_exact(
    journal: &mut dyn PairingJournal,
    occurrences: &[PairingOccurrence],
) -> Result<(), PairingJournalError> {
    if occurrences.is_empty() {
        return Ok(());
    }
    let mut entries = Vec::with_capacity(occurrences.len());
    for occurrence in occurrences {
        let canonical_bytes = occurrence
            .canonical_bytes()
            .map_err(|_| PairingJournalError)?;
        entries.push(PairingJournalEntry {
            occurrence_id: occurrence.occurrence_id.clone(),
            document_sha256: StableString::new(
                Sha256Digest::of_bytes(&canonical_bytes).to_string(),
            )
            .map_err(|_| PairingJournalError)?,
            canonical_bytes,
        });
    }
    let receipts = journal.append_atomically(&entries)?;
    if receipts.len() != entries.len()
        || receipts
            .iter()
            .zip(&entries)
            .any(|(receipt, entry)| !receipt_matches_entry(receipt, entry))
    {
        return Err(PairingJournalError);
    }
    Ok(())
}

fn receipt_matches_entry(receipt: &PairingJournalReceipt, entry: &PairingJournalEntry) -> bool {
    receipt.occurrence_id == entry.occurrence_id
        && receipt.document_sha256 == entry.document_sha256
        && receipt.readback_bytes == entry.canonical_bytes
        && receipt.commit_seq > 0
}

fn verify_epoch_invalidations(
    origin: &PairingOrigin,
    sample: PairingClockSample,
    config: PairingConfig,
    epoch: &PairingEpochReceipt,
) -> Result<(), PairingJournalError> {
    let expected_len = usize::try_from(epoch.next_ordinal).map_err(|_| PairingJournalError)?;
    if epoch.invalidations.len() != expected_len
        || expected_len
            > config
                .max_active_codes
                .saturating_add(config.max_live_sessions)
        || epoch
            .invalidated_issue_count
            .saturating_add(epoch.invalidated_session_count)
            != u32::try_from(expected_len).map_err(|_| PairingJournalError)?
    {
        return Err(PairingJournalError);
    }
    let mut issue_count = 0_u32;
    let mut session_count = 0_u32;
    for (index, receipt) in epoch.invalidations.iter().enumerate() {
        let occurrence =
            parse_pairing_occurrence(&receipt.readback_bytes).map_err(|_| PairingJournalError)?;
        let entry = PairingJournalEntry {
            occurrence_id: occurrence.occurrence_id.clone(),
            document_sha256: StableString::new(
                Sha256Digest::of_bytes(&receipt.readback_bytes).to_string(),
            )
            .map_err(|_| PairingJournalError)?,
            canonical_bytes: receipt.readback_bytes.clone(),
        };
        let ordinal = u64::try_from(index + 1).map_err(|_| PairingJournalError)?;
        if !receipt_matches_entry(receipt, &entry)
            || receipt.commit_seq != epoch.commit_seq
            || occurrence.occurrence_id != pairing_occurrence_id(origin, epoch.epoch, ordinal)
            || occurrence.kind != PairingOccurrenceKind::RestartInvalidated
            || &occurrence.origin != origin
            || occurrence.epoch.get() != epoch.epoch
            || occurrence.at_monotonic_ms != sample.monotonic_ms
            || occurrence.observed_at != sample.observed_at
            || occurrence.predecessor_occurrence_id.is_none()
        {
            return Err(PairingJournalError);
        }
        match (
            occurrence.issue_id.is_some(),
            occurrence.session_id.is_some(),
        ) {
            (true, false) => issue_count = issue_count.saturating_add(1),
            (false, true) => session_count = session_count.saturating_add(1),
            _ => return Err(PairingJournalError),
        }
    }
    if issue_count != epoch.invalidated_issue_count
        || session_count != epoch.invalidated_session_count
    {
        return Err(PairingJournalError);
    }
    Ok(())
}

enum Exchanged {
    Session {
        capability: SecretCapability,
        descriptor: PairingSessionDescriptor,
    },
    Rejected(PairingError),
}

#[derive(Debug, thiserror::Error)]
pub enum OrdinaryPairingError {
    #[error(transparent)]
    Pairing(#[from] PairingError),
    #[error(transparent)]
    Journal(#[from] PairingJournalError),
    #[error("pairing coordinator lock is unavailable")]
    Unavailable,
}

/// Mount the exchange route only after the sealed production constructor succeeds.
pub fn ordinary_pairing_router(service: Arc<OrdinaryPairingService>) -> Router {
    Router::new()
        .route("/api/v1/pairing/exchange", post(exchange_route))
        .layer(DefaultBodyLimit::max(MAX_PAIRING_REQUEST_BYTES))
        .with_state(service)
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PairingExchangeRequest {
    contract: StableString,
    schema_version: u16,
    one_time_code: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PairingExchangeResponse<'a> {
    contract: &'static str,
    schema_version: u16,
    session_id: &'a StableString,
    origin: &'a PairingOrigin,
    epoch: PairingEpoch,
    expires_at: PairingWallInstant,
    scopes: &'a [PairingScope],
    authority: &'static str,
    capability: &'a str,
}

async fn exchange_route(
    State(service): State<Arc<OrdinaryPairingService>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = browser_posture_failure(&service.origin, &headers) {
        return response;
    }
    if headers.get(PAIRING_TOKEN_HEADER).is_some() {
        return problem(
            StatusCode::BAD_REQUEST,
            "unexpected_capability",
            "pairing exchange cannot carry an existing capability",
        );
    }
    if header_text(&headers, header::CONTENT_TYPE.as_str()).as_deref() != Some("application/json") {
        return problem(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "invalid_content_type",
            "content type must be application/json",
        );
    }
    let Ok(request): Result<PairingExchangeRequest, _> =
        strict_json::parse(&body, MAX_PAIRING_REQUEST_BYTES)
    else {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_pairing_exchange",
            "pairing exchange failed strict V1 parsing",
        );
    };
    if request.contract.as_str() != "joshi.pairing.exchange" || request.schema_version != 1 {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_pairing_exchange",
            "pairing exchange contract or schema is unsupported",
        );
    }
    match service.exchange(&request.one_time_code) {
        Ok(Exchanged::Session {
            capability,
            descriptor,
        }) => json_response(
            StatusCode::OK,
            &PairingExchangeResponse {
                contract: "joshi.pairing.session",
                schema_version: 1,
                session_id: &descriptor.session_id,
                origin: &descriptor.origin,
                epoch: descriptor.epoch,
                expires_at: descriptor.expires_at,
                scopes: &descriptor.scopes,
                authority: "read_only_no_execution",
                capability: capability.as_str(),
            },
        ),
        Ok(Exchanged::Rejected(PairingError::RateLimited))
        | Err(OrdinaryPairingError::Pairing(PairingError::RateLimited)) => problem(
            StatusCode::TOO_MANY_REQUESTS,
            "pairing_rate_limited",
            "pairing attempt bound is exhausted",
        ),
        Err(OrdinaryPairingError::Journal(_) | OrdinaryPairingError::Unavailable) => problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "pairing_writer_unavailable",
            "pairing state was not acknowledged because durable exact readback is unavailable",
        ),
        Ok(Exchanged::Rejected(_)) | Err(OrdinaryPairingError::Pairing(_)) => problem(
            StatusCode::UNAUTHORIZED,
            "invalid_pairing_code",
            "pairing code is invalid, expired, revoked, or already consumed",
        ),
    }
}

fn browser_posture_failure(origin: &PairingOrigin, headers: &HeaderMap) -> Option<Response> {
    let supplied_origin = header_text(headers, header::ORIGIN.as_str());
    let host = header_text(headers, header::HOST.as_str());
    if supplied_origin.as_deref() != Some(origin.as_str())
        || supplied_origin
            .as_deref()
            .zip(host.as_deref())
            .is_none_or(|(supplied, host)| !exact_loopback_same_origin(supplied, host))
    {
        return Some(problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "pairing requires the configured exact matching loopback Host and Origin",
        ));
    }
    if header_text(headers, SEC_FETCH_SITE_HEADER).as_deref() != Some("same-origin")
        || header_text(headers, SEC_FETCH_MODE_HEADER).as_deref() != Some("cors")
        || header_text(headers, SEC_FETCH_DEST_HEADER).as_deref() != Some("empty")
    {
        return Some(problem(
            StatusCode::FORBIDDEN,
            "browser_posture_rejected",
            "pairing requires same-origin browser Fetch Metadata",
        ));
    }
    None
}

fn exact_loopback_same_origin(origin: &str, host: &str) -> bool {
    let Ok(uri) = origin.parse::<Uri>() else {
        return false;
    };
    let Some(authority) = uri.authority() else {
        return false;
    };
    let Some(host_ip_or_name) = uri.host() else {
        return false;
    };
    let loopback = host_ip_or_name == "localhost"
        || host_ip_or_name
            .trim_matches(['[', ']'])
            .parse::<IpAddr>()
            .is_ok_and(|address| address.is_loopback());
    uri.scheme_str() == Some("http")
        && uri.path() == "/"
        && uri.query().is_none()
        && loopback
        && authority.as_str() == host
}

fn header_text(headers: &HeaderMap, name: &str) -> Option<String> {
    let mut values = headers.get_all(name).iter();
    let value = values.next()?;
    if values.next().is_some() {
        return None;
    }
    value.to_str().ok().map(str::to_owned)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Problem<'a> {
    contract: &'static str,
    schema_version: u16,
    code: &'a str,
    detail: &'a str,
}

fn problem(status: StatusCode, code: &str, detail: &str) -> Response {
    json_response(
        status,
        &Problem {
            contract: "joshi.core.problem",
            schema_version: 1,
            code,
            detail,
        },
    )
}

fn json_response(status: StatusCode, value: &impl Serialize) -> Response {
    match serde_json::to_vec(value) {
        Ok(bytes) => {
            let mut response = Response::new(axum::body::Body::from(bytes));
            *response.status_mut() = status;
            response.headers_mut().insert(
                header::CONTENT_TYPE,
                HeaderValue::from_static("application/json"),
            );
            response
                .headers_mut()
                .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
            response
        }
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::service::{CoreService, PairingCapability};
    use axum::{body::Body, http::Request};
    use http_body_util::BodyExt as _;
    use joshi_domain::UtcTimestamp;
    use joshi_pairing::pairing_epoch_occurrence_id;
    use joshi_publication::CockpitV2BrowserPresentationClaimV1;
    use joshi_store::{SqliteStore, StoreConfig, StoreMode};
    use std::{path::Path, time::Duration};
    use tower::ServiceExt as _;

    struct FixedEntropy(u8);

    impl Entropy for FixedEntropy {
        fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError> {
            for byte in bytes {
                *byte = self.0;
                self.0 = self.0.wrapping_add(1);
            }
            Ok(())
        }
    }

    struct FixedClock {
        monotonic: u64,
        wall: PairingWallInstant,
    }

    impl PairingClock for FixedClock {
        fn sample(&mut self) -> Result<PairingClockSample, PairingError> {
            self.monotonic += 1;
            Ok(PairingClockSample {
                monotonic_ms: MonotonicMillis::new(self.monotonic),
                observed_at: self.wall,
            })
        }
    }

    struct SequenceClock {
        values: Vec<u64>,
        index: usize,
        wall: PairingWallInstant,
    }

    impl PairingClock for SequenceClock {
        fn sample(&mut self) -> Result<PairingClockSample, PairingError> {
            let value = *self
                .values
                .get(self.index)
                .ok_or(PairingError::InvalidConfig)?;
            self.index += 1;
            Ok(PairingClockSample {
                monotonic_ms: MonotonicMillis::new(value),
                observed_at: self.wall.checked_add_ms(value)?,
            })
        }
    }

    #[derive(Default)]
    struct MemoryJournal {
        entries: Vec<PairingJournalEntry>,
        fail: bool,
        corrupt_readback: bool,
        restart_invalidation: bool,
    }

    impl PairingJournal for Arc<Mutex<MemoryJournal>> {
        fn begin_epoch(
            &mut self,
            origin: &PairingOrigin,
            sample: PairingClockSample,
            _config: PairingConfig,
        ) -> Result<PairingEpochReceipt, PairingJournalError> {
            let restart_invalidation = self
                .lock()
                .map_err(|_| PairingJournalError)?
                .restart_invalidation;
            let epoch = if restart_invalidation { 2 } else { 1 };
            let epoch_occurrence = PairingOccurrence {
                contract: StableString::new(joshi_pairing::PAIRING_OCCURRENCE_CONTRACT).unwrap(),
                schema_version: joshi_pairing::PAIRING_SCHEMA_VERSION,
                occurrence_id: pairing_epoch_occurrence_id(origin, epoch),
                kind: PairingOccurrenceKind::EpochStarted,
                issue_id: None,
                session_id: None,
                predecessor_occurrence_id: None,
                origin: origin.clone(),
                epoch: PairingEpoch::new(epoch).unwrap(),
                at_monotonic_ms: sample.monotonic_ms,
                observed_at: sample.observed_at,
                expires_at: None,
                scopes: Vec::new(),
                rate_window_id: None,
                rate_window_expires_at: None,
                failed_attempt_ordinal: None,
                attempt_window_started_monotonic_ms: None,
                reason: Some(StableString::new("process_start").unwrap()),
                authority: StableString::new("read_only_pairing_exchange").unwrap(),
            };
            let epoch_receipt = test_receipt(&epoch_occurrence, 1);
            let invalidations = if restart_invalidation {
                let occurrence = PairingOccurrence {
                    contract: StableString::new(joshi_pairing::PAIRING_OCCURRENCE_CONTRACT)
                        .unwrap(),
                    schema_version: joshi_pairing::PAIRING_SCHEMA_VERSION,
                    occurrence_id: pairing_occurrence_id(origin, epoch, 1),
                    kind: PairingOccurrenceKind::RestartInvalidated,
                    issue_id: Some(StableString::new("pair-issue-prior").unwrap()),
                    session_id: None,
                    predecessor_occurrence_id: Some(
                        StableString::new("pair-occurrence-prior").unwrap(),
                    ),
                    origin: origin.clone(),
                    epoch: PairingEpoch::new(epoch).unwrap(),
                    at_monotonic_ms: sample.monotonic_ms,
                    observed_at: sample.observed_at,
                    expires_at: None,
                    scopes: vec![PairingScope::CockpitRead],
                    rate_window_id: None,
                    rate_window_expires_at: None,
                    failed_attempt_ordinal: None,
                    attempt_window_started_monotonic_ms: None,
                    reason: Some(StableString::new("process_restart").unwrap()),
                    authority: StableString::new("read_only_pairing_exchange").unwrap(),
                };
                vec![test_receipt(&occurrence, 1)]
            } else {
                Vec::new()
            };
            Ok(PairingEpochReceipt {
                origin: origin.clone(),
                epoch,
                invalidated_issue_count: u32::from(restart_invalidation),
                invalidated_session_count: 0,
                next_ordinal: u64::from(restart_invalidation),
                invalidations,
                rate: PairingRateBootstrap {
                    last_observed_at: sample.observed_at,
                    attempt: PairingRateWindowBootstrap {
                        window_id: None,
                        used: 0,
                        expires_at: None,
                    },
                    issue: PairingRateWindowBootstrap {
                        window_id: None,
                        used: 0,
                        expires_at: None,
                    },
                },
                commit_seq: 1,
                epoch_occurrence: epoch_receipt,
            })
        }

        fn append_atomically(
            &mut self,
            entries: &[PairingJournalEntry],
        ) -> Result<Vec<PairingJournalReceipt>, PairingJournalError> {
            let mut journal = self.lock().map_err(|_| PairingJournalError)?;
            if journal.fail {
                return Err(PairingJournalError);
            }
            journal.entries.extend_from_slice(entries);
            let corrupt_readback = journal.corrupt_readback;
            Ok(entries
                .iter()
                .enumerate()
                .map(|(index, entry)| PairingJournalReceipt {
                    occurrence_id: entry.occurrence_id.clone(),
                    document_sha256: entry.document_sha256.clone(),
                    readback_bytes: if corrupt_readback {
                        b"caller-echo-without-exact-readback".to_vec()
                    } else {
                        entry.canonical_bytes.clone()
                    },
                    commit_seq: u64::try_from(index + 2).unwrap(),
                })
                .collect())
        }
    }

    fn test_receipt(occurrence: &PairingOccurrence, commit_seq: u64) -> PairingJournalReceipt {
        let bytes = occurrence.canonical_bytes().unwrap();
        PairingJournalReceipt {
            occurrence_id: occurrence.occurrence_id.clone(),
            document_sha256: StableString::new(Sha256Digest::of_bytes(&bytes).to_string()).unwrap(),
            readback_bytes: bytes,
            commit_seq,
        }
    }

    fn test_service(journal: Arc<Mutex<MemoryJournal>>) -> OrdinaryPairingService {
        test_service_epoch(journal, 1)
    }

    fn test_service_epoch(
        journal: Arc<Mutex<MemoryJournal>>,
        epoch: u64,
    ) -> OrdinaryPairingService {
        OrdinaryPairingService::from_initialized_parts(
            PairingOrigin::new("http://127.0.0.1:8787").unwrap(),
            PairingConfig::default(),
            epoch,
            Box::new(FixedEntropy(0)),
            Box::new(FixedClock {
                monotonic: 0,
                wall: "2026-08-18T12:00:00.000000Z".parse().unwrap(),
            }),
            Box::new(journal),
        )
        .unwrap()
    }

    fn store(root: &Path) -> SqliteStore {
        let mut store = SqliteStore::open(
            StoreConfig {
                catalog_path: root.join("catalog.sqlite"),
                blob_root: root.join("blobs"),
                export_root: root.join("exports"),
                inline_blob_max_bytes: 1024,
                busy_timeout: Duration::from_secs(1),
                catalog_id: StableString::new("pairing-authorizer-test").unwrap(),
                max_observations_per_batch: 64,
                max_raw_bytes_per_batch: 1024 * 1024,
            },
            StoreMode::SingleWriter,
        )
        .unwrap();
        store
            .migrate(
                "2026-08-18T12:00:00.000000Z"
                    .parse::<UtcTimestamp>()
                    .unwrap(),
            )
            .unwrap();
        store
    }

    fn request(body: String) -> Request<Body> {
        Request::builder()
            .method("POST")
            .uri("/api/v1/pairing/exchange")
            .header("content-type", "application/json")
            .header("host", "127.0.0.1:8787")
            .header("origin", "http://127.0.0.1:8787")
            .header("sec-fetch-site", "same-origin")
            .header("sec-fetch-mode", "cors")
            .header("sec-fetch-dest", "empty")
            .body(Body::from(body))
            .unwrap()
    }

    fn presentation_request(capability: &str, body: Vec<u8>) -> Request<Body> {
        Request::builder()
            .method("POST")
            .uri("/api/v1/cockpit-v2/presentations")
            .header("content-type", "application/json")
            .header("host", "127.0.0.1:8787")
            .header("origin", "http://127.0.0.1:8787")
            .header("sec-fetch-site", "same-origin")
            .header("sec-fetch-mode", "cors")
            .header("sec-fetch-dest", "empty")
            .header("x-joshi-pairing-token", capability)
            .body(Body::from(body))
            .unwrap()
    }

    fn aligned_now() -> UtcTimestamp {
        let nanos = time::OffsetDateTime::now_utc().unix_timestamp_nanos();
        let aligned = nanos.div_euclid(1_000) * 1_000;
        UtcTimestamp::new(time::OffsetDateTime::from_unix_timestamp_nanos(aligned).unwrap())
            .unwrap()
    }

    #[tokio::test]
    async fn issue_and_consume_are_read_back_before_secret_or_capability_returns() {
        let journal = Arc::new(Mutex::new(MemoryJournal::default()));
        let service = Arc::new(test_service(journal.clone()));
        let issued = service.issue_code(vec![PairingScope::CockpitRead]).unwrap();
        assert_eq!(
            issued.code.as_str(),
            "JOSHI-000G-40R4-0M30-E209-185G-R38E-1W81-24GK"
        );
        assert_eq!(journal.lock().unwrap().entries.len(), 1);
        let body = include_str!("../../../fixtures/pairing/exchange_request_v1.json")
            .trim_end()
            .to_owned();
        let response = ordinary_pairing_router(service)
            .oneshot(request(body))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(
            bytes.as_ref(),
            include_bytes!("../../../fixtures/pairing/exchange_response_v1.json")
                .strip_suffix(b"\n")
                .unwrap()
        );
        let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(value["origin"], "http://127.0.0.1:8787");
        assert_eq!(value["epoch"], "1");
        assert!(value["capability"].as_str().unwrap().starts_with("jpc1_"));
        let journal = journal.lock().unwrap();
        assert_eq!(journal.entries.len(), 2);
        assert!(!journal.entries.iter().any(|entry| {
            let text = String::from_utf8_lossy(&entry.canonical_bytes);
            text.contains(issued.code.as_str()) || text.contains("jpc1_")
        }));
    }

    #[tokio::test]
    async fn exact_origin_fetch_metadata_and_canonical_code_are_required() {
        let service = Arc::new(test_service(Arc::new(Mutex::new(MemoryJournal::default()))));
        let issued = service.issue_code(vec![PairingScope::CockpitRead]).unwrap();
        let body = format!(
            "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
            issued.code.as_str()
        );
        let mut wrong_host = request(body.clone());
        wrong_host
            .headers_mut()
            .insert("host", HeaderValue::from_static("localhost:8787"));
        assert_eq!(
            ordinary_pairing_router(service.clone())
                .oneshot(wrong_host)
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        let mut cross_site = request(body.clone());
        cross_site
            .headers_mut()
            .insert("sec-fetch-site", HeaderValue::from_static("cross-site"));
        assert_eq!(
            ordinary_pairing_router(service.clone())
                .oneshot(cross_site)
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        let mut duplicate_origin = request(body.clone());
        duplicate_origin.headers_mut().append(
            header::ORIGIN,
            HeaderValue::from_static("http://127.0.0.1:8787"),
        );
        assert_eq!(
            ordinary_pairing_router(service.clone())
                .oneshot(duplicate_origin)
                .await
                .unwrap()
                .status(),
            StatusCode::FORBIDDEN
        );
        let obsolete = request(
            r#"{"contract":"joshi.pairing.exchange","schemaVersion":1,"oneTimeCode":"EMBER-482901"}"#.to_owned(),
        );
        assert_eq!(
            ordinary_pairing_router(service)
                .oneshot(obsolete)
                .await
                .unwrap()
                .status(),
            StatusCode::UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn journal_failure_never_returns_capability_and_consumes_code_fail_closed() {
        let journal = Arc::new(Mutex::new(MemoryJournal::default()));
        let service = Arc::new(test_service(journal.clone()));
        let issued = service.issue_code(vec![PairingScope::CockpitRead]).unwrap();
        journal.lock().unwrap().fail = true;
        let body = format!(
            "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
            issued.code.as_str()
        );
        let first = ordinary_pairing_router(service.clone())
            .oneshot(request(body.clone()))
            .await
            .unwrap();
        assert_eq!(first.status(), StatusCode::SERVICE_UNAVAILABLE);
        let text = String::from_utf8(
            first
                .into_body()
                .collect()
                .await
                .unwrap()
                .to_bytes()
                .to_vec(),
        )
        .unwrap();
        assert!(!text.contains("jpc1_"));
        journal.lock().unwrap().fail = false;
        let retry = ordinary_pairing_router(service)
            .oneshot(request(body))
            .await
            .unwrap();
        assert_eq!(retry.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn false_readback_receipt_never_releases_an_issued_code() {
        let journal = Arc::new(Mutex::new(MemoryJournal {
            corrupt_readback: true,
            ..MemoryJournal::default()
        }));
        let service = Arc::new(test_service(journal.clone()));
        assert!(matches!(
            service.issue_code(vec![PairingScope::CockpitRead]),
            Err(OrdinaryPairingError::Journal(_))
        ));
        journal.lock().unwrap().corrupt_readback = false;
        let body = include_str!("../../../fixtures/pairing/exchange_request_v1.json")
            .trim_end()
            .to_owned();
        let response = ordinary_pairing_router(service)
            .oneshot(request(body))
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[test]
    fn sealed_production_seeds_runtime_ordinal_after_exact_restart_invalidations() {
        let journal = Arc::new(Mutex::new(MemoryJournal {
            restart_invalidation: true,
            ..MemoryJournal::default()
        }));
        let origin = PairingOrigin::new("http://127.0.0.1:8787").unwrap();
        let service = OrdinaryPairingService::initialize_durable(
            origin.clone(),
            PairingConfig::default(),
            DurablePairingJournal::from_test(Box::new(journal.clone())),
            Box::new(FixedEntropy(0)),
            Box::new(FixedClock {
                monotonic: 0,
                wall: "2026-08-18T12:00:00.000000Z".parse().unwrap(),
            }),
        )
        .unwrap();
        let issued = service.issue_code(vec![PairingScope::CockpitRead]).unwrap();
        assert_eq!(
            issued.metadata.occurrence_id,
            pairing_occurrence_id(&origin, 2, 2)
        );
        let persisted = &journal.lock().unwrap().entries;
        assert_eq!(persisted.len(), 1);
        assert_eq!(persisted[0].occurrence_id, issued.metadata.occurrence_id);
    }

    #[tokio::test]
    #[allow(clippy::too_many_lines)]
    async fn exchange_authorizes_scoped_core_routes_and_restart_refuses_the_old_capability() {
        let root = tempfile::tempdir().unwrap();
        let origin = PairingOrigin::new("http://127.0.0.1:8787").unwrap();
        let legacy = PairingCapability::from_hex(&"c".repeat(64)).unwrap();
        let (core, ordinary) = CoreService::with_sqlite_pairing(
            store(root.path()),
            None,
            legacy,
            origin.clone(),
            PairingConfig::default(),
        )
        .unwrap();
        let issued = ordinary
            .issue_code(vec![
                PairingScope::CockpitRead,
                PairingScope::OperatorEvidenceWrite,
            ])
            .unwrap();
        let app = core.router();
        let exchange_body = format!(
            "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
            issued.code.as_str()
        );
        let response = app.clone().oneshot(request(exchange_body)).await.unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let response_bytes = response.into_body().collect().await.unwrap().to_bytes();
        let response: serde_json::Value = serde_json::from_slice(&response_bytes).unwrap();
        let capability = response["capability"].as_str().unwrap();
        let session_id = response["sessionId"].as_str().unwrap();
        assert!(capability.starts_with("jpc1_"));
        assert!(matches!(
            ordinary.authorize(
                capability,
                "http://127.0.0.1:8787",
                PairingScope::PresentationEvidenceWrite,
            ),
            Err(OrdinaryPairingError::Pairing(PairingError::ScopeDenied))
        ));

        let read = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                "/api/v1/session/launch",
                capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(read.status(), StatusCode::SERVICE_UNAVAILABLE);

        let write = app
            .clone()
            .oneshot(authorized_request(
                "POST",
                "/api/v1/operator/commands",
                capability,
                Body::from(include_bytes!("../fixtures/operator_readiness_v1.json").as_slice()),
            ))
            .await
            .unwrap();
        assert_eq!(write.status(), StatusCode::UNPROCESSABLE_ENTITY);

        let revoked = ordinary
            .revoke_session(session_id, "operator_revoked")
            .unwrap();
        assert_eq!(revoked.kind, PairingOccurrenceKind::Revoked);
        let revoked_refusal = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                "/api/v1/session/launch",
                capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(revoked_refusal.status(), StatusCode::UNAUTHORIZED);

        let live_issue = ordinary
            .issue_code(vec![PairingScope::CockpitRead])
            .unwrap();
        let live_response = app
            .oneshot(request(format!(
                "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
                live_issue.code.as_str()
            )))
            .await
            .unwrap();
        assert_eq!(live_response.status(), StatusCode::OK);
        let live_response = live_response
            .into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes();
        let live_response: serde_json::Value = serde_json::from_slice(&live_response).unwrap();
        let live_capability = live_response["capability"].as_str().unwrap().to_owned();

        drop(ordinary);
        let (restarted_core, restarted) = CoreService::with_sqlite_pairing(
            store(root.path()),
            None,
            PairingCapability::from_hex(&"c".repeat(64)).unwrap(),
            origin.clone(),
            PairingConfig::default(),
        )
        .unwrap();
        let post_restart_issue = restarted
            .issue_code(vec![PairingScope::CockpitRead])
            .unwrap();
        assert_eq!(
            post_restart_issue.metadata.occurrence_id,
            pairing_occurrence_id(&origin, 2, 2)
        );
        let restarted_app = restarted_core.router();
        let refused = restarted_app
            .oneshot(authorized_request(
                "GET",
                "/api/v1/session/launch",
                &live_capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(refused.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    #[allow(clippy::too_many_lines)]
    async fn paired_read_opens_exact_headed_g0_publication_then_revoke_and_restart_refuse() {
        let root = tempfile::tempdir().unwrap();
        let report = crate::wave5_g0::run_wave5_g0_source_publication(root.path()).unwrap();
        let publication_id =
            joshi_publication::CockpitPublicationId::new(report.publication_id).unwrap();
        let config = crate::wave5_g0::offline_fixture_store_config(root.path()).unwrap();
        let store = SqliteStore::open(config.clone(), StoreMode::SingleWriter).unwrap();
        let publication = store
            .load_cockpit_v2_publication_v1(&publication_id)
            .unwrap()
            .unwrap();
        let head = store
            .load_cockpit_v2_head_v1(&publication_id)
            .unwrap()
            .unwrap();
        drop(store);

        let legacy = PairingCapability::from_hex(&"d".repeat(64)).unwrap();
        let default_store = SqliteStore::open(config.clone(), StoreMode::SingleWriter).unwrap();
        let default_app = CoreService::new(default_store, None, legacy).router();
        let unmounted = default_app
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/v1/cockpit-v2/publications/{}",
                        publication_id.as_str()
                    ))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(unmounted.status(), StatusCode::NOT_FOUND);

        let origin = PairingOrigin::new("http://127.0.0.1:8787").unwrap();
        let store = SqliteStore::open(config.clone(), StoreMode::SingleWriter).unwrap();
        let (core, ordinary) = CoreService::with_sqlite_pairing(
            store,
            None,
            PairingCapability::from_hex(&"d".repeat(64)).unwrap(),
            origin.clone(),
            PairingConfig::default(),
        )
        .unwrap();
        let wrong_scope = ordinary
            .issue_code(vec![PairingScope::OperatorEvidenceWrite])
            .unwrap();
        let app = core.router();
        let wrong_scope_exchange = app
            .clone()
            .oneshot(request(format!(
                "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
                wrong_scope.code.as_str()
            )))
            .await
            .unwrap();
        assert_eq!(wrong_scope_exchange.status(), StatusCode::OK);
        let wrong_scope_exchange: serde_json::Value = serde_json::from_slice(
            &wrong_scope_exchange
                .into_body()
                .collect()
                .await
                .unwrap()
                .to_bytes(),
        )
        .unwrap();
        let wrong_scope_capability = wrong_scope_exchange["capability"].as_str().unwrap();
        let route = format!(
            "/api/v1/cockpit-v2/publications/{}",
            publication_id.as_str()
        );
        let scope_refused = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                &route,
                wrong_scope_capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(scope_refused.status(), StatusCode::UNAUTHORIZED);

        let issued = ordinary
            .issue_code(vec![PairingScope::CockpitRead])
            .unwrap();
        let exchange = app
            .clone()
            .oneshot(request(format!(
                "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
                issued.code.as_str()
            )))
            .await
            .unwrap();
        assert_eq!(exchange.status(), StatusCode::OK);
        let exchange: serde_json::Value =
            serde_json::from_slice(&exchange.into_body().collect().await.unwrap().to_bytes())
                .unwrap();
        let capability = exchange["capability"].as_str().unwrap().to_owned();
        let session_id = exchange["sessionId"].as_str().unwrap().to_owned();
        let mut wrong_origin_request = authorized_request(
            "GET",
            "/api/v1/cockpit-v2/publications",
            &capability,
            Body::empty(),
        );
        wrong_origin_request.headers_mut().insert(
            header::ORIGIN,
            HeaderValue::from_static("http://localhost:8787"),
        );
        let wrong_origin = app.clone().oneshot(wrong_origin_request).await.unwrap();
        assert_eq!(wrong_origin.status(), StatusCode::FORBIDDEN);
        let index = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                "/api/v1/cockpit-v2/publications",
                &capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(index.status(), StatusCode::OK);
        assert_eq!(
            index.headers().get(header::CACHE_CONTROL).unwrap(),
            "no-store"
        );
        let index: serde_json::Value =
            serde_json::from_slice(&index.into_body().collect().await.unwrap().to_bytes()).unwrap();
        assert_eq!(index["contract"], "joshi.core.cockpit_v2_index");
        assert_eq!(index["authority"], "read_only_no_execution");
        assert_eq!(index["items"].as_array().unwrap().len(), 1);
        assert_eq!(index["items"][0]["publicationId"], publication_id.as_str());
        assert_eq!(
            index["items"][0]["publicationDigest"],
            publication.publication.publication_digest.as_str()
        );
        assert_eq!(
            index["items"][0]["publicationBytesDigest"],
            publication.publication_bytes_digest.as_str()
        );
        assert_eq!(
            index["items"][0]["headDigest"],
            head.head.head_digest.as_str()
        );
        assert_eq!(
            index["items"][0]["headBytesDigest"],
            head.head_digest.as_str()
        );
        assert_eq!(index["items"][0]["eligibleCount"], "2");
        assert_eq!(index["items"][0]["factCount"], "2");
        assert_eq!(index["items"][0]["gapCount"], "0");
        assert_eq!(index["items"][0]["ceiling"], "unverified_semantic");
        let opened = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                &route,
                &capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(opened.status(), StatusCode::OK);
        assert_eq!(
            opened.headers().get(header::CACHE_CONTROL).unwrap(),
            "no-store"
        );
        let opened = opened.into_body().collect().await.unwrap().to_bytes();
        let expected = format!(
            "{{\"authority\":\"read_only_no_execution\",\"contract\":\"joshi.core.cockpit_v2_open\",\"head\":{},\"headBytesDigest\":\"{}\",\"headCommitSeq\":\"{}\",\"publication\":{},\"publicationBytesDigest\":\"{}\",\"publicationCommitSeq\":\"{}\",\"schemaVersion\":1,\"sourceOccurrenceId\":{}}}",
            String::from_utf8(head.head_bytes).unwrap(),
            head.head_digest.as_str(),
            head.commit_seq.get(),
            String::from_utf8(publication.publication_bytes).unwrap(),
            publication.publication_bytes_digest.as_str(),
            publication.commit_seq.get(),
            serde_json::to_string(publication.source_occurrence_id.as_str()).unwrap(),
        );
        assert_eq!(opened.as_ref(), expected.as_bytes());

        ordinary
            .revoke_session(&session_id, "operator_revoked")
            .unwrap();
        let revoked = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                &route,
                &capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(revoked.status(), StatusCode::UNAUTHORIZED);

        let live_issue = ordinary
            .issue_code(vec![PairingScope::CockpitRead])
            .unwrap();
        let live_exchange = app
            .oneshot(request(format!(
                "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
                live_issue.code.as_str()
            )))
            .await
            .unwrap();
        let live_exchange: serde_json::Value = serde_json::from_slice(
            &live_exchange
                .into_body()
                .collect()
                .await
                .unwrap()
                .to_bytes(),
        )
        .unwrap();
        let live_capability = live_exchange["capability"].as_str().unwrap().to_owned();
        drop(ordinary);

        let restarted_store = SqliteStore::open(config, StoreMode::SingleWriter).unwrap();
        let (restarted_core, _restarted) = CoreService::with_sqlite_pairing(
            restarted_store,
            None,
            PairingCapability::from_hex(&"d".repeat(64)).unwrap(),
            origin,
            PairingConfig::default(),
        )
        .unwrap();
        let refused = restarted_core
            .router()
            .oneshot(authorized_request(
                "GET",
                &route,
                &live_capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(refused.status(), StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    #[allow(clippy::too_many_lines)]
    async fn paired_browser_presentation_is_exact_idempotent_and_store_reopenable() {
        let root = tempfile::tempdir().unwrap();
        let report = crate::wave5_g0::run_wave5_g0_source_publication(root.path()).unwrap();
        let publication_id =
            joshi_publication::CockpitPublicationId::new(report.publication_id).unwrap();
        let config = crate::wave5_g0::offline_fixture_store_config(root.path()).unwrap();
        let mut store = SqliteStore::open(config.clone(), StoreMode::SingleWriter).unwrap();
        let migration = store.migrate(aligned_now()).unwrap();
        assert_eq!(migration.runtime.user_version, 23);
        let publication = store
            .load_cockpit_v2_publication_v1(&publication_id)
            .unwrap()
            .unwrap();
        let head = store
            .load_cockpit_v2_head_v1(&publication_id)
            .unwrap()
            .unwrap();
        drop(store);

        let origin = PairingOrigin::new("http://127.0.0.1:8787").unwrap();
        let (core, ordinary) = CoreService::with_sqlite_pairing(
            SqliteStore::open(config.clone(), StoreMode::SingleWriter).unwrap(),
            None,
            PairingCapability::from_hex(&"e".repeat(64)).unwrap(),
            origin,
            PairingConfig::default(),
        )
        .unwrap();
        let issued = ordinary
            .issue_code(vec![
                PairingScope::CockpitRead,
                PairingScope::PresentationEvidenceWrite,
            ])
            .unwrap();
        let app = core.router();
        let exchanged = app
            .clone()
            .oneshot(request(format!(
                "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
                issued.code.as_str()
            )))
            .await
            .unwrap();
        assert_eq!(exchanged.status(), StatusCode::OK);
        let exchanged: serde_json::Value =
            serde_json::from_slice(&exchanged.into_body().collect().await.unwrap().to_bytes())
                .unwrap();
        let capability = exchanged["capability"].as_str().unwrap().to_owned();
        let session_id = exchanged["sessionId"].as_str().unwrap().to_owned();

        let opened = app
            .clone()
            .oneshot(authorized_request(
                "GET",
                &format!(
                    "/api/v1/cockpit-v2/publications/{}",
                    publication_id.as_str()
                ),
                &capability,
                Body::empty(),
            ))
            .await
            .unwrap();
        assert_eq!(opened.status(), StatusCode::OK);

        let mut claim: CockpitV2BrowserPresentationClaimV1 =
            serde_json::from_value(serde_json::json!({
                "contract": "joshi.cockpit.v2.browser_presentation_claim",
                "schemaVersion": 1,
                "idempotencyKey": "browser-presentation:paired-browser-page-1:1",
                "clientPresentationId": "paired-browser-presentation-1",
                "browserPageId": "paired-browser-page-1",
                "presentationSeq": "1",
                "publication": {
                    "publicationId": publication_id.as_str(),
                    "publicationDigest": publication.publication.publication_digest.as_str(),
                    "publicationBytesDigest": publication.publication_bytes_digest.as_str(),
                    "publicationCommitSeq": publication.commit_seq.get().to_string(),
                },
                "head": {
                    "headDigest": head.head.head_digest.as_str(),
                    "headBytesDigest": head.head_digest.as_str(),
                    "headCommitSeq": head.commit_seq.get().to_string(),
                },
                "sourceOccurrenceId": publication.source_occurrence_id.as_str(),
                "renderedSubjects": publication.publication.manifest.rendered_subjects,
                "renderedSubjectCount": publication
                    .publication
                    .manifest
                    .rendered_subjects
                    .len()
                    .to_string(),
                "mountedAt": aligned_now().to_string(),
                "clientClockId": "paired-browser-page-1-performance",
                "monotonicNs": "1000",
                "viewport": {
                    "widthCssPx": "1280",
                    "heightCssPx": "800",
                    "devicePixelRatioMilli": "2000",
                },
                "documentVisibility": "visible",
                "documentHasFocus": true,
                "authority": "read_only_no_execution",
                "ceiling": "browser_reported_not_pixel_verified",
                "claimDigest": format!("sha256:{}", "0".repeat(64)),
            }))
            .unwrap();
        claim.claim_digest = claim.computed_digest().unwrap();
        let claim_bytes = claim.canonical_bytes().unwrap();

        let mut prepair_mount = claim.clone();
        prepair_mount.idempotency_key =
            StableString::new("browser-presentation:paired-browser-page-1:2").unwrap();
        prepair_mount.client_presentation_id =
            StableString::new("paired-browser-presentation-prepair").unwrap();
        prepair_mount.presentation_seq = joshi_domain::WireU64::new(2);
        prepair_mount.mounted_at = publication.publication.manifest.cutoff.knowledge_at;
        prepair_mount.claim_digest = prepair_mount.computed_digest().unwrap();
        let prepair_refused = app
            .clone()
            .oneshot(presentation_request(
                &capability,
                prepair_mount.canonical_bytes().unwrap(),
            ))
            .await
            .unwrap();
        assert_eq!(prepair_refused.status(), StatusCode::UNPROCESSABLE_ENTITY);

        let accepted = app
            .clone()
            .oneshot(presentation_request(&capability, claim_bytes.clone()))
            .await
            .unwrap();
        assert_eq!(accepted.status(), StatusCode::OK);
        let accepted: serde_json::Value =
            serde_json::from_slice(&accepted.into_body().collect().await.unwrap().to_bytes())
                .unwrap();
        assert_eq!(
            accepted["contract"],
            "joshi.core.cockpit_v2_browser_presentation_receipt"
        );
        assert_eq!(accepted["catalogSchema"], "joshi.sqlite.v23");
        assert_eq!(accepted["status"], "accepted");
        assert_eq!(
            accepted["ceiling"],
            "durable_browser_report_only_not_pixel_verified"
        );
        assert_eq!(accepted["claimDigest"], claim.claim_digest.as_str());
        assert_eq!(accepted["pairingSessionId"], session_id);

        let retry = app
            .clone()
            .oneshot(presentation_request(&capability, claim_bytes.clone()))
            .await
            .unwrap();
        assert_eq!(retry.status(), StatusCode::OK);
        let retry: serde_json::Value =
            serde_json::from_slice(&retry.into_body().collect().await.unwrap().to_bytes()).unwrap();
        assert_eq!(retry["status"], "idempotent");
        assert_eq!(retry["storeCommitSeq"], accepted["storeCommitSeq"]);

        let mut conflicting = claim.clone();
        conflicting.document_has_focus = false;
        conflicting.claim_digest = conflicting.computed_digest().unwrap();
        let conflict = app
            .clone()
            .oneshot(presentation_request(
                &capability,
                conflicting.canonical_bytes().unwrap(),
            ))
            .await
            .unwrap();
        assert_eq!(conflict.status(), StatusCode::CONFLICT);

        ordinary
            .revoke_session(&session_id, "operator_revoked")
            .unwrap();
        let revoked_retry = app
            .clone()
            .oneshot(presentation_request(&capability, claim_bytes.clone()))
            .await
            .unwrap();
        assert_eq!(revoked_retry.status(), StatusCode::UNAUTHORIZED);
        drop(app);
        drop(ordinary);

        let reopened = SqliteStore::open(config, StoreMode::ReadOnly)
            .unwrap()
            .load_cockpit_v2_browser_presentation_v1(&claim.client_presentation_id)
            .unwrap()
            .unwrap();
        assert_eq!(reopened.claim, claim);
        assert_eq!(reopened.claim_bytes, claim_bytes);
        assert_eq!(reopened.pairing_session_id.as_str(), session_id);
        assert!(reopened.commit_seq.get() > head.commit_seq.get());
    }

    #[tokio::test]
    async fn authorizer_persists_expiry_from_its_single_boundary_sample_before_refusal() {
        let journal = Arc::new(Mutex::new(MemoryJournal::default()));
        let origin = PairingOrigin::new("http://127.0.0.1:8787").unwrap();
        let config = PairingConfig {
            session_ttl_ms: 60_000,
            ..PairingConfig::default()
        };
        let service = Arc::new(
            OrdinaryPairingService::from_initialized_parts(
                origin.clone(),
                config,
                1,
                Box::new(FixedEntropy(0)),
                Box::new(SequenceClock {
                    values: vec![1, 2, 60_002],
                    index: 0,
                    wall: "2026-08-18T12:00:00.000000Z".parse().unwrap(),
                }),
                Box::new(journal.clone()),
            )
            .unwrap(),
        );
        let issued = service.issue_code(vec![PairingScope::CockpitRead]).unwrap();
        let body = format!(
            "{{\"contract\":\"joshi.pairing.exchange\",\"schemaVersion\":1,\"oneTimeCode\":\"{}\"}}",
            issued.code.as_str()
        );
        let response = ordinary_pairing_router(service.clone())
            .oneshot(request(body))
            .await
            .unwrap();
        let response = response.into_body().collect().await.unwrap().to_bytes();
        let response: serde_json::Value = serde_json::from_slice(&response).unwrap();
        let capability = response["capability"].as_str().unwrap();
        assert!(matches!(
            service.authorize(capability, origin.as_str(), PairingScope::CockpitRead),
            Err(OrdinaryPairingError::Pairing(PairingError::InvalidSession))
        ));
        let entries = &journal.lock().unwrap().entries;
        assert_eq!(entries.len(), 3);
        let expired = parse_pairing_occurrence(&entries[2].canonical_bytes).unwrap();
        assert_eq!(expired.kind, PairingOccurrenceKind::Expired);
    }

    #[test]
    fn sqlite_adapter_readback_persists_boundary_expiry_before_reopen() {
        let root = tempfile::tempdir().unwrap();
        let origin = PairingOrigin::new("http://127.0.0.1:8787").unwrap();
        let now = time::OffsetDateTime::now_utc();
        let base = (now - time::Duration::minutes(2))
            .replace_nanosecond(((now - time::Duration::minutes(2)).nanosecond() / 1_000) * 1_000)
            .unwrap();
        let base = PairingWallInstant::new(UtcTimestamp::new(base).unwrap());
        let service = OrdinaryPairingService::initialize_durable(
            origin.clone(),
            PairingConfig {
                session_ttl_ms: 60_000,
                ..PairingConfig::default()
            },
            DurablePairingJournal::from_sqlite(store(root.path())).unwrap(),
            Box::new(FixedEntropy(0)),
            Box::new(SequenceClock {
                values: vec![0, 1, 2, 60_002],
                index: 0,
                wall: base,
            }),
        )
        .unwrap();
        let issued = service.issue_code(vec![PairingScope::CockpitRead]).unwrap();
        let Exchanged::Session {
            capability,
            descriptor: _,
        } = service.exchange(issued.code.as_str()).unwrap()
        else {
            panic!("valid code was rejected")
        };
        assert!(matches!(
            service.authorize(
                capability.as_str(),
                origin.as_str(),
                PairingScope::CockpitRead,
            ),
            Err(OrdinaryPairingError::Pairing(PairingError::InvalidSession))
        ));
        drop(service);

        let reopened = store(root.path());
        let expired_id = pairing_occurrence_id(&origin, 1, 3);
        let expired = reopened
            .load_pairing_occurrence_v1(&expired_id)
            .unwrap()
            .expect("expiry occurrence survives reopen");
        assert_eq!(expired.occurrence.kind, PairingOccurrenceKind::Expired);
        assert_eq!(expired.occurrence.occurrence_id, expired_id);
        for ordinal in 1..=3 {
            let stored = reopened
                .load_pairing_occurrence_v1(&pairing_occurrence_id(&origin, 1, ordinal))
                .unwrap()
                .expect("complete session lineage survives reopen");
            let text = String::from_utf8(stored.document_bytes).unwrap();
            assert!(!text.contains(issued.code.as_str()));
            assert!(!text.contains(capability.as_str()));
            assert!(!text.contains("jpc1_"));
        }
    }

    fn authorized_request(method: &str, uri: &str, capability: &str, body: Body) -> Request<Body> {
        let mut builder = Request::builder()
            .method(method)
            .uri(uri)
            .header("host", "127.0.0.1:8787")
            .header("sec-fetch-site", "same-origin")
            .header("sec-fetch-mode", "cors")
            .header("sec-fetch-dest", "empty")
            .header("x-joshi-pairing-token", capability);
        if method == "POST" {
            builder = builder
                .header("origin", "http://127.0.0.1:8787")
                .header("content-type", "application/json");
        }
        builder.body(body).unwrap()
    }
}
