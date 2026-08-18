use axum::{
    Router,
    body::Bytes,
    extract::{DefaultBodyLimit, Path, Query, State},
    http::{HeaderMap, HeaderValue, StatusCode, Uri, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use joshi_admission::{
    COMPANION_BATCH_CONTRACT, CompanionReceiptV1, ParsedCompanionBatch, Sha256Digest,
    admit_companion,
    operational::{
        ExplicitAbstentionCommandV1, MAX_OPERATIONAL_RECEIPT_BYTES, ProspectiveNominationCommandV1,
    },
    parse_companion, strict_json,
};
use joshi_domain::{SceneId, StableString, UtcTimestamp};
use joshi_operator::{OperatorCommandStatus, ValidatedOperatorCommandV1};
use joshi_publication::CockpitPublicationId;
use joshi_store::{
    OperatorCaptureMetadata, SceneMode, SceneSourceMode, SqliteStore, StoredCockpitV2Head,
    StoredCockpitV2Publication,
};
use serde::{Deserialize, Serialize};
use std::{
    fmt,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::{Instant, SystemTime, UNIX_EPOCH},
};
use tower::limit::ConcurrencyLimitLayer;
use zeroize::Zeroize as _;

use crate::pairing::{
    OrdinaryPairingError, OrdinaryPairingService, PairingAuthorizer, ordinary_pairing_router,
};
use joshi_pairing::{PairingConfig, PairingOrigin, PairingScope};

const COMPANION_DIGEST_HEADER: &str = "x-joshi-batch-digest";
const COMPANION_SCHEMA_HEADER: &str = "x-joshi-companion-schema";
const PAIRING_TOKEN_HEADER: &str = "x-joshi-pairing-token";
const SEC_FETCH_DEST_HEADER: &str = "sec-fetch-dest";
const SEC_FETCH_MODE_HEADER: &str = "sec-fetch-mode";
const SEC_FETCH_SITE_HEADER: &str = "sec-fetch-site";
const MAX_COMMAND_BYTES: usize = 64 * 1024;
const MAX_COMPANION_BYTES: usize = 512 * 1024;
const MAX_GLASS_RESPONSE_BYTES: usize = 4 * 1024 * 1024;

#[derive(Clone)]
pub struct CoreService {
    inner: Arc<Inner>,
}

struct Inner {
    store: Arc<Mutex<SqliteStore>>,
    companion_installation_id: Option<String>,
    pairing: PairingCapability,
    ordinary_pairing: Option<Arc<OrdinaryPairingService>>,
    monotonic_epoch: Instant,
    monotonic_clock_id: String,
}

#[derive(Eq, PartialEq)]
pub struct PairingCapability([u8; 32]);

impl PairingCapability {
    /// Decode the exact 32-byte local pairing capability from lowercase hexadecimal.
    ///
    /// # Errors
    ///
    /// Returns [`PairingCapabilityError`] unless the representation is exactly 64 lowercase digits.
    pub fn from_hex(value: &str) -> Result<Self, PairingCapabilityError> {
        if value.len() != 64 {
            return Err(PairingCapabilityError);
        }
        let mut bytes = [0_u8; 32];
        for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
            bytes[index] = (hex(pair[0])? << 4) | hex(pair[1])?;
        }
        Ok(Self(bytes))
    }

    fn matches_header(&self, value: &[u8]) -> bool {
        let Ok(text) = std::str::from_utf8(value) else {
            return false;
        };
        let Ok(candidate) = Self::from_hex(text) else {
            return false;
        };
        self.0
            .iter()
            .zip(candidate.0)
            .fold(0_u8, |difference, (left, right)| {
                difference | (*left ^ right)
            })
            == 0
    }
}

impl Drop for PairingCapability {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}

impl fmt::Debug for PairingCapability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("PairingCapability([REDACTED])")
    }
}

#[derive(Clone, Copy, Debug, Eq, thiserror::Error, PartialEq)]
#[error("pairing token must be exactly 32 bytes encoded as 64 lowercase hexadecimal characters")]
pub struct PairingCapabilityError;

fn hex(byte: u8) -> Result<u8, PairingCapabilityError> {
    match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        _ => Err(PairingCapabilityError),
    }
}

