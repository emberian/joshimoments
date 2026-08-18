//! Exact DLMM position inventory and read-only modeled-action wire adapters.

use std::collections::BTreeMap;

use joshi_domain::{
    AssetId, ObservationId, PoolId, PositionId, ProtocolProfileId, StableString, VenueId, WireU64,
    WireU128,
};
use joshi_liquidity::{
    action::{
        ActionRefusal, ActionSupport, AddLiquidityProjection, RebalanceBudget,
        RemoveLiquidityProjection, UnsupportedField,
    },
    position::{
        AccrualState, AssetPairAmounts, BinInventory, DlmmPositionState, PositionError,
        PositionInventory, PositionLifecycle, PositionVersion, RewardAmount,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{
    AssetDefinitionDto, EpistemicClass, ExactMetric, Freshness, MetricReading, MetricUnit, WireI32,
};

/// One immutable position state plus any observation-bound modeled action results.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreshPosition {
    pub state: DlmmPositionState,
    pub freshness: Freshness,
    pub actions: Vec<LiquidityActionProjectionInput>,
}

/// Already-evaluated read-only action result. Every variant preserves its semantic operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LiquidityActionProjectionInput {
    Add {
        action_id: StableString,
        result: Result<AddLiquidityProjection, ActionRefusal>,
    },
    Remove {
        action_id: StableString,
        result: Result<RemoveLiquidityProjection, ActionRefusal>,
    },
    RebalanceInPlace {
        action_id: StableString,
        result: Result<RebalanceBudget, ActionRefusal>,
    },
    CloseReopen {
        action_id: StableString,
        old_position_id: PositionId,
        new_position_id: PositionId,
        result: Result<ActionSupport, ActionRefusal>,
    },
}

impl LiquidityActionProjectionInput {
    fn action_id(&self) -> &StableString {
        match self {
            Self::Add { action_id, .. }
            | Self::Remove { action_id, .. }
            | Self::RebalanceInPlace { action_id, .. }
            | Self::CloseReopen { action_id, .. } => action_id,
        }
    }
}

/// Decoded position-account version.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum PositionVersionDto {
    V1,
    V2,
    Unknown { discriminator: StableString },
}

/// Position account lifecycle, independent of the pool lifecycle.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum PositionLifecycleDto {
    Open,
    EmptyOpen,
    Closed,
    Unknown { discriminator: StableString },
}

/// Exact pair of X/Y metrics.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssetPairMetricsDto {
    pub x: ExactMetric<WireU128>,
    pub y: ExactMetric<WireU128>,
}

/// One pending reward in its independently named asset.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RewardMetricDto {
    pub asset_id: AssetId,
    pub amount: ExactMetric<WireU128>,
}

/// Known versus unsupported accrual values; unsupported never becomes an empty list or zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum AccrualProjectionDto<T> {
    ObservedPending { value: T },
    Unsupported { fields: Vec<StableString> },
}

/// Exact position entitlement in one DLMM bin.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BinInventoryDto {
    pub bin_id: WireI32,
    pub price_q64: ExactMetric<WireU128>,
    pub principal: AssetPairMetricsDto,
    pub pending_fees: AccrualProjectionDto<AssetPairMetricsDto>,
    pub pending_rewards: AccrualProjectionDto<Vec<RewardMetricDto>>,
    pub unsupported_fields: Vec<StableString>,
}

/// Exact withdrawal inventory, not quote-currency value or liquidation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PositionInventoryDto {
    pub principal: AssetPairMetricsDto,
    pub pending_fees: AccrualProjectionDto<AssetPairMetricsDto>,
    pub pending_rewards: AccrualProjectionDto<Vec<RewardMetricDto>>,
    pub bins: Vec<BinInventoryDto>,
    pub unsupported_fields: Vec<StableString>,
}

/// Position projection refusal code.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PositionRefusalDto {
    ProfileMismatch,
    InvertedRange,
    UnsupportedPositionVersion,
    UnsupportedPositionLifecycle,
    LifecycleShareMismatch,
    IdenticalPairAssets,
    MalformedUnsupportedFields,
    UnorderedBins,
    BinOutsidePositionRange,
    BinPriceMismatch,
    ShareWithoutSupply,
    ShareExceedsSupply,
    Arithmetic,
}

