//! Mark, size-specific quote, refusal, and whole-liquidation wire adapters.

use std::collections::BTreeMap;

use joshi_domain::{
    AssetId, CommandId, ObservationId, PoolId, ProtocolProfileId, QuoteId, StableString, VenueId,
    WireU64, WireU128,
};
use joshi_market_math::{
    fee::FeeBreakdown,
    profile::{ProtocolFamily, ProtocolProfile},
    quote::{
        ExecutableLiquidation, FormulaId, MarkObservation, QuoteBinding, QuoteCalculation,
        QuoteOutcome, QuoteRefusal, QuoteSize, SpotQuote,
    },
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{
    AssetDefinitionDto, EpistemicClass, ExactMetric, ExactRatioDto, Freshness, MetricReading,
    MetricUnit,
};

/// A mark plus its independent display freshness policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreshMark {
    pub mark_id: StableString,
    pub mark: MarkObservation,
    pub freshness: Freshness,
}

/// A quote calculation plus its independent validity/freshness policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreshQuote {
    pub calculation: QuoteCalculation,
    /// Retained request pair; the kernel calculation binding intentionally does not duplicate it.
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub route_id: StableString,
    pub route_observation_ids: Vec<ObservationId>,
    pub freshness: Freshness,
}

/// Full-position promotion plus independently evaluated validity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreshLiquidation {
    pub full_position_quote_id: StableString,
    pub route_id: StableString,
    pub route_observation_ids: Vec<ObservationId>,
    pub liquidation: ExecutableLiquidation,
    pub freshness: Freshness,
}

/// Protocol family carried into the public artifact.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtocolFamilyDto {
    PumpCurve,
    PumpSwapCanonical,
    PumpSwapNonCanonical,
    MeteoraDlmm,
}

/// Profile identity and exact owned operation-graph provenance.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProtocolProfileDto {
    pub profile_id: ProtocolProfileId,
    pub venue_id: VenueId,
    pub family: ProtocolFamilyDto,
    pub program_identity: StableString,
    pub source_revision: StableString,
}

impl From<&ProtocolProfile> for ProtocolProfileDto {
    fn from(value: &ProtocolProfile) -> Self {
        Self {
            profile_id: value.id.clone(),
            venue_id: value.venue.clone(),
            family: match value.family {
                ProtocolFamily::PumpCurve => ProtocolFamilyDto::PumpCurve,
                ProtocolFamily::PumpSwapCanonical => ProtocolFamilyDto::PumpSwapCanonical,
                ProtocolFamily::PumpSwapNonCanonical => ProtocolFamilyDto::PumpSwapNonCanonical,
                ProtocolFamily::MeteoraDlmm => ProtocolFamilyDto::MeteoraDlmm,
            },
            program_identity: value.program_identity.clone(),
            source_revision: value.source_revision.clone(),
        }
    }
}

/// Exact-base/exact-quote request semantics; unsupported paths remain representable on refusal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum QuoteSizeDto {
    ExactBaseOutBuy { amount: crate::AtomicAmountDto },
    ExactBaseInSell { amount: crate::AtomicAmountDto },
    ExactQuoteInBuy { amount: crate::AtomicAmountDto },
    ExactQuoteOutSell { amount: crate::AtomicAmountDto },
}

/// State and fee observations that actually drove a quote, even on refusal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuoteBindingDto {
    pub quote_id: QuoteId,
    pub intent_command_id: Option<CommandId>,
    pub intended_state_observation_id: Option<ObservationId>,
    pub observed_state_observation_id: ObservationId,
    pub fee_observation_id: ObservationId,
    pub observed_slot: WireU64,
    pub profile: ProtocolProfileDto,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub base_asset_id: AssetId,
    pub quote_asset_id: AssetId,
    pub route_id: StableString,
    pub route_observation_ids: Vec<ObservationId>,
}

/// Formula identifier for deterministic quote provenance.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FormulaDto {
    PumpCurveExactBaseOutBuyV1,
    PumpCurveExactBaseInSellV1,
    PumpSwapExactBaseOutBuyV1,
    PumpSwapExactBaseInSellV1,
}

