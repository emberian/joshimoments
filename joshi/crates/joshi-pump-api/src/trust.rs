//! Explicit, versioned schema-trust and credential-path decisions over exact response bytes.
//!
//! A source-edge crate may not silently trust a provider schema. Every acquisition whose bytes
//! reach a durable assertion must carry one recorded decision: the observed structural fingerprint
//! was either matched against a reviewed schema and promoted, or refused with a reason code. The
//! reviewed schema carries the exact shape it reviewed, so a fingerprint cannot be pinned without
//! writing down what was looked at, and provider drift refuses automatically.
//!
//! This module never reads, holds, or describes credential material. It records only whether an
//! authenticated path was taken, and if not, why.

use std::collections::BTreeSet;

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use thiserror::Error;

use crate::ROUTE_CATALOG;
use crate::catalog::{AccessClass, RouteSpec};
use crate::client::sha256;
use crate::model::{Acquisition, BodyCapture};
use crate::normalize::{fingerprint_of_shape, reject_duplicate_keys, schema_fingerprint};

pub const SCHEMA_REVIEW_V1: &str = "joshi.pump_api.schema_review.v1";
pub const SCHEMA_TRUST_DECISION_V1: &str = "joshi.pump_api.schema_trust_decision.v1";
pub const SESSION_PATH_NOTE_V1: &str = "joshi.pump_api.session_path_note.v1";

const MAX_REVIEW_BYTES: usize = 256 * 1024;

#[derive(Error, Debug)]
pub enum TrustError {
    #[error("invalid reviewed-schema JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("reviewed schema exceeds {MAX_REVIEW_BYTES} bytes")]
    ReviewTooLarge,
    #[error("duplicate object key {0:?} in reviewed schema")]
    DuplicateKey(String),
    #[error("reviewed schema contract/version is not {SCHEMA_REVIEW_V1}")]
    ReviewContract,
    #[error("reviewed schema is internally inconsistent: {0}")]
    ReviewInconsistent(&'static str),
    #[error("acquisition route {0:?} is not in the pinned catalog")]
    UnknownRoute(String),
    #[error("decision timestamp is not a canonical six-digit UTC instant")]
    DecidedAt,
}

/// Promotion state of one exact observed structural schema.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SchemaTrustOutcome {
    Promoted,
    Refused,
}

/// A human-reviewed schema. The reviewed shape is retained verbatim so that the pinned
/// fingerprint is recomputable from what the reviewer actually read.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SchemaReviewV1 {
    pub contract: String,
    pub schema_version: String,
    pub review_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub schema_fingerprint: String,
    pub reviewed_shape: Vec<String>,
    pub reviewer: String,
    pub reviewed_at: String,
    pub decision: SchemaTrustOutcome,
    pub rationale: String,
}

impl SchemaReviewV1 {
    /// Strictly decode a bounded reviewed-schema artifact.
    ///
    /// # Errors
    ///
    /// Returns an error for oversized input, duplicate keys, unknown fields, the wrong contract,
    /// or a reviewed shape that does not hash to the declared fingerprint.
    pub fn from_slice(bytes: &[u8]) -> Result<Self, TrustError> {
        if bytes.len() > MAX_REVIEW_BYTES {
            return Err(TrustError::ReviewTooLarge);
        }
        reject_duplicate_keys(bytes).map_err(|error| match error {
            crate::normalize::NormalizeError::DuplicateKey(key) => TrustError::DuplicateKey(key),
            crate::normalize::NormalizeError::Json(error) => TrustError::Json(error),
            _ => TrustError::ReviewContract,
        })?;
        let review: Self = serde_json::from_slice(bytes)?;
        review.validate()?;
        Ok(review)
    }

    /// Recompute the fingerprint implied by the reviewed shape lines.
    #[must_use]
    pub fn shape_digest(&self) -> String {
        fingerprint_of_shape(&self.reviewed_shape)
    }

    /// Check every internal invariant of a reviewed schema.
    ///
    /// # Errors
    ///
    /// Returns an error for the wrong contract or a shape that does not hash to the declared
    /// fingerprint.
    pub fn validate(&self) -> Result<(), TrustError> {
        if self.contract != SCHEMA_REVIEW_V1 || self.schema_version != "1" {
            return Err(TrustError::ReviewContract);
        }
        if self.review_id.trim().is_empty() || self.reviewer.trim().is_empty() {
            return Err(TrustError::ReviewInconsistent(
                "review id and reviewer must both be present",
            ));
        }
        if self.reviewed_shape.is_empty() {
            return Err(TrustError::ReviewInconsistent(
                "a reviewed schema must retain the shape it reviewed",
            ));
        }
        let unique = self.reviewed_shape.iter().collect::<BTreeSet<_>>();
        if unique.len() != self.reviewed_shape.len() {
            return Err(TrustError::ReviewInconsistent(
                "reviewed shape contains duplicate lines",
            ));
        }
        if self.shape_digest() != self.schema_fingerprint {
            return Err(TrustError::ReviewInconsistent(
                "reviewed shape does not hash to the declared schema fingerprint",
            ));
        }
        Ok(())
    }
}

