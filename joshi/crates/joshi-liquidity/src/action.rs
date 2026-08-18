//! Read-only add/remove/rebalance intent semantics. No value can build a transaction.

use std::collections::BTreeSet;

use joshi_accounting::amount::AtomQty;
use joshi_domain::{ObservationId, PositionId, ProtocolProfileId};
use joshi_market_math::wide::{Rounding, mul_div_u128};
use thiserror::Error;

use crate::{
    position::{
        AccrualState, AssetPairAmounts, DlmmPositionState, PositionError, RewardAmount,
        deposit_share, inventory_for_share,
    },
    q64::BinId,
};

/// Known semantic gap that must remain visible on a modeled action result.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnsupportedField {
    MintedLiquidityShares,
    InitialLiquidityShare,
    CompositionFee,
    TransactionAccountLimits,
    TransactionCostAndPriority,
    InterfaceSupport,
    SwapTraversal,
    CloseReopenFriction,
    AccrualDerivation,
}

/// Strength of an action projection. `ModeledOnly` never claims UI or deployed-handler support.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ActionSupport {
    ModeledOnly {
        profile_id: ProtocolProfileId,
        unsupported_fields: Vec<UnsupportedField>,
    },
    DifferentiallyVerifiedProfile {
        profile_id: ProtocolProfileId,
    },
}

/// Common identity that prevents applying an intent to a newer or different position snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PositionIntentIdentity {
    pub position_id: PositionId,
    pub state_observation_id: ObservationId,
    pub profile_id: ProtocolProfileId,
}

/// Exact atomic amounts directed to one target bin.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BinDeposit {
    pub bin_id: BinId,
    pub amounts: AssetPairAmounts,
}

/// Add-liquidity intent. It describes deposits, not minted shares or a transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AddLiquidityIntent {
    pub identity: PositionIntentIdentity,
    pub deposits: Vec<BinDeposit>,
}

/// Validated add amounts and the semantic gaps that remain.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AddLiquidityProjection {
    pub identity: PositionIntentIdentity,
    pub deposits: Vec<BinDepositProjection>,
    pub total_deposit: AssetPairAmounts,
    pub support: ActionSupport,
}

/// Exact input plus projected share for a nonempty observed bin.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BinDepositProjection {
    pub bin_id: BinId,
    pub amounts: AssetPairAmounts,
    pub projected_liquidity_share: Option<u128>,
}

/// Removal fraction in basis points of this position's share in a named bin.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RemoveBps(u16);

impl RemoveBps {
    /// Creates a positive fraction no greater than 100%.
    ///
    /// # Errors
    ///
    /// Refuses zero or values above 10,000.
    pub const fn new(value: u16) -> Result<Self, ActionRefusal> {
        if value == 0 || value > 10_000 {
            Err(ActionRefusal::InvalidRemovalFraction)
        } else {
            Ok(Self(value))
        }
    }

    #[must_use]
    pub const fn get(self) -> u16 {
        self.0
    }
}

/// One per-bin removal request.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BinRemoval {
    pub bin_id: BinId,
    pub bps: RemoveBps,
}

/// Remove-liquidity intent with claim and account-lifecycle choices kept explicit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoveLiquidityIntent {
    pub identity: PositionIntentIdentity,
    pub removals: Vec<BinRemoval>,
    pub claim_fees: bool,
    pub claim_rewards: bool,
    pub close_position_account: bool,
}

/// Exact projected principal withdrawal for one bin.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BinWithdrawal {
    pub bin_id: BinId,
    pub removed_share: u128,
    pub remaining_share: u128,
    pub principal: AssetPairAmounts,
}

/// Exact withdrawal projection. Claims remain separate from principal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoveLiquidityProjection {
    pub identity: PositionIntentIdentity,
    pub bins: Vec<BinWithdrawal>,
    pub principal: AssetPairAmounts,
    pub claimed_fees: Option<AssetPairAmounts>,
    pub claimed_rewards: Option<Vec<RewardAmount>>,
    pub closes_position_account: bool,
    pub support: ActionSupport,
}

/// Whether a rebalance budget assumes an internal swap.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SwapRequirement {
    Forbidden,
    Required,
}

/// In-place rebalance intent: preserve position identity while changing its bin allocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RebalanceInPlaceIntent {
    pub identity: PositionIntentIdentity,
    pub target_deposits: Vec<BinDeposit>,
    pub top_up_limits: AssetPairAmounts,
    pub minimum_withdrawals: AssetPairAmounts,
    pub swap_requirement: SwapRequirement,
}