/// Separately rounded fee components; no display code may recompute their total.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FeeBreakdownDto {
    pub lp: ExactMetric<WireU128>,
    pub protocol: ExactMetric<WireU128>,
    pub creator: ExactMetric<WireU128>,
    pub total: ExactMetric<WireU128>,
}

/// Successful size-specific quote. It does not assert landing or fillability after its state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SpotQuoteDto {
    pub formula: FormulaDto,
    pub input: ExactMetric<WireU128>,
    pub output: ExactMetric<WireU128>,
    pub raw_quote: ExactMetric<WireU128>,
    pub fees: FeeBreakdownDto,
}

/// Closed refusal codes from the exact kernel.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QuoteRefusalDto {
    ZeroSize,
    UnsupportedSizeKind,
    InactiveLifecycle,
    IntendedStateMismatch,
    ProfileMismatch,
    MarketIdentityMismatch,
    InvalidReserveState,
    InsufficientRealBase,
    InsufficientRealQuote,
    NonpositiveEffectiveQuoteReserve,
    MalformedFeeConfiguration,
    CreatorFeeApplicabilityUnknown,
    FeesExceedRawOutput,
    NotAFullLiquidationQuote,
    Arithmetic,
}

/// Exact success/refusal union; refusal never drops the request/observed-state binding.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum QuoteOutcomeDto {
    Success { quote: Box<SpotQuoteDto> },
    Refused { reason: QuoteRefusalDto },
}

/// Immutable quote artifact with exact freshness.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuoteProjectionDto {
    pub binding: QuoteBindingDto,
    pub requested_size: QuoteSizeDto,
    pub freshness: Freshness,
    pub outcome: QuoteOutcomeDto,
}

/// Reduced reserve-ratio mark. It carries no capacity or executable semantics.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MarkProjectionDto {
    pub mark_id: StableString,
    pub profile_id: ProtocolProfileId,
    pub venue_id: VenueId,
    pub pool_id: PoolId,
    pub observation_id: ObservationId,
    pub slot: WireU64,
    pub freshness: Freshness,
    pub atomic_price: ExactMetric<ExactRatioDto>,
}

/// State-conditioned full-position sell quote, not current execution or landed disposal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FullPositionQuoteProjectionDto {
    pub full_position_quote_id: StableString,
    pub route_id: StableString,
    pub route_observation_ids: Vec<ObservationId>,
    pub quote_id: QuoteId,
    pub full_position: ExactMetric<WireU128>,
    pub expected_output: ExactMetric<WireU128>,
    pub freshness: Freshness,
}

/// Complete market portion of the read projection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MarketProjectionDto {
    pub marks: Vec<MarkProjectionDto>,
    pub quotes: Vec<QuoteProjectionDto>,
    pub full_position_quotes: Vec<FullPositionQuoteProjectionDto>,
}

/// Adapts exact market-kernel outputs into a deterministic wire DTO.
///
/// # Errors
///
/// Refuses missing asset metadata, malformed freshness, unordered identities, or fee overflow.
pub fn project_market(
    definitions: &[AssetDefinitionDto],
    marks: &[FreshMark],
    quotes: &[FreshQuote],
    liquidations: &[FreshLiquidation],
) -> Result<MarketProjectionDto, MarketProjectionError> {
    let definitions = definition_map(definitions)?;
    validate_order(marks, quotes, liquidations)?;
    for freshness in marks
        .iter()
        .map(|value| &value.freshness)
        .chain(quotes.iter().map(|value| &value.freshness))
        .chain(liquidations.iter().map(|value| &value.freshness))
    {
        freshness
            .validate()
            .map_err(MarketProjectionError::Freshness)?;
    }
    Ok(MarketProjectionDto {
        marks: marks.iter().map(mark_dto).collect(),
        quotes: quotes
            .iter()
            .map(|value| quote_dto(value, &definitions))
            .collect::<Result<Vec<_>, _>>()?,
        full_position_quotes: liquidations
            .iter()
            .map(|value| liquidation_dto(value, &definitions))
            .collect::<Result<Vec<_>, _>>()?,
    })
}

