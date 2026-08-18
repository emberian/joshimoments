//! Finalized wallet, lots, basis, runner, and episode projection DTOs.

use std::collections::BTreeMap;

use joshi_accounting::{
    accounting::{CashEpoch, ClassificationProjection},
    amount::{AtomQty, SignedAtoms, TotalAtoms},
    basis::{Basis, BasisQuality, ExactRatio},
    effect::FinalizedWalletEffect,
    episode::{EpisodePhase, EpisodeProjection, EpochStatus},
    lots::{CapitalRecovery, Lot, LotOrigin, RealizedComponent},
    model::{AssetKey, WalletSnapshot},
};
use joshi_domain::{
    AccountId, CommitSeq, EpisodeId, LotId, ObservationId, QuoteId, StableString, WalletEffectId,
    WireU64,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    AssetDefinitionDto, AtomicAmountDto, ExactRatioDto, MetricReading, SignedAtomicAmountDto,
};

/// Finalized effect plus the exact observations from which before/after state was decoded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidencedWalletEffect {
    pub effect: FinalizedWalletEffect,
    pub evidence: Vec<ObservationId>,
    pub landed_commit: CommitSeq,
    pub classification: ClassificationProjection,
}

/// Realized calculation contextualized without changing the wallet-effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RealizedInput {
    pub effect_id: WalletEffectId,
    pub episode_id: Option<EpisodeId>,
    pub epoch_index: Option<u32>,
    pub components: BTreeMap<AssetKey, RealizedComponent>,
}

impl RealizedInput {
    /// Extracts realized components from a disposal classification.
    #[must_use]
    pub fn from_classification(
        effect_id: WalletEffectId,
        episode_id: Option<EpisodeId>,
        epoch_index: Option<u32>,
        classification: &ClassificationProjection,
    ) -> Option<Self> {
        let ClassificationProjection::Disposal { realized, .. } = classification else {
            return None;
        };
        Some(Self {
            effect_id,
            episode_id,
            epoch_index,
            components: realized.clone(),
        })
    }
}

/// Explicit cash-recovery fact for one episode epoch and reference asset.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapitalRecoveryInput {
    pub epoch: CashEpoch,
    pub status: CapitalRecovery,
}

/// Episode interpretation with the asset whose quantity is attributed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidencedEpisode {
    pub asset_id: AssetKey,
    pub projection: EpisodeProjection,
}

/// Unrealized value is admitted only from an independently named full liquidation quote.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnrealizedInput {
    pub asset_id: AssetKey,
    pub reference_asset_id: AssetKey,
    pub liquidation_quote_id: QuoteId,
    pub basis_quality: BasisQuality,
    pub liquidation_proceeds: ExactRatio,
    pub remaining_known_basis: ExactRatio,
}

/// Complete pure input assembled by the evidence adapter after accounting projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountingProjectionInput {
    pub asset_definitions: Vec<AssetDefinitionDto>,
    pub finalized_snapshot: WalletSnapshot,
    pub snapshot_evidence: Vec<ObservationId>,
    /// Assets whose inventory is intentionally governed by this lot projection.
    pub inventory_asset_ids: Vec<AssetKey>,
    pub effects: Vec<EvidencedWalletEffect>,
    pub lots: Vec<Lot>,
    pub realized: Vec<RealizedInput>,
    pub episodes: Vec<EvidencedEpisode>,
    pub capital_recovery: Vec<CapitalRecoveryInput>,
    pub unrealized: Vec<UnrealizedInput>,
}

/// Basis quality retained in the public contract.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BasisQualityDto {
    Known,
    Estimated,
    Partial,
    Unknown,
}

impl From<BasisQuality> for BasisQualityDto {
    fn from(value: BasisQuality) -> Self {
        match value {
            BasisQuality::Known => Self::Known,
            BasisQuality::Estimated => Self::Estimated,
            BasisQuality::Partial => Self::Partial,
            BasisQuality::Unknown => Self::Unknown,
        }
    }
}

/// One exact known commodity component of basis or result.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RationalAssetComponentDto {
    pub asset_id: AssetKey,
    pub atoms: ExactRatioDto,
}

/// Exact known basis vector plus honest quality.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BasisDto {
    pub quality: BasisQualityDto,
    pub known_components: Vec<RationalAssetComponentDto>,
}

