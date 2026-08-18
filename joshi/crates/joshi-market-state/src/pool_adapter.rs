use crate::{
    AssetPairV1, ChainFinality, CreatorFeeV1, DecodedPoolStateV1, DlmmAccrualV1,
    DlmmPositionLifecycleV1, DlmmPositionVersionV1, FeePolicyV1, FeeScheduleV1, PoolAccountRole,
    PoolBundleV1, PoolKind, PoolProjection, ProtocolProfileV1, VenueLifecycleV1,
};
use joshi_accounting::amount::AtomQty;
use joshi_domain::{ObservationId, WireU128};
use joshi_liquidity::{
    position::{
        AccrualState, AssetPairAmounts, DlmmPositionState, ObservedAssetDefinition,
        PositionBinState, PositionLifecycle, PositionVersion, RewardAmount,
    },
    q64::{BinId, BinStep, Q64x64},
};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeePolicy, FeeSchedule, FeeTier},
    profile::{ProtocolFamily, ProtocolProfile, VenueLifecycle},
    pump::{PumpCurveState, PumpSwapState},
};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

/// Strict account-closure or protocol-kernel admission failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PoolAdapterError {
    #[error("pool closure has no account observations")]
    EmptyClosure,
    #[error("pool closure contains duplicate account identity")]
    DuplicateAccount,
    #[error("pool closure is missing required account role {0}")]
    MissingRole(&'static str),
    #[error("pool closure contains a role not admitted for its declared family")]
    UnexpectedRole,
    #[error("pool closure combines more than one chain slot")]
    MixedSlot,
    #[error("pool closure contains a non-finalized account observation")]
    NotFinalized,
    #[error("pool closure carries unsupported account, token-extension, or decoded fields")]
    UnsupportedState,
    #[error("decoded state kind does not match the closure family")]
    FamilyMismatch,
    #[error("decoded state identity or evidence does not match the account closure")]
    IdentityMismatch,
    #[error("signed reserve text is not a canonical i128")]
    InvalidSignedReserve,
    #[error("fee configuration is invalid: {0}")]
    InvalidFee(String),
    #[error("protocol kernel refused the supposedly complete state: {0}")]
    KernelRefusal(String),
}

