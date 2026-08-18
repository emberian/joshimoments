use crate::{
    ADJUDICATION_CONTRACT, BookError, CLAIM_DEFINITION_CONTRACT, CLAIM_OCCURRENCE_CONTRACT,
    FORECAST_SUBMISSION_CONTRACT, PROBABILITY_SCALE_PPM, Result, SCHEMA_VERSION,
    SCORE_ARTIFACT_CONTRACT, SUPPORT_SUMMARY_CONTRACT, ValidatedArtifact,
    canonical::decode_canonical,
    canonical_bytes, digest_bytes,
    model::{
        AdjudicationDispositionV1, AdjudicationV1, ArtifactRefV1, CapabilityAttestationV1,
        CapabilityKindV1, CapabilityMaturityV1, CapabilityRequirementV1, ClaimDefinitionV1,
        ClaimFamilyV1, ClaimOccurrenceV1, EpistemicAuthorityV1, ForecastPayloadV1,
        ForecastSubmissionV1, FrozenInputManifestV1, OccurrenceKindV1, OutcomeCoverageStatusV1,
        OutcomeProbabilityV1, OutcomeStateV1, ProperScoreArtifactV1, ProperScoreRuleV1,
        ResolvedOccurrencePortV1, ScoringContractV1, SubmissionPhaseV1,
        SupportCalibrationSummaryV1, SupportMaturityV1,
    },
};
use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use serde::Serialize;
use std::collections::BTreeSet;

fn invalid<T>(message: impl Into<String>) -> Result<T> {
    Err(BookError::Invalid(message.into()))
}

fn header(contract: &StableString, version: u64, expected: &str) -> Result<()> {
    if contract.as_str() != expected || version != SCHEMA_VERSION {
        return invalid(format!(
            "expected {expected} schema version {SCHEMA_VERSION}"
        ));
    }
    Ok(())
}

pub(crate) fn authority(value: EpistemicAuthorityV1) -> Result<()> {
    if value != EpistemicAuthorityV1::READ_ONLY_H3 {
        return invalid("epistemic artifacts must be powerless read_only_no_execution H3 values");
    }
    Ok(())
}

pub(crate) fn sha256(value: &ValueDigest, field: &str) -> Result<()> {
    let Some(hex) = value.as_str().strip_prefix("sha256:") else {
        return invalid(format!(
            "{field} must be an algorithm-qualified sha256 digest"
        ));
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return invalid(format!(
            "{field} must contain 64 lowercase hexadecimal digits"
        ));
    }
    Ok(())
}

pub(crate) fn artifact_ref(value: &ArtifactRefV1, field: &str) -> Result<()> {
    sha256(&value.semantic_digest, &format!("{field}.semanticDigest"))
}

fn sorted_unique<T: Ord>(values: &[T], field: &str) -> Result<()> {
    if values.windows(2).any(|pair| pair[0] >= pair[1]) {
        return invalid(format!(
            "{field} must be strictly sorted and duplicate-free"
        ));
    }
    Ok(())
}

fn sorted_artifacts(values: &[ArtifactRefV1], field: &str) -> Result<()> {
    for value in values {
        artifact_ref(value, field)?;
    }
    if values.windows(2).any(|pair| {
        (&pair[0].occurrence_id, &pair[0].semantic_digest)
            >= (&pair[1].occurrence_id, &pair[1].semantic_digest)
    }) {
        return invalid(format!(
            "{field} must be strictly sorted and duplicate-free"
        ));
    }
    Ok(())
}

pub(crate) fn exact_ref<T>(id: &StableString, artifact: &ValidatedArtifact<T>) -> ArtifactRefV1 {
    ArtifactRefV1 {
        occurrence_id: id.clone(),
        semantic_digest: artifact.semantic_digest().clone(),
    }
}

fn freeze<T: Serialize>(value: T) -> Result<ValidatedArtifact<T>> {
    let bytes = canonical_bytes(&value)?;
    ValidatedArtifact::new(value, bytes)
}

fn decode<T: serde::de::DeserializeOwned + Serialize>(
    bytes: &[u8],
    validate: impl FnOnce(&T) -> Result<()>,
) -> Result<ValidatedArtifact<T>> {
    let (value, canonical) = decode_canonical(bytes)?;
    validate(&value)?;
    ValidatedArtifact::new(value, canonical)
}

