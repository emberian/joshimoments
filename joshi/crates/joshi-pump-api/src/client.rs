use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::Engine as _;
use reqwest::header::{
    ACCEPT, ACCEPT_ENCODING, AUTHORIZATION, CONTENT_TYPE, COOKIE, HeaderName, HeaderValue,
    USER_AGENT,
};
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::sync::Mutex;
use url::Url;

use crate::auth::{SessionError, SessionProvider};
use crate::catalog::{AccessClass, RouteId, RouteSpec, TransportKind};
use crate::identity::{AcquisitionReservation, IdentityError, IdentityStore};
use crate::model::{
    Acquisition, AcquisitionClocks, BodyCapture, CoverageBoundary, CoverageGap, CoverageScope,
    CoverageWindow, FetchOutcome, LogicalRequest, SafeHeader,
};
use crate::{ROUTE_CATALOG, SOURCE_CONTRACT};

#[derive(Clone, Debug)]
pub struct ClientConfig {
    pub enabled_routes: BTreeSet<RouteId>,
    pub request_budget: usize,
    pub response_limit_bytes: usize,
    pub request_timeout: Duration,
    pub minimum_host_interval: Duration,
    pub maximum_attempts: usize,
    pub maximum_backoff: Duration,
    pub user_agent: String,
}

impl Default for ClientConfig {
    fn default() -> Self {
        Self {
            // One source of truth: a route is on by default exactly when the pinned catalog
            // says it is collectable. A second hand-maintained list here would silently drift
            // away from the catalog bit that operators actually read and edit.
            enabled_routes: RouteId::ALL
                .into_iter()
                .filter(|route| RouteSpec::for_id(*route).collection_enabled)
                .collect(),
            request_budget: 20,
            response_limit_bytes: 2 * 1024 * 1024,
            request_timeout: Duration::from_secs(15),
            minimum_host_interval: Duration::from_millis(1_100),
            maximum_attempts: 3,
            maximum_backoff: Duration::from_secs(30),
            user_agent: "joshi-pump-api/0.1 read-only personal accessibility client".to_owned(),
        }
    }
}

