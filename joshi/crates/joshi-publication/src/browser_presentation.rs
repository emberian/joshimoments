//! Exact, authority-free browser presentation claim for one headed Cockpit V2 publication.
//!
//! This contract is the browser-to-store request waist only. It binds what the browser reports
//! mounting to exact immutable publication/head bytes and their durable commit coordinates. It
//! does not prove pixels were visible, confer a durable receipt, or qualify product use.

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_projection::ProjectionAuthority;
use serde::{Deserialize, Serialize};

use crate::{
    COCKPIT_V2_BROWSER_PRESENTATION_CLAIM_CONTRACT, COCKPIT_V2_BROWSER_PRESENTATION_SCHEMA_VERSION,
    CockpitPublicationId, CockpitV2HeadV1, CockpitV2PublicationV1, PublicationError, digest_json,
    digest_match, sha256_digest, validate_sha256,
};

/// Exact immutable publication coordinates returned by the paired Core open route.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2PresentedPublicationRefV1 {
    pub publication_id: CockpitPublicationId,
    pub publication_digest: ValueDigest,
    pub publication_bytes_digest: ValueDigest,
    pub publication_commit_seq: CommitSeq,
}

/// Exact immutable head coordinates returned by the paired Core open route.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2PresentedHeadRefV1 {
    pub head_digest: ValueDigest,
    pub head_bytes_digest: ValueDigest,
    pub head_commit_seq: CommitSeq,
}

/// Bounded client viewport measurement at the mount callback.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2BrowserViewportV1 {
    pub width_css_px: WireU64,
    pub height_css_px: WireU64,
    /// Device pixel ratio multiplied by 1,000; avoids a floating-point wire value.
    pub device_pixel_ratio_milli: WireU64,
}

/// Browser document visibility at the mount callback.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitV2DocumentVisibility {
    Visible,
    Hidden,
}

/// Explicit limit on what this client-authored claim can establish.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CockpitV2BrowserPresentationCeiling {
    BrowserReportedNotPixelVerified,
}

/// Browser-authored claim that one exact Cockpit V2 body/head was mounted.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CockpitV2BrowserPresentationClaimV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub idempotency_key: StableString,
    pub client_presentation_id: StableString,
    pub browser_page_id: StableString,
    pub presentation_seq: WireU64,
    pub publication: CockpitV2PresentedPublicationRefV1,
    pub head: CockpitV2PresentedHeadRefV1,
    pub source_occurrence_id: StableString,
    pub rendered_subjects: Vec<StableString>,
    pub rendered_subject_count: WireU64,
    pub mounted_at: UtcTimestamp,
    pub client_clock_id: StableString,
    pub monotonic_ns: WireU64,
    pub viewport: CockpitV2BrowserViewportV1,
    pub document_visibility: CockpitV2DocumentVisibility,
    pub document_has_focus: bool,
    pub authority: ProjectionAuthority,
    pub ceiling: CockpitV2BrowserPresentationCeiling,
    pub claim_digest: ValueDigest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ClaimMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    idempotency_key: &'a StableString,
    client_presentation_id: &'a StableString,
    browser_page_id: &'a StableString,
    presentation_seq: WireU64,
    publication: &'a CockpitV2PresentedPublicationRefV1,
    head: &'a CockpitV2PresentedHeadRefV1,
    source_occurrence_id: &'a StableString,
    rendered_subjects: &'a [StableString],
    rendered_subject_count: WireU64,
    mounted_at: UtcTimestamp,
    client_clock_id: &'a StableString,
    monotonic_ns: WireU64,
    viewport: CockpitV2BrowserViewportV1,
    document_visibility: CockpitV2DocumentVisibility,
    document_has_focus: bool,
    authority: ProjectionAuthority,
    ceiling: CockpitV2BrowserPresentationCeiling,
}

