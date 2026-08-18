//! Pure, fixture-only prospective campaign contracts for `N03/W6-C0`.
//!
//! The crate validates exact campaign registration and frozen enrollment against an exact N00
//! program registration. It performs no enrollment, randomization, acquisition, presentation,
//! reveal, adjudication, store write, or economic action. Public success is always
//! `unverified_semantic_fixture_only`.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_wave6_registry::{
    ProgramAuthorityV1, SemanticCeilingV1, ValidatedProgramRegistration, Wave6ProgramRegistrationV1,
};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Exact campaign registration contract.
pub const CAMPAIGN_REGISTRATION_CONTRACT: &str = "joshi.wave6.campaign-registration.v1";
/// Exact frozen enrollment contract.
pub const FROZEN_ENROLLMENT_CONTRACT: &str = "joshi.wave6.frozen-enrollment.v1";

/// Campaign contract result.
pub type Result<T> = std::result::Result<T, CampaignError>;

/// Exact fixture campaign contract failure.
#[derive(Debug, Error)]
pub enum CampaignError {
    /// JSON encoding or decoding failed.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    /// Exact bytes differed from compact JSON plus one newline.
    #[error("campaign bytes are not canonical compact JSON with one trailing newline")]
    NonCanonical,
    /// A shared identity wrapper rejected generated digest material.
    #[error("invalid campaign identity: {0}")]
    Identity(String),
    /// A digest was malformed or did not match recomputed exact material.
    #[error("campaign digest closure failure: {0}")]
    Digest(&'static str),
    /// The campaign widened or broke the owning program authority.
    #[error("campaign program/authority binding failure")]
    Program,
    /// Registration structure or chronology was invalid.
    #[error("campaign registration failure: {0}")]
    Registration(&'static str),
    /// Frozen enrollment was incomplete, branched, late, or inconsistent.
    #[error("campaign enrollment failure: {0}")]
    Enrollment(&'static str),
}

/// Fixed assignment mechanism available to this fixture contract.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssignmentMechanismV1 {
    /// Exact caller-fed assignments for contract testing only.
    DeterministicFixtureOnly,
}

/// Complete disposition grammar for a later outcome.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CensoringDispositionV1 {
    /// Exact observed outcome.
    ResolvedObserved,
    /// Healthy covered survival through horizon.
    HealthyNoEventThroughHorizon,
    /// Administrative censoring.
    AdministrativeCensored,
    /// Source loss.
    SourceLossCensored,
    /// Interval censoring.
    IntervalCensored,
    /// Competing event.
    CompetingEvent,
    /// Intervention invalidated the estimand.
    InterventionInvalidated,
    /// Conflicting evidence.
    Conflicting,
    /// Unsupported outcome.
    Unsupported,
    /// Still open.
    Open,
}

const ALL_CENSORING_DISPOSITIONS: [CensoringDispositionV1; 10] = [
    CensoringDispositionV1::ResolvedObserved,
    CensoringDispositionV1::HealthyNoEventThroughHorizon,
    CensoringDispositionV1::AdministrativeCensored,
    CensoringDispositionV1::SourceLossCensored,
    CensoringDispositionV1::IntervalCensored,
    CensoringDispositionV1::CompetingEvent,
    CensoringDispositionV1::InterventionInvalidated,
    CensoringDispositionV1::Conflicting,
    CensoringDispositionV1::Unsupported,
    CensoringDispositionV1::Open,
];

/// Exact estimand with a named denominator and unit.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignEstimandV1 {
    /// Estimand identity.
    pub estimand_id: StableString,
    /// Explicit numerator.
    pub numerator: StableString,
    /// Explicit denominator/risk set.
    pub denominator: StableString,
    /// Outcome name.
    pub outcome: StableString,
    /// Exact unit.
    pub unit: StableString,
}

/// Frozen eligible universe and its self-digest.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignUniverseV1 {
    /// Universe identity.
    pub universe_id: StableString,
    /// Strictly sorted eligible subjects.
    pub subject_ids: Vec<StableString>,
    /// Frozen inclusion rule.
    pub inclusion_rule: StableString,
    /// Registered exclusion reason codes.
    pub exclusion_reason_ids: Vec<StableString>,
    /// Digest of exact universe material excluding this field.
    pub universe_digest: ValueDigest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UniverseDigestMaterialV1<'a> {
    universe_id: &'a StableString,
    subject_ids: &'a [StableString],
    inclusion_rule: &'a StableString,
    exclusion_reason_ids: &'a [StableString],
}

