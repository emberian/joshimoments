//! Program-registration semantic validation.

use joshi_domain::{StableString, ValueDigest};
use std::cmp::Ordering;

use crate::{
    DeskOperationV1, FixtureMaturityV1, RegistryError, Result, SemanticCeilingV1,
    Wave6ProgramRegistrationV1, canonical_bytes, digest_bytes,
};

const REQUIRED_SOURCE_PROHIBITIONS: &[&str] = &[
    "authenticated_live_source",
    "paid_provider_query",
    "wallet_or_signing_material",
];
const REQUIRED_OUTPUT_PROHIBITIONS: &[&str] = &[
    "live_alert_or_ranking",
    "operator_visible_forecast",
    "production_market_release",
];
const REQUIRED_CLAIM_PROHIBITIONS: &[&str] = &[
    "causal_identification",
    "economic_profit_or_advantage",
    "hidden_identity_or_intent",
    "operational_or_product_maturity",
];
const REQUIRED_SIDE_EFFECT_PROHIBITIONS: &[&str] = &[
    "acquisition_or_hot_lease_mutation",
    "asset_reservation",
    "glass_or_presentation_mutation",
    "liquidity_installation",
    "transaction_construction_signing_or_submission",
];

pub(crate) fn validate_sha256_public(value: &ValueDigest, field: &'static str) -> Result<()> {
    let value = value.as_str();
    let Some(hex) = value.strip_prefix("sha256:") else {
        return Err(RegistryError::DigestFormat { field });
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(RegistryError::DigestFormat { field });
    }
    Ok(())
}

fn strictly_sorted_by<T>(values: &[T], compare: impl Fn(&T, &T) -> Ordering) -> bool {
    values
        .windows(2)
        .all(|pair| compare(&pair[0], &pair[1]).is_lt())
}

fn sorted_stable_strings(values: &[StableString], field: &'static str) -> Result<()> {
    if values.is_empty()
        || !strictly_sorted_by(values, |left, right| left.as_str().cmp(right.as_str()))
    {
        return Err(RegistryError::Collection(field));
    }
    Ok(())
}

fn require_members(values: &[StableString], required: &'static [&'static str]) -> Result<()> {
    for expected in required {
        if values
            .binary_search_by(|value| value.as_str().cmp(expected))
            .is_err()
        {
            return Err(RegistryError::MissingProhibition(expected));
        }
    }
    Ok(())
}

impl Wave6ProgramRegistrationV1 {
    /// Revalidates the fixture-only program registration and its self-declared digest.
    ///
    /// # Errors
    ///
    /// Refuses authority widening, unsorted or duplicate closure, invalid digests, unbounded
    /// provider/external budgets, missing prohibitions, or digest mismatch.
    pub fn validate(&self) -> Result<()> {
        if self.contract.as_str() != Self::contract_name()
            || self.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        {
            return Err(RegistryError::Authority);
        }

        validate_sha256_public(&self.source_tree_digest, "sourceTreeDigest")?;
        validate_sha256_public(&self.build_digest, "buildDigest")?;
        validate_sha256_public(&self.environment_digest, "environmentDigest")?;
        validate_sha256_public(&self.config_digest, "configDigest")?;
        validate_sha256_public(&self.registration_digest, "registrationDigest")?;

        if !strictly_sorted_by(&self.consumed_wave5_gates, |left, right| {
            left.gate.cmp(&right.gate)
        }) {
            return Err(RegistryError::Collection("consumedWave5Gates"));
        }
        for gate in &self.consumed_wave5_gates {
            validate_sha256_public(&gate.occurrence_digest, "occurrenceDigest")?;
            if gate.evidence_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly {
                return Err(RegistryError::Authority);
            }
        }

        if self.artifact_kinds.is_empty()
            || !strictly_sorted_by(&self.artifact_kinds, |left, right| {
                left.kind_id.as_str().cmp(right.kind_id.as_str())
            })
        {
            return Err(RegistryError::Collection("artifactKinds"));
        }
        for artifact in &self.artifact_kinds {
            validate_sha256_public(&artifact.schema_digest, "artifactKinds.schemaDigest")?;
            if artifact.max_fixture_maturity > FixtureMaturityV1::FixtureRoundtrip
                || artifact.permitted_claim == artifact.prohibited_inference
            {
                return Err(RegistryError::Artifact("artifact kind claim boundary"));
            }
        }

        if self.local_symbols.is_empty()
            || !strictly_sorted_by(&self.local_symbols, |left, right| {
                left.symbol_id.as_str().cmp(right.symbol_id.as_str())
            })
        {
            return Err(RegistryError::Collection("localSymbols"));
        }

        if self.data_policy.privacy_class.as_str() != "fixture_public_no_personal_data"
            || self.data_policy.retention_class.as_str() != "checked_in_fixture_only"
            || self.data_policy.deletion_class.as_str() != "repository_history_only"
            || self.data_policy.export_class.as_str() != "fixture_artifact_only"
        {
            return Err(RegistryError::Policy("data class"));
        }
        if self.budgets.provider_units.get() != 0
            || self.budgets.external_mutation_units.get() != 0
            || self.budgets.max_artifacts.get() == 0
        {
            return Err(RegistryError::Policy("budget"));
        }

        if self.permitted_desk_operations.is_empty()
            || !strictly_sorted_by(&self.permitted_desk_operations, Ord::cmp)
            || !self
                .permitted_desk_operations
                .contains(&DeskOperationV1::EmitRefusal)
        {
            return Err(RegistryError::Collection("permittedDeskOperations"));
        }

        sorted_stable_strings(&self.prohibited_sources, "prohibitedSources")?;
        sorted_stable_strings(&self.prohibited_outputs, "prohibitedOutputs")?;
        sorted_stable_strings(&self.prohibited_claims, "prohibitedClaims")?;
        sorted_stable_strings(&self.prohibited_side_effects, "prohibitedSideEffects")?;
        require_members(&self.prohibited_sources, REQUIRED_SOURCE_PROHIBITIONS)?;
        require_members(&self.prohibited_outputs, REQUIRED_OUTPUT_PROHIBITIONS)?;
        require_members(&self.prohibited_claims, REQUIRED_CLAIM_PROHIBITIONS)?;
        require_members(
            &self.prohibited_side_effects,
            REQUIRED_SIDE_EFFECT_PROHIBITIONS,
        )?;

        let computed = digest_bytes(&canonical_bytes(&self.digest_material())?)?;
        if computed != self.registration_digest {
            return Err(RegistryError::DigestMismatch);
        }
        Ok(())
    }
}