#[allow(clippy::too_many_lines)]
fn validate_requirements(definition: &ClaimDefinitionV1) -> Result<()> {
    if definition
        .required_capabilities
        .windows(2)
        .any(|pair| (&pair[0].kind, &pair[0].profile_id) >= (&pair[1].kind, &pair[1].profile_id))
    {
        return invalid("requiredCapabilities must be sorted by kind/profile and duplicate-free");
    }
    let kinds: BTreeSet<_> = definition
        .required_capabilities
        .iter()
        .map(|requirement| requirement.kind)
        .collect();
    let (required, quote_profile) = match &definition.family {
        ClaimFamilyV1::SpotCompetingRisk {
            quote_profile_id,
            quote_freshness_us,
            observation_cadence_us,
            net_profit_threshold_atoms,
            drawdown_threshold_atoms,
            ..
        } => {
            if quote_freshness_us.get() == 0
                || observation_cadence_us.get() == 0
                || net_profit_threshold_atoms.get() == 0
                || drawdown_threshold_atoms.get() == 0
            {
                return invalid("spot competing-risk thresholds and clocks must be positive");
            }
            (
                [
                    CapabilityKindV1::CoherentVenueState,
                    CapabilityKindV1::DirectionBySizeQuote,
                    CapabilityKindV1::FeeModel,
                    CapabilityKindV1::QuoteFreshness,
                ]
                .as_slice(),
                Some(quote_profile_id),
            )
        }
        ClaimFamilyV1::LiquiditySurvival {
            quote_profile_id,
            maximum_slippage_ppm,
            minimum_capacity_atoms,
            quote_freshness_us,
            checkpoint_cadence_us,
            ..
        } => {
            if maximum_slippage_ppm.get() > PROBABILITY_SCALE_PPM
                || minimum_capacity_atoms.get() == 0
                || quote_freshness_us.get() == 0
                || checkpoint_cadence_us.get() == 0
            {
                return invalid(
                    "liquidity-survival capacity/clocks must be positive and ppm bounded",
                );
            }
            (
                [
                    CapabilityKindV1::DirectionBySizeQuote,
                    CapabilityKindV1::QuoteFreshness,
                    CapabilityKindV1::RouteCapacity,
                ]
                .as_slice(),
                Some(quote_profile_id),
            )
        }
        ClaimFamilyV1::RunnerCompetingRisk { .. } => (
            [
                CapabilityKindV1::ExactRunnerLot,
                CapabilityKindV1::DirectionBySizeQuote,
                CapabilityKindV1::WholePositionLiquidation,
            ]
            .as_slice(),
            None,
        ),
        ClaimFamilyV1::RunnerFrozenBranchValue { .. } => (
            [
                CapabilityKindV1::ExactRunnerLot,
                CapabilityKindV1::WholePositionLiquidation,
                CapabilityKindV1::CommonTerminalManifest,
                CapabilityKindV1::FrozenReplay,
            ]
            .as_slice(),
            None,
        ),
        ClaimFamilyV1::DisabledLpSchedule { .. } => (
            [
                CapabilityKindV1::LpScheduleState,
                CapabilityKindV1::ExternalSelfFlowSeparation,
                CapabilityKindV1::ExactInventory,
                CapabilityKindV1::WholePositionLiquidation,
                CapabilityKindV1::FrozenReplay,
            ]
            .as_slice(),
            None,
        ),
        ClaimFamilyV1::DisabledRoutedLiquidity { .. } => (
            [
                CapabilityKindV1::LpScheduleState,
                CapabilityKindV1::ExternalSelfFlowSeparation,
                CapabilityKindV1::ExactInventory,
                CapabilityKindV1::WholePositionLiquidation,
                CapabilityKindV1::FrozenReplay,
                CapabilityKindV1::RouteCapacity,
            ]
            .as_slice(),
            None,
        ),
    };
    if required.iter().any(|kind| !kinds.contains(kind)) {
        return invalid("claim family omits a mandatory mechanics capability prerequisite");
    }
    if let Some(profile) = quote_profile
        && required.iter().any(|kind| {
            !definition
                .required_capabilities
                .iter()
                .any(|requirement| requirement.kind == *kind && &requirement.profile_id == profile)
        })
    {
        return invalid("quote-family capability prerequisites must use the frozen quote profile");
    }
    for requirement in &definition.required_capabilities {
        let expected_maturity = match requirement.kind {
            CapabilityKindV1::CoherentVenueState
            | CapabilityKindV1::ExactRunnerLot
            | CapabilityKindV1::LpScheduleState
            | CapabilityKindV1::ExternalSelfFlowSeparation
            | CapabilityKindV1::ExactInventory
            | CapabilityKindV1::CommonTerminalManifest
            | CapabilityKindV1::FrozenReplay => CapabilityMaturityV1::CoherentRealState,
            CapabilityKindV1::DirectionBySizeQuote
            | CapabilityKindV1::FeeModel
            | CapabilityKindV1::QuoteFreshness
            | CapabilityKindV1::RouteCapacity => CapabilityMaturityV1::ExactQuote,
            CapabilityKindV1::WholePositionLiquidation => {
                CapabilityMaturityV1::WholePositionLiquidation
            }
        };
        if requirement.required_maturity != expected_maturity {
            return invalid("claim family selected an invalid typed capability maturity");
        }
    }
    Ok(())
}

fn claim_definition_syntax(value: &ClaimDefinitionV1) -> Result<()> {
    header(
        &value.contract,
        value.schema_version.get(),
        CLAIM_DEFINITION_CONTRACT,
    )?;
    authority(value.authority)?;
    sha256(&value.producer_build_digest, "producerBuildDigest")?;
    if value.definition_version.get() == 0 {
        return invalid("definitionVersion must be positive");
    }
    match (value.definition_version.get(), &value.supersedes) {
        (1, None) => {}
        (1, Some(_)) => return invalid("definition version one cannot supersede another version"),
        (_, Some(reference)) => artifact_ref(reference, "supersedes")?,
        (_, None) => return invalid("later definition versions require an exact supersedes ref"),
    }
    if !(2..=64).contains(&value.outcome_space.len()) {
        return invalid("outcomeSpace must contain between two and 64 states");
    }
    if value
        .outcome_space
        .windows(2)
        .any(|pair| pair[0].outcome_id >= pair[1].outcome_id)
    {
        return invalid("outcomeSpace must be sorted by outcomeId and duplicate-free");
    }
    sorted_unique(
        &value.adjudication.eligible_observation_contracts,
        "adjudication.eligibleObservationContracts",
    )?;
    sorted_unique(&value.support.required_coverage, "support.requiredCoverage")?;
    sorted_unique(&value.support.prohibited_inputs, "support.prohibitedInputs")?;
    if !value.scoring.abstention_is_unscored
        || (!value.scoring.permits_resolved_observed
            && !value.scoring.permits_healthy_no_event
            && !value.scoring.permits_frozen_replay)
    {
        return invalid("scoring must leave abstention unscored and admit a resolved target kind");
    }
    match value.scoring.rule {
        ProperScoreRuleV1::BrierCategorical => {
            if value.scoring.probability_floor_ppm.is_some() {
                return invalid("Brier scoring does not use a probability floor");
            }
        }
        ProperScoreRuleV1::LogCategorical => {
            let Some(floor) = value.scoring.probability_floor_ppm else {
                return invalid("log scoring requires a prospectively declared probability floor");
            };
            if floor.get() == 0 || floor.get() >= PROBABILITY_SCALE_PPM / 2 {
                return invalid("log-score probability floor is outside the supported ppm domain");
            }
        }
    }
    validate_requirements(value)
}

