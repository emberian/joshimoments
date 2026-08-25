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
use joshi_domain::{SceneId, StableString, UtcTimestamp, WireU64};
use joshi_operator::{OperatorCommandStatus, ValidatedGlassViewV1, ValidatedOperatorCommandV1};
use joshi_publication::CockpitPublicationId;
use joshi_store::{
    IdempotencyStatus, OperatorCaptureMetadata, SceneMode, SceneSourceMode, SqliteStore,
    StoredCockpitV2Head, StoredCockpitV2Publication,
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

use crate::{
    live_follow::{FollowError, FollowRuntime},
    pairing::{
        OrdinaryPairingError, OrdinaryPairingService, PairingAuthorizer, ordinary_pairing_router,
    },
    venue_readout::{MountedVenueReadouts, venue_readout_wire},
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
// JOSHI is a local, loopback, single-operator tool reading the operator's OWN catalog — there is
// no hostile remote client to defend against, so this is not a security bound. It exists only so
// a runaway derivation cannot hand a browser tab a response so large it freezes parsing it (the
// one genuinely physical limit), and to catch a dozens-of-GB accident. 256 MiB is far beyond any
// realistic board (5000 dense candidates ~= 40 MiB) and still chewable by a browser; the
// byte-aware candidate cap sits under it as the graceful runaway net, not a routine elider.
pub(crate) const MAX_GLASS_RESPONSE_BYTES: usize = 256 * 1024 * 1024;
const MAX_PRESENTATION_CLAIM_BYTES: usize = 64 * 1024;

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
    /// A scene this process derived from the store and is serving, before any act made it
    /// durable. The first operator act that names it commits the exact bytes it was served.
    live_surface: Option<Arc<ValidatedGlassViewV1>>,
    /// Pre-trade readouts this process assembled from one retained account capture.
    ///
    /// Mounted the same way the scene above is: derived once, held in memory, and served
    /// byte-identically for the life of the process. Absent means this core was started without a
    /// capture, which is a different answer from a coin the capture did not cover, and the two
    /// reach the cockpit under different problem codes.
    venue_readouts: Option<Arc<MountedVenueReadouts>>,
    /// A follow mount: many immutable scenes derived over time from a sibling-written catalog,
    /// listed by the scene feed. When present, scene reads and operator acts go through it; the
    /// store above then carries only pairing state. Nothing here is a mutable current-scene
    /// pointer — the feed lists facts and the client chooses.
    follow: Option<Arc<FollowRuntime>>,
    /// Where the operational hot-attention channel lives (`crate::hot_requests`): a file under
    /// the followed catalog's keeper root that a qualifying committed act appends its mint to,
    /// so a keeper watching that root taps the coin while attention is on it. `None` means this
    /// process serves no keeper-rooted catalog and qualifying acts stay durable-only — the
    /// degradation is silence-with-absence, never an error.
    hot_requests_path: Option<std::path::PathBuf>,
}

#[derive(Eq, PartialEq)]
pub struct PairingCapability([u8; 32]);

impl PairingCapability {
    /// Generates a process-local legacy guard from operating-system entropy.
    ///
    /// This is used only where ordinary pairing is the mounted browser authority but the older
    /// fail-closed handlers still require a nonpublic fallback value in the service state.
    ///
    /// # Errors
    ///
    /// Returns an error if the operating system cannot provide 32 random bytes.
    pub fn generate_os_random() -> Result<Self, PairingCapabilityGenerationError> {
        let mut bytes = [0_u8; 32];
        getrandom::fill(&mut bytes).map_err(|_| PairingCapabilityGenerationError)?;
        Ok(Self(bytes))
    }

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

#[derive(Clone, Copy, Debug, Eq, thiserror::Error, PartialEq)]
#[error("operating-system entropy is unavailable for the process-local pairing guard")]
pub struct PairingCapabilityGenerationError;

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
                live_surface: None,
                venue_readouts: None,
                follow: None,
                hot_requests_path: None,
            }),
        }
    }

    #[allow(clippy::too_many_arguments)] // The one private waist every mount states itself through.
    fn with_ordinary_pairing(
        store: Arc<Mutex<SqliteStore>>,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
        ordinary_pairing: Arc<OrdinaryPairingService>,
        live_surface: Option<Arc<ValidatedGlassViewV1>>,
        venue_readouts: Option<Arc<MountedVenueReadouts>>,
        follow: Option<Arc<FollowRuntime>>,
        hot_requests_path: Option<std::path::PathBuf>,
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
                live_surface,
                venue_readouts,
                follow,
                hot_requests_path,
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
    pub fn with_sqlite_pairing(
        store: SqliteStore,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
        origin: PairingOrigin,
        config: PairingConfig,
    ) -> Result<(Self, Arc<OrdinaryPairingService>), OrdinaryPairingError> {
        Self::with_sqlite_pairing_mounting(
            store,
            companion_installation_id,
            pairing,
            origin,
            config,
            None,
        )
    }

    /// Opt in to ordinary pairing while serving one scene this process derived from the store.
    ///
    /// The mounted view is served byte-for-byte by the snapshot route until an operator act names
    /// it, at which point the store retains those exact bytes atomically with the act. Nothing
    /// else can introduce a scene, so no act can ever be bound to bytes nobody was served.
    ///
    /// # Errors
    ///
    /// Fails unless the `SQLite` journal atomically begins and exactly reads back a higher epoch.
    pub fn with_sqlite_pairing_mounting(
        store: SqliteStore,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
        origin: PairingOrigin,
        config: PairingConfig,
        live_surface: Option<ValidatedGlassViewV1>,
    ) -> Result<(Self, Arc<OrdinaryPairingService>), OrdinaryPairingError> {
        Self::with_sqlite_pairing_mounting_venues(
            store,
            companion_installation_id,
            pairing,
            origin,
            config,
            live_surface,
            None,
            None,
        )
    }

    /// Mount a derived scene and, alongside it, the pre-trade readouts one retained account
    /// capture supports.
    ///
    /// The two mounts are independent on purpose. A scene says which coins the feed carried; a
    /// readout says what one of them would cost to trade, and those come from different bytes read
    /// at different times. Mounting a readout never changes a scene and can never make one appear.
    ///
    /// `hot_requests_path` is where a qualifying committed act appends its mint for a keeper to
    /// notice (`crate::hot_requests`); a static mount over a keeper-rooted catalog passes the
    /// file beside that catalog, and a throwaway or fixture mount passes `None`.
    ///
    /// # Errors
    ///
    /// Fails unless the `SQLite` journal atomically begins and exactly reads back a higher epoch.
    #[allow(clippy::too_many_arguments)] // Every mount is stated explicitly at the call site.
    pub fn with_sqlite_pairing_mounting_venues(
        store: SqliteStore,
        companion_installation_id: Option<String>,
        pairing: PairingCapability,
        origin: PairingOrigin,
        config: PairingConfig,
        live_surface: Option<ValidatedGlassViewV1>,
        venue_readouts: Option<MountedVenueReadouts>,
        hot_requests_path: Option<std::path::PathBuf>,
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
            live_surface.map(Arc::new),
            venue_readouts.map(Arc::new),
            None,
            hot_requests_path,
        );
        Ok((service, ordinary))
    }

    /// Mount a follow surface: many immutable scenes over a sibling-written catalog, plus the
    /// scene feed that lists them.
    ///
    /// The pairing store here is the follow mount's own small catalog. It deliberately carries no
    /// scenes and no acts: those live in the follow runtime's generations, which are replaced as
    /// the source advances, and replacing a generation must never invalidate the operator's
    /// session.
    ///
    /// # Errors
    ///
    /// Fails unless the `SQLite` journal atomically begins and exactly reads back a higher epoch.
    pub fn with_sqlite_pairing_following(
        pairing_store: SqliteStore,
        pairing: PairingCapability,
        origin: PairingOrigin,
        config: PairingConfig,
        follow: Arc<FollowRuntime>,
        venue_readouts: Option<MountedVenueReadouts>,
    ) -> Result<(Self, Arc<OrdinaryPairingService>), OrdinaryPairingError> {
        let store = Arc::new(Mutex::new(pairing_store));
        let ordinary = Arc::new(OrdinaryPairingService::production_with_shared_store(
            origin,
            config,
            store.clone(),
        )?);
        // The follow mount knows which catalog it reads, so the hot-attention channel needs no
        // extra configuration: it lives beside that catalog, in the keeper root.
        let hot_requests_path = follow.hot_requests_path();
        let service = Self::with_ordinary_pairing(
            store,
            None,
            pairing,
            ordinary.clone(),
            None,
            venue_readouts.map(Arc::new),
            Some(follow),
            hot_requests_path,
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
            .route("/api/v1/glass/scenes", get(scene_feed))
            .route("/api/v1/glass/scenes/{scene_id}", get(historical_scene))
            .route(
                "/api/v1/glass/scenes/{scene_id}/candidates/{candidate_id}",
                get(candidate_slice),
            )
            .route(
                "/api/v1/glass/venue-readouts/{mint}",
                get(venue_readout_for_mint),
            )
            .route(
                "/api/v1/operator/commands",
                post(operator_command).get(operator_command_readback),
            )
            .route("/api/v1/session/launch", get(prospective_session_launch))
            .route(
                "/api/v1/operator/prospective-nominations",
                post(prospective_nomination),
            )
            .route("/api/v1/operator/abstentions", post(explicit_abstention));
        if ordinary_product_routes_mounted {
            router = router
                .route(
                    "/api/v1/cockpit-v2/publications",
                    get(cockpit_v2_publication_index),
                )
                .route(
                    "/api/v1/cockpit-v2/publications/{publication_id}",
                    get(cockpit_v2_publication),
                )
                .route(
                    "/api/v1/cockpit-v2/presentations",
                    post(cockpit_v2_browser_presentation),
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CockpitV2IndexEntry {
    publication_id: String,
    publication_digest: String,
    publication_bytes_digest: String,
    publication_commit_seq: WireU64,
    head_digest: String,
    head_bytes_digest: String,
    head_commit_seq: WireU64,
    source_occurrence_id: String,
    supersedes_publication_id: Option<String>,
    eligible_count: WireU64,
    fact_count: WireU64,
    gap_count: WireU64,
    ceiling: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CockpitV2Index {
    contract: &'static str,
    schema_version: u16,
    authority: &'static str,
    items: Vec<CockpitV2IndexEntry>,
}

async fn cockpit_v2_publication_index(
    State(service): State<CoreService>,
    headers: HeaderMap,
) -> Response {
    match authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead) {
        OrdinaryAuthorization::Authorized(_) => {}
        OrdinaryAuthorization::Rejected(response) => return response,
        OrdinaryAuthorization::NotConfigured => {
            return problem(
                StatusCode::NOT_FOUND,
                "route_not_mounted",
                "ordinary Cockpit V2 publication access is not mounted",
            );
        }
    }
    let Ok(store) = service.inner.store.lock() else {
        return problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "reader_unavailable",
            "catalog lock is unavailable",
        );
    };
    let Ok(publications) = store.list_headed_cockpit_v2_publications_v1() else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "publication_index_readback_failed",
            "exact headed Cockpit V2 publication index failed durable readback",
        );
    };
    let mut items = Vec::with_capacity(publications.len());
    for (publication, head) in publications {
        let Ok(fact_count) = u64::try_from(publication.publication.manifest.source_facts.len())
        else {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "publication_index_too_large",
                "Cockpit V2 fact count exceeds its wire representation",
            );
        };
        let Ok(gap_count) = u64::try_from(publication.publication.manifest.gaps.len()) else {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "publication_index_too_large",
                "Cockpit V2 gap count exceeds its wire representation",
            );
        };
        items.push(CockpitV2IndexEntry {
            publication_id: publication.publication.publication_id.to_string(),
            publication_digest: publication.publication.publication_digest.to_string(),
            publication_bytes_digest: publication.publication_bytes_digest.to_string(),
            publication_commit_seq: WireU64::new(publication.commit_seq.get()),
            head_digest: head.head.head_digest.to_string(),
            head_bytes_digest: head.head_digest.to_string(),
            head_commit_seq: WireU64::new(head.commit_seq.get()),
            source_occurrence_id: publication.source_occurrence_id.to_string(),
            supersedes_publication_id: publication
                .publication
                .supersedes_publication_id
                .map(|value| value.to_string()),
            eligible_count: publication
                .publication
                .manifest
                .observed_universe
                .eligible_count,
            fact_count: WireU64::new(fact_count),
            gap_count: WireU64::new(gap_count),
            ceiling: "unverified_semantic",
        });
    }
    json_response(
        StatusCode::OK,
        &CockpitV2Index {
            contract: "joshi.core.cockpit_v2_index",
            schema_version: 1,
            authority: "read_only_no_execution",
            items,
        },
    )
}