/// One recorded decision about whether an exact observed schema may produce trusted records.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SchemaTrustDecisionV1 {
    pub contract: String,
    pub schema_version: String,
    pub decision_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub acquisition_id: String,
    pub http_status: Option<String>,
    pub body_blob_id: Option<String>,
    pub observed_schema_fingerprint: Option<String>,
    pub outcome: SchemaTrustOutcome,
    pub reason_code: String,
    pub detail: String,
    pub review_id: Option<String>,
    pub review_shape_digest: Option<String>,
    pub decided_at: String,
}

impl SchemaTrustDecisionV1 {
    #[must_use]
    pub fn promoted(&self) -> bool {
        self.outcome == SchemaTrustOutcome::Promoted
    }

    /// Digest over the exact canonical decision bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if the decision cannot be serialized.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, TrustError> {
        Ok(serde_json::to_vec(self)?)
    }
}

/// Decide whether one acquisition's exact bytes may be normalized into trusted records.
///
/// The decision is total: every acquisition receives either a promotion bound to a named review,
/// or a refusal with a reason code. Absence of a review is a refusal, never a default trust.
///
/// # Errors
///
/// Returns an error only when the acquisition names a route outside the pinned catalog or the
/// decision timestamp is not canonical. Provider-side problems become refusals, not errors.
#[allow(clippy::too_many_lines)] // Every refusal branch and its reason code stay auditable together.
pub fn decide_schema_trust(
    acquisition: &Acquisition,
    review: Option<&SchemaReviewV1>,
    decided_at: &str,
) -> Result<SchemaTrustDecisionV1, TrustError> {
    let route = acquisition
        .route_id
        .parse::<crate::catalog::RouteId>()
        .map_err(|_| TrustError::UnknownRoute(acquisition.route_id.clone()))?;
    if !is_canonical_utc(decided_at) {
        return Err(TrustError::DecidedAt);
    }
    let mut decision = SchemaTrustDecisionV1 {
        contract: SCHEMA_TRUST_DECISION_V1.to_owned(),
        schema_version: "1".to_owned(),
        decision_id: format!("decision:pump-schema-trust:{}", acquisition.acquisition_id),
        route_id: route.to_string(),
        catalog_version: acquisition.catalog_version.clone(),
        acquisition_id: acquisition.acquisition_id.clone(),
        http_status: acquisition.http_status.map(|status| status.to_string()),
        body_blob_id: acquisition.body.blob_id().map(str::to_owned),
        observed_schema_fingerprint: None,
        outcome: SchemaTrustOutcome::Refused,
        reason_code: "refused_unclassified".to_owned(),
        detail: String::new(),
        review_id: review.map(|value| value.review_id.clone()),
        review_shape_digest: review.map(SchemaReviewV1::shape_digest),
        decided_at: decided_at.to_owned(),
    };

    if acquisition.catalog_version != ROUTE_CATALOG {
        return Ok(refuse(
            decision,
            "refused_acquisition_catalog_version_mismatch",
            "the acquisition was taken under a different pinned route catalog",
        ));
    }
    let BodyCapture::Exact {
        bytes_base64,
        byte_length,
        blob_id,
        ..
    } = &acquisition.body
    else {
        return Ok(refuse(
            decision,
            "refused_non_exact_body",
            "only a complete exact response body can be schema-reviewed",
        ));
    };
    if !acquisition
        .http_status
        .is_some_and(|status| (200..300).contains(&status))
    {
        return Ok(refuse(
            decision,
            "refused_non_success_status",
            "a non-2xx response is retained as bytes but never promoted as a product schema",
        ));
    }
    let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(bytes_base64) else {
        return Ok(refuse(
            decision,
            "refused_undecodable_body",
            "the retained body base64 did not decode",
        ));
    };
    if byte_length != &bytes.len().to_string() || blob_id != &sha256(&bytes) {
        return Ok(refuse(
            decision,
            "refused_body_identity_mismatch",
            "declared body length or digest does not match the retained bytes",
        ));
    }
    if reject_duplicate_keys(&bytes).is_err() {
        return Ok(refuse(
            decision,
            "refused_duplicate_object_key",
            "the response body contains a duplicate object key",
        ));
    }
    let Ok(raw) = serde_json::from_slice::<Box<RawValue>>(&bytes) else {
        return Ok(refuse(
            decision,
            "refused_unparseable_json",
            "the response body is not well-formed JSON",
        ));
    };
    let Ok(observed) = schema_fingerprint(&raw) else {
        return Ok(refuse(
            decision,
            "refused_unfingerprintable_body",
            "the response body exceeds the structural fingerprint limits",
        ));
    };
    decision.observed_schema_fingerprint = Some(observed.clone());

    let Some(review) = review else {
        return Ok(refuse(
            decision,
            "refused_no_review_for_route",
            "no reviewed schema was supplied; exact bytes are retained and quarantined",
        ));
    };
    if review.validate().is_err() {
        return Ok(refuse(
            decision,
            "refused_review_internally_inconsistent",
            "the supplied reviewed schema failed its own shape/fingerprint closure",
        ));
    }
    if review.route_id != route.to_string() {
        return Ok(refuse(
            decision,
            "refused_review_route_mismatch",
            "the reviewed schema was reviewed for a different route",
        ));
    }
    if review.catalog_version != acquisition.catalog_version {
        return Ok(refuse(
            decision,
            "refused_review_catalog_version_mismatch",
            "the reviewed schema was reviewed under a different pinned route catalog",
        ));
    }
    if review.decision == SchemaTrustOutcome::Refused {
        return Ok(refuse(
            decision,
            "refused_reviewer_refused_this_schema",
            "the reviewer explicitly refused this schema",
        ));
    }
    if review.schema_fingerprint != observed {
        return Ok(refuse(
            decision,
            "refused_observed_fingerprint_not_reviewed",
            "the provider response shape differs from the reviewed shape",
        ));
    }
    decision.outcome = SchemaTrustOutcome::Promoted;
    "promoted_reviewed_schema_fingerprint_match".clone_into(&mut decision.reason_code);
    "the observed structural schema is byte-identical to the named reviewed shape"
        .clone_into(&mut decision.detail);
    Ok(decision)
}

