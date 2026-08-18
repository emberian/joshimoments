use std::collections::BTreeMap;

use joshi_domain::{StableString, UtcTimestamp};
use serde::{Deserialize, Serialize};

use crate::{ScopeInput, ScopeTarget};

/// One bounded lease over an already-versioned public-key input.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ScopeLease {
    pub lease_id: StableString,
    pub input: ScopeInput,
    pub opened_at: UtcTimestamp,
    pub expires_at: UtcTimestamp,
    pub reason_input_ids: Vec<StableString>,
}

/// Active lease and its exact target, retained separately from acquisition state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActiveLease {
    pub lease_id: StableString,
    pub scope_id: StableString,
    pub target: ScopeTarget,
    pub budget: crate::ReadBudget,
    pub expires_at: UtcTimestamp,
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum LeaseError {
    #[error("lease expiration must be later than opening")]
    InvalidInterval,
    #[error("scope input cannot contain zero public keys")]
    EmptyScope,
    #[error("mint cohort exceeds the lease's wallet budget")]
    TooManyWallets,
    #[error("lease identity was reused for different contents")]
    IdentityConflict,
    #[error("scope input was not available when the lease opened")]
    FutureKnownInput,
    #[error("scope input request time must not exceed its availability time")]
    InvalidInputClocks,
    #[error("candidate/cohort availability exceeds scope-input availability")]
    FutureKnownCandidate,
    #[error("candidate valid-time interval is invalid")]
    InvalidCandidateInterval,
}

/// Idempotent lease registry. Expiration removes acquisition desire, not historical evidence.
#[derive(Clone, Debug, Default)]
pub struct LeaseBook {
    leases: BTreeMap<StableString, ScopeLease>,
}

impl LeaseBook {
    /// Apply one exact lease or accept its idempotent replay.
    ///
    /// # Errors
    ///
    /// Rejects invalid intervals, empty targets, excess public keys, and identity conflicts.
    pub fn apply(&mut self, lease: ScopeLease) -> Result<(), LeaseError> {
        if lease.expires_at <= lease.opened_at {
            return Err(LeaseError::InvalidInterval);
        }
        if lease.input.requested_at > lease.input.available_at {
            return Err(LeaseError::InvalidInputClocks);
        }
        if lease.input.available_at > lease.opened_at {
            return Err(LeaseError::FutureKnownInput);
        }
        validate_target_knowledge(&lease)?;
        let keys = lease.input.target.public_keys();
        if keys.is_empty() {
            return Err(LeaseError::EmptyScope);
        }
        if u64::try_from(keys.len()).unwrap_or(u64::MAX) > lease.input.budget.max_public_keys.get()
        {
            return Err(LeaseError::TooManyWallets);
        }
        if let Some(current) = self.leases.get(&lease.lease_id) {
            return if current == &lease {
                Ok(())
            } else {
                Err(LeaseError::IdentityConflict)
            };
        }
        self.leases.insert(lease.lease_id.clone(), lease);
        Ok(())
    }

    /// Return leases active at the supplied bitemporal availability cutoff.
    #[must_use]
    pub fn active_at(&self, at: UtcTimestamp) -> Vec<ActiveLease> {
        self.leases
            .values()
            .filter(|lease| {
                lease.input.available_at <= at && lease.opened_at <= at && at < lease.expires_at
            })
            .map(|lease| ActiveLease {
                lease_id: lease.lease_id.clone(),
                scope_id: lease.input.scope_id.clone(),
                target: lease.input.target.clone(),
                budget: lease.input.budget.clone(),
                expires_at: lease.expires_at,
            })
            .collect()
    }

    /// Remove expired acquisition desire and return the affected lease identities.
    pub fn expire_at(&mut self, at: UtcTimestamp) -> Vec<StableString> {
        let expired: Vec<_> = self
            .leases
            .iter()
            .filter(|(_, lease)| lease.expires_at <= at)
            .map(|(identity, _)| identity.clone())
            .collect();
        for identity in &expired {
            self.leases.remove(identity);
        }
        expired
    }
}

fn validate_target_knowledge(lease: &ScopeLease) -> Result<(), LeaseError> {
    let candidates: Vec<_> = match &lease.input.target {
        ScopeTarget::Wallet { candidate } => vec![candidate],
        ScopeTarget::MintCohort { cohort } => {
            if cohort.available_at > lease.input.available_at {
                return Err(LeaseError::FutureKnownCandidate);
            }
            cohort
                .participants
                .iter()
                .map(|participant| &participant.wallet)
                .collect()
        }
    };
    for candidate in candidates {
        if candidate.available_at > lease.input.available_at {
            return Err(LeaseError::FutureKnownCandidate);
        }
        if candidate
            .valid_to
            .is_some_and(|valid_to| candidate.valid_from.is_some_and(|from| valid_to <= from))
        {
            return Err(LeaseError::InvalidCandidateInterval);
        }
        if candidate
            .valid_from
            .is_some_and(|from| from > lease.opened_at)
            || candidate.valid_to.is_some_and(|to| lease.opened_at >= to)
        {
            return Err(LeaseError::InvalidCandidateInterval);
        }
    }
    Ok(())
}
