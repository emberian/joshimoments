//! Exact fixture-only wire contracts for supported N01 evaluation artifacts.

use joshi_domain::{StableString, ValueDigest};
use serde::{Deserialize, Serialize};

use crate::{RegistryError, Result, SemanticCeilingV1, canonical::decode_canonical, digest_bytes};

/// Registered generic known-truth evaluation kind.
pub const KNOWN_TRUTH_EVALUATION_KIND: &str = "known_truth_evaluation_fixture";
/// Registered generic known-truth evaluation schema.
pub const KNOWN_TRUTH_EVALUATION_SCHEMA: &str = "joshi.analysis.wave6-known-truth/v1";
/// Registered protocol known-truth evaluation kind.
pub const PROTOCOL_EVALUATION_KIND: &str = "protocol_known_truth_evaluation_fixture";
/// Registered protocol known-truth evaluation schema.
pub const PROTOCOL_EVALUATION_SCHEMA: &str = "joshi.analysis.wave6-protocol-known-truth/v1";
/// Registered structural known-truth evaluation kind.
pub const STRUCTURAL_EVALUATION_KIND: &str = "structural_known_truth_evaluation_fixture";
/// Registered structural known-truth evaluation schema.
pub const STRUCTURAL_EVALUATION_SCHEMA: &str = "joshi.analysis.wave6-structural-known-truth/v1";
/// Generated domain-counterexample evaluation kind. N00 does not register this kind yet.
pub const DOMAIN_EVALUATION_KIND: &str = "domain_known_truth_evaluation_fixture";
/// Generated domain-counterexample evaluation schema. Parsing does not register or persist it.
pub const DOMAIN_EVALUATION_SCHEMA: &str = "joshi.analysis.wave6-domain-known-truth/v1";

const GENERIC_AUTHORITY: &str = "fixture_only_no_market_causal_policy_or_economic_claim";
const PROTOCOL_AUTHORITY: &str = "fixture_protocol_arithmetic_only_no_market_or_economic_claim";
const STRUCTURAL_AUTHORITY: &str =
    "fixture_structural_transition_only_no_identity_market_causal_or_economic_claim";
const DOMAIN_AUTHORITY: &str =
    "fixture_domain_counterexamples_only_no_market_identity_causal_policy_or_economic_claim";
const PUMP_FIXTURE_DIGEST: &str =
    "sha256:47837451236ec38eaffa78521d4fc6aa8ffb44d69136a19a0b532d1ad20c29df";
const DLMM_FIXTURE_DIGEST: &str =
    "sha256:a84a22100cfa790aaf37b649bd7db359b3f21afd2a82d2c0074a9cf3cc11e1c8";
const STRUCTURAL_FIXTURE_DIGEST: &str =
    "sha256:806bf5668a0de0f113677f5aad6947074cb463aa1dc9776794e22a2b491be154";

/// Complete generic known-truth evaluation output.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnownTruthEvaluationV1 {
    /// Fixed fixture-only authority.
    pub authority: StableString,
    /// Candidate implementation identity.
    pub candidate_id: StableString,
    /// Self-digest over the exact evaluation material.
    pub evaluation_digest: ValueDigest,
    /// Exact sorted passing case denominator.
    pub passed_case_ids: Vec<StableString>,
    /// One result digest in matching case order.
    pub result_digests: Vec<ValueDigest>,
    /// Exact suite digest.
    pub suite_digest: ValueDigest,
    /// Exact suite identity.
    pub suite_id: StableString,
}

/// Complete Pump/PumpSwap/DLMM known-truth evaluation output.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProtocolEvaluationV1 {
    /// Fixed fixture-only authority.
    pub authority: StableString,
    /// Candidate implementation identity.
    pub candidate_id: StableString,
    /// Frozen DLMM fixture digest.
    pub dlmm_fixture_digest: ValueDigest,
    /// Self-digest over the exact evaluation material.
    pub evaluation_digest: ValueDigest,
    /// Exact sorted passing case denominator.
    pub passed_case_ids: Vec<StableString>,
    /// Frozen Pump/PumpSwap fixture digest.
    pub pump_fixture_digest: ValueDigest,
    /// One result digest in matching case order.
    pub result_digests: Vec<ValueDigest>,
    /// Exact suite digest.
    pub suite_digest: ValueDigest,
    /// Exact suite identity.
    pub suite_id: StableString,
}