impl CoreService {
    #[must_use]
    pub fn new(
        store: SqliteStore,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
    ) -> Self {
        let started = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |value| value.as_micros());
        Self {
            inner: Arc::new(Inner {
                store: Arc::new(Mutex::new(store)),
                companion_installation_id,
                pairing,
                ordinary_pairing: None,
                monotonic_epoch: Instant::now(),
                monotonic_clock_id: format!("joshi-core-process-{}-{started}", std::process::id()),
            }),
        }
    }

    fn with_ordinary_pairing(
        store: Arc<Mutex<SqliteStore>>,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
        ordinary_pairing: Arc<OrdinaryPairingService>,
    ) -> Self {
        let started = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |value| value.as_micros());
        Self {
            inner: Arc::new(Inner {
                store,
                companion_installation_id,
                pairing,
                ordinary_pairing: Some(ordinary_pairing),
                monotonic_epoch: Instant::now(),
                monotonic_clock_id: format!("joshi-core-process-{}-{started}", std::process::id()),
            }),
        }
    }

    /// Opt in to ordinary pairing through the sole `SQLite` journal adapter.
    ///
    /// The returned handle is the launcher/revocation waist; it cannot be replaced by a
    /// caller-implemented journal or deterministic entropy/clock in a production build.
    ///
    /// # Errors
    ///
    /// Fails unless the `SQLite` journal atomically begins and exactly reads back a higher epoch.
    #[allow(dead_code)] // The default product router stays unmounted until the G0 harness opts in.
    pub(crate) fn with_sqlite_pairing(
        store: SqliteStore,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
        origin: PairingOrigin,
        config: PairingConfig,
    ) -> Result<(Self, Arc<OrdinaryPairingService>), OrdinaryPairingError> {
        let store = Arc::new(Mutex::new(store));
        let ordinary = Arc::new(OrdinaryPairingService::production_with_shared_store(
            origin,
            config,
            store.clone(),
        )?);
        let service = Self::with_ordinary_pairing(
            store,
            companion_installation_id,
            pairing,
            ordinary.clone(),
        );
        Ok((service, ordinary))
    }

    pub fn router(self) -> Router {
        let ordinary_product_routes_mounted = self.inner.ordinary_pairing.is_some();
        let pairing_router = self
            .inner
            .ordinary_pairing
            .clone()
            .map(ordinary_pairing_router);
        let mut router = Router::new()
            .route("/api/v1/health", get(health))
            .route("/v1/observations/pump-companion", post(companion))
            .route("/api/v1/glass/snapshot", get(snapshot))
            .route("/api/v1/glass/scenes/{scene_id}", get(historical_scene))
            .route("/api/v1/operator/commands", post(operator_command))
            .route("/api/v1/session/launch", get(prospective_session_launch))
            .route(
                "/api/v1/operator/prospective-nominations",
                post(prospective_nomination),
            )
            .route("/api/v1/operator/abstentions", post(explicit_abstention));
        if ordinary_product_routes_mounted {
            router = router.route(
                "/api/v1/cockpit-v2/publications/{publication_id}",
                get(cockpit_v2_publication),
            );
        }
        let router = router
            // No stream route exists in V1: reconnect ordering/digest binding is not frozen.
            .layer(DefaultBodyLimit::max(MAX_COMPANION_BYTES))
            .layer(ConcurrencyLimitLayer::new(16))
            .with_state(self);
        match pairing_router {
            Some(pairing) => router.merge(pairing),
            None => router,
        }
    }

    /// Serve the bounded router on an explicitly loopback socket.
    ///
    /// # Errors
    ///
    /// Returns an error for non-loopback addresses or listener/server I/O failures.
    pub async fn serve(self, address: SocketAddr) -> Result<(), ServiceError> {
        if !address.ip().is_loopback() {
            return Err(ServiceError::NonLoopback(address));
        }
        let listener = tokio::net::TcpListener::bind(address).await?;
        axum::serve(listener, self.router())
            .await
            .map_err(ServiceError::Io)
    }
}

