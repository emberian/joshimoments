//! Pure Cockpit V2 semantic-manifest and immutable publication contracts.
//!
//! V2 closes the broad surface at the publication waist. It carries typed, sorted references to
//! public source facts, the Ember-approved surface profile, the declared observed universe,
//! membership, coverage and gaps. It carries no source body bytes and rejects private or
//! authenticated protection domains. The commit state machine below is a model of crash-visible
//! states; it performs no store or route I/O.

#![allow(clippy::missing_errors_doc)]

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_projection::ProjectionAuthority;
use serde::{Deserialize, Serialize};

use crate::{
    COCKPIT_V2_CHECKPOINT_CONTRACT, COCKPIT_V2_MANIFEST_CONTRACT, COCKPIT_V2_PUBLICATION_CONTRACT,
    COCKPIT_V2_QUERY_CONTRACT, COCKPIT_V2_SCHEMA_VERSION, CockpitPublicationId, PublicationError,
    digest_json, digest_match, sha256_digest, stable, validate_sha256,
};

/// Exact valid/knowledge/commit cutoff used by every V2 query and manifest.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2CutoffV1 {
    pub knowledge_at: UtcTimestamp,
    pub commit_through: Option<CommitSeq>,
    pub chain_slot: Option<WireU64>,
}

/// Only public source bytes may be named by a public cockpit publication.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProtectionDomain {
    Public,
    AppPrivate,
    Authenticated,
    RawPrivateBytes,
}

/// Typed source-fact reference. A reference is not a source-body container.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2SourceFactRefV1 {
    pub fact_id: StableString,
    pub fact_digest: ValueDigest,
    /// Profile-declared surface that owns this public fact.
    pub surface_id: StableString,
    pub source_id: StableString,
    /// Facts are subject-bound. A source-wide fact cannot silently cover another subject.
    pub subject: StableString,
    /// Facts are field-bound so exact all-fact coverage has one unambiguous cell.
    pub field: StableString,
    pub protection: ProtectionDomain,
    pub observed_at: UtcTimestamp,
    pub known_at: UtcTimestamp,
    pub commit_seq: Option<CommitSeq>,
}

/// One declared profile source/field cell. The manifest repeats this public semantic shape so it
/// can prove the complete profile × eligible-subject coverage denominator without loading a
/// private profile body.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2SurfaceFieldRefV1 {
    pub surface_id: StableString,
    pub source_id: StableString,
    pub field: StableString,
}

/// Exact profile closure consumed by Glass and publication.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2SurfaceProfileRefV1 {
    pub profile_id: StableString,
    pub profile_digest: ValueDigest,
    pub field_cells: Vec<CockpitV2SurfaceFieldRefV1>,
}

/// Exact eligible denominator closure consumed by Glass and publication.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2ObservedUniverseRefV1 {
    pub universe_id: StableString,
    pub universe_digest: ValueDigest,
    pub eligible_count: WireU64,
    pub eligible_subjects: Vec<StableString>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UniverseMaterial<'a> {
    domain: &'static str,
    universe_id: &'a StableString,
    eligible_count: WireU64,
    eligible_subjects: &'a [StableString],
}

impl CockpitV2ObservedUniverseRefV1 {
    pub fn computed_digest(&self) -> Result<ValueDigest, PublicationError> {
        digest_json(&UniverseMaterial {
            domain: "joshi.cockpit.v2.observed_universe.v1",
            universe_id: &self.universe_id,
            eligible_count: self.eligible_count,
            eligible_subjects: &self.eligible_subjects,
        })
    }
}

/// Membership classes retain cold/control and hot/episode semantics in the public artifact.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitV2MembershipKind {
    Census,
    Warm,
    Hot,
    Episode,
    ColdControl,
    DenominatorOnly,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2MembershipRefV1 {
    pub subject: StableString,
    pub membership: CockpitV2MembershipKind,
    pub observed_at: UtcTimestamp,
    pub evidence_digest: ValueDigest,
}