/// Inventory success/refusal; the identity and observed state survive refusal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum PositionInventoryOutcomeDto {
    Available {
        inventory: Box<PositionInventoryDto>,
    },
    Refused {
        reason: PositionRefusalDto,
    },
}

/// Named semantic gaps in an action projection.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UnsupportedActionFieldDto {
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

/// Evidence grade of an LP action calculation. Modeled-only never implies UI support.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ActionSupportDto {
    ModeledOnly {
        profile_id: ProtocolProfileId,
        unsupported_fields: Vec<UnsupportedActionFieldDto>,
    },
    DifferentiallyVerifiedProfile {
        profile_id: ProtocolProfileId,
    },
}

/// Closed action refusal codes.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionRefusalDto {
    IdentityMismatch,
    InvalidBinSet,
    InvalidRemovalFraction,
    DepositRoundsToZero,
    RemovalRoundsToZero,
    CloseWouldLeaveLiquidity,
    UnsupportedAccrual,
    TopUpLimitExceeded,
    WithdrawalMinimumNotMet,
    SwapTraversalUnsupported,
    ReusedPositionIdentity,
    Arithmetic,
    Position,
}

/// Projected deposit into one bin.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BinDepositDto {
    pub bin_id: WireI32,
    pub amounts: AssetPairMetricsDto,
    pub projected_liquidity_share: MetricReading<WireU128>,
}

/// Projected removal from one bin.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BinWithdrawalDto {
    pub bin_id: WireI32,
    pub removed_share: ExactMetric<WireU128>,
    pub remaining_share: ExactMetric<WireU128>,
    pub principal: AssetPairMetricsDto,
}

/// Claim state disambiguates not-requested from unsupported and projected zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ClaimProjectionDto<T> {
    NotRequested,
    Projected { value: T },
}

/// Successful add-liquidity model.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AddActionProjectionDto {
    pub deposits: Vec<BinDepositDto>,
    pub total_deposit: AssetPairMetricsDto,
    pub support: ActionSupportDto,
}

/// Successful remove-liquidity model.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RemoveActionProjectionDto {
    pub bins: Vec<BinWithdrawalDto>,
    pub principal: AssetPairMetricsDto,
    pub claimed_fees: ClaimProjectionDto<AssetPairMetricsDto>,
    pub claimed_rewards: ClaimProjectionDto<Vec<RewardMetricDto>>,
    pub closes_position_account: bool,
    pub support: ActionSupportDto,
}

/// Successful in-place rebalance budget model.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RebalanceActionProjectionDto {
    pub current_principal: AssetPairMetricsDto,
    pub target_principal: AssetPairMetricsDto,
    pub required_top_up: AssetPairMetricsDto,
    pub residual_withdrawal: AssetPairMetricsDto,
    pub support: ActionSupportDto,
}

/// Successful close/reopen distinction model.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CloseReopenActionProjectionDto {
    pub old_position_id: PositionId,
    pub new_position_id: PositionId,
    pub support: ActionSupportDto,
}

/// Successful LP action projection with each semantic operation structurally distinct.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum LiquidityActionSuccessDto {
    Add {
        projection: Box<AddActionProjectionDto>,
    },
    Remove {
        projection: Box<RemoveActionProjectionDto>,
    },
    RebalanceInPlace {
        projection: Box<RebalanceActionProjectionDto>,
    },
    CloseReopen {
        projection: Box<CloseReopenActionProjectionDto>,
    },
}

/// Modeled action success/refusal. Neither variant has execution authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum LiquidityActionOutcomeDto {
    Modeled {
        projection: Box<LiquidityActionSuccessDto>,
    },
    Refused {
        reason: ActionRefusalDto,
    },
}

/// One immutable LP action artifact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LiquidityActionDto {
    pub action_id: StableString,
    pub outcome: LiquidityActionOutcomeDto,
}