async fn cockpit_v2_publication(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Path(publication_id): Path<String>,
) -> Response {
    match authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead) {
        OrdinaryAuthorization::Authorized => {}
        OrdinaryAuthorization::Rejected(response) => return response,
        OrdinaryAuthorization::NotConfigured => {
            return problem(
                StatusCode::NOT_FOUND,
                "route_not_mounted",
                "ordinary Cockpit V2 publication access is not mounted",
            );
        }
    }
    let Ok(publication_id) = CockpitPublicationId::new(publication_id) else {
        return problem(
            StatusCode::BAD_REQUEST,
            "invalid_publication_id",
            "Cockpit V2 publication identity is invalid",
        );
    };
    let Ok(store) = service.inner.store.lock() else {
        return problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "reader_unavailable",
            "catalog lock is unavailable",
        );
    };
    let (publication, head) = match (
        store.load_cockpit_v2_publication_v1(&publication_id),
        store.load_cockpit_v2_head_v1(&publication_id),
    ) {
        (Ok(Some(publication)), Ok(Some(head))) => (publication, head),
        (Ok(_), Ok(_)) => {
            return problem(
                StatusCode::NOT_FOUND,
                "headed_publication_not_found",
                "exact headed Cockpit V2 publication was not found",
            );
        }
        _ => {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "publication_readback_failed",
                "exact headed Cockpit V2 publication failed durable readback",
            );
        }
    };
    if publication.source_occurrence_id != head.source_occurrence_id
        || publication.commit_seq >= head.commit_seq
    {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "publication_lineage_failed",
            "Cockpit V2 publication and head do not close one strict store lineage",
        );
    }
    exact_cockpit_v2_response(&publication, &head)
}

fn exact_cockpit_v2_response(
    publication: &StoredCockpitV2Publication,
    head: &StoredCockpitV2Head,
) -> Response {
    let prefix = "{\"authority\":\"read_only_no_execution\",\"contract\":\"joshi.core.cockpit_v2_open\",\"head\":";
    let middle = format!(
        ",\"headBytesDigest\":\"{}\",\"headCommitSeq\":\"{}\",\"publication\":",
        head.head_digest.as_str(),
        head.commit_seq.get(),
    );
    let suffix = format!(
        ",\"publicationBytesDigest\":\"{}\",\"publicationCommitSeq\":\"{}\",\"schemaVersion\":1,\"sourceOccurrenceId\":{}}}",
        publication.publication_bytes_digest.as_str(),
        publication.commit_seq.get(),
        serde_json::to_string(publication.source_occurrence_id.as_str())
            .expect("stable strings always serialize"),
    );
    let Some(length) = prefix
        .len()
        .checked_add(head.head_bytes.len())
        .and_then(|value| value.checked_add(middle.len()))
        .and_then(|value| value.checked_add(publication.publication_bytes.len()))
        .and_then(|value| value.checked_add(suffix.len()))
    else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "publication_response_too_large",
            "Cockpit V2 publication response length overflowed",
        );
    };
    if length > MAX_GLASS_RESPONSE_BYTES {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "publication_response_too_large",
            "Cockpit V2 publication response exceeds the bounded Glass contract",
        );
    }
    let mut body = Vec::with_capacity(length);
    body.extend_from_slice(prefix.as_bytes());
    body.extend_from_slice(&head.head_bytes);
    body.extend_from_slice(middle.as_bytes());
    body.extend_from_slice(&publication.publication_bytes);
    body.extend_from_slice(suffix.as_bytes());
    let mut response = Response::new(axum::body::Body::from(body));
    *response.status_mut() = StatusCode::OK;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    response
}

async fn prospective_session_launch(
    State(service): State<CoreService>,
    headers: HeaderMap,
) -> Response {
    if let Some(response) =
        prospective_pairing_failure(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    problem(
        StatusCode::SERVICE_UNAVAILABLE,
        "prospective_session_not_registered",
        "no exact durable launch is bound to this pairing capability",
    )
}

async fn prospective_nomination(
    State(service): State<CoreService>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) =
        prospective_pairing_failure(&service, &headers, PairingScope::OperatorEvidenceWrite)
    {
        return response;
    }
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        != Some("application/json")
    {
        return problem(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "invalid_content_type",
            "content type must be application/json",
        );
    }
    let Ok(command): Result<ProspectiveNominationCommandV1, _> =
        strict_json::parse(&body, MAX_OPERATIONAL_RECEIPT_BYTES)
    else {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_prospective_nomination",
            "prospective nomination failed strict V1 parsing",
        );
    };
    if command.validate().is_err() {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_prospective_nomination",
            "prospective nomination failed strict V1 validation",
        );
    }
    problem(
        StatusCode::SERVICE_UNAVAILABLE,
        "prospective_store_adapter_unavailable",
        "nomination was not acknowledged because exact durable launch resolution is unavailable",
    )
}

