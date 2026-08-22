//! Strict paired-response measurement and route-promotion evaluation.
//!
//! This module does not acquire a Pump session. It evaluates already captured, exact response
//! bodies. Session occurrence IDs and visible-state fingerprints are non-secret digests supplied
//! by an Ember-present handoff; they are never credentials or evidence of authentication by
//! themselves.

use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr as _;

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use time::{OffsetDateTime, PrimitiveDateTime};

use crate::catalog::RouteId;
use crate::client::sha256;
use crate::model::{Acquisition, BodyCapture, LogicalRequest};
use crate::normalize::{next_cursor, records, reject_duplicate_keys, schema_fingerprint};
use crate::parity::diff_raw;
use crate::projection::{PARITY_REQUEST_FINGERPRINT_CONTRACT, parity_request_projection};

pub const PARITY_INPUT_V2: &str = "joshi.pump_api.parity_input.v2";
pub const PARITY_REPORT_V2: &str = "joshi.pump_api.parity_report.v2";
pub const PROMOTION_RUN_V1: &str = "joshi.pump_api.promotion_run.v1";
pub const PROMOTION_REPORT_V1: &str = "joshi.pump_api.promotion_report.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParitySource {
    PumpCompanion,
    DirectPumpApi,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthDisposition {
    NotRequiredPublic,
    OrdinarySessionAccepted,
    SessionRejected,
    ChallengeOrSignatureRequired,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParityInputV2 {
    pub contract: String,
    pub pair_id: String,
    pub source_acquisition_id: String,
    pub source: ParitySource,
    pub route_id: String,
    pub catalog_version: String,
    pub request_fingerprint: String,
    pub request_fingerprint_contract: String,
    pub request_projection_completeness: String,
    pub visible_filter_fingerprint: String,
    pub cursor_in_fingerprint: Option<String>,
    pub pagination_kind: String,
    pub page_ordinal: String,
    pub session_class: String,
    pub session_occurrence_id: String,
    pub auth_disposition: AuthDisposition,
    pub comparison_boundary: String,
    pub started_at: String,
    pub received_at: String,
    pub http_status: u16,
    pub body_base64: String,
    pub byte_length: String,
    pub blob_id: String,
    /// Optional exact digest of a separately witnessed rendered order. Absence is retained as
    /// uncertainty and never upgraded from provider response order.
    pub rendered_order_digest: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DirectParityHandoff {
    pub pair_id: String,
    pub session_class: String,
    pub session_occurrence_id: String,
    pub auth_disposition: AuthDisposition,
    pub rendered_order_digest: Option<String>,
}

/// Build the direct half of a V2 pair from one exact identity-encoded response acquisition.
///
/// # Errors
///
/// Refuses route/catalog/request disagreement, non-exact or content-encoded bodies, missing status,
/// and invalid non-secret handoff digests. It never reads or accepts session material.
pub fn direct_parity_input(
    acquisition: &Acquisition,
    request: &LogicalRequest,
    handoff: DirectParityHandoff,
) -> Result<ParityInputV2, String> {
    if acquisition.route_id != request.route.to_string() {
        return Err("acquisition/request route mismatch".into());
    }
    let BodyCapture::Exact {
        boundary,
        bytes_base64,
        byte_length,
        blob_id,
        ..
    } = &acquisition.body
    else {
        return Err("direct parity requires one complete exact body".into());
    };
    if boundary != "http_entity_body_post_transfer_decoding_identity_encoding" {
        return Err("direct/browser decoded-body boundary is not proven equivalent".into());
    }
    let projection = parity_request_projection(request).map_err(|error| error.to_string())?;
    let input = ParityInputV2 {
        contract: PARITY_INPUT_V2.into(),
        pair_id: handoff.pair_id,
        source_acquisition_id: acquisition.acquisition_id.clone(),
        source: ParitySource::DirectPumpApi,
        route_id: acquisition.route_id.clone(),
        catalog_version: acquisition.catalog_version.clone(),
        request_fingerprint: projection.request_fingerprint,
        request_fingerprint_contract: PARITY_REQUEST_FINGERPRINT_CONTRACT.into(),
        request_projection_completeness: "complete".into(),
        visible_filter_fingerprint: projection.visible_filter_fingerprint,
        cursor_in_fingerprint: projection.cursor_in_fingerprint,
        pagination_kind: projection.pagination_kind,
        page_ordinal: projection.page_ordinal,
        session_class: handoff.session_class,
        session_occurrence_id: handoff.session_occurrence_id,
        auth_disposition: handoff.auth_disposition,
        comparison_boundary: "fetch_response_decoded_body_bytes".into(),
        started_at: acquisition.clocks.started_at.clone(),
        received_at: acquisition.clocks.received_at.clone(),
        http_status: acquisition
            .http_status
            .ok_or_else(|| "direct parity requires an HTTP status".to_owned())?,
        body_base64: bytes_base64.clone(),
        byte_length: byte_length.clone(),
        blob_id: blob_id.clone(),
        rendered_order_digest: handoff.rendered_order_digest,
    };
    let failures = validate_input(&input, ParitySource::DirectPumpApi, "direct");
    if failures.is_empty() {
        Ok(input)
    } else {
        Err(format!(
            "invalid direct parity input: {}",
            failures.join(",")
        ))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MismatchEvidence {
    pub kind: String,
    pub pointer: Option<String>,
    pub companion_digest: Option<String>,
    pub direct_digest: Option<String>,
    pub detail: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParityReportV2 {
    pub contract: String,
    pub pair_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub request_fingerprint: String,
    pub visible_filter_fingerprint: String,
    pub cursor_in_fingerprint: Option<String>,
    pub page_ordinal: String,
    pub session_class: String,
    pub session_occurrence_id: String,
    pub auth_disposition: AuthDisposition,
    pub companion_source_acquisition_id: String,
    pub direct_source_acquisition_id: String,
    pub disposition: String,
    pub precondition_failures: Vec<String>,
    pub pair_skew_us: Option<String>,
    pub companion_blob_id: String,
    pub direct_blob_id: String,
    pub companion_schema_fingerprint: Option<String>,
    pub direct_schema_fingerprint: Option<String>,
    pub companion_cursor_out_fingerprint: Option<String>,
    pub direct_cursor_out_fingerprint: Option<String>,
    pub ordered_membership_disposition: String,
    pub companion_member_count: Option<String>,
    pub direct_member_count: Option<String>,
    pub pagination_disposition: String,
    pub rendered_order_disposition: String,
    pub mismatches: Vec<MismatchEvidence>,
    pub mismatches_truncated: bool,
}

/// Compare one companion response and one direct response under the exact V2 pairing boundary.
///
/// The result can establish provider-response ordered-membership parity. It establishes rendered
/// product order only when both sides reference the same separately witnessed render-order digest.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn compare_v2(
    companion: &ParityInputV2,
    direct: &ParityInputV2,
    maximum_pair_skew_us: u64,
    maximum_mismatches: usize,
) -> ParityReportV2 {
    let mut failures = validate_input(companion, ParitySource::PumpCompanion, "companion");
    failures.extend(validate_input(
        direct,
        ParitySource::DirectPumpApi,
        "direct",
    ));
    for (name, left, right) in [
        ("pair_id", &companion.pair_id, &direct.pair_id),
        ("route_id", &companion.route_id, &direct.route_id),
        (
            "catalog_version",
            &companion.catalog_version,
            &direct.catalog_version,
        ),
        (
            "request_fingerprint",
            &companion.request_fingerprint,
            &direct.request_fingerprint,
        ),
        (
            "request_fingerprint_contract",
            &companion.request_fingerprint_contract,
            &direct.request_fingerprint_contract,
        ),
        (
            "visible_filter_fingerprint",
            &companion.visible_filter_fingerprint,
            &direct.visible_filter_fingerprint,
        ),
        (
            "pagination_kind",
            &companion.pagination_kind,
            &direct.pagination_kind,
        ),
        (
            "page_ordinal",
            &companion.page_ordinal,
            &direct.page_ordinal,
        ),
        (
            "session_class",
            &companion.session_class,
            &direct.session_class,
        ),
        (
            "session_occurrence_id",
            &companion.session_occurrence_id,
            &direct.session_occurrence_id,
        ),
        (
            "comparison_boundary",
            &companion.comparison_boundary,
            &direct.comparison_boundary,
        ),
    ] {
        if left != right {
            failures.push(name.to_owned());
        }
    }
    if companion.cursor_in_fingerprint != direct.cursor_in_fingerprint {
        failures.push("cursor_in_fingerprint".into());
    }
    if companion.source_acquisition_id == direct.source_acquisition_id {
        failures.push("source_acquisition_occurrences_not_distinct".into());
    }
    if companion.request_projection_completeness != "complete"
        || direct.request_projection_completeness != "complete"
    {
        failures.push("request_projection_incomplete".into());
    }
    if companion.auth_disposition != direct.auth_disposition {
        failures.push("auth_disposition".into());
    }
    if matches!(
        companion.auth_disposition,
        AuthDisposition::SessionRejected | AuthDisposition::ChallengeOrSignatureRequired
    ) {
        failures.push("authenticated_path_stop_condition".into());
    }

    let pair_skew_us = pair_skew(companion, direct);
    match pair_skew_us {
        Some(skew) if skew <= maximum_pair_skew_us => {}
        Some(_) => failures.push("pair_time_boundary".into()),
        None => failures.push("source_time_interval".into()),
    }
    failures.sort();
    failures.dedup();

    let mut report = ParityReportV2 {
        contract: PARITY_REPORT_V2.into(),
        pair_id: companion.pair_id.clone(),
        route_id: companion.route_id.clone(),
        catalog_version: companion.catalog_version.clone(),
        request_fingerprint: companion.request_fingerprint.clone(),
        visible_filter_fingerprint: companion.visible_filter_fingerprint.clone(),
        cursor_in_fingerprint: companion.cursor_in_fingerprint.clone(),
        page_ordinal: companion.page_ordinal.clone(),
        session_class: companion.session_class.clone(),
        session_occurrence_id: companion.session_occurrence_id.clone(),
        auth_disposition: companion.auth_disposition.clone(),
        companion_source_acquisition_id: companion.source_acquisition_id.clone(),
        direct_source_acquisition_id: direct.source_acquisition_id.clone(),
        disposition: "incomparable".into(),
        precondition_failures: failures,
        pair_skew_us: pair_skew_us.map(|value| value.to_string()),
        companion_blob_id: companion.blob_id.clone(),
        direct_blob_id: direct.blob_id.clone(),
        companion_schema_fingerprint: None,
        direct_schema_fingerprint: None,
        companion_cursor_out_fingerprint: None,
        direct_cursor_out_fingerprint: None,
        ordered_membership_disposition: "unavailable".into(),
        companion_member_count: None,
        direct_member_count: None,
        pagination_disposition: "unavailable".into(),
        rendered_order_disposition: rendered_order_disposition(companion, direct),
        mismatches: Vec::new(),
        mismatches_truncated: false,
    };
    if !report.precondition_failures.is_empty() {
        return report;
    }

    let Some(companion_bytes) = verified_bytes(companion) else {
        report
            .precondition_failures
            .push("companion_body_closure".into());
        return report;
    };
    let Some(direct_bytes) = verified_bytes(direct) else {
        report
            .precondition_failures
            .push("direct_body_closure".into());
        return report;
    };
    let Some(companion_raw) = strict_raw(&companion_bytes) else {
        report.disposition = "quarantined_companion_schema_or_json".into();
        mismatch(
            &mut report,
            "schema_drift",
            None,
            Some(&companion.blob_id),
            None,
            "companion body is invalid or has duplicate keys",
            maximum_mismatches,
        );
        return report;
    };
    let Some(direct_raw) = strict_raw(&direct_bytes) else {
        report.disposition = "quarantined_direct_schema_or_json".into();
        mismatch(
            &mut report,
            "schema_drift",
            None,
            None,
            Some(&direct.blob_id),
            "direct body is invalid or has duplicate keys",
            maximum_mismatches,
        );
        return report;
    };
    report.companion_schema_fingerprint = schema_fingerprint(&companion_raw).ok();
    report.direct_schema_fingerprint = schema_fingerprint(&direct_raw).ok();
    if report.companion_schema_fingerprint != report.direct_schema_fingerprint {
        let companion_schema = report.companion_schema_fingerprint.clone();
        let direct_schema = report.direct_schema_fingerprint.clone();
        mismatch(
            &mut report,
            "schema_drift",
            Some("$"),
            companion_schema.as_deref(),
            direct_schema.as_deref(),
            "structural response schemas differ",
            maximum_mismatches,
        );
    }
    let mut value_differences = Vec::new();
    let mut value_differences_truncated = false;
    diff_raw(
        &companion_raw,
        &direct_raw,
        "$",
        &mut value_differences,
        maximum_mismatches.max(1),
        &mut value_differences_truncated,
    );
    for difference in value_differences {
        mismatch(
            &mut report,
            "response_value",
            Some(&difference.pointer),
            Some(&difference.companion_value_digest),
            Some(&difference.direct_value_digest),
            "exact JSON value or presence differs",
            maximum_mismatches,
        );
    }
    report.mismatches_truncated |= value_differences_truncated;

    let Ok(route) = RouteId::from_str(&companion.route_id) else {
        report.precondition_failures.push("route_id_unknown".into());
        return report;
    };
    let companion_members = ordered_membership(route, &companion_raw);
    let direct_members = ordered_membership(route, &direct_raw);
    if let (Ok(left), Ok(right)) = (companion_members, direct_members) {
        report.companion_member_count = Some(left.len().to_string());
        report.direct_member_count = Some(right.len().to_string());
        if left == right {
            report.ordered_membership_disposition = "exact_match".into();
        } else {
            report.ordered_membership_disposition = "mismatch".into();
            mismatch(
                &mut report,
                "ordered_membership",
                None,
                Some(&sha256(left.join("\n").as_bytes())),
                Some(&sha256(right.join("\n").as_bytes())),
                "ordered response membership differs",
                maximum_mismatches,
            );
        }
    } else {
        report.ordered_membership_disposition = "unavailable".into();
        mismatch(
            &mut report,
            "ordered_membership_unavailable",
            None,
            None,
            None,
            "route body did not yield a strict membership projection",
            maximum_mismatches,
        );
    }

    let companion_cursor = next_cursor(&companion_raw).ok().flatten();
    let direct_cursor = next_cursor(&direct_raw).ok().flatten();
    report.companion_cursor_out_fingerprint = companion_cursor
        .as_deref()
        .map(|value| sha256(value.as_bytes()));
    report.direct_cursor_out_fingerprint = direct_cursor
        .as_deref()
        .map(|value| sha256(value.as_bytes()));
    if report.companion_cursor_out_fingerprint == report.direct_cursor_out_fingerprint {
        report.pagination_disposition = "cursor_match_one_page_completion_unknown".into();
    } else {
        report.pagination_disposition = "cursor_mismatch".into();
        let companion_cursor = report.companion_cursor_out_fingerprint.clone();
        let direct_cursor = report.direct_cursor_out_fingerprint.clone();
        mismatch(
            &mut report,
            "pagination_cursor_out",
            None,
            companion_cursor.as_deref(),
            direct_cursor.as_deref(),
            "provider next-cursor identities differ",
            maximum_mismatches,
        );
    }

    if companion.http_status != direct.http_status {
        mismatch(
            &mut report,
            "http_status",
            None,
            Some(&sha256(companion.http_status.to_string().as_bytes())),
            Some(&sha256(direct.http_status.to_string().as_bytes())),
            "HTTP status differs",
            maximum_mismatches,
        );
    }
    report.disposition = if report.mismatches.is_empty() {
        if companion_bytes == direct_bytes {
            "exact_bytes_equal"
        } else {
            "json_semantic_equal_exact_bytes_differ"
        }
    } else {
        "comparable_with_mismatch_evidence"
    }
    .into();
    report
}

fn validate_input(input: &ParityInputV2, source: ParitySource, side: &str) -> Vec<String> {
    let mut failures = Vec::new();
    if input.contract != PARITY_INPUT_V2 {
        failures.push(format!("{side}_contract"));
    }
    if input.source != source {
        failures.push(format!("{side}_source"));
    }
    if input.catalog_version != crate::ROUTE_CATALOG {
        failures.push(format!("{side}_catalog_version"));
    }
    if input.request_fingerprint_contract != PARITY_REQUEST_FINGERPRINT_CONTRACT {
        failures.push(format!("{side}_request_fingerprint_contract"));
    }
    if RouteId::from_str(&input.route_id).is_err() {
        failures.push(format!("{side}_route_id"));
    }
    if input.source_acquisition_id.trim().is_empty() || input.source_acquisition_id.len() > 256 {
        failures.push(format!("{side}_source_acquisition_id"));
    }
    for (name, value) in [
        ("request_fingerprint", input.request_fingerprint.as_str()),
        (
            "visible_filter_fingerprint",
            input.visible_filter_fingerprint.as_str(),
        ),
        (
            "session_occurrence_id",
            input.session_occurrence_id.as_str(),
        ),
        ("blob_id", input.blob_id.as_str()),
    ] {
        if !is_sha256(value) {
            failures.push(format!("{side}_{name}"));
        }
    }
    if input
        .cursor_in_fingerprint
        .as_deref()
        .is_some_and(|value| !is_sha256(value))
        || input
            .rendered_order_digest
            .as_deref()
            .is_some_and(|value| !is_sha256(value))
    {
        failures.push(format!("{side}_optional_digest"));
    }
    if input.page_ordinal.parse::<u64>().is_err() || input.byte_length.parse::<u64>().is_err() {
        failures.push(format!("{side}_wire_u64"));
    }
    match (input.session_class.as_str(), &input.auth_disposition) {
        ("public", AuthDisposition::NotRequiredPublic)
        | (
            "ordinary_authenticated",
            AuthDisposition::OrdinarySessionAccepted
            | AuthDisposition::SessionRejected
            | AuthDisposition::ChallengeOrSignatureRequired,
        )
        | ("unknown", AuthDisposition::Unknown) => {}
        _ => failures.push(format!("{side}_session_auth_consistency")),
    }
    if input.comparison_boundary != "fetch_response_decoded_body_bytes" {
        failures.push(format!("{side}_comparison_boundary"));
    }
    failures
}

fn pair_skew(left: &ParityInputV2, right: &ParityInputV2) -> Option<u64> {
    let left_started = parse_time(&left.started_at)?;
    let left_received = parse_time(&left.received_at)?;
    let right_started = parse_time(&right.started_at)?;
    let right_received = parse_time(&right.received_at)?;
    if left_received < left_started || right_received < right_started {
        return None;
    }
    let micros = (left_received - right_received)
        .whole_microseconds()
        .unsigned_abs();
    u64::try_from(micros).ok()
}

fn parse_time(value: &str) -> Option<OffsetDateTime> {
    let format = time::macros::format_description!(
        "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
    );
    PrimitiveDateTime::parse(value, format)
        .ok()
        .map(PrimitiveDateTime::assume_utc)
}

fn is_sha256(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

fn verified_bytes(input: &ParityInputV2) -> Option<Vec<u8>> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(&input.body_base64)
        .ok()?;
    (input.byte_length == bytes.len().to_string() && input.blob_id == sha256(&bytes))
        .then_some(bytes)
}

fn strict_raw(bytes: &[u8]) -> Option<Box<RawValue>> {
    reject_duplicate_keys(bytes).ok()?;
    serde_json::from_slice(bytes).ok()
}

fn ordered_membership(route: RouteId, root: &RawValue) -> Result<Vec<String>, ()> {
    let rows = records(route, root).map_err(|_| ())?;
    rows.iter()
        .map(|row| {
            let object = serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(row.get())
                .map_err(|_| ())?;
            let keys: &[&str] = match route {
                RouteId::CoinExact
                | RouteId::DiscoveryCoins
                | RouteId::CurrentlyLive
                | RouteId::CoinSearch
                | RouteId::BalanceTokens => &["mint"],
                RouteId::CalloutRecent
                | RouteId::CalloutTop
                | RouteId::CalloutByUser
                | RouteId::CommunityCallouts => &["calloutId", "id"],
                RouteId::UserSearch | RouteId::UserProfile | RouteId::Following => {
                    &["address", "userId"]
                }
                RouteId::CommunityMessages => &["id"],
                RouteId::Trades => &["signature"],
                RouteId::Candles => &["timestamp", "time"],
                RouteId::SolPrice | RouteId::BalanceSummary => &["asOfTimestamp", "updatedAt"],
                RouteId::LiveChat => return Err(()),
            };
            for key in keys {
                if let Some(value) = object.get(*key) {
                    return Ok(sha256(format!("{key}={}", value.get()).as_bytes()));
                }
            }
            Err(())
        })
        .collect()
}

fn rendered_order_disposition(left: &ParityInputV2, right: &ParityInputV2) -> String {
    match (&left.rendered_order_digest, &right.rendered_order_digest) {
        (Some(left), Some(right)) if left == right => "separately_witnessed_match",
        (Some(_), Some(_)) => "separately_witnessed_mismatch",
        _ => "provider_response_only_rendered_order_unwitnessed",
    }
    .into()
}

#[allow(clippy::too_many_arguments)]
fn mismatch(
    report: &mut ParityReportV2,
    kind: &str,
    pointer: Option<&str>,
    companion_digest: Option<&str>,
    direct_digest: Option<&str>,
    detail: &str,
    maximum: usize,
) {
    if report.mismatches.len() >= maximum.max(1) {
        report.mismatches_truncated = true;
        return;
    }
    report.mismatches.push(MismatchEvidence {
        kind: kind.into(),
        pointer: pointer.map(str::to_owned),
        companion_digest: companion_digest.map(str::to_owned),
        direct_digest: direct_digest.map(str::to_owned),
        detail: detail.into(),
    });
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)] // Closed wire checklist; booleans are independently audited gates.
pub struct PromotionOccurrence {
    pub pair_id: String,
    pub pair_report_blob_id: String,
    pub session_occurrence_id: String,
    pub comparable: bool,
    pub ordered_membership_match: bool,
    pub differences_understood: bool,
    pub difference_review_id: Option<String>,
    pub mismatch_count: String,
    pub pagination_gap_ids: Vec<String>,
    pub pagination_chain_complete: bool,
    pub auth_accepted: bool,
    pub schema_quarantined: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromotionRunV1 {
    pub contract: String,
    pub run_id: String,
    pub route_id: String,
    pub catalog_version: String,
    pub session_path_disposition: SessionPathDisposition,
    pub occurrences: Vec<PromotionOccurrence>,
    pub stop_condition_ids: Vec<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionPathDisposition {
    OrdinaryHeadlessSessionAdmissible,
    AuthenticatedDirectNotAdmissible,
    NotRunEmberPresentRequired,
    StoppedOnSourceCondition,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromotionReportV1 {
    pub contract: String,
    pub run_id: String,
    pub route_id: String,
    pub session_path_disposition: SessionPathDisposition,
    pub disposition: String,
    pub occurrence_count: String,
    pub distinct_session_count: String,
    pub ordered_membership_match_count: String,
    pub failures: Vec<String>,
}

/// Evaluate the preregistered W4 route gate without turning one successful pair into promotion.
#[must_use]
pub fn evaluate_promotion(run: &PromotionRunV1) -> PromotionReportV1 {
    let mut failures = Vec::new();
    if run.contract != PROMOTION_RUN_V1 {
        failures.push("contract".into());
    }
    if run.catalog_version != crate::ROUTE_CATALOG {
        failures.push("catalog_version".into());
    }
    if run.session_path_disposition == SessionPathDisposition::OrdinaryHeadlessSessionAdmissible
        && RouteId::from_str(&run.route_id).is_err()
    {
        failures.push("route_id".into());
    }
    let mut pair_ids = BTreeSet::new();
    let mut sessions = BTreeSet::new();
    let mut matching = 0_usize;
    for occurrence in &run.occurrences {
        if !pair_ids.insert(&occurrence.pair_id) {
            failures.push("duplicate_pair_id".into());
        }
        sessions.insert(&occurrence.session_occurrence_id);
        if !is_sha256(&occurrence.pair_report_blob_id)
            || !is_sha256(&occurrence.session_occurrence_id)
        {
            failures.push("invalid_occurrence_digest".into());
        }
        if occurrence.ordered_membership_match {
            matching += 1;
        }
        if !occurrence.comparable {
            failures.push("incomparable_pair".into());
        }
        let mismatch_count = occurrence.mismatch_count.parse::<u64>();
        if mismatch_count.is_err() {
            failures.push("invalid_mismatch_count".into());
        }
        if !occurrence.differences_understood
            || (mismatch_count.is_ok_and(|count| count > 0)
                && occurrence.difference_review_id.is_none())
        {
            failures.push("unreviewed_difference".into());
        }
        if !occurrence.pagination_gap_ids.is_empty() || !occurrence.pagination_chain_complete {
            failures.push("pagination_not_gap_free".into());
        }
        if !occurrence.auth_accepted {
            failures.push("auth_not_accepted".into());
        }
        if occurrence.schema_quarantined {
            failures.push("schema_quarantined".into());
        }
    }
    if run.occurrences.len() != 20 {
        failures.push("pair_count_not_20".into());
    }
    if sessions.len() < 3 {
        failures.push("fewer_than_3_sessions".into());
    }
    if matching < 19 {
        failures.push("fewer_than_19_ordered_membership_matches".into());
    }
    if !run.stop_condition_ids.is_empty() {
        failures.push("source_stop_condition_observed".into());
    }
    match run.session_path_disposition {
        SessionPathDisposition::OrdinaryHeadlessSessionAdmissible => {}
        SessionPathDisposition::NotRunEmberPresentRequired => {
            failures.push("ember_present_run_not_performed".into());
        }
        SessionPathDisposition::AuthenticatedDirectNotAdmissible
        | SessionPathDisposition::StoppedOnSourceCondition => {
            failures.push("authenticated_direct_not_admissible".into());
        }
    }
    failures.sort();
    failures.dedup();
    let disposition = if failures.is_empty() {
        "promotable_continuous_direct_source"
    } else if failures
        .iter()
        .any(|failure| failure == "authenticated_direct_not_admissible")
    {
        "authenticated_direct_not_admissible"
    } else {
        "not_promoted"
    };
    PromotionReportV1 {
        contract: PROMOTION_REPORT_V1.into(),
        run_id: run.run_id.clone(),
        route_id: run.route_id.clone(),
        session_path_disposition: run.session_path_disposition,
        disposition: disposition.into(),
        occurrence_count: run.occurrences.len().to_string(),
        distinct_session_count: sessions.len().to_string(),
        ordered_membership_match_count: matching.to_string(),
        failures,
    }
}