/// Validates and canonicalizes a claim definition.
///
/// # Errors
///
/// Refuses malformed identity, family, scoring, capability, or authority semantics.
pub fn validate_claim_definition(
    value: ClaimDefinitionV1,
) -> Result<ValidatedArtifact<ClaimDefinitionV1>> {
    claim_definition_syntax(&value)?;
    if value.definition_version.get() != 1 || value.supersedes.is_some() {
        return invalid(
            "noninitial claim definitions require exact prior-object lineage validation",
        );
    }
    freeze(value)
}

/// Validates a consecutive claim-definition version against the exact prior bytes.
///
/// # Errors
///
/// Refuses an initial version, identity change, skipped version, or substituted prior digest.
pub fn validate_claim_definition_supersession(
    value: ClaimDefinitionV1,
    prior: &ValidatedArtifact<ClaimDefinitionV1>,
) -> Result<ValidatedArtifact<ClaimDefinitionV1>> {
    claim_definition_syntax(&value)?;
    if value.definition_version.get() != prior.value().definition_version.get() + 1
        || value.claim_definition_id != prior.value().claim_definition_id
        || value.supersedes != Some(exact_ref(&prior.value().claim_definition_id, prior))
    {
        return invalid("claim-definition supersession is not exact and consecutive");
    }
    freeze(value)
}

/// Strictly decodes canonical claim-definition bytes.
///
/// # Errors
///
/// Refuses noncanonical JSON or an invalid claim definition.
pub fn decode_claim_definition(bytes: &[u8]) -> Result<ValidatedArtifact<ClaimDefinitionV1>> {
    let (value, canonical) = decode_canonical(bytes)?;
    claim_definition_syntax(&value)?;
    if value.definition_version.get() != 1 || value.supersedes.is_some() {
        return invalid("noninitial claim definitions require an exact prior object");
    }
    ValidatedArtifact::new(value, canonical)
}

fn validate_evidence_manifest(
    manifest: &FrozenInputManifestV1,
    information_cutoff: UtcTimestamp,
) -> Result<()> {
    if manifest.evidence.is_empty() {
        return invalid("frozen input manifest cannot be empty");
    }
    if manifest.evidence.windows(2).any(|pair| {
        (
            &pair[0].artifact.occurrence_id,
            &pair[0].artifact.semantic_digest,
        ) >= (
            &pair[1].artifact.occurrence_id,
            &pair[1].artifact.semantic_digest,
        )
    }) {
        return invalid("frozen evidence must be sorted by occurrence identity/digest");
    }
    let mut maximum = manifest.evidence[0].available_at;
    for evidence in &manifest.evidence {
        artifact_ref(&evidence.artifact, "frozenInput.evidence.artifact")?;
        if evidence.valid_from > evidence.valid_through {
            return invalid("evidence validFrom must not follow validThrough");
        }
        if evidence.available_at > information_cutoff {
            return invalid("evidence became available after the occurrence information cutoff");
        }
        maximum = maximum.max(evidence.available_at);
    }
    if maximum != manifest.maximum_input_availability
        || manifest.maximum_input_availability > information_cutoff
    {
        return invalid(
            "maximumInputAvailability must equal the latest frozen evidence availability",
        );
    }
    sorted_unique(&manifest.coverage_ids, "frozenInput.coverageIds")?;
    sorted_unique(&manifest.gap_ids, "frozenInput.gapIds")?;
    if manifest
        .coverage_ids
        .iter()
        .any(|id| manifest.gap_ids.binary_search(id).is_ok())
    {
        return invalid("one identifier cannot be both a coverage window and a gap");
    }
    Ok(())
}

fn validate_capabilities(
    requirements: &[CapabilityRequirementV1],
    attestations: &[CapabilityAttestationV1],
) -> Result<()> {
    if attestations
        .windows(2)
        .any(|pair| (&pair[0].kind, &pair[0].profile_id) >= (&pair[1].kind, &pair[1].profile_id))
    {
        return invalid("capabilityClosure must be sorted by kind/profile and duplicate-free");
    }
    for attestation in attestations {
        artifact_ref(&attestation.artifact, "capabilityClosure.artifact")?;
    }
    for requirement in requirements {
        if !attestations.iter().any(|attestation| {
            attestation.kind == requirement.kind
                && attestation.profile_id == requirement.profile_id
                && attestation.maturity == requirement.required_maturity
        }) {
            return invalid("capability closure does not satisfy an exact family prerequisite");
        }
    }
    Ok(())
}

