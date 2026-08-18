//! Exact, non-executable Wave 6 research-proposal fixture contract.

use std::collections::BTreeSet;

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use serde::{Deserialize, Serialize};

use crate::{RegistryError, Result, SemanticCeilingV1, canonical::decode_canonical, digest_bytes};

/// Registered N02 proposal kind.
pub const RESEARCH_PROPOSAL_KIND: &str = "research_proposal_fixture";
/// Registered N02 proposal schema.
pub const RESEARCH_PROPOSAL_SCHEMA: &str = "joshi.analysis.wave6-research-desk/v1";

const AUTHORITY: &str = "read_only_proposal_only_no_query_no_glass_no_action_no_claim_promotion";
const CLAIM_SCOPE: &str = "research_design_proposal_not_result_or_live_decision";
const MAX_PPM: u64 = 1_000_000;

/// Evidence role admitted by the pure Python desk contract.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResearchArtifactRoleV1 {
    /// Design-time evidence.
    Design,
    /// Outcome evidence, structurally refused from a locked hypothesis.
    Outcome,
}

/// Coverage state admitted by the general descriptor grammar.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResearchCoverageStatusV1 {
    Complete,
    Partial,
    Gap,
    Stale,
    Unsupported,
}

/// Proposal family admitted by the research desk.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResearchProposalKindV1 {
    Estimand,
    ControlSet,
    FeatureDecomposition,
    Counterexample,
    Falsifier,
    ExperimentManifest,
}

/// One point-in-time artifact descriptor; never a query handle.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchArtifactDescriptorV1 {
    pub artifact_id: StableString,
    pub as_of: UtcTimestamp,
    pub available_at: UtcTimestamp,
    pub commit_seq: WireU64,
    pub coverage_ppm: u64,
    pub coverage_status: ResearchCoverageStatusV1,
    pub gap_ids: Vec<StableString>,
    pub provenance_digest: ValueDigest,
    pub role: ResearchArtifactRoleV1,
    pub topology_id: StableString,
    pub topology_version_id: StableString,
    pub unit: StableString,
}

/// Frozen local policy carried in full by a proposal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchDeskPolicyV1 {
    pub allowed_gap_ids: Vec<StableString>,
    pub information_cutoff: UtcTimestamp,
    pub max_artifacts: u64,
    pub max_experiment_units: u64,
    pub max_experiments: u64,
    pub max_total_experiment_units: u64,
    pub minimum_coverage_ppm: u64,
    pub policy_id: StableString,
    pub required_topology_id: StableString,
    pub required_topology_version_id: StableString,
    pub required_unit: StableString,
}

/// Exact estimand declaration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchEstimandV1 {
    pub denominator: StableString,
    pub estimand_id: StableString,
    pub numerator: StableString,
    pub outcome_name: StableString,
    pub unit: StableString,
}

/// One predeclared control.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchControlV1 {
    pub control_id: StableString,
    pub measurement: StableString,
    pub rationale: StableString,
}

/// One decomposed feature.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchFeatureV1 {
    pub definition: StableString,
    pub feature_id: StableString,
    pub unit: StableString,
}

/// One explicit falsifier.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchFalsifierV1 {
    pub condition: StableString,
    pub failure_interpretation: StableString,
    pub falsifier_id: StableString,
}

/// One declarative, zero-query experiment manifest.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchExperimentV1 {
    pub artifact_ids: Vec<StableString>,
    pub executable: bool,
    pub experiment_id: StableString,
    pub purpose: StableString,
    pub query_count: u64,
    pub resource_units: u64,
}

/// Frozen proposal specification.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchProposalSpecV1 {
    pub artifact_ids: Vec<StableString>,
    pub controls: Vec<ResearchControlV1>,
    pub counterexamples: Vec<StableString>,
    pub estimand: ResearchEstimandV1,
    pub experiments: Vec<ResearchExperimentV1>,
    pub falsifiers: Vec<ResearchFalsifierV1>,
    pub features: Vec<ResearchFeatureV1>,
    pub hypothesis: StableString,
    pub kind: ResearchProposalKindV1,
    pub title: StableString,
}

