//! Strict Wave 6 program-registration wire types.

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use serde::{Deserialize, Serialize};

use crate::PROGRAM_REGISTRATION_CONTRACT;

/// Fixed read-only authority available to a Wave 6 fixture registration.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProgramAuthorityV1 {
    /// Read/record/replay/propose/hypothetical-shadow only; never economic authority.
    ReadRecordReplayProposeShadowOnly,
}

/// Public maturity ceiling of every value produced by this crate.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SemanticCeilingV1 {
    /// Caller-fed fixture semantics with no durable or operational provenance.
    UnverifiedSemanticFixtureOnly,
}

/// Scientific/authority rung named by an artifact kind.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClaimRungV1 {
    /// Finalized atomic settlement or declared accounting boundary.
    H0Settlement,
    /// Exact profiled deterministic transition or refusal.
    H1ProtocolKinematics,
    /// Observation-policy-scoped description.
    H2Descriptive,
    /// Calibrated conditional estimate, never causality.
    H3Fitted,
    /// Compatible equivalence class, never hidden identity.
    H4LatentAbductive,
    /// Read-only hypothetical proposal.
    H5Policy,
}

/// Highest maturity a public fixture registration can name.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FixtureMaturityV1 {
    /// Schema and intrinsic semantic validation only.
    ContractOnly,
    /// Deterministic fixture bytes can be reproduced and revalidated.
    FixtureRoundtrip,
}

/// Named Wave 5 external gate. A public reference remains unverified.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Wave5GateV1 {
    /// Complete fake-source root fault witness.
    G0RootFaultWitness,
    /// Bounded nonfixture operational witness.
    G1OperationalWitness,
    /// Exact durable scene/memory chain.
    G2MemoryWitness,
    /// Ordinary operator-use/accessibility witness.
    G3OperatorUseWitness,
    /// Durable claim occurrence and adjudication spine.
    G4aDurableClaimSpineWitness,
    /// Repeated chronological claim support.
    G4bDurableClaimSupportWitness,
    /// Profile/kind-specific mechanics witness.
    G5MechanicsWitness,
    /// Consolidated inventory and liquidation witness.
    G6PortfolioLiquidationWitness,
}

/// Caller-declared reference to an external gate.
///
/// Presence here never proves the gate. The fixture registry has no store resolver and its public
/// semantic ceiling cannot rise when this vector is nonempty.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5GateRefV1 {
    /// Gate family.
    pub gate: Wave5GateV1,
    /// Alleged immutable occurrence identity.
    pub occurrence_id: StableString,
    /// Alleged exact occurrence digest.
    pub occurrence_digest: ValueDigest,
    /// Fixed marker preventing a caller reference from masquerading as store resolution.
    pub evidence_ceiling: SemanticCeilingV1,
}

/// One allowed Wave 6 artifact schema and its maximum fixture claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactKindRegistrationV1 {
    /// Stable artifact family identity.
    pub kind_id: StableString,
    /// Versioned exact schema contract.
    pub schema_id: StableString,
    /// Digest of the frozen schema bytes.
    pub schema_digest: ValueDigest,
    /// Highest scientific rung the kind could express after its independent gates.
    pub claim_rung: ClaimRungV1,
    /// Public pre-gate maturity ceiling.
    pub max_fixture_maturity: FixtureMaturityV1,
    /// Explicit permissible claim wording family.
    pub permitted_claim: StableString,
    /// Explicit forbidden inference for this kind.
    pub prohibited_inference: StableString,
}

/// One symbol in the frozen local semantic table.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LocalSymbolV1 {
    /// Stable symbol identity.
    pub symbol_id: StableString,
    /// Human-readable exact meaning.
    pub definition: StableString,
    /// Optional exact unit; absence is explicit for nonnumeric objects.
    pub unit: Option<StableString>,
    /// Optional clock domain; absence is explicit for timeless objects.
    pub clock: Option<StableString>,
}

/// Data-handling boundary of the pre-gate contract.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DataPolicyV1 {
    /// Must remain `fixture_public_no_personal_data` in V1.
    pub privacy_class: StableString,
    /// Must remain `checked_in_fixture_only` in V1.
    pub retention_class: StableString,
    /// Must remain `repository_history_only` in V1.
    pub deletion_class: StableString,
    /// Must remain `fixture_artifact_only` in V1.
    pub export_class: StableString,
}

/// Bounded abstract resources. Provider/external-mutation budgets are permanently zero in V1.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProgramBudgetsV1 {
    /// Local deterministic compute units.
    pub compute_units: WireU64,
    /// Local fixture read units.
    pub read_units: WireU64,
    /// Optional human-attention units; zero is permitted.
    pub attention_units: WireU64,
    /// Provider/network units; must be zero.
    pub provider_units: WireU64,
    /// External mutation units; must be zero.
    pub external_mutation_units: WireU64,
    /// Positive local stop limit.
    pub max_artifacts: WireU64,
}

/// Operations a fixture-only research desk may propose locally.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeskOperationV1 {
    /// Validate exact checked-in fixture descriptors.
    InspectFixtureDescriptor,
    /// Compare deterministic fixture artifacts.
    CompareFixtureArtifacts,
    /// Draft a non-executable protocol for human review.
    DraftNonExecutableProtocol,
    /// Emit a refusal with exact failed predicates.
    EmitRefusal,
}