fn occurrence_syntax(
    value: &ClaimOccurrenceV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    resolved: &ResolvedOccurrencePortV1,
) -> Result<()> {
    header(
        &value.contract,
        value.schema_version.get(),
        CLAIM_OCCURRENCE_CONTRACT,
    )?;
    authority(value.authority)?;
    let expected_definition = exact_ref(&definition.value().claim_definition_id, definition);
    if value.claim_definition != expected_definition {
        return invalid("occurrence does not reference the exact claim-definition bytes");
    }
    artifact_ref(&value.scene, "scene")?;
    artifact_ref(&value.instrumented_universe, "instrumentedUniverse")?;
    if value.scene != resolved.scene
        || value.instrumented_universe != resolved.instrumented_universe
        || value.capability_closure != resolved.capabilities
    {
        return invalid("occurrence differs from its unverified semantic projection");
    }
    if !(value.frozen_input.maximum_input_availability <= value.occurrence_information_cutoff
        && value.occurrence_information_cutoff <= value.occurrence_commit_at
        && value.occurrence_commit_at <= value.issue_deadline
        && value.issue_deadline <= value.target_window_origin
        && value.target_window_origin < value.horizon_at
        && value.horizon_at < value.knowledge_deadline)
    {
        return invalid(
            "clock chain must satisfy max_input <= info_cutoff <= commit <= issue <= target < horizon < knowledge",
        );
    }
    validate_evidence_manifest(&value.frozen_input, value.occurrence_information_cutoff)?;
    sorted_unique(
        &value
            .sealed_forecast_journal
            .eligible_first_round_forecaster_ids,
        "sealedForecastJournal.eligibleFirstRoundForecasterIds",
    )?;
    if value
        .sealed_forecast_journal
        .eligible_first_round_forecaster_ids
        .is_empty()
        || value
            .sealed_forecast_journal
            .required_first_round_count
            .get()
            == 0
        || value
            .sealed_forecast_journal
            .required_first_round_count
            .get()
            > value
                .sealed_forecast_journal
                .eligible_first_round_forecaster_ids
                .len() as u64
        || value.sealed_forecast_journal.reveal_not_before < value.knowledge_deadline
    {
        return invalid(
            "sealed journal must preregister a nonempty eligible set/count and reveal no earlier than knowledge deadline",
        );
    }
    if value.conditioning.exact_size_atoms.get() == 0 {
        return invalid("conditioning exactSizeAtoms must be positive");
    }
    match &definition.value().family {
        ClaimFamilyV1::DisabledLpSchedule { .. }
        | ClaimFamilyV1::DisabledRoutedLiquidity { .. } => {
            return invalid("disabled LP/routed claim definitions cannot create occurrences");
        }
        _ => {}
    }
    validate_capabilities(
        &definition.value().required_capabilities,
        &value.capability_closure,
    )?;
    match &value.occurrence_kind {
        OccurrenceKindV1::Initial => {}
        OccurrenceKindV1::RevisionLandmark {
            prior_occurrence, ..
        } => artifact_ref(prior_occurrence, "occurrenceKind.priorOccurrence")?,
    }
    Ok(())
}

/// Validates a frozen occurrence against an exact definition and unverified semantic projection.
///
/// # Errors
///
/// Refuses unresolved references, missing capabilities, mutable inputs, or invalid clocks.
pub fn validate_claim_occurrence(
    value: ClaimOccurrenceV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    resolved: &ResolvedOccurrencePortV1,
) -> Result<ValidatedArtifact<ClaimOccurrenceV1>> {
    occurrence_syntax(&value, definition, resolved)?;
    if !matches!(value.occurrence_kind, OccurrenceKindV1::Initial) {
        return invalid("revision occurrences require exact prior-occurrence lineage validation");
    }
    freeze(value)
}

/// Validates a revision-landmark occurrence against the exact prior occurrence bytes.
///
/// # Errors
///
/// Refuses substituted lineage, changed subject/definition, or a nonlater information cut.
pub fn validate_revision_occurrence(
    value: ClaimOccurrenceV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    resolved: &ResolvedOccurrencePortV1,
    prior: &ValidatedArtifact<ClaimOccurrenceV1>,
) -> Result<ValidatedArtifact<ClaimOccurrenceV1>> {
    occurrence_syntax(&value, definition, resolved)?;
    let OccurrenceKindV1::RevisionLandmark {
        prior_occurrence, ..
    } = &value.occurrence_kind
    else {
        return invalid("revision validator requires a revision-landmark occurrence");
    };
    if prior_occurrence != &exact_ref(&prior.value().claim_occurrence_id, prior)
        || value.claim_definition != prior.value().claim_definition
        || value.subject_id != prior.value().subject_id
        || value.portfolio_domain_id != prior.value().portfolio_domain_id
        || value.occurrence_information_cutoff <= prior.value().occurrence_information_cutoff
    {
        return invalid("revision occurrence does not close exact prior identity and later state");
    }
    freeze(value)
}

/// Strictly decodes canonical occurrence bytes against an unverified semantic projection.
///
/// # Errors
///
/// Refuses noncanonical JSON or an occurrence that fails semantic projection closure.
pub fn decode_claim_occurrence(
    bytes: &[u8],
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    resolved: &ResolvedOccurrencePortV1,
) -> Result<ValidatedArtifact<ClaimOccurrenceV1>> {
    let (value, canonical) = decode_canonical(bytes)?;
    occurrence_syntax(&value, definition, resolved)?;
    if !matches!(value.occurrence_kind, OccurrenceKindV1::Initial) {
        return invalid("revision occurrence decoding requires an exact prior object");
    }
    ValidatedArtifact::new(value, canonical)
}

fn validate_probabilities(
    probabilities: &[OutcomeProbabilityV1],
    outcomes: &[OutcomeStateV1],
) -> Result<()> {
    if probabilities.len() != outcomes.len() {
        return invalid("categorical forecast must cover the exact registered outcome space");
    }
    let mut total = 0_u64;
    for (probability, outcome) in probabilities.iter().zip(outcomes) {
        if probability.outcome_id != outcome.outcome_id
            || probability.probability_ppm.get() > PROBABILITY_SCALE_PPM
        {
            return invalid(
                "forecast probabilities must follow outcome order and remain ppm bounded",
            );
        }
        total = total
            .checked_add(probability.probability_ppm.get())
            .ok_or_else(|| BookError::Invalid("probability sum overflow".into()))?;
    }
    if total != PROBABILITY_SCALE_PPM {
        return invalid("categorical probabilities must sum exactly to one million ppm");
    }
    Ok(())
}