fn definition_map(
    values: &[AssetDefinitionDto],
) -> Result<BTreeMap<AssetId, &AssetDefinitionDto>, MarketProjectionError> {
    let mut result = BTreeMap::new();
    for value in values {
        if result.insert(value.asset_id.clone(), value).is_some() {
            return Err(MarketProjectionError::DuplicateAssetDefinition(
                value.asset_id.to_string(),
            ));
        }
    }
    Ok(result)
}

fn validate_order(
    marks: &[FreshMark],
    quotes: &[FreshQuote],
    liquidations: &[FreshLiquidation],
) -> Result<(), MarketProjectionError> {
    if marks
        .windows(2)
        .any(|window| window[0].mark_id >= window[1].mark_id)
    {
        return Err(MarketProjectionError::Unordered("marks"));
    }
    if quotes.windows(2).any(|window| {
        window[0].calculation.binding.quote_id >= window[1].calculation.binding.quote_id
    }) {
        return Err(MarketProjectionError::Unordered("quotes"));
    }
    if liquidations
        .windows(2)
        .any(|window| window[0].full_position_quote_id >= window[1].full_position_quote_id)
    {
        return Err(MarketProjectionError::Unordered("liquidations"));
    }
    Ok(())
}

fn mark_dto(value: &FreshMark) -> MarkProjectionDto {
    let price = value.mark.atomic_price;
    MarkProjectionDto {
        mark_id: value.mark_id.clone(),
        profile_id: value.mark.profile_id.clone(),
        venue_id: value.mark.venue_id.clone(),
        pool_id: value.mark.pool_id.clone(),
        observation_id: value.mark.observation_id.clone(),
        slot: value.mark.slot,
        freshness: value.freshness.clone(),
        atomic_price: ExactMetric {
            metric_id: metric_id("mark", value.mark_id.as_str(), "atomic_price"),
            semantic_label: stable("reserve_ratio_mark_not_executable"),
            epistemic_class: EpistemicClass::DeterministicCalculation,
            reading: MetricReading::Known {
                value: ExactRatioDto {
                    numerator: price.numerator_quote_atoms().to_string(),
                    denominator: price.denominator_base_atoms().to_string(),
                },
            },
            unit: MetricUnit::AtomicPriceRatio {
                quote_asset_id: value.mark.quote_asset_id.clone(),
                base_asset_id: value.mark.base_asset_id.clone(),
            },
            evidence: vec![value.mark.observation_id.clone()],
            source_value_digest: None,
            rendering_hint: Some(stable("quote atoms per base atom")),
        },
    }
}

