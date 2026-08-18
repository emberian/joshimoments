use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_wave6_registry::{ProgramAuthorityV1, SemanticCeilingV1};
use serde::{Deserialize, Serialize};

use crate::{
    CampaignError, CampaignRegistrationV1, CensoringDispositionV1, FrozenEnrollmentV1, Result,
    UnverifiedSemantic, canonical_bytes, decode_canonical, digest_bytes, sorted_unique,
    validate_sha256,
};

/// Exact fixture-only assignment contract.
pub const CAMPAIGN_ASSIGNMENT_CONTRACT: &str = "joshi.wave6.campaign-assignment.v1";
/// Exact fixture-only evidence seal contract.
pub const CAMPAIGN_SEAL_CONTRACT: &str = "joshi.wave6.campaign-seal.v1";
/// Exact fixture-only typed adjudication contract.
pub const CAMPAIGN_ADJUDICATION_CONTRACT: &str = "joshi.wave6.campaign-adjudication.v1";

/// One exact assignment for one included subject.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignAssignmentRowV1 {
    /// Included subject identity.
    pub subject_id: StableString,
    /// Registered arm identity.
    pub arm_id: StableString,
    /// Exact registered arm probability copied into the assignment.
    pub probability_ppm: WireU64,
}

/// Exact caller-fed deterministic fixture assignment.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignAssignmentV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Campaign identity.
    pub campaign_id: StableString,
    /// Exact campaign registration digest.
    pub campaign_registration_digest: ValueDigest,
    /// Frozen enrollment identity.
    pub enrollment_id: StableString,
    /// Exact frozen enrollment digest.
    pub enrollment_digest: ValueDigest,
    /// Assignment occurrence identity.
    pub assignment_id: StableString,
    /// Caller-fed deterministic fixture basis digest; never randomization authority.
    pub assignment_basis_digest: ValueDigest,
    /// One row for every included subject, in frozen-universe order.
    pub assignments: Vec<CampaignAssignmentRowV1>,
    /// Fixture assignment clock.
    pub assigned_at: UtcTimestamp,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Digest over exact material excluding this field.
    pub assignment_digest: ValueDigest,
}

/// Exact assignment digest material.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampaignAssignmentDigestMaterialV1<'a> {
    contract: &'a StableString,
    campaign_id: &'a StableString,
    campaign_registration_digest: &'a ValueDigest,
    enrollment_id: &'a StableString,
    enrollment_digest: &'a ValueDigest,
    assignment_id: &'a StableString,
    assignment_basis_digest: &'a ValueDigest,
    assignments: &'a [CampaignAssignmentRowV1],
    assigned_at: UtcTimestamp,
    authority: ProgramAuthorityV1,
    semantic_ceiling: SemanticCeilingV1,
}

/// Exact caller-fed evidence identity and as-known boundary.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignEvidenceRefV1 {
    /// Artifact identity.
    pub artifact_id: StableString,
    /// Versioned artifact contract.
    pub artifact_contract: StableString,
    /// Exact artifact byte digest.
    pub content_digest: ValueDigest,
    /// When the referenced material became available.
    pub available_at: UtcTimestamp,
    /// Caller-fed fixture commit sequence; not store authority.
    pub alleged_commit_seq: WireU64,
}

/// Exact frozen input/evidence seal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignSealV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Campaign identity.
    pub campaign_id: StableString,
    /// Exact campaign registration digest.
    pub campaign_registration_digest: ValueDigest,
    /// Frozen enrollment identity.
    pub enrollment_id: StableString,
    /// Exact frozen enrollment digest.
    pub enrollment_digest: ValueDigest,
    /// Assignment identity.
    pub assignment_id: StableString,
    /// Exact assignment digest.
    pub assignment_digest: ValueDigest,
    /// Seal occurrence identity.
    pub seal_id: StableString,
    /// Must equal the registered input cutoff.
    pub input_knowledge_cutoff: UtcTimestamp,
    /// Maximum caller-fed fixture commit admitted by the seal.
    pub as_of_commit_seq: WireU64,
    /// Strictly sorted, nonempty exact evidence closure.
    pub evidence: Vec<CampaignEvidenceRefV1>,
    /// Fixture seal clock.
    pub sealed_at: UtcTimestamp,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Digest over exact material excluding this field.
    pub seal_digest: ValueDigest,
}