/// Budget conservation for modeled in-place rebalance, before protocol share/transaction effects.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RebalanceBudget {
    pub identity: PositionIntentIdentity,
    pub current_principal: AssetPairAmounts,
    pub target_principal: AssetPairAmounts,
    pub required_top_up: AssetPairAmounts,
    pub residual_withdrawal: AssetPairAmounts,
    pub support: ActionSupport,
}

/// Explicitly different semantic operation that retires one position identity and creates another.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CloseReopenIntent {
    pub identity: PositionIntentIdentity,
    pub new_position_id: PositionId,
    pub new_lower_bin_id: BinId,
    pub new_upper_bin_id: BinId,
    pub target_deposits: Vec<BinDeposit>,
}

/// Closed set of liquidity intent meanings; no variant is an executable instruction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LiquidityActionIntent {
    Add(AddLiquidityIntent),
    Remove(RemoveLiquidityIntent),
    RebalanceInPlace(RebalanceInPlaceIntent),
    CloseReopen(CloseReopenIntent),
}

/// Intent/state/refusal distinction for the read-only action kernel.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ActionRefusal {
    #[error("intent identity does not match the immutable position observation")]
    IdentityMismatch,
    #[error("bin deposits/removals are empty, unordered, duplicated, or outside the position")]
    InvalidBinSet,
    #[error("removal basis points must be in 1..=10,000")]
    InvalidRemovalFraction,
    #[error("a nonzero deposit rounds to zero liquidity share")]
    DepositRoundsToZero,
    #[error("a nonzero removal fraction rounds to zero liquidity share")]
    RemovalRoundsToZero,
    #[error("a close intent would leave nonzero liquidity share")]
    CloseWouldLeaveLiquidity,
    #[error("requested claim values are unsupported by this observation")]
    UnsupportedAccrual,
    #[error("modeled target exceeds its explicit top-up limit")]
    TopUpLimitExceeded,
    #[error("modeled residual is below an explicit withdrawal minimum")]
    WithdrawalMinimumNotMet,
    #[error("swap-required rebalance is outside this no-swap semantic kernel")]
    SwapTraversalUnsupported,
    #[error("new position identity is equal to the position being retired")]
    ReusedPositionIdentity,
    #[error("checked action arithmetic failed")]
    Arithmetic,
    #[error(transparent)]
    Position(#[from] PositionError),
}

/// Validates exact add amounts without inventing minted-share or transaction semantics.
///
/// # Errors
///
/// Refuses identity mismatch, malformed bin sets, or checked aggregation failure.
pub fn project_add(
    state: &DlmmPositionState,
    intent: &AddLiquidityIntent,
) -> Result<AddLiquidityProjection, ActionRefusal> {
    state.validate()?;
    validate_identity(state, &intent.identity)?;
    validate_deposits(state, &intent.deposits)?;
    let total_deposit = sum_deposits(&intent.deposits)?;
    let deposits = intent
        .deposits
        .iter()
        .map(|deposit| {
            let bin = state
                .bins
                .iter()
                .find(|bin| bin.bin_id == deposit.bin_id)
                .ok_or(ActionRefusal::InvalidBinSet)?;
            let projected_liquidity_share = if deposit.bin_id == state.active_bin_id {
                None
            } else {
                deposit_share(bin, deposit.amounts)?
            };
            if projected_liquidity_share == Some(0) {
                return Err(ActionRefusal::DepositRoundsToZero);
            }
            Ok(BinDepositProjection {
                bin_id: deposit.bin_id,
                amounts: deposit.amounts,
                projected_liquidity_share,
            })
        })
        .collect::<Result<Vec<_>, ActionRefusal>>()?;
    let has_initial_bin = intent.deposits.iter().any(|deposit| {
        state
            .bins
            .iter()
            .any(|bin| bin.bin_id == deposit.bin_id && bin.liquidity_supply == 0)
    });
    let has_active_bin = intent
        .deposits
        .iter()
        .any(|deposit| deposit.bin_id == state.active_bin_id);
    let mut unsupported_fields = vec![
        UnsupportedField::TransactionAccountLimits,
        UnsupportedField::TransactionCostAndPriority,
        UnsupportedField::InterfaceSupport,
    ];
    if has_initial_bin {
        unsupported_fields.push(UnsupportedField::InitialLiquidityShare);
    }
    if has_active_bin {
        unsupported_fields.push(UnsupportedField::CompositionFee);
    }
    Ok(AddLiquidityProjection {
        identity: intent.identity.clone(),
        deposits,
        total_deposit,
        support: ActionSupport::ModeledOnly {
            profile_id: state.profile.id.clone(),
            unsupported_fields,
        },
    })
}

