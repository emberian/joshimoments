use std::collections::BTreeMap;

use base64::Engine as _;
use serde::{Deserialize, Serialize};

use crate::catalog::RouteId;

/// Caller-supplied route arguments. Values never enter logs or locators verbatim; the request
/// fingerprint applies each route's redaction policy.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct RequestParameters {
    pub path: BTreeMap<String, String>,
    pub query: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LogicalRequest {
    pub route: RouteId,
    pub parameters: RequestParameters,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SafeHeader {
    pub name: String,
    pub value: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum BodyCapture {
    Exact {
        boundary: String,
        media_type: String,
        bytes_base64: String,
        byte_length: String,
        blob_id: String,
    },
    Truncated {
        boundary: String,
        media_type: String,
        prefix_base64: String,
        prefix_length: String,
        received_at_least: String,
        prefix_blob_id: String,
        limit_bytes: String,
    },
    Missing {
        reason: String,
    },
}

impl BodyCapture {
    #[must_use]
    pub fn exact_bytes(&self) -> Option<Vec<u8>> {
        let Self::Exact { bytes_base64, .. } = self else {
            return None;
        };
        base64::engine::general_purpose::STANDARD
            .decode(bytes_base64)
            .ok()
    }

    #[must_use]
    pub fn blob_id(&self) -> Option<&str> {
        match self {
            Self::Exact { blob_id, .. } => Some(blob_id),
            Self::Truncated { prefix_blob_id, .. } => Some(prefix_blob_id),
            Self::Missing { .. } => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AcquisitionClocks {
    /// Canonical six-digit UTC emitted at the source edge.
    pub started_at: String,
    pub received_at: String,
    pub monotonic_clock_id: String,
    pub started_monotonic_ns: String,
    pub received_monotonic_ns: String,
    pub elapsed_ns: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Acquisition {
    pub contract: String,
    pub catalog_version: String,
    pub acquisition_id: String,
    pub request_group_id: String,
    pub attempt_ordinal: String,
    pub route_id: String,
    pub transport: String,
    pub access_class: String,
    pub stability: String,
    pub session_class: String,
    pub source_locator: String,
    pub request_fingerprint: String,
    pub http_status: Option<u16>,
    pub safe_response_headers: Vec<SafeHeader>,
    pub clocks: AcquisitionClocks,
    pub body: BodyCapture,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageScope {
    pub route_id: String,
    pub request_fingerprint: String,
    pub order_semantics: String,
    pub cursor_in_fingerprint: Option<String>,
    pub page_size: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageBoundary {
    pub last_accepted_cursor_fingerprint: Option<String>,
    pub first_resumed_cursor_fingerprint: Option<String>,
    pub interval_status: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageGap {
    pub gap_id: String,
    pub detected_at: String,
    pub reason: String,
    pub scope: CoverageScope,
    pub boundary: CoverageBoundary,
    pub related_acquisition_ids: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageWindow {
    pub window_id: String,
    pub observed_from: String,
    pub observed_to: String,
    pub scope: CoverageScope,
    pub acquisition_ids: Vec<String>,
    pub completeness: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FidelityGap {
    pub code: String,
    pub detail: String,
    pub acquisition_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FetchOutcome {
    pub contract: String,
    pub request_group_id: String,
    pub attempts: Vec<Acquisition>,
    pub coverage_windows: Vec<CoverageWindow>,
    pub coverage_gaps: Vec<CoverageGap>,
    pub completed: bool,
}