fn submission_syntax(
    value: &ForecastSubmissionV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
) -> Result<()> {
    header(
        &value.contract,
        value.schema_version.get(),
        FORECAST_SUBMISSION_CONTRACT,
    )?;
    authority(value.authority)?;
    if value.claim_occurrence != exact_ref(&occurrence.value().claim_occurrence_id, occurrence) {
        return invalid("submission does not reference the exact claim-occurrence bytes");
    }
    for (digest, field) in [
        (
            &value.lineage.prompt_template_digest,
            "promptTemplateDigest",
        ),
        (
            &value.lineage.training_snapshot_digest,
            "trainingSnapshotDigest",
        ),
    ] {
        sha256(digest, field)?;
    }
    if let Some(digest) = &value.lineage.calibration_snapshot_digest {
        sha256(digest, "calibrationSnapshotDigest")?;
    }
    sorted_unique(&value.lineage.lineage_groups, "lineageGroups")?;
    if value
        .lineage
        .lineage_groups
        .binary_search(&value.lineage.primary_lineage_group)
        .is_err()
    {
        return invalid("primaryLineageGroup must be present in lineageGroups");
    }
    let frozen_digest = digest_bytes(&canonical_bytes(&occurrence.value().frozen_input)?)?;
    if value.frozen_input_manifest_digest != frozen_digest
        || value.maximum_input_availability
            != occurrence.value().frozen_input.maximum_input_availability
        || value.submission_input_cutoff != occurrence.value().occurrence_information_cutoff
    {
        return invalid("submission must consume the exact occurrence-frozen input manifest");
    }
    if !(value.maximum_input_availability <= value.submission_input_cutoff
        && value.submission_input_cutoff <= occurrence.value().occurrence_information_cutoff
        && occurrence.value().occurrence_information_cutoff
            <= occurrence.value().occurrence_commit_at
        && occurrence.value().occurrence_commit_at <= value.submission_production_time
        && value.submission_production_time <= occurrence.value().issue_deadline
        && occurrence.value().issue_deadline <= occurrence.value().target_window_origin)
    {
        return invalid("forecast submission violates the exact B0 clock chain");
    }
    match (&value.phase, &occurrence.value().occurrence_kind) {
        (SubmissionPhaseV1::FirstRound, OccurrenceKindV1::Initial)
        | (SubmissionPhaseV1::Revision { .. }, OccurrenceKindV1::RevisionLandmark { .. }) => {}
        _ => return invalid("submission phase does not match initial/revision occurrence kind"),
    }
    if matches!(value.phase, SubmissionPhaseV1::FirstRound)
        && occurrence
            .value()
            .sealed_forecast_journal
            .eligible_first_round_forecaster_ids
            .binary_search(&value.lineage.forecaster_id)
            .is_err()
    {
        return invalid("first-round forecaster was not preregistered in the sealed journal");
    }
    if let SubmissionPhaseV1::Revision {
        revises_submission,
        visible_parent_submission_ids,
        visible_ensemble_ids,
    } = &value.phase
    {
        artifact_ref(revises_submission, "phase.revisesSubmission")?;
        sorted_unique(visible_parent_submission_ids, "visibleParentSubmissionIds")?;
        sorted_unique(visible_ensemble_ids, "visibleEnsembleIds")?;
        if visible_parent_submission_ids
            .binary_search(&revises_submission.occurrence_id)
            .is_err()
        {
            return invalid("revision must disclose the submission it revises as a visible parent");
        }
    }
    if let ForecastPayloadV1::Categorical { probabilities } = &value.payload {
        validate_probabilities(probabilities, &definition.value().outcome_space)?;
    }
    Ok(())
}

/// Validates a forecast against its exact definition and occurrence.
///
/// # Errors
///
/// Refuses input substitution, post-cutoff evidence, malformed probabilities, or authority.
pub fn validate_forecast_submission(
    value: ForecastSubmissionV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
) -> Result<ValidatedArtifact<ForecastSubmissionV1>> {
    submission_syntax(&value, definition, occurrence)?;
    freeze(value)
}

/// Strictly decodes canonical forecast bytes.
///
/// # Errors
///
/// Refuses noncanonical JSON or invalid forecast semantics.
pub fn decode_forecast_submission(
    bytes: &[u8],
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
) -> Result<ValidatedArtifact<ForecastSubmissionV1>> {
    decode(bytes, |value| {
        submission_syntax(value, definition, occurrence)
    })
}

/// Validates the append-only link between a revision and its explicitly visible prior forecast.
///
/// # Errors
///
/// Refuses a missing landmark, substituted parent, changed subject, or nonlater information cut.
pub fn validate_revision(
    revision: &ValidatedArtifact<ForecastSubmissionV1>,
    revision_occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    prior: &ValidatedArtifact<ForecastSubmissionV1>,
    prior_occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
) -> Result<()> {
    let SubmissionPhaseV1::Revision {
        revises_submission, ..
    } = &revision.value().phase
    else {
        return invalid("forecast is not a revision");
    };
    let OccurrenceKindV1::RevisionLandmark {
        prior_occurrence: occurrence_parent,
        ..
    } = &revision_occurrence.value().occurrence_kind
    else {
        return invalid("revision does not use a preregistered landmark occurrence");
    };
    if revises_submission != &exact_ref(&prior.value().submission_id, prior)
        || occurrence_parent
            != &exact_ref(
                &prior_occurrence.value().claim_occurrence_id,
                prior_occurrence,
            )
        || revision.value().lineage.forecaster_id != prior.value().lineage.forecaster_id
        || revision_occurrence.value().claim_definition != prior_occurrence.value().claim_definition
        || revision_occurrence.value().subject_id != prior_occurrence.value().subject_id
        || revision_occurrence.value().occurrence_information_cutoff
            <= prior_occurrence.value().occurrence_information_cutoff
    {
        return invalid(
            "revision does not close the exact prior forecast and later information state",
        );
    }
    Ok(())
}

