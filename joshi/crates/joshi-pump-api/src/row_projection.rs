//! A schema gate that reviews ROWS rather than whole documents.
//!
//! [`crate::trust::decide_schema_trust`] pins one digest over an entire response. That works for a
//! route whose document is one record, or whose rows are homogeneous, and it is what governs
//! `coin_exact`, `candles` and `trades`. It cannot govern a discovery feed, and the reason is a
//! measurement rather than an opinion: [`crate::normalize::schema_fingerprint`] collapses every
//! array element onto the single pointer `$/*`, so a page's digest is the UNION of the key sets of
//! whichever coins happened to land in it. Eleven reads of `/coins` on 2026-08-22 produced eight
//! distinct fingerprints, and two byte-identical requests ninety-seven seconds apart differed only
//! because one page contained a coin with a community takeover recorded. That gate would admit
//! roughly one read in eight while reporting the other seven as provider drift.
//!
//! This module narrows instead of widening. A review names a REQUIRED leaf set that every row must
//! carry, and a CLOSED optional leaf set that a row may carry. Anything else refuses. It therefore
//! stops firing on row heterogeneity, which is not drift, and keeps firing on a renamed, retyped,
//! removed or newly-added provider field, which is.
//!
//! Three refusals it must make, in the words of the failures that motivated them:
//!
//!   * A row carrying an unknown leaf REFUSES. It is never silently projected away. Silent
//!     dropping is exactly how `ath_market_cap` and `volume_1h_usd` — the only within-lifetime
//!     peak and the only realised-flow number this whole catalog exposes — went missing from three
//!     routes for three days without one test going red.
//!   * A row missing a required leaf REFUSES, and the refusal names the row ordinal and the leaf.
//!   * A row whose leaf carries an unreviewed wire type REFUSES, likewise named.
//!
//! The optional set is closed and enumerated. Adding a leaf to it is a review act performed by a
//! person writing down what they looked at; it is never inferred from a body that happened to
//! arrive. And the whole-document fingerprint is still recorded on every decision, because it
//! remains a perfectly good drift SIGNAL even though it was never a usable GATE.

use std::collections::{BTreeMap, BTreeSet};

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

use crate::ROUTE_CATALOG;
use crate::catalog::RouteId;
use crate::client::sha256;
use crate::model::{Acquisition, BodyCapture};
use crate::normalize::{
    fingerprint_of_shape, records, reject_duplicate_keys, schema_fingerprint, schema_shape,
};
use crate::trust::{SchemaTrustDecisionV1, SchemaTrustOutcome, TrustError};

pub const ROW_PROJECTION_REVIEW_V1: &str = "joshi.pump_api.row_projection_review.v1";

const MAX_REVIEW_BYTES: usize = 256 * 1024;
const WIRE_TYPES: [&str; 6] = ["array", "boolean", "null", "number", "object", "string"];

/// A human-reviewed row projection: what every row must carry, and what a row is allowed to carry.
///
/// Both leaf sets are written in the same `pointer:type` vocabulary that
/// [`crate::normalize::schema_shape`] emits, with the ROW as the root. A flat coin record's mint
/// is therefore `$/mint:string`. A leaf that legitimately arrives under two wire types is two
/// lines, and a nullable leaf is one line plus `…:null`; there is no way to say "any type".
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RowProjectionReviewV1 {
    pub contract: String,
    pub schema_version: String,
    pub review_id: String,
    pub route_id: String,
    pub catalog_version: String,
    /// Present on every row of this route, in the reviewed wire type.
    pub required_leaves: Vec<String>,
    /// Permitted on a row of this route. Closed: absence from both lists is a refusal.
    pub optional_leaves: Vec<String>,
    pub reviewer: String,
    pub reviewed_at: String,
    pub decision: SchemaTrustOutcome,
    pub rationale: String,
}

impl RowProjectionReviewV1 {
    /// Strictly decode a bounded row-projection review.
    ///
    /// # Errors
    ///
    /// Returns an error for oversized input, duplicate keys, unknown fields, the wrong contract,
    /// or a leaf listing that is not internally consistent.
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

    /// Digest over the exact leaf listing that was reviewed, required and optional kept apart so
    /// that promoting a leaf from optional to required cannot leave the digest unchanged.
    #[must_use]
    pub fn leaf_digest(&self) -> String {
        let mut lines = Vec::new();
        lines.extend(self.required_leaves.iter().map(|leaf| format!("R {leaf}")));
        lines.extend(self.optional_leaves.iter().map(|leaf| format!("O {leaf}")));
        fingerprint_of_shape(&lines)
    }

