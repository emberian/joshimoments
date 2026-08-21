//! One bounded, read-only Pump product read carried all the way to a durable, restart-readable
//! versioned assertion.
//!
//! The binary performs exactly one documented `GET`, retains the exact response bytes through the
//! ordinary source-admission path, records an explicit schema-trust decision and an explicit
//! credential-path decision as assertions in the same immutable batch, derives one identity and
//! topology claim only when the schema was promoted, then drops the store, reopens it, and proves
//! the fact and the bytes that said so both survive.
//!
//! It constructs, signs, and submits nothing. Every route it can reach is a `GET`.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use joshi_domain::{StableString, UtcTimestamp};
use joshi_pump_adapter::{
    PreparedProductRead, ProductReadInput, close_receipt, prepare_direct_product_read,
};
use joshi_pump_api::{
    AuthenticatedPathDecision, ClientConfig, FetchOutcome, IdentityStore, LogicalRequest,
    NoSession, ProductIdentityClaimV1, PumpApiClient, RequestParameters, RouteId, SessionProvider,
    fingerprint_of_shape,
};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Parser)]
#[command(name = "joshi-pump-product-read")]
#[command(about = "One bounded documented Pump product read, admitted and read back after restart")]
struct Cli {
    /// SPL mint of the coin to read. It appears in the URL path and in the derived claim.
    #[arg(long)]
    mint: String,
    /// Durable working root: identity reservations, catalog, blobs, exports.
    #[arg(long)]
    state_dir: PathBuf,
    /// Reviewed-schema artifact. Omitting it forces an explicit quarantine refusal.
    #[arg(long)]
    review: Option<PathBuf>,
    /// Write the observed structural shape and fingerprint here for schema review.
    #[arg(long)]
    emit_shape: Option<PathBuf>,
    /// Write the exact serialized fetch outcome here, so offline tests can replay this read.
    #[arg(long)]
    emit_outcome: Option<PathBuf>,
    /// Hard ceiling on HTTP requests this process may make.
    #[arg(long, default_value_t = 2)]
    request_budget: usize,
}