/// Field/source coverage state remains explicit in the public artifact.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitV2CoverageState {
    Complete,
    Partial,
    Stale,
    Unknown,
    Unavailable,
    Refused,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2CoverageRefV1 {
    pub surface_id: StableString,
    pub source_id: StableString,
    pub subject: StableString,
    pub field: StableString,
    pub fact_ids: Vec<StableString>,
    pub state: CockpitV2CoverageState,
    pub coverage_digest: ValueDigest,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2GapRefV1 {
    pub gap_id: StableString,
    pub surface_id: StableString,
    pub source_id: StableString,
    pub subject: StableString,
    pub field: StableString,
    pub reason: StableString,
    pub since: UtcTimestamp,
    pub until: Option<UtcTimestamp>,
    pub evidence_digest: Option<ValueDigest>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2OmissionV1 {
    pub subject: StableString,
    pub reason: StableString,
    pub membership: CockpitV2MembershipKind,
}

/// Immutable broad semantic surface manifest. The rendered subset cannot hide references,
/// denominator, coverage or gaps.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2ManifestV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub surface_profile: CockpitV2SurfaceProfileRefV1,
    pub observed_universe: CockpitV2ObservedUniverseRefV1,
    pub cutoff: CockpitV2CutoffV1,
    pub source_facts: Vec<CockpitV2SourceFactRefV1>,
    pub memberships: Vec<CockpitV2MembershipRefV1>,
    pub coverage: Vec<CockpitV2CoverageRefV1>,
    pub gaps: Vec<CockpitV2GapRefV1>,
    pub rendered_subjects: Vec<StableString>,
    pub omissions: Vec<CockpitV2OmissionV1>,
    pub ordering_policy: StableString,
    pub pagination_policy: StableString,
    pub authority: ProjectionAuthority,
    pub ceiling: CockpitV2Ceiling,
    pub semantic_digest: ValueDigest,
    pub container_digest: ValueDigest,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitV2Ceiling {
    UnverifiedSemantic,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SemanticMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    surface_profile: &'a CockpitV2SurfaceProfileRefV1,
    observed_universe: &'a CockpitV2ObservedUniverseRefV1,
    cutoff: CockpitV2CutoffV1,
    source_facts: &'a [CockpitV2SourceFactRefV1],
    memberships: &'a [CockpitV2MembershipRefV1],
    coverage: &'a [CockpitV2CoverageRefV1],
    gaps: &'a [CockpitV2GapRefV1],
    rendered_subjects: &'a [StableString],
    omissions: &'a [CockpitV2OmissionV1],
    ordering_policy: &'a StableString,
    pagination_policy: &'a StableString,
    authority: ProjectionAuthority,
    ceiling: CockpitV2Ceiling,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ContainerMaterial<'a> {
    semantic: SemanticMaterial<'a>,
    semantic_digest: &'a ValueDigest,
    container_digest: &'a ValueDigest,
}

impl CockpitV2ManifestV1 {
    fn semantic_material(&self) -> SemanticMaterial<'_> {
        SemanticMaterial {
            contract: &self.contract,
            schema_version: self.schema_version,
            surface_profile: &self.surface_profile,
            observed_universe: &self.observed_universe,
            cutoff: self.cutoff,
            source_facts: &self.source_facts,
            memberships: &self.memberships,
            coverage: &self.coverage,
            gaps: &self.gaps,
            rendered_subjects: &self.rendered_subjects,
            omissions: &self.omissions,
            ordering_policy: &self.ordering_policy,
            pagination_policy: &self.pagination_policy,
            authority: self.authority,
            ceiling: self.ceiling,
        }
    }

    fn container_digest_with(&self, digest: &ValueDigest) -> Result<ValueDigest, PublicationError> {
        digest_json(&ContainerMaterial {
            semantic: self.semantic_material(),
            semantic_digest: &self.semantic_digest,
            container_digest: digest,
        })
    }

    pub fn computed_semantic_digest(&self) -> Result<ValueDigest, PublicationError> {
        digest_json(&self.semantic_material())
    }

    /// Computes the container digest over canonical fields with a zero self-slot. This is
    /// intentionally distinct from the semantic digest and from the final serialized bytes.
    pub fn computed_container_digest(&self) -> Result<ValueDigest, PublicationError> {
        self.container_digest_with(&crate::zero_digest()?)
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PublicationError> {
        self.validate()?;
        serde_json::to_vec(self).map_err(PublicationError::from)
    }

    #[allow(clippy::too_many_lines)]
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != COCKPIT_V2_MANIFEST_CONTRACT
            || self.schema_version != COCKPIT_V2_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
            || self.ceiling != CockpitV2Ceiling::UnverifiedSemantic
        {
            return Err(PublicationError::CockpitV2Contract);
        }
        validate_sha256(&self.surface_profile.profile_digest)?;
        validate_sha256(&self.observed_universe.universe_digest)?;
        validate_sha256(&self.semantic_digest)?;
        validate_sha256(&self.container_digest)?;
        if self
            .cutoff
            .commit_through
            .is_some_and(|commit| commit == CommitSeq::new(0))
        {
            return Err(PublicationError::CockpitV2Cutoff);
        }
        validate_sorted_unique(&self.source_facts, |value| &value.fact_id)?;
        validate_sorted_unique(&self.memberships, |value| &value.subject)?;
        validate_sorted_unique(&self.gaps, |value| &value.gap_id)?;
        validate_sorted_unique(&self.rendered_subjects, |value| value)?;
        validate_sorted_unique(&self.observed_universe.eligible_subjects, |value| value)?;
        if u64::try_from(self.observed_universe.eligible_subjects.len())
            .map_err(|_| PublicationError::CockpitV2Reference)?
            != self.observed_universe.eligible_count.get()
        {
            return Err(PublicationError::CockpitV2Reference);
        }
        let universe_digest = self.observed_universe.computed_digest()?;
        digest_match(
            "cockpit V2 observed universe",
            &self.observed_universe.universe_digest,
            &universe_digest,
        )?;
        let eligible: std::collections::BTreeSet<_> =
            self.observed_universe.eligible_subjects.iter().collect();
        let memberships: std::collections::BTreeSet<_> = self
            .memberships
            .iter()
            .map(|value| &value.subject)
            .collect();
        let rendered: std::collections::BTreeSet<_> = self.rendered_subjects.iter().collect();
        let omissions: std::collections::BTreeSet<_> =
            self.omissions.iter().map(|value| &value.subject).collect();
        let mut rendered_partition = rendered.clone();
        rendered_partition.extend(omissions.iter().copied());
        if memberships != eligible
            || rendered_partition != eligible
            || !rendered.is_disjoint(&omissions)
            || memberships
                .iter()
                .chain(rendered.iter())
                .chain(omissions.iter())
                .any(|subject| !eligible.contains(subject))
        {
            return Err(PublicationError::CockpitV2Reference);
        }
        if self
            .omissions
            .windows(2)
            .any(|window| window[0] >= window[1])
        {
            return Err(PublicationError::CockpitV2Ordering);
        }
        if self.surface_profile.field_cells.is_empty() || self.coverage.is_empty() {
            return Err(PublicationError::CockpitV2Reference);
        }
        if self.surface_profile.field_cells.windows(2).any(|window| {
            (
                &window[0].surface_id,
                &window[0].source_id,
                &window[0].field,
            ) >= (
                &window[1].surface_id,
                &window[1].source_id,
                &window[1].field,
            )
        }) || self.coverage.windows(2).any(|window| {
            (
                &window[0].surface_id,
                &window[0].source_id,
                &window[0].subject,
                &window[0].field,
            ) >= (
                &window[1].surface_id,
                &window[1].source_id,
                &window[1].subject,
                &window[1].field,
            )
        }) {
            return Err(PublicationError::CockpitV2Ordering);
        }
        let declared_cells: std::collections::BTreeSet<_> = self
            .surface_profile
            .field_cells
            .iter()
            .map(|cell| (&cell.surface_id, &cell.source_id, &cell.field))
            .collect();
        let expected_coverage: std::collections::BTreeSet<_> = self
            .surface_profile
            .field_cells
            .iter()
            .flat_map(|cell| {
                self.observed_universe.eligible_subjects.iter().map(move |subject| {
                    (&cell.surface_id, &cell.source_id, subject, &cell.field)
                })
            })
            .collect();
        let actual_coverage: std::collections::BTreeSet<_> = self
            .coverage
            .iter()
            .map(|cell| (&cell.surface_id, &cell.source_id, &cell.subject, &cell.field))
            .collect();
        if actual_coverage != expected_coverage || actual_coverage.len() != self.coverage.len() {
            return Err(PublicationError::CockpitV2Reference);
        }
        for fact in &self.source_facts {
            validate_sha256(&fact.fact_digest)?;
            if fact.protection != ProtectionDomain::Public {
                return Err(PublicationError::CockpitV2PrivateBytes);
            }
            if !eligible.contains(&fact.subject)
                || !declared_cells.contains(&(&fact.surface_id, &fact.source_id, &fact.field))
            {
                return Err(PublicationError::CockpitV2Reference);
            }
            if fact.observed_at > fact.known_at || fact.known_at > self.cutoff.knowledge_at {
                return Err(PublicationError::CockpitV2Cutoff);
            }
            if self
                .cutoff
                .commit_through
                .zip(fact.commit_seq)
                .is_some_and(|(cut, seq)| seq > cut)
            {
                return Err(PublicationError::CockpitV2Cutoff);
            }
            if self.cutoff.commit_through.is_some() && fact.commit_seq.is_none() {
                return Err(PublicationError::CockpitV2Cutoff);
            }
        }
        for membership in &self.memberships {
            validate_sha256(&membership.evidence_digest)?;
            if membership.observed_at > self.cutoff.knowledge_at {
                return Err(PublicationError::CockpitV2Cutoff);
            }
        }
        for coverage in &self.coverage {
            validate_sha256(&coverage.coverage_digest)?;
            if coverage.fact_ids.windows(2).any(|window| window[0] >= window[1])
            {
                return Err(PublicationError::CockpitV2Reference);
            }
            if coverage.state == CockpitV2CoverageState::Complete
                && (coverage.fact_ids.is_empty()
                    || self.gaps.iter().any(|gap| {
                        gap.surface_id == coverage.surface_id
                            && gap.source_id == coverage.source_id
                            && gap.subject == coverage.subject
                            && gap.field == coverage.field
                    }))
            {
                return Err(PublicationError::CockpitV2Reference);
            }
        }
        let facts_by_id: std::collections::BTreeMap<_, _> = self
            .source_facts
            .iter()
            .map(|fact| (&fact.fact_id, fact))
            .collect();
        for coverage in &self.coverage {
            let scoped_facts: Vec<_> = coverage
                .fact_ids
                .iter()
                .filter_map(|fact_id| facts_by_id.get(fact_id))
                .collect();
            if scoped_facts.len() != coverage.fact_ids.len() {
                return Err(PublicationError::CockpitV2Reference);
            }
            if scoped_facts.iter().any(|fact| {
                fact.surface_id != coverage.surface_id
                    || fact.source_id != coverage.source_id
                    || fact.subject != coverage.subject
                    || fact.field != coverage.field
            }) {
                return Err(PublicationError::CockpitV2Reference);
            }
        }
        let source_fact_ids: std::collections::BTreeSet<_> =
            self.source_facts.iter().map(|fact| &fact.fact_id).collect();
        let mut referenced_fact_ids = std::collections::BTreeSet::new();
        for fact_id in self
            .coverage
            .iter()
            .flat_map(|coverage| coverage.fact_ids.iter())
        {
            if !referenced_fact_ids.insert(fact_id) {
                return Err(PublicationError::CockpitV2Reference);
            }
        }
        if referenced_fact_ids != source_fact_ids {
            return Err(PublicationError::CockpitV2Reference);
        }
        for gap in &self.gaps {
            if !actual_coverage.contains(&(
                &gap.surface_id,
                &gap.source_id,
                &gap.subject,
                &gap.field,
            )) {
                return Err(PublicationError::CockpitV2Reference);
            }
            if gap.since > self.cutoff.knowledge_at
                || gap
                    .until
                    .is_some_and(|until| until > self.cutoff.knowledge_at)
                || gap.until.is_some_and(|until| until <= gap.since)
            {
                return Err(PublicationError::CockpitV2Cutoff);
            }
            if let Some(digest) = &gap.evidence_digest {
                validate_sha256(digest)?;
            }
        }
        let semantic = self.computed_semantic_digest()?;
        digest_match("cockpit V2 semantic", &self.semantic_digest, &semantic)?;
        let zero = crate::zero_digest()?;
        let container = self.container_digest_with(&zero)?;
        digest_match("cockpit V2 container", &self.container_digest, &container)
            .map_err(|_| PublicationError::CockpitV2Digest)
    }
}

fn validate_sorted_unique<T, F>(values: &[T], key: F) -> Result<(), PublicationError>
where
    F: Fn(&T) -> &StableString,
{
    if values
        .windows(2)
        .any(|window| key(&window[0]) >= key(&window[1]))
    {
        return Err(PublicationError::CockpitV2Ordering);
    }
    Ok(())
}

/// Exact preparation output; no I/O is performed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedCockpitV2 {
    pub manifest: CockpitV2ManifestV1,
    pub semantic_bytes: Vec<u8>,
    pub container_bytes: Vec<u8>,
    pub checkpoint: CockpitV2CheckpointV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2CheckpointV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub profile_digest: ValueDigest,
    pub universe_digest: ValueDigest,
    pub cutoff: CockpitV2CutoffV1,
    pub semantic_digest: ValueDigest,
    pub container_digest: ValueDigest,
    pub checkpoint_digest: ValueDigest,
    pub authority: ProjectionAuthority,
}