fn quote_dto(
    value: &FreshQuote,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Result<QuoteProjectionDto, MarketProjectionError> {
    if value.route_observation_ids.is_empty()
        || value
            .route_observation_ids
            .windows(2)
            .any(|window| window[0] >= window[1])
    {
        return Err(MarketProjectionError::Unordered("quote route observations"));
    }
    let binding = binding_dto(value);
    let requested_size = size_dto(
        value.calculation.requested_size,
        &value.base_asset_id,
        &value.quote_asset_id,
        definitions,
    )?;
    let outcome = match &value.calculation.outcome {
        QuoteOutcome::Success(quote) => {
            validate_success_pair(quote, &value.base_asset_id, &value.quote_asset_id)?;
            QuoteOutcomeDto::Success {
                quote: Box::new(spot_quote_dto(quote, definitions)?),
            }
        }
        QuoteOutcome::Refused(reason) => QuoteOutcomeDto::Refused {
            reason: refusal_dto(reason),
        },
    };
    Ok(QuoteProjectionDto {
        binding,
        requested_size,
        freshness: value.freshness.clone(),
        outcome,
    })
}

fn validate_success_pair(
    quote: &SpotQuote,
    base_asset_id: &AssetId,
    quote_asset_id: &AssetId,
) -> Result<(), MarketProjectionError> {
    let pair_matches = match quote.requested_size {
        QuoteSize::ExactBaseOutBuy(_) | QuoteSize::ExactQuoteInBuy(_) => {
            quote.input.asset_id == *quote_asset_id && quote.output.asset_id == *base_asset_id
        }
        QuoteSize::ExactBaseInSell(_) | QuoteSize::ExactQuoteOutSell(_) => {
            quote.input.asset_id == *base_asset_id && quote.output.asset_id == *quote_asset_id
        }
    };
    if pair_matches {
        Ok(())
    } else {
        Err(MarketProjectionError::RequestPairMismatch)
    }
}

fn binding_dto(value: &FreshQuote) -> QuoteBindingDto {
    let binding = &value.calculation.binding;
    QuoteBindingDto {
        quote_id: binding.quote_id.clone(),
        intent_command_id: binding.intent_command_id.clone(),
        intended_state_observation_id: binding.intended_state_observation.clone(),
        observed_state_observation_id: binding.observed.state_observation_id.clone(),
        fee_observation_id: binding.observed.fee_observation_id.clone(),
        observed_slot: binding.observed.slot,
        profile: ProtocolProfileDto::from(&binding.profile),
        venue_id: binding.venue_id.clone(),
        pool_id: binding.pool_id.clone(),
        base_asset_id: value.base_asset_id.clone(),
        quote_asset_id: value.quote_asset_id.clone(),
        route_id: value.route_id.clone(),
        route_observation_ids: value.route_observation_ids.clone(),
    }
}

fn size_dto(
    value: QuoteSize,
    base_asset_id: &AssetId,
    quote_asset_id: &AssetId,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Result<QuoteSizeDto, MarketProjectionError> {
    let amount = match value {
        QuoteSize::ExactBaseOutBuy(atoms) | QuoteSize::ExactBaseInSell(atoms) => {
            crate::AtomicAmountDto::from_u64(lookup(definitions, base_asset_id)?, atoms.get())
        }
        QuoteSize::ExactQuoteInBuy(atoms) | QuoteSize::ExactQuoteOutSell(atoms) => {
            crate::AtomicAmountDto::from_u64(lookup(definitions, quote_asset_id)?, atoms.get())
        }
    };
    Ok(match value {
        QuoteSize::ExactBaseOutBuy(_) => QuoteSizeDto::ExactBaseOutBuy { amount },
        QuoteSize::ExactBaseInSell(_) => QuoteSizeDto::ExactBaseInSell { amount },
        QuoteSize::ExactQuoteInBuy(_) => QuoteSizeDto::ExactQuoteInBuy { amount },
        QuoteSize::ExactQuoteOutSell(_) => QuoteSizeDto::ExactQuoteOutSell { amount },
    })
}

fn spot_quote_dto(
    value: &SpotQuote,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Result<SpotQuoteDto, MarketProjectionError> {
    let input_definition = lookup(definitions, &value.input.asset_id)?;
    let output_definition = lookup(definitions, &value.output.asset_id)?;
    let quote_definition = match value.requested_size {
        QuoteSize::ExactBaseOutBuy(_) | QuoteSize::ExactQuoteInBuy(_) => input_definition,
        QuoteSize::ExactBaseInSell(_) | QuoteSize::ExactQuoteOutSell(_) => output_definition,
    };
    let quote_id = value.binding.quote_id.as_str();
    Ok(SpotQuoteDto {
        formula: formula_dto(value.formula),
        input: atom_metric(
            metric_id("quote", quote_id, "input"),
            "quote_input",
            input_definition,
            value.input.atoms.get(),
            &value.binding,
        ),
        output: atom_metric(
            metric_id("quote", quote_id, "output"),
            "quote_output",
            output_definition,
            value.output.atoms.get(),
            &value.binding,
        ),
        raw_quote: atom_metric(
            metric_id("quote", quote_id, "raw_quote"),
            "raw_quote_before_fees",
            quote_definition,
            value.raw_quote_atoms.get(),
            &value.binding,
        ),
        fees: fee_dto(value.fees, quote_definition, &value.binding)?,
    })
}

fn fee_dto(
    value: FeeBreakdown,
    definition: &AssetDefinitionDto,
    binding: &QuoteBinding,
) -> Result<FeeBreakdownDto, MarketProjectionError> {
    let total = value
        .checked_total()
        .map_err(|_| MarketProjectionError::FeeOverflow)?;
    let quote_id = binding.quote_id.as_str();
    Ok(FeeBreakdownDto {
        lp: atom_metric(
            metric_id("quote", quote_id, "fee_lp"),
            "lp_fee",
            definition,
            value.lp_atoms,
            binding,
        ),
        protocol: atom_metric(
            metric_id("quote", quote_id, "fee_protocol"),
            "protocol_fee",
            definition,
            value.protocol_atoms,
            binding,
        ),
        creator: atom_metric(
            metric_id("quote", quote_id, "fee_creator"),
            "creator_fee",
            definition,
            value.creator_atoms,
            binding,
        ),
        total: atom_metric(
            metric_id("quote", quote_id, "fee_total"),
            "total_separately_rounded_fees",
            definition,
            total,
            binding,
        ),
    })
}

fn atom_metric(
    id: StableString,
    label: &str,
    definition: &AssetDefinitionDto,
    atoms: u64,
    binding: &QuoteBinding,
) -> ExactMetric<WireU128> {
    ExactMetric {
        metric_id: id,
        semantic_label: stable(label),
        epistemic_class: EpistemicClass::DeterministicCalculation,
        reading: MetricReading::Known {
            value: WireU128::new(u128::from(atoms)),
        },
        unit: MetricUnit::AssetAtoms {
            asset_id: definition.asset_id.clone(),
            decimals: definition.decimals,
            definition_observation_id: definition.definition_observation_id.clone(),
        },
        evidence: binding_evidence(binding),
        source_value_digest: None,
        rendering_hint: None,
    }
}

fn liquidation_dto(
    value: &FreshLiquidation,
    definitions: &BTreeMap<AssetId, &AssetDefinitionDto>,
) -> Result<FullPositionQuoteProjectionDto, MarketProjectionError> {
    if value.route_observation_ids.is_empty()
        || value
            .route_observation_ids
            .windows(2)
            .any(|window| window[0] >= window[1])
    {
        return Err(MarketProjectionError::Unordered(
            "full-position quote route observations",
        ));
    }
    let quote = value.liquidation.quote();
    let input_definition = lookup(definitions, &quote.input.asset_id)?;
    let output_definition = lookup(definitions, &quote.output.asset_id)?;
    let mut full_position = atom_metric(
        metric_id(
            "full_position_quote",
            value.full_position_quote_id.as_str(),
            "full_position",
        ),
        "full_position_input",
        input_definition,
        value.liquidation.full_position_atoms().get(),
        &quote.binding,
    );
    full_position
        .evidence
        .extend(value.route_observation_ids.iter().cloned());
    full_position.evidence.sort();
    full_position.evidence.dedup();
    let mut expected_output = atom_metric(
        metric_id(
            "full_position_quote",
            value.full_position_quote_id.as_str(),
            "expected_output",
        ),
        "state_conditioned_full_position_output_not_landed_or_current_execution",
        output_definition,
        quote.output.atoms.get(),
        &quote.binding,
    );
    expected_output
        .evidence
        .extend(value.route_observation_ids.iter().cloned());
    expected_output.evidence.sort();
    expected_output.evidence.dedup();
    Ok(FullPositionQuoteProjectionDto {
        full_position_quote_id: value.full_position_quote_id.clone(),
        route_id: value.route_id.clone(),
        route_observation_ids: value.route_observation_ids.clone(),
        quote_id: quote.binding.quote_id.clone(),
        full_position,
        expected_output,
        freshness: value.freshness.clone(),
    })
}

fn binding_evidence(binding: &QuoteBinding) -> Vec<ObservationId> {
    let mut evidence = vec![
        binding.observed.state_observation_id.clone(),
        binding.observed.fee_observation_id.clone(),
    ];
    evidence.sort();
    evidence.dedup();
    evidence
}

fn lookup<'a>(
    definitions: &'a BTreeMap<AssetId, &'a AssetDefinitionDto>,
    asset: &AssetId,
) -> Result<&'a AssetDefinitionDto, MarketProjectionError> {
    definitions
        .get(asset)
        .copied()
        .ok_or_else(|| MarketProjectionError::MissingAssetDefinition(asset.to_string()))
}

fn formula_dto(value: FormulaId) -> FormulaDto {
    match value {
        FormulaId::PumpCurveExactBaseOutBuyV1 => FormulaDto::PumpCurveExactBaseOutBuyV1,
        FormulaId::PumpCurveExactBaseInSellV1 => FormulaDto::PumpCurveExactBaseInSellV1,
        FormulaId::PumpSwapExactBaseOutBuyV1 => FormulaDto::PumpSwapExactBaseOutBuyV1,
        FormulaId::PumpSwapExactBaseInSellV1 => FormulaDto::PumpSwapExactBaseInSellV1,
    }
}

fn refusal_dto(value: &QuoteRefusal) -> QuoteRefusalDto {
    match value {
        QuoteRefusal::ZeroSize => QuoteRefusalDto::ZeroSize,
        QuoteRefusal::UnsupportedSizeKind => QuoteRefusalDto::UnsupportedSizeKind,
        QuoteRefusal::InactiveLifecycle => QuoteRefusalDto::InactiveLifecycle,
        QuoteRefusal::IntendedStateMismatch => QuoteRefusalDto::IntendedStateMismatch,
        QuoteRefusal::ProfileMismatch => QuoteRefusalDto::ProfileMismatch,
        QuoteRefusal::MarketIdentityMismatch => QuoteRefusalDto::MarketIdentityMismatch,
        QuoteRefusal::InvalidReserveState => QuoteRefusalDto::InvalidReserveState,
        QuoteRefusal::InsufficientRealBase => QuoteRefusalDto::InsufficientRealBase,
        QuoteRefusal::InsufficientRealQuote => QuoteRefusalDto::InsufficientRealQuote,
        QuoteRefusal::NonpositiveEffectiveQuoteReserve => {
            QuoteRefusalDto::NonpositiveEffectiveQuoteReserve
        }
        QuoteRefusal::MalformedFeeConfiguration => QuoteRefusalDto::MalformedFeeConfiguration,
        QuoteRefusal::CreatorFeeApplicabilityUnknown => {
            QuoteRefusalDto::CreatorFeeApplicabilityUnknown
        }
        QuoteRefusal::FeesExceedRawOutput => QuoteRefusalDto::FeesExceedRawOutput,
        QuoteRefusal::NotAFullLiquidationQuote => QuoteRefusalDto::NotAFullLiquidationQuote,
        QuoteRefusal::Arithmetic => QuoteRefusalDto::Arithmetic,
    }
}

fn metric_id(prefix: &str, identity: &str, field: &str) -> StableString {
    let digest = Sha256::digest(format!("{prefix}\0{identity}\0{field}").as_bytes());
    StableString::new(format!("metric:sha256:{digest:x}"))
        .expect("fixed-width digest metric identity is valid")
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("static projection label is valid")
}

/// Market-to-wire projection failure.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum MarketProjectionError {
    #[error("duplicate asset definition: {0}")]
    DuplicateAssetDefinition(String),
    #[error("missing asset definition: {0}")]
    MissingAssetDefinition(String),
    #[error("market projection input is not strictly ordered: {0}")]
    Unordered(&'static str),
    #[error("invalid quote/mark freshness: {0}")]
    Freshness(&'static str),
    #[error("fee components overflow their atomic width")]
    FeeOverflow,
    #[error("retained quote request pair disagrees with successful kernel output")]
    RequestPairMismatch,
}