/// Projects exact principal withdrawal and optionally observed pending claims.
///
/// # Errors
///
/// Refuses stale identity, malformed removals, unsupported requested accrual, an unsafe close, or
/// checked arithmetic failure.
pub fn project_remove(
    state: &DlmmPositionState,
    intent: &RemoveLiquidityIntent,
) -> Result<RemoveLiquidityProjection, ActionRefusal> {
    state.validate()?;
    validate_identity(state, &intent.identity)?;
    validate_removals(state, &intent.removals)?;

    let mut principal = AssetPairAmounts::default();
    let mut withdrawals = Vec::with_capacity(intent.removals.len());
    let mut removed_bins = BTreeSet::new();
    for removal in &intent.removals {
        let bin = state
            .bins
            .iter()
            .find(|bin| bin.bin_id == removal.bin_id)
            .ok_or(ActionRefusal::InvalidBinSet)?;
        let removed_share = if removal.bps.get() == 10_000 {
            bin.position_share
        } else {
            mul_div_u128(
                bin.position_share,
                u128::from(removal.bps.get()),
                10_000,
                Rounding::Down,
            )
            .map_err(|_| ActionRefusal::Arithmetic)?
        };
        let remaining_share = bin
            .position_share
            .checked_sub(removed_share)
            .ok_or(ActionRefusal::Arithmetic)?;
        if removed_share == 0 {
            return Err(ActionRefusal::RemovalRoundsToZero);
        }
        let amounts = inventory_for_share(bin, removed_share)?;
        principal = principal
            .checked_add(amounts)
            .map_err(ActionRefusal::from)?;
        removed_bins.insert(bin.bin_id);
        withdrawals.push(BinWithdrawal {
            bin_id: bin.bin_id,
            removed_share,
            remaining_share,
            principal: amounts,
        });
    }

    if intent.close_position_account
        && state.bins.iter().any(|bin| {
            bin.position_share != 0
                && (!removed_bins.contains(&bin.bin_id)
                    || withdrawals.iter().any(|withdrawal| {
                        withdrawal.bin_id == bin.bin_id && withdrawal.remaining_share != 0
                    }))
        })
    {
        return Err(ActionRefusal::CloseWouldLeaveLiquidity);
    }

    let inventory = state.inventory()?;
    let claimed_fees = if intent.claim_fees {
        Some(
            inventory
                .pending_fees
                .ok_or(ActionRefusal::UnsupportedAccrual)?,
        )
    } else {
        None
    };
    let claimed_rewards = if intent.claim_rewards {
        if state
            .bins
            .iter()
            .any(|bin| matches!(bin.accrual, AccrualState::Unsupported { .. }))
        {
            return Err(ActionRefusal::UnsupportedAccrual);
        }
        Some(
            inventory
                .pending_rewards
                .ok_or(ActionRefusal::UnsupportedAccrual)?,
        )
    } else {
        None
    };

    Ok(RemoveLiquidityProjection {
        identity: intent.identity.clone(),
        bins: withdrawals,
        principal,
        claimed_fees,
        claimed_rewards,
        closes_position_account: intent.close_position_account,
        support: ActionSupport::ModeledOnly {
            profile_id: state.profile.id.clone(),
            unsupported_fields: vec![
                UnsupportedField::TransactionAccountLimits,
                UnsupportedField::TransactionCostAndPriority,
                UnsupportedField::InterfaceSupport,
            ],
        },
    })
}

/// Checks asset conservation for a no-swap in-place rebalance intent.
///
/// This validates economic budgeting only. Minted shares, realized remove rounding, account limits,
/// transaction construction, and UI support remain explicit gaps.
///
/// # Errors
///
/// Refuses stale identity, malformed targets, swap traversal, limit/minimum failure, or arithmetic.
pub fn project_rebalance_budget(
    state: &DlmmPositionState,
    intent: &RebalanceInPlaceIntent,
) -> Result<RebalanceBudget, ActionRefusal> {
    state.validate()?;
    validate_identity(state, &intent.identity)?;
    validate_deposits(state, &intent.target_deposits)?;
    if intent.swap_requirement == SwapRequirement::Required {
        return Err(ActionRefusal::SwapTraversalUnsupported);
    }
    let current = state.inventory()?.principal;
    let target = sum_deposits(&intent.target_deposits)?;
    let top_up = AssetPairAmounts {
        x: AtomQty::new(target.x.get().saturating_sub(current.x.get())),
        y: AtomQty::new(target.y.get().saturating_sub(current.y.get())),
    };
    if top_up.x > intent.top_up_limits.x || top_up.y > intent.top_up_limits.y {
        return Err(ActionRefusal::TopUpLimitExceeded);
    }
    let available = current.checked_add(top_up).map_err(ActionRefusal::from)?;
    let residual = available.checked_sub(target).map_err(ActionRefusal::from)?;
    if residual.x < intent.minimum_withdrawals.x || residual.y < intent.minimum_withdrawals.y {
        return Err(ActionRefusal::WithdrawalMinimumNotMet);
    }
    Ok(RebalanceBudget {
        identity: intent.identity.clone(),
        current_principal: current,
        target_principal: target,
        required_top_up: top_up,
        residual_withdrawal: residual,
        support: ActionSupport::ModeledOnly {
            profile_id: state.profile.id.clone(),
            unsupported_fields: vec![
                UnsupportedField::MintedLiquidityShares,
                UnsupportedField::TransactionAccountLimits,
                UnsupportedField::TransactionCostAndPriority,
                UnsupportedField::InterfaceSupport,
            ],
        },
    })
}