impl CockpitV2CheckpointV1 {
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != COCKPIT_V2_CHECKPOINT_CONTRACT
            || self.schema_version != COCKPIT_V2_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::CockpitV2Contract);
        }
        validate_sha256(&self.profile_digest)?;
        validate_sha256(&self.universe_digest)?;
        validate_sha256(&self.semantic_digest)?;
        validate_sha256(&self.container_digest)?;
        validate_sha256(&self.checkpoint_digest)?;
        let material = (
            &self.profile_digest,
            &self.universe_digest,
            self.cutoff,
            &self.semantic_digest,
            &self.container_digest,
        );
        let computed = digest_json(&material)?;
        digest_match("cockpit V2 checkpoint", &self.checkpoint_digest, &computed)
    }
}

pub fn prepare_cockpit_v2(
    manifest: CockpitV2ManifestV1,
) -> Result<PreparedCockpitV2, PublicationError> {
    let semantic_bytes = serde_json::to_vec(&manifest.semantic_material())?;
    let semantic_digest = sha256_digest(&semantic_bytes);
    if semantic_digest != manifest.semantic_digest {
        return Err(PublicationError::CockpitV2Digest);
    }
    manifest.validate()?;
    let container_bytes = manifest.canonical_bytes()?;
    let checkpoint_material = (
        &manifest.surface_profile.profile_digest,
        &manifest.observed_universe.universe_digest,
        manifest.cutoff,
        &manifest.semantic_digest,
        &manifest.container_digest,
    );
    let mut checkpoint = CockpitV2CheckpointV1 {
        contract: stable(COCKPIT_V2_CHECKPOINT_CONTRACT),
        schema_version: COCKPIT_V2_SCHEMA_VERSION,
        profile_digest: manifest.surface_profile.profile_digest.clone(),
        universe_digest: manifest.observed_universe.universe_digest.clone(),
        cutoff: manifest.cutoff,
        semantic_digest: manifest.semantic_digest.clone(),
        container_digest: manifest.container_digest.clone(),
        checkpoint_digest: crate::zero_digest()?,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
    };
    checkpoint.checkpoint_digest = digest_json(&checkpoint_material)?;
    Ok(PreparedCockpitV2 {
        manifest,
        semantic_bytes,
        container_bytes,
        checkpoint,
    })
}

