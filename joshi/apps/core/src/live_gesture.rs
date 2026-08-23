//! One operator gesture over a real, store-derived surface, proved across a restart.
//!
//! The gesture is the hold: the single keystroke Glass binds to `;`, which marks the coin on
//! screen so a feed that forgets cannot take it away again. The walk mounts a copy of a real
//! catalog, derives the exact Glass scene from the observations a provider actually sent, serves
//! it through the ordinary paired loopback route, holds one real mint through the same HTTP route
//! and with the same canonical payload bytes the browser sends, then drops everything and reopens
//! the catalog read-only to show the act coming back bound to the same scene bytes.
//!
//! What this walk does not claim: that a human saw pixels. It proves byte identity between what
//! the route served, what the act named, and what the store retained. An attached-browser witness
//! is a separate slice.

use crate::{
    live_surface::{
        LiveSurfaceError, LiveSurfaceOptions, LiveSurfaceReport, derive_live_surface,
        derive_live_surface_with, source_identity,
    },
    pairing::OrdinaryPairingError,
    service::{CoreService, PairingCapability, PairingCapabilityGenerationError},
};
use axum::{
    Router,
    body::{Body, to_bytes},
    http::{Request, Response, StatusCode},
};
use joshi_domain::{CommitSeq, SceneId, StableString, UtcTimestamp};
use joshi_operator::ValidatedGlassViewV1;
use joshi_pairing::{PairingConfig, PairingOrigin, PairingScope};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fmt::Write as _,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};
use thiserror::Error;
use tower::ServiceExt as _;
use zeroize::Zeroizing;

const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

/// Where a mounted live surface keeps its writable overlay of a real catalog.
#[must_use]
pub fn overlay_root(state: &Path) -> PathBuf {
    state.join("live-surface")
}

