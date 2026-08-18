//! One-shot, offline-only pairing and Cockpit V2 route witness for the G0 fixture.
//!
//! This is not a browser-presentation or product-use witness. It exercises the real local HTTP
//! router in-process against an already completed fixture catalog, then proves restart
//! invalidation and exact publication readback without serializing a code or capability.

use crate::{
    pairing::OrdinaryPairingError,
    service::{CoreService, PairingCapability, PairingCapabilityGenerationError},
    wave5_g0::offline_fixture_store_config,
};
use axum::{
    Router,
    body::{Body, to_bytes},
    http::{Request, Response, StatusCode},
};
use joshi_admission::Sha256Digest;
use joshi_domain::StableString;
use joshi_pairing::{
    PairingConfig, PairingOccurrenceKind, PairingOrigin, PairingScope, pairing_occurrence_id,
};
use joshi_store::{SqliteStore, StoreError, StoreMode};
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;
use tower::ServiceExt as _;
use zeroize::Zeroizing;

const ORIGIN: &str = "http://127.0.0.1:8787";
const MAX_RESPONSE_BYTES: usize = 4 * 1024 * 1024;

/// Exact, secret-free result of the in-process pairing and immutable-open smoke walk.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct G0InspectorSmokeReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub publication_id: String,
    pub publication_digest: String,
    pub head_digest: String,
    pub pairing_occurrence_id: String,
    pub pairing_occurrence_digest: String,
    pub session_id: String,
    pub route_response_digest: String,
    pub route_response_byte_length: u64,
    pub reopened_response_digest: String,
    pub paired_route_read_closed: bool,
    pub restart_old_capability_refused: bool,
    pub fresh_pairing_reopen_closed: bool,
    pub full_offline_fault_walk: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