/// One registered campaign arm.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignArmV1 {
    /// Arm identity.
    pub arm_id: StableString,
    /// Exact allocation probability in parts per million.
    pub probability_ppm: WireU64,
    /// Exact arm content/policy digest.
    pub arm_digest: ValueDigest,
    /// Invariant safety content shared across every arm.
    pub invariant_safety_digest: ValueDigest,
}

/// One frozen metric and its baseline/multiplicity family.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignMetricV1 {
    /// Metric identity.
    pub metric_id: StableString,
    /// Explicit numerator.
    pub numerator: StableString,
    /// Explicit denominator.
    pub denominator: StableString,
    /// Exact unit.
    pub unit: StableString,
    /// Named simple baseline.
    pub baseline_id: StableString,
    /// Multiplicity family.
    pub multiplicity_family_id: StableString,
}

/// Strict local resource ceiling; provider/external mutation are fixed at zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignBudgetsV1 {
    /// Local compute units.
    pub compute_units: WireU64,
    /// Local fixture read units.
    pub read_units: WireU64,
    /// Human attention units.
    pub attention_units: WireU64,
    /// Provider units; zero in V1.
    pub provider_units: WireU64,
    /// External mutation units; zero in V1.
    pub external_mutation_units: WireU64,
    /// Maximum eligible subjects.
    pub max_subjects: WireU64,
}

/// Independent hard stops.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignStopRulesV1 {
    /// Apparatus stop.
    pub apparatus_stop: StableString,
    /// Scientific stop.
    pub scientific_stop: StableString,
    /// Operator burden/safety stop.
    pub operator_stop: StableString,
}

/// Exact caller-fed campaign registration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignRegistrationV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Owning N00 program.
    pub program_id: StableString,
    /// Owning N00 registration digest.
    pub program_registration_digest: ValueDigest,
    /// Campaign identity.
    pub campaign_id: StableString,
    /// Campaign family.
    pub campaign_family_id: StableString,
    /// Semantic version.
    pub semantic_version: StableString,
    /// Composite object/estimand name.
    pub object: StableString,
    /// Exact estimand.
    pub estimand: CampaignEstimandV1,
    /// Frozen eligible universe.
    pub universe: CampaignUniverseV1,
    /// Fixture-only assignment mechanism.
    pub assignment_mechanism: AssignmentMechanismV1,
    /// Strictly sorted arms.
    pub arms: Vec<CampaignArmV1>,
    /// Strictly sorted metrics.
    pub metrics: Vec<CampaignMetricV1>,
    /// Exact inference method; descriptive fixture only in V1.
    pub inference_method: StableString,
    /// Complete censoring/competing-event grammar.
    pub censoring_dispositions: Vec<CensoringDispositionV1>,
    /// Frozen correction contract.
    pub correction_contract: StableString,
    /// Frozen contamination contract.
    pub contamination_contract: StableString,
    /// Resource ceilings.
    pub budgets: CampaignBudgetsV1,
    /// Independent stop rules.
    pub stop_rules: CampaignStopRulesV1,
    /// Fixture registration time.
    pub registered_at: UtcTimestamp,
    /// Enrollment deadline.
    pub enrollment_cutoff: UtcTimestamp,
    /// Latest input knowledge.
    pub input_knowledge_cutoff: UtcTimestamp,
    /// Seal deadline.
    pub seal_deadline: UtcTimestamp,
    /// Maturity deadline.
    pub maturity_deadline: UtcTimestamp,
    /// Latest outcome knowledge.
    pub outcome_knowledge_cutoff: UtcTimestamp,
    /// Adjudication deadline.
    pub adjudication_deadline: UtcTimestamp,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Digest over exact material excluding this field.
    pub campaign_registration_digest: ValueDigest,
}