    /// Check every internal invariant of a row-projection review.
    ///
    /// # Errors
    ///
    /// Returns an error for the wrong contract, an empty or duplicated leaf listing, a leaf line
    /// that is not `pointer:type`, an unknown wire type, or a leaf named both required and
    /// optional.
    pub fn validate(&self) -> Result<(), TrustError> {
        if self.contract != ROW_PROJECTION_REVIEW_V1 || self.schema_version != "1" {
            return Err(TrustError::ReviewContract);
        }
        if self.review_id.trim().is_empty() || self.reviewer.trim().is_empty() {
            return Err(TrustError::ReviewInconsistent(
                "review id and reviewer must both be present",
            ));
        }
        if self.required_leaves.is_empty() {
            return Err(TrustError::ReviewInconsistent(
                "a row projection with no required leaf certifies nothing about any row",
            ));
        }
        let mut all = BTreeSet::new();
        for leaf in self.required_leaves.iter().chain(&self.optional_leaves) {
            let (pointer, wire) = split_leaf(leaf).ok_or(TrustError::ReviewInconsistent(
                "every leaf must be written as `pointer:type`",
            ))?;
            if !WIRE_TYPES.contains(&wire) {
                return Err(TrustError::ReviewInconsistent(
                    "leaf wire type must be one of array, boolean, null, number, object, string",
                ));
            }
            if !pointer.starts_with("$/") {
                return Err(TrustError::ReviewInconsistent(
                    "a leaf pointer is relative to the row, so it must begin with `$/`",
                ));
            }
            if !all.insert(leaf.clone()) {
                return Err(TrustError::ReviewInconsistent(
                    "the same leaf line appears twice in the reviewed projection",
                ));
            }
        }
        let required = pointers(&self.required_leaves);
        let optional = pointers(&self.optional_leaves);
        if required.intersection(&optional).next().is_some() {
            return Err(TrustError::ReviewInconsistent(
                "a leaf cannot be both required on every row and optional on a row",
            ));
        }
        // A leaf may only be REQUIRED if the normalizer actually reads it. Requiring an unread
        // field buys nothing and costs a refusal every time the provider omits it on some rare
        // row — which is how a fail-closed gate turns into noise a reader learns to wave through.
        // Requiring a field the projection DOES consume is what makes a refusal mean that
        // something we depend on went missing. Anything unread still has to be in the closed
        // optional set, so an unreviewed leaf still refuses.
        let Ok(route) = self.route_id.parse::<RouteId>() else {
            return Err(TrustError::ReviewInconsistent(
                "the reviewed route is not in the pinned catalog",
            ));
        };
        let read = crate::normalize::extracted_fields(route);
        for pointer in &required {
            let head = pointer
                .trim_start_matches("$/")
                .split('/')
                .next()
                .unwrap_or_default();
            if !read.contains(&head) {
                return Err(TrustError::ReviewInconsistent(
                    "a leaf may only be required if the normalizer reads it; anything else                      belongs in the closed optional set",
                ));
            }
        }
        Ok(())
    }

    fn required_pointers(&self) -> BTreeSet<&str> {
        pointers(&self.required_leaves)
    }

    fn known_pointers(&self) -> BTreeSet<&str> {
        let mut set = pointers(&self.required_leaves);
        set.extend(pointers(&self.optional_leaves));
        set
    }

    fn known_lines(&self) -> BTreeSet<&str> {
        self.required_leaves
            .iter()
            .chain(&self.optional_leaves)
            .map(String::as_str)
            .collect()
    }
}

fn split_leaf(leaf: &str) -> Option<(&str, &str)> {
    let (pointer, wire) = leaf.rsplit_once(':')?;
    (!pointer.is_empty() && !wire.is_empty()).then_some((pointer, wire))
}

fn pointers(leaves: &[String]) -> BTreeSet<&str> {
    leaves
        .iter()
        .filter_map(|leaf| split_leaf(leaf).map(|(pointer, _)| pointer))
        .collect()
}