/// Exact seal digest material.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampaignSealDigestMaterialV1<'a> {
    contract: &'a StableString,
    campaign_id: &'a StableString,
    campaign_registration_digest: &'a ValueDigest,
    enrollment_id: &'a StableString,
    enrollment_digest: &'a ValueDigest,
    assignment_id: &'a StableString,
    assignment_digest: &'a ValueDigest,
    seal_id: &'a StableString,
    input_knowledge_cutoff: UtcTimestamp,
    as_of_commit_seq: WireU64,
    evidence: &'a [CampaignEvidenceRefV1],
    sealed_at: UtcTimestamp,
    authority: ProgramAuthorityV1,
    semantic_ceiling: SemanticCeilingV1,
}

/// Public adjudication claim is only an exact fixture disposition, never a result or score.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FixtureAdjudicationClaimV1 {
    /// Caller-fed exact typed disposition at the unverified fixture ceiling.
    DescriptiveFixtureDispositionOnly,
}

/// One exact outcome/censoring disposition for one included subject.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignOutcomeV1 {
    /// Included subject identity.
    pub subject_id: StableString,
    /// Registered outcome/censoring state.
    pub disposition: CensoringDispositionV1,
    /// Exact observed value only for `resolved_observed`.
    pub observed_value: Option<StableString>,
    /// Exact registered estimand unit only when a value is present.
    pub observed_unit: Option<StableString>,
    /// Strictly sorted exact evidence known by this row's clock.
    pub evidence: Vec<CampaignEvidenceRefV1>,
    /// Strictly sorted typed coverage/source gaps where required.
    pub gap_ids: Vec<StableString>,
    /// When this exact disposition became known.
    pub known_at: UtcTimestamp,
}

/// Exact caller-fed fixture adjudication with one disposition per included subject.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignAdjudicationV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Campaign identity.
    pub campaign_id: StableString,
    /// Exact campaign registration digest.
    pub campaign_registration_digest: ValueDigest,
    /// Frozen enrollment identity.
    pub enrollment_id: StableString,
    /// Exact frozen enrollment digest.
    pub enrollment_digest: ValueDigest,
    /// Exact seal identity.
    pub seal_id: StableString,
    /// Exact seal digest.
    pub seal_digest: ValueDigest,
    /// Adjudication occurrence identity.
    pub adjudication_id: StableString,
    /// Must equal the registered outcome knowledge cutoff.
    pub outcome_knowledge_cutoff: UtcTimestamp,
    /// Maximum caller-fed fixture commit admitted by outcome evidence.
    pub as_of_commit_seq: WireU64,
    /// One exact row per frozen included subject.
    pub outcomes: Vec<CampaignOutcomeV1>,
    /// Fixed nonpromoting claim kind.
    pub claim: FixtureAdjudicationClaimV1,
    /// Fixture adjudication clock.
    pub adjudicated_at: UtcTimestamp,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Digest over exact material excluding this field.
    pub adjudication_digest: ValueDigest,
}

/// Exact adjudication digest material.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampaignAdjudicationDigestMaterialV1<'a> {
    contract: &'a StableString,
    campaign_id: &'a StableString,
    campaign_registration_digest: &'a ValueDigest,
    enrollment_id: &'a StableString,
    enrollment_digest: &'a ValueDigest,
    seal_id: &'a StableString,
    seal_digest: &'a ValueDigest,
    adjudication_id: &'a StableString,
    outcome_knowledge_cutoff: UtcTimestamp,
    as_of_commit_seq: WireU64,
    outcomes: &'a [CampaignOutcomeV1],
    claim: FixtureAdjudicationClaimV1,
    adjudicated_at: UtcTimestamp,
    authority: ProgramAuthorityV1,
    semantic_ceiling: SemanticCeilingV1,
}

fn included_subjects(enrollment: &FrozenEnrollmentV1) -> Vec<&StableString> {
    enrollment
        .dispositions
        .iter()
        .filter(|row| row.included)
        .map(|row| &row.subject_id)
        .collect()
}

fn validate_evidence_ref(
    evidence: &CampaignEvidenceRefV1,
    cutoff: UtcTimestamp,
    as_of_commit_seq: WireU64,
) -> Result<()> {
    validate_sha256(&evidence.content_digest, "evidence.contentDigest")?;
    if evidence.available_at > cutoff
        || evidence.alleged_commit_seq.get() == 0
        || evidence.alleged_commit_seq > as_of_commit_seq
    {
        return Err(CampaignError::Seal("evidence cutoff"));
    }
    Ok(())
}

