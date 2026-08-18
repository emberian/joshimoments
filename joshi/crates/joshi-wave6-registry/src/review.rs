//! Exact caller-fed research-disposition contract with no identity or approval authority.

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use serde::{Deserialize, Serialize};

use crate::{
    RegistryError, Result, SemanticCeilingV1, ValidatedResearchProposal,
    canonical::decode_canonical, digest_bytes,
};

/// One disposition word admitted by the Python research-desk ledger.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResearchDispositionKindV1 {
    Accept,
    Reject,
    Hold,
    Supersede,
}

/// Exact Python disposition bytes. `human_id` remains an unverified caller string.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResearchDispositionV1 {
    pub decided_at: UtcTimestamp,
    pub disposition: ResearchDispositionKindV1,
    pub disposition_id: StableString,
    pub human_id: StableString,
    pub proposal_id: StableString,
    pub reason: String,
}

/// Strictly parsed fixture disposition bound to one exact proposal.
#[derive(Clone, Debug)]
pub struct ValidatedResearchDisposition {
    value: ResearchDispositionV1,
    exact_bytes: Vec<u8>,
    content_digest: ValueDigest,
}

impl ValidatedResearchDisposition {
    #[must_use]
    pub const fn value(&self) -> &ResearchDispositionV1 {
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

    /// Exact parsing never authenticates the claimed human identity.
    #[must_use]
    pub const fn human_identity_verified(&self) -> bool {
        false
    }

    /// A fixture disposition never grants approval or execution authority.
    #[must_use]
    pub const fn approval_or_execution_authority(&self) -> bool {
        false
    }

    #[must_use]
    pub const fn semantic_ceiling(&self) -> SemanticCeilingV1 {
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    }
}

#[derive(Serialize)]
struct DispositionContent<'a> {
    decided_at: UtcTimestamp,
    disposition: ResearchDispositionKindV1,
    human_id: &'a StableString,
    proposal_id: &'a StableString,
    reason: &'a str,
}

/// Parses exact canonical disposition bytes and binds them to an exact proposal.
///
/// # Errors
///
/// Refuses unknown or noncanonical fields, changed content identity, blank/control/oversized
/// reasons, a foreign proposal, or a disposition clock before proposal creation.
pub fn parse_research_disposition_exact(
    bytes: &[u8],
    proposal: &ValidatedResearchProposal,
) -> Result<ValidatedResearchDisposition> {
    let value: ResearchDispositionV1 = decode_canonical(bytes)?;
    validate_reason(&value.reason)?;
    if value.proposal_id != proposal.value().proposal_id
        || value.decided_at < proposal.value().created_at
    {
        return Err(RegistryError::Review("proposal binding or chronology"));
    }
    let content = disposition_content(&value);
    let digest = digest_bytes(&serde_json::to_vec(&content)?)?;
    let raw = digest
        .as_str()
        .strip_prefix("sha256:")
        .ok_or(RegistryError::Review("generated disposition digest"))?;
    let expected_id = format!("human-disposition-{}", &raw[..32]);
    if value.disposition_id.as_str() != expected_id {
        return Err(RegistryError::Review("disposition content identity"));
    }
    Ok(ValidatedResearchDisposition {
        value,
        exact_bytes: bytes.to_vec(),
        content_digest: digest_bytes(bytes)?,
    })
}

fn disposition_content(value: &ResearchDispositionV1) -> DispositionContent<'_> {
    DispositionContent {
        decided_at: value.decided_at,
        disposition: value.disposition,
        human_id: &value.human_id,
        proposal_id: &value.proposal_id,
        reason: &value.reason,
    }
}

fn validate_reason(reason: &str) -> Result<()> {
    if reason.is_empty()
        || reason != reason.trim()
        || reason.len() > 2_000
        || reason
            .chars()
            .any(|character| character.is_control() || character == '\u{7f}')
    {
        return Err(RegistryError::Review("disposition reason"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{canonical_bytes, parse_research_proposal_exact};

    const PROPOSAL: &[u8] = include_bytes!("../../../fixtures/wave6/research_proposal_v1.json");
    const DISPOSITION: &[u8] =
        include_bytes!("../../../fixtures/wave6/research_disposition_v1.json");

    #[test]
    fn exact_python_disposition_cross_parses_without_human_or_execution_authority() {
        let proposal = parse_research_proposal_exact(PROPOSAL).expect("proposal");
        let parsed = parse_research_disposition_exact(DISPOSITION, &proposal).expect("disposition");
        assert_eq!(
            parsed.value().disposition_id.as_str(),
            "human-disposition-f203c6ccee72320de0adf61e805f8e65"
        );
        assert_eq!(
            parsed.content_digest().as_str(),
            "sha256:a43c7d584056f4dc536f61dbbb80ee670c1797412f9d8d32024d09b250d42577"
        );
        assert!(!parsed.human_identity_verified());
        assert!(!parsed.approval_or_execution_authority());
        assert_eq!(
            parsed.semantic_ceiling(),
            SemanticCeilingV1::UnverifiedSemanticFixtureOnly
        );
    }

    #[test]
    fn disposition_refuses_foreign_proposal_backdating_and_identity_substitution() {
        let proposal = parse_research_proposal_exact(PROPOSAL).expect("proposal");
        let parsed = parse_research_disposition_exact(DISPOSITION, &proposal).expect("disposition");

        let mut foreign = parsed.value().clone();
        foreign.proposal_id = StableString::new("research-proposal-foreign").expect("foreign");
        assert!(
            parse_research_disposition_exact(
                &canonical_bytes(&foreign).expect("foreign bytes"),
                &proposal
            )
            .is_err()
        );

        let mut backdated = parsed.value().clone();
        backdated.decided_at = "2026-08-18T00:11:59.999999Z"
            .parse()
            .expect("backdated time");
        let material = disposition_content(&backdated);
        let digest = digest_bytes(&serde_json::to_vec(&material).expect("material")).expect("hash");
        backdated.disposition_id =
            StableString::new(format!("human-disposition-{}", &digest.as_str()[7..39]))
                .expect("backdated ID");
        assert!(
            parse_research_disposition_exact(
                &canonical_bytes(&backdated).expect("backdated bytes"),
                &proposal
            )
            .is_err()
        );

        let mut changed = parsed.value().clone();
        changed.reason.push_str(" changed");
        assert!(
            parse_research_disposition_exact(
                &canonical_bytes(&changed).expect("changed bytes"),
                &proposal
            )
            .is_err()
        );
    }
}