/// Validates one same-slot finalized closure and invokes the existing exact read-only kernel.
///
/// The returned projection is a reserve mark or withdrawal inventory, not a quote, fill, or
/// executable liquidation value. A caller may only retain quote-capable state when this adapter
/// explicitly admitted the complete closure.
///
/// # Errors
///
/// Refuses missing, mixed-slot, non-finalized, unsupported, identity-incoherent, or kernel-invalid
/// state.
#[allow(clippy::too_many_lines)] // One exhaustive family dispatch keeps admission before kernels.
pub fn adapt_pool_bundle(bundle: &PoolBundleV1) -> Result<PoolProjection, PoolAdapterError> {
    validate_account_closure(bundle)?;
    match (&bundle.pool_kind, &bundle.decoded_state) {
        (PoolKind::PumpCurve, DecodedPoolStateV1::PumpCurve(wire)) => {
            if wire.pool_id != bundle.pool_id || wire.slot != bundle.slot {
                return Err(PoolAdapterError::IdentityMismatch);
            }
            require_observation_role(bundle, &wire.state_observation_id, PoolAccountRole::Curve)?;
            require_observation_role(
                bundle,
                &wire.fee_observation_id,
                PoolAccountRole::FeeConfiguration,
            )?;
            let state = PumpCurveState {
                profile: protocol_profile(&wire.profile, ProtocolFamily::PumpCurve),
                pool_id: wire.pool_id.clone(),
                base_asset_id: wire.base_asset_id.clone(),
                quote_asset_id: wire.quote_asset_id.clone(),
                state_observation_id: wire.state_observation_id.clone(),
                fee_observation_id: wire.fee_observation_id.clone(),
                slot: wire.slot,
                lifecycle: lifecycle(&wire.lifecycle),
                virtual_base_reserves: AtomQty::new(wire.virtual_base_reserves.get()),
                virtual_quote_reserves: AtomQty::new(wire.virtual_quote_reserves.get()),
                real_base_reserves: AtomQty::new(wire.real_base_reserves.get()),
                real_quote_reserves: AtomQty::new(wire.real_quote_reserves.get()),
                base_mint_supply: AtomQty::new(wire.base_mint_supply.get()),
                is_mayhem_mode: wire.is_mayhem_mode,
                fee_policy: fee_policy(&wire.fee_policy)?,
            };
            let mark = state
                .mark()
                .map_err(|error| PoolAdapterError::KernelRefusal(error.to_string()))?;
            Ok(PoolProjection::PumpCurve {
                bundle_id: bundle.bundle_id.clone(),
                pool_id: bundle.pool_id.clone(),
                slot: bundle.slot,
                numerator_quote_atoms: WireU128::new(mark.atomic_price.numerator_quote_atoms()),
                denominator_base_atoms: WireU128::new(mark.atomic_price.denominator_base_atoms()),
                quote_state_admitted: matches!(wire.lifecycle, VenueLifecycleV1::Trading),
            })
        }
        (PoolKind::PumpSwapCanonical, DecodedPoolStateV1::PumpSwapCanonical(wire)) => {
            if wire.pool_id != bundle.pool_id || wire.slot != bundle.slot {
                return Err(PoolAdapterError::IdentityMismatch);
            }
            require_observation_role(bundle, &wire.state_observation_id, PoolAccountRole::Pool)?;
            require_observation_role(
                bundle,
                &wire.fee_observation_id,
                PoolAccountRole::FeeConfiguration,
            )?;
            let signed_reserve = parse_i128(wire.virtual_quote_reserves.as_str())?;
            let state = PumpSwapState {
                profile: protocol_profile(&wire.profile, ProtocolFamily::PumpSwapCanonical),
                pool_id: wire.pool_id.clone(),
                base_asset_id: wire.base_asset_id.clone(),
                quote_asset_id: wire.quote_asset_id.clone(),
                state_observation_id: wire.state_observation_id.clone(),
                fee_observation_id: wire.fee_observation_id.clone(),
                slot: wire.slot,
                lifecycle: lifecycle(&wire.lifecycle),
                base_reserves: AtomQty::new(wire.base_reserves.get()),
                raw_quote_reserves: AtomQty::new(wire.raw_quote_reserves.get()),
                virtual_quote_reserves: signed_reserve,
                base_mint_supply: AtomQty::new(wire.base_mint_supply.get()),
                fee_policy: fee_policy(&wire.fee_policy)?,
            };
            let mark = state
                .mark()
                .map_err(|error| PoolAdapterError::KernelRefusal(error.to_string()))?;
            Ok(PoolProjection::PumpSwapCanonical {
                bundle_id: bundle.bundle_id.clone(),
                pool_id: bundle.pool_id.clone(),
                slot: bundle.slot,
                numerator_quote_atoms: WireU128::new(mark.atomic_price.numerator_quote_atoms()),
                denominator_base_atoms: WireU128::new(mark.atomic_price.denominator_base_atoms()),
                quote_state_admitted: matches!(wire.lifecycle, VenueLifecycleV1::Trading),
            })
        }
        (PoolKind::MeteoraDlmmPosition, DecodedPoolStateV1::MeteoraDlmmPosition(wire)) => {
            if wire.pool_id != bundle.pool_id || wire.slot != bundle.slot {
                return Err(PoolAdapterError::IdentityMismatch);
            }
            require_observation_role(bundle, &wire.observation_id, PoolAccountRole::Position)?;
            require_observation_role(bundle, &wire.token_x.observation_id, PoolAccountRole::MintX)?;
            require_observation_role(bundle, &wire.token_y.observation_id, PoolAccountRole::MintY)?;
            if !wire.unsupported_fields.is_empty()
                || !wire.token_x.unsupported_extensions.is_empty()
                || !wire.token_y.unsupported_extensions.is_empty()
                || wire
                    .bins
                    .iter()
                    .any(|bin| matches!(bin.accrual, DlmmAccrualV1::Unsupported { .. }))
            {
                return Err(PoolAdapterError::UnsupportedState);
            }
            let bin_step = BinStep::new(wire.bin_step_basis_points)
                .map_err(|error| PoolAdapterError::KernelRefusal(error.to_string()))?;
            let state = DlmmPositionState {
                profile: protocol_profile(&wire.profile, ProtocolFamily::MeteoraDlmm),
                venue_id: wire.profile.venue_id.clone(),
                pool_id: wire.pool_id.clone(),
                position_id: wire.position_id.clone(),
                observation_id: wire.observation_id.clone(),
                slot: wire.slot,
                version: match wire.version {
                    DlmmPositionVersionV1::V1 => PositionVersion::V1,
                    DlmmPositionVersionV1::V2 => PositionVersion::V2,
                    DlmmPositionVersionV1::Unsupported => {
                        return Err(PoolAdapterError::UnsupportedState);
                    }
                },
                lifecycle: match wire.lifecycle {
                    DlmmPositionLifecycleV1::Open => PositionLifecycle::Open,
                    DlmmPositionLifecycleV1::EmptyOpen => PositionLifecycle::EmptyOpen,
                    DlmmPositionLifecycleV1::Closed => PositionLifecycle::Closed,
                    DlmmPositionLifecycleV1::Unsupported => {
                        return Err(PoolAdapterError::UnsupportedState);
                    }
                },
                token_x: asset_definition(&wire.token_x),
                token_y: asset_definition(&wire.token_y),
                lower_bin_id: BinId::new(wire.lower_bin_id),
                upper_bin_id: BinId::new(wire.upper_bin_id),
                active_bin_id: BinId::new(wire.active_bin_id),
                bin_step,
                bins: wire
                    .bins
                    .iter()
                    .map(position_bin)
                    .collect::<Result<_, _>>()?,
                unsupported_fields: Vec::new(),
            };
            let inventory = state
                .inventory()
                .map_err(|error| PoolAdapterError::KernelRefusal(error.to_string()))?;
            if !inventory.unsupported_fields.is_empty() {
                return Err(PoolAdapterError::UnsupportedState);
            }
            Ok(PoolProjection::MeteoraDlmmPosition {
                bundle_id: bundle.bundle_id.clone(),
                pool_id: bundle.pool_id.clone(),
                position_id: wire.position_id.clone(),
                slot: bundle.slot,
                principal: pair(inventory.principal),
                pending_fees: inventory.pending_fees.map(pair),
                unsupported_fields: Vec::new(),
                inventory_state_admitted: true,
            })
        }
        _ => Err(PoolAdapterError::FamilyMismatch),
    }
}