fn evidence_sorted_unique(evidence: &[CampaignEvidenceRefV1]) -> bool {
    evidence
        .windows(2)
        .all(|pair| pair[0].artifact_id < pair[1].artifact_id)
}

fn canonical_signed_i128(value: &str) -> bool {
    if value == "0" {
        return true;
    }
    let digits = value.strip_prefix('-').unwrap_or(value);
    !digits.is_empty()
        && !digits.starts_with('0')
        && digits.bytes().all(|byte| byte.is_ascii_digit())
        && value.parse::<i128>().is_ok()
}

impl CampaignAssignmentV1 {
    /// Exact material covered by `assignment_digest`.
    #[must_use]
    pub fn digest_material(&self) -> CampaignAssignmentDigestMaterialV1<'_> {
        CampaignAssignmentDigestMaterialV1 {
            contract: &self.contract,
            campaign_id: &self.campaign_id,
            campaign_registration_digest: &self.campaign_registration_digest,
            enrollment_id: &self.enrollment_id,
            enrollment_digest: &self.enrollment_digest,
            assignment_id: &self.assignment_id,
            assignment_basis_digest: &self.assignment_basis_digest,
            assignments: &self.assignments,
            assigned_at: self.assigned_at,
            authority: self.authority,
            semantic_ceiling: self.semantic_ceiling,
        }
    }

    fn validate(
        &self,
        registration: &CampaignRegistrationV1,
        enrollment: &FrozenEnrollmentV1,
    ) -> Result<()> {
        if self.contract.as_str() != CAMPAIGN_ASSIGNMENT_CONTRACT
            || self.campaign_id != registration.campaign_id
            || self.campaign_registration_digest != registration.campaign_registration_digest
            || self.enrollment_id != enrollment.enrollment_id
            || self.enrollment_digest != enrollment.enrollment_digest
            || self.authority != registration.authority
            || self.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            || self.assigned_at <= enrollment.frozen_at
            || self.assigned_at > registration.input_knowledge_cutoff
        {
            return Err(CampaignError::Assignment("chain binding"));
        }
        validate_sha256(&self.assignment_basis_digest, "assignmentBasisDigest")?;
        let subjects = included_subjects(enrollment);
        if self.assignments.len() != subjects.len() {
            return Err(CampaignError::Assignment("subject closure"));
        }
        for (subject, assignment) in subjects.into_iter().zip(&self.assignments) {
            let arm = registration
                .arms
                .iter()
                .find(|arm| arm.arm_id == assignment.arm_id)
                .ok_or(CampaignError::Assignment("unknown arm"))?;
            if subject != &assignment.subject_id
                || assignment.probability_ppm != arm.probability_ppm
            {
                return Err(CampaignError::Assignment("subject or probability"));
            }
        }
        validate_sha256(&self.assignment_digest, "assignmentDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.assignment_digest {
            return Err(CampaignError::Digest("assignmentDigest"));
        }
        Ok(())
    }
}

impl CampaignSealV1 {
    /// Exact material covered by `seal_digest`.
    #[must_use]
    pub fn digest_material(&self) -> CampaignSealDigestMaterialV1<'_> {
        CampaignSealDigestMaterialV1 {
            contract: &self.contract,
            campaign_id: &self.campaign_id,
            campaign_registration_digest: &self.campaign_registration_digest,
            enrollment_id: &self.enrollment_id,
            enrollment_digest: &self.enrollment_digest,
            assignment_id: &self.assignment_id,
            assignment_digest: &self.assignment_digest,
            seal_id: &self.seal_id,
            input_knowledge_cutoff: self.input_knowledge_cutoff,
            as_of_commit_seq: self.as_of_commit_seq,
            evidence: &self.evidence,
            sealed_at: self.sealed_at,
            authority: self.authority,
            semantic_ceiling: self.semantic_ceiling,
        }
    }

    fn validate(
        &self,
        registration: &CampaignRegistrationV1,
        enrollment: &FrozenEnrollmentV1,
        assignment: &CampaignAssignmentV1,
    ) -> Result<()> {
        if self.contract.as_str() != CAMPAIGN_SEAL_CONTRACT
            || self.campaign_id != registration.campaign_id
            || self.campaign_registration_digest != registration.campaign_registration_digest
            || self.enrollment_id != enrollment.enrollment_id
            || self.enrollment_digest != enrollment.enrollment_digest
            || self.assignment_id != assignment.assignment_id
            || self.assignment_digest != assignment.assignment_digest
            || self.input_knowledge_cutoff != registration.input_knowledge_cutoff
            || self.authority != registration.authority
            || self.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            || self.as_of_commit_seq.get() == 0
            || self.sealed_at <= assignment.assigned_at
            || self.sealed_at <= registration.input_knowledge_cutoff
            || self.sealed_at > registration.seal_deadline
            || self.evidence.is_empty()
            || !evidence_sorted_unique(&self.evidence)
        {
            return Err(CampaignError::Seal(
                "chain, chronology, or evidence closure",
            ));
        }
        for evidence in &self.evidence {
            validate_evidence_ref(evidence, self.input_knowledge_cutoff, self.as_of_commit_seq)?;
        }
        validate_sha256(&self.seal_digest, "sealDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.seal_digest {
            return Err(CampaignError::Digest("sealDigest"));
        }
        Ok(())
    }
}