/// Strict canonical decoders used by publication adapters and readback checks.
pub fn parse_cockpit_v2_manifest(bytes: &[u8]) -> Result<CockpitV2ManifestV1, PublicationError> {
    let value: CockpitV2ManifestV1 = serde_json::from_slice(bytes)?;
    value.validate()?;
    if value.canonical_bytes()? != bytes {
        return Err(PublicationError::CockpitV2Digest);
    }
    Ok(value)
}

pub fn parse_cockpit_v2_checkpoint(
    bytes: &[u8],
) -> Result<CockpitV2CheckpointV1, PublicationError> {
    let value: CockpitV2CheckpointV1 = serde_json::from_slice(bytes)?;
    value.validate()?;
    if serde_json::to_vec(&value)? != bytes {
        return Err(PublicationError::CockpitV2Digest);
    }
    Ok(value)
}

pub fn parse_cockpit_v2_query(bytes: &[u8]) -> Result<CockpitV2QueryV1, PublicationError> {
    let value: CockpitV2QueryV1 = serde_json::from_slice(bytes)?;
    value.validate()?;
    if serde_json::to_vec(&value)? != bytes {
        return Err(PublicationError::CockpitV2Digest);
    }
    Ok(value)
}

pub fn parse_cockpit_v2_head(bytes: &[u8]) -> Result<CockpitV2HeadV1, PublicationError> {
    let value: CockpitV2HeadV1 = serde_json::from_slice(bytes)?;
    value.canonical_bytes()?;
    if serde_json::to_vec(&value)? != bytes {
        return Err(PublicationError::CockpitV2Digest);
    }
    Ok(value)
}

