//! Observed two-vault pool inventory, and exact sizes expressed as fractions of it.
//!
//! A constant-product pool's liquidity is not a parameter a caller supplies; it is whatever the two
//! vault accounts held at one slot. This module states that inventory as an exact asset pair bound
//! to the observations it came from, and derives quote sizes as exact fractions of the observed
//! base inventory rather than as free-floating numbers.
//!
//! Nothing here is a fill, an order, or an execution estimate. A depth is what was in the vaults;
//! a fraction of it is a size someone might ask about.

use joshi_accounting::amount::AtomQty;
use joshi_domain::{AssetId, ObservationId, PoolId, WireU64};
use joshi_market_math::wide::{Rounding, WideMathError, add_signed_reserve, mul_div_u128};
use thiserror::Error;

use crate::position::AssetPairAmounts;

const BASIS_POINTS_DENOMINATOR: u128 = 10_000;

/// A fraction of an observed inventory, in basis points of 10,000.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct DepthFractionBps(u16);

impl DepthFractionBps {
    /// Creates a positive fraction no greater than the whole inventory.
    ///
    /// # Errors
    ///
    /// Refuses zero and values above 10,000 basis points.
    pub const fn new(value: u16) -> Result<Self, DepthError> {
        if value == 0 || value > 10_000 {
            Err(DepthError::InvalidFraction)
        } else {
            Ok(Self(value))
        }
    }

    #[must_use]
    pub const fn get(self) -> u16 {
        self.0
    }
}

/// The exact inventory two pool vaults held at one observed slot.
///
/// `raw_quote_atoms` is the quote vault balance the provider stated. `virtual_quote_reserves` is
/// the signed protocol adjustment; the two are kept separate because only their sum enters the
/// formula and only the first is a token balance anyone can look up.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedPoolDepth {
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    /// The observation that carried both vault balances. One observation, so one slot.
    pub state_observation_id: ObservationId,
    pub slot: WireU64,
    pub base_atoms: AtomQty,
    pub raw_quote_atoms: AtomQty,
    pub virtual_quote_reserves: i128,
}

impl ObservedPoolDepth {
    /// The two vault balances as an exact asset pair, base first.
    #[must_use]
    pub const fn inventory(&self) -> AssetPairAmounts {
        AssetPairAmounts {
            x: self.base_atoms,
            y: self.raw_quote_atoms,
        }
    }

    /// The quote reserve the constant-product formula actually uses.
    ///
    /// # Errors
    ///
    /// Refuses a signed sum outside `u128`, including a negative one, and a zero result.
    pub fn effective_quote_atoms(&self) -> Result<u128, DepthError> {
        let effective =
            add_signed_reserve(self.raw_quote_atoms.get(), self.virtual_quote_reserves)?;
        if effective == 0 {
            Err(DepthError::EmptyQuoteSide)
        } else {
            Ok(effective)
        }
    }

    /// An exact fraction of the observed base inventory, truncated toward zero.
    ///
    /// Truncation is deliberate: a size derived from inventory must never round up past what the
    /// vault was observed to hold.
    ///
    /// # Errors
    ///
    /// Refuses an empty base side and any fraction that truncates to nothing.
    pub fn base_fraction_atoms(&self, fraction: DepthFractionBps) -> Result<AtomQty, DepthError> {
        if self.base_atoms == AtomQty::ZERO {
            return Err(DepthError::EmptyBaseSide);
        }
        let atoms = mul_div_u128(
            u128::from(self.base_atoms.get()),
            u128::from(fraction.get()),
            BASIS_POINTS_DENOMINATOR,
            Rounding::Down,
        )?;
        let atoms =
            u64::try_from(atoms).map_err(|_| DepthError::Arithmetic(WideMathError::Narrowing))?;
        if atoms == 0 {
            Err(DepthError::FractionTruncatesToNothing)
        } else {
            Ok(AtomQty::new(atoms))
        }
    }

