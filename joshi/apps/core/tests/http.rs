use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt as _;
use joshi_admission::Sha256Digest;
use joshi_core::readiness::{WALKING_MATERIAL, run_offline_readiness};
use joshi_core::service::{CoreService, PairingCapability, ServiceError};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_operator::ValidatedOperatorCommandV1;
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use std::{path::Path, time::Duration};
use tower::ServiceExt as _;

const BODY: &[u8] = include_bytes!("../fixtures/companion_ingress_v1.json");
const RECEIPT_GOLDEN: &[u8] = include_bytes!("../fixtures/companion_receipt_v1.json");
const DIGEST: &str = "sha256:f585b52da69d89bc5ab7a8e88f7c0ecc6486b572edbd85d0b1816c3b5d60ae2e";
const INSTALLATION: &str = "60000000-0000-4000-8000-000000000001";
const PAIRING_TOKEN: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable")
}
fn time(value: &str) -> UtcTimestamp {
    value.parse().expect("time")
}
fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 1024,
        busy_timeout: Duration::from_secs(1),
        catalog_id: stable("local-test-catalog"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 1024 * 1024,
    }
}
fn store(root: &Path, migrate: bool) -> SqliteStore {
    let mut store = SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open");
    if migrate {
        store
            .migrate(time("2026-08-16T18:00:00.000000Z"))
            .expect("migrate");
    }
    store
}
fn request(body: Vec<u8>) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri("/v1/observations/pump-companion")
        .header("content-type", "application/json")
        .header(
            "x-joshi-companion-schema",
            "joshi.pump_companion.capture_batch",
        )
        .header("x-joshi-batch-digest", DIGEST)
        .header("x-joshi-pairing-token", PAIRING_TOKEN)
        .body(Body::from(body))
        .expect("request")
}
fn pairing() -> PairingCapability {
    PairingCapability::from_hex(PAIRING_TOKEN).expect("pairing")
}

fn prospective_launch_request(
    origin: Option<&str>,
    host: &str,
    fetch_site: &str,
    token: &str,
) -> Request<Body> {
    let mut request = Request::builder()
        .uri("/api/v1/session/launch")
        .header("host", host)
        .header("sec-fetch-site", fetch_site)
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .header("x-joshi-pairing-token", token);
    if let Some(origin) = origin {
        request = request.header("origin", origin);
    }
    request.body(Body::empty()).expect("launch request")
}

#[test]
fn pairing_capability_is_strict_and_debug_redacted() {
    assert_eq!(format!("{:?}", pairing()), "PairingCapability([REDACTED])");
    assert!(PairingCapability::from_hex(&PAIRING_TOKEN.to_uppercase()).is_err());
    assert!(PairingCapability::from_hex("cc").is_err());
}

#[tokio::test]
async fn ack_is_only_emitted_after_commit_and_exact_retry_is_idempotent() {
    let root = tempfile::tempdir().expect("tempdir");
    let app = CoreService::new(
        store(root.path(), true),
        Some(INSTALLATION.into()),
        pairing(),
    )
    .router();
    let first = app
        .clone()
        .oneshot(request(BODY.to_vec()))
        .await
        .expect("response");
    assert_eq!(first.status(), StatusCode::ACCEPTED);
    let bytes = first.into_body().collect().await.expect("body").to_bytes();
    assert_eq!(
        bytes.as_ref(),
        RECEIPT_GOLDEN.strip_suffix(b"\n").unwrap_or(RECEIPT_GOLDEN)
    );
    let receipt: serde_json::Value = serde_json::from_slice(&bytes).expect("receipt");
    assert_eq!(receipt["contract"], "joshi.pump_companion.ingest_receipt");
    assert_eq!(receipt["ingressBatchDigest"], DIGEST);
    assert_ne!(receipt["ingressBatchDigest"], receipt["durableBatchDigest"]);
    assert_ne!(
        receipt["durableBatchDigest"],
        receipt["storeAdmissionDigest"]
    );
    let retry = app.oneshot(request(BODY.to_vec())).await.expect("retry");
    assert_eq!(retry.status(), StatusCode::OK);
    let bytes = retry.into_body().collect().await.expect("body").to_bytes();
    let receipt: serde_json::Value = serde_json::from_slice(&bytes).expect("receipt");
    assert_eq!(receipt["status"], "idempotent");
}