/// Exact registration digest material.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampaignRegistrationDigestMaterialV1<'a> {
    contract: &'a StableString,
    program_id: &'a StableString,
    program_registration_digest: &'a ValueDigest,
    campaign_id: &'a StableString,
    campaign_family_id: &'a StableString,
    semantic_version: &'a StableString,
    object: &'a StableString,
    estimand: &'a CampaignEstimandV1,
    universe: &'a CampaignUniverseV1,
    assignment_mechanism: AssignmentMechanismV1,
    arms: &'a [CampaignArmV1],
    metrics: &'a [CampaignMetricV1],
    inference_method: &'a StableString,
    censoring_dispositions: &'a [CensoringDispositionV1],
    correction_contract: &'a StableString,
    contamination_contract: &'a StableString,
    budgets: &'a CampaignBudgetsV1,
    stop_rules: &'a CampaignStopRulesV1,
    registered_at: UtcTimestamp,
    enrollment_cutoff: UtcTimestamp,
    input_knowledge_cutoff: UtcTimestamp,
    seal_deadline: UtcTimestamp,
    maturity_deadline: UtcTimestamp,
    outcome_knowledge_cutoff: UtcTimestamp,
    adjudication_deadline: UtcTimestamp,
    authority: ProgramAuthorityV1,
    semantic_ceiling: SemanticCeilingV1,
}

/// One exact subject enrollment disposition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EnrollmentDispositionV1 {
    /// Subject in the registered universe.
    pub subject_id: StableString,
    /// Included in the frozen risk set.
    pub included: bool,
    /// Registered reason when excluded; absent when included.
    pub exclusion_reason_id: Option<StableString>,
}

/// Exact caller-fed frozen enrollment.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FrozenEnrollmentV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Campaign identity.
    pub campaign_id: StableString,
    /// Exact campaign registration digest.
    pub campaign_registration_digest: ValueDigest,
    /// Enrollment occurrence identity.
    pub enrollment_id: StableString,
    /// One disposition for every registered universe subject.
    pub dispositions: Vec<EnrollmentDispositionV1>,
    /// Fixture freeze clock.
    pub frozen_at: UtcTimestamp,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Digest over exact material excluding this field.
    pub enrollment_digest: ValueDigest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FrozenEnrollmentDigestMaterialV1<'a> {
    contract: &'a StableString,
    campaign_id: &'a StableString,
    campaign_registration_digest: &'a ValueDigest,
    enrollment_id: &'a StableString,
    dispositions: &'a [EnrollmentDispositionV1],
    frozen_at: UtcTimestamp,
    authority: ProgramAuthorityV1,
    semantic_ceiling: SemanticCeilingV1,
}

/// Strictly validated exact fixture bytes with no durable authority.
#[derive(Clone, Debug)]
pub struct UnverifiedSemantic<T> {
    value: T,
    exact_bytes: Vec<u8>,
    document_digest: ValueDigest,
}

impl<T> UnverifiedSemantic<T> {
    /// Validated caller-fed value.
    #[must_use]
    pub const fn value(&self) -> &T {
        &self.value
    }

    /// Exact canonical bytes.
    #[must_use]
    pub fn exact_bytes(&self) -> &[u8] {
        &self.exact_bytes
    }

    /// Full document digest.
    #[must_use]
    pub const fn document_digest(&self) -> &ValueDigest {
        &self.document_digest
    }