/// Exact material sealed by `commitment_digest`.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchCommitmentV1 {
    pub artifact_descriptors: Vec<ResearchArtifactDescriptorV1>,
    pub authority: StableString,
    pub claim_scope: StableString,
    pub evidence_closure_digest: ValueDigest,
    pub hypothesis_locked_at: UtcTimestamp,
    pub policy: ResearchDeskPolicyV1,
    pub policy_digest: ValueDigest,
    pub schema_id: StableString,
    pub specification: ResearchProposalSpecV1,
}

/// Exact checked Python proposal wire contract.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchProposalV1 {
    pub artifact_descriptors: Vec<ResearchArtifactDescriptorV1>,
    pub authority: StableString,
    pub claim_scope: StableString,
    pub commitment: ResearchCommitmentV1,
    pub commitment_digest: ValueDigest,
    pub created_at: UtcTimestamp,
    pub evidence_closure_digest: ValueDigest,
    pub hypothesis_locked_at: UtcTimestamp,
    pub policy: ResearchDeskPolicyV1,
    pub policy_digest: ValueDigest,
    pub policy_id: StableString,
    pub proposal_digest: ValueDigest,
    pub proposal_id: StableString,
    pub schema_id: StableString,
    pub specification: ResearchProposalSpecV1,
}

/// Strictly decoded proposal with no store, query, result, or human authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedResearchProposal {
    value: ResearchProposalV1,
    exact_bytes: Vec<u8>,
    content_digest: ValueDigest,
}

impl ValidatedResearchProposal {
    #[must_use]
    pub const fn value(&self) -> &ResearchProposalV1 {
        &self.value
    }

    #[must_use]
    pub fn exact_bytes(&self) -> &[u8] {
        &self.exact_bytes
    }

    #[must_use]
    pub const fn content_digest(&self) -> &ValueDigest {
        &self.content_digest
    }

    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

/// Strictly parses one exact, non-executable research proposal.
///
/// # Errors
///
/// Refuses noncanonical/unknown fields, future or outcome evidence, incomplete descriptor closure,
/// executable/query manifests, budget widening, duplicate identities, or any digest mismatch.
pub fn parse_research_proposal_exact(bytes: &[u8]) -> Result<ValidatedResearchProposal> {
    let value: ResearchProposalV1 = decode_canonical(bytes)?;
    validate_proposal(&value)?;
    Ok(ValidatedResearchProposal {
        value,
        exact_bytes: bytes.to_vec(),
        content_digest: digest_bytes(bytes)?,
    })
}

#[derive(Serialize)]
struct EvidenceDigestMaterial<'a> {
    artifact_descriptors: &'a [ResearchArtifactDescriptorV1],
    schema_id: &'static str,
}

#[derive(Serialize)]
struct PolicyDigestMaterial<'a> {
    allowed_gap_ids: &'a [StableString],
    information_cutoff: UtcTimestamp,
    max_artifacts: u64,
    max_experiment_units: u64,
    max_experiments: u64,
    max_total_experiment_units: u64,
    minimum_coverage_ppm: u64,
    policy_id: &'a StableString,
    required_topology_id: &'a StableString,
    required_topology_version_id: &'a StableString,
    required_unit: &'a StableString,
    schema_id: &'static str,
}

#[derive(Serialize)]
struct ProposalContentMaterial<'a> {
    commitment: &'a ResearchCommitmentV1,
    commitment_digest: &'a ValueDigest,
    created_at: UtcTimestamp,
    schema_id: &'static str,
}