#[tokio::test]
async fn invalid_ambiguous_or_precommit_requests_never_receive_a_success_status() {
    let root = tempfile::tempdir().expect("tempdir");
    let app = CoreService::new(
        store(root.path(), false),
        Some(INSTALLATION.into()),
        pairing(),
    )
    .router();
    let before_migration = app
        .clone()
        .oneshot(request(BODY.to_vec()))
        .await
        .expect("response");
    assert!(before_migration.status().is_server_error());

    let mut duplicate = String::from_utf8(BODY.to_vec()).expect("utf8");
    duplicate = duplicate.replace(
        "\"schemaVersion\":1",
        "\"schemaVersion\":1,\"schemaVersion\":1",
    );
    let duplicate_response = app
        .clone()
        .oneshot(request(duplicate.into_bytes()))
        .await
        .expect("response");
    assert_eq!(
        duplicate_response.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );

    let wrong_header = Request::builder()
        .method("POST")
        .uri("/v1/observations/pump-companion")
        .header("content-type", "application/json")
        .header(
            "x-joshi-companion-schema",
            "joshi.pump_companion.capture_batch",
        )
        .header("x-joshi-batch-digest", format!("sha256:{}", "0".repeat(64)))
        .header("x-joshi-pairing-token", PAIRING_TOKEN)
        .body(Body::from(BODY))
        .expect("request");
    let wrong = app.clone().oneshot(wrong_header).await.expect("response");
    assert_eq!(wrong.status(), StatusCode::BAD_REQUEST);

    let stream = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/glass/stream")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(stream.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn listener_rejects_nonloopback_binding_before_io() {
    let root = tempfile::tempdir().expect("tempdir");
    let service = CoreService::new(
        store(root.path(), true),
        Some(INSTALLATION.into()),
        pairing(),
    );
    let result = service.serve("0.0.0.0:0".parse().unwrap()).await;
    assert!(matches!(result, Err(ServiceError::NonLoopback(_))));
}

#[tokio::test]
async fn immutable_scene_is_returned_in_the_exact_glass_snapshot_envelope() {
    let root = tempfile::tempdir().expect("tempdir");
    let state = root.path().join("readiness");
    run_offline_readiness(&state, WALKING_MATERIAL).expect("walking scene");
    let config = StoreConfig {
        catalog_path: state.join("catalog.sqlite"),
        blob_root: state.join("blobs"),
        export_root: state.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: stable("joshi-offline-readiness"),
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    };
    let service_store = SqliteStore::open(config, StoreMode::SingleWriter).expect("reopen writer");
    let app = CoreService::new(service_store, None, pairing()).router();
    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/v1/glass/snapshot?mode=witnessed&basisSceneId=scene-readiness-1")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = response
        .into_body()
        .collect()
        .await
        .expect("body")
        .to_bytes();
    let view = include_bytes!("../fixtures/glass_readiness_v1.json");
    let view = view.strip_suffix(b"\n").unwrap_or(view);
    let digest = Sha256Digest::of_bytes(view);
    let mut expected = format!(
        "{{\"contract\":\"joshi.glass.snapshot\",\"schemaVersion\":1,\"snapshotDigest\":\"{digest}\",\"transport\":\"loopback\",\"recordingAuthority\":\"read_record_replay_only\",\"view\":"
    )
    .into_bytes();
    expected.extend_from_slice(view);
    expected.push(b'}');
    assert_eq!(bytes.as_ref(), expected);
}

#[tokio::test]
async fn operator_http_requires_pairing_and_allowed_origin_before_durable_acceptance() {
    let root = tempfile::tempdir().expect("tempdir");
    let state = root.path().join("operator-http");
    run_offline_readiness(&state, WALKING_MATERIAL).expect("walking scene");
    let config = StoreConfig {
        catalog_path: state.join("catalog.sqlite"),
        blob_root: state.join("blobs"),
        export_root: state.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: stable("joshi-offline-readiness"),
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    };
    let service_store = SqliteStore::open(config, StoreMode::SingleWriter).expect("reopen writer");
    let app = CoreService::new(service_store, None, pairing()).router();
    let command = include_str!("../fixtures/operator_readiness_v1.json")
        .trim_end()
        .replace("command-readiness-1", "command-http-2")
        .replace("retry-readiness-1", "retry-http-2")
        .replace("\"clientCommandSeq\":\"1\"", "\"clientCommandSeq\":\"2\"")
        .replace(
            "\"issuedAt\":\"2026-08-16T18:43:02.000000Z\"",
            "\"issuedAt\":\"2026-08-16T18:43:04.000000Z\"",
        )
        .replace("\"monotonicNs\":\"2000000\"", "\"monotonicNs\":\"3000000\"");
    let operator_request = |token: &str, origin: &str| {
        Request::builder()
            .method("POST")
            .uri("/api/v1/operator/commands")
            .header("content-type", "application/json")
            .header("origin", origin)
            .header("x-joshi-pairing-token", token)
            .body(Body::from(command.clone()))
            .expect("request")
    };
    ValidatedOperatorCommandV1::parse_exact(command.as_bytes()).expect("mutated command contract");
    let unpaired = app
        .clone()
        .oneshot(operator_request(
            "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "http://127.0.0.1:5173",
        ))
        .await
        .expect("unpaired response");
    assert_eq!(unpaired.status(), StatusCode::UNAUTHORIZED);
    let rejected_origin = app
        .clone()
        .oneshot(operator_request(PAIRING_TOKEN, "https://attacker.example"))
        .await
        .expect("origin response");
    assert_eq!(rejected_origin.status(), StatusCode::FORBIDDEN);
    let preflight = app
        .clone()
        .oneshot(
            Request::builder()
                .method("OPTIONS")
                .uri("/api/v1/operator/commands")
                .header("origin", "http://127.0.0.1:5173")
                .body(Body::empty())
                .expect("preflight"),
        )
        .await
        .expect("preflight response");
    assert_eq!(preflight.status(), StatusCode::METHOD_NOT_ALLOWED);
    assert!(
        preflight
            .headers()
            .get("access-control-allow-origin")
            .is_none()
    );

    let accepted = app
        .oneshot(operator_request(PAIRING_TOKEN, "http://127.0.0.1:5173"))
        .await
        .expect("accepted response");
    let status = accepted.status();
    let bytes = accepted
        .into_body()
        .collect()
        .await
        .expect("body")
        .to_bytes();
    assert_eq!(
        status,
        StatusCode::ACCEPTED,
        "unexpected response: {}",
        String::from_utf8_lossy(&bytes)
    );
    let receipt: serde_json::Value = serde_json::from_slice(&bytes).expect("receipt");
    assert_eq!(receipt["contract"], "joshi.store.command_receipt");
    assert_eq!(receipt["commandId"], "command-http-2");
    assert_eq!(receipt["scene"]["sceneId"], "scene-readiness-1");
    assert_eq!(receipt["status"], "accepted");
}

