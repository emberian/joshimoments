use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::frame::UnixMillis;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseKind {
    MintTrades,
    AccountTrades,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct LeaseKey {
    pub kind: LeaseKind,
    /// A mint for `mint_trades`; a wallet for `account_trades`.
    pub address: String,
}

impl LeaseKey {
    /// Create a typed hot-scope key from a Solana mint or wallet address.
    ///
    /// # Errors
    ///
    /// Returns [`ScopeError::InvalidAddress`] unless `address` is base58 for exactly 32 bytes.
    pub fn new(kind: LeaseKind, address: impl Into<String>) -> Result<Self, ScopeError> {
        let address = address.into();
        let bytes = bs58::decode(&address)
            .into_vec()
            .map_err(|_| ScopeError::InvalidAddress(address.clone()))?;
        if bytes.len() != 32 {
            return Err(ScopeError::InvalidAddress(address));
        }
        Ok(Self { kind, address })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct HotLease {
    pub lease_id: String,
    pub key: LeaseKey,
    pub opened_at: UnixMillis,
    pub expires_at: UnixMillis,
    pub reason: String,
}

impl HotLease {
    /// Validate the lease identity and lifetime.
    ///
    /// # Errors
    ///
    /// Returns an error for an empty identity or a non-positive interval.
    pub fn validate(&self) -> Result<(), ScopeError> {
        if self.lease_id.trim().is_empty() {
            return Err(ScopeError::EmptyLeaseId);
        }
        if self.expires_at <= self.opened_at {
            return Err(ScopeError::InvalidInterval);
        }
        Ok(())
    }
}

#[derive(Error, Debug, Eq, PartialEq)]
pub enum ScopeError {
    #[error("not a 32-byte base58 Solana address: {0}")]
    InvalidAddress(String),
    #[error("lease id cannot be empty")]
    EmptyLeaseId,
    #[error("lease expiration must be later than its opening")]
    InvalidInterval,
    #[error("hot-scope capacity exceeded")]
    CapacityExceeded,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ScopeDelta {
    pub subscribe: BTreeSet<LeaseKey>,
    pub unsubscribe: BTreeSet<LeaseKey>,
}

#[derive(Clone, Debug)]
pub struct ScopeBook {
    max_keys: usize,
    leases: BTreeMap<LeaseKey, BTreeMap<String, HotLease>>,
    applied: BTreeSet<LeaseKey>,
}

impl ScopeBook {
    /// Construct a scope book with an explicit unique-key ceiling.
    ///
    /// # Errors
    ///
    /// Returns [`ScopeError::CapacityExceeded`] when `max_keys` is zero.
    pub fn new(max_keys: usize) -> Result<Self, ScopeError> {
        if max_keys == 0 {
            return Err(ScopeError::CapacityExceeded);
        }
        Ok(Self {
            max_keys,
            leases: BTreeMap::new(),
            applied: BTreeSet::new(),
        })
    }

    /// Insert or replace one reason-specific lease.
    ///
    /// # Errors
    ///
    /// Returns a validation error or [`ScopeError::CapacityExceeded`] when a new unique key would
    /// cross the configured bound.
    pub fn upsert(&mut self, lease: HotLease) -> Result<(), ScopeError> {
        lease.validate()?;
        let is_new_key = !self.leases.contains_key(&lease.key);
        if is_new_key && self.leases.len() >= self.max_keys {
            return Err(ScopeError::CapacityExceeded);
        }
        self.leases
            .entry(lease.key.clone())
            .or_default()
            .insert(lease.lease_id.clone(), lease);
        Ok(())
    }

    pub fn release(&mut self, lease_id: &str) -> bool {
        let mut found = false;
        self.leases.retain(|_, leases| {
            found |= leases.remove(lease_id).is_some();
            !leases.is_empty()
        });
        found
    }

    pub fn expire(&mut self, now: UnixMillis) -> Vec<HotLease> {
        let mut expired = Vec::new();
        self.leases.retain(|_, leases| {
            leases.retain(|_, lease| {
                if lease.expires_at <= now {
                    expired.push(lease.clone());
                    false
                } else {
                    true
                }
            });
            !leases.is_empty()
        });
        expired
    }

    #[must_use]
    pub fn desired(&self) -> BTreeSet<LeaseKey> {
        self.leases.keys().cloned().collect()
    }

    #[must_use]
    pub fn delta(&self) -> ScopeDelta {
        let desired = self.desired();
        ScopeDelta {
            subscribe: desired.difference(&self.applied).cloned().collect(),
            unsubscribe: self.applied.difference(&desired).cloned().collect(),
        }
    }

    /// Call only after every command for this delta was accepted by the socket writer.
    pub fn mark_applied(&mut self, delta: &ScopeDelta) {
        for key in &delta.unsubscribe {
            self.applied.remove(key);
        }
        self.applied.extend(delta.subscribe.iter().cloned());
    }

    /// A new socket has no subscriptions, even if the previous socket did.
    pub fn reset_applied(&mut self) {
        self.applied.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const MINT: &str = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump";

    fn lease(id: &str, expires_at: i64) -> HotLease {
        HotLease {
            lease_id: id.to_owned(),
            key: LeaseKey::new(LeaseKind::MintTrades, MINT).unwrap(),
            opened_at: UnixMillis(1),
            expires_at: UnixMillis(expires_at),
            reason: "operator-selected hot coin".to_owned(),
        }
    }

    #[test]
    fn overlapping_leases_do_not_unsubscribe_early() {
        let mut book = ScopeBook::new(10).unwrap();
        book.upsert(lease("a", 10)).unwrap();
        book.upsert(lease("b", 20)).unwrap();
        let delta = book.delta();
        assert_eq!(delta.subscribe.len(), 1);
        book.mark_applied(&delta);

        book.expire(UnixMillis(11));
        assert!(book.delta().unsubscribe.is_empty());
        book.expire(UnixMillis(21));
        assert_eq!(book.delta().unsubscribe.len(), 1);
    }

    #[test]
    fn reconnect_resubscribes_every_desired_key() {
        let mut book = ScopeBook::new(10).unwrap();
        book.upsert(lease("a", 10)).unwrap();
        let delta = book.delta();
        book.mark_applied(&delta);
        assert!(book.delta().subscribe.is_empty());
        book.reset_applied();
        assert_eq!(book.delta().subscribe.len(), 1);
    }
}
