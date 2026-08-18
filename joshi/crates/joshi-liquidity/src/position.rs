//! Exact DLMM position, per-bin inventory, and accrued-claim snapshots.

use std::collections::{BTreeMap, BTreeSet};

use joshi_accounting::amount::AtomQty;
use joshi_domain::{
    AssetId, ObservationId, PoolId, PositionId, ProtocolProfileId, StableString, VenueId, WireU64,
};
use joshi_market_math::{
    profile::{ProtocolFamily, ProtocolProfile},
    wide::{Rounding, mul_div_u128},
};
use ruint::aliases::U256;
use thiserror::Error;

use crate::q64::{BinId, BinStep, Q64x64, price_from_bin_id};

/// Evidence-bound asset display metadata. Atoms remain accounting truth.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedAssetDefinition {
    pub asset_id: AssetId,
    pub decimals: u8,
    pub token_program: StableString,
    pub observation_id: ObservationId,
}

/// Exact pair of X and Y atomic quantities.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct AssetPairAmounts {
    pub x: AtomQty,
    pub y: AtomQty,
}

impl AssetPairAmounts {
    /// Adds pair components independently without wrapping.
    ///
    /// # Errors
    ///
    /// Refuses either component above `u64::MAX`.
    pub fn checked_add(self, rhs: Self) -> Result<Self, PositionError> {
        Ok(Self {
            x: self
                .x
                .checked_add(rhs.x)
                .map_err(|_| PositionError::Arithmetic)?,
            y: self
                .y
                .checked_add(rhs.y)
                .map_err(|_| PositionError::Arithmetic)?,
        })
    }

    /// Subtracts pair components independently without underflow.
    ///
    /// # Errors
    ///
    /// Refuses a larger right-hand component.
    pub fn checked_sub(self, rhs: Self) -> Result<Self, PositionError> {
        Ok(Self {
            x: self
                .x
                .checked_sub(rhs.x)
                .map_err(|_| PositionError::Arithmetic)?,
            y: self
                .y
                .checked_sub(rhs.y)
                .map_err(|_| PositionError::Arithmetic)?,
        })
    }
}

/// Pending reward in its own named asset.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RewardAmount {
    pub asset_id: AssetId,
    pub atoms: AtomQty,
}

/// Whether pending fees and rewards are directly observed or unavailable.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AccrualState {
    ObservedPending {
        fees: AssetPairAmounts,
        rewards: Vec<RewardAmount>,
    },
    Unsupported {
        fields: Vec<StableString>,
    },
}

/// One observed DLMM bin and this position's liquidity share in it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PositionBinState {
    pub bin_id: BinId,
    pub price_q64: Q64x64,
    pub pool_amounts: AssetPairAmounts,
    pub liquidity_supply: u128,
    pub position_share: u128,
    pub accrual: AccrualState,
}

/// Versioned account layout whose fields have been decoded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PositionVersion {
    V1,
    V2,
    Unknown(StableString),
}

/// Lifecycle of the position account, not the market itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PositionLifecycle {
    Open,
    EmptyOpen,
    Closed,
    Unknown(StableString),
}

/// Complete immutable input for per-bin inventory projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DlmmPositionState {
    pub profile: ProtocolProfile,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub position_id: PositionId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub version: PositionVersion,
    pub lifecycle: PositionLifecycle,
    pub token_x: ObservedAssetDefinition,
    pub token_y: ObservedAssetDefinition,
    pub lower_bin_id: BinId,
    pub upper_bin_id: BinId,
    pub active_bin_id: BinId,
    pub bin_step: BinStep,
    pub bins: Vec<PositionBinState>,
    pub unsupported_fields: Vec<StableString>,
}

/// Principal and claim state derived for one bin.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BinInventory {
    pub bin_id: BinId,
    pub price_q64: Q64x64,
    pub principal: AssetPairAmounts,
    pub pending_fees: Option<AssetPairAmounts>,
    pub pending_rewards: Option<Vec<RewardAmount>>,
    pub unsupported_fields: Vec<StableString>,
}

/// Withdrawal inventory and separately claimable values. This is not quote-currency liquidation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PositionInventory {
    pub profile_id: ProtocolProfileId,
    pub position_id: PositionId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub principal: AssetPairAmounts,
    pub pending_fees: Option<AssetPairAmounts>,
    pub pending_rewards: Option<Vec<RewardAmount>>,
    pub bins: Vec<BinInventory>,
    pub unsupported_fields: Vec<StableString>,
}