async fn cockpit_v2_publication(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Path(publication_id): Path<String>,
) -> Response {
    match authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead) {
        OrdinaryAuthorization::Authorized(_) => {}
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

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CockpitV2BrowserPresentationReceipt<'a> {
    contract: &'static str,
    schema_version: u16,
    catalog_id: &'a str,
    catalog_schema: &'a str,
    client_presentation_id: &'a str,
    claim_digest: &'a str,
    claim_bytes_digest: &'a str,
    pairing_session_id: &'a str,
    publication_id: &'a str,
    store_commit_seq: WireU64,
    status: &'static str,
    authority: &'static str,
    ceiling: &'static str,
}

#[allow(clippy::too_many_lines)]
async fn cockpit_v2_browser_presentation(
    State(service): State<CoreService>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if body.is_empty() || body.len() > MAX_PRESENTATION_CLAIM_BYTES {
        return problem(
            StatusCode::PAYLOAD_TOO_LARGE,
            "presentation_claim_too_large",
            "Cockpit V2 browser presentation claim exceeds 64 KiB",
        );
    }
    if single_header_text(&headers, header::CONTENT_TYPE.as_str()).as_deref()
        != Some("application/json")
    {
        return problem(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "invalid_content_type",
            "Cockpit V2 browser presentation requires application/json",
        );
    }
    let Some(authorizer) = &service.inner.ordinary_pairing else {
        return problem(
            StatusCode::NOT_FOUND,
            "route_not_mounted",
            "ordinary Cockpit V2 presentation evidence is not mounted",
        );
    };
    if single_header_text(&headers, header::ORIGIN.as_str()).as_deref()
        != Some(authorizer.configured_origin().as_str())
    {
        return problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "presentation evidence requires the configured exact loopback Origin",
        );
    }
    let session = match authorize_ordinary_if_configured(
        &service,
        &headers,
        PairingScope::PresentationEvidenceWrite,
    ) {
        OrdinaryAuthorization::Authorized(descriptor) => descriptor,
        OrdinaryAuthorization::Rejected(response) => return response,
        OrdinaryAuthorization::NotConfigured => {
            return problem(
                StatusCode::NOT_FOUND,
                "route_not_mounted",
                "ordinary Cockpit V2 presentation evidence is not mounted",
            );
        }
    };
    let Ok(mut store) = service.inner.store.lock() else {
        return problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "presentation_writer_unavailable",
            "catalog writer lock is unavailable",
        );
    };
    let receipt = match store.commit_cockpit_v2_browser_presentation_v1(
        &body,
        &session,
        StableString::new(env!("CARGO_PKG_VERSION")).expect("package version is stable"),
    ) {
        Ok(receipt) => receipt,
        Err(joshi_store::StoreError::IdentityConflict { .. }) => {
            return problem(
                StatusCode::CONFLICT,
                "presentation_identity_conflict",
                "presentation idempotency identity already closes different exact bytes",
            );
        }
        Err(
            joshi_store::StoreError::InvalidBatch(_)
            | joshi_store::StoreError::MissingIdentity { .. },
        ) => {
            return problem(
                StatusCode::UNPROCESSABLE_ENTITY,
                "invalid_presentation_claim",
                "presentation claim does not close the exact paired headed publication",
            );
        }
        Err(_) => {
            return problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "presentation_commit_unavailable",
                "presentation evidence was not acknowledged because exact store readback failed",
            );
        }
    };
    json_response(
        StatusCode::OK,
        &CockpitV2BrowserPresentationReceipt {
            contract: "joshi.core.cockpit_v2_browser_presentation_receipt",
            schema_version: 1,
            catalog_id: receipt.catalog_id().as_str(),
            catalog_schema: receipt.catalog_schema().as_str(),
            client_presentation_id: receipt.client_presentation_id().as_str(),
            claim_digest: receipt.claim_digest().as_str(),
            claim_bytes_digest: receipt.claim_bytes_digest().as_str(),
            pairing_session_id: receipt.pairing_session_id().as_str(),
            publication_id: receipt.publication_id().as_str(),
            store_commit_seq: WireU64::new(receipt.commit_seq().get()),
            status: match receipt.status() {
                IdempotencyStatus::Accepted => "accepted",
                IdempotencyStatus::Idempotent => "idempotent",
            },
            authority: "read_only_no_execution",
            ceiling: "durable_browser_report_only_not_pixel_verified",
        },
    )
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
        OrdinaryAuthorization::Authorized(_) => return None,
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
    Authorized(joshi_pairing::PairingSessionDescriptor),
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
    let configured_origin = authorizer.configured_origin().as_str();
    let origin = single_header_text(headers, header::ORIGIN.as_str());
    let host = single_header_text(headers, header::HOST.as_str());
    if (headers.contains_key(header::ORIGIN) && origin.as_deref() != Some(configured_origin))
        || host
            .as_deref()
            .is_none_or(|host| !exact_loopback_same_origin(configured_origin, host))
    {
        return OrdinaryAuthorization::Rejected(problem(
            StatusCode::FORBIDDEN,
            "origin_rejected",
            "ordinary session requires the configured exact loopback Host and any supplied Origin",
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
    match authorizer.authorize(&capability, configured_origin, scope) {
        Ok(descriptor) => OrdinaryAuthorization::Authorized(descriptor),
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

/// The scene feed: every immutable scene a follow mount has derived, newest first, plus whether
/// the source catalog could actually be looked at.
///
/// This is a list of facts, not a mutable pointer. A client that wants a newer scene reads the
/// list and *chooses* to rebind through the ordinary scene routes; nothing served to it ever
/// changes underneath it. Each row carries the evidence watermark it was cut at, so a client
/// advances on new observations, never on a new scene identity. On a core without a follow mount
/// the feed states its own absence instead of serving an empty list.
async fn scene_feed(State(service): State<CoreService>, headers: HeaderMap) -> Response {
    if let OrdinaryAuthorization::Rejected(response) =
        authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    let Some(follow) = &service.inner.follow else {
        return problem(
            StatusCode::NOT_FOUND,
            "scene_feed_not_mounted",
            "this core serves one mounted scene and does not follow a catalog; the launch scene \
             identity is printed at startup and no newer scene will ever exist here",
        );
    };
    match follow.feed_wire() {
        Ok(wire) => json_response(StatusCode::OK, &wire),
        Err(_) => problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "reader_unavailable",
            "follow state lock is unavailable",
        ),
    }
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
    let (view_bytes, mode) = match resolve_scene_bytes(service, scene_id) {
        Ok(found) => found,
        Err(response) => return *response,
    };
    if let Some(expected) = expected_mode
        && expected != mode
    {
        return problem(
            StatusCode::CONFLICT,
            "mode_mismatch",
            "requested replay mode does not match immutable scene",
        );
    }
    let Some(snapshot) = snapshot_bytes(&view_bytes) else {
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

/// Resolve one immutable scene's exact canonical view bytes and mode, wherever this process
/// holds them (follow generations, durable store, or the mounted live surface).
fn resolve_scene_bytes(
    service: &CoreService,
    scene_id: &str,
) -> Result<(Vec<u8>, &'static str), Box<Response>> {
    let Ok(scene_id) = SceneId::new(scene_id) else {
        return Err(Box::new(problem(
            StatusCode::BAD_REQUEST,
            "invalid_scene",
            "scene identity is invalid",
        )));
    };
    // A follow mount serves every scene it has derived, durable bytes preferred; nothing else in
    // this process holds scenes then.
    if let Some(follow) = &service.inner.follow {
        return match follow.scene_bytes(&scene_id) {
            Ok(Some(found)) => Ok(found),
            Ok(None) => Err(Box::new(problem(
                StatusCode::NOT_FOUND,
                "scene_not_found",
                "immutable scene was not found",
            ))),
            Err(_) => Err(Box::new(problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "reader_unavailable",
                "follow state lock is unavailable",
            ))),
        };
    }
    let Ok(store) = service.inner.store.lock() else {
        return Err(Box::new(problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "reader_unavailable",
            "catalog lock is unavailable",
        )));
    };
    let stored = store.load_scene(&scene_id).ok();
    // A scene this process derived from the store is served from memory only until an
    // operator act makes it durable; afterwards the durable bytes answer, and they are the
    // same bytes.
    let mounted = service
        .inner
        .live_surface
        .as_ref()
        .filter(|view| *view.scene_id() == scene_id);
    match (&stored, mounted) {
        (Some(scene), _) => Ok((scene.view_bytes.clone(), mode_name(scene.mode))),
        (None, Some(view)) => Ok((view.canonical_bytes().to_vec(), glass_mode_name(view))),
        (None, None) => Err(Box::new(problem(
            StatusCode::NOT_FOUND,
            "scene_not_found",
            "immutable scene was not found",
        ))),
    }
}

/// Tolerant reader for slicing: only identity, clocks, and the candidate subtrees are read. The
/// full strict parse already happened when these canonical bytes were made.
#[derive(Deserialize)]
struct SliceView<'a> {
    #[serde(rename = "sceneId")]
    scene_id: String,
    #[serde(rename = "asOf", borrow)]
    as_of: SliceAsOf<'a>,
    #[serde(borrow)]
    payload: SlicePayload<'a>,
}
#[derive(Deserialize)]
struct SliceAsOf<'a> {
    #[serde(rename = "catalogCommit")]
    catalog_commit: &'a str,
    #[serde(rename = "renderedAt")]
    rendered_at: &'a str,
}
#[derive(Deserialize)]
struct SlicePayload<'a> {
    #[serde(borrow)]
    candidates: Vec<&'a serde_json::value::RawValue>,
}
#[derive(Deserialize)]
struct CandidateIdentity<'a> {
    id: &'a str,
}