/// Validates that close/reopen is represented as a new identity rather than an in-place rebalance.
///
/// # Errors
///
/// Refuses stale identity, reused position identity, or malformed targets.
pub fn validate_close_reopen(
    state: &DlmmPositionState,
    intent: &CloseReopenIntent,
) -> Result<ActionSupport, ActionRefusal> {
    state.validate()?;
    validate_identity(state, &intent.identity)?;
    if intent.new_position_id == state.position_id {
        return Err(ActionRefusal::ReusedPositionIdentity);
    }
    validate_deposits_in_range(
        intent.new_lower_bin_id,
        intent.new_upper_bin_id,
        &intent.target_deposits,
    )?;
    Ok(ActionSupport::ModeledOnly {
        profile_id: state.profile.id.clone(),
        unsupported_fields: vec![
            UnsupportedField::CloseReopenFriction,
            UnsupportedField::MintedLiquidityShares,
            UnsupportedField::TransactionAccountLimits,
            UnsupportedField::TransactionCostAndPriority,
            UnsupportedField::InterfaceSupport,
        ],
    })
}

fn validate_identity(
    state: &DlmmPositionState,
    identity: &PositionIntentIdentity,
) -> Result<(), ActionRefusal> {
    if identity.position_id != state.position_id
        || identity.state_observation_id != state.observation_id
        || identity.profile_id != state.profile.id
    {
        Err(ActionRefusal::IdentityMismatch)
    } else {
        Ok(())
    }
}

fn validate_deposits(
    state: &DlmmPositionState,
    deposits: &[BinDeposit],
) -> Result<(), ActionRefusal> {
    validate_deposits_in_range(state.lower_bin_id, state.upper_bin_id, deposits)?;
    if deposits
        .iter()
        .any(|deposit| !state.bins.iter().any(|bin| bin.bin_id == deposit.bin_id))
    {
        Err(ActionRefusal::InvalidBinSet)
    } else {
        Ok(())
    }
}

fn validate_deposits_in_range(
    lower_bin_id: BinId,
    upper_bin_id: BinId,
    deposits: &[BinDeposit],
) -> Result<(), ActionRefusal> {
    if deposits.is_empty()
        || lower_bin_id > upper_bin_id
        || deposits
            .windows(2)
            .any(|window| window[0].bin_id >= window[1].bin_id)
        || deposits.iter().any(|deposit| {
            deposit.bin_id < lower_bin_id
                || deposit.bin_id > upper_bin_id
                || deposit.amounts == AssetPairAmounts::default()
        })
    {
        Err(ActionRefusal::InvalidBinSet)
    } else {
        Ok(())
    }
}

fn validate_removals(
    state: &DlmmPositionState,
    removals: &[BinRemoval],
) -> Result<(), ActionRefusal> {
    if removals.is_empty()
        || removals
            .windows(2)
            .any(|window| window[0].bin_id >= window[1].bin_id)
        || removals.iter().any(|removal| {
            !state
                .bins
                .iter()
                .any(|bin| bin.bin_id == removal.bin_id && bin.position_share != 0)
        })
    {
        Err(ActionRefusal::InvalidBinSet)
    } else {
        Ok(())
    }
}

fn sum_deposits(deposits: &[BinDeposit]) -> Result<AssetPairAmounts, ActionRefusal> {
    deposits
        .iter()
        .try_fold(AssetPairAmounts::default(), |aggregate, deposit| {
            aggregate
                .checked_add(deposit.amounts)
                .map_err(ActionRefusal::from)
        })
}