    /// Public ceiling can never rise above fixture semantics.
    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

/// Compact JSON plus one newline.
///
/// # Errors
///
/// Returns JSON serialization errors.
pub fn canonical_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let mut bytes = serde_json::to_vec(value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

/// Algorithm-qualified exact SHA-256.
///
/// # Errors
///
/// Returns an error only if the shared stable wrapper rejects generated output.
pub fn digest_bytes(bytes: &[u8]) -> Result<ValueDigest> {
    let hex = format!("{:x}", Sha256::digest(bytes));
    ValueDigest::new(format!("sha256:{hex}"))
        .map_err(|error| CampaignError::Identity(error.to_string()))
}

fn decode_canonical<T: DeserializeOwned + Serialize>(bytes: &[u8]) -> Result<T> {
    let value = serde_json::from_slice(bytes)?;
    if canonical_bytes(&value)? != bytes {
        return Err(CampaignError::NonCanonical);
    }
    Ok(value)
}

fn validate_sha256(value: &ValueDigest, field: &'static str) -> Result<()> {
    let Some(hex) = value.as_str().strip_prefix("sha256:") else {
        return Err(CampaignError::Digest(field));
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(CampaignError::Digest(field));
    }
    Ok(())
}

fn sorted_unique<T: Ord>(values: &[T]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
}

impl CampaignUniverseV1 {
    /// Recomputes exact universe digest.
    ///
    /// # Errors
    ///
    /// Returns serialization/identity errors.
    pub fn computed_digest(&self) -> Result<ValueDigest> {
        digest_bytes(&canonical_bytes(&UniverseDigestMaterialV1 {
            universe_id: &self.universe_id,
            subject_ids: &self.subject_ids,
            inclusion_rule: &self.inclusion_rule,
            exclusion_reason_ids: &self.exclusion_reason_ids,
        })?)
    }

    fn validate(&self) -> Result<()> {
        if self.subject_ids.is_empty()
            || !sorted_unique(&self.subject_ids)
            || !sorted_unique(&self.exclusion_reason_ids)
        {
            return Err(CampaignError::Registration("universe closure"));
        }
        validate_sha256(&self.universe_digest, "universeDigest")?;
        if self.computed_digest()? != self.universe_digest {
            return Err(CampaignError::Digest("universeDigest"));
        }
        Ok(())
    }
}

impl CampaignRegistrationV1 {
    /// Exact material covered by `campaign_registration_digest`.
    #[must_use]
    pub fn digest_material(&self) -> CampaignRegistrationDigestMaterialV1<'_> {
        CampaignRegistrationDigestMaterialV1 {
            contract: &self.contract,
            program_id: &self.program_id,
            program_registration_digest: &self.program_registration_digest,
            campaign_id: &self.campaign_id,
            campaign_family_id: &self.campaign_family_id,
            semantic_version: &self.semantic_version,
            object: &self.object,
            estimand: &self.estimand,
            universe: &self.universe,
            assignment_mechanism: self.assignment_mechanism,
            arms: &self.arms,
            metrics: &self.metrics,
            inference_method: &self.inference_method,
            censoring_dispositions: &self.censoring_dispositions,
            correction_contract: &self.correction_contract,
            contamination_contract: &self.contamination_contract,
            budgets: &self.budgets,
            stop_rules: &self.stop_rules,
            registered_at: self.registered_at,
            enrollment_cutoff: self.enrollment_cutoff,
            input_knowledge_cutoff: self.input_knowledge_cutoff,
            seal_deadline: self.seal_deadline,
            maturity_deadline: self.maturity_deadline,
            outcome_knowledge_cutoff: self.outcome_knowledge_cutoff,
            adjudication_deadline: self.adjudication_deadline,
            authority: self.authority,
            semantic_ceiling: self.semantic_ceiling,
        }
    }

    /// Revalidates exact fixture campaign registration.
    ///
    /// # Errors
    ///
    /// Refuses program/authority mismatch, incomplete universe, probability/safety/metric defects,
    /// nonzero provider/external budgets, incomplete censor grammar, bad chronology, or digest.
    pub fn validate(&self, program: &Wave6ProgramRegistrationV1) -> Result<()> {
        if self.contract.as_str() != CAMPAIGN_REGISTRATION_CONTRACT
            || self.program_id != program.program_id
            || self.program_registration_digest != program.registration_digest
            || self.authority != program.authority
            || self.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(CampaignError::Program);
        }
        self.universe.validate()?;
        if self.arms.len() < 2
            || !self
                .arms
                .windows(2)
                .all(|pair| pair[0].arm_id < pair[1].arm_id)
            || self.metrics.is_empty()
            || !self
                .metrics
                .windows(2)
                .all(|pair| pair[0].metric_id < pair[1].metric_id)
        {
            return Err(CampaignError::Registration("arms or metrics"));
        }
        let mut probability = 0_u64;
        let safety = &self.arms[0].invariant_safety_digest;
        let mut arm_digests = BTreeSet::new();
        for arm in &self.arms {
            validate_sha256(&arm.arm_digest, "arms.armDigest")?;
            validate_sha256(&arm.invariant_safety_digest, "arms.invariantSafetyDigest")?;
            probability = probability
                .checked_add(arm.probability_ppm.get())
                .ok_or(CampaignError::Registration("probability overflow"))?;
            if &arm.invariant_safety_digest != safety || !arm_digests.insert(arm.arm_digest.clone())
            {
                return Err(CampaignError::Registration("arm safety/content"));
            }
        }
        if probability != 1_000_000 {
            return Err(CampaignError::Registration("allocation probability"));
        }
        let max_subjects = usize::try_from(self.budgets.max_subjects.get())
            .map_err(|_| CampaignError::Registration("max subjects overflow"))?;
        if self.inference_method.as_str() != "descriptive_fixture_exact_only"
            || self.censoring_dispositions != ALL_CENSORING_DISPOSITIONS
            || self.budgets.provider_units.get() != 0
            || self.budgets.external_mutation_units.get() != 0
            || max_subjects < self.universe.subject_ids.len()
        {
            return Err(CampaignError::Registration("authority or budget boundary"));
        }
        if !(self.registered_at <= self.enrollment_cutoff
            && self.enrollment_cutoff <= self.input_knowledge_cutoff
            && self.input_knowledge_cutoff < self.seal_deadline
            && self.seal_deadline <= self.maturity_deadline
            && self.maturity_deadline <= self.outcome_knowledge_cutoff
            && self.outcome_knowledge_cutoff <= self.adjudication_deadline)
        {
            return Err(CampaignError::Registration("deadline chronology"));
        }
        validate_sha256(
            &self.campaign_registration_digest,
            "campaignRegistrationDigest",
        )?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)?
            != self.campaign_registration_digest
        {
            return Err(CampaignError::Digest("campaignRegistrationDigest"));
        }
        Ok(())
    }
}