/// One candidate of one immutable scene, sliced out verbatim.
///
/// A 962-subject board scene is a multi-megabyte read, and both the resident's analyst and the
/// coin page need exactly one coin from it. The slice carries the candidate's bytes verbatim
/// (borrowed from the canonical view, never re-serialized), the FULL view's digest so the slice
/// is always traceable to the exact scene it was cut from, and the rendered-candidate count so
/// a reader knows the denominator. A slice is a projection for reading; it has no digest of its
/// own and no act may bind to it — acts bind to the scene.
async fn candidate_slice(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Path((scene_id, candidate_id)): Path<(String, String)>,
) -> Response {
    if let OrdinaryAuthorization::Rejected(response) =
        authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    let (view_bytes, mode) = match resolve_scene_bytes(&service, &scene_id) {
        Ok(found) => found,
        Err(response) => return *response,
    };
    let Ok(view) = serde_json::from_slice::<SliceView<'_>>(&view_bytes) else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "scene_unreadable",
            "retained scene bytes did not parse as a Glass view",
        );
    };
    let rendered_count = view.payload.candidates.len();
    let found = view.payload.candidates.iter().enumerate().find(|(_, raw)| {
        serde_json::from_str::<CandidateIdentity<'_>>(raw.get())
            .is_ok_and(|identity| identity.id == candidate_id)
    });
    let Some((ordinal, raw)) = found else {
        return problem(
            StatusCode::NOT_FOUND,
            "candidate_not_rendered",
            &format!(
                "this scene renders {rendered_count} candidate(s) and none carries that id; an \
                 elided candidate remains observed in the catalog — falling out of render is a \
                 bound, never a denial"
            ),
        );
    };
    let digest = Sha256Digest::of_bytes(&view_bytes);
    let mut body = format!(
        "{{\"contract\":\"joshi.glass.candidate_slice\",\"schemaVersion\":1,\
         \"sceneId\":{},\"viewDigest\":\"{digest}\",\"mode\":\"{mode}\",\
         \"catalogCommit\":\"{}\",\"renderedAt\":\"{}\",\
         \"renderedCandidateCount\":\"{rendered_count}\",\
         \"renderedOrdinal\":\"{ordinal}\",\"candidate\":",
        serde_json::to_string(&view.scene_id).unwrap_or_else(|_| "\"\"".to_owned()),
        view.as_of.catalog_commit,
        view.as_of.rendered_at,
    );
    body.push_str(raw.get());
    body.push('}');
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