fn validate_account_closure(bundle: &PoolBundleV1) -> Result<(), PoolAdapterError> {
    if bundle.accounts.is_empty() {
        return Err(PoolAdapterError::EmptyClosure);
    }
    let mut accounts = BTreeSet::new();
    let mut roles = BTreeMap::<PoolAccountRole, usize>::new();
    for account in &bundle.accounts {
        if !accounts.insert(account.account_id.as_str()) {
            return Err(PoolAdapterError::DuplicateAccount);
        }
        *roles.entry(account.role).or_default() += 1;
        if account.slot != bundle.slot {
            return Err(PoolAdapterError::MixedSlot);
        }
        if account.finality != ChainFinality::Finalized {
            return Err(PoolAdapterError::NotFinalized);
        }
        if account.role == PoolAccountRole::Unsupported || !account.unsupported_fields.is_empty() {
            return Err(PoolAdapterError::UnsupportedState);
        }
    }
    let (required, allowed): (&[PoolAccountRole], &[PoolAccountRole]) = match bundle.pool_kind {
        PoolKind::PumpCurve => (
            &[
                PoolAccountRole::Curve,
                PoolAccountRole::GlobalConfiguration,
                PoolAccountRole::FeeConfiguration,
                PoolAccountRole::BaseMint,
            ],
            &[
                PoolAccountRole::Curve,
                PoolAccountRole::GlobalConfiguration,
                PoolAccountRole::FeeConfiguration,
                PoolAccountRole::BaseMint,
            ],
        ),
        PoolKind::PumpSwapCanonical => (
            &[
                PoolAccountRole::Pool,
                PoolAccountRole::GlobalConfiguration,
                PoolAccountRole::FeeConfiguration,
                PoolAccountRole::BaseMint,
                PoolAccountRole::QuoteMint,
                PoolAccountRole::BaseVault,
                PoolAccountRole::QuoteVault,
            ],
            &[
                PoolAccountRole::Pool,
                PoolAccountRole::GlobalConfiguration,
                PoolAccountRole::FeeConfiguration,
                PoolAccountRole::BaseMint,
                PoolAccountRole::QuoteMint,
                PoolAccountRole::BaseVault,
                PoolAccountRole::QuoteVault,
            ],
        ),
        PoolKind::MeteoraDlmmPosition => (
            &[
                PoolAccountRole::Position,
                PoolAccountRole::LbPair,
                PoolAccountRole::FeeConfiguration,
                PoolAccountRole::ReserveX,
                PoolAccountRole::ReserveY,
                PoolAccountRole::MintX,
                PoolAccountRole::MintY,
                PoolAccountRole::BinArray,
            ],
            &[
                PoolAccountRole::Position,
                PoolAccountRole::LbPair,
                PoolAccountRole::FeeConfiguration,
                PoolAccountRole::ReserveX,
                PoolAccountRole::ReserveY,
                PoolAccountRole::MintX,
                PoolAccountRole::MintY,
                PoolAccountRole::BinArray,
                PoolAccountRole::BitmapExtension,
            ],
        ),
    };
    for role in required {
        if !roles.contains_key(role) {
            return Err(PoolAdapterError::MissingRole(role_name(*role)));
        }
    }
    if roles.keys().any(|role| !allowed.contains(role)) {
        return Err(PoolAdapterError::UnexpectedRole);
    }
    if roles
        .iter()
        .any(|(role, count)| *role != PoolAccountRole::BinArray && *count != 1)
    {
        return Err(PoolAdapterError::DuplicateAccount);
    }
    Ok(())
}