impl From<&Basis> for BasisDto {
    fn from(value: &Basis) -> Self {
        Self {
            quality: value.quality.into(),
            known_components: value
                .known
                .iter()
                .map(|(asset_id, atoms)| RationalAssetComponentDto {
                    asset_id: asset_id.clone(),
                    atoms: ExactRatioDto::from_exact(atoms),
                })
                .collect(),
        }
    }
}

/// One exact finalized account balance. Absence from a snapshot is never represented here as zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LandedBalanceDto {
    pub account_id: AccountId,
    pub amount: AtomicAmountDto,
    pub finality: FinalityDto,
    pub evidence: Vec<ObservationId>,
}

/// Closed finality for financial facts accepted by this projection.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FinalityDto {
    Finalized,
}

/// One account-level before/after change inside a finalized wallet effect.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AccountEffectDto {
    pub account_id: AccountId,
    pub before: AtomicAmountDto,
    pub after: AtomicAmountDto,
    pub change: SignedAtomicAmountDto,
}

/// Classification status retained independently of exact landed effect truth.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum EffectClassificationDto {
    Acquisition,
    Disposal { allocated_basis: BasisDto },
    ExternalInflowUnknown,
    ExternalOutflow { transferred_basis: BasisDto },
    CustodyOnly,
    Unclassified,
}

/// Finalized landed wallet effect and its evidence closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LandedEffectDto {
    pub effect_id: WalletEffectId,
    pub landed_commit: CommitSeq,
    pub finality: FinalityDto,
    pub evidence: Vec<ObservationId>,
    pub account_effects: Vec<AccountEffectDto>,
    pub aggregate_change: Vec<SignedAtomicAmountDto>,
    pub classification: EffectClassificationDto,
}

/// Origin of an accounting lot.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LotOriginDto {
    Acquisition,
    ExternalInflow,
}

/// One basis epoch reference; episode attribution is not ledger truth.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BasisEpochDto {
    pub episode_id: EpisodeId,
    pub epoch_index: WireU64,
}

/// Remaining inventory lot, including fully consumed lots for reproducible history.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LotDto {
    pub lot_id: LotId,
    pub original_quantity: AtomicAmountDto,
    pub remaining_quantity: AtomicAmountDto,
    pub remaining_basis: BasisDto,
    pub origin: LotOriginDto,
    pub basis_epoch: Option<BasisEpochDto>,
}

/// Retained-runner state is quantity exposure, not a declaration that remaining basis is free.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum RunnerStateDto {
    None,
    Retained { lot_ids: Vec<LotId> },
}

/// Reconciliation of observed aggregate inventory against classified lots.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InventoryAssetDto {
    pub observed: AtomicAmountDto,
    pub classified_lots: AtomicAmountDto,
    pub wallet_minus_lots_residual: SignedAtomicAmountDto,
    pub remaining_basis: BasisDto,
    pub runner: RunnerStateDto,
}

/// Realized result for one disposal component.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RealizedComponentDto {
    pub reference_asset_id: AssetKey,
    pub proceeds: ExactRatioDto,
    pub allocated_known_basis: ExactRatioDto,
    pub result: MetricReading<ExactRatioDto>,
    pub basis_quality: BasisQualityDto,
}

/// Realized event attribution; this cannot alter the landed effect.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RealizedResultDto {
    pub effect_id: WalletEffectId,
    pub episode_id: Option<EpisodeId>,
    pub epoch_index: Option<WireU64>,
    pub components: Vec<RealizedComponentDto>,
}

/// Unrealized result tied to one exact whole-position quote, never a reserve-ratio mark.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UnrealizedResultDto {
    pub asset_id: AssetKey,
    pub reference_asset_id: AssetKey,
    pub liquidation_quote_id: QuoteId,
    pub liquidation_proceeds: ExactRatioDto,
    pub remaining_known_basis: ExactRatioDto,
    pub result: MetricReading<ExactRatioDto>,
    pub basis_quality: BasisQualityDto,
}

/// Operator episode phase.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpisodePhaseDto {
    OpenFlat,
    Invested,
    WatchingFlat,
    Closed,
}

/// Inventory epoch status.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpochStatusDto {
    Open,
    Closed,
}

/// One explicit zero-to-nonzero-to-zero inventory epoch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InventoryEpochDto {
    pub epoch_index: WireU64,
    pub status: EpochStatusDto,
    pub opened_by_effect_id: WalletEffectId,
    pub closed_by_effect_id: Option<WalletEffectId>,
}

