use std::collections::{BTreeMap, BTreeSet};

use thiserror::Error;

use crate::amount::{ArithmeticError, AtomQty, TotalAtoms};
use crate::basis::{Basis, BasisError, BasisQuality, ExactRatio};
use crate::model::{AssetKey, EpisodeKey, LotKey};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LotOrigin {
    Acquisition,
    ExternalInflow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BasisEpochRef {
    pub episode: EpisodeKey,
    pub index: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Lot {
    pub id: LotKey,
    pub asset: AssetKey,
    pub original_quantity: AtomQty,
    pub remaining_quantity: AtomQty,
    pub remaining_basis: Basis,
    pub origin: LotOrigin,
    pub epoch: Option<BasisEpochRef>,
}

impl Lot {
    /// Constructs a nonzero acquisition lot.
    ///
    /// # Errors
    ///
    /// Returns [`LotError::ZeroQuantity`] when quantity is zero.
    pub fn acquisition(
        id: LotKey,
        asset: AssetKey,
        quantity: AtomQty,
        basis: Basis,
        epoch: Option<BasisEpochRef>,
    ) -> Result<Self, LotError> {
        if quantity == AtomQty::ZERO {
            return Err(LotError::ZeroQuantity);
        }
        Ok(Self {
            id,
            asset,
            original_quantity: quantity,
            remaining_quantity: quantity,
            remaining_basis: basis,
            origin: LotOrigin::Acquisition,
            epoch,
        })
    }

    /// Constructs a nonzero external-inflow lot whose basis is explicitly unknown.
    ///
    /// # Errors
    ///
    /// Returns [`LotError::ZeroQuantity`] when quantity is zero.
    pub fn external_unknown(
        id: LotKey,
        asset: AssetKey,
        quantity: AtomQty,
    ) -> Result<Self, LotError> {
        if quantity == AtomQty::ZERO {
            return Err(LotError::ZeroQuantity);
        }
        Ok(Self {
            id,
            asset,
            original_quantity: quantity,
            remaining_quantity: quantity,
            remaining_basis: Basis::unknown(),
            origin: LotOrigin::ExternalInflow,
            epoch: None,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LotAllocation {
    pub lot: LotKey,
    pub quantity: AtomQty,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct LotBook {
    lots: BTreeMap<LotKey, Lot>,
}

impl LotBook {
    /// Inserts a lot without overwriting an existing identity.
    ///
    /// # Errors
    ///
    /// Returns [`LotError::DuplicateLot`] when the ID already exists.
    pub fn insert(&mut self, lot: Lot) -> Result<(), LotError> {
        if self.lots.contains_key(&lot.id) {
            return Err(LotError::DuplicateLot(lot.id.as_str().to_owned()));
        }
        self.lots.insert(lot.id.clone(), lot);
        Ok(())
    }

    #[must_use]
    pub fn get(&self, id: &LotKey) -> Option<&Lot> {
        self.lots.get(id)
    }

    /// Sums remaining quantity for one asset with checked `u128` aggregation.
    ///
    /// # Errors
    ///
    /// Returns an arithmetic error if aggregate quantity exceeds `u128`.
    pub fn remaining_quantity(&self, asset: &AssetKey) -> Result<TotalAtoms, LotError> {
        self.lots
            .values()
            .filter(|lot| &lot.asset == asset)
            .try_fold(TotalAtoms::ZERO, |total, lot| {
                total
                    .checked_add(lot.remaining_quantity.into())
                    .map_err(LotError::from)
            })
    }

    pub fn remaining_basis(&self, asset: &AssetKey) -> Basis {
        self.lots
            .values()
            .filter(|lot| &lot.asset == asset && lot.remaining_quantity != AtomQty::ZERO)
            .map(|lot| lot.remaining_basis.clone())
            .reduce(|total, basis| total.merged_with(&basis))
            .unwrap_or(Basis {
                quality: BasisQuality::Known,
                known: BTreeMap::new(),
            })
    }

    /// Explicitly consume named lot slices. There is intentionally no default FIFO/LIFO policy.
    ///
    /// # Errors
    ///
    /// Returns an error for missing/duplicated/wrong-asset/oversized slices, a mismatched total,
    /// or any exact arithmetic failure. Validation and mutation are atomic.
    pub fn consume(
        &mut self,
        asset: &AssetKey,
        expected_quantity: AtomQty,
        allocations: &[LotAllocation],
    ) -> Result<Basis, LotError> {
        validate_allocations(&self.lots, asset, expected_quantity, allocations)?;

        // Work on a clone so any unexpected arithmetic failure is atomic.
        let mut next = self.clone();
        let mut allocated = Basis {
            quality: BasisQuality::Known,
            known: BTreeMap::new(),
        };
        for slice in allocations {
            let lot = next
                .lots
                .get_mut(&slice.lot)
                .ok_or_else(|| LotError::UnknownLot(slice.lot.to_string()))?;
            let slice_basis = lot
                .remaining_basis
                .allocate(slice.quantity, lot.remaining_quantity)?;
            lot.remaining_quantity = lot.remaining_quantity.checked_sub(slice.quantity)?;
            lot.remaining_basis = lot.remaining_basis.checked_sub_known(&slice_basis)?;
            allocated = allocated.merged_with(&slice_basis);
        }
        *self = next;
        Ok(allocated)
    }
}

fn validate_allocations(
    lots: &BTreeMap<LotKey, Lot>,
    asset: &AssetKey,
    expected_quantity: AtomQty,
    allocations: &[LotAllocation],
) -> Result<(), LotError> {
    if expected_quantity == AtomQty::ZERO {
        return Err(LotError::ZeroQuantity);
    }
    let mut seen = BTreeSet::new();
    let mut sum = AtomQty::ZERO;
    for slice in allocations {
        if slice.quantity == AtomQty::ZERO {
            return Err(LotError::ZeroQuantity);
        }
        if !seen.insert(slice.lot.clone()) {
            return Err(LotError::DuplicateAllocation(slice.lot.as_str().to_owned()));
        }
        let lot = lots
            .get(&slice.lot)
            .ok_or_else(|| LotError::UnknownLot(slice.lot.as_str().to_owned()))?;
        if &lot.asset != asset {
            return Err(LotError::WrongAsset(slice.lot.as_str().to_owned()));
        }
        if slice.quantity > lot.remaining_quantity {
            return Err(LotError::InsufficientLot(slice.lot.as_str().to_owned()));
        }
        sum = sum.checked_add(slice.quantity)?;
    }
    if sum != expected_quantity {
        return Err(LotError::AllocationTotal {
            expected: expected_quantity.get(),
            actual: sum.get(),
        });
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RealizedComponent {
    pub proceeds: ExactRatio,
    pub allocated_known_basis: ExactRatio,
    pub result: Option<ExactRatio>,
    pub quality: BasisQuality,
}

pub(crate) fn realized_components(
    net_proceeds: &BTreeMap<AssetKey, AtomQty>,
    allocated_basis: &Basis,
) -> BTreeMap<AssetKey, RealizedComponent> {
    let assets: BTreeSet<_> = net_proceeds
        .keys()
        .chain(allocated_basis.known.keys())
        .cloned()
        .collect();
    assets
        .into_iter()
        .map(|asset| {
            let proceeds = net_proceeds
                .get(&asset)
                .copied()
                .map_or_else(ExactRatio::zero, ExactRatio::from_atom_qty);
            let allocated_known_basis = allocated_basis
                .component(&asset)
                .cloned()
                .unwrap_or_else(ExactRatio::zero);
            let result = matches!(
                allocated_basis.quality,
                BasisQuality::Known | BasisQuality::Estimated
            )
            .then(|| proceeds.sub(&allocated_known_basis));
            (
                asset,
                RealizedComponent {
                    proceeds,
                    allocated_known_basis,
                    result,
                    quality: allocated_basis.quality,
                },
            )
        })
        .collect()
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CapitalRecovery {
    NoCapitalRecorded,
    NotRecovered { shortfall: TotalAtoms },
    Recovered { excess: TotalAtoms },
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct CashAccumulator {
    cash_spent: TotalAtoms,
    cash_returned: TotalAtoms,
}

impl CashAccumulator {
    pub(crate) fn record_spend(&mut self, amount: AtomQty) -> Result<(), ArithmeticError> {
        self.cash_spent = self.cash_spent.checked_add(amount.into())?;
        Ok(())
    }

    pub(crate) fn record_return(&mut self, amount: AtomQty) -> Result<(), ArithmeticError> {
        self.cash_returned = self.cash_returned.checked_add(amount.into())?;
        Ok(())
    }

    pub(crate) fn status(self) -> Result<CapitalRecovery, ArithmeticError> {
        if self.cash_spent == TotalAtoms::ZERO {
            return Ok(CapitalRecovery::NoCapitalRecorded);
        }
        if self.cash_returned >= self.cash_spent {
            Ok(CapitalRecovery::Recovered {
                excess: self.cash_returned.checked_sub(self.cash_spent)?,
            })
        } else {
            Ok(CapitalRecovery::NotRecovered {
                shortfall: self.cash_spent.checked_sub(self.cash_returned)?,
            })
        }
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum LotError {
    #[error(transparent)]
    Arithmetic(#[from] ArithmeticError),
    #[error(transparent)]
    Basis(#[from] BasisError),
    #[error("lot quantity must be nonzero")]
    ZeroQuantity,
    #[error("duplicate lot id: {0}")]
    DuplicateLot(String),
    #[error("duplicate lot allocation: {0}")]
    DuplicateAllocation(String),
    #[error("unknown lot: {0}")]
    UnknownLot(String),
    #[error("lot belongs to a different asset: {0}")]
    WrongAsset(String),
    #[error("lot has insufficient remaining quantity: {0}")]
    InsufficientLot(String),
    #[error("lot allocations total {actual}, expected {expected}")]
    AllocationTotal { expected: u64, actual: u64 },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn partial_sale_then_close_has_no_basis_dust() {
        let token = AssetKey::new("token-a").unwrap();
        let sol = AssetKey::new("sol").unwrap();
        let lot_id = LotKey::new("lot-a").unwrap();
        let mut book = LotBook::default();
        book.insert(
            Lot::acquisition(
                lot_id.clone(),
                token.clone(),
                AtomQty::new(1_000),
                Basis::known(sol.clone(), AtomQty::new(101)),
                None,
            )
            .unwrap(),
        )
        .unwrap();

        let first = book
            .consume(
                &token,
                AtomQty::new(600),
                &[LotAllocation {
                    lot: lot_id.clone(),
                    quantity: AtomQty::new(600),
                }],
            )
            .unwrap();
        assert_eq!(first.component(&sol).unwrap().numerator_string(), "303");
        assert_eq!(
            book.remaining_basis(&token)
                .component(&sol)
                .unwrap()
                .numerator_string(),
            "202"
        );

        let second = book
            .consume(
                &token,
                AtomQty::new(400),
                &[LotAllocation {
                    lot: lot_id,
                    quantity: AtomQty::new(400),
                }],
            )
            .unwrap();
        assert_eq!(
            first
                .merged_with(&second)
                .component(&sol)
                .unwrap()
                .numerator_string(),
            "101"
        );
        assert_eq!(book.remaining_quantity(&token), Ok(TotalAtoms::ZERO));
        assert!(book.remaining_basis(&token).is_exact_zero());
    }

    #[test]
    fn no_implicit_fifo_exists() {
        let token = AssetKey::new("token-a").unwrap();
        let sol = AssetKey::new("sol").unwrap();
        let mut book = LotBook::default();
        for (id, basis) in [("first", 10), ("second", 20)] {
            book.insert(
                Lot::acquisition(
                    LotKey::new(id).unwrap(),
                    token.clone(),
                    AtomQty::new(10),
                    Basis::known(sol.clone(), AtomQty::new(basis)),
                    None,
                )
                .unwrap(),
            )
            .unwrap();
        }
        assert!(matches!(
            book.consume(&token, AtomQty::new(10), &[]),
            Err(LotError::AllocationTotal { .. })
        ));
    }
}