#[tokio::test]
async fn prospective_routes_require_attached_origin_and_never_ack_without_durable_binding() {
    let root = tempfile::tempdir().expect("tempdir");
    let app = CoreService::new(store(root.path(), true), None, pairing()).router();
    let missing_origin = app
        .clone()
        .oneshot(prospective_launch_request(
            None,
            "127.0.0.1:5173",
            "same-origin",
            PAIRING_TOKEN,
        ))
        .await
        .expect("missing-origin response");
    assert_eq!(missing_origin.status(), StatusCode::FORBIDDEN);
    let wrong_pairing = app
        .clone()
        .oneshot(prospective_launch_request(
            Some("http://127.0.0.1:5173"),
            "127.0.0.1:5173",
            "same-origin",
            "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        ))
        .await
        .expect("wrong-pairing response");
    assert_eq!(wrong_pairing.status(), StatusCode::UNAUTHORIZED);
    let unavailable = app
        .clone()
        .oneshot(prospective_launch_request(
            Some("http://127.0.0.1:5173"),
            "127.0.0.1:5173",
            "same-origin",
            PAIRING_TOKEN,
        ))
        .await
        .expect("unavailable response");
    assert_eq!(unavailable.status(), StatusCode::SERVICE_UNAVAILABLE);
    let unavailable_body = unavailable
        .into_body()
        .collect()
        .await
        .expect("unavailable body")
        .to_bytes();
    assert_eq!(
        unavailable_body.as_ref(),
        br#"{"contract":"joshi.core.problem","schemaVersion":1,"code":"prospective_session_not_registered","detail":"no exact durable launch is bound to this pairing capability"}"#,
    );

    let mismatched_host = app
        .clone()
        .oneshot(prospective_launch_request(
            Some("http://127.0.0.1:5173"),
            "localhost:5173",
            "same-origin",
            PAIRING_TOKEN,
        ))
        .await
        .expect("mismatched host response");
    assert_eq!(mismatched_host.status(), StatusCode::FORBIDDEN);

    let cross_site_metadata = app
        .clone()
        .oneshot(prospective_launch_request(
            Some("http://127.0.0.1:5173"),
            "127.0.0.1:5173",
            "cross-site",
            PAIRING_TOKEN,
        ))
        .await
        .expect("cross-site metadata response");
    assert_eq!(cross_site_metadata.status(), StatusCode::FORBIDDEN);

    let invalid_nomination = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/operator/prospective-nominations")
                .header("content-type", "application/json")
                .header("host", "127.0.0.1:5173")
                .header("origin", "http://127.0.0.1:5173")
                .header("sec-fetch-site", "same-origin")
                .header("sec-fetch-mode", "cors")
                .header("sec-fetch-dest", "empty")
                .header("x-joshi-pairing-token", PAIRING_TOKEN)
                .body(Body::from("{}"))
                .expect("nomination request"),
        )
        .await
        .expect("nomination response");
    assert_eq!(
        invalid_nomination.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
}

#[tokio::test]
async fn one_time_pairing_exchange_is_not_mounted_without_a_session_registry() {
    let root = tempfile::tempdir().expect("tempdir");
    let app = CoreService::new(store(root.path(), true), None, pairing()).router();
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/pairing/exchange")
                .header("content-type", "application/json")
                .header("host", "127.0.0.1:5173")
                .header("origin", "http://127.0.0.1:5173")
                .header("sec-fetch-site", "same-origin")
                .header("sec-fetch-mode", "cors")
                .header("sec-fetch-dest", "empty")
                .body(Body::from(
                    include_str!("../../../fixtures/pairing/exchange_request_v1.json").trim_end(),
                ))
                .expect("pairing exchange request"),
        )
        .await
        .expect("pairing exchange response");
    assert_eq!(response.status(), StatusCode::NOT_FOUND);
}