pub fn parse_cockpit_v2_publication(
    bytes: &[u8],
) -> Result<CockpitV2PublicationV1, PublicationError> {
    let value: CockpitV2PublicationV1 = serde_json::from_slice(bytes)?;
    if value.canonical_bytes()? != bytes {
        return Err(PublicationError::CockpitV2Digest);
    }
    Ok(value)
}

impl PreparedCockpitV2 {
    pub fn validate(&self) -> Result<(), PublicationError> {
        self.manifest.validate()?;
        self.checkpoint.validate()?;
        if serde_json::to_vec(&self.manifest.semantic_material())? != self.semantic_bytes
            || self.manifest.canonical_bytes()? != self.container_bytes
        {
            return Err(PublicationError::CockpitV2Digest);
        }
        if self.checkpoint.profile_digest != self.manifest.surface_profile.profile_digest
            || self.checkpoint.universe_digest != self.manifest.observed_universe.universe_digest
            || self.checkpoint.cutoff != self.manifest.cutoff
            || self.checkpoint.semantic_digest != self.manifest.semantic_digest
            || self.checkpoint.container_digest != self.manifest.container_digest
        {
            return Err(PublicationError::CockpitV2Reference);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2PublicationV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub publication_id: CockpitPublicationId,
    pub manifest: CockpitV2ManifestV1,
    pub checkpoint: CockpitV2CheckpointV1,
    pub commit_seq: CommitSeq,
    pub supersedes_publication_id: Option<CockpitPublicationId>,
    pub publication_digest: ValueDigest,
    pub authority: ProjectionAuthority,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PublicationV2Material<'a> {
    contract: &'a StableString,
    schema_version: u16,
    publication_id: &'a CockpitPublicationId,
    manifest: &'a CockpitV2ManifestV1,
    checkpoint: &'a CockpitV2CheckpointV1,
    commit_seq: CommitSeq,
    supersedes_publication_id: &'a Option<CockpitPublicationId>,
    authority: ProjectionAuthority,
}

impl CockpitV2PublicationV1 {
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != COCKPIT_V2_PUBLICATION_CONTRACT
            || self.schema_version != COCKPIT_V2_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::CockpitV2Contract);
        }
        self.manifest.validate()?;
        self.checkpoint.validate()?;
        if self
            .manifest
            .cutoff
            .commit_through
            .is_some_and(|cut| self.commit_seq <= cut)
        {
            return Err(PublicationError::CommitOrder);
        }
        if self.checkpoint.semantic_digest != self.manifest.semantic_digest
            || self.checkpoint.container_digest != self.manifest.container_digest
            || self.checkpoint.profile_digest != self.manifest.surface_profile.profile_digest
            || self.checkpoint.universe_digest != self.manifest.observed_universe.universe_digest
            || self.checkpoint.cutoff != self.manifest.cutoff
        {
            return Err(PublicationError::CockpitV2Reference);
        }
        validate_sha256(&self.publication_digest)?;
        let computed = digest_json(&PublicationV2Material {
            contract: &self.contract,
            schema_version: self.schema_version,
            publication_id: &self.publication_id,
            manifest: &self.manifest,
            checkpoint: &self.checkpoint,
            commit_seq: self.commit_seq,
            supersedes_publication_id: &self.supersedes_publication_id,
            authority: self.authority,
        })?;
        digest_match(
            "cockpit V2 publication",
            &self.publication_digest,
            &computed,
        )
    }
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PublicationError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }
}