/// Non-ledger episode interpretation, including watching-flat and re-entry epochs.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeDto {
    pub episode_id: EpisodeId,
    pub phase: EpisodePhaseDto,
    pub attributed_quantity: AtomicAmountDto,
    pub epochs: Vec<InventoryEpochDto>,
}

/// Cash recovery is neither realized `PnL` nor a basis rewrite.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum CapitalRecoveryStatusDto {
    NoCapitalRecorded,
    NotRecovered { shortfall: AtomicAmountDto },
    Recovered { excess: AtomicAmountDto },
}

/// Exact per-epoch cash recovery state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapitalRecoveryDto {
    pub episode_id: EpisodeId,
    pub epoch_index: WireU64,
    pub reference_asset_id: AssetKey,
    pub recovery: CapitalRecoveryStatusDto,
}

/// Complete accounting portion of the public read projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AccountingProjectionDto {
    pub asset_definitions: Vec<AssetDefinitionDto>,
    pub landed_balances: Vec<LandedBalanceDto>,
    pub landed_effects: Vec<LandedEffectDto>,
    pub inventory: Vec<InventoryAssetDto>,
    pub lots: Vec<LotDto>,
    pub realized: Vec<RealizedResultDto>,
    pub unrealized: Vec<UnrealizedResultDto>,
    pub episodes: Vec<EpisodeDto>,
    pub capital_recovery: Vec<CapitalRecoveryDto>,
}

/// Projects strict accounting output from public accounting-kernel values.
///
/// # Errors
///
/// Refuses missing metadata, unsorted/duplicated state, broken effect chains, overflow, and
/// unrealized calculations that claim known result from partial/unknown basis.
#[allow(clippy::too_many_lines)] // The join is easier to audit when all accounting output is adjacent.
pub fn project_accounting(
    input: &AccountingProjectionInput,
) -> Result<AccountingProjectionDto, AccountingProjectionError> {
    let definitions = definitions(&input.asset_definitions)?;
    validate_order(input)?;
    validate_effect_chain(&input.effects, &input.finalized_snapshot)?;

    let mut landed_balances = Vec::with_capacity(input.finalized_snapshot.balances.len());
    let mut observed = BTreeMap::<AssetKey, TotalAtoms>::new();
    for (key, atoms) in &input.finalized_snapshot.balances {
        let definition = definition(&definitions, &key.asset)?;
        landed_balances.push(LandedBalanceDto {
            account_id: key.account.clone(),
            amount: AtomicAmountDto::from_u64(definition, atoms.get()),
            finality: FinalityDto::Finalized,
            evidence: input.snapshot_evidence.clone(),
        });
        add_total(&mut observed, &key.asset, *atoms)?;
    }

    let mut classified = BTreeMap::<AssetKey, TotalAtoms>::new();
    let mut basis = BTreeMap::<AssetKey, Basis>::new();
    let mut runner_ids = BTreeMap::<AssetKey, Vec<LotId>>::new();
    let lots = input
        .lots
        .iter()
        .map(|lot| {
            let definition = definition(&definitions, &lot.asset)?;
            add_total(&mut classified, &lot.asset, lot.remaining_quantity)?;
            if lot.remaining_quantity != AtomQty::ZERO {
                basis
                    .entry(lot.asset.clone())
                    .and_modify(|value| *value = value.merged_with(&lot.remaining_basis))
                    .or_insert_with(|| lot.remaining_basis.clone());
            }
            if lot.remaining_quantity != AtomQty::ZERO
                && lot.remaining_quantity < lot.original_quantity
            {
                runner_ids
                    .entry(lot.asset.clone())
                    .or_default()
                    .push(lot.id.clone());
            }
            Ok(LotDto {
                lot_id: lot.id.clone(),
                original_quantity: AtomicAmountDto::from_u64(
                    definition,
                    lot.original_quantity.get(),
                ),
                remaining_quantity: AtomicAmountDto::from_u64(
                    definition,
                    lot.remaining_quantity.get(),
                ),
                remaining_basis: BasisDto::from(&lot.remaining_basis),
                origin: match lot.origin {
                    LotOrigin::Acquisition => LotOriginDto::Acquisition,
                    LotOrigin::ExternalInflow => LotOriginDto::ExternalInflow,
                },
                basis_epoch: lot.epoch.as_ref().map(|epoch| BasisEpochDto {
                    episode_id: epoch.episode.clone(),
                    epoch_index: WireU64::new(u64::from(epoch.index)),
                }),
            })
        })
        .collect::<Result<Vec<_>, AccountingProjectionError>>()?;

    let inventory = input
        .inventory_asset_ids
        .iter()
        .map(|asset| {
            let definition = definition(&definitions, asset)?;
            let observed_atoms = observed.get(asset).copied().unwrap_or(TotalAtoms::ZERO);
            let lot_atoms = classified.get(asset).copied().unwrap_or(TotalAtoms::ZERO);
            let residual = SignedAtoms::between(lot_atoms, observed_atoms);
            let remaining_basis = basis.get(asset).cloned().unwrap_or_else(empty_basis);
            let runner = runner_ids
                .remove(asset)
                .map_or(RunnerStateDto::None, |ids| RunnerStateDto::Retained {
                    lot_ids: ids,
                });
            Ok(InventoryAssetDto {
                observed: AtomicAmountDto::from_total(definition, observed_atoms),
                classified_lots: AtomicAmountDto::from_total(definition, lot_atoms),
                wallet_minus_lots_residual: SignedAtomicAmountDto::from_signed(
                    definition, residual,
                ),
                remaining_basis: BasisDto::from(&remaining_basis),
                runner,
            })
        })
        .collect::<Result<Vec<_>, AccountingProjectionError>>()?;

    Ok(AccountingProjectionDto {
        asset_definitions: input.asset_definitions.clone(),
        landed_balances,
        landed_effects: input
            .effects
            .iter()
            .map(|value| effect_dto(value, &definitions))
            .collect::<Result<Vec<_>, _>>()?,
        inventory,
        lots,
        realized: input.realized.iter().map(realized_dto).collect(),
        unrealized: input.unrealized.iter().map(unrealized_dto).collect(),
        episodes: input
            .episodes
            .iter()
            .map(|value| episode_dto(value, &definitions))
            .collect::<Result<Vec<_>, _>>()?,
        capital_recovery: input
            .capital_recovery
            .iter()
            .map(|value| recovery_dto(value, &definitions))
            .collect::<Result<Vec<_>, _>>()?,
    })
}

