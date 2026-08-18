//! Exact append-only fixture campaign lifecycle.

use std::collections::BTreeSet;

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use serde::{Deserialize, Serialize};

use crate::{
    CAMPAIGN_LIFECYCLE_CONTRACT, ProgramAuthorityV1, RegistryError, Result, SemanticCeilingV1,
    Wave6ProgramRegistrationV1, canonical_bytes, digest_bytes,
};

/// Declared campaign lifecycle state. Every public occurrence remains caller-fed and unverified.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CampaignStateV1 {
    /// Exploratory draft with no prospective standing.
    DraftExploratory,
    /// Caller-declared preregistration; not a durable seal.
    Preregistered,
    /// Caller-declared frozen enrollment commitment.
    EnrollmentFrozen,
    /// Caller-declared running phase; this crate performs no work.
    Running,
    /// Caller-declared seal; this crate owns no sealed journal.
    Sealed,
    /// Caller-declared maturation.
    Matured,
    /// Caller-declared censoring.
    Censored,
    /// Apparatus failure, never a scientific negative result.
    AbortedApparatus,
    /// Caller-declared adjudication.
    Adjudicated,
    /// Continue unchanged.
    Continue,
    /// Revision requires an independently identified new campaign.
    ReviseAsNewCampaign,
    /// Park without deletion.
    Park,
    /// Reject without deletion.
    Reject,
}

impl CampaignStateV1 {
    fn allows(self, next: Self) -> bool {
        matches!(
            (self, next),
            (Self::DraftExploratory, Self::Preregistered)
                | (Self::Preregistered, Self::EnrollmentFrozen)
                | (Self::EnrollmentFrozen, Self::Running)
                | (Self::Running, Self::Sealed)
                | (
                    Self::Sealed,
                    Self::Matured | Self::Censored | Self::AbortedApparatus
                )
                | (
                    Self::Matured | Self::Censored | Self::AbortedApparatus,
                    Self::Adjudicated
                )
                | (
                    Self::Adjudicated,
                    Self::Continue | Self::ReviseAsNewCampaign | Self::Park | Self::Reject
                )
        )
    }
}

/// One append-only caller-fed lifecycle transition.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignTransitionV1 {
    /// Distinct transition occurrence identity.
    pub transition_id: StableString,
    /// Exact predecessor transition, absent only for the draft genesis.
    pub predecessor_transition_id: Option<StableString>,
    /// Prior state, absent only for the draft genesis.
    pub from_state: Option<CampaignStateV1>,
    /// New declared state.
    pub to_state: CampaignStateV1,
    /// Exact immutable campaign-definition digest.
    pub campaign_definition_digest: ValueDigest,
    /// Exact commitment introduced at enrollment freeze and immutable afterward.
    pub frozen_commitment_digest: Option<ValueDigest>,
    /// Caller fixture clock; not a store commit.
    pub recorded_at: UtcTimestamp,
    /// Stable transition reason.
    pub reason: StableString,
    /// Optional successor campaign required only for `revise_as_new_campaign`.
    pub successor_campaign_id: Option<StableString>,
    /// Fixed authority.
    pub authority: ProgramAuthorityV1,
    /// Fixed semantic ceiling.
    pub semantic_ceiling: SemanticCeilingV1,
}

/// Exact fixture campaign lifecycle document.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampaignLifecycleV1 {
    /// Contract discriminator.
    pub contract: StableString,
    /// Owning program.
    pub program_id: StableString,
    /// Owning registration digest.
    pub registration_digest: ValueDigest,
    /// One campaign identity.
    pub campaign_id: StableString,
    /// Strict append order.
    pub transitions: Vec<CampaignTransitionV1>,
    /// Digest over [`CampaignLifecycleDigestMaterialV1`].
    pub lifecycle_digest: ValueDigest,
}

/// Self-digest material for [`CampaignLifecycleV1`].
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampaignLifecycleDigestMaterialV1<'a> {
    /// Contract.
    pub contract: &'a StableString,
    /// Program.
    pub program_id: &'a StableString,
    /// Registration digest.
    pub registration_digest: &'a ValueDigest,
    /// Campaign.
    pub campaign_id: &'a StableString,
    /// Ordered transitions.
    pub transitions: &'a [CampaignTransitionV1],
}

