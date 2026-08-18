use std::collections::{BTreeMap, BTreeSet};

use thiserror::Error;

use crate::amount::{ArithmeticError, AtomQty, SignedAtoms, TotalAtoms};
use crate::model::{AccountKey, AssetKey, EffectKey, WalletSnapshot};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountEffect {
    pub account: AccountKey,
    pub asset: AssetKey,
    pub before: AtomQty,
    pub after: AtomQty,
    pub change: SignedAtoms,
}

/// Exact effects derived only from finalized before/after account balances.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalizedWalletEffect {
    pub id: EffectKey,
    pub account_effects: Vec<AccountEffect>,
    pub aggregate_before: BTreeMap<AssetKey, TotalAtoms>,
    pub aggregate_after: BTreeMap<AssetKey, TotalAtoms>,
    pub aggregate_change: BTreeMap<AssetKey, SignedAtoms>,
}

impl FinalizedWalletEffect {
    /// Derives exact account and consolidated effects from two finalized snapshots.
    ///
    /// # Errors
    ///
    /// Returns [`EffectError`] if checked controlled-domain aggregation overflows.
    pub fn between(
        id: EffectKey,
        before: &WalletSnapshot,
        after: &WalletSnapshot,
    ) -> Result<Self, EffectError> {
        let keys: BTreeSet<_> = before
            .balances
            .keys()
            .chain(after.balances.keys())
            .cloned()
            .collect();

        let mut account_effects = Vec::new();
        let mut aggregate_before = BTreeMap::new();
        let mut aggregate_after = BTreeMap::new();

        for key in keys {
            let before_amount = before.balances.get(&key).copied().unwrap_or(AtomQty::ZERO);
            let after_amount = after.balances.get(&key).copied().unwrap_or(AtomQty::ZERO);

            add_total(&mut aggregate_before, &key.asset, before_amount)?;
            add_total(&mut aggregate_after, &key.asset, after_amount)?;

            if before_amount != after_amount {
                account_effects.push(AccountEffect {
                    account: key.account,
                    asset: key.asset,
                    before: before_amount,
                    after: after_amount,
                    change: SignedAtoms::between(before_amount.into(), after_amount.into()),
                });
            }
        }

        aggregate_before.retain(|_, amount| *amount != TotalAtoms::ZERO);
        aggregate_after.retain(|_, amount| *amount != TotalAtoms::ZERO);

        let assets: BTreeSet<_> = aggregate_before
            .keys()
            .chain(aggregate_after.keys())
            .cloned()
            .collect();
        let aggregate_change = assets
            .into_iter()
            .map(|asset| {
                let old = aggregate_before
                    .get(&asset)
                    .copied()
                    .unwrap_or(TotalAtoms::ZERO);
                let new = aggregate_after
                    .get(&asset)
                    .copied()
                    .unwrap_or(TotalAtoms::ZERO);
                (asset, SignedAtoms::between(old, new))
            })
            .collect();

        Ok(Self {
            id,
            account_effects,
            aggregate_before,
            aggregate_after,
            aggregate_change,
        })
    }

    pub fn change_for(&self, asset: &AssetKey) -> SignedAtoms {
        self.aggregate_change
            .get(asset)
            .copied()
            .unwrap_or(SignedAtoms::Unchanged)
    }

    #[must_use]
    pub fn is_custody_only(&self) -> bool {
        self.aggregate_change
            .values()
            .all(|change| *change == SignedAtoms::Unchanged)
            && !self.account_effects.is_empty()
    }
}

fn add_total(
    totals: &mut BTreeMap<AssetKey, TotalAtoms>,
    asset: &AssetKey,
    amount: AtomQty,
) -> Result<(), EffectError> {
    let total = totals.entry(asset.clone()).or_insert(TotalAtoms::ZERO);
    *total = total.checked_add(amount.into())?;
    Ok(())
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum EffectError {
    #[error(transparent)]
    Arithmetic(#[from] ArithmeticError),
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::AccountAssetKey;

    #[test]
    fn custody_move_is_not_a_household_asset_effect() {
        let token = AssetKey::new("token-a").unwrap();
        let first = AccountAssetKey {
            account: AccountKey::new("first").unwrap(),
            asset: token.clone(),
        };
        let second = AccountAssetKey {
            account: AccountKey::new("second").unwrap(),
            asset: token.clone(),
        };
        let before = WalletSnapshot {
            balances: BTreeMap::from([
                (first.clone(), AtomQty::new(10)),
                (second.clone(), AtomQty::ZERO),
            ]),
        };
        let after = WalletSnapshot {
            balances: BTreeMap::from([(first, AtomQty::ZERO), (second, AtomQty::new(10))]),
        };

        let effect =
            FinalizedWalletEffect::between(EffectKey::new("move").unwrap(), &before, &after)
                .unwrap();
        assert!(effect.is_custody_only());
        assert_eq!(effect.change_for(&token), SignedAtoms::Unchanged);
        assert_eq!(effect.account_effects.len(), 2);
    }
}