fn validate_proposal(value: &ResearchProposalV1) -> Result<()> {
    if value.authority.as_str() != AUTHORITY
        || value.claim_scope.as_str() != CLAIM_SCOPE
        || value.schema_id.as_str() != RESEARCH_PROPOSAL_SCHEMA
        || value.commitment.authority.as_str() != AUTHORITY
        || value.commitment.claim_scope.as_str() != CLAIM_SCOPE
        || value.commitment.schema_id.as_str() != RESEARCH_PROPOSAL_SCHEMA
    {
        return Err(RegistryError::Research("authority, claim scope, or schema"));
    }
    if value.created_at < value.hypothesis_locked_at {
        return Err(RegistryError::Research("proposal chronology"));
    }
    validate_policy(&value.policy)?;
    validate_specification(&value.specification)?;
    if value.policy_id != value.policy.policy_id
        || value.artifact_descriptors != value.commitment.artifact_descriptors
        || value.authority != value.commitment.authority
        || value.claim_scope != value.commitment.claim_scope
        || value.evidence_closure_digest != value.commitment.evidence_closure_digest
        || value.hypothesis_locked_at != value.commitment.hypothesis_locked_at
        || value.policy != value.commitment.policy
        || value.policy_digest != value.commitment.policy_digest
        || value.schema_id != value.commitment.schema_id
        || value.specification != value.commitment.specification
    {
        return Err(RegistryError::Research("duplicated commitment closure"));
    }
    validate_descriptors(value)?;
    validate_experiments(value)?;

    let policy_material = PolicyDigestMaterial {
        allowed_gap_ids: &value.policy.allowed_gap_ids,
        information_cutoff: value.policy.information_cutoff,
        max_artifacts: value.policy.max_artifacts,
        max_experiment_units: value.policy.max_experiment_units,
        max_experiments: value.policy.max_experiments,
        max_total_experiment_units: value.policy.max_total_experiment_units,
        minimum_coverage_ppm: value.policy.minimum_coverage_ppm,
        policy_id: &value.policy.policy_id,
        required_topology_id: &value.policy.required_topology_id,
        required_topology_version_id: &value.policy.required_topology_version_id,
        required_unit: &value.policy.required_unit,
        schema_id: RESEARCH_PROPOSAL_SCHEMA,
    };
    require_digest(&policy_material, &value.policy_digest, "policy digest")?;
    let evidence_material = EvidenceDigestMaterial {
        artifact_descriptors: &value.artifact_descriptors,
        schema_id: RESEARCH_PROPOSAL_SCHEMA,
    };
    require_digest(
        &evidence_material,
        &value.evidence_closure_digest,
        "evidence closure digest",
    )?;
    require_digest(
        &value.commitment,
        &value.commitment_digest,
        "commitment digest",
    )?;
    let proposal_material = ProposalContentMaterial {
        commitment: &value.commitment,
        commitment_digest: &value.commitment_digest,
        created_at: value.created_at,
        schema_id: RESEARCH_PROPOSAL_SCHEMA,
    };
    require_digest(
        &proposal_material,
        &value.proposal_digest,
        "proposal digest",
    )?;
    let raw = canonical_sha256(&proposal_material)?;
    let expected_id = format!("research-proposal-{}", &raw[..32]);
    if value.proposal_id.as_str() != expected_id {
        return Err(RegistryError::Research("proposal content identity"));
    }
    Ok(())
}

fn validate_policy(policy: &ResearchDeskPolicyV1) -> Result<()> {
    if policy.max_artifacts == 0
        || policy.max_experiments == 0
        || policy.max_experiment_units == 0
        || policy.max_total_experiment_units == 0
        || policy.max_experiment_units > policy.max_total_experiment_units
        || policy.minimum_coverage_ppm > MAX_PPM
        || !sorted_unique(&policy.allowed_gap_ids, false)
    {
        return Err(RegistryError::Research("desk policy"));
    }
    Ok(())
}