#[derive(Error, Debug)]
pub enum PumpApiError {
    #[error("route {0} is not explicitly enabled")]
    RouteDisabled(String),
    #[error("route {0} is reconnaissance-only or has no implemented HTTP transport")]
    UnsupportedTransport(String),
    #[error("unknown path parameter {name:?} for route {route}")]
    UnknownPathParameter { route: String, name: String },
    #[error("missing path parameter {name:?} for route {route}")]
    MissingPathParameter { route: String, name: String },
    #[error("query parameter {name:?} is not allowlisted for route {route}")]
    QueryNotAllowed { route: String, name: String },
    #[error("request budget exhausted before route {0}")]
    RequestBudget(String),
    #[error("invalid source URL or header: {0}")]
    InvalidRequest(String),
    #[error(transparent)]
    Session(#[from] SessionError),
    #[error(transparent)]
    Identity(#[from] IdentityError),
    #[error("unable to construct HTTP client: {0}")]
    Client(#[from] reqwest::Error),
    #[error("system clock precedes the Unix epoch")]
    Clock,
    #[error("formatted timestamp failed: {0}")]
    Timestamp(#[from] time::error::Format),
}

pub struct PumpApiClient {
    http: reqwest::Client,
    config: ClientConfig,
    identity: IdentityStore,
    sessions: Arc<dyn SessionProvider>,
    calls: AtomicUsize,
    last_request: Mutex<HashMap<String, Instant>>,
    monotonic_origin: Instant,
    monotonic_clock_id: String,
}

impl std::fmt::Debug for PumpApiClient {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("PumpApiClient")
            .field("config", &self.config)
            .field("identity", &self.identity)
            .field("sessions", &"[SESSION PROVIDER]")
            .finish_non_exhaustive()
    }
}

impl PumpApiClient {
    /// Build a cookie-store-free, redirect-refusing HTTP client.
    ///
    /// # Errors
    ///
    /// Returns an error if TLS/client construction or the local clock fails.
    pub fn new(
        config: ClientConfig,
        identity: IdentityStore,
        sessions: Arc<dyn SessionProvider>,
    ) -> Result<Self, PumpApiError> {
        let http = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .timeout(config.request_timeout)
            .build()?;
        let clock_nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| PumpApiError::Clock)?
            .as_micros();
        let monotonic_clock_id = format!(
            "mono:pump-api:{}:{}:{clock_nonce}",
            identity.installation(),
            std::process::id()
        );
        Ok(Self {
            http,
            config,
            identity,
            sessions,
            calls: AtomicUsize::new(0),
            last_request: Mutex::new(HashMap::new()),
            monotonic_origin: Instant::now(),
            monotonic_clock_id,
        })
    }

    /// Execute one bounded logical GET. Every response attempt is retained separately. The
    /// returned acquisition IDs remain reserved until the durable sink acknowledges them through
    /// `IdentityStore`; ambiguous sink receipts must retry, never acknowledge.
    ///
    /// # Errors
    ///
    /// Returns a typed error before network I/O for disabled/invalid routes, missing sessions,
    /// identity persistence failures, or exhausted run budget. HTTP/provider failures are retained
    /// in the returned attempt/gap records rather than collapsed into this error channel.
    #[allow(clippy::too_many_lines)] // Each retry attempt's evidence boundary stays visible here.
    pub async fn fetch(&self, request: &LogicalRequest) -> Result<FetchOutcome, PumpApiError> {
        let spec = RouteSpec::for_id(request.route);
        self.validate(spec, request)?;
        let url = build_url(spec, request)?;
        let request_fingerprint = request_fingerprint(spec, request);
        let cursor_in_fingerprint = cursor_fingerprint(spec, request);
        let session = if spec.requires_session() {
            Some(self.sessions.session_for(spec)?)
        } else {
            None
        };
        let session_class = session.as_ref().map_or_else(
            || "public".to_owned(),
            |material| format!("authenticated:{}", sha256(material.class().as_bytes())),
        );
        if !self.try_consume_request_budget() {
            return Err(PumpApiError::RequestBudget(spec.id.to_string()));
        }
        let first = self.identity.reserve()?;
        let request_group_id =
            first
                .acquisition_id
                .replacen("acq:pump-api:", "reqgrp:pump-api:", 1);
        let mut next_reservation = Some(first);
        let mut attempts = Vec::new();
        let mut windows = Vec::new();
        let mut gaps = Vec::new();

        for attempt in 0..self.config.maximum_attempts.max(1) {
            if attempt > 0 && !self.try_consume_request_budget() {
                let related = attempts
                    .last()
                    .map_or(request_group_id.as_str(), |value: &Acquisition| {
                        value.acquisition_id.as_str()
                    });
                gaps.push(coverage_gap(
                    related,
                    "request_budget_exhausted_before_retry",
                    spec,
                    &request_fingerprint,
                    cursor_in_fingerprint.clone(),
                    page_size(spec, request),
                )?);
                break;
            }
            let reservation = match next_reservation.take() {
                Some(value) => value,
                None => self.identity.reserve()?,
            };
            self.pace(url.host_str().unwrap_or("unknown")).await;
            let started_wall = time::OffsetDateTime::now_utc();
            let started_mono = self.monotonic_origin.elapsed();
            let mut builder = self
                .http
                .get(url.clone())
                .header(ACCEPT, "application/json")
                .header(ACCEPT_ENCODING, "identity")
                .header(USER_AGENT, self.config.user_agent.as_str());
            if let Some(material) = session.as_ref() {
                if let Some(bearer) = material.bearer_secret() {
                    let value = HeaderValue::from_str(&format!("Bearer {bearer}"))
                        .map_err(|error| PumpApiError::InvalidRequest(error.to_string()))?;
                    builder = builder.header(AUTHORIZATION, value);
                }
                if let Some(cookie) = material.cookie_secret() {
                    let value = HeaderValue::from_str(cookie)
                        .map_err(|error| PumpApiError::InvalidRequest(error.to_string()))?;
                    builder = builder.header(COOKIE, value);
                }
                if let Some((name, value)) = material.csrf_secret() {
                    let name = HeaderName::from_bytes(name.as_bytes())
                        .map_err(|error| PumpApiError::InvalidRequest(error.to_string()))?;
                    let value = HeaderValue::from_str(value)
                        .map_err(|error| PumpApiError::InvalidRequest(error.to_string()))?;
                    builder = builder.header(name, value);
                }
            }

            let sent = builder.send().await;
            let received_wall = time::OffsetDateTime::now_utc();
            let received_mono = self.monotonic_origin.elapsed();
            let clocks = clocks(
                started_wall,
                received_wall,
                &self.monotonic_clock_id,
                started_mono,
                received_mono,
            )?;
            let ordinal = (attempt + 1).to_string();

            match sent {
                Ok(response) => {
                    let status = response.status().as_u16();
                    let headers = safe_headers(response.headers());
                    let retry_after = retry_after_seconds(response.headers());
                    let media_type = response
                        .headers()
                        .get(CONTENT_TYPE)
                        .and_then(|value| value.to_str().ok())
                        .unwrap_or("application/octet-stream")
                        .to_owned();
                    let content_encoding = response
                        .headers()
                        .get("content-encoding")
                        .and_then(|value| value.to_str().ok())
                        .unwrap_or("identity")
                        .to_ascii_lowercase();
                    let body = capture_body(
                        response,
                        self.config.response_limit_bytes,
                        &media_type,
                        &content_encoding,
                    )
                    .await;
                    let oversized = matches!(body, BodyCapture::Truncated { .. });
                    let body_missing = matches!(body, BodyCapture::Missing { .. });
                    let acquisition = acquisition(
                        spec,
                        request,
                        &reservation,
                        &request_group_id,
                        &ordinal,
                        &session_class,
                        &request_fingerprint,
                        Some(status),
                        headers,
                        clocks,
                        body,
                    );
                    let acquisition_id = acquisition.acquisition_id.clone();
                    attempts.push(acquisition);

                    if oversized {
                        gaps.push(coverage_gap(
                            &acquisition_id,
                            "response_too_large",
                            spec,
                            &request_fingerprint,
                            cursor_in_fingerprint.clone(),
                            page_size(spec, request),
                        )?);
                        break;
                    }
                    if body_missing {
                        gaps.push(coverage_gap(
                            &acquisition_id,
                            "response_body_read_failed",
                            spec,
                            &request_fingerprint,
                            cursor_in_fingerprint.clone(),
                            page_size(spec, request),
                        )?);
                        break;
                    }
                    if status == 401 || status == 403 {
                        self.sessions.invalidate(spec);
                        gaps.push(coverage_gap(
                            &acquisition_id,
                            "authenticated_session_rejected",
                            spec,
                            &request_fingerprint,
                            cursor_in_fingerprint.clone(),
                            page_size(spec, request),
                        )?);
                        break;
                    }
                    if (200..300).contains(&status)
                        && let Some(last) = attempts.last()
                    {
                        windows.push(coverage_window(
                            last,
                            spec,
                            &request_fingerprint,
                            cursor_in_fingerprint.clone(),
                            page_size(spec, request),
                        ));
                    }
                    let retryable = status == 429 || matches!(status, 502..=504);
                    if retryable && attempt + 1 < self.config.maximum_attempts.max(1) {
                        let delay = retry_after.unwrap_or_else(|| {
                            Duration::from_secs(1_u64 << u32::try_from(attempt).unwrap_or(5).min(5))
                        });
                        tokio::time::sleep(delay.min(self.config.maximum_backoff)).await;
                        continue;
                    }
                    if retryable {
                        gaps.push(coverage_gap(
                            &acquisition_id,
                            if status == 429 {
                                "rate_limit_exhausted"
                            } else {
                                "provider_unavailable"
                            },
                            spec,
                            &request_fingerprint,
                            cursor_in_fingerprint.clone(),
                            page_size(spec, request),
                        )?);
                    }
                    break;
                }
                Err(error) => {
                    let acquisition = acquisition(
                        spec,
                        request,
                        &reservation,
                        &request_group_id,
                        &ordinal,
                        &session_class,
                        &request_fingerprint,
                        None,
                        Vec::new(),
                        clocks,
                        BodyCapture::Missing {
                            reason: transport_error_class(&error).to_owned(),
                        },
                    );
                    let acquisition_id = acquisition.acquisition_id.clone();
                    attempts.push(acquisition);
                    if attempt + 1 < self.config.maximum_attempts.max(1) {
                        let delay = Duration::from_secs(
                            1_u64 << u32::try_from(attempt).unwrap_or(5).min(5),
                        );
                        tokio::time::sleep(delay.min(self.config.maximum_backoff)).await;
                        continue;
                    }
                    gaps.push(coverage_gap(
                        &acquisition_id,
                        "transport_exhausted",
                        spec,
                        &request_fingerprint,
                        cursor_in_fingerprint.clone(),
                        page_size(spec, request),
                    )?);
                    break;
                }
            }
        }
        let completed = attempts.last().is_some_and(|attempt| {
            attempt
                .http_status
                .is_some_and(|status| (200..300).contains(&status))
                && matches!(attempt.body, BodyCapture::Exact { .. })
        });
        Ok(FetchOutcome {
            contract: "joshi.pump_api.fetch_outcome.v1".to_owned(),
            request_group_id,
            attempts,
            coverage_windows: windows,
            coverage_gaps: gaps,
            completed,
        })
    }

    fn validate(&self, spec: RouteSpec, request: &LogicalRequest) -> Result<(), PumpApiError> {
        if !self.config.enabled_routes.contains(&spec.id) {
            return Err(PumpApiError::RouteDisabled(spec.id.to_string()));
        }
        if spec.transport != TransportKind::Http || spec.access == AccessClass::ReconnaissanceOnly {
            return Err(PumpApiError::UnsupportedTransport(spec.id.to_string()));
        }
        for name in request.parameters.path.keys() {
            if !spec.required_path.contains(&name.as_str()) {
                return Err(PumpApiError::UnknownPathParameter {
                    route: spec.id.to_string(),
                    name: name.clone(),
                });
            }
        }
        for name in spec.required_path {
            if !request.parameters.path.contains_key(*name) {
                return Err(PumpApiError::MissingPathParameter {
                    route: spec.id.to_string(),
                    name: (*name).to_owned(),
                });
            }
        }
        for name in request.parameters.query.keys() {
            if !spec.allowed_query.contains(&name.as_str()) {
                return Err(PumpApiError::QueryNotAllowed {
                    route: spec.id.to_string(),
                    name: name.clone(),
                });
            }
        }
        Ok(())
    }

    async fn pace(&self, host: &str) {
        let mut last_request = self.last_request.lock().await;
        if let Some(last) = last_request.get(host) {
            let elapsed = last.elapsed();
            if let Some(wait) = self.config.minimum_host_interval.checked_sub(elapsed) {
                tokio::time::sleep(wait).await;
            }
        }
        last_request.insert(host.to_owned(), Instant::now());
    }

    fn try_consume_request_budget(&self) -> bool {
        self.calls
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |used| {
                (used < self.config.request_budget).then_some(used + 1)
            })
            .is_ok()
    }
}

pub(crate) fn build_url(spec: RouteSpec, request: &LogicalRequest) -> Result<Url, PumpApiError> {
    let mut url =
        Url::parse(spec.origin).map_err(|error| PumpApiError::InvalidRequest(error.to_string()))?;
    {
        let mut segments = url
            .path_segments_mut()
            .map_err(|()| PumpApiError::InvalidRequest("origin cannot be a base URL".to_owned()))?;
        segments.clear();
        for segment in spec.path_template.trim_start_matches('/').split('/') {
            if let Some(name) = segment
                .strip_prefix('{')
                .and_then(|value| value.strip_suffix('}'))
            {
                let value = request.parameters.path.get(name).ok_or_else(|| {
                    PumpApiError::MissingPathParameter {
                        route: spec.id.to_string(),
                        name: name.to_owned(),
                    }
                })?;
                segments.push(value);
            } else if !segment.is_empty() {
                segments.push(segment);
            }
        }
    }
    if !request.parameters.query.is_empty() {
        let mut pairs = url.query_pairs_mut();
        for (name, value) in &request.parameters.query {
            pairs.append_pair(name, value);
        }
    }
    Ok(url)
}

fn request_fingerprint(spec: RouteSpec, request: &LogicalRequest) -> String {
    let mut material = BTreeMap::new();
    material.insert("catalog".to_owned(), ROUTE_CATALOG.to_owned());
    material.insert("method".to_owned(), "GET".to_owned());
    material.insert("origin".to_owned(), spec.origin.to_owned());
    material.insert("pathTemplate".to_owned(), spec.path_template.to_owned());
    material.insert("route".to_owned(), spec.id.to_string());
    for (name, value) in &request.parameters.path {
        material.insert(format!("path.{name}.sha256"), sha256(value.as_bytes()));
    }
    for (name, value) in &request.parameters.query {
        let encoded = if spec.sensitive_query.contains(&name.as_str()) {
            sha256(value.as_bytes())
        } else {
            value.clone()
        };
        material.insert(format!("query.{name}"), encoded);
    }
    let mut canonical = String::new();
    for (name, value) in material {
        canonical.push_str(&name);
        canonical.push('=');
        canonical.push_str(&value);
        canonical.push('\n');
    }
    sha256(canonical.as_bytes())
}

fn cursor_fingerprint(spec: RouteSpec, request: &LogicalRequest) -> Option<String> {
    [
        "pageToken",
        "cursor",
        "before",
        "beforeId",
        "offset",
        "page",
    ]
    .into_iter()
    .find_map(|name| request.parameters.query.get(name))
    .map(|value| format!("{}:{value}", spec.id))
    .map(|value| sha256(value.as_bytes()))
}

fn page_size(spec: RouteSpec, request: &LogicalRequest) -> Option<String> {
    let _ = spec;
    request
        .parameters
        .query
        .get("limit")
        .or_else(|| request.parameters.query.get("size"))
        .cloned()
}

async fn capture_body(
    mut response: reqwest::Response,
    limit: usize,
    media_type: &str,
    content_encoding: &str,
) -> BodyCapture {
    let boundary = if content_encoding == "identity" {
        "http_entity_body_post_transfer_decoding_identity_encoding"
    } else {
        "http_entity_body_post_transfer_decoding_content_encoded"
    };
    let mut bytes = Vec::new();
    loop {
        match response.chunk().await {
            Ok(Some(chunk)) => {
                if bytes.len().saturating_add(chunk.len()) > limit {
                    let remaining = limit.saturating_sub(bytes.len());
                    bytes.extend_from_slice(&chunk[..remaining]);
                    return BodyCapture::Truncated {
                        boundary: boundary.to_owned(),
                        media_type: media_type.to_owned(),
                        prefix_base64: base64::engine::general_purpose::STANDARD.encode(&bytes),
                        prefix_length: bytes.len().to_string(),
                        received_at_least: bytes
                            .len()
                            .saturating_add(chunk.len() - remaining)
                            .to_string(),
                        prefix_blob_id: sha256(&bytes),
                        limit_bytes: limit.to_string(),
                    };
                }
                bytes.extend_from_slice(&chunk);
            }
            Ok(None) => {
                return BodyCapture::Exact {
                    boundary: boundary.to_owned(),
                    media_type: media_type.to_owned(),
                    bytes_base64: base64::engine::general_purpose::STANDARD.encode(&bytes),
                    byte_length: bytes.len().to_string(),
                    blob_id: sha256(&bytes),
                };
            }
            Err(error) => {
                return BodyCapture::Missing {
                    reason: transport_error_class(&error).to_owned(),
                };
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn acquisition(
    spec: RouteSpec,
    request: &LogicalRequest,
    reservation: &AcquisitionReservation,
    request_group_id: &str,
    attempt_ordinal: &str,
    session_class: &str,
    request_fingerprint: &str,
    http_status: Option<u16>,
    safe_response_headers: Vec<SafeHeader>,
    clocks: AcquisitionClocks,
    body: BodyCapture,
) -> Acquisition {
    Acquisition {
        contract: SOURCE_CONTRACT.to_owned(),
        catalog_version: ROUTE_CATALOG.to_owned(),
        acquisition_id: reservation.acquisition_id.clone(),
        request_group_id: request_group_id.to_owned(),
        attempt_ordinal: attempt_ordinal.to_owned(),
        route_id: spec.id.to_string(),
        transport: spec.transport.to_string(),
        access_class: spec.access.to_string(),
        stability: spec.stability.to_string(),
        session_class: session_class.to_owned(),
        source_locator: format!("{}{}", spec.origin, spec.path_template),
        resolved_public_path: resolved_public_path(spec, request),
        resolved_public_query: resolved_public_query(spec, request),
        request_fingerprint: request_fingerprint.to_owned(),
        http_status,
        safe_response_headers,
        clocks,
        body,
    }
}

/// The exact resolved values of the path segments the pinned catalog marks public subjects, and
/// nothing else. Every other parameter stays inside the one-way request fingerprint.
fn resolved_public_path(spec: RouteSpec, request: &LogicalRequest) -> BTreeMap<String, String> {
    spec.public_subject_path()
        .iter()
        .filter_map(|name| {
            request
                .parameters
                .path
                .get(*name)
                .map(|value| ((*name).to_owned(), value.clone()))
        })
        .collect()
}

/// The exact values of the query parameters the pinned catalog marks public, and nothing else.
///
/// The catalog declaration is necessary but not sufficient: this writer independently refuses
/// any name the route pins sensitive and any name
/// [`query_parameter_never_public`](crate::catalog::query_parameter_never_public) rejects, so a
/// mistaken future catalog edit cannot widen retention to a subject, a cursor, or anything
/// credential-adjacent. Everything refused here survives only inside the one-way
/// `request_fingerprint`, which continues to cover the full request either way.
fn resolved_public_query(spec: RouteSpec, request: &LogicalRequest) -> BTreeMap<String, String> {
    spec.public_query_parameters()
        .iter()
        .filter(|name| !spec.sensitive_query.contains(*name))
        .filter(|name| !crate::catalog::query_parameter_never_public(name))
        .filter_map(|name| {
            request
                .parameters
                .query
                .get(*name)
                .map(|value| ((*name).to_owned(), value.clone()))
        })
        .collect()
}

fn clocks(
    started_at: time::OffsetDateTime,
    received_at: time::OffsetDateTime,
    monotonic_clock_id: &str,
    started_mono: Duration,
    received_mono: Duration,
) -> Result<AcquisitionClocks, PumpApiError> {
    Ok(AcquisitionClocks {
        started_at: utc(started_at)?,
        received_at: utc(received_at)?,
        monotonic_clock_id: monotonic_clock_id.to_owned(),
        started_monotonic_ns: started_mono.as_nanos().to_string(),
        received_monotonic_ns: received_mono.as_nanos().to_string(),
        elapsed_ns: received_mono
            .saturating_sub(started_mono)
            .as_nanos()
            .to_string(),
    })
}

fn utc(value: time::OffsetDateTime) -> Result<String, time::error::Format> {
    value.format(time::macros::format_description!(
        "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
    ))
}

fn safe_headers(headers: &reqwest::header::HeaderMap) -> Vec<SafeHeader> {
    const ALLOWED: [&str; 9] = [
        "age",
        "cache-control",
        "content-encoding",
        "content-type",
        "date",
        "etag",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    ];
    let mut output = headers
        .iter()
        .filter_map(|(name, value)| {
            let name = name.as_str().to_ascii_lowercase();
            if !ALLOWED.contains(&name.as_str()) {
                return None;
            }
            value.to_str().ok().map(|value| SafeHeader {
                name,
                value: value.to_owned(),
            })
        })
        .collect::<Vec<_>>();
    output.sort_by(|left, right| {
        left.name
            .cmp(&right.name)
            .then(left.value.cmp(&right.value))
    });
    output
}

fn retry_after_seconds(headers: &reqwest::header::HeaderMap) -> Option<Duration> {
    headers
        .get("retry-after")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .map(Duration::from_secs)
}

fn coverage_gap(
    acquisition_id: &str,
    reason: &str,
    spec: RouteSpec,
    request_fingerprint: &str,
    cursor_in_fingerprint: Option<String>,
    page_size: Option<String>,
) -> Result<CoverageGap, PumpApiError> {
    Ok(CoverageGap {
        gap_id: format!("gap:{}:{reason}", acquisition_id.trim_start_matches("acq:")),
        detected_at: utc(time::OffsetDateTime::now_utc())?,
        reason: reason.to_owned(),
        scope: CoverageScope {
            route_id: spec.id.to_string(),
            request_fingerprint: request_fingerprint.to_owned(),
            order_semantics: spec.ordering.to_owned(),
            cursor_in_fingerprint,
            page_size,
        },
        boundary: CoverageBoundary {
            last_accepted_cursor_fingerprint: None,
            first_resumed_cursor_fingerprint: None,
            interval_status: "unknown_until_recovery".to_owned(),
        },
        related_acquisition_ids: vec![acquisition_id.to_owned()],
    })
}

fn coverage_window(
    acquisition: &Acquisition,
    spec: RouteSpec,
    request_fingerprint: &str,
    cursor_in_fingerprint: Option<String>,
    page_size: Option<String>,
) -> CoverageWindow {
    CoverageWindow {
        window_id: format!(
            "window:{}",
            acquisition.acquisition_id.trim_start_matches("acq:")
        ),
        observed_from: acquisition.clocks.started_at.clone(),
        observed_to: acquisition.clocks.received_at.clone(),
        scope: CoverageScope {
            route_id: spec.id.to_string(),
            request_fingerprint: request_fingerprint.to_owned(),
            order_semantics: spec.ordering.to_owned(),
            cursor_in_fingerprint,
            page_size,
        },
        acquisition_ids: vec![acquisition.acquisition_id.clone()],
        completeness: "one_response_page_observed_feed_completion_unknown".to_owned(),
    }
}

fn transport_error_class(error: &reqwest::Error) -> &'static str {
    if error.is_timeout() {
        "timeout"
    } else if error.is_connect() {
        "connect"
    } else if error.is_body() {
        "body_read"
    } else if error.is_decode() {
        "decode"
    } else {
        "transport"
    }
}

#[must_use]
pub fn sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(7 + digest.len() * 2);
    output.push_str("sha256:");
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::RequestParameters;

    #[test]
    fn fingerprint_hashes_sensitive_query_and_all_path_values() {
        let spec = RouteSpec::for_id(RouteId::CoinSearch);
        let request = LogicalRequest {
            route: RouteId::CoinSearch,
            parameters: RequestParameters {
                path: BTreeMap::new(),
                query: BTreeMap::from([
                    ("limit".to_owned(), "5".to_owned()),
                    ("searchTerm".to_owned(), "private thought".to_owned()),
                ]),
            },
        };
        let first = request_fingerprint(spec, &request);
        assert!(first.starts_with("sha256:"));
        assert!(!first.contains("private"));
        let mut changed = request.clone();
        changed
            .parameters
            .query
            .insert("searchTerm".to_owned(), "another".to_owned());
        assert_ne!(first, request_fingerprint(spec, &changed));
    }

    #[test]
    fn only_catalog_declared_public_subjects_are_restated_on_the_envelope() {
        // The mint the request resolved into a coin route's path is restated verbatim; the
        // callout route's `{user}` segment is not catalog-declared public and stays only inside
        // the one-way fingerprint.
        let candles = RouteSpec::for_id(RouteId::Candles);
        let request = LogicalRequest {
            route: RouteId::Candles,
            parameters: RequestParameters {
                path: BTreeMap::from([("mint".to_owned(), "MINTPUBLIC1111".to_owned())]),
                query: BTreeMap::new(),
            },
        };
        assert_eq!(
            resolved_public_path(candles, &request),
            BTreeMap::from([("mint".to_owned(), "MINTPUBLIC1111".to_owned())])
        );

        let callout = RouteSpec::for_id(RouteId::CalloutByUser);
        let request = LogicalRequest {
            route: RouteId::CalloutByUser,
            parameters: RequestParameters {
                path: BTreeMap::from([("user".to_owned(), "somebody".to_owned())]),
                query: BTreeMap::new(),
            },
        };
        assert!(resolved_public_path(callout, &request).is_empty());

        // An envelope retained before the field existed still parses, and its absence stays an
        // absence rather than an empty claim. (resolvedPublicQuery below follows identically.)
        let legacy: crate::model::Acquisition = serde_json::from_value(serde_json::json!({
            "contract": SOURCE_CONTRACT,
            "catalogVersion": ROUTE_CATALOG,
            "acquisitionId": "acq:test",
            "requestGroupId": "reqgrp:test",
            "attemptOrdinal": "1",
            "routeId": "candles",
            "transport": "http",
            "accessClass": "observed_public_product",
            "stability": "undocumented_observed",
            "sessionClass": "public",
            "sourceLocator": "https://swap-api.pump.fun/v1/coins/{mint}/candles",
            "requestFingerprint": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "httpStatus": 200,
            "safeResponseHeaders": [],
            "clocks": {
                "startedAt": "2026-08-22T01:00:00.000000Z",
                "receivedAt": "2026-08-22T01:00:00.100000Z",
                "monotonicClockId": "test-clock",
                "startedMonotonicNs": "0",
                "receivedMonotonicNs": "100",
                "elapsedNs": "100"
            },
            "body": { "status": "missing", "reason": "test" }
        }))
        .expect("an envelope without resolvedPublicPath still parses");
        assert!(legacy.resolved_public_path.is_empty());
        assert!(legacy.resolved_public_query.is_empty());
        let reserialized = serde_json::to_value(&legacy).expect("reserialize");
        assert!(
            reserialized.get("resolvedPublicPath").is_none(),
            "an absent record stays absent on the wire"
        );
        assert!(
            reserialized.get("resolvedPublicQuery").is_none(),
            "an absent query record stays absent on the wire"
        );
    }

    #[test]
    fn only_catalog_declared_query_parameters_are_restated_on_the_envelope() {
        // The page shape is restated verbatim; the subject of the ask is not, even though the
        // route allowlists it — `searchTerm` is pinned sensitive and floor-refused by name.
        let search = RouteSpec::for_id(RouteId::CoinSearch);
        let request = LogicalRequest {
            route: RouteId::CoinSearch,
            parameters: RequestParameters {
                path: BTreeMap::new(),
                query: BTreeMap::from([
                    ("limit".to_owned(), "100".to_owned()),
                    ("offset".to_owned(), "70".to_owned()),
                    ("searchTerm".to_owned(), "private thought".to_owned()),
                ]),
            },
        };
        assert_eq!(
            resolved_public_query(search, &request),
            BTreeMap::from([
                ("limit".to_owned(), "100".to_owned()),
                ("offset".to_owned(), "70".to_owned()),
            ])
        );

        // A candle window's interval/currency/limit are restated so the retained bytes can say
        // which series they are; `before` stays only inside the one-way fingerprint.
        let candles = RouteSpec::for_id(RouteId::Candles);
        let request = LogicalRequest {
            route: RouteId::Candles,
            parameters: RequestParameters {
                path: BTreeMap::from([("mint".to_owned(), "MINTPUBLIC1111".to_owned())]),
                query: BTreeMap::from([
                    ("interval".to_owned(), "1m".to_owned()),
                    ("limit".to_owned(), "1000".to_owned()),
                    ("before".to_owned(), "1787352121000".to_owned()),
                ]),
            },
        };
        let restated = resolved_public_query(candles, &request);
        assert_eq!(
            restated,
            BTreeMap::from([
                ("interval".to_owned(), "1m".to_owned()),
                ("limit".to_owned(), "1000".to_owned()),
            ])
        );
        assert!(!restated.contains_key("before"));

        // The fingerprint still covers what retention restates: changing a restated value
        // changes the fingerprint, so redaction and restatement stay two views of one request.
        let mut changed = request.clone();
        changed
            .parameters
            .query
            .insert("limit".to_owned(), "500".to_owned());
        assert_ne!(
            request_fingerprint(candles, &request),
            request_fingerprint(candles, &changed)
        );
    }

    #[test]
    fn url_builder_percent_encodes_path_segments() {
        let spec = RouteSpec::for_id(RouteId::UserProfile);
        let request = LogicalRequest {
            route: RouteId::UserProfile,
            parameters: RequestParameters {
                path: BTreeMap::from([("key".to_owned(), "a/b ?".to_owned())]),
                query: BTreeMap::new(),
            },
        };
        let url = build_url(spec, &request).unwrap();
        assert_eq!(
            url.as_str(),
            "https://frontend-api-v3.pump.fun/users/a%2Fb%20%3F"
        );
    }
}