fn definitions(
    values: &[AssetDefinitionDto],
) -> Result<BTreeMap<AssetKey, &AssetDefinitionDto>, AccountingProjectionError> {
    let mut result = BTreeMap::new();
    for value in values {
        if result.insert(value.asset_id.clone(), value).is_some() {
            return Err(AccountingProjectionError::DuplicateAssetDefinition(
                value.asset_id.to_string(),
            ));
        }
    }
    if values
        .windows(2)
        .any(|window| window[0].asset_id >= window[1].asset_id)
    {
        return Err(AccountingProjectionError::UnorderedInput(
            "asset definitions",
        ));
    }
    Ok(result)
}

fn definition<'a>(
    definitions: &'a BTreeMap<AssetKey, &'a AssetDefinitionDto>,
    asset: &AssetKey,
) -> Result<&'a AssetDefinitionDto, AccountingProjectionError> {
    definitions
        .get(asset)
        .copied()
        .ok_or_else(|| AccountingProjectionError::MissingAssetDefinition(asset.to_string()))
}

fn validate_order(input: &AccountingProjectionInput) -> Result<(), AccountingProjectionError> {
    if input.snapshot_evidence.is_empty()
        || input
            .snapshot_evidence
            .windows(2)
            .any(|window| window[0] >= window[1])
    {
        return Err(AccountingProjectionError::UnorderedInput(
            "snapshot evidence",
        ));
    }
    if input
        .effects
        .windows(2)
        .any(|window| window[0].landed_commit >= window[1].landed_commit)
    {
        return Err(AccountingProjectionError::UnorderedInput("effects"));
    }
    if input.inventory_asset_ids.is_empty()
        || input
            .inventory_asset_ids
            .windows(2)
            .any(|window| window[0] >= window[1])
    {
        return Err(AccountingProjectionError::UnorderedInput(
            "inventory assets",
        ));
    }
    if input
        .lots
        .windows(2)
        .any(|window| window[0].id >= window[1].id)
    {
        return Err(AccountingProjectionError::UnorderedInput("lots"));
    }
    if input
        .episodes
        .windows(2)
        .any(|window| window[0].projection.id >= window[1].projection.id)
    {
        return Err(AccountingProjectionError::UnorderedInput("episodes"));
    }
    for effect in &input.effects {
        if effect.evidence.is_empty()
            || effect
                .evidence
                .windows(2)
                .any(|window| window[0] >= window[1])
        {
            return Err(AccountingProjectionError::UnorderedInput("effect evidence"));
        }
    }
    Ok(())
}