fn require_observation_role(
    bundle: &PoolBundleV1,
    observation_id: &ObservationId,
    role: PoolAccountRole,
) -> Result<(), PoolAdapterError> {
    if bundle
        .accounts
        .iter()
        .any(|account| account.role == role && account.observation_id == *observation_id)
    {
        Ok(())
    } else {
        Err(PoolAdapterError::IdentityMismatch)
    }
}

const fn role_name(role: PoolAccountRole) -> &'static str {
    match role {
        PoolAccountRole::Curve => "curve",
        PoolAccountRole::Pool => "pool",
        PoolAccountRole::Position => "position",
        PoolAccountRole::GlobalConfiguration => "global_configuration",
        PoolAccountRole::FeeConfiguration => "fee_configuration",
        PoolAccountRole::BaseMint => "base_mint",
        PoolAccountRole::QuoteMint => "quote_mint",
        PoolAccountRole::BaseVault => "base_vault",
        PoolAccountRole::QuoteVault => "quote_vault",
        PoolAccountRole::LbPair => "lb_pair",
        PoolAccountRole::ReserveX => "reserve_x",
        PoolAccountRole::ReserveY => "reserve_y",
        PoolAccountRole::MintX => "mint_x",
        PoolAccountRole::MintY => "mint_y",
        PoolAccountRole::BinArray => "bin_array",
        PoolAccountRole::BitmapExtension => "bitmap_extension",
        PoolAccountRole::Unsupported => "unsupported",
    }
}

fn protocol_profile(wire: &ProtocolProfileV1, family: ProtocolFamily) -> ProtocolProfile {
    ProtocolProfile {
        id: wire.id.clone(),
        venue: wire.venue_id.clone(),
        family,
        program_identity: wire.program_identity.clone(),
        source_revision: wire.source_revision.clone(),
    }
}