/// Store configuration for a real catalog directory that this process never writes.
///
/// # Errors
///
/// Fails when the catalog identity is not a valid wire string.
pub fn source_catalog_config(catalog: &Path) -> Result<StoreConfig, LiveGestureError> {
    Ok(StoreConfig {
        catalog_path: catalog.join("catalog.sqlite"),
        blob_root: catalog.join("blobs"),
        export_root: catalog.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-live-source")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

/// Store configuration for the writable overlay that retains operator acts.
///
/// # Errors
///
/// Fails when the catalog identity is not a valid wire string.
pub fn overlay_catalog_config(state: &Path) -> Result<StoreConfig, LiveGestureError> {
    let root = overlay_root(state);
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-live-surface-overlay")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

/// A mounted live surface: a writable overlay of a real catalog plus its exact derived scene.
pub struct MountedLiveSurface {
    pub store: SqliteStore,
    pub view: ValidatedGlassViewV1,
    pub surface: LiveSurfaceReport,
    pub catalog_schema: String,
}

/// Copies a real catalog into a writable overlay and derives its exact Glass scene.
///
/// The source catalog is opened read-only and copied through `SQLite`'s consistent backup API;
/// sibling writers of the real catalog are never disturbed and the original is never migrated.
///
/// # Errors
///
/// Fails on an unusable overlay, migration drift, or any derivation refusal.
pub fn mount_live_surface(
    catalog: &Path,
    state: &Path,
    source_id: &str,
) -> Result<MountedLiveSurface, LiveGestureError> {
    mount_live_surface_with(catalog, state, source_id, &LiveSurfaceOptions::default())
}

/// Copies a real catalog into a writable overlay and derives its exact Glass scene, honouring
/// what the operator stated about bytes the catalog cannot attribute on its own.
///
/// # Errors
///
/// Fails on an unusable overlay, migration drift, or any derivation refusal.
pub fn mount_live_surface_with(
    catalog: &Path,
    state: &Path,
    source_id: &str,
    options: &LiveSurfaceOptions,
) -> Result<MountedLiveSurface, LiveGestureError> {
    let overlay = overlay_catalog_config(state)?;
    match fs::symlink_metadata(&overlay.catalog_path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(LiveGestureError::Invariant(
                    "live surface overlay is not a regular file",
                ));
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let source = SqliteStore::open(source_catalog_config(catalog)?, StoreMode::ReadOnly)?;
            source.backup_to(&overlay.catalog_path)?;
            drop(source);
            copy_blob_tree(&catalog.join("blobs"), &overlay.blob_root)?;
        }
        Err(error) => return Err(LiveGestureError::Io(error.to_string())),
    }
    let mut store = SqliteStore::open(overlay, StoreMode::SingleWriter)?;
    let migration = store.migrate(now()?)?;
    let source = source_identity(source_id)?;
    let derivation = derive_live_surface_with(&store, &source, None, options)?;
    Ok(MountedLiveSurface {
        store,
        view: derivation.view,
        surface: derivation.report,
        catalog_schema: format!("joshi.sqlite.v{}", migration.current),
    })
}

/// Exact, secret-free result of one keyboard-shaped mark over a real store-derived surface.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct LiveGestureReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub catalog_schema: String,
    pub surface: LiveSurfaceReport,
    pub pairing_session_id: String,
    /// Digest of the exact bytes the paired snapshot route served.
    pub served_snapshot_digest: String,
    pub served_view_digest: String,
    pub subject_mint: String,
    pub command_id: String,
    pub command_kind: &'static str,
    /// The frozen operator label that makes this act a hold rather than any other focus record.
    pub command_ui_label: &'static str,
    pub command_commit_seq: String,
    pub command_status: u16,
    pub retry_status: u16,
    pub retry_commit_seq: String,
    /// Scene view digest read back out of the reopened catalog, recomputed from stored bytes.
    pub reopened_scene_view_digest: String,
    pub reopened_snapshot_digest: String,
    pub reopened_command_commit_seq: String,
    pub reopened_command_subject: String,
    pub rederived_scene_id: String,
    pub rederived_view_digest: String,
    pub scene_bound_to_served_bytes: bool,
    pub rederivation_is_stable: bool,
    pub restart_readback_closed: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub ceiling: &'static str,
}

/// Mount a real catalog, hold one real mint through the paired route, restart, and read it back.
///
/// # Errors
///
/// Refuses any route status, digest, binding, ordering or readback mismatch.
#[allow(clippy::too_many_lines)] // The ordered four-clause walk is clearer in one visible closure.
pub async fn run_live_gesture_walk(
    catalog: &Path,
    state: &Path,
    source_id: &str,
    origin: &str,
) -> Result<LiveGestureReport, LiveGestureError> {
    let mounted = mount_live_surface(catalog, state, source_id)?;
    let surface = mounted.surface.clone();
    let catalog_schema = mounted.catalog_schema.clone();
    let view_digest = mounted.view.digest().to_string();
    let scene_id = mounted.view.scene_id().to_string();
    let view_bytes = mounted.view.canonical_bytes().to_vec();
    let subject_mint = first_candidate(&mounted.view)?;

    let pairing_origin = PairingOrigin::new(origin.to_owned())?;
    let (core, launcher) = CoreService::with_sqlite_pairing_mounting(
        mounted.store,
        None,
        PairingCapability::generate_os_random()?,
        pairing_origin,
        PairingConfig::default(),
        Some(mounted.view),
    )?;
    let issued = launcher.issue_code(vec![
        PairingScope::CockpitRead,
        PairingScope::OperatorEvidenceWrite,
    ])?;
    let app = core.router();
    let session = exchange(&app, origin, issued.code.as_str()).await?;
    let capability = Zeroizing::new(session.capability);

    let route = format!("/api/v1/glass/snapshot?mode=witnessed&basisSceneId={scene_id}");
    let served = send(
        &app,
        authorized(origin, "GET", &route, capability.as_str(), Body::empty())?,
    )
    .await;
    if served.status() != StatusCode::OK {
        return Err(LiveGestureError::Invariant(
            "paired snapshot route did not serve the mounted live scene",
        ));
    }
    let served_bytes = response_bytes(served).await?;
    if !contains_exact_view(&served_bytes, &view_bytes) {
        return Err(LiveGestureError::Invariant(
            "served snapshot does not carry the exact derived view bytes",
        ));
    }
    let served_snapshot_digest = hex_digest(&served_bytes);
    let served_view_digest = qualified_digest(&view_bytes);
    if served_view_digest != view_digest {
        return Err(LiveGestureError::Invariant(
            "served view digest differs from the derived scene digest",
        ));
    }

    let issued_at = now()?;
    let command_id = format!("command-live-{}", short_digest(&served_bytes));
    let command_bytes = mark_command_bytes(
        &command_id,
        &scene_id,
        &view_digest,
        &subject_mint,
        issued_at,
    );
    let accepted = send(
        &app,
        authorized(
            origin,
            "POST",
            "/api/v1/operator/commands",
            capability.as_str(),
            Body::from(command_bytes.clone()),
        )?,
    )
    .await;
    let command_status = accepted.status().as_u16();
    if accepted.status() != StatusCode::ACCEPTED {
        let detail = response_bytes(accepted).await?;
        return Err(LiveGestureError::Refused(
            String::from_utf8_lossy(&detail).into_owned(),
        ));
    }
    let receipt: CommandReceiptBody = serde_json::from_slice(&response_bytes(accepted).await?)?;
    if receipt.scene.scene_id != scene_id || receipt.scene.view_digest != view_digest {
        return Err(LiveGestureError::Invariant(
            "operator receipt is not bound to the exact scene that was served",
        ));
    }
    let retried = send(
        &app,
        authorized(
            origin,
            "POST",
            "/api/v1/operator/commands",
            capability.as_str(),
            Body::from(command_bytes),
        )?,
    )
    .await;
    let retry_status = retried.status().as_u16();
    if retried.status() != StatusCode::OK {
        return Err(LiveGestureError::Invariant(
            "exact operator retry did not return the original durable closure",
        ));
    }
    let retry_receipt: CommandReceiptBody =
        serde_json::from_slice(&response_bytes(retried).await?)?;
    if retry_receipt.commit_seq != receipt.commit_seq {
        return Err(LiveGestureError::Invariant(
            "operator retry changed the durable commit sequence",
        ));
    }

    // Everything above dies here: the router, the writer lease, and the in-memory derived view.
    drop(app);
    drop(launcher);

    let reopened = SqliteStore::open(overlay_catalog_config(state)?, StoreMode::ReadOnly)?;
    let scene = reopened.load_scene(&SceneId::new(scene_id.clone())?)?;
    let reopened_scene_view_digest = qualified_digest(&scene.view_bytes);
    if scene.view_bytes != view_bytes {
        return Err(LiveGestureError::Invariant(
            "reopened scene bytes differ from the bytes the route served",
        ));
    }
    // Re-derive at the exact cutoff the served scene named. The overlay has since advanced (the
    // act itself is a commit), so "stable" means the same evidence cut re-renders byte for byte,
    // not that a later cut must agree with an earlier one.
    let cutoff = surface
        .catalog_commit
        .parse::<u64>()
        .map(CommitSeq::new)
        .map_err(|_| LiveGestureError::Invariant("derived catalog cutoff is not a commit"))?;
    let rederived = derive_live_surface(&reopened, &source_identity(source_id)?, Some(cutoff))?;
    let commands = reopened.operator_commands_for_scene_v1(&SceneId::new(scene_id.clone())?)?;
    let stored = commands
        .iter()
        .find(|stored| stored.command_id.as_str() == command_id)
        .ok_or(LiveGestureError::Invariant(
            "reopened catalog does not carry the committed operator act",
        ))?;
    if stored.scene_id.as_ref().map(StableString::as_str) != Some(scene_id.as_str())
        || stored.scene_view_sha256.as_deref() != Some(&reopened_scene_view_digest[7..])
        || stored.effect_ceiling != "observe_only"
        || stored.authority_class != "evidence_only"
    {
        return Err(LiveGestureError::Invariant(
            "reopened operator act is not bound to the same scene bytes",
        ));
    }
    let reopened_snapshot_digest = hex_digest(&snapshot_envelope(&scene.view_bytes));

    Ok(LiveGestureReport {
        contract: "joshi.core.live_gesture",
        schema_version: 1,
        authority: "read_only_no_execution",
        catalog_schema,
        surface,
        pairing_session_id: session.session_id,
        served_snapshot_digest: served_snapshot_digest.clone(),
        served_view_digest,
        subject_mint,
        command_id,
        command_kind: "record_focus",
        command_ui_label: HOLD_UI_LABEL,
        command_commit_seq: receipt.commit_seq.clone(),
        command_status,
        retry_status,
        retry_commit_seq: retry_receipt.commit_seq,
        reopened_scene_view_digest: reopened_scene_view_digest.clone(),
        reopened_snapshot_digest: reopened_snapshot_digest.clone(),
        reopened_command_commit_seq: stored.commit_seq.get().to_string(),
        reopened_command_subject: stored.subject_key.clone(),
        rederived_scene_id: rederived.report.scene_id.clone(),
        rederived_view_digest: rederived.report.view_digest.clone(),
        scene_bound_to_served_bytes: reopened_scene_view_digest == view_digest,
        rederivation_is_stable: rederived.report.scene_id == scene_id
            && rederived.report.view_digest == view_digest,
        restart_readback_closed: reopened_snapshot_digest == served_snapshot_digest
            && stored.commit_seq.get().to_string() == receipt.commit_seq,
        browser_presented: false,
        product_qualified: false,
        ceiling: "live_route_and_restart_closed_no_human_witness",
    })
}

pub(crate) fn first_candidate(view: &ValidatedGlassViewV1) -> Result<String, LiveGestureError> {
    view.choices()
        .first()
        .map(|choice| choice.candidate_id().to_string())
        .ok_or(LiveGestureError::Invariant(
            "derived live scene renders no candidate to mark",
        ))
}

/// The frozen label that distinguishes a hold from every other `record_focus` act.
///
/// Mirrors `HOLD_UI_LABEL` in `apps/glass/src/operator/holds.ts`. The label is the whole
/// discriminator: change it on one side only and every hold already in a catalog is orphaned.
const HOLD_UI_LABEL: &str = "Hold coin";

/// Builds exactly the canonical operator command bytes one Glass hold keystroke emits.
///
/// Every optional field is null on purpose, and that is the point of the gesture rather than an
/// omission in this walk. Asking for confidence, urgency, a reason or a note at the moment of
/// noticing is what made the coin unreachable in the first place; words come later, as their own
/// act, or never.
pub(crate) fn mark_command_bytes(
    command_id: &str,
    scene_id: &str,
    view_digest: &str,
    subject: &str,
    issued_at: UtcTimestamp,
) -> Vec<u8> {
    format!(
        concat!(
            r#"{{"contract":"joshi.operator.command","schemaVersion":1,"commandId":"{}","#,
            r#""idempotencyKey":"retry-{}","clientSessionId":"session-{}","clientCommandSeq":"1","#,
            r#""scene":{{"sceneId":"{}","viewDigest":"{}"}},"issuedAt":"{}","#,
            r#""clientClock":{{"clockId":"live-gesture-walk-clock","monotonicNs":"1"}},"#,
            r#""commandKind":"record_focus","subject":{{"kind":"candidate","key":"{}"}},"#,
            r#""payload":{{"context":{{"uiLabel":"{}","uiLabelVersion":"1","#,
            r#""confidencePpm":null,"urgency":null,"whyNow":null,"note":null}},"#,
            r#""dwellMilliseconds":null}},"#,
            r#""authorityClass":"evidence_only","effectCeiling":"observe_only"}}"#
        ),
        command_id,
        command_id,
        command_id,
        scene_id,
        view_digest,
        issued_at,
        subject,
        HOLD_UI_LABEL
    )
    .into_bytes()
}

fn contains_exact_view(snapshot: &[u8], view: &[u8]) -> bool {
    snapshot.windows(view.len()).any(|window| window == view)
}

fn snapshot_envelope(view_bytes: &[u8]) -> Vec<u8> {
    let digest = qualified_digest(view_bytes);
    let prefix = format!(
        "{{\"contract\":\"joshi.glass.snapshot\",\"schemaVersion\":1,\"snapshotDigest\":\"{digest}\",\"transport\":\"loopback\",\"recordingAuthority\":\"read_record_replay_only\",\"view\":"
    );
    let mut result = Vec::with_capacity(prefix.len() + view_bytes.len() + 1);
    result.extend_from_slice(prefix.as_bytes());
    result.extend_from_slice(view_bytes);
    result.push(b'}');
    result
}

pub(crate) fn qualified_digest(bytes: &[u8]) -> String {
    format!("sha256:{}", hex_digest(bytes))
}

pub(crate) fn hex_digest(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let mut hex = String::with_capacity(64);
    for byte in hasher.finalize() {
        write!(hex, "{byte:02x}").expect("string write is infallible");
    }
    hex
}

fn short_digest(bytes: &[u8]) -> String {
    hex_digest(bytes).chars().take(16).collect()
}

pub(crate) fn copy_blob_tree(source: &Path, destination: &Path) -> Result<(), LiveGestureError> {
    if !source.is_dir() {
        return Ok(());
    }
    fs::create_dir_all(destination).map_err(|error| LiveGestureError::Io(error.to_string()))?;
    for entry in fs::read_dir(source).map_err(|error| LiveGestureError::Io(error.to_string()))? {
        let entry = entry.map_err(|error| LiveGestureError::Io(error.to_string()))?;
        let kind = entry
            .file_type()
            .map_err(|error| LiveGestureError::Io(error.to_string()))?;
        let target = destination.join(entry.file_name());
        if kind.is_dir() {
            copy_blob_tree(&entry.path(), &target)?;
        } else if kind.is_file() {
            fs::copy(entry.path(), &target)
                .map_err(|error| LiveGestureError::Io(error.to_string()))?;
        }
    }
    Ok(())
}

pub(crate) fn now() -> Result<UtcTimestamp, LiveGestureError> {
    crate::wave5_readiness::now().map_err(|_| LiveGestureError::Invariant("clock is unavailable"))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ExchangeResponse {
    pub(crate) session_id: String,
    pub(crate) capability: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommandReceiptBody {
    scene: SceneReferenceBody,
    commit_seq: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SceneReferenceBody {
    scene_id: String,
    view_digest: String,
}

pub(crate) async fn exchange(
    app: &Router,
    origin: &str,
    code: &str,
) -> Result<ExchangeResponse, LiveGestureError> {
    let body = serde_json::json!({
        "contract": "joshi.pairing.exchange",
        "schemaVersion": 1,
        "oneTimeCode": code,
    });
    let request = Request::builder()
        .method("POST")
        .uri("/api/v1/pairing/exchange")
        .header("content-type", "application/json")
        .header("host", authority(origin))
        .header("origin", origin)
        .header("sec-fetch-site", "same-origin")
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .body(Body::from(serde_json::to_vec(&body)?))
        .map_err(|_| LiveGestureError::Invariant("exchange request construction failed"))?;
    let response = send(app, request).await;
    if response.status() != StatusCode::OK {
        return Err(LiveGestureError::Invariant(
            "one-time pairing exchange refused the issued code",
        ));
    }
    Ok(serde_json::from_slice(&response_bytes(response).await?)?)
}

pub(crate) fn authorized(
    origin: &str,
    method: &str,
    uri: &str,
    capability: &str,
    body: Body,
) -> Result<Request<Body>, LiveGestureError> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("host", authority(origin))
        .header("origin", origin)
        .header("sec-fetch-site", "same-origin")
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .header("x-joshi-pairing-token", capability);
    if method == "POST" {
        builder = builder.header("content-type", "application/json");
    }
    builder
        .body(body)
        .map_err(|_| LiveGestureError::Invariant("authorized request construction failed"))
}

fn authority(origin: &str) -> String {
    origin
        .split_once("://")
        .map_or_else(|| origin.to_owned(), |(_, authority)| authority.to_owned())
}

pub(crate) async fn send(app: &Router, request: Request<Body>) -> Response<Body> {
    match app.clone().oneshot(request).await {
        Ok(response) => response,
        Err(error) => match error {},
    }
}

pub(crate) async fn response_bytes(response: Response<Body>) -> Result<Vec<u8>, LiveGestureError> {
    to_bytes(response.into_body(), MAX_RESPONSE_BYTES)
        .await
        .map(|bytes| bytes.to_vec())
        .map_err(|_| LiveGestureError::Invariant("HTTP response body read failed"))
}

#[derive(Debug, Error)]
pub enum LiveGestureError {
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Surface(#[from] LiveSurfaceError),
    #[error(transparent)]
    Pairing(#[from] OrdinaryPairingError),
    #[error(transparent)]
    PairingGeneration(#[from] PairingCapabilityGenerationError),
    #[error(transparent)]
    Protocol(#[from] joshi_pairing::PairingError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("live gesture filesystem failure: {0}")]
    Io(String),
    #[error("operator route refused the scene-bound mark: {0}")]
    Refused(String),
    #[error("live gesture invariant failed: {0}")]
    Invariant(&'static str),
}

/// Offline fixture material shared by the live gesture and live journal restart walks.
#[cfg(test)]
pub(crate) mod live_fixture {
    use super::*;
    use joshi_admission::{SourceFrameInput, source_frames};
    use joshi_domain::OpenVariant;
    use joshi_sources::{
        ContentType, EvidenceContext, LogicalSourceLocator, ProviderEventTime, RawSourceFrame,
        SourceId as FrameSourceId, StreamClass, Transport, UnixMillis,
    };

    pub(crate) const FIXTURE_SOURCE: &str = "source.other.fixture";
    pub(crate) const FIXTURE_MINT: &str = "FixtureMint1111111111111111111111111111111111";

    pub(crate) fn instant(value: &str) -> UtcTimestamp {
        value.parse().expect("fixture instant")
    }

    /// A deliberately fabricated provider frame. It is shaped like a Solana `getTransaction`
    /// response so the route can be exercised offline; it is never labelled as a real provider.
    fn fixture_frame(ordinal: u64) -> RawSourceFrame {
        let body = serde_json::to_vec(&serde_json::json!({
            "jsonrpc": "2.0",
            "id": ordinal,
            "result": {
                "slot": 440_345_530_u64 + ordinal,
                "blockTime": 1_787_175_921_i64,
                "meta": {
                    "err": null,
                    "postTokenBalances": [{
                        "accountIndex": 3,
                        "mint": FIXTURE_MINT,
                        "owner": "FixtureOwner111111111111111111111111111111111",
                        "uiTokenAmount": {"amount": "0", "decimals": 6},
                    }],
                },
            },
        }))
        .expect("fixture body");
        RawSourceFrame {
            contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
            source: FrameSourceId::Other("fixture".to_owned()),
            transport: Transport::Http,
            stream_class: StreamClass::Backfill,
            direction: joshi_sources::FrameDirection::Inbound,
            content_type: ContentType::Json,
            received_at: UnixMillis(
                1_787_175_936_000 + i64::try_from(ordinal).expect("fixture ordinal"),
            ),
            connection_epoch: 1,
            sequence: ordinal,
            http_status: Some(200),
            safe_headers: Vec::new(),
            body: body.into(),
        }
    }

    fn fixture_context(ordinal: u64) -> EvidenceContext {
        EvidenceContext {
            occurrence_namespace: "live-gesture-fixture".to_owned(),
            redacted_request_fingerprint_material: format!("fixture:getTransaction:{ordinal}"),
            parent_acquisition_id: None,
            locator: LogicalSourceLocator::Fixture {
                name: "get_transaction".to_owned(),
            },
            source_variant: OpenVariant::known("fixture_response:getTransaction")
                .expect("fixture variant"),
            source_cursor: None,
            source_events: Vec::new(),
            provider_event_time: ProviderEventTime::Bounded {
                lower: instant("2026-08-19T21:45:21.000000Z"),
                upper: instant("2026-08-19T21:45:22.000000Z"),
                precision_us: 1_000_000,
            },
            chain_slot: Some(440_345_530 + ordinal),
            transaction_index: None,
            instruction_path: Vec::new(),
            log_index: None,
            finality: None,
            acquisition_started_at: instant("2026-08-19T21:45:35.000000Z"),
            requested_at: Some(instant("2026-08-19T21:45:35.000000Z")),
            monotonic_clock_id: "live-gesture-fixture-clock".to_owned(),
            acquisition_started_monotonic_ns: 1_000_000 + ordinal,
            received_monotonic_ns: 2_000_000 + ordinal,
            persisted_at: instant("2026-08-19T21:45:38.000000Z"),
        }
    }

    pub(crate) fn seed_catalog(catalog: &Path) -> Result<(), Box<dyn std::error::Error>> {
        commit_frames(catalog, 0..2, "batch-live-gesture-fixture", 3_000_000)
    }

    /// Append further fixture observations to an already-seeded catalog, as the keeper would:
    /// a later batch of new acquisitions, committed while a reader may be following.
    pub(crate) fn extend_catalog(
        catalog: &Path,
        ordinals: std::ops::Range<u64>,
        batch_id: &str,
    ) -> Result<(), Box<dyn std::error::Error>> {
        commit_frames(catalog, ordinals, batch_id, 4_000_000)
    }

    fn commit_frames(
        catalog: &Path,
        ordinals: std::ops::Range<u64>,
        batch_id: &str,
        monotonic_ns: u64,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut store =
            SqliteStore::open(source_catalog_config(catalog)?, StoreMode::SingleWriter)?;
        store.migrate(instant("2026-08-19T21:45:30.000000Z"))?;
        let frames = ordinals
            .map(|ordinal| SourceFrameInput {
                frame: fixture_frame(ordinal),
                context: fixture_context(ordinal),
            })
            .collect::<Vec<_>>();
        let batch = source_frames(
            frames,
            Vec::new(),
            Vec::new(),
            StableString::new(batch_id)?,
            instant("2026-08-19T21:45:39.000000Z"),
            StableString::new("live-gesture-fixture-writer")?,
            monotonic_ns,
        )?;
        batch.commit(&mut store)?;
        Ok(())
    }

    /// Commit one observation for a *different* source into the same catalog: the catalog's
    /// commit sequence advances while the followed source's evidence watermark does not.
    pub(crate) fn commit_bystander_frame(
        catalog: &Path,
        ordinal: u64,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut store =
            SqliteStore::open(source_catalog_config(catalog)?, StoreMode::SingleWriter)?;
        store.migrate(instant("2026-08-19T21:45:30.000000Z"))?;
        let mut frame = fixture_frame(ordinal);
        frame.source = FrameSourceId::Other("bystander".to_owned());
        let mut context = fixture_context(ordinal);
        context.redacted_request_fingerprint_material =
            format!("bystander:getTransaction:{ordinal}");
        let batch = source_frames(
            vec![SourceFrameInput { frame, context }],
            Vec::new(),
            Vec::new(),
            StableString::new(format!("batch-live-bystander-{ordinal}"))?,
            instant("2026-08-19T21:45:39.000000Z"),
            StableString::new("live-gesture-fixture-writer")?,
            5_000_000 + ordinal,
        )?;
        batch.commit(&mut store)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{
        live_fixture::{FIXTURE_MINT, FIXTURE_SOURCE, instant, seed_catalog},
        *,
    };

    #[tokio::test]
    async fn one_hold_keystroke_binds_the_exact_served_scene_and_survives_restart() {
        let root = tempfile::tempdir().expect("temporary live gesture root");
        let catalog = root.path().join("catalog");
        let state = root.path().join("state");
        seed_catalog(&catalog).expect("seeded fixture catalog");

        let report =
            run_live_gesture_walk(&catalog, &state, FIXTURE_SOURCE, "http://127.0.0.1:4173")
                .await
                .expect("live gesture walk");

        assert_eq!(report.subject_mint, FIXTURE_MINT);
        assert_eq!(report.command_kind, "record_focus");
        assert_eq!(report.command_ui_label, "Hold coin");
        assert_eq!(report.command_status, 202);
        assert_eq!(report.retry_status, 200);
        assert_eq!(report.command_commit_seq, report.retry_commit_seq);
        assert_eq!(
            report.command_commit_seq,
            report.reopened_command_commit_seq
        );
        assert_eq!(report.served_view_digest, report.reopened_scene_view_digest);
        assert_eq!(
            report.served_snapshot_digest,
            report.reopened_snapshot_digest
        );
        assert_eq!(report.reopened_command_subject, FIXTURE_MINT);
        assert!(report.scene_bound_to_served_bytes);
        assert!(report.rederivation_is_stable);
        assert!(report.restart_readback_closed);
        // No price series was observed, so none is rendered, and nothing here is a human witness.
        assert!(!report.surface.price_series_rendered);
        assert!(!report.browser_presented);
        assert!(!report.product_qualified);
    }

    #[tokio::test]
    async fn an_act_naming_an_unserved_scene_is_refused() {
        let root = tempfile::tempdir().expect("temporary refusal root");
        let catalog = root.path().join("catalog");
        let state = root.path().join("state");
        seed_catalog(&catalog).expect("seeded fixture catalog");
        let mounted =
            mount_live_surface(&catalog, &state, FIXTURE_SOURCE).expect("mounted live surface");
        let origin = "http://127.0.0.1:4173";
        let subject = first_candidate(&mounted.view).expect("candidate");
        let real_digest = mounted.view.digest().to_string();
        let (core, launcher) = CoreService::with_sqlite_pairing_mounting(
            mounted.store,
            None,
            PairingCapability::generate_os_random().expect("capability"),
            PairingOrigin::new(origin.to_owned()).expect("origin"),
            PairingConfig::default(),
            Some(mounted.view),
        )
        .expect("paired service");
        let issued = launcher
            .issue_code(vec![
                PairingScope::CockpitRead,
                PairingScope::OperatorEvidenceWrite,
            ])
            .expect("one-time code");
        let app = core.router();
        let session = exchange(&app, origin, issued.code.as_str())
            .await
            .expect("pairing exchange");
        let bytes = mark_command_bytes(
            "command-unserved-1",
            "scene-live-00000000000000000000000000000000",
            &real_digest,
            &subject,
            instant("2026-08-19T21:50:00.000000Z"),
        );
        let response = send(
            &app,
            authorized(
                origin,
                "POST",
                "/api/v1/operator/commands",
                &session.capability,
                Body::from(bytes),
            )
            .expect("request"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }
}