/// What one held coin's live venue state costs, for a mint the cockpit names.
///
/// The cockpit asks per held coin rather than receiving readouts inside the scene, because a scene
/// and a readout are two different observations of two different things: a scene is what the feed
/// carried at one commit, a readout is what an account read said at one slot. Folding the second
/// into the first would bind a coin's cost to a scene identity that had nothing to do with it, and
/// would make every re-read of a price rewrite the scene an operator act is bound to.
///
/// The two absences are kept apart on purpose. `venue_readouts_not_mounted` is this core having no
/// capture at all; `venue_readout_not_measured` is a capture that covers other coins and not this
/// one. A cockpit that collapsed them would render "we have not measured this" over what is really
/// "nothing has been measured at all".
async fn venue_readout_for_mint(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Path(mint): Path<String>,
) -> Response {
    if let OrdinaryAuthorization::Rejected(response) =
        authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    let Some(mounted) = service.inner.venue_readouts.as_ref() else {
        return problem(
            StatusCode::NOT_FOUND,
            "venue_readouts_not_mounted",
            "this core was started without a venue account capture, so it has measured no coin's \
             fee floor or clip interval; an empty answer here is not a claim about any coin",
        );
    };
    let Some(readout) = mounted.get(&mint) else {
        return problem(
            StatusCode::NOT_FOUND,
            "venue_readout_not_measured",
            "the mounted capture supports no venue readout for this mint; it may name no venue \
             for this coin, or the venue it named could not be assembled from the retained bytes",
        );
    };
    json_response(StatusCode::OK, &venue_readout_wire(readout))
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

pub(crate) fn glass_mode_name(view: &ValidatedGlassViewV1) -> &'static str {
    match view.mode() {
        joshi_operator::GlassMode::Witnessed => "witnessed",
        joshi_operator::GlassMode::KnowledgeCutoff => "knowledge_cutoff",
        joshi_operator::GlassMode::Retrospective => "retrospective",
    }
}