/// One observed DLMM position with inventory and read-only action models.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LiquidityPositionDto {
    pub profile_id: ProtocolProfileId,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub position_id: PositionId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub version: PositionVersionDto,
    pub lifecycle: PositionLifecycleDto,
    pub token_x_asset_id: AssetId,
    pub token_y_asset_id: AssetId,
    pub lower_bin_id: WireI32,
    pub upper_bin_id: WireI32,
    pub active_bin_id: WireI32,
    pub bin_step_bps: WireU64,
    pub freshness: Freshness,
    pub inventory: PositionInventoryOutcomeDto,
    pub actions: Vec<LiquidityActionDto>,
}

/// Complete liquidity portion of the read projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LiquidityProjectionDto {
    pub positions: Vec<LiquidityPositionDto>,
}

/// Projects exact DLMM inventory and read-only actions.
///
/// # Errors
///
/// Refuses metadata conflict, invalid freshness, or unordered position/action identities.
pub fn project_liquidity(
    definitions: &[AssetDefinitionDto],
    positions: &[FreshPosition],
) -> Result<LiquidityProjectionDto, LiquidityProjectionError> {
    let definition_count = definitions.len();
    let definitions: BTreeMap<_, _> = definitions
        .iter()
        .map(|value| (value.asset_id.clone(), value))
        .collect();
    if definitions.len() != definition_count {
        return Err(LiquidityProjectionError::DuplicateAssetDefinition);
    }
    if positions
        .windows(2)
        .any(|window| window[0].state.position_id >= window[1].state.position_id)
    {
        return Err(LiquidityProjectionError::Unordered("positions"));
    }
    let values = positions
        .iter()
        .map(|position| position_dto(position, &definitions))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(LiquidityProjectionDto { positions: values })
}