#[derive(Debug, Error)]
pub enum G0InspectorSmokeError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Pairing(#[from] OrdinaryPairingError),
    #[error(transparent)]
    PairingGeneration(#[from] PairingCapabilityGenerationError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Protocol(#[from] joshi_pairing::PairingError),
    #[error("G0 inspector smoke invariant failed: {0}")]
    Invariant(&'static str),
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExchangeResponse {
    contract: String,
    schema_version: u16,
    session_id: String,
    origin: String,
    epoch: String,
    expires_at: String,
    scopes: Vec<PairingScope>,
    authority: String,
    capability: String,
}

/// Exercise durable pairing, exact Cockpit V2 HTTP open, restart invalidation, and fresh reopen.
///
/// The input state must already contain exactly one headed offline G0 fixture publication. No
/// network socket is opened. The report intentionally excludes all code/capability material.
///
/// # Errors
///
/// Refuses an ambiguous fixture, route/status/body mismatch, pairing lineage substitution, or
/// restart that accepts the prior process capability.
#[allow(clippy::too_many_lines)]
pub async fn run_g0_inspector_smoke(
    state: &Path,
) -> Result<G0InspectorSmokeReport, G0InspectorSmokeError> {
    let config = offline_fixture_store_config(state)
        .map_err(|_| G0InspectorSmokeError::Invariant("fixture store configuration is invalid"))?;
    let store = SqliteStore::open(config.clone(), StoreMode::SingleWriter)?;
    let headed = store.list_headed_cockpit_v2_publications_v1()?;
    let [(publication, head)] = headed.as_slice() else {
        return Err(G0InspectorSmokeError::Invariant(
            "fixture must contain exactly one headed Cockpit V2 publication",
        ));
    };
    let publication_id = publication.publication.publication_id.clone();
    let publication_digest = publication.publication.publication_digest.clone();
    let head_digest = head.head.head_digest.clone();
    drop(store);

    let origin = PairingOrigin::new(ORIGIN)?;
    let (core, pairing) = CoreService::with_sqlite_pairing(
        SqliteStore::open(config.clone(), StoreMode::SingleWriter)?,
        None,
        PairingCapability::generate_os_random()?,
        origin.clone(),
        PairingConfig::default(),
    )?;
    let issued = pairing.issue_code(vec![PairingScope::CockpitRead])?;
    let issued_ordinal = occurrence_ordinal(issued.metadata.occurrence_id.as_str())?;
    let consumed_id = pairing_occurrence_id(
        &origin,
        issued.metadata.epoch.get(),
        issued_ordinal
            .checked_add(1)
            .ok_or(G0InspectorSmokeError::Invariant("pairing ordinal overflow"))?,
    );
    let app = core.router();
    let exchange_response = exchange(&app, issued.code.as_str()).await?;
    if exchange_response.contract != "joshi.pairing.session"
        || exchange_response.schema_version != 1
        || exchange_response.origin != ORIGIN
        || exchange_response.epoch != issued.metadata.epoch.get().to_string()
        || exchange_response.authority != "read_only_no_execution"
        || exchange_response.scopes != [PairingScope::CockpitRead]
        || exchange_response.expires_at.is_empty()
    {
        return Err(G0InspectorSmokeError::Invariant(
            "pairing exchange response differs from its issued scope/origin/epoch",
        ));
    }
    let session_id = exchange_response.session_id.clone();
    let capability = Zeroizing::new(exchange_response.capability);
    let route = format!(
        "/api/v1/cockpit-v2/publications/{}",
        publication_id.as_str()
    );
    let opened = send(
        &app,
        authorized_request("GET", &route, capability.as_str(), Body::empty())?,
    )
    .await;
    if opened.status() != StatusCode::OK {
        return Err(G0InspectorSmokeError::Invariant(
            "fresh pairing did not open the exact Cockpit V2 route",
        ));
    }
    let opened_bytes = response_bytes(opened).await?;
    validate_open_body(
        &opened_bytes,
        publication_id.as_str(),
        publication_digest.as_str(),
        head_digest.as_str(),
    )?;
    let route_response_digest = Sha256Digest::of_bytes(&opened_bytes);
    let route_response_byte_length = u64::try_from(opened_bytes.len())
        .map_err(|_| G0InspectorSmokeError::Invariant("route response length overflow"))?;
    drop(app);
    drop(pairing);

    let (restarted_core, restarted_pairing) = CoreService::with_sqlite_pairing(
        SqliteStore::open(config.clone(), StoreMode::SingleWriter)?,
        None,
        PairingCapability::generate_os_random()?,
        origin.clone(),
        PairingConfig::default(),
    )?;
    let restarted_app = restarted_core.router();
    let old_capability = send(
        &restarted_app,
        authorized_request("GET", &route, capability.as_str(), Body::empty())?,
    )
    .await;
    if old_capability.status() != StatusCode::UNAUTHORIZED {
        return Err(G0InspectorSmokeError::Invariant(
            "restart accepted a prior-process pairing capability",
        ));
    }
    drop(capability);

    let reopened_issue = restarted_pairing.issue_code(vec![PairingScope::CockpitRead])?;
    let reopened_exchange = exchange(&restarted_app, reopened_issue.code.as_str()).await?;
    let reopened_capability = Zeroizing::new(reopened_exchange.capability);
    let reopened = send(
        &restarted_app,
        authorized_request("GET", &route, reopened_capability.as_str(), Body::empty())?,
    )
    .await;
    if reopened.status() != StatusCode::OK {
        return Err(G0InspectorSmokeError::Invariant(
            "fresh post-restart pairing did not reopen the publication",
        ));
    }
    let reopened_bytes = response_bytes(reopened).await?;
    if reopened_bytes != opened_bytes {
        return Err(G0InspectorSmokeError::Invariant(
            "post-restart Cockpit V2 route response changed bytes",
        ));
    }
    drop(reopened_capability);
    drop(restarted_app);
    drop(restarted_pairing);

    let store = SqliteStore::open(config, StoreMode::ReadOnly)?;
    let pairing_occurrence =
        store
            .load_pairing_occurrence_v1(&consumed_id)?
            .ok_or(G0InspectorSmokeError::Invariant(
                "consumed pairing occurrence was absent after restart",
            ))?;
    if pairing_occurrence.occurrence.kind != PairingOccurrenceKind::Consumed
        || pairing_occurrence
            .occurrence
            .session_id
            .as_ref()
            .map(StableString::as_str)
            != Some(session_id.as_str())
        || pairing_occurrence.occurrence.origin != origin
    {
        return Err(G0InspectorSmokeError::Invariant(
            "consumed pairing occurrence differs from the route session",
        ));
    }
    let reopened_publication = store
        .load_cockpit_v2_publication_v1(&publication_id)?
        .ok_or(G0InspectorSmokeError::Invariant(
            "publication was absent after pairing restart",
        ))?;
    let reopened_head =
        store
            .load_cockpit_v2_head_v1(&publication_id)?
            .ok_or(G0InspectorSmokeError::Invariant(
                "head was absent after pairing restart",
            ))?;
    if reopened_publication.publication.publication_digest != publication_digest
        || reopened_head.head.head_digest != head_digest
    {
        return Err(G0InspectorSmokeError::Invariant(
            "publication/head changed across paired restart",
        ));
    }

    Ok(G0InspectorSmokeReport {
        contract: "joshi.wave5.g0_inspector_smoke",
        schema_version: 1,
        authority: "read_only_no_execution",
        status: "useful_partial",
        publication_id: publication_id.to_string(),
        publication_digest: publication_digest.to_string(),
        head_digest: head_digest.to_string(),
        pairing_occurrence_id: consumed_id.to_string(),
        pairing_occurrence_digest: pairing_occurrence.document_digest.to_string(),
        session_id,
        route_response_digest: route_response_digest.to_string(),
        route_response_byte_length,
        reopened_response_digest: Sha256Digest::of_bytes(&reopened_bytes).to_string(),
        paired_route_read_closed: true,
        restart_old_capability_refused: true,
        fresh_pairing_reopen_closed: true,
        full_offline_fault_walk: false,
        browser_presented: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn occurrence_ordinal(value: &str) -> Result<u64, G0InspectorSmokeError> {
    value
        .rsplit_once('-')
        .and_then(|(_, ordinal)| ordinal.parse().ok())
        .filter(|ordinal| *ordinal > 0)
        .ok_or(G0InspectorSmokeError::Invariant(
            "issued pairing occurrence has no positive terminal ordinal",
        ))
}

async fn exchange(app: &Router, code: &str) -> Result<ExchangeResponse, G0InspectorSmokeError> {
    let body = serde_json::json!({
        "contract": "joshi.pairing.exchange",
        "schemaVersion": 1,
        "oneTimeCode": code,
    });
    let response = send(
        app,
        Request::builder()
            .method("POST")
            .uri("/api/v1/pairing/exchange")
            .header("content-type", "application/json")
            .header("host", "127.0.0.1:8787")
            .header("origin", ORIGIN)
            .header("sec-fetch-site", "same-origin")
            .header("sec-fetch-mode", "cors")
            .header("sec-fetch-dest", "empty")
            .body(Body::from(serde_json::to_vec(&body)?))
            .map_err(|_| {
                G0InspectorSmokeError::Invariant("exchange request construction failed")
            })?,
    )
    .await;
    if response.status() != StatusCode::OK {
        return Err(G0InspectorSmokeError::Invariant(
            "one-time pairing exchange route refused the issued code",
        ));
    }
    Ok(serde_json::from_slice(&response_bytes(response).await?)?)
}

fn authorized_request(
    method: &str,
    uri: &str,
    capability: &str,
    body: Body,
) -> Result<Request<Body>, G0InspectorSmokeError> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header("host", "127.0.0.1:8787")
        .header("sec-fetch-site", "same-origin")
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .header("x-joshi-pairing-token", capability)
        .body(body)
        .map_err(|_| G0InspectorSmokeError::Invariant("authorized request construction failed"))
}

async fn send(app: &Router, request: Request<Body>) -> Response<Body> {
    match app.clone().oneshot(request).await {
        Ok(response) => response,
        Err(error) => match error {},
    }
}

async fn response_bytes(response: Response<Body>) -> Result<Vec<u8>, G0InspectorSmokeError> {
    to_bytes(response.into_body(), MAX_RESPONSE_BYTES)
        .await
        .map(|bytes| bytes.to_vec())
        .map_err(|_| G0InspectorSmokeError::Invariant("HTTP response body read failed"))
}

fn validate_open_body(
    bytes: &[u8],
    publication_id: &str,
    publication_digest: &str,
    head_digest: &str,
) -> Result<(), G0InspectorSmokeError> {
    let value: serde_json::Value = serde_json::from_slice(bytes)?;
    if value["contract"] != "joshi.core.cockpit_v2_open"
        || value["authority"] != "read_only_no_execution"
        || value["schemaVersion"] != 1
        || value["publication"]["publicationId"] != publication_id
        || value["publication"]["publicationDigest"] != publication_digest
        || value["head"]["headDigest"] != head_digest
    {
        return Err(G0InspectorSmokeError::Invariant(
            "Cockpit V2 route body differs from the exact headed publication",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn real_pairing_route_reopens_exact_fixture_and_never_promotes_product() {
        let state = tempfile::tempdir().expect("temporary inspector smoke state");
        crate::wave5_g0::run_wave5_g0_source_publication(state.path())
            .expect("G0 fixture component");
        let report = run_g0_inspector_smoke(state.path())
            .await
            .expect("G0 inspector smoke");
        assert!(report.paired_route_read_closed);
        assert!(report.restart_old_capability_refused);
        assert!(report.fresh_pairing_reopen_closed);
        assert_eq!(
            report.route_response_digest,
            report.reopened_response_digest
        );
        assert!(!report.full_offline_fault_walk);
        assert!(!report.browser_presented);
        assert!(!report.product_qualified);
        assert!(!report.live_qualified);
    }
}