async fn explicit_abstention(
    State(service): State<CoreService>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) =
        prospective_pairing_failure(&service, &headers, PairingScope::OperatorEvidenceWrite)
    {
        return response;
    }
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        != Some("application/json")
    {
        return problem(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "invalid_content_type",
            "content type must be application/json",
        );
    }
    let Ok(command): Result<ExplicitAbstentionCommandV1, _> =
        strict_json::parse(&body, MAX_OPERATIONAL_RECEIPT_BYTES)
    else {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_explicit_abstention",
            "explicit abstention failed strict V1 parsing",
        );
    };
    if command.validate().is_err() {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_explicit_abstention",
            "explicit abstention failed strict V1 validation",
        );
    }
    problem(
        StatusCode::SERVICE_UNAVAILABLE,
        "prospective_store_adapter_unavailable",
        "abstention was not acknowledged because exact durable launch resolution is unavailable",
    )
}

fn prospective_pairing_failure(
    service: &CoreService,
    headers: &HeaderMap,
    scope: PairingScope,
) -> Option<Response> {
    match authorize_ordinary_if_configured(service, headers, scope) {
        OrdinaryAuthorization::Authorized => return None,
        OrdinaryAuthorization::NotConfigured => {}
        OrdinaryAuthorization::Rejected(response) => return Some(response),
    }
    let origin = single_header_text(headers, header::ORIGIN.as_str());
    let host = single_header_text(headers, header::HOST.as_str());
    if origin
        .as_deref()
        .zip(host.as_deref())
        .is_none_or(|(origin, host)| !exact_loopback_same_origin(origin, host))
    {
        return Some(problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "prospective session requires exact matching loopback Host and Origin",
        ));
    }
    if single_header_text(headers, SEC_FETCH_SITE_HEADER).as_deref() != Some("same-origin")
        || single_header_text(headers, SEC_FETCH_MODE_HEADER).as_deref() != Some("cors")
        || single_header_text(headers, SEC_FETCH_DEST_HEADER).as_deref() != Some("empty")
    {
        return Some(problem(
            StatusCode::FORBIDDEN,
            "browser_posture_rejected",
            "prospective session requires same-origin browser Fetch Metadata",
        ));
    }
    if !headers
        .get(PAIRING_TOKEN_HEADER)
        .is_some_and(|value| service.inner.pairing.matches_header(value.as_bytes()))
    {
        return Some(problem(
            StatusCode::UNAUTHORIZED,
            "pairing_required",
            "valid launch-bound local pairing capability is required",
        ));
    }
    None
}

enum OrdinaryAuthorization {
    NotConfigured,
    Authorized,
    Rejected(Response),
}

fn authorize_ordinary_if_configured(
    service: &CoreService,
    headers: &HeaderMap,
    scope: PairingScope,
) -> OrdinaryAuthorization {
    let Some(authorizer) = &service.inner.ordinary_pairing else {
        return OrdinaryAuthorization::NotConfigured;
    };
    let origin = single_header_text(headers, header::ORIGIN.as_str());
    let host = single_header_text(headers, header::HOST.as_str());
    if origin.as_deref() != Some(authorizer.configured_origin().as_str())
        || origin
            .as_deref()
            .zip(host.as_deref())
            .is_none_or(|(origin, host)| !exact_loopback_same_origin(origin, host))
    {
        return OrdinaryAuthorization::Rejected(problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "ordinary session requires the configured exact loopback Host and Origin",
        ));
    }
    if single_header_text(headers, SEC_FETCH_SITE_HEADER).as_deref() != Some("same-origin")
        || single_header_text(headers, SEC_FETCH_MODE_HEADER).as_deref() != Some("cors")
        || single_header_text(headers, SEC_FETCH_DEST_HEADER).as_deref() != Some("empty")
    {
        return OrdinaryAuthorization::Rejected(problem(
            StatusCode::FORBIDDEN,
            "browser_posture_rejected",
            "ordinary session requires same-origin browser Fetch Metadata",
        ));
    }
    let Some(capability) = single_header_text(headers, PAIRING_TOKEN_HEADER) else {
        return OrdinaryAuthorization::Rejected(problem(
            StatusCode::UNAUTHORIZED,
            "pairing_required",
            "ordinary local pairing capability is required",
        ));
    };
    match authorizer.authorize(
        &capability,
        origin.as_deref().expect("checked origin"),
        scope,
    ) {
        Ok(()) => OrdinaryAuthorization::Authorized,
        Err(OrdinaryPairingError::Journal(_) | OrdinaryPairingError::Unavailable) => {
            OrdinaryAuthorization::Rejected(problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "pairing_writer_unavailable",
                "ordinary session state could not be durably resolved",
            ))
        }
        Err(OrdinaryPairingError::Pairing(_)) => OrdinaryAuthorization::Rejected(problem(
            StatusCode::UNAUTHORIZED,
            "pairing_required",
            "ordinary local session is invalid, expired, revoked, or lacks the required scope",
        )),
    }
}