fn position_dto(
    value: &FreshPosition,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Result<LiquidityPositionDto, LiquidityProjectionError> {
    value
        .freshness
        .validate()
        .map_err(LiquidityProjectionError::Freshness)?;
    if value
        .actions
        .windows(2)
        .any(|window| window[0].action_id() >= window[1].action_id())
    {
        return Err(LiquidityProjectionError::Unordered("position actions"));
    }
    let x = lookup(definitions, &value.state.token_x.asset_id)?;
    let y = lookup(definitions, &value.state.token_y.asset_id)?;
    validate_asset_definition(x, &value.state.token_x)?;
    validate_asset_definition(y, &value.state.token_y)?;
    validate_reward_definitions(value, definitions)?;
    let inventory = match value.state.inventory() {
        Ok(inventory) => PositionInventoryOutcomeDto::Available {
            inventory: Box::new(inventory_dto(&inventory, x, y, definitions)),
        },
        Err(error) => PositionInventoryOutcomeDto::Refused {
            reason: position_refusal(&error),
        },
    };
    Ok(LiquidityPositionDto {
        profile_id: value.state.profile.id.clone(),
        venue_id: value.state.venue_id.clone(),
        pool_id: value.state.pool_id.clone(),
        position_id: value.state.position_id.clone(),
        observation_id: value.state.observation_id.clone(),
        slot: value.state.slot,
        version: version_dto(&value.state.version),
        lifecycle: lifecycle_dto(&value.state.lifecycle),
        token_x_asset_id: value.state.token_x.asset_id.clone(),
        token_y_asset_id: value.state.token_y.asset_id.clone(),
        lower_bin_id: WireI32::new(value.state.lower_bin_id.get()),
        upper_bin_id: WireI32::new(value.state.upper_bin_id.get()),
        active_bin_id: WireI32::new(value.state.active_bin_id.get()),
        bin_step_bps: WireU64::new(u64::from(value.state.bin_step.get())),
        freshness: value.freshness.clone(),
        inventory,
        actions: value
            .actions
            .iter()
            .map(|action| action_dto(action, x, y, definitions, &value.state.observation_id))
            .collect(),
    })
}

fn inventory_dto(
    value: &PositionInventory,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> PositionInventoryDto {
    PositionInventoryDto {
        principal: pair_metrics(
            "position",
            value.position_id.as_str(),
            "principal",
            value.principal,
            x,
            y,
            &value.observation_id,
        ),
        pending_fees: value.pending_fees.map_or_else(
            || AccrualProjectionDto::Unsupported {
                fields: value.unsupported_fields.clone(),
            },
            |fees| AccrualProjectionDto::ObservedPending {
                value: pair_metrics(
                    "position",
                    value.position_id.as_str(),
                    "pending_fees",
                    fees,
                    x,
                    y,
                    &value.observation_id,
                ),
            },
        ),
        pending_rewards: value.pending_rewards.as_ref().map_or_else(
            || AccrualProjectionDto::Unsupported {
                fields: value.unsupported_fields.clone(),
            },
            |rewards| AccrualProjectionDto::ObservedPending {
                value: reward_metrics(
                    "position",
                    value.position_id.as_str(),
                    rewards,
                    &value.observation_id,
                    definitions,
                ),
            },
        ),
        bins: value
            .bins
            .iter()
            .map(|bin| bin_dto(bin, value, x, y, definitions))
            .collect(),
        unsupported_fields: value.unsupported_fields.clone(),
    }
}

fn bin_dto(
    bin: &BinInventory,
    inventory: &PositionInventory,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> BinInventoryDto {
    let bin_identity = format!("{}:bin:{}", inventory.position_id, bin.bin_id.get());
    BinInventoryDto {
        bin_id: WireI32::new(bin.bin_id.get()),
        price_q64: ExactMetric {
            metric_id: metric_id("position", &bin_identity, "price_q64"),
            semantic_label: stable("dlmm_y_atoms_per_x_atom_q64"),
            epistemic_class: EpistemicClass::DeterministicCalculation,
            reading: MetricReading::Known {
                value: WireU128::new(bin.price_q64.bits()),
            },
            unit: MetricUnit::Q64x64Price,
            evidence: vec![inventory.observation_id.clone()],
            source_value_digest: None,
            rendering_hint: None,
        },
        principal: pair_metrics(
            "position_bin",
            &bin_identity,
            "principal",
            bin.principal,
            x,
            y,
            &inventory.observation_id,
        ),
        pending_fees: bin.pending_fees.map_or_else(
            || AccrualProjectionDto::Unsupported {
                fields: bin.unsupported_fields.clone(),
            },
            |fees| AccrualProjectionDto::ObservedPending {
                value: pair_metrics(
                    "position_bin",
                    &bin_identity,
                    "pending_fees",
                    fees,
                    x,
                    y,
                    &inventory.observation_id,
                ),
            },
        ),
        pending_rewards: bin.pending_rewards.as_ref().map_or_else(
            || AccrualProjectionDto::Unsupported {
                fields: bin.unsupported_fields.clone(),
            },
            |rewards| AccrualProjectionDto::ObservedPending {
                value: reward_metrics(
                    "position_bin",
                    &bin_identity,
                    rewards,
                    &inventory.observation_id,
                    definitions,
                ),
            },
        ),
        unsupported_fields: bin.unsupported_fields.clone(),
    }
}

fn action_dto(
    value: &LiquidityActionProjectionInput,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
    observation_id: &ObservationId,
) -> LiquidityActionDto {
    let action_id = value.action_id().clone();
    let outcome = match value {
        LiquidityActionProjectionInput::Add { result, .. } => {
            result.as_ref().map_or_else(refused, |projection| {
                modeled(LiquidityActionSuccessDto::Add {
                    projection: Box::new(add_action_dto(
                        projection,
                        action_id.as_str(),
                        x,
                        y,
                        observation_id,
                    )),
                })
            })
        }
        LiquidityActionProjectionInput::Remove { result, .. } => {
            result.as_ref().map_or_else(refused, |projection| {
                modeled(LiquidityActionSuccessDto::Remove {
                    projection: Box::new(remove_action_dto(
                        projection,
                        action_id.as_str(),
                        x,
                        y,
                        definitions,
                        observation_id,
                    )),
                })
            })
        }
        LiquidityActionProjectionInput::RebalanceInPlace { result, .. } => {
            result.as_ref().map_or_else(refused, |projection| {
                modeled(LiquidityActionSuccessDto::RebalanceInPlace {
                    projection: Box::new(rebalance_action_dto(
                        projection,
                        action_id.as_str(),
                        x,
                        y,
                        observation_id,
                    )),
                })
            })
        }
        LiquidityActionProjectionInput::CloseReopen {
            old_position_id,
            new_position_id,
            result,
            ..
        } => result.as_ref().map_or_else(refused, |support| {
            modeled(LiquidityActionSuccessDto::CloseReopen {
                projection: Box::new(CloseReopenActionProjectionDto {
                    old_position_id: old_position_id.clone(),
                    new_position_id: new_position_id.clone(),
                    support: support_dto(support),
                }),
            })
        }),
    };
    LiquidityActionDto { action_id, outcome }
}

fn modeled(value: LiquidityActionSuccessDto) -> LiquidityActionOutcomeDto {
    LiquidityActionOutcomeDto::Modeled {
        projection: Box::new(value),
    }
}

fn add_action_dto(
    value: &AddLiquidityProjection,
    action_id: &str,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    observation_id: &ObservationId,
) -> AddActionProjectionDto {
    AddActionProjectionDto {
        deposits: value
            .deposits
            .iter()
            .map(|deposit| BinDepositDto {
                bin_id: WireI32::new(deposit.bin_id.get()),
                amounts: pair_metrics(
                    "liquidity_action",
                    action_id,
                    &format!("deposit_bin_{}", deposit.bin_id.get()),
                    deposit.amounts,
                    x,
                    y,
                    observation_id,
                ),
                projected_liquidity_share: deposit.projected_liquidity_share.map_or_else(
                    || MetricReading::Unsupported {
                        reason: stable("initial_or_active_bin_share_semantics"),
                    },
                    |share| MetricReading::Known {
                        value: WireU128::new(share),
                    },
                ),
            })
            .collect(),
        total_deposit: pair_metrics(
            "liquidity_action",
            action_id,
            "total_deposit",
            value.total_deposit,
            x,
            y,
            observation_id,
        ),
        support: support_dto(&value.support),
    }
}

fn remove_action_dto(
    value: &RemoveLiquidityProjection,
    action_id: &str,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
    observation_id: &ObservationId,
) -> RemoveActionProjectionDto {
    RemoveActionProjectionDto {
        bins: value
            .bins
            .iter()
            .map(|bin| BinWithdrawalDto {
                bin_id: WireI32::new(bin.bin_id.get()),
                removed_share: share_metric(
                    action_id,
                    &format!("removed_share_bin_{}", bin.bin_id.get()),
                    bin.removed_share,
                    observation_id,
                ),
                remaining_share: share_metric(
                    action_id,
                    &format!("remaining_share_bin_{}", bin.bin_id.get()),
                    bin.remaining_share,
                    observation_id,
                ),
                principal: pair_metrics(
                    "liquidity_action",
                    action_id,
                    &format!("withdrawal_bin_{}", bin.bin_id.get()),
                    bin.principal,
                    x,
                    y,
                    observation_id,
                ),
            })
            .collect(),
        principal: pair_metrics(
            "liquidity_action",
            action_id,
            "withdrawal_principal",
            value.principal,
            x,
            y,
            observation_id,
        ),
        claimed_fees: value
            .claimed_fees
            .map_or(ClaimProjectionDto::NotRequested, |fees| {
                ClaimProjectionDto::Projected {
                    value: pair_metrics(
                        "liquidity_action",
                        action_id,
                        "claimed_fees",
                        fees,
                        x,
                        y,
                        observation_id,
                    ),
                }
            }),
        claimed_rewards: value.claimed_rewards.as_ref().map_or(
            ClaimProjectionDto::NotRequested,
            |rewards| ClaimProjectionDto::Projected {
                value: reward_metrics(
                    "liquidity_action",
                    action_id,
                    rewards,
                    observation_id,
                    definitions,
                ),
            },
        ),
        closes_position_account: value.closes_position_account,
        support: support_dto(&value.support),
    }
}

fn rebalance_action_dto(
    value: &RebalanceBudget,
    action_id: &str,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    observation_id: &ObservationId,
) -> RebalanceActionProjectionDto {
    let pair = |field, amounts| {
        pair_metrics(
            "liquidity_action",
            action_id,
            field,
            amounts,
            x,
            y,
            observation_id,
        )
    };
    RebalanceActionProjectionDto {
        current_principal: pair("rebalance_current_principal", value.current_principal),
        target_principal: pair("rebalance_target_principal", value.target_principal),
        required_top_up: pair("rebalance_required_top_up", value.required_top_up),
        residual_withdrawal: pair("rebalance_residual_withdrawal", value.residual_withdrawal),
        support: support_dto(&value.support),
    }
}

fn pair_metrics(
    prefix: &str,
    identity: &str,
    field: &str,
    value: AssetPairAmounts,
    x: &AssetDefinitionDto,
    y: &AssetDefinitionDto,
    observation_id: &ObservationId,
) -> AssetPairMetricsDto {
    AssetPairMetricsDto {
        x: atom_metric(
            prefix,
            identity,
            &format!("{field}_x"),
            value.x.get(),
            x,
            observation_id,
        ),
        y: atom_metric(
            prefix,
            identity,
            &format!("{field}_y"),
            value.y.get(),
            y,
            observation_id,
        ),
    }
}

fn atom_metric(
    prefix: &str,
    identity: &str,
    field: &str,
    atoms: u64,
    definition: &AssetDefinitionDto,
    observation_id: &ObservationId,
) -> ExactMetric<WireU128> {
    ExactMetric {
        metric_id: metric_id(prefix, identity, field),
        semantic_label: stable(field),
        epistemic_class: EpistemicClass::DeterministicCalculation,
        reading: MetricReading::Known {
            value: WireU128::new(u128::from(atoms)),
        },
        unit: MetricUnit::AssetAtoms {
            asset_id: definition.asset_id.clone(),
            decimals: definition.decimals,
            definition_observation_id: definition.definition_observation_id.clone(),
        },
        evidence: vec![observation_id.clone()],
        source_value_digest: None,
        rendering_hint: None,
    }
}

fn share_metric(
    identity: &str,
    field: &str,
    share: u128,
    observation_id: &ObservationId,
) -> ExactMetric<WireU128> {
    ExactMetric {
        metric_id: metric_id("liquidity_action", identity, field),
        semantic_label: stable(field),
        epistemic_class: EpistemicClass::DeterministicCalculation,
        reading: MetricReading::Known {
            value: WireU128::new(share),
        },
        unit: MetricUnit::LiquidityShare,
        evidence: vec![observation_id.clone()],
        source_value_digest: None,
        rendering_hint: None,
    }
}

fn reward_metrics(
    prefix: &str,
    identity: &str,
    rewards: &[RewardAmount],
    observation_id: &ObservationId,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Vec<RewardMetricDto> {
    rewards
        .iter()
        .map(|reward| {
            let definition = definitions
                .get(&reward.asset_id)
                .copied()
                .expect("reward definitions were validated before projection");
            RewardMetricDto {
                asset_id: reward.asset_id.clone(),
                amount: atom_metric(
                    prefix,
                    identity,
                    &format!("reward_{}", reward.asset_id),
                    reward.atoms.get(),
                    definition,
                    observation_id,
                ),
            }
        })
        .collect()
}

fn support_dto(value: &ActionSupport) -> ActionSupportDto {
    match value {
        ActionSupport::ModeledOnly {
            profile_id,
            unsupported_fields,
        } => {
            let mut fields = unsupported_fields
                .iter()
                .copied()
                .map(unsupported_dto)
                .collect::<Vec<_>>();
            fields.sort();
            fields.dedup();
            ActionSupportDto::ModeledOnly {
                profile_id: profile_id.clone(),
                unsupported_fields: fields,
            }
        }
        ActionSupport::DifferentiallyVerifiedProfile { profile_id } => {
            ActionSupportDto::DifferentiallyVerifiedProfile {
                profile_id: profile_id.clone(),
            }
        }
    }
}

fn unsupported_dto(value: UnsupportedField) -> UnsupportedActionFieldDto {
    match value {
        UnsupportedField::MintedLiquidityShares => UnsupportedActionFieldDto::MintedLiquidityShares,
        UnsupportedField::InitialLiquidityShare => UnsupportedActionFieldDto::InitialLiquidityShare,
        UnsupportedField::CompositionFee => UnsupportedActionFieldDto::CompositionFee,
        UnsupportedField::TransactionAccountLimits => {
            UnsupportedActionFieldDto::TransactionAccountLimits
        }
        UnsupportedField::TransactionCostAndPriority => {
            UnsupportedActionFieldDto::TransactionCostAndPriority
        }
        UnsupportedField::InterfaceSupport => UnsupportedActionFieldDto::InterfaceSupport,
        UnsupportedField::SwapTraversal => UnsupportedActionFieldDto::SwapTraversal,
        UnsupportedField::CloseReopenFriction => UnsupportedActionFieldDto::CloseReopenFriction,
        UnsupportedField::AccrualDerivation => UnsupportedActionFieldDto::AccrualDerivation,
    }
}

fn refused(value: &ActionRefusal) -> LiquidityActionOutcomeDto {
    LiquidityActionOutcomeDto::Refused {
        reason: match value {
            ActionRefusal::IdentityMismatch => ActionRefusalDto::IdentityMismatch,
            ActionRefusal::InvalidBinSet => ActionRefusalDto::InvalidBinSet,
            ActionRefusal::InvalidRemovalFraction => ActionRefusalDto::InvalidRemovalFraction,
            ActionRefusal::DepositRoundsToZero => ActionRefusalDto::DepositRoundsToZero,
            ActionRefusal::RemovalRoundsToZero => ActionRefusalDto::RemovalRoundsToZero,
            ActionRefusal::CloseWouldLeaveLiquidity => ActionRefusalDto::CloseWouldLeaveLiquidity,
            ActionRefusal::UnsupportedAccrual => ActionRefusalDto::UnsupportedAccrual,
            ActionRefusal::TopUpLimitExceeded => ActionRefusalDto::TopUpLimitExceeded,
            ActionRefusal::WithdrawalMinimumNotMet => ActionRefusalDto::WithdrawalMinimumNotMet,
            ActionRefusal::SwapTraversalUnsupported => ActionRefusalDto::SwapTraversalUnsupported,
            ActionRefusal::ReusedPositionIdentity => ActionRefusalDto::ReusedPositionIdentity,
            ActionRefusal::Arithmetic => ActionRefusalDto::Arithmetic,
            ActionRefusal::Position(_) => ActionRefusalDto::Position,
        },
    }
}

fn position_refusal(value: &PositionError) -> PositionRefusalDto {
    match value {
        PositionError::ProfileMismatch => PositionRefusalDto::ProfileMismatch,
        PositionError::InvertedRange => PositionRefusalDto::InvertedRange,
        PositionError::UnsupportedPositionVersion => PositionRefusalDto::UnsupportedPositionVersion,
        PositionError::UnsupportedPositionLifecycle => {
            PositionRefusalDto::UnsupportedPositionLifecycle
        }
        PositionError::LifecycleShareMismatch => PositionRefusalDto::LifecycleShareMismatch,
        PositionError::IdenticalPairAssets => PositionRefusalDto::IdenticalPairAssets,
        PositionError::MalformedUnsupportedFields => PositionRefusalDto::MalformedUnsupportedFields,
        PositionError::UnorderedBins => PositionRefusalDto::UnorderedBins,
        PositionError::BinOutsidePositionRange => PositionRefusalDto::BinOutsidePositionRange,
        PositionError::BinPriceMismatch => PositionRefusalDto::BinPriceMismatch,
        PositionError::ShareWithoutSupply => PositionRefusalDto::ShareWithoutSupply,
        PositionError::ShareExceedsSupply => PositionRefusalDto::ShareExceedsSupply,
        PositionError::Arithmetic => PositionRefusalDto::Arithmetic,
    }
}

fn version_dto(value: &PositionVersion) -> PositionVersionDto {
    match value {
        PositionVersion::V1 => PositionVersionDto::V1,
        PositionVersion::V2 => PositionVersionDto::V2,
        PositionVersion::Unknown(discriminator) => PositionVersionDto::Unknown {
            discriminator: discriminator.clone(),
        },
    }
}

fn lifecycle_dto(value: &PositionLifecycle) -> PositionLifecycleDto {
    match value {
        PositionLifecycle::Open => PositionLifecycleDto::Open,
        PositionLifecycle::EmptyOpen => PositionLifecycleDto::EmptyOpen,
        PositionLifecycle::Closed => PositionLifecycleDto::Closed,
        PositionLifecycle::Unknown(discriminator) => PositionLifecycleDto::Unknown {
            discriminator: discriminator.clone(),
        },
    }
}

fn validate_asset_definition(
    public: &AssetDefinitionDto,
    observed: &joshi_liquidity::position::ObservedAssetDefinition,
) -> Result<(), LiquidityProjectionError> {
    if public.asset_id != observed.asset_id
        || public.decimals != observed.decimals
        || public.token_program != observed.token_program
        || public.definition_observation_id != observed.observation_id
    {
        Err(LiquidityProjectionError::AssetDefinitionConflict(
            public.asset_id.to_string(),
        ))
    } else {
        Ok(())
    }
}

fn validate_reward_definitions(
    position: &FreshPosition,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Result<(), LiquidityProjectionError> {
    for bin in &position.state.bins {
        if let AccrualState::ObservedPending { rewards, .. } = &bin.accrual {
            if rewards
                .windows(2)
                .any(|window| window[0].asset_id >= window[1].asset_id)
            {
                return Err(LiquidityProjectionError::Unordered("position rewards"));
            }
            for reward in rewards {
                lookup(definitions, &reward.asset_id)?;
            }
        }
    }
    for action in &position.actions {
        if let LiquidityActionProjectionInput::Remove {
            result: Ok(projection),
            ..
        } = action
            && let Some(rewards) = &projection.claimed_rewards
        {
            if rewards
                .windows(2)
                .any(|window| window[0].asset_id >= window[1].asset_id)
            {
                return Err(LiquidityProjectionError::Unordered("claimed rewards"));
            }
            for reward in rewards {
                lookup(definitions, &reward.asset_id)?;
            }
        }
    }
    Ok(())
}

fn lookup<'a>(
    values: &'a BTreeMap<AssetId, &'a AssetDefinitionDto>,
    asset_id: &AssetId,
) -> Result<&'a AssetDefinitionDto, LiquidityProjectionError> {
    values
        .get(asset_id)
        .copied()
        .ok_or_else(|| LiquidityProjectionError::MissingAssetDefinition(asset_id.to_string()))
}

fn metric_id(prefix: &str, identity: &str, field: &str) -> StableString {
    let digest = Sha256::digest(format!("{prefix}\0{identity}\0{field}").as_bytes());
    StableString::new(format!("metric:sha256:{digest:x}"))
        .expect("fixed-width digest metric identity is valid")
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("static projection label is valid")
}

/// Liquidity-to-wire projection failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum LiquidityProjectionError {
    #[error("duplicate asset definition")]
    DuplicateAssetDefinition,
    #[error("missing asset definition: {0}")]
    MissingAssetDefinition(String),
    #[error("liquidity asset definition conflicts with public metadata: {0}")]
    AssetDefinitionConflict(String),
    #[error("liquidity projection input is not strictly ordered: {0}")]
    Unordered(&'static str),
    #[error("invalid position freshness: {0}")]
    Freshness(&'static str),
}