fn validate_specification(specification: &ResearchProposalSpecV1) -> Result<()> {
    if !sorted_unique(&specification.artifact_ids, true)
        || specification.controls.is_empty()
        || !sorted_by_key(&specification.controls, |row| &row.control_id)
        || !sorted_unique(&specification.counterexamples, false)
        || !sorted_by_key(&specification.experiments, |row| &row.experiment_id)
        || !sorted_by_key(&specification.falsifiers, |row| &row.falsifier_id)
        || !sorted_by_key(&specification.features, |row| &row.feature_id)
    {
        return Err(RegistryError::Research(
            "proposal specification collections",
        ));
    }
    Ok(())
}

fn validate_descriptors(value: &ResearchProposalV1) -> Result<()> {
    let descriptor_count = u64::try_from(value.artifact_descriptors.len())
        .map_err(|_| RegistryError::Research("artifact descriptor count"))?;
    if descriptor_count == 0
        || descriptor_count > value.policy.max_artifacts
        || !sorted_by_key(&value.artifact_descriptors, |row| &row.artifact_id)
        || value.specification.artifact_ids.len() != value.artifact_descriptors.len()
    {
        return Err(RegistryError::Research("artifact descriptor closure"));
    }
    for (descriptor, artifact_id) in value
        .artifact_descriptors
        .iter()
        .zip(&value.specification.artifact_ids)
    {
        if descriptor.artifact_id != *artifact_id
            || descriptor.as_of > descriptor.available_at
            || descriptor.available_at > value.policy.information_cutoff
            || descriptor.available_at > value.hypothesis_locked_at
            || descriptor.commit_seq.get() == 0
            || descriptor.coverage_status != ResearchCoverageStatusV1::Complete
            || descriptor.coverage_ppm < value.policy.minimum_coverage_ppm
            || descriptor.coverage_ppm > MAX_PPM
            || !sorted_unique(&descriptor.gap_ids, false)
            || descriptor
                .gap_ids
                .iter()
                .any(|gap| !value.policy.allowed_gap_ids.contains(gap))
            || descriptor.unit != value.policy.required_unit
            || descriptor.topology_id != value.policy.required_topology_id
            || descriptor.topology_version_id != value.policy.required_topology_version_id
            || descriptor.role == ResearchArtifactRoleV1::Outcome
        {
            return Err(RegistryError::Research("artifact descriptor admission"));
        }
    }
    if value.specification.estimand.unit != value.policy.required_unit {
        return Err(RegistryError::Research("estimand unit"));
    }
    Ok(())
}

fn validate_experiments(value: &ResearchProposalV1) -> Result<()> {
    let experiment_count = u64::try_from(value.specification.experiments.len())
        .map_err(|_| RegistryError::Research("experiment count"))?;
    if experiment_count > value.policy.max_experiments {
        return Err(RegistryError::Research("experiment count budget"));
    }
    let admitted: BTreeSet<&StableString> = value.specification.artifact_ids.iter().collect();
    let mut total_units = 0_u64;
    for experiment in &value.specification.experiments {
        total_units = total_units
            .checked_add(experiment.resource_units)
            .ok_or(RegistryError::Research("experiment resource overflow"))?;
        if experiment.executable
            || experiment.query_count != 0
            || experiment.resource_units == 0
            || experiment.resource_units > value.policy.max_experiment_units
            || !sorted_unique(&experiment.artifact_ids, true)
            || experiment
                .artifact_ids
                .iter()
                .any(|artifact| !admitted.contains(artifact))
        {
            return Err(RegistryError::Research(
                "experiment execution or budget boundary",
            ));
        }
    }
    if total_units > value.policy.max_total_experiment_units {
        return Err(RegistryError::Research("total experiment resource budget"));
    }
    Ok(())
}

fn sorted_unique(values: &[StableString], nonempty: bool) -> bool {
    (!nonempty || !values.is_empty())
        && values
            .windows(2)
            .all(|pair| pair[0].as_str() < pair[1].as_str())
}