impl CockpitV2BrowserPresentationClaimV1 {
    fn material(&self) -> ClaimMaterial<'_> {
        ClaimMaterial {
            contract: &self.contract,
            schema_version: self.schema_version,
            idempotency_key: &self.idempotency_key,
            client_presentation_id: &self.client_presentation_id,
            browser_page_id: &self.browser_page_id,
            presentation_seq: self.presentation_seq,
            publication: &self.publication,
            head: &self.head,
            source_occurrence_id: &self.source_occurrence_id,
            rendered_subjects: &self.rendered_subjects,
            rendered_subject_count: self.rendered_subject_count,
            mounted_at: self.mounted_at,
            client_clock_id: &self.client_clock_id,
            monotonic_ns: self.monotonic_ns,
            viewport: self.viewport,
            document_visibility: self.document_visibility,
            document_has_focus: self.document_has_focus,
            authority: self.authority,
            ceiling: self.ceiling,
        }
    }

    /// Computes the exact claim digest without including the self field.
    ///
    /// # Errors
    ///
    /// Returns an error only if canonical JSON encoding fails.
    pub fn computed_digest(&self) -> Result<ValueDigest, PublicationError> {
        digest_json(&self.material())
    }

    /// Validates canonical shape and the deliberately narrow authority ceiling.
    ///
    /// # Errors
    ///
    /// Refuses wrong contract/authority, zero or unbounded measurements, unordered subjects,
    /// count mismatch, or a forged claim digest.
    pub fn validate(&self) -> Result<(), PublicationError> {
        if self.contract.as_str() != COCKPIT_V2_BROWSER_PRESENTATION_CLAIM_CONTRACT
            || self.schema_version != COCKPIT_V2_BROWSER_PRESENTATION_SCHEMA_VERSION
            || self.authority != ProjectionAuthority::ReadOnlyNoExecution
            || self.ceiling != CockpitV2BrowserPresentationCeiling::BrowserReportedNotPixelVerified
            || self.presentation_seq.get() == 0
            || self.publication.publication_commit_seq.get() == 0
            || self.head.head_commit_seq.get() == 0
            || self.publication.publication_commit_seq >= self.head.head_commit_seq
        {
            return Err(PublicationError::CockpitV2Contract);
        }
        if self.idempotency_key.as_str()
            != format!(
                "browser-presentation:{}:{}",
                self.browser_page_id.as_str(),
                self.presentation_seq.get()
            )
        {
            return Err(PublicationError::CockpitV2Presentation);
        }
        if self.viewport.width_css_px.get() == 0
            || self.viewport.width_css_px.get() > 32_768
            || self.viewport.height_css_px.get() == 0
            || self.viewport.height_css_px.get() > 32_768
            || !(100..=10_000).contains(&self.viewport.device_pixel_ratio_milli.get())
        {
            return Err(PublicationError::CockpitV2Presentation);
        }
        if self
            .rendered_subjects
            .windows(2)
            .any(|window| window[0] >= window[1])
            || self.rendered_subject_count.get()
                != u64::try_from(self.rendered_subjects.len())
                    .map_err(|_| PublicationError::ByteLength)?
        {
            return Err(PublicationError::CockpitV2Ordering);
        }
        for digest in [
            &self.publication.publication_digest,
            &self.publication.publication_bytes_digest,
            &self.head.head_digest,
            &self.head.head_bytes_digest,
            &self.claim_digest,
        ] {
            validate_sha256(digest)?;
        }
        let computed = self.computed_digest()?;
        digest_match(
            "cockpit V2 browser presentation claim",
            &self.claim_digest,
            &computed,
        )
    }

    /// Revalidates the claim against exact store-loaded publication/head bytes and coordinates.
    ///
    /// # Errors
    ///
    /// Refuses any byte, digest, commit, source, rendered-subject, or knowledge-clock mismatch.
    #[allow(clippy::too_many_arguments)]
    pub fn validate_against(
        &self,
        publication: &CockpitV2PublicationV1,
        publication_bytes: &[u8],
        publication_store_commit: CommitSeq,
        head: &CockpitV2HeadV1,
        head_bytes: &[u8],
        head_store_commit: CommitSeq,
        source_occurrence_id: &StableString,
    ) -> Result<(), PublicationError> {
        self.validate()?;
        publication.validate()?;
        head.validate_against(publication)?;
        if publication.canonical_bytes()? != publication_bytes
            || head.canonical_bytes()? != head_bytes
            || self.publication.publication_id != publication.publication_id
            || self.publication.publication_digest != publication.publication_digest
            || self.publication.publication_bytes_digest != sha256_digest(publication_bytes)
            || self.publication.publication_commit_seq != publication_store_commit
            || publication_store_commit != publication.commit_seq
            || self.head.head_digest != head.head_digest
            || self.head.head_bytes_digest != sha256_digest(head_bytes)
            || self.head.head_commit_seq != head_store_commit
            || head_store_commit <= publication_store_commit
            || &self.source_occurrence_id != source_occurrence_id
            || self.rendered_subjects != publication.manifest.rendered_subjects
            || self.mounted_at < publication.manifest.cutoff.knowledge_at
        {
            return Err(PublicationError::CockpitV2Presentation);
        }
        Ok(())
    }

    /// Returns strict canonical request bytes after validation.
    ///
    /// # Errors
    ///
    /// Refuses invalid input or JSON encoding failure.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PublicationError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }
}

/// Strict canonical parser for the browser-to-store request waist.
///
/// # Errors
///
/// Refuses unknown fields, invalid values, noncanonical JSON, or a forged digest.
pub fn parse_cockpit_v2_browser_presentation_claim(
    bytes: &[u8],
) -> Result<CockpitV2BrowserPresentationClaimV1, PublicationError> {
    let claim: CockpitV2BrowserPresentationClaimV1 = serde_json::from_slice(bytes)?;
    if claim.canonical_bytes()? != bytes {
        return Err(PublicationError::CockpitV2Digest);
    }
    Ok(claim)
}