pub(crate) fn mode_name(mode: SceneMode) -> &'static str {
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
        OrdinaryAuthorization::Authorized(_) => {}
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
    // A follow mount routes the act to the generation that can re-check the scene it names: a
    // new act to the newest generation, an exact retry back to the generation that already holds
    // it, so the retry returns the original durable closure.
    if let Some(follow) = &service.inner.follow {
        return match follow.commit_act(
            &command,
            committed_at,
            committed_mono_ns,
            &service.inner.monotonic_clock_id,
        ) {
            Ok(receipt) => {
                let status = match receipt.status() {
                    OperatorCommandStatus::Accepted => StatusCode::ACCEPTED,
                    OperatorCommandStatus::Idempotent => StatusCode::OK,
                };
                note_hot_request(&service, &command, &receipt);
                json_response(status, &receipt)
            }
            Err(FollowError::LockPoisoned) => problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "writer_unavailable",
                "durable writer lock is unavailable",
            ),
            Err(error) => problem(
                StatusCode::UNPROCESSABLE_ENTITY,
                "operator_commit_rejected",
                &format!("scene-bound operator command was not committed: {error}"),
            ),
        };
    }
    let receipt = {
        let Ok(mut store) = service.inner.store.lock() else {
            return problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "writer_unavailable",
                "durable writer lock is unavailable",
            );
        };
        // The act carries the scene it was made over. When that scene is the one this process
        // derived and served, and nothing has retained it yet, the exact served bytes become
        // durable in the same transaction as the act. Otherwise the store re-reads the retained
        // bytes and refuses the act unless they hash to the digest the browser echoed back.
        let mounted = service
            .inner
            .live_surface
            .as_ref()
            .filter(|view| view.scene_id() == command.scene_id())
            .filter(|view| store.load_scene(view.scene_id()).is_err());
        let Ok(capture) = operator_capture(mounted.is_some(), &service.inner.monotonic_clock_id)
        else {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "capture_metadata_failed",
                "server capture metadata is unavailable",
            );
        };
        match store.commit_operator_v1(
            &command,
            mounted.map(AsRef::as_ref),
            &capture,
            committed_at,
            StableString::new(service.inner.monotonic_clock_id.clone())
                .expect("validated service clock"),
            committed_mono_ns,
            StableString::new(env!("CARGO_PKG_VERSION")).expect("valid build"),
        ) {
            Ok(value) => value,
            Err(error) => {
                return problem(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "operator_commit_rejected",
                    &format!("scene-bound operator command was not committed: {error}"),
                );
            }
        }
    };
    let status = match receipt.status() {
        OperatorCommandStatus::Accepted => StatusCode::ACCEPTED,
        OperatorCommandStatus::Idempotent => StatusCode::OK,
    };
    note_hot_request(&service, &command, &receipt);
    json_response(status, &receipt)
}