#[tokio::main]
async fn main() {
    if let Err(error) = run(Cli::parse()).await {
        eprintln!("joshi-pump-product-read: {error}");
        std::process::exit(2);
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunReceipt {
    contract: &'static str,
    authority: &'static str,
    route_id: String,
    source_locator: String,
    request_fingerprint: String,
    http_status: Option<u16>,
    response_bytes: String,
    body_blob_id: String,
    observed_schema_fingerprint: Option<String>,
    schema_trust_outcome: String,
    schema_trust_reason: String,
    schema_review_id: Option<String>,
    authenticated_path: String,
    authenticated_path_reason: String,
    durable_batch_id: String,
    durable_logical_digest: String,
    store_admission_digest: String,
    through_commit_seq: String,
    admitted_observations: String,
    admitted_assertions: String,
    admitted_coverage_windows: String,
    admitted_coverage_gaps: String,
    identity_semantic_key: Option<String>,
    identity_claim_digest: Option<String>,
    identity_subject: Option<String>,
    identity_attributes: Option<Value>,
    reopened_integrity: String,
    reopened_external_blobs_checked: String,
    readback_assertion_ids: Vec<String>,
    readback_body_path: Option<String>,
    readback_body_bytes_equal_response: bool,
    readback_attributes_equal_claim: bool,
}

#[allow(clippy::too_many_lines)] // The whole acquire/admit/restart/read-back walk stays in one place.
async fn run(cli: Cli) -> Result<(), Box<dyn std::error::Error>> {
    let route = RouteId::CoinExact;
    let mut config = ClientConfig {
        request_budget: cli.request_budget,
        maximum_attempts: 1,
        response_limit_bytes: 512 * 1024,
        request_timeout: Duration::from_secs(20),
        ..ClientConfig::default()
    };
    config.enabled_routes = [route].into_iter().collect();

    let identity = IdentityStore::open(cli.state_dir.join("identity"))?;
    // A documented public product route. No session provider is configured, so the transport
    // client cannot attach credential material even if a route asked for it.
    let sessions: Arc<dyn SessionProvider> = Arc::new(NoSession);
    let client = PumpApiClient::new(config, identity.clone(), sessions)?;
    let request = LogicalRequest {
        route,
        parameters: RequestParameters {
            path: [("mint".to_owned(), cli.mint.clone())]
                .into_iter()
                .collect(),
            query: std::collections::BTreeMap::new(),
        },
    };
    let outcome: FetchOutcome = client.fetch(&request).await?;
    let outcome_bytes = serde_json::to_vec(&outcome)?;
    let decided_at = now_utc()?;

    if let Some(path) = cli.emit_shape.as_deref() {
        emit_shape(path, &outcome)?;
    }
    if let Some(path) = cli.emit_outcome.as_deref() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, &outcome_bytes)?;
    }

    let review_bytes = cli.review.as_deref().map(fs::read).transpose()?;
    let prepared = prepare_direct_product_read(&ProductReadInput {
        outcome_bytes: &outcome_bytes,
        review_bytes: review_bytes.as_deref(),
        authenticated_path: AuthenticatedPathDecision::NotPerformed,
        session_reason_code: "no_documented_authenticated_get_read_route_for_present_credential",
        session_detail: concat!(
            "This run read a documented public product route with no session provider configured. ",
            "The only Pump-family credential present on this host authenticates PumpPortal's ",
            "Lightning trading API, its wallet-creation route, and its WebSocket data stream; ",
            "none of those is a documented HTTP GET product read, and the trading siblings are ",
            "out of scope for a read-only lane. No pump.fun user session was available, so no ",
            "authenticated product route was attempted."
        ),
        durable_batch_id: &format!(
            "batch:pump-product-read:{}",
            outcome
                .request_group_id
                .trim_start_matches("reqgrp:pump-api:")
        ),
        committed_at: decided_at.parse::<UtcTimestamp>()?,
        committed_monotonic_ns: 1,
        decided_at: &decided_at,
    })?;

    let response_bytes = prepared
        .acquisition
        .body
        .exact_bytes()
        .ok_or("the completed read retained no exact body")?;

    let mut store = SqliteStore::open(store_config(&cli.state_dir)?, StoreMode::SingleWriter)?;
    store.migrate(decided_at.parse::<UtcTimestamp>()?)?;
    let receipt = prepared.prepared.admission_batch().commit(&mut store)?;
    let closed = close_receipt(&prepared.prepared, &receipt)?;
    prepared.prepared.acknowledge_direct(&identity, &receipt)?;
    drop(store);

    let reopened = SqliteStore::open(store_config(&cli.state_dir)?, StoreMode::ReadOnly)?;
    let verification = reopened.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" || verification.foreign_key_defects != 0 {
        return Err("reopened catalog failed verification".into());
    }
    let cutoff = verification.max_commit_seq;
    let mut readback_ids = Vec::new();
    let mut readback_claim = None;
    for key in [
        Some(prepared.trust_semantic_key()),
        Some(prepared.session_semantic_key()),
        prepared.identity_semantic_key(),
    ]
    .into_iter()
    .flatten()
    {
        let rows = reopened.effective_assertions_as_known(&key, cutoff)?;
        if rows.is_empty() {
            return Err(format!("semantic key {key} did not survive the restart").into());
        }
        for row in rows {
            readback_ids.push(row.assertion_id.to_string());
            if let Some(claim) = row.value.get("claim") {
                readback_claim = Some(serde_json::from_value::<ProductIdentityClaimV1>(
                    claim.clone(),
                )?);
            }
        }
    }
    readback_ids.sort();

    let mut readback_body_path = None;
    let mut body_equal = false;
    let mut attributes_equal = false;
    if let Some(claim) = readback_claim.as_ref() {
        let path = external_blob_path(&cli.state_dir, "public_source", &claim.body_blob_id)?;
        let bytes = fs::read(&path)?;
        body_equal = bytes == response_bytes;
        attributes_equal = attributes_match(&bytes, claim)?;
        readback_body_path = Some(path.display().to_string());
        if !body_equal || !attributes_equal {
            return Err("read-back provider bytes do not support the stored claim".into());
        }
    }
    drop(reopened);

    let receipt = RunReceipt {
        contract: "joshi.pump_product_read_run.v1",
        authority: "read_only_no_execution",
        route_id: prepared.acquisition.route_id.clone(),
        source_locator: prepared.acquisition.source_locator.clone(),
        request_fingerprint: prepared.acquisition.request_fingerprint.clone(),
        http_status: prepared.acquisition.http_status,
        response_bytes: response_bytes.len().to_string(),
        body_blob_id: prepared
            .acquisition
            .body
            .blob_id()
            .unwrap_or_default()
            .to_owned(),
        observed_schema_fingerprint: prepared.decision.observed_schema_fingerprint.clone(),
        schema_trust_outcome: format!("{:?}", prepared.decision.outcome).to_ascii_lowercase(),
        schema_trust_reason: prepared.decision.reason_code.clone(),
        schema_review_id: prepared.decision.review_id.clone(),
        authenticated_path: format!("{:?}", prepared.session_path.authenticated_path)
            .to_ascii_lowercase(),
        authenticated_path_reason: prepared.session_path.reason_code.clone(),
        durable_batch_id: closed.durable_batch_id.clone(),
        durable_logical_digest: closed.durable_logical_digest.to_string(),
        store_admission_digest: closed.store_admission_digest.to_string(),
        through_commit_seq: closed.through_commit_seq.clone(),
        admitted_observations: receipt_count(&prepared, "observations"),
        admitted_assertions: receipt_count(&prepared, "assertions"),
        admitted_coverage_windows: receipt_count(&prepared, "coverage_windows"),
        admitted_coverage_gaps: receipt_count(&prepared, "coverage_gaps"),
        identity_semantic_key: prepared.identity_semantic_key(),
        identity_claim_digest: prepared
            .claim
            .as_ref()
            .map(|claim| claim.claim_digest.clone()),
        identity_subject: prepared.claim.as_ref().map(|claim| claim.subject.clone()),
        identity_attributes: prepared
            .claim
            .as_ref()
            .map(|claim| serde_json::to_value(&claim.attributes))
            .transpose()?,
        reopened_integrity: verification.integrity,
        reopened_external_blobs_checked: verification.external_artifacts_checked.to_string(),
        readback_assertion_ids: readback_ids,
        readback_body_path,
        readback_body_bytes_equal_response: body_equal,
        readback_attributes_equal_claim: attributes_equal,
    };
    println!("{}", serde_json::to_string_pretty(&receipt)?);
    Ok(())
}