impl CampaignOutcomeV1 {
    fn validate(
        &self,
        registration: &CampaignRegistrationV1,
        cutoff: UtcTimestamp,
        as_of_commit_seq: WireU64,
    ) -> Result<()> {
        if self.known_at < registration.maturity_deadline
            || self.known_at > cutoff
            || !evidence_sorted_unique(&self.evidence)
            || !sorted_unique(&self.gap_ids)
        {
            return Err(CampaignError::Adjudication("outcome cutoff or ordering"));
        }
        for evidence in &self.evidence {
            validate_evidence_ref(evidence, self.known_at, as_of_commit_seq)
                .map_err(|_| CampaignError::Adjudication("outcome evidence cutoff"))?;
        }
        let value_present = self.observed_value.is_some();
        if value_present != self.observed_unit.is_some()
            || self
                .observed_unit
                .as_ref()
                .is_some_and(|unit| unit != &registration.estimand.unit)
            || self.observed_value.as_ref().is_some_and(|value| {
                registration.estimand.value_contract.as_str() != "canonical_signed_i128_decimal"
                    || !canonical_signed_i128(value.as_str())
            })
        {
            return Err(CampaignError::Adjudication("outcome value/unit"));
        }
        let valid_shape = match self.disposition {
            CensoringDispositionV1::ResolvedObserved => {
                value_present && !self.evidence.is_empty() && self.gap_ids.is_empty()
            }
            CensoringDispositionV1::HealthyNoEventThroughHorizon
            | CensoringDispositionV1::AdministrativeCensored
            | CensoringDispositionV1::CompetingEvent
            | CensoringDispositionV1::InterventionInvalidated => {
                !value_present && !self.evidence.is_empty() && self.gap_ids.is_empty()
            }
            CensoringDispositionV1::SourceLossCensored
            | CensoringDispositionV1::Unsupported
            | CensoringDispositionV1::Open => !value_present && !self.gap_ids.is_empty(),
            CensoringDispositionV1::IntervalCensored => {
                !value_present && !self.evidence.is_empty() && !self.gap_ids.is_empty()
            }
            CensoringDispositionV1::Conflicting => {
                !value_present && self.evidence.len() >= 2 && self.gap_ids.is_empty()
            }
        };
        if !valid_shape {
            return Err(CampaignError::Adjudication("disposition evidence shape"));
        }
        Ok(())
    }
}

