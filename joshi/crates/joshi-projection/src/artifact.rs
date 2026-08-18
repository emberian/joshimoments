//! Versioned immutable projection envelope, validation, residuals, and canonical bytes.

use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{CommitSeq, StableString, ValueDigest};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::{
    AccountingProjectionDto, AssetDefinitionDto, CoverageStatus, EffectClassificationDto,
    LiquidityProjectionDto, MarketProjectionDto, MetricReading, PROJECTION_CONTRACT,
    PROJECTION_SCHEMA_VERSION, PROJECTION_VERSION, ProjectionCoverage, ProjectionInputClosure,
    SignedAtomicAmountDto,
};

/// Hard capability ceiling carried on every public artifact.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectionAuthority {
    ReadOnlyNoExecution,
}

/// Named residual state. A nonzero amount is not the only kind of incompleteness.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ResidualStateDto {
    ExactAtomic { value: SignedAtomicAmountDto },
    Partial { reason: StableString },
    Conflicting { reason: StableString },
    Unknown { reason: StableString },
    Unsupported { reason: StableString },
}

/// One stable reconciliation, coverage, classification, or protocol residual.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NamedResidualDto {
    pub residual_id: StableString,
    pub category: StableString,
    pub scope: StableString,
    pub state: ResidualStateDto,
}

/// Projection watermark for core/glass scene admission.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionWatermarkDto {
    pub name: StableString,
    pub version: StableString,
    pub state_digest: ValueDigest,
    pub delivered_through: CommitSeq,
}

/// Inputs to immutable artifact construction. All semantic calculations have already happened.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProjectionDraft {
    pub projection_id: StableString,
    pub supersedes_projection_id: Option<StableString>,
    pub calculator_build: StableString,
    pub request_digest: ValueDigest,
    pub input: ProjectionInputClosure,
    pub coverage: Vec<ProjectionCoverage>,
    pub accounting: AccountingProjectionDto,
    pub market: MarketProjectionDto,
    pub liquidity: LiquidityProjectionDto,
}

/// Strict exact read DTO served to Glass. It contains no transaction or policy authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProjectionArtifactV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub projection_id: StableString,
    pub supersedes_projection_id: Option<StableString>,
    pub calculator_build: StableString,
    pub request_digest: ValueDigest,
    pub result_digest: ValueDigest,
    pub input: ProjectionInputClosure,
    pub coverage: Vec<ProjectionCoverage>,
    pub accounting: AccountingProjectionDto,
    pub market: MarketProjectionDto,
    pub liquidity: LiquidityProjectionDto,
    pub residuals: Vec<NamedResidualDto>,
    pub authority: ProjectionAuthority,
}

impl ProjectionArtifactV1 {
    /// Returns the exact scene watermark core must mount beside artifact bytes.
    #[must_use]
    pub fn watermark(&self) -> ProjectionWatermarkDto {
        ProjectionWatermarkDto {
            name: stable(PROJECTION_CONTRACT),
            version: stable(PROJECTION_VERSION),
            state_digest: self.result_digest.clone(),
            delivered_through: self.input.through_commit_seq,
        }
    }

    /// Revalidates closure, strict wire semantics, and the self-declared result digest.
    ///
    /// # Errors
    ///
    /// Returns a typed defect rather than serving an ambiguous artifact.
    pub fn validate(&self) -> Result<(), ProjectionError> {
        if self.contract.as_str() != PROJECTION_CONTRACT
            || self.schema_version != PROJECTION_SCHEMA_VERSION
        {
            return Err(ProjectionError::Contract);
        }
        self.input.validate()?;
        validate_sha256(&self.request_digest)?;
        validate_sha256(&self.result_digest)?;
        validate_projection_registration(&self.input)?;
        validate_coverage(&self.coverage)?;
        validate_assertion_conflicts(&self.input, &self.coverage)?;
        validate_wire_payload(self)?;
        validate_unrealized_links(&self.accounting, &self.market)?;
        let actual = digest_material(self)?;
        if actual != self.result_digest {
            return Err(ProjectionError::DigestMismatch {
                declared: self.result_digest.to_string(),
                computed: actual.to_string(),
            });
        }
        Ok(())
    }
}