/// Position state or checked arithmetic failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PositionError {
    #[error("profile is not a Meteora DLMM profile or its venue identity is inconsistent")]
    ProfileMismatch,
    #[error("position range is inverted")]
    InvertedRange,
    #[error("position account version is not supported by this formula profile")]
    UnsupportedPositionVersion,
    #[error("position lifecycle is unknown to this formula profile")]
    UnsupportedPositionLifecycle,
    #[error("an empty or closed lifecycle carries nonzero liquidity share")]
    LifecycleShareMismatch,
    #[error("token X and token Y resolve to the same asset identity")]
    IdenticalPairAssets,
    #[error("unsupported field names are empty, duplicated, or unordered")]
    MalformedUnsupportedFields,
    #[error("position bins are not strictly ordered or contain duplicates")]
    UnorderedBins,
    #[error("a position bin is outside the declared range")]
    BinOutsidePositionRange,
    #[error("observed bin price differs from the profile's exact Q64.64 price")]
    BinPriceMismatch,
    #[error("a nonzero position share has zero liquidity supply")]
    ShareWithoutSupply,
    #[error("position share exceeds bin liquidity supply")]
    ShareExceedsSupply,
    #[error("checked position arithmetic failed")]
    Arithmetic,
}

impl DlmmPositionState {
    /// Validates structural/profile invariants and projects exact per-bin withdrawal inventory.
    ///
    /// Pending values are kept separate from principal. If any bin's accrual fields are
    /// unsupported, the aggregate pending-fee value is `None` and named fields remain attached.
    ///
    /// # Errors
    ///
    /// Refuses malformed state, a profile-price mismatch, or checked arithmetic failure.
    pub fn inventory(&self) -> Result<PositionInventory, PositionError> {
        self.validate()?;
        let mut principal = AssetPairAmounts::default();
        let mut pending_fees = Some(AssetPairAmounts::default());
        let mut pending_reward_totals = BTreeMap::<AssetId, AtomQty>::new();
        let mut pending_rewards_supported = true;
        let mut unsupported_fields = self
            .unsupported_fields
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>();
        let mut bins = Vec::with_capacity(self.bins.len());

        for bin in &self.bins {
            let bin_principal = inventory_for_share(bin, bin.position_share)?;
            principal = principal.checked_add(bin_principal)?;
            let (bin_fees, bin_rewards, bin_unsupported) = match &bin.accrual {
                AccrualState::ObservedPending {
                    fees,
                    rewards: bin_rewards,
                } => {
                    if let Some(aggregate) = pending_fees {
                        pending_fees = Some(aggregate.checked_add(*fees)?);
                    }
                    for reward in bin_rewards {
                        add_reward(&mut pending_reward_totals, reward)?;
                    }
                    (Some(*fees), Some(bin_rewards.clone()), Vec::new())
                }
                AccrualState::Unsupported { fields } => {
                    pending_fees = None;
                    pending_rewards_supported = false;
                    unsupported_fields.extend(fields.iter().cloned());
                    (None, None, fields.clone())
                }
            };
            bins.push(BinInventory {
                bin_id: bin.bin_id,
                price_q64: bin.price_q64,
                principal: bin_principal,
                pending_fees: bin_fees,
                pending_rewards: bin_rewards,
                unsupported_fields: bin_unsupported,
            });
        }

        Ok(PositionInventory {
            profile_id: self.profile.id.clone(),
            position_id: self.position_id.clone(),
            observation_id: self.observation_id.clone(),
            slot: self.slot,
            principal,
            pending_fees,
            pending_rewards: pending_rewards_supported.then(|| {
                pending_reward_totals
                    .into_iter()
                    .map(|(asset_id, atoms)| RewardAmount { asset_id, atoms })
                    .collect()
            }),
            bins,
            unsupported_fields: unsupported_fields.into_iter().collect(),
        })
    }

    pub(crate) fn validate(&self) -> Result<(), PositionError> {
        if self.profile.family != ProtocolFamily::MeteoraDlmm || self.venue_id != self.profile.venue
        {
            return Err(PositionError::ProfileMismatch);
        }
        if self.lower_bin_id > self.upper_bin_id {
            return Err(PositionError::InvertedRange);
        }
        if matches!(self.version, PositionVersion::Unknown(_)) {
            return Err(PositionError::UnsupportedPositionVersion);
        }
        if matches!(self.lifecycle, PositionLifecycle::Unknown(_)) {
            return Err(PositionError::UnsupportedPositionLifecycle);
        }
        if self.token_x.asset_id == self.token_y.asset_id {
            return Err(PositionError::IdenticalPairAssets);
        }
        validate_unsupported_fields(&self.unsupported_fields, false)?;
        if self
            .bins
            .windows(2)
            .any(|window| window[0].bin_id >= window[1].bin_id)
        {
            return Err(PositionError::UnorderedBins);
        }
        for bin in &self.bins {
            if bin.bin_id < self.lower_bin_id || bin.bin_id > self.upper_bin_id {
                return Err(PositionError::BinOutsidePositionRange);
            }
            if price_from_bin_id(bin.bin_id, self.bin_step)
                .map_err(|_| PositionError::Arithmetic)?
                != bin.price_q64
            {
                return Err(PositionError::BinPriceMismatch);
            }
            validate_share(bin, bin.position_share)?;
            if let AccrualState::Unsupported { fields } = &bin.accrual {
                validate_unsupported_fields(fields, true)?;
            }
        }
        if matches!(
            self.lifecycle,
            PositionLifecycle::EmptyOpen | PositionLifecycle::Closed
        ) && self.bins.iter().any(|bin| bin.position_share != 0)
        {
            return Err(PositionError::LifecycleShareMismatch);
        }
        Ok(())
    }
}