/// Complete migration/order/identity known-truth evaluation output.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StructuralEvaluationV1 {
    /// Fixed fixture-only authority.
    pub authority: StableString,
    /// Candidate implementation identity.
    pub candidate_id: StableString,
    /// Self-digest over the exact evaluation material.
    pub evaluation_digest: ValueDigest,
    /// Frozen structural source-fixture digest.
    pub fixture_digest: ValueDigest,
    /// Exact sorted passing case denominator.
    pub passed_case_ids: Vec<StableString>,
    /// One result digest in matching case order.
    pub result_digests: Vec<ValueDigest>,
    /// Exact suite digest.
    pub suite_digest: ValueDigest,
    /// Exact suite identity.
    pub suite_id: StableString,
}

/// Complete generated domain-counterexample evaluation output.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DomainEvaluationV1 {
    /// Fixed fixture-only authority.
    pub authority: StableString,
    /// Candidate implementation identity.
    pub candidate_id: StableString,
    /// Self-digest over the exact evaluation material.
    pub evaluation_digest: ValueDigest,
    /// Exact sorted passing case denominator.
    pub passed_case_ids: Vec<StableString>,
    /// One result digest in matching case order.
    pub result_digests: Vec<ValueDigest>,
    /// Exact suite digest.
    pub suite_digest: ValueDigest,
    /// Exact suite identity.
    pub suite_id: StableString,
}

/// One supported evaluation artifact family.
///
/// Parsing a value does not prove that its kind is present in an N00 registration or store.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FixtureEvaluationArtifactV1 {
    /// Generic signed-flow known-truth evaluation.
    KnownTruth(KnownTruthEvaluationV1),
    /// Pump/PumpSwap/DLMM exact arithmetic evaluation.
    Protocol(ProtocolEvaluationV1),
    /// Migration/order/identity structural evaluation.
    Structural(StructuralEvaluationV1),
    /// Generated venue/burst/mechanism/operator/episode/household counterexamples.
    Domain(DomainEvaluationV1),
}

impl FixtureEvaluationArtifactV1 {
    /// Exact semantic self-digest carried by the artifact.
    #[must_use]
    pub const fn evaluation_digest(&self) -> &ValueDigest {
        match self {
            Self::KnownTruth(value) => &value.evaluation_digest,
            Self::Protocol(value) => &value.evaluation_digest,
            Self::Structural(value) => &value.evaluation_digest,
            Self::Domain(value) => &value.evaluation_digest,
        }
    }

    /// Exact result denominator size.
    #[must_use]
    pub fn result_count(&self) -> usize {
        match self {
            Self::KnownTruth(value) => value.result_digests.len(),
            Self::Protocol(value) => value.result_digests.len(),
            Self::Structural(value) => value.result_digests.len(),
            Self::Domain(value) => value.result_digests.len(),
        }
    }
}

/// Strictly decoded evaluation bytes with no durable or empirical authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedEvaluationArtifact {
    value: FixtureEvaluationArtifactV1,
    exact_bytes: Vec<u8>,
    content_digest: ValueDigest,
}

impl ValidatedEvaluationArtifact {
    /// Exact typed fixture value.
    #[must_use]
    pub const fn value(&self) -> &FixtureEvaluationArtifactV1 {
        &self.value
    }

    /// Exact canonical artifact bytes including one trailing newline.
    #[must_use]
    pub fn exact_bytes(&self) -> &[u8] {
        &self.exact_bytes
    }

    /// Physical digest of the complete artifact bytes.
    #[must_use]
    pub const fn content_digest(&self) -> &ValueDigest {
        &self.content_digest
    }

    /// Exact semantic evaluation self-digest.
    #[must_use]
    pub const fn evaluation_digest(&self) -> &ValueDigest {
        self.value.evaluation_digest()
    }

