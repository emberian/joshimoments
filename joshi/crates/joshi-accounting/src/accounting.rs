use std::collections::{BTreeMap, BTreeSet};

use thiserror::Error;

use crate::amount::{AtomQty, SignedAtoms, TotalAtoms};
use crate::basis::Basis;
use crate::effect::FinalizedWalletEffect;
use crate::lots::{
    BasisEpochRef, CapitalRecovery, CashAccumulator, Lot, LotAllocation, LotBook, LotError,
    RealizedComponent, realized_components,
};
use crate::model::{AssetKey, EffectKey, EpisodeKey, LotKey, WalletSnapshot};

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct CashEpoch {
    pub episode: EpisodeKey,
    pub index: u32,
    pub asset: AssetKey,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CashMovement {
    pub epoch: CashEpoch,
    pub amount: AtomQty,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Classification {
    Acquisition {
        asset: AssetKey,
        quantity: AtomQty,
        lot: LotKey,
        basis: Basis,
        epoch: Option<BasisEpochRef>,
        cash_spend: Option<CashMovement>,
    },
    Disposal {
        asset: AssetKey,
        quantity: AtomQty,
        allocations: Vec<LotAllocation>,
        net_proceeds: BTreeMap<AssetKey, AtomQty>,
        cash_return: Option<CashMovement>,
    },
    ExternalInflowUnknown {
        asset: AssetKey,
        quantity: AtomQty,
        lot: LotKey,
    },
    ExternalOutflow {
        asset: AssetKey,
        quantity: AtomQty,
        allocations: Vec<LotAllocation>,
    },
    CustodyOnly,
    Unclassified,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ClassificationProjection {
    Acquisition,
    Disposal {
        allocated_basis: Basis,
        realized: BTreeMap<AssetKey, RealizedComponent>,
    },
    ExternalInflowUnknown,
    ExternalOutflow {
        transferred_basis: Basis,
    },
    CustodyOnly,
    Unclassified,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountingState {
    observed_balances: BTreeMap<AssetKey, TotalAtoms>,
    effects: BTreeMap<EffectKey, FinalizedWalletEffect>,
    classified: BTreeSet<EffectKey>,
    pub lots: LotBook,
    cash: BTreeMap<CashEpoch, CashAccumulator>,
}

impl AccountingState {
    /// Starts a projector at an independently observed finalized snapshot.
    ///
    /// # Errors
    ///
    /// Returns [`AccountingError`] if checked controlled-domain aggregation overflows.
    pub fn from_snapshot(snapshot: &WalletSnapshot) -> Result<Self, AccountingError> {
        Ok(Self {
            observed_balances: aggregate_snapshot(snapshot)?,
            effects: BTreeMap::new(),
            classified: BTreeSet::new(),
            lots: LotBook::default(),
            cash: BTreeMap::new(),
        })
    }

    /// Advance landed truth. This succeeds or fails independently from economic classification.
    ///
    /// # Errors
    ///
    /// Returns an error for a duplicate effect or a noncontiguous before-snapshot.
    pub fn apply_effect(&mut self, effect: FinalizedWalletEffect) -> Result<(), AccountingError> {
        if self.effects.contains_key(&effect.id) {
            return Err(AccountingError::DuplicateEffect(effect.id.to_string()));
        }
        if self.observed_balances != effect.aggregate_before {
            return Err(AccountingError::NonContiguousEffect(effect.id.to_string()));
        }
        self.observed_balances = effect.aggregate_after.clone();
        self.effects.insert(effect.id.clone(), effect);
        Ok(())
    }

    /// Add a projection over an already-applied effect. Failure cannot roll back landed truth.
    ///
    /// # Errors
    ///
    /// Returns an error when the effect is absent/already classified, observed quantities do not
    /// match the classification, or lot/basis/cash arithmetic cannot be applied exactly.
    pub fn classify(
        &mut self,
        effect_id: &EffectKey,
        classification: Classification,
    ) -> Result<ClassificationProjection, AccountingError> {
        if self.classified.contains(effect_id) {
            return Err(AccountingError::AlreadyClassified(effect_id.to_string()));
        }
        let effect = self
            .effects
            .get(effect_id)
            .ok_or_else(|| AccountingError::UnknownEffect(effect_id.to_string()))?;
        let mut next_lots = self.lots.clone();
        let mut next_cash = self.cash.clone();

        let projection = match classification {
            Classification::Acquisition {
                asset,
                quantity,
                lot,
                basis,
                epoch,
                cash_spend,
            } => {
                require_increase(effect, &asset, quantity)?;
                require_basis_effect(effect, &basis)?;
                if let Some(movement) = &cash_spend {
                    require_decrease(effect, &movement.epoch.asset, movement.amount)?;
                }
                next_lots.insert(Lot::acquisition(lot, asset, quantity, basis, epoch)?)?;
                if let Some(movement) = cash_spend {
                    next_cash
                        .entry(movement.epoch)
                        .or_default()
                        .record_spend(movement.amount)?;
                }
                ClassificationProjection::Acquisition
            }
            Classification::Disposal {
                asset,
                quantity,
                allocations,
                net_proceeds,
                cash_return,
            } => {
                require_decrease(effect, &asset, quantity)?;
                for (proceeds_asset, amount) in &net_proceeds {
                    require_increase(effect, proceeds_asset, *amount)?;
                }
                if let Some(movement) = &cash_return {
                    require_increase(effect, &movement.epoch.asset, movement.amount)?;
                }
                let allocated_basis = next_lots.consume(&asset, quantity, &allocations)?;
                let realized = realized_components(&net_proceeds, &allocated_basis);
                if let Some(movement) = cash_return {
                    next_cash
                        .entry(movement.epoch)
                        .or_default()
                        .record_return(movement.amount)?;
                }
                ClassificationProjection::Disposal {
                    allocated_basis,
                    realized,
                }
            }
            Classification::ExternalInflowUnknown {
                asset,
                quantity,
                lot,
            } => {
                require_increase(effect, &asset, quantity)?;
                next_lots.insert(Lot::external_unknown(lot, asset, quantity)?)?;
                ClassificationProjection::ExternalInflowUnknown
            }
            Classification::ExternalOutflow {
                asset,
                quantity,
                allocations,
            } => {
                require_decrease(effect, &asset, quantity)?;
                let transferred_basis = next_lots.consume(&asset, quantity, &allocations)?;
                ClassificationProjection::ExternalOutflow { transferred_basis }
            }
            Classification::CustodyOnly => {
                if !effect.is_custody_only() {
                    return Err(AccountingError::NotCustodyOnly(effect_id.to_string()));
                }
                ClassificationProjection::CustodyOnly
            }
            Classification::Unclassified => ClassificationProjection::Unclassified,
        };
        self.lots = next_lots;
        self.cash = next_cash;
        self.classified.insert(effect_id.clone());
        Ok(projection)
    }

    pub fn observed_balance(&self, asset: &AssetKey) -> TotalAtoms {
        self.observed_balances
            .get(asset)
            .copied()
            .unwrap_or(TotalAtoms::ZERO)
    }

    /// Compares independently observed quantity with classified lot quantity.
    ///
    /// # Errors
    ///
    /// Returns an error if checked lot aggregation overflows.
    pub fn lot_reconciliation(&self, asset: &AssetKey) -> Result<SignedAtoms, AccountingError> {
        Ok(SignedAtoms::between(
            self.lots.remaining_quantity(asset)?,
            self.observed_balance(asset),
        ))
    }

    /// Returns exact cash recovery for one inventory epoch and reference asset.
    ///
    /// # Errors
    ///
    /// Returns an error if checked cash aggregation/subtraction fails.
    pub fn capital_recovery(&self, epoch: &CashEpoch) -> Result<CapitalRecovery, AccountingError> {
        self.cash
            .get(epoch)
            .copied()
            .unwrap_or_default()
            .status()
            .map_err(AccountingError::from)
    }
}

fn require_basis_effect(
    effect: &FinalizedWalletEffect,
    basis: &Basis,
) -> Result<(), AccountingError> {
    if matches!(basis.quality, crate::basis::BasisQuality::Unknown) {
        return Ok(());
    }
    for (asset, amount) in &basis.known {
        let atoms = amount
            .to_u64_if_integer()
            .ok_or(AccountingError::NonAtomicObservedBasis)?;
        require_decrease(effect, asset, AtomQty::new(atoms))?;
    }
    Ok(())
}

fn require_increase(
    effect: &FinalizedWalletEffect,
    asset: &AssetKey,
    quantity: AtomQty,
) -> Result<(), AccountingError> {
    if effect.change_for(asset).exact_increase(quantity) {
        Ok(())
    } else {
        Err(AccountingError::EffectMismatch {
            effect: effect.id.to_string(),
            asset: asset.to_string(),
            direction: "increase",
            expected: quantity.get(),
        })
    }
}

fn require_decrease(
    effect: &FinalizedWalletEffect,
    asset: &AssetKey,
    quantity: AtomQty,
) -> Result<(), AccountingError> {
    if effect.change_for(asset).exact_decrease(quantity) {
        Ok(())
    } else {
        Err(AccountingError::EffectMismatch {
            effect: effect.id.to_string(),
            asset: asset.to_string(),
            direction: "decrease",
            expected: quantity.get(),
        })
    }
}

fn aggregate_snapshot(
    snapshot: &WalletSnapshot,
) -> Result<BTreeMap<AssetKey, TotalAtoms>, AccountingError> {
    let mut totals = BTreeMap::new();
    for (key, amount) in &snapshot.balances {
        if *amount == AtomQty::ZERO {
            continue;
        }
        let total = totals.entry(key.asset.clone()).or_insert(TotalAtoms::ZERO);
        *total = total.checked_add((*amount).into())?;
    }
    Ok(totals)
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AccountingError {
    #[error(transparent)]
    Arithmetic(#[from] crate::amount::ArithmeticError),
    #[error(transparent)]
    Lot(#[from] LotError),
    #[error("duplicate finalized wallet effect: {0}")]
    DuplicateEffect(String),
    #[error("wallet effect does not start from the current finalized snapshot: {0}")]
    NonContiguousEffect(String),
    #[error("unknown finalized wallet effect: {0}")]
    UnknownEffect(String),
    #[error("wallet effect already has an economic classification: {0}")]
    AlreadyClassified(String),
    #[error("effect {effect} does not contain exact {direction} of {expected} atoms for {asset}")]
    EffectMismatch {
        effect: String,
        asset: String,
        direction: &'static str,
        expected: u64,
    },
    #[error("observed acquisition basis must be a nonnegative integer number of atoms")]
    NonAtomicObservedBasis,
    #[error("effect is not a custody-only movement: {0}")]
    NotCustodyOnly(String),
}

#[cfg(test)]
mod tests {
    use joshi_domain::WireU64;

    use super::*;
    use crate::model::BalanceWire;

    fn snapshot(sol: u64, token: u64) -> WalletSnapshot {
        WalletSnapshot::from_wire(&[
            BalanceWire {
                account: "wallet-sol".into(),
                asset: "sol".into(),
                atoms: WireU64::new(sol),
            },
            BalanceWire {
                account: "wallet-token".into(),
                asset: "token".into(),
                atoms: WireU64::new(token),
            },
        ])
        .unwrap()
    }

    #[test]
    fn failed_classification_preserves_landed_truth_and_prior_projection() {
        let sol = AssetKey::new("sol").unwrap();
        let token = AssetKey::new("token").unwrap();
        let lot = LotKey::new("lot-a").unwrap();
        let initial = snapshot(200, 0);
        let first_after = snapshot(190, 100);
        let first_id = EffectKey::new("first").unwrap();
        let mut state = AccountingState::from_snapshot(&initial).unwrap();
        state
            .apply_effect(
                FinalizedWalletEffect::between(first_id.clone(), &initial, &first_after).unwrap(),
            )
            .unwrap();
        state
            .classify(
                &first_id,
                Classification::Acquisition {
                    asset: token.clone(),
                    quantity: AtomQty::new(100),
                    lot: lot.clone(),
                    basis: Basis::known(sol.clone(), AtomQty::new(10)),
                    epoch: None,
                    cash_spend: None,
                },
            )
            .unwrap();

        let second_after = snapshot(189, 110);
        let second_id = EffectKey::new("second").unwrap();
        state
            .apply_effect(
                FinalizedWalletEffect::between(second_id.clone(), &first_after, &second_after)
                    .unwrap(),
            )
            .unwrap();
        let error = state.classify(
            &second_id,
            Classification::Acquisition {
                asset: token.clone(),
                quantity: AtomQty::new(10),
                lot,
                basis: Basis::known(sol, AtomQty::new(1)),
                epoch: None,
                cash_spend: None,
            },
        );
        assert!(matches!(
            error,
            Err(AccountingError::Lot(LotError::DuplicateLot(_)))
        ));

        assert_eq!(state.observed_balance(&token), TotalAtoms::new(110));
        assert_eq!(
            state.lots.remaining_quantity(&token),
            Ok(TotalAtoms::new(100))
        );
        assert_eq!(
            state.lot_reconciliation(&token),
            Ok(SignedAtoms::Increase(TotalAtoms::new(10)))
        );
        assert_eq!(
            state.classify(&second_id, Classification::Unclassified),
            Ok(ClassificationProjection::Unclassified)
        );
    }

    #[test]
    fn omitted_zero_and_explicit_zero_are_contiguous() {
        let token = AssetKey::new("token").unwrap();
        let empty = WalletSnapshot::default();
        let explicit_zero = WalletSnapshot::from_wire(&[BalanceWire {
            account: "wallet-token".into(),
            asset: "token".into(),
            atoms: WireU64::new(0),
        }])
        .unwrap();
        let funded = WalletSnapshot::from_wire(&[BalanceWire {
            account: "wallet-token".into(),
            asset: "token".into(),
            atoms: WireU64::new(5),
        }])
        .unwrap();

        let mut from_absent = AccountingState::from_snapshot(&empty).unwrap();
        from_absent
            .apply_effect(
                FinalizedWalletEffect::between(
                    EffectKey::new("fund-absent").unwrap(),
                    &empty,
                    &funded,
                )
                .unwrap(),
            )
            .unwrap();

        let mut from_explicit = AccountingState::from_snapshot(&explicit_zero).unwrap();
        from_explicit
            .apply_effect(
                FinalizedWalletEffect::between(
                    EffectKey::new("fund-explicit").unwrap(),
                    &explicit_zero,
                    &funded,
                )
                .unwrap(),
            )
            .unwrap();

        assert_eq!(from_absent.observed_balance(&token), TotalAtoms::new(5));
        assert_eq!(from_explicit.observed_balance(&token), TotalAtoms::new(5));
    }
}
