//! One versioned identity/topology claim derived strictly from exact promoted response bytes.
//!
//! A claim is only derivable from a [`crate::normalize::Normalization`] that a reviewed schema
//! already promoted, so the schema-trust decision is load-bearing rather than decorative. Every
//! attribute is copied verbatim out of the provider's own bytes; nothing is computed, defaulted,
//! or filled in, and an absent provider field is simply an absent attribute.

use std::collections::BTreeMap;
use std::str::FromStr as _;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::catalog::RouteId;
use crate::client::sha256;
use crate::model::Acquisition;
use crate::normalize::{Normalization, TaggedScalar};

pub const PRODUCT_IDENTITY_CLAIM_V1: &str = "joshi.pump_api.product_identity_claim.v1";

/// Provider fields that describe *who and what* a coin is, rather than its current price state.
/// `creator`, `name` and `symbol` are the identity half; the rest is program/quote topology.
const COIN_IDENTITY_FIELDS: [&str; 7] = [
    "creator",
    "name",
    "program",
    "protocol",
    "quote_mint",
    "symbol",
    "token_program",
];

#[derive(Error, Debug)]
pub enum IdentityClaimError {
    #[error("acquisition route {0:?} is not in the pinned catalog")]
    UnknownRoute(String),
    #[error("route {0} has no reviewed identity projection in this build")]
    UnsupportedRoute(String),
    #[error("acquisition and normalization describe different occurrences")]
    Mismatch,
    #[error("an identity claim requires a promoted, accepted normalization")]
    NotPromoted,
    #[error("expected exactly one product record, found {0}")]
    RecordCount(usize),
    #[error("the promoted body has no exact string {0:?} to identify the subject")]
    MissingSubject(&'static str),
    #[error("the promoted body carries no reviewed identity attribute")]
    NoAttributes,
    #[error("claim serialization failed: {0}")]
    Json(#[from] serde_json::Error),
}

/// One provider-asserted identity/topology fact about one subject, as of one observation.
///
/// The valid interval of this claim is the observation instant, not the lifetime of the fact:
/// the provider is asserting a current mutable record, and nothing here upgrades that to history.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProductIdentityClaimV1 {
    pub contract: String,
    pub schema_version: String,
    pub claim_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub subject_kind: String,
    pub subject: String,
    /// Exact provider strings, keyed by the provider's own field name.
    pub attributes: BTreeMap<String, String>,
    /// Wire encoding each attribute was retained under, so a numeric lexeme is never mistaken
    /// for a decoded string.
    pub attribute_encodings: BTreeMap<String, String>,
    pub schema_fingerprint: String,
    pub acquisition_id: String,
    pub body_blob_id: String,
    pub exact_row_blob_id: String,
    pub observed_at: String,
    pub claim_digest: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ClaimMaterial<'a> {
    contract: &'a str,
    schema_version: &'a str,
    route_id: &'a str,
    catalog_version: &'a str,
    subject_kind: &'a str,
    subject: &'a str,
    attributes: &'a BTreeMap<String, String>,
    attribute_encodings: &'a BTreeMap<String, String>,
    schema_fingerprint: &'a str,
    acquisition_id: &'a str,
    body_blob_id: &'a str,
    exact_row_blob_id: &'a str,
    observed_at: &'a str,
}

/// Derive the single identity/topology claim carried by one promoted acquisition.
///
/// # Errors
///
/// Returns an error when the route has no reviewed identity projection, the normalization was not
/// promoted, the acquisition and normalization disagree, the subject identifier is missing, or no
/// reviewed identity attribute is present in the provider bytes.
pub fn product_identity_claim(
    acquisition: &Acquisition,
    normalization: &Normalization,
) -> Result<ProductIdentityClaimV1, IdentityClaimError> {
    let route = RouteId::from_str(&acquisition.route_id)
        .map_err(|_| IdentityClaimError::UnknownRoute(acquisition.route_id.clone()))?;
    let (subject_field, subject_kind, identity_fields) = match route {
        RouteId::CoinExact => ("mint", "spl_mint", COIN_IDENTITY_FIELDS),
        other => return Err(IdentityClaimError::UnsupportedRoute(other.to_string())),
    };
    if normalization.acquisition_id != acquisition.acquisition_id
        || normalization.route_id != acquisition.route_id
    {
        return Err(IdentityClaimError::Mismatch);
    }
    if normalization.disposition != "accepted_provider_assertions" {
        return Err(IdentityClaimError::NotPromoted);
    }
    let schema_fingerprint = normalization
        .schema_fingerprint
        .clone()
        .ok_or(IdentityClaimError::NotPromoted)?;
    let body_blob_id = acquisition
        .body
        .blob_id()
        .ok_or(IdentityClaimError::NotPromoted)?
        .to_owned();
    let [record] = normalization.records.as_slice() else {
        return Err(IdentityClaimError::RecordCount(normalization.records.len()));
    };
    let subject = record
        .fields
        .iter()
        .find(|field| field.field == subject_field)
        .and_then(exact_string)
        .ok_or(IdentityClaimError::MissingSubject(subject_field))?;
    let mut attributes = BTreeMap::new();
    let mut attribute_encodings = BTreeMap::new();
    for name in identity_fields {
        let Some(field) = record.fields.iter().find(|field| field.field == name) else {
            continue;
        };
        let Some(value) = field.value.clone() else {
            continue;
        };
        attributes.insert((*name).to_owned(), value);
        attribute_encodings.insert((*name).to_owned(), field.encoding.clone());
    }
    if attributes.is_empty() {
        return Err(IdentityClaimError::NoAttributes);
    }
    let material = ClaimMaterial {
        contract: PRODUCT_IDENTITY_CLAIM_V1,
        schema_version: "1",
        route_id: &acquisition.route_id,
        catalog_version: &acquisition.catalog_version,
        subject_kind,
        subject: &subject,
        attributes: &attributes,
        attribute_encodings: &attribute_encodings,
        schema_fingerprint: &schema_fingerprint,
        acquisition_id: &acquisition.acquisition_id,
        body_blob_id: &body_blob_id,
        exact_row_blob_id: &record.exact_row_blob_id,
        observed_at: &acquisition.clocks.received_at,
    };
    let claim_digest = sha256(&serde_json::to_vec(&material)?);
    Ok(ProductIdentityClaimV1 {
        contract: PRODUCT_IDENTITY_CLAIM_V1.to_owned(),
        schema_version: "1".to_owned(),
        claim_id: format!(
            "claim:pump-product-identity:{}:{}",
            acquisition.acquisition_id,
            claim_digest.trim_start_matches("sha256:")
        ),
        route_id: acquisition.route_id.clone(),
        catalog_version: acquisition.catalog_version.clone(),
        subject_kind: subject_kind.to_owned(),
        subject,
        attributes,
        attribute_encodings,
        schema_fingerprint,
        acquisition_id: acquisition.acquisition_id.clone(),
        body_blob_id,
        exact_row_blob_id: record.exact_row_blob_id.clone(),
        observed_at: acquisition.clocks.received_at.clone(),
        claim_digest,
    })
}

fn exact_string(field: &TaggedScalar) -> Option<String> {
    (field.encoding == "utf8")
        .then(|| field.value.clone())
        .flatten()
        .filter(|value| !value.trim().is_empty())
}