pub fn finalize_cockpit_v2(
    prepared: &PreparedCockpitV2,
    publication_id: CockpitPublicationId,
    commit_seq: CommitSeq,
    supersedes_publication_id: Option<CockpitPublicationId>,
    previous: Option<&CockpitV2PublicationV1>,
) -> Result<CockpitV2PublicationV1, PublicationError> {
    prepared.validate()?;
    if let Some(cut) = prepared.manifest.cutoff.commit_through
        && commit_seq <= cut
    {
        return Err(PublicationError::CommitOrder);
    }
    match (previous, &supersedes_publication_id) {
        (None, None) => {}
        (Some(prior), Some(id)) if &prior.publication_id == id && prior.commit_seq < commit_seq => {
            prior.validate()?;
        }
        _ => return Err(PublicationError::Supersession),
    }
    let mut value = CockpitV2PublicationV1 {
        contract: stable(COCKPIT_V2_PUBLICATION_CONTRACT),
        schema_version: COCKPIT_V2_SCHEMA_VERSION,
        publication_id,
        manifest: prepared.manifest.clone(),
        checkpoint: prepared.checkpoint.clone(),
        commit_seq,
        supersedes_publication_id,
        publication_digest: crate::zero_digest()?,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
    };
    value.publication_digest = digest_json(&PublicationV2Material {
        contract: &value.contract,
        schema_version: value.schema_version,
        publication_id: &value.publication_id,
        manifest: &value.manifest,
        checkpoint: &value.checkpoint,
        commit_seq: value.commit_seq,
        supersedes_publication_id: &value.supersedes_publication_id,
        authority: value.authority,
    })?;
    value.validate()?;
    Ok(value)
}