fn validate_effect_chain(
    effects: &[EvidencedWalletEffect],
    snapshot: &WalletSnapshot,
) -> Result<(), AccountingProjectionError> {
    if effects
        .windows(2)
        .any(|window| window[0].effect.aggregate_after != window[1].effect.aggregate_before)
    {
        return Err(AccountingProjectionError::BrokenEffectChain);
    }
    let Some(last) = effects.last() else {
        return Ok(());
    };
    let mut aggregate = BTreeMap::new();
    for (key, atoms) in &snapshot.balances {
        add_total(&mut aggregate, &key.asset, *atoms)?;
    }
    aggregate.retain(|_, amount| *amount != TotalAtoms::ZERO);
    if last.effect.aggregate_after != aggregate {
        return Err(AccountingProjectionError::EffectSnapshotMismatch);
    }
    Ok(())
}

fn effect_dto(
    value: &EvidencedWalletEffect,
    definitions: &BTreeMap<AssetKey, &AssetDefinitionDto>,
) -> Result<LandedEffectDto, AccountingProjectionError> {
    let account_effects = value
        .effect
        .account_effects
        .iter()
        .map(|effect| {
            let definition = definition(definitions, &effect.asset)?;
            Ok(AccountEffectDto {
                account_id: effect.account.clone(),
                before: AtomicAmountDto::from_u64(definition, effect.before.get()),
                after: AtomicAmountDto::from_u64(definition, effect.after.get()),
                change: SignedAtomicAmountDto::from_signed(definition, effect.change),
            })
        })
        .collect::<Result<Vec<_>, AccountingProjectionError>>()?;
    let aggregate_change = value
        .effect
        .aggregate_change
        .iter()
        .map(|(asset, change)| {
            definition(definitions, asset)
                .map(|definition| SignedAtomicAmountDto::from_signed(definition, *change))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(LandedEffectDto {
        effect_id: value.effect.id.clone(),
        landed_commit: value.landed_commit,
        finality: FinalityDto::Finalized,
        evidence: value.evidence.clone(),
        account_effects,
        aggregate_change,
        classification: classification_dto(&value.classification),
    })
}

fn classification_dto(value: &ClassificationProjection) -> EffectClassificationDto {
    match value {
        ClassificationProjection::Acquisition => EffectClassificationDto::Acquisition,
        ClassificationProjection::Disposal {
            allocated_basis, ..
        } => EffectClassificationDto::Disposal {
            allocated_basis: BasisDto::from(allocated_basis),
        },
        ClassificationProjection::ExternalInflowUnknown => {
            EffectClassificationDto::ExternalInflowUnknown
        }
        ClassificationProjection::ExternalOutflow { transferred_basis } => {
            EffectClassificationDto::ExternalOutflow {
                transferred_basis: BasisDto::from(transferred_basis),
            }
        }
        ClassificationProjection::CustodyOnly => EffectClassificationDto::CustodyOnly,
        ClassificationProjection::Unclassified => EffectClassificationDto::Unclassified,
    }
}

fn realized_dto(value: &RealizedInput) -> RealizedResultDto {
    RealizedResultDto {
        effect_id: value.effect_id.clone(),
        episode_id: value.episode_id.clone(),
        epoch_index: value
            .epoch_index
            .map(|index| WireU64::new(u64::from(index))),
        components: value
            .components
            .iter()
            .map(|(asset, component)| RealizedComponentDto {
                reference_asset_id: asset.clone(),
                proceeds: ExactRatioDto::from_exact(&component.proceeds),
                allocated_known_basis: ExactRatioDto::from_exact(&component.allocated_known_basis),
                result: component.result.as_ref().map_or_else(
                    || MetricReading::Unknown {
                        reason: stable("basis_not_known_enough"),
                    },
                    |result| MetricReading::Known {
                        value: ExactRatioDto::from_exact(result),
                    },
                ),
                basis_quality: component.quality.into(),
            })
            .collect(),
    }
}

fn unrealized_dto(value: &UnrealizedInput) -> UnrealizedResultDto {
    let result = match value.basis_quality {
        BasisQuality::Known | BasisQuality::Estimated => MetricReading::Known {
            value: ExactRatioDto::from_exact(
                &value.liquidation_proceeds.sub(&value.remaining_known_basis),
            ),
        },
        BasisQuality::Partial | BasisQuality::Unknown => MetricReading::Unknown {
            reason: stable("basis_not_known_enough"),
        },
    };
    UnrealizedResultDto {
        asset_id: value.asset_id.clone(),
        reference_asset_id: value.reference_asset_id.clone(),
        liquidation_quote_id: value.liquidation_quote_id.clone(),
        liquidation_proceeds: ExactRatioDto::from_exact(&value.liquidation_proceeds),
        remaining_known_basis: ExactRatioDto::from_exact(&value.remaining_known_basis),
        result,
        basis_quality: value.basis_quality.into(),
    }
}

fn episode_dto(
    value: &EvidencedEpisode,
    definitions: &BTreeMap<AssetKey, &AssetDefinitionDto>,
) -> Result<EpisodeDto, AccountingProjectionError> {
    let projection = &value.projection;
    let definition = definition(definitions, &value.asset_id)?;
    Ok(EpisodeDto {
        episode_id: projection.id.clone(),
        phase: match projection.phase {
            EpisodePhase::OpenFlat => EpisodePhaseDto::OpenFlat,
            EpisodePhase::Invested => EpisodePhaseDto::Invested,
            EpisodePhase::WatchingFlat => EpisodePhaseDto::WatchingFlat,
            EpisodePhase::Closed => EpisodePhaseDto::Closed,
        },
        attributed_quantity: AtomicAmountDto::from_u64(
            definition,
            projection.attributed_quantity.get(),
        ),
        epochs: projection
            .epochs
            .iter()
            .map(|epoch| InventoryEpochDto {
                epoch_index: WireU64::new(u64::from(epoch.index)),
                status: match epoch.status {
                    EpochStatus::Open => EpochStatusDto::Open,
                    EpochStatus::Closed => EpochStatusDto::Closed,
                },
                opened_by_effect_id: epoch.opened_by.clone(),
                closed_by_effect_id: epoch.closed_by.clone(),
            })
            .collect(),
    })
}

fn recovery_dto(
    value: &CapitalRecoveryInput,
    definitions: &BTreeMap<AssetKey, &AssetDefinitionDto>,
) -> Result<CapitalRecoveryDto, AccountingProjectionError> {
    let definition = definition(definitions, &value.epoch.asset)?;
    let recovery = match value.status {
        CapitalRecovery::NoCapitalRecorded => CapitalRecoveryStatusDto::NoCapitalRecorded,
        CapitalRecovery::NotRecovered { shortfall } => CapitalRecoveryStatusDto::NotRecovered {
            shortfall: AtomicAmountDto::from_total(definition, shortfall),
        },
        CapitalRecovery::Recovered { excess } => CapitalRecoveryStatusDto::Recovered {
            excess: AtomicAmountDto::from_total(definition, excess),
        },
    };
    Ok(CapitalRecoveryDto {
        episode_id: value.epoch.episode.clone(),
        epoch_index: WireU64::new(u64::from(value.epoch.index)),
        reference_asset_id: value.epoch.asset.clone(),
        recovery,
    })
}

fn add_total(
    values: &mut BTreeMap<AssetKey, TotalAtoms>,
    asset: &AssetKey,
    atoms: AtomQty,
) -> Result<(), AccountingProjectionError> {
    let next = values
        .get(asset)
        .copied()
        .unwrap_or(TotalAtoms::ZERO)
        .checked_add(atoms.into())
        .map_err(|_| AccountingProjectionError::Arithmetic)?;
    values.insert(asset.clone(), next);
    Ok(())
}

fn empty_basis() -> Basis {
    Basis {
        quality: BasisQuality::Known,
        known: BTreeMap::new(),
    }
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("static projection discriminator is valid")
}

/// Accounting-to-wire projection failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AccountingProjectionError {
    #[error("duplicate asset definition: {0}")]
    DuplicateAssetDefinition(String),
    #[error("missing asset definition: {0}")]
    MissingAssetDefinition(String),
    #[error("projection input is not strictly ordered: {0}")]
    UnorderedInput(&'static str),
    #[error("finalized wallet effects are not contiguous")]
    BrokenEffectChain,
    #[error("last finalized effect does not equal the finalized snapshot")]
    EffectSnapshotMismatch,
    #[error("checked accounting projection arithmetic failed")]
    Arithmetic,
}