    /// Public parsing cannot raise the fixture-only ceiling.
    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

/// Parses one registered exact evaluation artifact.
///
/// # Errors
///
/// Refuses an unsupported kind/schema mapping, unknown or noncanonical fields, changed fixture
/// inputs, incomplete denominators, changed authority, or a mismatched semantic self-digest.
pub fn parse_evaluation_artifact_exact(
    kind_id: &StableString,
    schema_id: &StableString,
    bytes: &[u8],
) -> Result<ValidatedEvaluationArtifact> {
    let value = match (kind_id.as_str(), schema_id.as_str()) {
        (KNOWN_TRUTH_EVALUATION_KIND, KNOWN_TRUTH_EVALUATION_SCHEMA) => {
            let value: KnownTruthEvaluationV1 = decode_canonical(bytes)?;
            validate_known_truth(&value)?;
            FixtureEvaluationArtifactV1::KnownTruth(value)
        }
        (PROTOCOL_EVALUATION_KIND, PROTOCOL_EVALUATION_SCHEMA) => {
            let value: ProtocolEvaluationV1 = decode_canonical(bytes)?;
            validate_protocol(&value)?;
            FixtureEvaluationArtifactV1::Protocol(value)
        }
        (STRUCTURAL_EVALUATION_KIND, STRUCTURAL_EVALUATION_SCHEMA) => {
            let value: StructuralEvaluationV1 = decode_canonical(bytes)?;
            validate_structural(&value)?;
            FixtureEvaluationArtifactV1::Structural(value)
        }
        (DOMAIN_EVALUATION_KIND, DOMAIN_EVALUATION_SCHEMA) => {
            let value: DomainEvaluationV1 = decode_canonical(bytes)?;
            validate_domain(&value)?;
            FixtureEvaluationArtifactV1::Domain(value)
        }
        _ => {
            return Err(RegistryError::Evaluation(
                "unsupported registered evaluation kind/schema mapping",
            ));
        }
    };
    Ok(ValidatedEvaluationArtifact {
        value,
        exact_bytes: bytes.to_vec(),
        content_digest: digest_bytes(bytes)?,
    })
}

#[derive(Serialize)]
struct KnownTruthDigestMaterial<'a> {
    authority: &'a StableString,
    candidate_id: &'a StableString,
    passed_case_ids: &'a [StableString],
    result_digests: &'a [ValueDigest],
    schema_id: &'static str,
    suite_digest: &'a ValueDigest,
    suite_id: &'a StableString,
}

#[derive(Serialize)]
struct ProtocolDigestMaterial<'a> {
    authority: &'a StableString,
    candidate_id: &'a StableString,
    dlmm_fixture_digest: &'a ValueDigest,
    passed_case_ids: &'a [StableString],
    pump_fixture_digest: &'a ValueDigest,
    result_digests: &'a [ValueDigest],
    schema_id: &'static str,
    suite_digest: &'a ValueDigest,
    suite_id: &'a StableString,
}

#[derive(Serialize)]
struct StructuralDigestMaterial<'a> {
    authority: &'a StableString,
    candidate_id: &'a StableString,
    fixture_digest: &'a ValueDigest,
    passed_case_ids: &'a [StableString],
    result_digests: &'a [ValueDigest],
    schema_id: &'static str,
    suite_digest: &'a ValueDigest,
    suite_id: &'a StableString,
}

#[derive(Serialize)]
struct DomainDigestMaterial<'a> {
    authority: &'a StableString,
    candidate_id: &'a StableString,
    passed_case_ids: &'a [StableString],
    result_digests: &'a [ValueDigest],
    schema_id: &'static str,
    suite_digest: &'a ValueDigest,
    suite_id: &'a StableString,
}