/// Exact Wave 6 fixture program registration.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave6ProgramRegistrationV1 {
    /// Exact contract discriminator.
    pub contract: StableString,
    /// One immutable program occurrence identity.
    pub program_id: StableString,
    /// Campaign/program family identity.
    pub program_family_id: StableString,
    /// Semantic version of this frozen registration.
    pub semantic_version: StableString,
    /// Exact source-tree digest.
    pub source_tree_digest: ValueDigest,
    /// Exact build digest.
    pub build_digest: ValueDigest,
    /// Exact environment digest.
    pub environment_digest: ValueDigest,
    /// Exact configuration digest.
    pub config_digest: ValueDigest,
    /// Fixed read-only authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed public semantic ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Caller-declared external-gate references; never store authority here.
    pub consumed_wave5_gates: Vec<Wave5GateRefV1>,
    /// Registered artifact kinds, strictly sorted by kind identity.
    pub artifact_kinds: Vec<ArtifactKindRegistrationV1>,
    /// Frozen local symbols, strictly sorted by symbol identity.
    pub local_symbols: Vec<LocalSymbolV1>,
    /// Fixture-only privacy/retention/deletion/export boundary.
    pub data_policy: DataPolicyV1,
    /// Bounded local resources.
    pub budgets: ProgramBudgetsV1,
    /// Strictly sorted, duplicate-free desk operations.
    pub permitted_desk_operations: Vec<DeskOperationV1>,
    /// Strictly sorted prohibited source families.
    pub prohibited_sources: Vec<StableString>,
    /// Strictly sorted prohibited output families.
    pub prohibited_outputs: Vec<StableString>,
    /// Strictly sorted prohibited claim families.
    pub prohibited_claims: Vec<StableString>,
    /// Strictly sorted prohibited side effects.
    pub prohibited_side_effects: Vec<StableString>,
    /// Fixture clock; not a store commit time.
    pub registered_at: UtcTimestamp,
    /// Digest of [`ProgramRegistrationDigestMaterialV1`].
    pub registration_digest: ValueDigest,
}

/// Digest material for [`Wave6ProgramRegistrationV1`], excluding its self-declared digest.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgramRegistrationDigestMaterialV1<'a> {
    /// Contract.
    pub contract: &'a StableString,
    /// Program occurrence identity.
    pub program_id: &'a StableString,
    /// Program family.
    pub program_family_id: &'a StableString,
    /// Semantic version.
    pub semantic_version: &'a StableString,
    /// Source tree digest.
    pub source_tree_digest: &'a ValueDigest,
    /// Build digest.
    pub build_digest: &'a ValueDigest,
    /// Environment digest.
    pub environment_digest: &'a ValueDigest,
    /// Configuration digest.
    pub config_digest: &'a ValueDigest,
    /// Authority.
    pub authority: ProgramAuthorityV1,
    /// Semantic ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
    /// Gate references.
    pub consumed_wave5_gates: &'a [Wave5GateRefV1],
    /// Artifact kinds.
    pub artifact_kinds: &'a [ArtifactKindRegistrationV1],
    /// Symbols.
    pub local_symbols: &'a [LocalSymbolV1],
    /// Data policy.
    pub data_policy: &'a DataPolicyV1,
    /// Budgets.
    pub budgets: &'a ProgramBudgetsV1,
    /// Desk operations.
    pub permitted_desk_operations: &'a [DeskOperationV1],
    /// Prohibited sources.
    pub prohibited_sources: &'a [StableString],
    /// Prohibited outputs.
    pub prohibited_outputs: &'a [StableString],
    /// Prohibited claims.
    pub prohibited_claims: &'a [StableString],
    /// Prohibited effects.
    pub prohibited_side_effects: &'a [StableString],
    /// Fixture clock.
    pub registered_at: UtcTimestamp,
}

impl Wave6ProgramRegistrationV1 {
    /// Returns the exact material covered by `registration_digest`.
    #[must_use]
    pub fn digest_material(&self) -> ProgramRegistrationDigestMaterialV1<'_> {
        ProgramRegistrationDigestMaterialV1 {
            contract: &self.contract,
            program_id: &self.program_id,
            program_family_id: &self.program_family_id,
            semantic_version: &self.semantic_version,
            source_tree_digest: &self.source_tree_digest,
            build_digest: &self.build_digest,
            environment_digest: &self.environment_digest,
            config_digest: &self.config_digest,
            authority: self.authority,
            semantic_ceiling: self.semantic_ceiling,
            consumed_wave5_gates: &self.consumed_wave5_gates,
            artifact_kinds: &self.artifact_kinds,
            local_symbols: &self.local_symbols,
            data_policy: &self.data_policy,
            budgets: &self.budgets,
            permitted_desk_operations: &self.permitted_desk_operations,
            prohibited_sources: &self.prohibited_sources,
            prohibited_outputs: &self.prohibited_outputs,
            prohibited_claims: &self.prohibited_claims,
            prohibited_side_effects: &self.prohibited_side_effects,
            registered_at: self.registered_at,
        }
    }

    /// Returns the fixed contract string.
    #[must_use]
    pub const fn contract_name() -> &'static str {
        PROGRAM_REGISTRATION_CONTRACT
    }
}
