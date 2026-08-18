use crate::Result;
use joshi_epistemic_book::{
    ClaimDefinitionV1, ClaimOccurrenceV1, ForecastSubmissionV1, ResolvedOccurrencePortV1,
    SubmissionPhaseV1, ValidatedArtifact, validate_claim_occurrence, validate_forecast_submission,
};

/// Caller-owned semantic result. It is immutable and strictly validated, but grants no durable
/// receipt, maturity, blindness proof, score, or ensemble eligibility.
#[derive(Clone, Debug)]
pub struct UnverifiedSemantic<T> {
    artifact: ValidatedArtifact<T>,
}

impl<T> UnverifiedSemantic<T> {
    /// Returns the strictly validated but non-promoting artifact.
    #[must_use]
    pub const fn artifact(&self) -> &ValidatedArtifact<T> {
        &self.artifact
    }
}

/// Public caller DTO for an occurrence semantic preflight.
///
/// `resolved` is deliberately only a caller-owned projection. It is checked for internal
/// consistency by the book, but it is not a store receipt and cannot create durable authority.
#[derive(Clone, Debug)]
pub struct ClaimOccurrencePreflight {
    /// Exact validated definition bytes to which this occurrence must bind.
    pub definition: ValidatedArtifact<ClaimDefinitionV1>,
    /// Candidate frozen occurrence.
    pub occurrence: ClaimOccurrenceV1,
    /// Unverified scene, universe, and capability projection.
    pub resolved: ResolvedOccurrencePortV1,
}

/// Public caller DTO for a first-round semantic preflight.
#[derive(Clone, Debug)]
pub struct FirstRoundSubmissionPreflight {
    /// Exact validated claim definition.
    pub definition: ValidatedArtifact<ClaimDefinitionV1>,
    /// Exact validated (but not durable) occurrence.
    pub occurrence: ValidatedArtifact<ClaimOccurrenceV1>,
    /// Candidate forecast submission.
    pub submission: ForecastSubmissionV1,
}

/// Strictly validates a caller-owned frozen occurrence without promoting it.
///
/// # Errors
///
/// Returns the book's semantic error for invalid identity, capability, frozen-input, authority,
/// or exact B0-clock data. Success is only [`UnverifiedSemantic`].
pub fn preflight_claim_occurrence(
    input: ClaimOccurrencePreflight,
) -> Result<UnverifiedSemantic<ClaimOccurrenceV1>> {
    Ok(UnverifiedSemantic {
        artifact: validate_claim_occurrence(input.occurrence, &input.definition, &input.resolved)?,
    })
}

/// Strictly validates a caller-owned initial forecast without promoting it.
///
/// A first-round phase is required here so that callers cannot present a revision as a sealed
/// submission. Actual mutual blindness still requires a private namespace and visibility receipt.
///
/// # Errors
///
/// Refuses non-first-round, late, wrong-occurrence, non-preregistered, or input-substituting
/// submissions. Success is only [`UnverifiedSemantic`].
pub fn preflight_first_round_submission(
    input: FirstRoundSubmissionPreflight,
) -> Result<UnverifiedSemantic<ForecastSubmissionV1>> {
    if !matches!(input.submission.phase, SubmissionPhaseV1::FirstRound) {
        return Err(crate::EpistemicAdmissionError::FirstRoundNotBlind);
    }
    Ok(UnverifiedSemantic {
        artifact: validate_forecast_submission(
            input.submission,
            &input.definition,
            &input.occurrence,
        )?,
    })
}