/// Decide whether one collection acquisition's rows may be normalized into trusted records.
///
/// The decision is total in the same way [`crate::trust::decide_schema_trust`] is: every
/// acquisition receives either a promotion bound to a named review, or a refusal with a reason
/// code. The whole-document fingerprint is recorded on both outcomes as an observation, never as
/// the thing being gated on.
///
/// # Errors
///
/// Returns an error only when the acquisition names a route outside the pinned catalog or the
/// decision timestamp is not canonical. Provider-side problems become refusals, not errors.
#[allow(clippy::too_many_lines)] // Every refusal branch and its reason code stay auditable together.
pub fn decide_row_projection_trust(
    acquisition: &Acquisition,
    review: Option<&RowProjectionReviewV1>,
    decided_at: &str,
) -> Result<SchemaTrustDecisionV1, TrustError> {
    let route = acquisition
        .route_id
        .parse::<RouteId>()
        .map_err(|_| TrustError::UnknownRoute(acquisition.route_id.clone()))?;
    if !crate::trust::is_canonical_utc(decided_at) {
        return Err(TrustError::DecidedAt);
    }
    let mut decision = SchemaTrustDecisionV1 {
        contract: crate::trust::SCHEMA_TRUST_DECISION_V1.to_owned(),
        schema_version: "1".to_owned(),
        decision_id: format!(
            "decision:pump-row-projection:{}",
            acquisition.acquisition_id
        ),
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
        review_shape_digest: review.map(RowProjectionReviewV1::leaf_digest),
        decided_at: decided_at.to_owned(),
    };

    if acquisition.catalog_version != ROUTE_CATALOG {
        return Ok(refuse(
            decision,
            "refused_acquisition_catalog_version_mismatch",
            "the acquisition was taken under a different pinned route catalog".to_owned(),
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
            "only a complete exact response body can be row-reviewed".to_owned(),
        ));
    };
    if !acquisition
        .http_status
        .is_some_and(|status| (200..300).contains(&status))
    {
        return Ok(refuse(
            decision,
            "refused_non_success_status",
            "a non-2xx response is retained as bytes but never promoted as a product schema"
                .to_owned(),
        ));
    }
    let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(bytes_base64) else {
        return Ok(refuse(
            decision,
            "refused_undecodable_body",
            "the retained body base64 did not decode".to_owned(),
        ));
    };
    if byte_length != &bytes.len().to_string() || blob_id != &sha256(&bytes) {
        return Ok(refuse(
            decision,
            "refused_body_identity_mismatch",
            "declared body length or digest does not match the retained bytes".to_owned(),
        ));
    }
    if reject_duplicate_keys(&bytes).is_err() {
        return Ok(refuse(
            decision,
            "refused_duplicate_object_key",
            "the response body contains a duplicate object key".to_owned(),
        ));
    }
    let Ok(raw) = serde_json::from_slice::<Box<RawValue>>(&bytes) else {
        return Ok(refuse(
            decision,
            "refused_unparseable_json",
            "the response body is not well-formed JSON".to_owned(),
        ));
    };
    // Recorded on every outcome, gating none of them. It is still the cheapest drift signal we
    // have: a fingerprint that has never been seen before is worth a look even when the rows pass.
    if let Ok(observed) = schema_fingerprint(&raw) {
        decision.observed_schema_fingerprint = Some(observed);
    } else {
        return Ok(refuse(
            decision,
            "refused_unfingerprintable_body",
            "the response body exceeds the structural fingerprint limits".to_owned(),
        ));
    }

    let Some(review) = review else {
        return Ok(refuse(
            decision,
            "refused_no_row_projection_review_for_route",
            "no reviewed row projection was supplied; exact bytes are retained and quarantined"
                .to_owned(),
        ));
    };
    if review.validate().is_err() {
        return Ok(refuse(
            decision,
            "refused_row_projection_review_internally_inconsistent",
            "the supplied row projection failed its own leaf-listing closure".to_owned(),
        ));
    }
    if review.route_id != route.to_string() {
        return Ok(refuse(
            decision,
            "refused_row_projection_review_route_mismatch",
            "the row projection was reviewed for a different route".to_owned(),
        ));
    }
    if review.catalog_version != acquisition.catalog_version {
        return Ok(refuse(
            decision,
            "refused_row_projection_review_catalog_version_mismatch",
            "the row projection was reviewed under a different pinned route catalog".to_owned(),
        ));
    }
    if review.decision == SchemaTrustOutcome::Refused {
        return Ok(refuse(
            decision,
            "refused_reviewer_refused_this_row_projection",
            "the reviewer explicitly refused this row projection".to_owned(),
        ));
    }
    let Ok(rows) = records(route, &raw) else {
        return Ok(refuse(
            decision,
            "refused_container_not_readable",
            "the reviewed container for this route did not yield rows from these bytes".to_owned(),
        ));
    };
    if rows.is_empty() {
        // An empty page is not absence and it is not a certified schema either. `/coins` answers
        // an offset past the end with a bare `[]` under HTTP 200, byte-identical to a filter that
        // matched nothing, so promoting one would certify a row shape from zero rows.
        return Ok(refuse(
            decision,
            "refused_empty_page_has_no_row_to_check",
            "the page carried no row, so nothing was certified; an empty page is never evidence \
             that nothing matched"
                .to_owned(),
        ));
    }
    if let Err((code, detail)) = check_rows(&rows, review) {
        return Ok(refuse(decision, code, detail));
    }
    decision.outcome = SchemaTrustOutcome::Promoted;
    "promoted_reviewed_row_projection".clone_into(&mut decision.reason_code);
    decision.detail = format!(
        "all {} rows carry every required leaf in its reviewed wire type and no leaf outside the \
         closed reviewed set",
        rows.len()
    );
    Ok(decision)
}