/// Immutable append-only V2 head. It is separate from the publication body so a crash between
/// body commit and head append leaves the prior head selected without exposing a mixture.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2HeadV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub publication_id: CockpitPublicationId,
    pub publication_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub head_digest: ValueDigest,
    pub authority: ProjectionAuthority,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct HeadV2Material<'a> {
    contract: &'a StableString,
    schema_version: u16,
    publication_id: &'a CockpitPublicationId,
    publication_digest: &'a ValueDigest,
    commit_seq: CommitSeq,
    authority: ProjectionAuthority,
}

impl CockpitV2HeadV1 {
    pub fn from_publication(
        publication: &CockpitV2PublicationV1,
    ) -> Result<Self, PublicationError> {
        publication.validate()?;
        let contract = stable("joshi.cockpit.v2.head");
        let mut head = Self {
            contract,
            schema_version: COCKPIT_V2_SCHEMA_VERSION,
            publication_id: publication.publication_id.clone(),
            publication_digest: publication.publication_digest.clone(),
            commit_seq: publication.commit_seq,
            head_digest: crate::zero_digest()?,
            authority: ProjectionAuthority::ReadOnlyNoExecution,
        };
        head.head_digest = digest_json(&HeadV2Material {
            contract: &head.contract,
            schema_version: head.schema_version,
            publication_id: &head.publication_id,
            publication_digest: &head.publication_digest,
            commit_seq: head.commit_seq,
            authority: head.authority,
        })?;
        Ok(head)
    }
    pub fn validate_against(
        &self,
        publication: &CockpitV2PublicationV1,
    ) -> Result<(), PublicationError> {
        publication.validate()?;
        if self.contract.as_str() != "joshi.cockpit.v2.head"
            || self.schema_version != COCKPIT_V2_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
            || self.publication_id != publication.publication_id
            || self.publication_digest != publication.publication_digest
            || self.commit_seq != publication.commit_seq
        {
            return Err(PublicationError::CockpitV2Stage);
        }
        validate_sha256(&self.head_digest)?;
        let expected = digest_json(&HeadV2Material {
            contract: &self.contract,
            schema_version: self.schema_version,
            publication_id: &self.publication_id,
            publication_digest: &self.publication_digest,
            commit_seq: self.commit_seq,
            authority: self.authority,
        })?;
        digest_match("cockpit V2 head", &self.head_digest, &expected)
    }
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PublicationError> {
        if self.contract.as_str() != "joshi.cockpit.v2.head"
            || self.schema_version != COCKPIT_V2_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
        {
            return Err(PublicationError::CockpitV2Contract);
        }
        validate_sha256(&self.head_digest)?;
        let expected = digest_json(&HeadV2Material {
            contract: &self.contract,
            schema_version: self.schema_version,
            publication_id: &self.publication_id,
            publication_digest: &self.publication_digest,
            commit_seq: self.commit_seq,
            authority: self.authority,
        })?;
        digest_match("cockpit V2 head", &self.head_digest, &expected)?;
        Ok(serde_json::to_vec(self)?)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2QueryV1 {
    pub contract: StableString,
    pub publication_id: CockpitPublicationId,
    pub semantic_digest: ValueDigest,
    pub container_digest: ValueDigest,
    pub cutoff: CockpitV2CutoffV1,
}

impl CockpitV2QueryV1 {
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != COCKPIT_V2_QUERY_CONTRACT {
            return Err(PublicationError::CockpitV2Contract);
        }
        validate_sha256(&self.semantic_digest)?;
        validate_sha256(&self.container_digest)?;
        Ok(())
    }
    pub fn validate_loaded(
        &self,
        publication: &CockpitV2PublicationV1,
    ) -> Result<(), PublicationError> {
        self.validate()?;
        publication.validate()?;
        if self.publication_id != publication.publication_id
            || self.semantic_digest != publication.manifest.semantic_digest
            || self.container_digest != publication.manifest.container_digest
            || self.cutoff != publication.manifest.cutoff
        {
            return Err(PublicationError::QueryMismatch);
        }
        Ok(())
    }
}

/// Crash-visible pure commit stages. A failed prepare exposes the prior head; a committed body
/// exposes the complete new publication while the prior head remains selected; head publication
/// exposes the new complete head.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitV2CommitStage {
    Prepared,
    Committed,
    HeadPublished,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2CommitStateV1 {
    pub stage: CockpitV2CommitStage,
    pub publication_id: CockpitPublicationId,
    pub container_digest: ValueDigest,
    pub head_digest: Option<ValueDigest>,
}

impl CockpitV2CommitStateV1 {
    pub fn validate(&self, publication: &CockpitV2PublicationV1) -> Result<(), PublicationError> {
        publication.validate()?;
        if publication.publication_id != self.publication_id
            || publication.manifest.container_digest != self.container_digest
            || (self.stage != CockpitV2CommitStage::HeadPublished && self.head_digest.is_some())
            || (self.stage == CockpitV2CommitStage::HeadPublished && self.head_digest.is_none())
        {
            return Err(PublicationError::CockpitV2Stage);
        }
        if let Some(digest) = &self.head_digest {
            let head = CockpitV2HeadV1::from_publication(publication)?;
            if digest != &head.head_digest {
                return Err(PublicationError::CockpitV2Stage);
            }
        }
        Ok(())
    }