fn validate_known_truth(value: &KnownTruthEvaluationV1) -> Result<()> {
    validate_common(
        &value.authority,
        GENERIC_AUTHORITY,
        &value.passed_case_ids,
        &value.result_digests,
        8,
    )?;
    let material = KnownTruthDigestMaterial {
        authority: &value.authority,
        candidate_id: &value.candidate_id,
        passed_case_ids: &value.passed_case_ids,
        result_digests: &value.result_digests,
        schema_id: KNOWN_TRUTH_EVALUATION_SCHEMA,
        suite_digest: &value.suite_digest,
        suite_id: &value.suite_id,
    };
    validate_self_digest(&material, &value.evaluation_digest)
}

fn validate_protocol(value: &ProtocolEvaluationV1) -> Result<()> {
    validate_common(
        &value.authority,
        PROTOCOL_AUTHORITY,
        &value.passed_case_ids,
        &value.result_digests,
        7,
    )?;
    if value.pump_fixture_digest.as_str() != PUMP_FIXTURE_DIGEST
        || value.dlmm_fixture_digest.as_str() != DLMM_FIXTURE_DIGEST
    {
        return Err(RegistryError::Evaluation("protocol fixture digest"));
    }
    let material = ProtocolDigestMaterial {
        authority: &value.authority,
        candidate_id: &value.candidate_id,
        dlmm_fixture_digest: &value.dlmm_fixture_digest,
        passed_case_ids: &value.passed_case_ids,
        pump_fixture_digest: &value.pump_fixture_digest,
        result_digests: &value.result_digests,
        schema_id: PROTOCOL_EVALUATION_SCHEMA,
        suite_digest: &value.suite_digest,
        suite_id: &value.suite_id,
    };
    validate_self_digest(&material, &value.evaluation_digest)
}

fn validate_structural(value: &StructuralEvaluationV1) -> Result<()> {
    validate_common(
        &value.authority,
        STRUCTURAL_AUTHORITY,
        &value.passed_case_ids,
        &value.result_digests,
        3,
    )?;
    if value.fixture_digest.as_str() != STRUCTURAL_FIXTURE_DIGEST {
        return Err(RegistryError::Evaluation("structural fixture digest"));
    }
    let material = StructuralDigestMaterial {
        authority: &value.authority,
        candidate_id: &value.candidate_id,
        fixture_digest: &value.fixture_digest,
        passed_case_ids: &value.passed_case_ids,
        result_digests: &value.result_digests,
        schema_id: STRUCTURAL_EVALUATION_SCHEMA,
        suite_digest: &value.suite_digest,
        suite_id: &value.suite_id,
    };
    validate_self_digest(&material, &value.evaluation_digest)
}

fn validate_domain(value: &DomainEvaluationV1) -> Result<()> {
    validate_common(
        &value.authority,
        DOMAIN_AUTHORITY,
        &value.passed_case_ids,
        &value.result_digests,
        7,
    )?;
    let material = DomainDigestMaterial {
        authority: &value.authority,
        candidate_id: &value.candidate_id,
        passed_case_ids: &value.passed_case_ids,
        result_digests: &value.result_digests,
        schema_id: DOMAIN_EVALUATION_SCHEMA,
        suite_digest: &value.suite_digest,
        suite_id: &value.suite_id,
    };
    validate_self_digest(&material, &value.evaluation_digest)
}

fn validate_common(
    authority: &StableString,
    expected_authority: &str,
    passed_case_ids: &[StableString],
    result_digests: &[ValueDigest],
    expected_count: usize,
) -> Result<()> {
    if authority.as_str() != expected_authority {
        return Err(RegistryError::Evaluation("authority"));
    }
    if passed_case_ids.len() != expected_count
        || result_digests.len() != expected_count
        || passed_case_ids
            .windows(2)
            .any(|pair| pair[0].as_str() >= pair[1].as_str())
    {
        return Err(RegistryError::Evaluation("exact result denominator"));
    }
    Ok(())
}

fn validate_self_digest<T: Serialize>(material: &T, alleged: &ValueDigest) -> Result<()> {
    let bytes = serde_json::to_vec(material)?;
    if digest_bytes(&bytes)? != *alleged {
        return Err(RegistryError::Evaluation("semantic self-digest"));
    }
    Ok(())
}