fn outcome_id(disposition: &AdjudicationDispositionV1) -> Option<&StableString> {
    match disposition {
        AdjudicationDispositionV1::ResolvedObserved { outcome_id }
        | AdjudicationDispositionV1::ResolvedFrozenReplay { outcome_id, .. }
        | AdjudicationDispositionV1::HealthyNoEventThroughHorizon { outcome_id } => {
            Some(outcome_id)
        }
        _ => None,
    }
}

pub(crate) fn resolved_outcome<'a>(
    value: &'a AdjudicationV1,
    scoring: &ScoringContractV1,
) -> Result<&'a StableString> {
    match &value.disposition {
        AdjudicationDispositionV1::ResolvedObserved { outcome_id }
            if scoring.permits_resolved_observed =>
        {
            Ok(outcome_id)
        }
        AdjudicationDispositionV1::HealthyNoEventThroughHorizon { outcome_id }
            if scoring.permits_healthy_no_event =>
        {
            Ok(outcome_id)
        }
        AdjudicationDispositionV1::ResolvedFrozenReplay { outcome_id, .. }
            if scoring.permits_frozen_replay =>
        {
            Ok(outcome_id)
        }
        _ => invalid("adjudication is not admissible under the registered scoring contract"),
    }
}

#[allow(clippy::too_many_lines)]
fn adjudication_syntax(
    value: &AdjudicationV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    previous: Option<&ValidatedArtifact<AdjudicationV1>>,
) -> Result<()> {
    header(
        &value.contract,
        value.schema_version.get(),
        ADJUDICATION_CONTRACT,
    )?;
    authority(value.authority)?;
    sha256(&value.resolver_build_digest, "resolverBuildDigest")?;
    if value.claim_occurrence != exact_ref(&occurrence.value().claim_occurrence_id, occurrence) {
        return invalid("adjudication does not reference the exact occurrence");
    }
    if value.knowledge_cutoff != occurrence.value().knowledge_deadline
        || value.adjudicated_at < occurrence.value().knowledge_deadline
    {
        return invalid(
            "adjudication must use the preregistered knowledge cutoff after its deadline",
        );
    }
    match (
        value.adjudication_version.get(),
        &value.supersedes,
        previous,
    ) {
        (1, None, None) => {}
        (1, _, _) => return invalid("adjudication version one cannot supersede another artifact"),
        (version, Some(reference), Some(prior))
            if version == prior.value().adjudication_version.get() + 1
                && reference == &exact_ref(&prior.value().adjudication_id, prior)
                && prior.value().claim_occurrence == value.claim_occurrence
                && value.adjudicated_at > prior.value().adjudicated_at => {}
        _ => {
            return invalid("adjudication supersession is not exact, consecutive, and append-only");
        }
    }
    if value.evidence.windows(2).any(|pair| {
        (
            &pair[0].artifact.occurrence_id,
            &pair[0].artifact.semantic_digest,
        ) >= (
            &pair[1].artifact.occurrence_id,
            &pair[1].artifact.semantic_digest,
        )
    }) {
        return invalid("outcome evidence must be sorted and duplicate-free");
    }
    for evidence in &value.evidence {
        artifact_ref(&evidence.artifact, "evidence.artifact")?;
        if evidence.available_at > value.knowledge_cutoff
            || definition
                .value()
                .adjudication
                .eligible_observation_contracts
                .binary_search(&evidence.observation_contract)
                .is_err()
        {
            return invalid("outcome evidence was late or used an ineligible contract");
        }
    }
    sorted_unique(&value.coverage.coverage_ids, "coverage.coverageIds")?;
    sorted_unique(&value.coverage.gap_ids, "coverage.gapIds")?;
    if let Some(id) = outcome_id(&value.disposition)
        && definition
            .value()
            .outcome_space
            .binary_search_by(|outcome| outcome.outcome_id.cmp(id))
            .is_err()
    {
        return invalid("adjudicated outcome is outside the registered outcome space");
    }
    match &value.disposition {
        AdjudicationDispositionV1::ResolvedObserved { .. } => {
            if value.coverage.status != OutcomeCoverageStatusV1::Complete
                || value.evidence.is_empty()
                || !value.coverage.gap_ids.is_empty()
            {
                return invalid("resolved observed outcome requires complete, non-gapped evidence");
            }
        }
        AdjudicationDispositionV1::ResolvedFrozenReplay {
            replay_manifest, ..
        } => {
            artifact_ref(replay_manifest, "disposition.replayManifest")?;
            let required: BTreeSet<_> = definition
                .value()
                .required_capabilities
                .iter()
                .map(|requirement| requirement.kind)
                .collect();
            if !matches!(
                definition.value().family,
                ClaimFamilyV1::RunnerFrozenBranchValue { .. }
            ) || !definition.value().scoring.permits_frozen_replay
                || value.coverage.status != OutcomeCoverageStatusV1::Complete
                || value.coverage.coverage_ids.is_empty()
                || !value.coverage.gap_ids.is_empty()
                || value.evidence.is_empty()
                || ![
                    CapabilityKindV1::CommonTerminalManifest,
                    CapabilityKindV1::FrozenReplay,
                    CapabilityKindV1::WholePositionLiquidation,
                ]
                .iter()
                .all(|kind| required.contains(kind))
            {
                return invalid(
                    "frozen replay requires its enabled family plus complete terminal evidence and mechanics prerequisites",
                );
            }
        }
        AdjudicationDispositionV1::HealthyNoEventThroughHorizon { .. } => {
            if value.coverage.status != OutcomeCoverageStatusV1::Complete
                || value.coverage.coverage_ids.is_empty()
                || !value.coverage.gap_ids.is_empty()
                || value.evidence.is_empty()
            {
                return invalid(
                    "healthy no-event requires nonempty complete evidence and coverage through the horizon",
                );
            }
        }
        AdjudicationDispositionV1::SourceLossCensored { gap_ids } => {
            sorted_unique(gap_ids, "disposition.gapIds")?;
            if gap_ids.is_empty()
                || gap_ids != &value.coverage.gap_ids
                || !matches!(
                    value.coverage.status,
                    OutcomeCoverageStatusV1::Gapped | OutcomeCoverageStatusV1::Unavailable
                )
            {
                return invalid("source-loss censoring must name the exact nonempty coverage gaps");
            }
        }
        AdjudicationDispositionV1::IntervalCensored { lower, upper } => {
            if matches!(value.coverage.status, OutcomeCoverageStatusV1::Complete)
                || matches!((lower, upper), (Some(lower), Some(upper)) if lower >= upper)
            {
                return invalid("interval censoring requires incomplete coverage and valid bounds");
            }
        }
        AdjudicationDispositionV1::Conflicting { observation_ids } => {
            sorted_unique(observation_ids, "disposition.observationIds")?;
            if observation_ids.len() < 2 {
                return invalid("conflicting adjudication requires at least two observations");
            }
            let retained: BTreeSet<_> = value
                .evidence
                .iter()
                .map(|evidence| &evidence.artifact.occurrence_id)
                .collect();
            if observation_ids.iter().any(|id| !retained.contains(id)) {
                return invalid("conflicting adjudication names evidence outside its closure");
            }
        }
        AdjudicationDispositionV1::RouteOrLiquidationRefused { .. } => {
            if value.evidence.is_empty() {
                return invalid("route/liquidation refusal requires retained refusal evidence");
            }
        }
        AdjudicationDispositionV1::OpenNotMature => {
            return invalid(
                "open_not_mature is a status, not an after-deadline adjudication artifact",
            );
        }
        AdjudicationDispositionV1::AdministrativeCensored { .. }
        | AdjudicationDispositionV1::LeftTruncated { .. }
        | AdjudicationDispositionV1::CompetingEvent { .. }
        | AdjudicationDispositionV1::InterventionInvalidatedActualPath { .. }
        | AdjudicationDispositionV1::Unsupported { .. } => {}
    }
    Ok(())
}