fn refuse(
    mut decision: SchemaTrustDecisionV1,
    reason_code: &str,
    detail: &str,
) -> SchemaTrustDecisionV1 {
    decision.outcome = SchemaTrustOutcome::Refused;
    reason_code.clone_into(&mut decision.reason_code);
    detail.clone_into(&mut decision.detail);
    decision
}

/// Whether an authenticated product read was actually performed on this run.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthenticatedPathDecision {
    /// An authenticated session was presented and the provider accepted it.
    Performed,
    /// No authenticated read was attempted, for the recorded reason.
    NotPerformed,
}

/// Whether the credential path was exercised on one acquisition, and if not, why not.
///
/// This record exists so that "we read a public route" can never be mistaken later for "we read an
/// authenticated route". It names no credential and carries no secret material.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SessionPathNoteV1 {
    pub contract: String,
    pub schema_version: String,
    pub note_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub route_access_class: String,
    pub route_requires_session: bool,
    pub observed_session_class: String,
    pub auth_disposition: crate::promotion::AuthDisposition,
    pub authenticated_path: AuthenticatedPathDecision,
    pub reason_code: String,
    pub detail: String,
    pub decided_at: String,
}

/// Derive the credential-path note for one acquisition from the acquisition itself.
///
/// The observed session class and HTTP status come from the acquisition; the reason and detail
/// are supplied by the operator of the run and must describe what actually happened.
///
/// # Errors
///
/// Returns an error when the acquisition names a route outside the pinned catalog or the decision
/// timestamp is not canonical.
pub fn session_path_note(
    acquisition: &Acquisition,
    authenticated_path: AuthenticatedPathDecision,
    reason_code: &str,
    detail: &str,
    decided_at: &str,
) -> Result<SessionPathNoteV1, TrustError> {
    let route = acquisition
        .route_id
        .parse::<crate::catalog::RouteId>()
        .map_err(|_| TrustError::UnknownRoute(acquisition.route_id.clone()))?;
    if !is_canonical_utc(decided_at) {
        return Err(TrustError::DecidedAt);
    }
    let spec = RouteSpec::for_id(route);
    let authenticated_session = acquisition.session_class.starts_with("authenticated:");
    let auth_disposition = match acquisition.http_status {
        Some(401 | 403) => crate::promotion::AuthDisposition::SessionRejected,
        Some(status) if (200..300).contains(&status) && authenticated_session => {
            crate::promotion::AuthDisposition::OrdinarySessionAccepted
        }
        Some(status)
            if (200..300).contains(&status)
                && spec.access != AccessClass::AuthenticatedUserSession =>
        {
            crate::promotion::AuthDisposition::NotRequiredPublic
        }
        _ => crate::promotion::AuthDisposition::Unknown,
    };
    Ok(SessionPathNoteV1 {
        contract: SESSION_PATH_NOTE_V1.to_owned(),
        schema_version: "1".to_owned(),
        note_id: format!("note:pump-session-path:{}", acquisition.acquisition_id),
        route_id: route.to_string(),
        catalog_version: acquisition.catalog_version.clone(),
        route_access_class: spec.access.to_string(),
        route_requires_session: spec.requires_session(),
        observed_session_class: acquisition.session_class.clone(),
        auth_disposition,
        authenticated_path,
        reason_code: reason_code.to_owned(),
        detail: detail.to_owned(),
        decided_at: decided_at.to_owned(),
    })
}

fn is_canonical_utc(value: &str) -> bool {
    time::PrimitiveDateTime::parse(
        value,
        time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ),
    )
    .is_ok()
}