    /// The fraction of the observed base inventory one size represents, in basis points, truncated.
    ///
    /// # Errors
    ///
    /// Refuses an empty base side and arithmetic failure.
    pub fn base_share_bps(&self, atoms: AtomQty) -> Result<u128, DepthError> {
        if self.base_atoms == AtomQty::ZERO {
            return Err(DepthError::EmptyBaseSide);
        }
        mul_div_u128(
            u128::from(atoms.get()),
            BASIS_POINTS_DENOMINATOR,
            u128::from(self.base_atoms.get()),
            Rounding::Down,
        )
        .map_err(Into::into)
    }
}

/// Refusals from reading an observed pool inventory.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum DepthError {
    #[error("inventory fraction is zero or above 10,000 basis points")]
    InvalidFraction,
    #[error("observed base vault is empty, so no base fraction exists")]
    EmptyBaseSide,
    #[error("effective quote reserve is zero or nonpositive")]
    EmptyQuoteSide,
    #[error("the requested fraction of the observed inventory truncates to zero atoms")]
    FractionTruncatesToNothing,
    #[error(transparent)]
    Arithmetic(#[from] WideMathError),
}

#[cfg(test)]
mod tests {
    use super::*;

    fn depth(base: u64, quote: u64, virtual_quote: i128) -> ObservedPoolDepth {
        ObservedPoolDepth {
            pool_id: PoolId::new("pool-depth-test").expect("pool id"),
            base_asset_id: AssetId::new("base").expect("base asset"),
            quote_asset_id: AssetId::new("quote").expect("quote asset"),
            state_observation_id: ObservationId::new("obs-depth-test").expect("observation id"),
            slot: WireU64::new(440_672_889),
            base_atoms: AtomQty::new(base),
            raw_quote_atoms: AtomQty::new(quote),
            virtual_quote_reserves: virtual_quote,
        }
    }

    #[test]
    fn inventory_is_the_two_observed_vault_balances_and_nothing_else() {
        let observed = depth(4_822_874_602_995, 15_592_870_111_376, 0);
        assert_eq!(observed.inventory().x.get(), 4_822_874_602_995);
        assert_eq!(observed.inventory().y.get(), 15_592_870_111_376);
        assert_eq!(observed.effective_quote_atoms(), Ok(15_592_870_111_376));
    }

    #[test]
    fn a_signed_virtual_reserve_moves_only_the_effective_quote_side() {
        let observed = depth(10, 100, -40);
        assert_eq!(observed.raw_quote_atoms.get(), 100);
        assert_eq!(observed.effective_quote_atoms(), Ok(60));
        assert_eq!(
            depth(10, 100, -100).effective_quote_atoms(),
            Err(DepthError::EmptyQuoteSide)
        );
        assert!(depth(10, 100, -101).effective_quote_atoms().is_err());
    }

    #[test]
    fn a_size_derived_from_inventory_truncates_down_and_never_up() {
        let observed = depth(9_999, 1, 0);
        let one_bp = DepthFractionBps::new(1).expect("fraction");
        assert_eq!(
            observed.base_fraction_atoms(one_bp),
            Err(DepthError::FractionTruncatesToNothing)
        );
        let ten_bps = DepthFractionBps::new(10).expect("fraction");
        assert_eq!(
            observed.base_fraction_atoms(ten_bps).map(AtomQty::get),
            Ok(9)
        );
    }

    #[test]
    fn a_whole_inventory_fraction_is_the_whole_observed_base_side() {
        let observed = depth(4_822_874_602_995, 1, 0);
        let whole = DepthFractionBps::new(10_000).expect("fraction");
        assert_eq!(
            observed.base_fraction_atoms(whole).map(AtomQty::get),
            Ok(4_822_874_602_995)
        );
        assert_eq!(
            observed.base_share_bps(AtomQty::new(4_822_874_602_995)),
            Ok(10_000)
        );
    }

    #[test]
    fn fractions_outside_the_inventory_are_refused() {
        assert_eq!(DepthFractionBps::new(0), Err(DepthError::InvalidFraction));
        assert_eq!(
            DepthFractionBps::new(10_001),
            Err(DepthError::InvalidFraction)
        );
    }
}