fn check_rows(
    rows: &[Box<RawValue>],
    review: &RowProjectionReviewV1,
) -> Result<(), (&'static str, String)> {
    let required = review.required_pointers();
    let known_pointers = review.known_pointers();
    let known_lines = review.known_lines();
    for (ordinal, row) in rows.iter().enumerate() {
        let Ok(shape) = schema_shape(row) else {
            return Err((
                "refused_row_not_fingerprintable",
                format!("row {ordinal} exceeds the structural limits"),
            ));
        };
        if !shape.iter().any(|line| line == "$:object") {
            return Err((
                "refused_row_is_not_an_object",
                format!("row {ordinal} is not a JSON object, so it has no leaves to review"),
            ));
        }
        let mut observed = BTreeMap::new();
        for line in &shape {
            if line == "$:object" {
                continue;
            }
            let Some((pointer, _)) = split_leaf(line) else {
                continue;
            };
            observed.insert(pointer, line.as_str());
        }
        for pointer in &required {
            if !observed.contains_key(pointer) {
                return Err((
                    "refused_row_missing_required_leaf",
                    format!("row {ordinal} is missing required leaf {pointer}"),
                ));
            }
        }
        for (pointer, line) in &observed {
            if known_lines.contains(line) {
                continue;
            }
            if known_pointers.contains(pointer) {
                return Err((
                    "refused_row_leaf_type_not_reviewed",
                    format!(
                        "row {ordinal} carries {line}, which is a reviewed leaf under an unreviewed wire type"
                    ),
                ));
            }
            return Err((
                "refused_row_carries_unreviewed_leaf",
                format!(
                    "row {ordinal} carries {line}, which no reviewer has looked at; it is refused \
                     rather than silently projected away"
                ),
            ));
        }
    }
    Ok(())
}

fn refuse(
    mut decision: SchemaTrustDecisionV1,
    reason_code: &str,
    detail: String,
) -> SchemaTrustDecisionV1 {
    decision.outcome = SchemaTrustOutcome::Refused;
    reason_code.clone_into(&mut decision.reason_code);
    decision.detail = detail;
    decision
}

/// Collect the exact row-leaf listing a body actually carries, split into leaves present on every
/// row and leaves present on some.
///
/// This is reviewer material, not a decision: it is what a person reads before writing a review
/// down. It deliberately returns what was OBSERVED, so a review authored from it covers only
/// pages someone has actually looked at.
///
/// # Errors
///
/// Returns an error for a route outside the catalog, a body that is not readable as rows, or
/// nesting beyond the structural limits.
pub fn observed_row_leaves(
    route: RouteId,
    bytes: &[u8],
) -> Result<(Vec<String>, Vec<String>), crate::normalize::NormalizeError> {
    let raw: Box<RawValue> = serde_json::from_slice(bytes)?;
    let rows = records(route, &raw)?;
    let mut union: BTreeSet<String> = BTreeSet::new();
    let mut intersection: Option<BTreeSet<String>> = None;
    for row in &rows {
        let lines = schema_shape(row)?
            .into_iter()
            .filter(|line| line != "$:object")
            .collect::<BTreeSet<_>>();
        union.extend(lines.iter().cloned());
        intersection = Some(match intersection {
            None => lines,
            Some(previous) => previous.intersection(&lines).cloned().collect(),
        });
    }
    let required = intersection.unwrap_or_default();
    let optional = union.difference(&required).cloned().collect::<Vec<_>>();
    Ok((required.into_iter().collect(), optional))
}