/// After a qualifying act is durable, append its mint to the operational hot-attention channel
/// (`crate::hot_requests`), so a keeper watching this catalog's root starts tapping the coin.
///
/// The act is already committed when this runs — including an exact idempotent retry, which
/// refreshes the hotness TTL exactly as a fresh act does. A channel failure is logged and never
/// surfaces into the response: the durable evidence is complete without the file.
fn note_hot_request(
    service: &CoreService,
    command: &ValidatedOperatorCommandV1,
    receipt: &joshi_operator::CommandReceiptV1,
) {
    let Some(path) = &service.inner.hot_requests_path else {
        return;
    };
    let Some(mint) = crate::hot_requests::qualifying_hot_mint(command) else {
        return;
    };
    if let Err(error) = crate::hot_requests::record_hot_request(
        path,
        &mint,
        command.kind().as_str(),
        command.command_id().as_str(),
        &receipt.commit_seq().get().to_string(),
        time::OffsetDateTime::now_utc(),
    ) {
        eprintln!(
            "hot-requests channel write failed for {mint} (the act itself is durable): {error}"
        );
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct OperatorReadbackQuery {
    scene_id: String,
}

/// One stored command as the readback route serves it. `None` only when the retained payload is
/// not exact canonical JSON, which the caller reports as corruption rather than skipping.
fn readback_command(
    scene_id: &SceneId,
    command: joshi_store::StoredOperatorCommandV1,
) -> Option<OperatorReadbackCommand> {
    let payload = String::from_utf8(command.payload).ok()?;
    let payload = serde_json::value::RawValue::from_string(payload).ok()?;
    Some(OperatorReadbackCommand {
        command_id: command.command_id.to_string(),
        commit_seq: WireU64::new(command.commit_seq.get()),
        scene: OperatorReadbackScene {
            scene_id: command
                .scene_id
                .as_ref()
                .map_or_else(|| scene_id.to_string(), ToString::to_string),
            view_digest: command
                .scene_view_sha256
                .map(|digest| format!("sha256:{digest}")),
        },
        client_session_id: command.client_session_id.to_string(),
        client_command_seq: WireU64::new(command.client_command_seq),
        idempotency_key: command.idempotency_key.to_string(),
        command_kind: command.command_kind,
        subject: OperatorReadbackSubject {
            kind: command.subject_kind,
            key: command.subject_key,
        },
        issued_at: command.issued_at,
        received_at: command.received_at,
        client_clock_id: command.client_clock_id,
        authority_class: command.authority_class,
        effect_ceiling: command.effect_ceiling,
        payload,
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct OperatorReadbackSubject {
    kind: String,
    key: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct OperatorReadbackScene {
    scene_id: String,
    /// Digest of the exact retained view bytes the command is bound to. `null` only when the
    /// stored command names a scene whose row the catalog no longer joins, which the surface
    /// must render as a stated gap rather than as a digest.
    view_digest: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct OperatorReadbackCommand {
    command_id: String,
    commit_seq: WireU64,
    scene: OperatorReadbackScene,
    client_session_id: String,
    client_command_seq: WireU64,
    idempotency_key: String,
    command_kind: String,
    subject: OperatorReadbackSubject,
    issued_at: UtcTimestamp,
    received_at: UtcTimestamp,
    client_clock_id: String,
    authority_class: String,
    effect_ceiling: String,
    /// The exact retained canonical payload bytes, spliced without re-encoding.
    payload: Box<serde_json::value::RawValue>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct OperatorReadback {
    contract: &'static str,
    schema_version: u16,
    authority: &'static str,
    scene_id: String,
    /// `durable` when the store retains the scene; `served_not_yet_durable` when this process
    /// derived and is serving it but no act has yet made it durable. The two are kept apart so
    /// an empty command list is never mistaken for a claim that nothing was ever said.
    scene_retention: &'static str,
    commands: Vec<OperatorReadbackCommand>,
}

/// Reads back every durable operator command bound to one immutable scene, in commit order.
///
/// This is the journal's query path and the held rail's reload path in one route: a hold, a
/// note, a journal entry, a disposition — every evidence act travels the same POST above, so one
/// read route returns all of them with their exact retained payload bytes. Serving stored bytes
/// unre-encoded keeps the operator's words verbatim; nothing is summarized or normalized here.
async fn operator_command_readback(
    State(service): State<CoreService>,
    headers: HeaderMap,
    Query(query): Query<OperatorReadbackQuery>,
) -> Response {
    if let OrdinaryAuthorization::Rejected(response) =
        authorize_ordinary_if_configured(&service, &headers, PairingScope::CockpitRead)
    {
        return response;
    }
    let Ok(scene_id) = SceneId::new(query.scene_id) else {
        return problem(
            StatusCode::BAD_REQUEST,
            "invalid_scene",
            "scene identity is invalid",
        );
    };
    // A follow mount's journal spans its retained generations: every act ever committed for this
    // scene, in the order its catalog retained it, whichever generation was current at the time.
    if let Some(follow) = &service.inner.follow {
        return match follow.readback(&scene_id) {
            Ok(Some((scene_retention, stored))) => {
                readback_response(&scene_id, scene_retention, stored)
            }
            Ok(None) => problem(
                StatusCode::NOT_FOUND,
                "scene_not_found",
                "immutable scene was not found",
            ),
            Err(FollowError::LockPoisoned) => problem(
                StatusCode::SERVICE_UNAVAILABLE,
                "reader_unavailable",
                "follow state lock is unavailable",
            ),
            Err(_) => problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "command_readback_failed",
                "durable operator commands failed exact readback",
            ),
        };
    }
    let Ok(store) = service.inner.store.lock() else {
        return problem(
            StatusCode::SERVICE_UNAVAILABLE,
            "reader_unavailable",
            "catalog lock is unavailable",
        );
    };
    let scene_retention = match store.load_scene(&scene_id) {
        Ok(_) => "durable",
        Err(joshi_store::StoreError::MissingIdentity { .. }) => {
            let mounted = service
                .inner
                .live_surface
                .as_ref()
                .is_some_and(|view| *view.scene_id() == scene_id);
            if !mounted {
                return problem(
                    StatusCode::NOT_FOUND,
                    "scene_not_found",
                    "immutable scene was not found",
                );
            }
            "served_not_yet_durable"
        }
        Err(_) => {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "scene_readback_failed",
                "retained scene failed durable readback",
            );
        }
    };
    let Ok(stored) = store.operator_commands_for_scene_v1(&scene_id) else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "command_readback_failed",
            "durable operator commands failed exact readback",
        );
    };
    readback_response(&scene_id, scene_retention, stored)
}

/// Serialize one scene's durable acts, exactly as retained, into the frozen readback envelope.
fn readback_response(
    scene_id: &SceneId,
    scene_retention: &'static str,
    stored: Vec<joshi_store::StoredOperatorCommandV1>,
) -> Response {
    let mut commands = Vec::with_capacity(stored.len());
    for command in stored {
        let Some(command) = readback_command(scene_id, command) else {
            return problem(
                StatusCode::INTERNAL_SERVER_ERROR,
                "command_payload_unreadable",
                "a retained command payload is not exact canonical JSON",
            );
        };
        commands.push(command);
    }
    let body = OperatorReadback {
        contract: "joshi.core.operator_command_readback",
        schema_version: 1,
        authority: "read_only_no_execution",
        scene_id: scene_id.to_string(),
        scene_retention,
        commands,
    };
    let Ok(bytes) = serde_json::to_vec(&body) else {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "readback_encoding_failed",
            "operator command readback response failed to encode",
        );
    };
    if bytes.len() > MAX_GLASS_RESPONSE_BYTES {
        return problem(
            StatusCode::INTERNAL_SERVER_ERROR,
            "readback_response_too_large",
            "operator command readback exceeds the bounded Glass response contract",
        );
    }
    let mut response = Response::new(axum::body::Body::from(bytes));
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

/// Capture metadata for the scene an act binds.
///
/// For an already durable scene this is inert: the store keeps the capture that was recorded when
/// the scene was retained. For a scene this process derived and served, the metadata says exactly
/// that: JOSHI rendered it from the catalog on the server clock domain, and no browser render
/// clock is claimed for bytes the browser did not compose.
pub(crate) fn operator_capture(
    mounting_derived_scene: bool,
    server_clock_id: &str,
) -> Result<OperatorCaptureMetadata, joshi_domain::WireStringError> {
    if mounting_derived_scene {
        return Ok(OperatorCaptureMetadata {
            client_scene_seq: 0,
            ui_build: StableString::new(format!("joshi-core-{}", env!("CARGO_PKG_VERSION")))?,
            source_mode: SceneSourceMode::Observatory,
            rendered_clock_id: StableString::new(server_clock_id)?,
            rendered_mono_ns: 0,
            screenshot_bytes: None,
        });
    }
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