impl FrozenEnrollmentV1 {
    fn digest_material(&self) -> FrozenEnrollmentDigestMaterialV1<'_> {
        FrozenEnrollmentDigestMaterialV1 {
            contract: &self.contract,
            campaign_id: &self.campaign_id,
            campaign_registration_digest: &self.campaign_registration_digest,
            enrollment_id: &self.enrollment_id,
            dispositions: &self.dispositions,
            frozen_at: self.frozen_at,
            authority: self.authority,
            semantic_ceiling: self.semantic_ceiling,
        }
    }

    /// Revalidates exact one-row-per-subject frozen enrollment.
    ///
    /// # Errors
    ///
    /// Refuses missing/extra/reordered subjects, invalid exclusions, empty enrollment, late freeze,
    /// authority mismatch, or digest mismatch.
    pub fn validate(&self, registration: &CampaignRegistrationV1) -> Result<()> {
        if self.contract.as_str() != FROZEN_ENROLLMENT_CONTRACT
            || self.campaign_id != registration.campaign_id
            || self.campaign_registration_digest != registration.campaign_registration_digest
            || self.authority != registration.authority
            || self.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            || self.frozen_at < registration.registered_at
            || self.frozen_at > registration.enrollment_cutoff
            || self.dispositions.len() != registration.universe.subject_ids.len()
        {
            return Err(CampaignError::Enrollment("registration binding"));
        }
        let reasons: BTreeSet<_> = registration.universe.exclusion_reason_ids.iter().collect();
        let mut included = 0_usize;
        for (subject, disposition) in registration
            .universe
            .subject_ids
            .iter()
            .zip(&self.dispositions)
        {
            if subject != &disposition.subject_id
                || disposition.included == disposition.exclusion_reason_id.is_some()
                || disposition
                    .exclusion_reason_id
                    .as_ref()
                    .is_some_and(|reason| !reasons.contains(reason))
            {
                return Err(CampaignError::Enrollment("subject disposition"));
            }
            included += usize::from(disposition.included);
        }
        if included == 0 {
            return Err(CampaignError::Enrollment("empty enrollment"));
        }
        validate_sha256(&self.enrollment_digest, "enrollmentDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.enrollment_digest {
            return Err(CampaignError::Digest("enrollmentDigest"));
        }
        Ok(())
    }
}

/// Strictly parses exact campaign registration bytes against N00.
///
/// # Errors
///
/// Refuses noncanonical bytes or any semantic/digest defect.
pub fn parse_campaign_registration_exact(
    bytes: &[u8],
    program: &ValidatedProgramRegistration,
) -> Result<UnverifiedSemantic<CampaignRegistrationV1>> {
    let value: CampaignRegistrationV1 = decode_canonical(bytes)?;
    value.validate(program.value())?;
    Ok(UnverifiedSemantic {
        value,
        exact_bytes: bytes.to_vec(),
        document_digest: digest_bytes(bytes)?,
    })
}

/// Strictly parses exact frozen enrollment bytes.
///
/// # Errors
///
/// Refuses noncanonical bytes or incomplete/late/digest-invalid enrollment.
pub fn parse_frozen_enrollment_exact(
    bytes: &[u8],
    registration: &UnverifiedSemantic<CampaignRegistrationV1>,
) -> Result<UnverifiedSemantic<FrozenEnrollmentV1>> {
    let value: FrozenEnrollmentV1 = decode_canonical(bytes)?;
    value.validate(registration.value())?;
    Ok(UnverifiedSemantic {
        value,
        exact_bytes: bytes.to_vec(),
        document_digest: digest_bytes(bytes)?,
    })
}

#[cfg(test)]
mod tests;