impl CampaignAdjudicationV1 {
    /// Exact material covered by `adjudication_digest`.
    #[must_use]
    pub fn digest_material(&self) -> CampaignAdjudicationDigestMaterialV1<'_> {
        CampaignAdjudicationDigestMaterialV1 {
            contract: &self.contract,
            campaign_id: &self.campaign_id,
            campaign_registration_digest: &self.campaign_registration_digest,
            enrollment_id: &self.enrollment_id,
            enrollment_digest: &self.enrollment_digest,
            seal_id: &self.seal_id,
            seal_digest: &self.seal_digest,
            adjudication_id: &self.adjudication_id,
            outcome_knowledge_cutoff: self.outcome_knowledge_cutoff,
            as_of_commit_seq: self.as_of_commit_seq,
            outcomes: &self.outcomes,
            claim: self.claim,
            adjudicated_at: self.adjudicated_at,
            authority: self.authority,
            semantic_ceiling: self.semantic_ceiling,
        }
    }

    fn validate(
        &self,
        registration: &CampaignRegistrationV1,
        enrollment: &FrozenEnrollmentV1,
        seal: &CampaignSealV1,
    ) -> Result<()> {
        if self.contract.as_str() != CAMPAIGN_ADJUDICATION_CONTRACT
            || self.campaign_id != registration.campaign_id
            || self.campaign_registration_digest != registration.campaign_registration_digest
            || self.enrollment_id != enrollment.enrollment_id
            || self.enrollment_digest != enrollment.enrollment_digest
            || self.seal_id != seal.seal_id
            || self.seal_digest != seal.seal_digest
            || self.outcome_knowledge_cutoff != registration.outcome_knowledge_cutoff
            || self.claim != FixtureAdjudicationClaimV1::DescriptiveFixtureDispositionOnly
            || self.authority != registration.authority
            || self.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
            || self.as_of_commit_seq < seal.as_of_commit_seq
            || self.adjudicated_at < registration.outcome_knowledge_cutoff
            || self.adjudicated_at > registration.adjudication_deadline
        {
            return Err(CampaignError::Adjudication("chain or chronology"));
        }
        let subjects = included_subjects(enrollment);
        if self.outcomes.len() != subjects.len() {
            return Err(CampaignError::Adjudication("subject closure"));
        }
        for (subject, outcome) in subjects.into_iter().zip(&self.outcomes) {
            if subject != &outcome.subject_id || outcome.known_at > self.adjudicated_at {
                return Err(CampaignError::Adjudication("subject or decision clock"));
            }
            outcome.validate(
                registration,
                self.outcome_knowledge_cutoff,
                self.as_of_commit_seq,
            )?;
        }
        validate_sha256(&self.adjudication_digest, "adjudicationDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.adjudication_digest {
            return Err(CampaignError::Digest("adjudicationDigest"));
        }
        Ok(())
    }
}

/// Strictly parses one exact fixture assignment.
///
/// # Errors
///
/// Refuses any chain, subject, arm, probability, chronology, authority, or digest mismatch.
pub fn parse_campaign_assignment_exact(
    bytes: &[u8],
    registration: &UnverifiedSemantic<CampaignRegistrationV1>,
    enrollment: &UnverifiedSemantic<FrozenEnrollmentV1>,
) -> Result<UnverifiedSemantic<CampaignAssignmentV1>> {
    let value: CampaignAssignmentV1 = decode_canonical(bytes)?;
    value.validate(registration.value(), enrollment.value())?;
    Ok(UnverifiedSemantic {
        value,
        exact_bytes: bytes.to_vec(),
        document_digest: digest_bytes(bytes)?,
    })
}

/// Strictly parses one exact fixture evidence seal.
///
/// # Errors
///
/// Refuses any chain, cutoff, evidence, chronology, authority, or digest mismatch.
pub fn parse_campaign_seal_exact(
    bytes: &[u8],
    registration: &UnverifiedSemantic<CampaignRegistrationV1>,
    enrollment: &UnverifiedSemantic<FrozenEnrollmentV1>,
    assignment: &UnverifiedSemantic<CampaignAssignmentV1>,
) -> Result<UnverifiedSemantic<CampaignSealV1>> {
    let value: CampaignSealV1 = decode_canonical(bytes)?;
    value.validate(registration.value(), enrollment.value(), assignment.value())?;
    Ok(UnverifiedSemantic {
        value,
        exact_bytes: bytes.to_vec(),
        document_digest: digest_bytes(bytes)?,
    })
}

/// Strictly parses one exact fixture adjudication.
///
/// # Errors
///
/// Refuses any chain, subject, disposition, evidence, gap, chronology, authority, or digest
/// mismatch.
pub fn parse_campaign_adjudication_exact(
    bytes: &[u8],
    registration: &UnverifiedSemantic<CampaignRegistrationV1>,
    enrollment: &UnverifiedSemantic<FrozenEnrollmentV1>,
    seal: &UnverifiedSemantic<CampaignSealV1>,
) -> Result<UnverifiedSemantic<CampaignAdjudicationV1>> {
    let value: CampaignAdjudicationV1 = decode_canonical(bytes)?;
    value.validate(registration.value(), enrollment.value(), seal.value())?;
    Ok(UnverifiedSemantic {
        value,
        exact_bytes: bytes.to_vec(),
        document_digest: digest_bytes(bytes)?,
    })
}
