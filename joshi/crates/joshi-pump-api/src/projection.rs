//! Shared non-secret request-state projection used only for direct/companion parity.

use crate::catalog::{PaginationKind, RouteSpec};
use crate::client::{PumpApiError, build_url, sha256};
use crate::model::LogicalRequest;

pub const PARITY_REQUEST_FINGERPRINT_CONTRACT: &str = "pump-parity-request-projection.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParityRequestProjection {
    pub request_fingerprint: String,
    pub visible_filter_fingerprint: String,
    pub cursor_in_fingerprint: Option<String>,
    pub pagination_kind: String,
    pub page_ordinal: String,
}

/// Project one direct request into the same digest-only parity boundary used by the companion.
/// Path and query values are hashed before entering canonical material.
///
/// # Errors
///
/// Returns an error when required path values are absent or the rendered request URL is invalid.
pub fn parity_request_projection(
    request: &LogicalRequest,
) -> Result<ParityRequestProjection, PumpApiError> {
    let spec = RouteSpec::for_id(request.route);
    let rendered = build_url(spec, request)?;
    let path = rendered.path();
    let mut request_lines = vec![
        format!("contract={PARITY_REQUEST_FINGERPRINT_CONTRACT}"),
        "method=GET".into(),
        format!("routeId={}", request.route),
        format!("origin={}", spec.origin),
        format!("path.sha256={}", sha256(path.as_bytes())),
    ];
    let mut filter_lines = vec![format!("routeId={}", request.route)];
    let mut cursor_lines = vec![format!("routeId={}", request.route)];
    let mut has_cursor_state = false;
    for (name, value) in &request.parameters.query {
        let line = format!("query.{name}.sha256={}", sha256(value.as_bytes()));
        request_lines.push(line.clone());
        if is_pagination_state(name) {
            has_cursor_state = true;
            cursor_lines.push(line);
        } else if !is_page_size(name) {
            filter_lines.push(line);
        }
    }
    Ok(ParityRequestProjection {
        request_fingerprint: sha256(request_lines.join("\n").as_bytes()),
        visible_filter_fingerprint: sha256(filter_lines.join("\n").as_bytes()),
        cursor_in_fingerprint: has_cursor_state.then(|| sha256(cursor_lines.join("\n").as_bytes())),
        pagination_kind: pagination_name(spec.pagination).into(),
        page_ordinal: page_ordinal(request),
    })
}

fn page_ordinal(request: &LogicalRequest) -> String {
    if let Some(page) = request.parameters.query.get("page")
        && page.parse::<u64>().is_ok()
    {
        return page.clone();
    }
    let offset = request
        .parameters
        .query
        .get("offset")
        .and_then(|value| value.parse::<u64>().ok());
    let size = request
        .parameters
        .query
        .get("limit")
        .or_else(|| request.parameters.query.get("size"))
        .and_then(|value| value.parse::<u64>().ok());
    match (offset, size) {
        (Some(offset), Some(size)) if size > 0 => (offset / size).to_string(),
        _ => "0".into(),
    }
}

fn is_pagination_state(name: &str) -> bool {
    matches!(
        name,
        "after" | "before" | "beforeId" | "cursor" | "offset" | "page" | "pageToken"
    )
}

fn is_page_size(name: &str) -> bool {
    matches!(name, "limit" | "size")
}

fn pagination_name(value: PaginationKind) -> &'static str {
    match value {
        PaginationKind::None => "none",
        PaginationKind::OffsetLimit => "offset_limit",
        PaginationKind::PageSize => "page_size",
        PaginationKind::PageToken => "page_token",
        PaginationKind::BeforeId => "before_id",
        PaginationKind::Cursor => "cursor",
        PaginationKind::VendorWindow => "vendor_window",
        PaginationKind::Stream => "stream",
    }
}