/// Builds, validates, and hashes one deterministic artifact.
///
/// # Errors
///
/// Refuses malformed closure, coverage, evidence, units, ratios, links, or digests.
pub fn build_projection(draft: ProjectionDraft) -> Result<ProjectionArtifactV1, ProjectionError> {
    draft.input.validate()?;
    validate_sha256(&draft.request_digest)?;
    validate_projection_registration(&draft.input)?;
    validate_coverage(&draft.coverage)?;
    validate_assertion_conflicts(&draft.input, &draft.coverage)?;
    let residuals = derive_residuals(&draft.accounting, &draft.coverage, &draft.liquidity);
    let mut artifact = ProjectionArtifactV1 {
        contract: stable(PROJECTION_CONTRACT),
        schema_version: PROJECTION_SCHEMA_VERSION,
        projection_id: draft.projection_id,
        supersedes_projection_id: draft.supersedes_projection_id,
        calculator_build: draft.calculator_build,
        request_digest: draft.request_digest,
        result_digest: ValueDigest::new(
            "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )
        .map_err(|error| ProjectionError::Identity(error.to_string()))?,
        input: draft.input,
        coverage: draft.coverage,
        accounting: draft.accounting,
        market: draft.market,
        liquidity: draft.liquidity,
        residuals,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
    };
    validate_wire_payload(&artifact)?;
    validate_unrealized_links(&artifact.accounting, &artifact.market)?;
    artifact.result_digest = digest_material(&artifact)?;
    artifact.validate()?;
    Ok(artifact)
}

/// Builds a closure-complete target projection while proving its incremental lineage.
///
/// Incremental reducers may use a prior artifact as a durable resume checkpoint, but the target
/// draft still contains the complete point-in-time closure. The final artifact therefore has no
/// build-path field and must be byte-identical to a full rebuild of the same draft.
///
/// # Errors
///
/// Refuses an invalid prior artifact, missing supersession link, non-advancing cutoff, calculator
/// build drift, or any ordinary target-projection defect.
pub fn build_projection_incremental(
    prior: &ProjectionArtifactV1,
    draft: ProjectionDraft,
) -> Result<ProjectionArtifactV1, ProjectionError> {
    prior.validate()?;
    if draft.supersedes_projection_id.as_ref() != Some(&prior.projection_id) {
        return Err(ProjectionError::IncrementalLineage);
    }
    if draft.input.through_commit_seq <= prior.input.through_commit_seq {
        return Err(ProjectionError::IncrementalCutoff);
    }
    if draft.calculator_build != prior.calculator_build {
        return Err(ProjectionError::IncrementalBuild);
    }
    build_projection(draft)
}

/// Returns exact schema-ordered compact JSON bytes after full validation.
///
/// # Errors
///
/// Refuses invalid artifact semantics, digest mismatch, or JSON serialization failure.
pub fn projection_bytes(artifact: &ProjectionArtifactV1) -> Result<Vec<u8>, ProjectionError> {
    artifact.validate()?;
    serde_json::to_vec(artifact).map_err(ProjectionError::Json)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DigestMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    projection_id: &'a StableString,
    supersedes_projection_id: &'a Option<StableString>,
    calculator_build: &'a StableString,
    request_digest: &'a ValueDigest,
    input: &'a ProjectionInputClosure,
    coverage: &'a [ProjectionCoverage],
    accounting: &'a AccountingProjectionDto,
    market: &'a MarketProjectionDto,
    liquidity: &'a LiquidityProjectionDto,
    residuals: &'a [NamedResidualDto],
    authority: ProjectionAuthority,
}

fn digest_material(artifact: &ProjectionArtifactV1) -> Result<ValueDigest, ProjectionError> {
    let material = DigestMaterial {
        contract: &artifact.contract,
        schema_version: artifact.schema_version,
        projection_id: &artifact.projection_id,
        supersedes_projection_id: &artifact.supersedes_projection_id,
        calculator_build: &artifact.calculator_build,
        request_digest: &artifact.request_digest,
        input: &artifact.input,
        coverage: &artifact.coverage,
        accounting: &artifact.accounting,
        market: &artifact.market,
        liquidity: &artifact.liquidity,
        residuals: &artifact.residuals,
        authority: artifact.authority,
    };
    let bytes = serde_json::to_vec(&material).map_err(ProjectionError::Json)?;
    let digest = Sha256::digest(bytes);
    ValueDigest::new(format!("sha256:{digest:x}"))
        .map_err(|error| ProjectionError::Identity(error.to_string()))
}

fn validate_projection_registration(input: &ProjectionInputClosure) -> Result<(), ProjectionError> {
    let version = input
        .as_of
        .projections
        .get(&stable(PROJECTION_CONTRACT))
        .ok_or(ProjectionError::ProjectionWatermark)?;
    if version.as_str() != PROJECTION_VERSION {
        return Err(ProjectionError::ProjectionWatermark);
    }
    Ok(())
}

fn validate_coverage(values: &[ProjectionCoverage]) -> Result<(), ProjectionError> {
    if values.is_empty()
        || values
            .windows(2)
            .any(|window| window[0].scope >= window[1].scope)
    {
        return Err(ProjectionError::CoverageOrder);
    }
    for value in values {
        if value
            .gap_ids
            .windows(2)
            .any(|window| window[0] >= window[1])
        {
            return Err(ProjectionError::CoverageOrder);
        }
        match &value.status {
            CoverageStatus::Complete if !value.gap_ids.is_empty() => {
                return Err(ProjectionError::CoverageContradiction);
            }
            CoverageStatus::Gap { .. } if value.gap_ids.is_empty() => {
                return Err(ProjectionError::CoverageContradiction);
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_assertion_conflicts(
    input: &ProjectionInputClosure,
    coverage: &[ProjectionCoverage],
) -> Result<(), ProjectionError> {
    let has_branch_conflict = input
        .effective_assertions
        .windows(2)
        .any(|window| window[0].semantic_key == window[1].semantic_key);
    let conflict_is_visible = coverage
        .iter()
        .any(|value| matches!(value.status, CoverageStatus::Conflicting { .. }));
    if has_branch_conflict && !conflict_is_visible {
        Err(ProjectionError::UnacknowledgedAssertionConflict)
    } else {
        Ok(())
    }
}

fn validate_wire_payload(artifact: &ProjectionArtifactV1) -> Result<(), ProjectionError> {
    let value = serde_json::to_value(artifact).map_err(ProjectionError::Json)?;
    let closure: BTreeSet<_> = artifact
        .input
        .observation_ids
        .iter()
        .map(joshi_domain::ObservationId::as_str)
        .collect();
    let definitions: BTreeMap<_, _> = artifact
        .accounting
        .asset_definitions
        .iter()
        .map(|value| (value.asset_id.as_str(), value))
        .collect();
    if definitions.len() != artifact.accounting.asset_definitions.len() {
        return Err(ProjectionError::AssetDefinition);
    }
    if artifact
        .accounting
        .asset_definitions
        .windows(2)
        .any(|window| window[0].asset_id >= window[1].asset_id)
    {
        return Err(ProjectionError::AssetDefinition);
    }
    let mut metric_ids = BTreeSet::new();
    walk_value(&value, &closure, &definitions, &mut metric_ids)
}

fn walk_value(
    value: &Value,
    closure: &BTreeSet<&str>,
    definitions: &BTreeMap<&str, &AssetDefinitionDto>,
    metric_ids: &mut BTreeSet<String>,
) -> Result<(), ProjectionError> {
    match value {
        Value::Object(object) => {
            if let Some(Value::String(metric_id)) = object.get("metricId")
                && !metric_ids.insert(metric_id.clone())
            {
                return Err(ProjectionError::DuplicateMetricId(metric_id.clone()));
            }
            if let Some(Value::String(status)) = object.get("status")
                && status == "conflicting"
                && let Some(Value::Array(candidates)) = object.get("candidates")
                && candidates.len() < 2
            {
                return Err(ProjectionError::MalformedConflict);
            }
            if let (
                Some(Value::String(asset_id)),
                Some(Value::Number(decimals)),
                Some(Value::String(observation_id)),
            ) = (
                object.get("assetId"),
                object.get("decimals"),
                object.get("definitionObservationId"),
            ) {
                let definition = definitions
                    .get(asset_id.as_str())
                    .ok_or(ProjectionError::AssetDefinition)?;
                if decimals.as_u64() != Some(u64::from(definition.decimals))
                    || observation_id != definition.definition_observation_id.as_str()
                {
                    return Err(ProjectionError::AssetDefinition);
                }
            }
            if let (Some(Value::String(numerator)), Some(Value::String(denominator))) =
                (object.get("numerator"), object.get("denominator"))
            {
                crate::ExactRatioDto {
                    numerator: numerator.clone(),
                    denominator: denominator.clone(),
                }
                .validate()
                .map_err(|_| ProjectionError::Ratio)?;
            }
            for (key, nested) in object {
                if key.ends_with("Digest")
                    && let Value::String(digest) = nested
                {
                    validate_sha256_text(digest)?;
                }
                if key == "evidence" || key == "routeObservationIds" {
                    validate_observation_array(nested, closure)?;
                } else if (key.ends_with("ObservationId") || key == "observationId")
                    && let Value::String(id) = nested
                    && !closure.contains(id.as_str())
                {
                    return Err(ProjectionError::EvidenceOutsideClosure(id.clone()));
                }
                walk_value(nested, closure, definitions, metric_ids)?;
            }
        }
        Value::Array(values) => {
            for nested in values {
                walk_value(nested, closure, definitions, metric_ids)?;
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
    Ok(())
}

fn validate_observation_array(
    value: &Value,
    closure: &BTreeSet<&str>,
) -> Result<(), ProjectionError> {
    let Value::Array(values) = value else {
        return Err(ProjectionError::EvidenceOrder);
    };
    if values.is_empty() {
        return Err(ProjectionError::EvidenceOrder);
    }
    let mut prior: Option<&str> = None;
    for value in values {
        let Value::String(id) = value else {
            return Err(ProjectionError::EvidenceOrder);
        };
        if prior.is_some_and(|previous| previous >= id.as_str()) {
            return Err(ProjectionError::EvidenceOrder);
        }
        if !closure.contains(id.as_str()) {
            return Err(ProjectionError::EvidenceOutsideClosure(id.clone()));
        }
        prior = Some(id);
    }
    Ok(())
}

fn validate_unrealized_links(
    accounting: &AccountingProjectionDto,
    market: &MarketProjectionDto,
) -> Result<(), ProjectionError> {
    let full_quotes: BTreeMap<_, _> = market
        .full_position_quotes
        .iter()
        .map(|value| (value.quote_id.as_str(), value))
        .collect();
    for value in &accounting.unrealized {
        let quote = full_quotes
            .get(value.liquidation_quote_id.as_str())
            .ok_or(ProjectionError::UnrealizedWithoutFullPositionQuote)?;
        if matches!(&value.result, MetricReading::Known { .. })
            && !matches!(&quote.freshness, crate::Freshness::Fresh { .. })
        {
            return Err(ProjectionError::UnrealizedFromNonFreshQuote);
        }
        let MetricReading::Known { value: output } = &quote.expected_output.reading else {
            return Err(ProjectionError::UnrealizedWithoutFullPositionQuote);
        };
        if value.liquidation_proceeds.denominator != "1"
            || value.liquidation_proceeds.numerator != output.to_string()
        {
            return Err(ProjectionError::UnrealizedQuoteMismatch);
        }
    }
    Ok(())
}

fn derive_residuals(
    accounting: &AccountingProjectionDto,
    coverage: &[ProjectionCoverage],
    liquidity: &LiquidityProjectionDto,
) -> Vec<NamedResidualDto> {
    let mut values = Vec::new();
    for inventory in &accounting.inventory {
        values.push(NamedResidualDto {
            residual_id: residual_id("wallet_minus_lots", inventory.observed.asset_id.as_str()),
            category: stable("wallet_minus_classified_lots"),
            scope: StableString::new(inventory.observed.asset_id.to_string())
                .expect("validated asset ID is a stable scope"),
            state: ResidualStateDto::ExactAtomic {
                value: inventory.wallet_minus_lots_residual.clone(),
            },
        });
    }
    for effect in &accounting.landed_effects {
        if matches!(effect.classification, EffectClassificationDto::Unclassified) {
            values.push(NamedResidualDto {
                residual_id: residual_id("unclassified_effect", effect.effect_id.as_str()),
                category: stable("unclassified_landed_effect"),
                scope: StableString::new(effect.effect_id.to_string())
                    .expect("validated effect ID is a stable scope"),
                state: ResidualStateDto::Unknown {
                    reason: stable("landed_effect_has_no_economic_classification"),
                },
            });
        }
    }
    for item in coverage {
        let state = match &item.status {
            CoverageStatus::Complete => continue,
            CoverageStatus::Partial { reason } | CoverageStatus::Gap { reason } => {
                ResidualStateDto::Partial {
                    reason: reason.clone(),
                }
            }
            CoverageStatus::Conflicting { reason } => ResidualStateDto::Conflicting {
                reason: reason.clone(),
            },
            CoverageStatus::Unknown { reason } => ResidualStateDto::Unknown {
                reason: reason.clone(),
            },
        };
        values.push(NamedResidualDto {
            residual_id: residual_id("coverage", item.scope.as_str()),
            category: stable("projection_coverage"),
            scope: item.scope.clone(),
            state,
        });
    }
    for position in &liquidity.positions {
        if let crate::PositionInventoryOutcomeDto::Available { inventory } = &position.inventory {
            for field in &inventory.unsupported_fields {
                values.push(NamedResidualDto {
                    residual_id: residual_id(
                        "liquidity_unsupported",
                        &format!("{}:{field}", position.position_id),
                    ),
                    category: stable("liquidity_unsupported_field"),
                    scope: StableString::new(position.position_id.to_string())
                        .expect("validated position ID is a stable scope"),
                    state: ResidualStateDto::Unsupported {
                        reason: field.clone(),
                    },
                });
            }
        }
    }
    values.sort_by(|left, right| left.residual_id.cmp(&right.residual_id));
    values
}

fn residual_id(category: &str, scope: &str) -> StableString {
    let digest = Sha256::digest(format!("{category}\0{scope}").as_bytes());
    StableString::new(format!("residual:sha256:{digest:x}"))
        .expect("fixed-width residual digest identity is valid")
}

fn validate_sha256(value: &ValueDigest) -> Result<(), ProjectionError> {
    validate_sha256_text(value.as_str())
}

fn validate_sha256_text(text: &str) -> Result<(), ProjectionError> {
    if text.len() != 71
        || !text.starts_with("sha256:")
        || !text[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ProjectionError::DigestFormat(text.to_owned()));
    }
    Ok(())
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("static projection contract value is valid")
}

/// Projection construction or validation failure.
#[derive(Debug, Error)]
pub enum ProjectionError {
    #[error(transparent)]
    InputClosure(#[from] crate::InputClosureError),
    #[error("projection contract or schema version mismatch")]
    Contract,
    #[error("projection as-of vector does not name the exact projection version")]
    ProjectionWatermark,
    #[error("projection coverage scopes/gaps are empty, duplicated, or unordered")]
    CoverageOrder,
    #[error("projection coverage status contradicts its gap identities")]
    CoverageContradiction,
    #[error("multiple effective assertion branches are not exposed as conflicting coverage")]
    UnacknowledgedAssertionConflict,
    #[error("asset definitions are duplicated, missing, or inconsistent")]
    AssetDefinition,
    #[error("financial metric identity appears more than once: {0}")]
    DuplicateMetricId(String),
    #[error("financial ratio is not canonical and reduced")]
    Ratio,
    #[error("conflicting metric state must carry at least two candidates")]
    MalformedConflict,
    #[error("metric/effect evidence must be nonempty, sorted, and duplicate-free")]
    EvidenceOrder,
    #[error("observation is outside the projection input closure: {0}")]
    EvidenceOutsideClosure(String),
    #[error("unrealized result lacks an exact full-position quote")]
    UnrealizedWithoutFullPositionQuote,
    #[error("known unrealized result is based on a non-fresh full-position quote")]
    UnrealizedFromNonFreshQuote,
    #[error("unrealized proceeds disagree with the linked full-position quote")]
    UnrealizedQuoteMismatch,
    #[error("digest must be sha256 followed by 64 lowercase hex digits: {0}")]
    DigestFormat(String),
    #[error("projection result digest mismatch: declared {declared}, computed {computed}")]
    DigestMismatch { declared: String, computed: String },
    #[error("incremental projection does not explicitly supersede its prior projection")]
    IncrementalLineage,
    #[error("incremental projection cutoff does not advance beyond its prior projection")]
    IncrementalCutoff,
    #[error("incremental projection changed calculator build; a full rebuild is required")]
    IncrementalBuild,
    #[error("invalid stable identity: {0}")]
    Identity(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