impl CampaignLifecycleV1 {
    /// Returns exact self-digest material.
    #[must_use]
    pub fn digest_material(&self) -> CampaignLifecycleDigestMaterialV1<'_> {
        CampaignLifecycleDigestMaterialV1 {
            contract: &self.contract,
            program_id: &self.program_id,
            registration_digest: &self.registration_digest,
            campaign_id: &self.campaign_id,
            transitions: &self.transitions,
        }
    }

    /// Revalidates the exact declared lifecycle.
    ///
    /// # Errors
    ///
    /// Refuses non-draft genesis, skipped/branched/backdated phases, commitment mutation,
    /// successor misuse, authority widening, duplicate transitions, or digest mismatch.
    pub fn validate(&self, registration: &Wave6ProgramRegistrationV1) -> Result<()> {
        if self.contract.as_str() != CAMPAIGN_LIFECYCLE_CONTRACT
            || self.program_id != registration.program_id
            || self.registration_digest != registration.registration_digest
            || self.transitions.is_empty()
        {
            return Err(RegistryError::Campaign("registration binding"));
        }

        let mut ids = BTreeSet::new();
        let mut previous: Option<&CampaignTransitionV1> = None;
        let mut definition: Option<&ValueDigest> = None;
        let mut frozen: Option<&ValueDigest> = None;
        for transition in &self.transitions {
            super::validate::validate_sha256_public(
                &transition.campaign_definition_digest,
                "campaignDefinitionDigest",
            )?;
            if let Some(commitment) = &transition.frozen_commitment_digest {
                super::validate::validate_sha256_public(commitment, "frozenCommitmentDigest")?;
            }
            if transition.authority != registration.authority
                || transition.semantic_ceiling != SemanticCeilingV1::UnverifiedSemanticFixtureOnly
                || !ids.insert(&transition.transition_id)
            {
                return Err(RegistryError::Campaign("transition occurrence"));
            }
            if let Some(exact_definition) = definition {
                if exact_definition != &transition.campaign_definition_digest {
                    return Err(RegistryError::Campaign("definition mutation"));
                }
            } else {
                definition = Some(&transition.campaign_definition_digest);
            }

            match previous {
                None if transition.predecessor_transition_id.is_none()
                    && transition.from_state.is_none()
                    && transition.to_state == CampaignStateV1::DraftExploratory
                    && transition.frozen_commitment_digest.is_none() => {}
                None => return Err(RegistryError::Campaign("draft genesis")),
                Some(prior)
                    if transition.predecessor_transition_id.as_ref()
                        != Some(&prior.transition_id)
                        || transition.from_state != Some(prior.to_state)
                        || !prior.to_state.allows(transition.to_state)
                        || transition.recorded_at <= prior.recorded_at =>
                {
                    return Err(RegistryError::Campaign("transition order"));
                }
                Some(_) => {}
            }

            if transition.to_state == CampaignStateV1::EnrollmentFrozen {
                let commitment = transition
                    .frozen_commitment_digest
                    .as_ref()
                    .ok_or(RegistryError::Campaign("missing frozen commitment"))?;
                frozen = Some(commitment);
            } else if frozen.is_some() && transition.frozen_commitment_digest.as_ref() != frozen {
                return Err(RegistryError::Campaign("frozen commitment mutation"));
            } else if frozen.is_none() && transition.frozen_commitment_digest.is_some() {
                return Err(RegistryError::Campaign("premature frozen commitment"));
            }

            let revises = transition.to_state == CampaignStateV1::ReviseAsNewCampaign;
            if revises != transition.successor_campaign_id.is_some()
                || transition.successor_campaign_id.as_ref() == Some(&self.campaign_id)
            {
                return Err(RegistryError::Campaign("successor campaign"));
            }
            previous = Some(transition);
        }
        super::validate::validate_sha256_public(&self.lifecycle_digest, "lifecycleDigest")?;
        if digest_bytes(&canonical_bytes(&self.digest_material())?)? != self.lifecycle_digest {
            return Err(RegistryError::Campaign("digest mismatch"));
        }
        Ok(())
    }
}