pub(crate) fn inventory_for_share(
    bin: &PositionBinState,
    share: u128,
) -> Result<AssetPairAmounts, PositionError> {
    validate_share(bin, share)?;
    if share == 0 {
        return Ok(AssetPairAmounts::default());
    }
    let x = mul_div_u128(
        u128::from(bin.pool_amounts.x.get()),
        share,
        bin.liquidity_supply,
        Rounding::Down,
    )
    .map_err(|_| PositionError::Arithmetic)?;
    let y = mul_div_u128(
        u128::from(bin.pool_amounts.y.get()),
        share,
        bin.liquidity_supply,
        Rounding::Down,
    )
    .map_err(|_| PositionError::Arithmetic)?;
    Ok(AssetPairAmounts {
        x: AtomQty::new(u64::try_from(x).map_err(|_| PositionError::Arithmetic)?),
        y: AtomQty::new(u64::try_from(y).map_err(|_| PositionError::Arithmetic)?),
    })
}

/// Computes `price_q64 * x_atoms + (y_atoms << 64)` using U256 and checks the protocol `u128`
/// narrowing boundary.
///
/// # Errors
///
/// Refuses a U256 operation or `u128` narrowing failure.
pub fn bin_liquidity(amounts: AssetPairAmounts, price_q64: Q64x64) -> Result<u128, PositionError> {
    let priced_x = U256::from(price_q64.bits())
        .checked_mul(U256::from(amounts.x.get()))
        .ok_or(PositionError::Arithmetic)?;
    let q64_y = u128::from(amounts.y.get())
        .checked_shl(64)
        .ok_or(PositionError::Arithmetic)?;
    let liquidity = priced_x
        .checked_add(U256::from(q64_y))
        .ok_or(PositionError::Arithmetic)?;
    u128::try_from(liquidity).map_err(|_| PositionError::Arithmetic)
}

/// Projects the liquidity share for a deposit into an already initialized nonempty bin.
///
/// `None` preserves the distinct initial-liquidity case, whose minimum-liquidity/composition
/// semantics require a more specific deployed-handler profile.
///
/// # Errors
///
/// Refuses malformed observed bin state or checked arithmetic failure.
pub fn deposit_share(
    bin: &PositionBinState,
    deposit: AssetPairAmounts,
) -> Result<Option<u128>, PositionError> {
    if bin.liquidity_supply == 0 {
        return Ok(None);
    }
    let existing_liquidity = bin_liquidity(bin.pool_amounts, bin.price_q64)?;
    if existing_liquidity == 0 {
        return Err(PositionError::ShareWithoutSupply);
    }
    let incoming_liquidity = bin_liquidity(deposit, bin.price_q64)?;
    mul_div_u128(
        incoming_liquidity,
        bin.liquidity_supply,
        existing_liquidity,
        Rounding::Down,
    )
    .map(Some)
    .map_err(|_| PositionError::Arithmetic)
}

fn validate_share(bin: &PositionBinState, share: u128) -> Result<(), PositionError> {
    if bin.liquidity_supply == 0 && share != 0 {
        return Err(PositionError::ShareWithoutSupply);
    }
    if share > bin.liquidity_supply {
        return Err(PositionError::ShareExceedsSupply);
    }
    Ok(())
}

fn add_reward(
    aggregate: &mut BTreeMap<AssetId, AtomQty>,
    reward: &RewardAmount,
) -> Result<(), PositionError> {
    let current = aggregate
        .get(&reward.asset_id)
        .copied()
        .unwrap_or(AtomQty::ZERO);
    aggregate.insert(
        reward.asset_id.clone(),
        current
            .checked_add(reward.atoms)
            .map_err(|_| PositionError::Arithmetic)?,
    );
    Ok(())
}

fn validate_unsupported_fields(
    fields: &[StableString],
    require_nonempty: bool,
) -> Result<(), PositionError> {
    if require_nonempty && fields.is_empty()
        || fields.windows(2).any(|window| window[0] >= window[1])
    {
        Err(PositionError::MalformedUnsupportedFields)
    } else {
        Ok(())
    }
}