/// Validates an append-only adjudication version.
///
/// # Errors
///
/// Refuses late evidence, false resolution, invalid censoring, or inexact supersession.
pub fn validate_adjudication(
    value: AdjudicationV1,
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    previous: Option<&ValidatedArtifact<AdjudicationV1>>,
) -> Result<ValidatedArtifact<AdjudicationV1>> {
    adjudication_syntax(&value, definition, occurrence, previous)?;
    freeze(value)
}

/// Strictly decodes canonical adjudication bytes.
///
/// # Errors
///
/// Refuses noncanonical JSON or invalid adjudication semantics.
pub fn decode_adjudication(
    bytes: &[u8],
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    previous: Option<&ValidatedArtifact<AdjudicationV1>>,
) -> Result<ValidatedArtifact<AdjudicationV1>> {
    decode(bytes, |value| {
        adjudication_syntax(value, definition, occurrence, previous)
    })
}

#[allow(clippy::too_many_lines)]
fn support_summary_syntax(value: &SupportCalibrationSummaryV1) -> Result<()> {
    const MIN_REPEATED_SUPPORT_SCORES: u64 = 40;
    const MIN_SCORES_PER_WINDOW: u64 = 20;
    header(
        &value.contract,
        value.schema_version.get(),
        SUPPORT_SUMMARY_CONTRACT,
    )?;
    authority(value.authority)?;
    artifact_ref(&value.claim_definition, "claimDefinition")?;
    sorted_artifacts(&value.score_artifacts, "scoreArtifacts")?;
    if value.scored_occurrences.get() > value.total_occurrences.get()
        || value.score_artifacts.len() as u64 != value.scored_occurrences.get()
    {
        return invalid("scored occurrences must be a subset exactly closed by scoreArtifacts");
    }
    if value
        .adjudication_counts
        .windows(2)
        .any(|pair| pair[0].disposition >= pair[1].disposition)
    {
        return invalid("adjudicationCounts must be sorted and duplicate-free");
    }
    let count_sum = value
        .adjudication_counts
        .iter()
        .try_fold(0_u64, |sum, count| sum.checked_add(count.count.get()))
        .ok_or_else(|| BookError::Invalid("adjudication count overflow".into()))?;
    if count_sum != value.total_occurrences.get() {
        return invalid("adjudicationCounts must preserve the complete occurrence denominator");
    }
    sorted_unique(&value.coverage_ids, "coverageIds")?;
    sorted_unique(&value.gap_ids, "gapIds")?;
    let mut member_scores = Vec::new();
    let mut member_occurrences = Vec::new();
    for window in &value.windows {
        if !(window.start < window.end && window.end <= window.embargo_through) {
            return invalid("evaluation window must satisfy start < end <= embargoThrough");
        }
        if window.eligible_score_count.get() != window.score_memberships.len() as u64 {
            return invalid(
                "window eligibleScoreCount must equal its exact named score membership",
            );
        }
        if window.score_memberships.windows(2).any(|pair| {
            (&pair[0].score.occurrence_id, &pair[0].score.semantic_digest)
                >= (&pair[1].score.occurrence_id, &pair[1].score.semantic_digest)
        }) {
            return invalid("window score memberships must be sorted and duplicate-free");
        }
        for membership in &window.score_memberships {
            artifact_ref(&membership.score, "windows.scoreMemberships.score")?;
            artifact_ref(
                &membership.claim_occurrence,
                "windows.scoreMemberships.claimOccurrence",
            )?;
            artifact_ref(
                &membership.adjudication,
                "windows.scoreMemberships.adjudication",
            )?;
            if membership.outcome_available_at > window.embargo_through {
                return invalid("support window admitted an outcome after its embargo cutoff");
            }
            member_scores.push(membership.score.clone());
            member_occurrences.push(membership.claim_occurrence.clone());
        }
    }
    if value
        .windows
        .windows(2)
        .any(|pair| pair[0].embargo_through >= pair[1].start)
    {
        return invalid("evaluation windows must be chronological, embargoed, and nonadjacent");
    }
    member_scores.sort_by(|left, right| {
        (&left.occurrence_id, &left.semantic_digest)
            .cmp(&(&right.occurrence_id, &right.semantic_digest))
    });
    if member_scores != value.score_artifacts {
        return invalid("window membership must partition the exact scoreArtifacts set once");
    }
    member_occurrences.sort_by(|left, right| {
        (&left.occurrence_id, &left.semantic_digest)
            .cmp(&(&right.occurrence_id, &right.semantic_digest))
    });
    if member_occurrences.windows(2).any(|pair| pair[0] == pair[1]) {
        return invalid("repeated support cannot count one claim occurrence more than once");
    }
    for bin in &value.calibration_bins {
        if bin.lower_ppm.get() > bin.mean_forecast_ppm.get()
            || bin.mean_forecast_ppm.get() > bin.upper_ppm.get()
            || bin.upper_ppm.get() > PROBABILITY_SCALE_PPM
            || bin.observed_count.get() > bin.occurrence_count.get()
        {
            return invalid("calibration bin is outside its registered ppm/support bounds");
        }
    }
    let derived_maturity = if value.scored_occurrences.get() >= MIN_REPEATED_SUPPORT_SCORES
        && value.windows.len() >= 2
        && value
            .windows
            .iter()
            .all(|window| window.eligible_score_count.get() >= MIN_SCORES_PER_WINDOW)
    {
        SupportMaturityV1::RepeatedProspectiveSupport
    } else if value.scored_occurrences.get() > 0 {
        SupportMaturityV1::DescriptiveSupport
    } else {
        SupportMaturityV1::ClosureOnly
    };
    if value.maturity != derived_maturity {
        return invalid(
            "support maturity must be derived exactly from admitted scores and windows",
        );
    }
    Ok(())
}