fn receipt_count(prepared: &PreparedProductRead, field: &str) -> String {
    let evidence = &prepared.prepared.admission_batch().store.evidence;
    match field {
        "observations" => evidence.observations.len().to_string(),
        "assertions" => evidence.assertions.len().to_string(),
        "coverage_windows" => evidence.coverage_windows.len().to_string(),
        _ => evidence.coverage_gaps.len().to_string(),
    }
}

fn attributes_match(
    bytes: &[u8],
    claim: &ProductIdentityClaimV1,
) -> Result<bool, Box<dyn std::error::Error>> {
    let value: Value = serde_json::from_slice(bytes)?;
    let object = value.as_object().ok_or("read-back body is not an object")?;
    if object.get("mint").and_then(Value::as_str) != Some(claim.subject.as_str()) {
        return Ok(false);
    }
    for (name, expected) in &claim.attributes {
        let Some(found) = object.get(name) else {
            return Ok(false);
        };
        let equal = match claim.attribute_encodings.get(name).map(String::as_str) {
            Some("utf8") => found.as_str() == Some(expected.as_str()),
            Some("boolean" | "json_number_lexeme") => found.to_string().as_str() == expected,
            _ => false,
        };
        if !equal {
            return Ok(false);
        }
    }
    Ok(true)
}

fn external_blob_path(
    state_dir: &Path,
    retention_class: &str,
    blob_id: &str,
) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let digest = blob_id
        .strip_prefix("sha256:")
        .ok_or("blob identity is not a sha256 digest")?;
    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("blob identity is not a 64-character hex digest".into());
    }
    Ok(state_dir
        .join("blobs")
        .join(retention_class)
        .join("sha256")
        .join(&digest[0..2])
        .join(&digest[2..4])
        .join(format!("{digest}.blob")))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObservedShape {
    contract: &'static str,
    route_id: String,
    catalog_version: String,
    acquisition_id: String,
    schema_fingerprint: String,
    shape: Vec<String>,
}

fn emit_shape(path: &Path, outcome: &FetchOutcome) -> Result<(), Box<dyn std::error::Error>> {
    let attempt = outcome.attempts.last().ok_or("no attempt to describe")?;
    let bytes = attempt
        .body
        .exact_bytes()
        .ok_or("cannot describe a non-exact body")?;
    let raw: Box<serde_json::value::RawValue> = serde_json::from_slice(&bytes)?;
    let shape = joshi_pump_api::schema_shape(&raw)?;
    let observed = ObservedShape {
        contract: "joshi.pump_api.observed_shape.v1",
        route_id: attempt.route_id.clone(),
        catalog_version: attempt.catalog_version.clone(),
        acquisition_id: attempt.acquisition_id.clone(),
        schema_fingerprint: fingerprint_of_shape(&shape),
        shape,
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(&observed)?)?;
    Ok(())
}

fn store_config(root: &Path) -> Result<StoreConfig, Box<dyn std::error::Error>> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        // Zero forces every retained body to a content-addressed file, so a full verification
        // after restart re-hashes the exact provider bytes rather than trusting a catalog row.
        inline_blob_max_bytes: 0,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new("joshi-pump-product-read")?,
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

fn now_utc() -> Result<String, Box<dyn std::error::Error>> {
    Ok(
        time::OffsetDateTime::now_utc().format(time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z"
        ))?,
    )
}