fn exact_loopback_same_origin(origin: &str, host: &str) -> bool {
    let Ok(uri) = origin.parse::<Uri>() else {
        return false;
    };
    let Some(authority) = uri.authority() else {
        return false;
    };
    let loopback = matches!(
        uri.host(),
        Some("127.0.0.1" | "localhost" | "::1" | "[::1]")
    );
    uri.scheme_str() == Some("http")
        && uri.path() == "/"
        && uri.query().is_none()
        && loopback
        && authority.as_str() == host
}

#[derive(Debug, thiserror::Error)]
pub enum ServiceError {
    #[error("core HTTP listener must bind a loopback address, not {0}")]
    NonLoopback(SocketAddr),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Health<'a> {
    contract: &'a str,
    schema_version: u64,
    authority: &'a str,
    stream_contract: Option<&'a str>,
}

async fn health() -> impl IntoResponse {
    axum::Json(Health {
        contract: "joshi.core.health",
        schema_version: 1,
        authority: "read_only_no_execution",
        stream_contract: None,
    })
}

#[allow(clippy::too_many_lines)] // The handler preserves an explicit fail-closed admission sequence.
async fn companion(
    State(service): State<CoreService>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        != Some("application/json")
    {
        return problem(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "invalid_content_type",
            "content type must be application/json",
        );
    }
    if let Some(origin) = header_text(&headers, header::ORIGIN.as_str())
        && !origin.starts_with("chrome-extension://")
        && !origin.starts_with("moz-extension://")
    {
        return problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "browser origin is not an extension context",
        );
    }
    if !headers
        .get(PAIRING_TOKEN_HEADER)
        .is_some_and(|value| service.inner.pairing.matches_header(value.as_bytes()))
    {
        return problem(
            StatusCode::UNAUTHORIZED,
            "pairing_required",
            "valid local pairing capability is required",
        );
    }
    let schema = header_text(&headers, COMPANION_SCHEMA_HEADER);
    if schema.as_deref() != Some(COMPANION_BATCH_CONTRACT) {
        return problem(
            StatusCode::BAD_REQUEST,
            "invalid_header",
            "companion schema header mismatch",
        );
    }
    let Some(supplied_digest) = header_text(&headers, COMPANION_DIGEST_HEADER) else {
        return problem(
            StatusCode::BAD_REQUEST,
            "invalid_header",
            "companion digest header is required",
        );
    };
    let Ok(parsed) = parse_companion(&body) else {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_companion_batch",
            "companion batch failed strict validation",
        );
    };
    if supplied_digest != parsed.ingress_digest().as_str() {
        return problem(
            StatusCode::BAD_REQUEST,
            "invalid_header",
            "companion digest header mismatch",
        );
    }
    if !paired(&service, &parsed) {
        return problem(
            StatusCode::FORBIDDEN,
            "unpaired_installation",
            "companion installation is not locally paired",
        );
    }
    let (committed_at, committed_mono_ns) = match now(&service) {
        Ok(value) => value,
        Err(error) => {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "clock_unavailable",
                &error,
            );
        }
    };
    let Ok(admission) = admit_companion(
        parsed,
        committed_at,
        committed_mono_ns,
        &service.inner.monotonic_clock_id,
    ) else {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "admission_rejected",
            "companion evidence admission failed",
        );
    };
    let receipt = {
        let Ok(mut store) = service.inner.store.lock() else {
            return problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "writer_unavailable",
                "durable writer lock is unavailable",
            );
        };
        match admission.batch.commit(&mut store) {
            Ok(value) => value,
            Err(_) => {
                return problem(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "durable_commit_failed",
                    "durable commit did not complete",
                );
            }
        }
    };
    let response = match CompanionReceiptV1::from_committed(&admission, &receipt) {
        Ok(value) => value,
        Err(error) => {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "receipt_closure_failed",
                &error.to_string(),
            );
        }
    };
    let status = match response.status {
        joshi_admission::PublicStatus::Accepted => StatusCode::ACCEPTED,
        joshi_admission::PublicStatus::Idempotent => StatusCode::OK,
    };
    json_response(status, &response)
}