fn sorted_by_key<T, F>(values: &[T], key: F) -> bool
where
    F: Fn(&T) -> &StableString,
{
    values
        .windows(2)
        .all(|pair| key(&pair[0]).as_str() < key(&pair[1]).as_str())
}

fn require_digest<T: Serialize>(
    material: &T,
    expected: &ValueDigest,
    field: &'static str,
) -> Result<()> {
    if digest_bytes(&serde_json::to_vec(material)?)? != *expected {
        return Err(RegistryError::Research(field));
    }
    Ok(())
}

fn canonical_sha256<T: Serialize>(material: &T) -> Result<String> {
    Ok(digest_bytes(&serde_json::to_vec(material)?)?
        .as_str()
        .strip_prefix("sha256:")
        .ok_or(RegistryError::Research("generated proposal digest"))?
        .to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::canonical_bytes;

    const FIXTURE: &[u8] = include_bytes!("../../../fixtures/wave6/research_proposal_v1.json");

    #[test]
    fn exact_python_proposal_cross_parses_without_execution_authority() {
        let parsed = parse_research_proposal_exact(FIXTURE).expect("research proposal");
        assert_eq!(
            parsed.content_digest().as_str(),
            "sha256:5da44fffda071866e79f80624ecece320884f69a598a582b4a5362c37d731503"
        );
        assert_eq!(
            parsed.value().proposal_digest.as_str(),
            "sha256:482af6e85fb9edae5a00eccf29af12b24319e5b0ca2cce81fda3aceb9632d5c4"
        );
        assert_eq!(parsed.value().artifact_descriptors.len(), 3);
        assert_eq!(parsed.value().specification.counterexamples.len(), 18);
        assert_eq!(parsed.value().specification.experiments.len(), 1);
        assert!(!parsed.value().specification.experiments[0].executable);
        assert_eq!(parsed.value().specification.experiments[0].query_count, 0);
        assert_eq!(
            parsed.semantic_ceiling(),
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
    }

    #[test]
    fn proposal_refuses_noncanonical_future_outcome_and_execution_changes() {
        let parsed = parse_research_proposal_exact(FIXTURE).expect("research proposal");

        let pretty = serde_json::to_vec_pretty(parsed.value()).expect("pretty proposal");
        assert!(parse_research_proposal_exact(&pretty).is_err());

        let mut future = parsed.value().clone();
        future.artifact_descriptors[0].available_at = future.created_at;
        future.commitment.artifact_descriptors[0].available_at = future.created_at;
        assert!(
            parse_research_proposal_exact(&canonical_bytes(&future).expect("future bytes"))
                .is_err()
        );

        let mut outcome = parsed.value().clone();
        outcome.artifact_descriptors[0].role = ResearchArtifactRoleV1::Outcome;
        outcome.commitment.artifact_descriptors[0].role = ResearchArtifactRoleV1::Outcome;
        assert!(
            parse_research_proposal_exact(&canonical_bytes(&outcome).expect("outcome bytes"))
                .is_err()
        );

        let mut executable = parsed.value().clone();
        executable.specification.experiments[0].executable = true;
        executable.commitment.specification.experiments[0].executable = true;
        assert!(
            parse_research_proposal_exact(&canonical_bytes(&executable).expect("executable bytes"))
                .is_err()
        );
    }

    #[test]
    fn duplicated_commitment_and_resource_substitution_refuse() {
        let parsed = parse_research_proposal_exact(FIXTURE).expect("research proposal");
        let mut changed = parsed.value().clone();
        changed.policy.max_total_experiment_units = 4;
        assert!(
            parse_research_proposal_exact(&canonical_bytes(&changed).expect("changed bytes"))
                .is_err()
        );

        let mut query = parsed.value().clone();
        query.specification.experiments[0].query_count = 1;
        query.commitment.specification.experiments[0].query_count = 1;
        assert!(
            parse_research_proposal_exact(&canonical_bytes(&query).expect("query bytes")).is_err()
        );
    }
}