fn lifecycle(value: &VenueLifecycleV1) -> VenueLifecycle {
    match value {
        VenueLifecycleV1::Trading => VenueLifecycle::Trading,
        VenueLifecycleV1::Complete => VenueLifecycle::Complete,
        VenueLifecycleV1::Migrated => VenueLifecycle::Migrated,
        VenueLifecycleV1::Disabled => VenueLifecycle::Disabled,
        VenueLifecycleV1::Unknown(detail) => VenueLifecycle::Unknown(detail.clone()),
    }
}

fn fee_policy(wire: &FeePolicyV1) -> Result<FeePolicy, PoolAdapterError> {
    match wire {
        FeePolicyV1::Flat(schedule) => fee_schedule(schedule).map(FeePolicy::Flat),
        FeePolicyV1::MarketCapTiers(tiers) => tiers
            .iter()
            .map(|tier| {
                Ok(FeeTier {
                    threshold_quote_atoms: tier.threshold_quote_atoms.get(),
                    schedule: fee_schedule(&tier.schedule)?,
                })
            })
            .collect::<Result<Vec<_>, PoolAdapterError>>()
            .map(FeePolicy::MarketCapTiers),
    }
}

fn fee_schedule(wire: &FeeScheduleV1) -> Result<FeeSchedule, PoolAdapterError> {
    let rate =
        |value| FeeBps::new(value).map_err(|error| PoolAdapterError::InvalidFee(error.to_string()));
    Ok(FeeSchedule {
        lp: rate(wire.lp_basis_points)?,
        protocol: rate(wire.protocol_basis_points)?,
        creator: match wire.creator {
            CreatorFeeV1::NotApplicable => CreatorFee::NotApplicable,
            CreatorFeeV1::Charged(value) => CreatorFee::Charged(rate(value)?),
            CreatorFeeV1::Unknown => CreatorFee::Unknown,
        },
    })
}

fn parse_i128(value: &str) -> Result<i128, PoolAdapterError> {
    let parsed = value
        .parse::<i128>()
        .map_err(|_| PoolAdapterError::InvalidSignedReserve)?;
    if parsed.to_string() == value {
        Ok(parsed)
    } else {
        Err(PoolAdapterError::InvalidSignedReserve)
    }
}

fn asset_definition(wire: &crate::TokenDefinitionV1) -> ObservedAssetDefinition {
    ObservedAssetDefinition {
        asset_id: wire.asset_id.clone(),
        decimals: wire.decimals,
        token_program: wire.token_program.clone(),
        observation_id: wire.observation_id.clone(),
    }
}

fn position_bin(wire: &crate::DlmmBinV1) -> Result<PositionBinState, PoolAdapterError> {
    Ok(PositionBinState {
        bin_id: BinId::new(wire.bin_id),
        price_q64: Q64x64::from_bits(wire.price_q64.get()),
        pool_amounts: amounts(&wire.pool_amounts),
        liquidity_supply: wire.liquidity_supply.get(),
        position_share: wire.position_share.get(),
        accrual: match &wire.accrual {
            DlmmAccrualV1::Observed { fees, rewards } => AccrualState::ObservedPending {
                fees: amounts(fees),
                rewards: rewards
                    .iter()
                    .map(|reward| RewardAmount {
                        asset_id: reward.asset_id.clone(),
                        atoms: AtomQty::new(reward.atoms.get()),
                    })
                    .collect(),
            },
            DlmmAccrualV1::Unsupported { .. } => {
                return Err(PoolAdapterError::UnsupportedState);
            }
        },
    })
}

const fn amounts(value: &AssetPairV1) -> AssetPairAmounts {
    AssetPairAmounts {
        x: AtomQty::new(value.x_atoms.get()),
        y: AtomQty::new(value.y_atoms.get()),
    }
}

const fn pair(value: AssetPairAmounts) -> AssetPairV1 {
    AssetPairV1 {
        x_atoms: joshi_domain::WireU64::new(value.x.get()),
        y_atoms: joshi_domain::WireU64::new(value.y.get()),
    }
}