/// Validates a support/calibration summary without upgrading its declared maturity.
///
/// # Errors
///
/// Refuses incomplete denominators, overlapping windows, invalid bins, or false maturity.
pub fn validate_support_summary(
    value: SupportCalibrationSummaryV1,
) -> Result<ValidatedArtifact<SupportCalibrationSummaryV1>> {
    support_summary_syntax(&value)?;
    freeze(value)
}

/// Strictly decodes canonical support/calibration bytes.
///
/// # Errors
///
/// Refuses noncanonical JSON or an invalid support summary.
pub fn decode_support_summary(
    bytes: &[u8],
) -> Result<ValidatedArtifact<SupportCalibrationSummaryV1>> {
    decode(bytes, support_summary_syntax)
}

pub(crate) fn score_header(value: &ProperScoreArtifactV1) -> Result<()> {
    header(
        &value.contract,
        value.schema_version.get(),
        SCORE_ARTIFACT_CONTRACT,
    )?;
    authority(value.authority)?;
    sha256(&value.calculation_build_digest, "calculationBuildDigest")?;
    artifact_ref(&value.claim_occurrence, "claimOccurrence")?;
    artifact_ref(&value.submission, "submission")?;
    artifact_ref(&value.adjudication, "adjudication")?;
    if let Some(reference) = &value.baseline_submission {
        artifact_ref(reference, "baselineSubmission")?;
    }
    Ok(())
}

/// Strictly decodes a score and recomputes it from its exact dependencies.
///
/// # Errors
///
/// Refuses noncanonical JSON, unqualified dependencies, or a nonreproducible score.
#[allow(clippy::too_many_arguments)]
pub fn decode_score_artifact(
    bytes: &[u8],
    definition: &ValidatedArtifact<ClaimDefinitionV1>,
    occurrence: &ValidatedArtifact<ClaimOccurrenceV1>,
    occurrence_capability: &crate::model::DurableOccurrenceCapability,
    candidate: &ValidatedArtifact<ForecastSubmissionV1>,
    candidate_capability: &crate::model::DurableSubmissionCapability,
    adjudication: &ValidatedArtifact<AdjudicationV1>,
    adjudication_capability: &crate::model::DurableAdjudicationCapability,
    baseline: Option<(
        &ValidatedArtifact<ForecastSubmissionV1>,
        &crate::model::DurableSubmissionCapability,
    )>,
) -> Result<ValidatedArtifact<ProperScoreArtifactV1>> {
    let (value, canonical) = decode_canonical(bytes)?;
    crate::score::score_syntax(
        &value,
        definition,
        occurrence,
        occurrence_capability,
        candidate,
        candidate_capability,
        adjudication,
        adjudication_capability,
        baseline,
    )?;
    ValidatedArtifact::new(value, canonical)
}