    pub fn advance(
        &self,
        next: CockpitV2CommitStage,
        publication: &CockpitV2PublicationV1,
        head_digest: Option<ValueDigest>,
    ) -> Result<Self, PublicationError> {
        self.validate(publication)?;
        if publication.publication_id != self.publication_id
            || publication.manifest.container_digest != self.container_digest
            || next <= self.stage
            || (next == CockpitV2CommitStage::HeadPublished && head_digest.is_none())
        {
            return Err(PublicationError::CockpitV2Stage);
        }
        if self.stage == CockpitV2CommitStage::Prepared && self.head_digest.is_some()
            || self.stage == CockpitV2CommitStage::Committed && self.head_digest.is_some()
            || next == CockpitV2CommitStage::Committed && head_digest.is_some()
        {
            return Err(PublicationError::CockpitV2Stage);
        }
        let expected_next = match self.stage {
            CockpitV2CommitStage::Prepared => CockpitV2CommitStage::Committed,
            CockpitV2CommitStage::Committed => CockpitV2CommitStage::HeadPublished,
            CockpitV2CommitStage::HeadPublished => return Err(PublicationError::CockpitV2Stage),
        };
        if next != expected_next {
            return Err(PublicationError::CockpitV2Stage);
        }
        if let Some(digest) = &head_digest {
            validate_sha256(digest)?;
            let head = CockpitV2HeadV1::from_publication(publication)?;
            if *digest != head.head_digest {
                return Err(PublicationError::CockpitV2Stage);
            }
        }
        Ok(Self {
            stage: next,
            publication_id: self.publication_id.clone(),
            container_digest: self.container_digest.clone(),
            head_digest,
        })
    }
}