fn paired(service: &CoreService, parsed: &ParsedCompanionBatch) -> bool {
    service.inner.companion_installation_id.as_deref() == Some(parsed.installation_id())
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SnapshotQuery {
    mode: String,
    basis_scene_id: Option<String>,
}

async fn snapshot(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Query(query): Query<SnapshotQuery>,
) -> Response {
    if let OrdinaryAuthorization::Rejected(response) =
        authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    let Some(scene) = query.basis_scene_id else {
        return problem(
            StatusCode::CONFLICT,
            "scene_required",
            "V1 has no mutable current-scene pointer; basisSceneId is required",
        );
    };
    scene_response(&service, &scene, Some(&query.mode))
}

async fn historical_scene(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Path(scene_id): Path<String>,
) -> Response {
    if let OrdinaryAuthorization::Rejected(response) =
        authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    scene_response(&service, &scene_id, None)
}

fn scene_response(service: &CoreService, scene_id: &str, expected_mode: Option<&str>) -> Response {
    let Ok(scene_id) = SceneId::new(scene_id) else {
        return problem(
            StatusCode::BAD_REQUEST,
            "invalid_scene",
            "scene identity is invalid",
        );
    };
    let Ok(store) = service.inner.store.lock() else {
        return problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "reader_unavailable",
            "catalog lock is unavailable",
        );
    };
    let Ok(scene) = store.load_scene(&scene_id) else {
        return problem(
            StatusCode::NOT_FOUND,
            "scene_not_found",
            "immutable scene was not found",
        );
    };
    if let Some(mode) = expected_mode
        && mode != mode_name(scene.mode)
    {
        return problem(
            StatusCode::CONFLICT,
            "mode_mismatch",
            "requested replay mode does not match immutable scene",
        );
    }
    let Some(snapshot) = snapshot_bytes(&scene.view_bytes) else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "scene_response_too_large",
            "immutable scene exceeds the bounded Glass response contract",
        );
    };
    let mut response = Response::new(axum::body::Body::from(snapshot));
    *response.status_mut() = StatusCode::OK;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    response
}

fn snapshot_bytes(view_bytes: &[u8]) -> Option<Vec<u8>> {
    let digest = Sha256Digest::of_bytes(view_bytes);
    let prefix = format!(
        "{{\"contract\":\"joshi.glass.snapshot\",\"schemaVersion\":1,\"snapshotDigest\":\"{digest}\",\"transport\":\"loopback\",\"recordingAuthority\":\"read_record_replay_only\",\"view\":"
    );
    let length = prefix.len().checked_add(view_bytes.len())?.checked_add(1)?;
    if length > MAX_GLASS_RESPONSE_BYTES {
        return None;
    }
    let mut result = Vec::with_capacity(length);
    result.extend_from_slice(prefix.as_bytes());
    result.extend_from_slice(view_bytes);
    result.push(b'}');
    Some(result)
}

fn mode_name(mode: SceneMode) -> &'static str {
    match mode {
        SceneMode::Witnessed => "witnessed",
        SceneMode::KnowledgeCutoff => "knowledge_cutoff",
        SceneMode::Retrospective => "retrospective",
    }
}

