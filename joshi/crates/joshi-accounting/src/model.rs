use std::collections::BTreeMap;

pub use joshi_domain::{
    AccountId as AccountKey, AssetId as AssetKey, EpisodeId as EpisodeKey, LotId as LotKey,
    WalletEffectId as EffectKey,
};
use joshi_domain::{WireStringError, WireU64};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::amount::AtomQty;

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AccountAssetKey {
    pub account: AccountKey,
    pub asset: AssetKey,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct WalletSnapshot {
    pub balances: BTreeMap<AccountAssetKey, AtomQty>,
}

impl WalletSnapshot {
    /// Builds a snapshot from strict decimal-string fixture rows.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid shared identity or duplicate account/asset row.
    pub fn from_wire(rows: &[BalanceWire]) -> Result<Self, SnapshotError> {
        let mut balances = BTreeMap::new();
        for row in rows {
            let key = AccountAssetKey {
                account: AccountKey::new(&row.account).map_err(|source| {
                    SnapshotError::InvalidAccount {
                        value: row.account.clone(),
                        source,
                    }
                })?,
                asset: AssetKey::new(&row.asset).map_err(|source| SnapshotError::InvalidAsset {
                    value: row.asset.clone(),
                    source,
                })?,
            };
            let amount = AtomQty::new(row.atoms.get());
            if balances.insert(key, amount).is_some() {
                return Err(SnapshotError::DuplicateRow {
                    account: row.account.clone(),
                    asset: row.asset.clone(),
                });
            }
        }
        Ok(Self { balances })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BalanceWire {
    pub account: String,
    pub asset: String,
    pub atoms: WireU64,
}

/// Invalid finalized snapshot input.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum SnapshotError {
    /// Account identity did not satisfy the shared domain contract.
    #[error("invalid account identity {value:?}: {source}")]
    InvalidAccount {
        /// Exact rejected value.
        value: String,
        /// Shared identity validation error.
        #[source]
        source: WireStringError,
    },
    /// Asset identity did not satisfy the shared domain contract.
    #[error("invalid asset identity {value:?}: {source}")]
    InvalidAsset {
        /// Exact rejected value.
        value: String,
        /// Shared identity validation error.
        #[source]
        source: WireStringError,
    },
    /// The same account/asset pair appeared more than once.
    #[error("duplicate account/asset row: {account} / {asset}")]
    DuplicateRow {
        /// Account identity from the duplicate row.
        account: String,
        /// Asset identity from the duplicate row.
        asset: String,
    },
}