#[allow(clippy::too_many_lines)] // Keeps the fail-closed authorization/admission order explicit.
async fn operator_command(
    State(service): State<CoreService>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if body.len() > MAX_COMMAND_BYTES {
        return problem(
            StatusCode::PAYLOAD_TOO_LARGE,
            "command_too_large",
            "operator command exceeds 64 KiB",
        );
    }
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        != Some("application/json")
    {
        return problem(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "invalid_content_type",
            "content type must be application/json",
        );
    }
    if !mutation_origin_allowed(&headers) {
        return problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "operator mutation origin is not an allowed loopback UI",
        );
    }
    match authorize_ordinary_if_configured(&service, &headers, PairingScope::OperatorEvidenceWrite)
    {
        OrdinaryAuthorization::Authorized => {}
        OrdinaryAuthorization::NotConfigured => {
            if !headers
                .get(PAIRING_TOKEN_HEADER)
                .is_some_and(|value| service.inner.pairing.matches_header(value.as_bytes()))
            {
                return problem(
                    StatusCode::UNAUTHORIZED,
                    "pairing_required",
                    "valid local pairing capability is required",
                );
            }
        }
        OrdinaryAuthorization::Rejected(response) => return response,
    }
    let Ok(command) = ValidatedOperatorCommandV1::parse_exact(&body) else {
        return problem(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_operator_command",
            "operator command failed exact V1 validation",
        );
    };
    let (committed_at, committed_mono_ns) = match now(&service) {
        Ok(value) => value,
        Err(error) => {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "clock_unavailable",
                &error,
            );
        }
    };
    let Ok(capture) = operator_capture() else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "capture_metadata_failed",
            "server capture metadata is unavailable",
        );
    };
    let receipt = {
        let Ok(mut store) = service.inner.store.lock() else {
            return problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "writer_unavailable",
                "durable writer lock is unavailable",
            );
        };
        match store.commit_operator_v1(
            &command,
            None,
            &capture,
            committed_at,
            StableString::new(service.inner.monotonic_clock_id.clone())
                .expect("validated service clock"),
            committed_mono_ns,
            StableString::new(env!("CARGO_PKG_VERSION")).expect("valid build"),
        ) {
            Ok(value) => value,
            Err(_) => {
                return problem(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "operator_commit_rejected",
                    "scene-bound operator command was not committed",
                );
            }
        }
    };
    let status = match receipt.status() {
        OperatorCommandStatus::Accepted => StatusCode::ACCEPTED,
        OperatorCommandStatus::Idempotent => StatusCode::OK,
    };
    json_response(status, &receipt)
}

fn operator_capture() -> Result<OperatorCaptureMetadata, joshi_domain::WireStringError> {
    Ok(OperatorCaptureMetadata {
        client_scene_seq: 0,
        ui_build: StableString::new("existing-scene")?,
        source_mode: SceneSourceMode::Observatory,
        rendered_clock_id: StableString::new("existing-scene")?,
        rendered_mono_ns: 0,
        screenshot_bytes: None,
    })
}

fn mutation_origin_allowed(headers: &HeaderMap) -> bool {
    let Some(origin) = header_text(headers, header::ORIGIN.as_str()) else {
        return true;
    };
    origin.starts_with("chrome-extension://")
        || origin.starts_with("moz-extension://")
        || origin == "http://127.0.0.1"
        || origin.starts_with("http://127.0.0.1:")
        || origin == "http://localhost"
        || origin.starts_with("http://localhost:")
}

fn header_text(headers: &HeaderMap, name: &str) -> Option<String> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned)
}

fn single_header_text(headers: &HeaderMap, name: &str) -> Option<String> {
    let mut values = headers.get_all(name).iter();
    let value = values.next()?;
    if values.next().is_some() {
        return None;
    }
    value.to_str().ok().map(str::to_owned)
}

fn now(service: &CoreService) -> Result<(UtcTimestamp, u64), String> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock precedes Unix epoch".to_owned())?;
    let micros = duration.as_micros();
    let nanos = i128::try_from(micros)
        .map_err(|_| "wall clock is out of range".to_owned())?
        .checked_mul(1_000)
        .ok_or_else(|| "wall clock is out of range".to_owned())?;
    let instant = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| "wall clock is out of range".to_owned())?;
    let wall = UtcTimestamp::new(instant)
        .map_err(|_| "wall clock is not microsecond aligned".to_owned())?;
    let mono = u64::try_from(service.inner.monotonic_epoch.elapsed().as_nanos())
        .map_err(|_| "monotonic clock is out of range".to_owned())?;
    Ok((wall, mono))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Problem<'a> {
    contract: &'a str,
    schema_version: u64,
    code: &'a str,
    detail: &'a str,
}

fn problem(status: StatusCode, code: &str, detail: &str) -> Response {
    json_response(
        status,
        &Problem {
            contract: "joshi.core.problem",
            schema_version: 1,
            code,
            detail,
        },
    )
}

fn json_response(status: StatusCode, value: &impl Serialize) -> Response {
    match serde_json::to_vec(value) {
        Ok(bytes) => {
            let mut response = Response::new(axum::body::Body::from(bytes));
            *response.status_mut() = status;
            response.headers_mut().insert(
                header::CONTENT_TYPE,
                HeaderValue::from_static("application/json"),
            );
            response
                .headers_mut()
                .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
            response
        }
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
