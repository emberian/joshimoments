//! Deterministic, provider-disabled Wave 5 authority/restart witness.

use std::{path::Path, time::Duration};

use joshi_admission::{
    Sha256Digest,
    operational::AUTHORITY,
    wave5::{
        BuildManifestV1, BuildProfile, CollectorRuntimeConfigV1, CredentialHandlingV1,
        ExactRegisteredDocumentV1, ExecutionAccountingDocumentV1, LocalStatusEndpointV1,
        OwnedWave5RunRegistrationBundleV1, OwnedWave5RunRegistrationDocumentsV1,
        PermittedProtectionClassV1, PrivacyPolicyV1, ProviderExecutionModeV1, RunBudgetLimitsV1,
        SourceTreeHeadV1, SourceTreeManifestV1, WAVE5_RUN_REGISTRATION_CONTRACT,
        WalletMaterialRuleV1, Wave5RunRegistrationV1,
    },
};
use joshi_domain::StableString;
use joshi_store::{
    IdempotencyStatus, SqliteStore, StoreConfig, StoreMode, Wave5RunRegistrationByteBundle,
};
use serde::Serialize;
use thiserror::Error;

const SURFACE_PROFILE_FILE: &[u8] =
    include_bytes!("../../../fixtures/surface/daily_use_surface_profile_v1.json");

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
// These independent booleans are deliberately explicit, machine-readable nonclaims in the
// readiness wire report rather than interchangeable state-machine transitions.
#[allow(clippy::struct_excessive_bools)]
pub struct Wave5IgnitionReadinessReport {
    pub contract: &'static str,
    pub schema_version: u64,
    pub authority: &'static str,
    pub status: &'static str,
    pub catalog_schema: String,
    pub run_id: String,
    pub registration_digest: String,
    pub accepted_commit_seq: String,
    pub retry_status: IdempotencyStatus,
    pub changed_same_id_refused: bool,
    pub durable_progress_count: usize,
    pub restart_reverified: bool,
    pub provider_io: bool,
    pub publication_qualified: bool,
    pub live_qualified: bool,
}

/// Walks exact semantic run registration, idempotent retry, store-only status projection and
/// restart readback. It performs no provider, credential, wallet, publication, or transaction I/O.
///
/// # Errors
///
/// Returns [`Wave5ReadinessError`] when fixture construction, semantic admission, store migration,
/// durable registration, idempotency, or restart readback fails.
pub fn run_wave5_ignition_readiness(
    state: &Path,
) -> Result<Wave5IgnitionReadinessReport, Wave5ReadinessError> {
    let (registration, bundle, conflicting_bundle) = fixture_registration_bundles()?;

    let mut store = SqliteStore::open(config(state)?, StoreMode::SingleWriter)?;
    store.migrate(now()?)?;
    let run_id = StableString::new(registration.run_id.clone())?;
    let exact = store_bundle(&bundle);
    let context = store.begin_wave5_commit(
        StableString::new("wave5:fixture:run-registration")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let accepted = store.commit_wave5_run_registration_v1(&exact, &context)?;
    if accepted.status != IdempotencyStatus::Accepted {
        return Err(Wave5ReadinessError::Invariant(
            "fresh Wave 5 registration was not accepted",
        ));
    }
    let retry_context = store.begin_wave5_commit(
        StableString::new("wave5:fixture:run-registration")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let retry = store.commit_wave5_run_registration_v1(&exact, &retry_context)?;
    if retry.status != IdempotencyStatus::Idempotent
        || retry.commit_seq != accepted.commit_seq
        || retry.exact_document_digest != accepted.exact_document_digest
    {
        return Err(Wave5ReadinessError::Invariant(
            "exact Wave 5 retry changed durable identity",
        ));
    }
    let conflicting_context = store.begin_wave5_commit(
        StableString::new("wave5:fixture:conflicting-registration")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    if store
        .commit_wave5_run_registration_v1(&store_bundle(&conflicting_bundle), &conflicting_context)
        .is_ok()
    {
        return Err(Wave5ReadinessError::Invariant(
            "changed bytes under one run identity were accepted",
        ));
    }
    let view = store.load_wave5_store_status_view_v1(&run_id)?;
    if view.durable_progress.len() != 1 {
        return Err(Wave5ReadinessError::Invariant(
            "store status did not resolve exact run progress",
        ));
    }
    drop(store);

    let reopened = SqliteStore::open(config(state)?, StoreMode::ReadOnly)?;
    let loaded =
        reopened
            .load_wave5_run_registration_v1(&run_id)?
            .ok_or(Wave5ReadinessError::Invariant(
                "registered run was absent after restart",
            ))?;
    let reopened_view = reopened.load_wave5_store_status_view_v1(&run_id)?;
    if loaded.exact_bytes != bundle.registration
        || loaded.exact_digest != accepted.exact_document_digest
        || reopened_view != view
    {
        return Err(Wave5ReadinessError::Invariant(
            "restart readback changed exact Wave 5 truth",
        ));
    }
    Ok(Wave5IgnitionReadinessReport {
        contract: "joshi.wave5.ignition_readiness",
        schema_version: 1,
        authority: AUTHORITY,
        status: "useful_partial",
        catalog_schema: accepted.catalog_schema.to_string(),
        run_id: run_id.to_string(),
        registration_digest: accepted.exact_document_digest.to_string(),
        accepted_commit_seq: accepted.commit_seq.get().to_string(),
        retry_status: retry.status,
        changed_same_id_refused: true,
        durable_progress_count: view.durable_progress.len(),
        restart_reverified: true,
        provider_io: false,
        publication_qualified: false,
        live_qualified: false,
    })
}

fn fixture_documents()
-> Result<(OwnedWave5RunRegistrationDocumentsV1, PrivacyPolicyV1), Wave5ReadinessError> {
    let source_tree = SourceTreeManifestV1 {
        contract: "joshi.wave5.source_tree_manifest".into(),
        schema_version: 1,
        repository_id: "joshi-wave5-fixture".into(),
        head: SourceTreeHeadV1::Unborn,
        dirty: true,
        working_tree_digest: digest(b"wave5-fixture-working-tree").to_string(),
        diff_digest: Some(digest(b"wave5-fixture-diff").to_string()),
        authority: AUTHORITY.into(),
    };
    let source_tree_bytes = serde_json::to_vec(&source_tree)?;
    let build = BuildManifestV1 {
        contract: "joshi.wave5.build_manifest".into(),
        schema_version: 1,
        build_id: "joshi-core-wave5-fixture".into(),
        source_tree_digest: digest(&source_tree_bytes).to_string(),
        rustc_version: "rustc-1.97".into(),
        target_triple: "fixture-no-native-artifact".into(),
        profile: BuildProfile::LocalDebug,
        authority: AUTHORITY.into(),
    };
    let build_bytes = serde_json::to_vec(&build)?;
    let configuration = CollectorRuntimeConfigV1 {
        contract: "joshi.collector.runtime_config.v1".into(),
        schema_version: 1,
        plan_id: "wave5-sealed-c0".into(),
        plan_template_digest: digest(b"joshi.provider_plan_template.v1:sealed-c0").to_string(),
        status_endpoint: LocalStatusEndpointV1 {
            address: "127.0.0.1"
                .parse()
                .map_err(|_| Wave5ReadinessError::Invariant("invalid static loopback"))?,
            port: 19_441,
        },
        provider_execution: ProviderExecutionModeV1::OfflineFixtureOnly,
        authority: AUTHORITY.into(),
    };
    let configuration_bytes = configuration.canonical_bytes()?;
    let budget = ExecutionAccountingDocumentV1 {
        contract: "joshi.collector.execution_accounting.v1".into(),
        schema_version: 1,
        limits: RunBudgetLimitsV1 {
            maximum_requests: 1,
            maximum_pages: 1,
            maximum_ingress_bytes: 1_048_576,
            maximum_durable_bytes: 1_048_576,
            maximum_provider_credits: 0,
            maximum_ingress_bytes_per_second: None,
            maximum_elapsed_ms: 60_000,
            maximum_in_flight_attempts: 1,
            maximum_in_flight_elapsed_overshoot_ms: 1_000,
        },
        authority: AUTHORITY.into(),
    };
    let budget_bytes = budget.canonical_bytes()?;
    let privacy = PrivacyPolicyV1 {
        contract: "joshi.wave5.privacy_policy".into(),
        schema_version: 1,
        policy_id: "wave5-fixture-public-only".into(),
        permitted_protection_classes: vec![PermittedProtectionClassV1::PublicIntegrity],
        credential_handling: CredentialHandlingV1::PurposeScopedHandlesOnly,
        wallet_material: WalletMaterialRuleV1::Forbidden,
        export_private_material: false,
        authority: AUTHORITY.into(),
    };
    let privacy_bytes = serde_json::to_vec(&privacy)?;
    let surface_bytes = SURFACE_PROFILE_FILE
        .strip_suffix(b"\n")
        .unwrap_or(SURFACE_PROFILE_FILE)
        .to_vec();
    Ok((
        OwnedWave5RunRegistrationDocumentsV1 {
            build: build_bytes,
            source_tree: source_tree_bytes,
            configuration: configuration_bytes,
            budget: budget_bytes,
            privacy: privacy_bytes,
            daily_use_surface_profile: surface_bytes,
        },
        privacy,
    ))
}

fn fixture_registration_bundles() -> Result<
    (
        Wave5RunRegistrationV1,
        OwnedWave5RunRegistrationBundleV1,
        OwnedWave5RunRegistrationBundleV1,
    ),
    Wave5ReadinessError,
> {
    let (documents, privacy) = fixture_documents()?;
    let registration = Wave5RunRegistrationV1 {
        contract: WAVE5_RUN_REGISTRATION_CONTRACT.into(),
        schema_version: 1,
        run_id: "wave5-ignition-fixture-0001".into(),
        build: exact("build:wave5-fixture", &documents.build)?,
        source_tree: exact("source-tree:wave5-fixture", &documents.source_tree)?,
        configuration: exact("configuration:wave5-fixture", &documents.configuration)?,
        budget: exact("budget:wave5-fixture", &documents.budget)?,
        privacy: exact("privacy:wave5-fixture", &documents.privacy)?,
        daily_use_surface_profile: exact(
            "surface-profile:wave5-fixture",
            &documents.daily_use_surface_profile,
        )?,
        authority: AUTHORITY.into(),
    };
    let registration_bytes = registration.canonical_bytes()?;
    let bundle = OwnedWave5RunRegistrationBundleV1 {
        registration: registration_bytes,
        documents,
    };
    bundle.validate()?;
    let conflicting_privacy = PrivacyPolicyV1 {
        policy_id: "wave5-fixture-public-and-private".into(),
        permitted_protection_classes: vec![
            PermittedProtectionClassV1::PublicIntegrity,
            PermittedProtectionClassV1::AuthenticatedPrivate,
        ],
        ..privacy
    };
    let mut conflicting_documents = bundle.documents.clone();
    conflicting_documents.privacy = serde_json::to_vec(&conflicting_privacy)?;
    let mut conflicting_registration = registration.clone();
    conflicting_registration.privacy = exact(
        "privacy:wave5-fixture-conflict",
        &conflicting_documents.privacy,
    )?;
    let conflicting_bundle = OwnedWave5RunRegistrationBundleV1 {
        registration: conflicting_registration.canonical_bytes()?,
        documents: conflicting_documents,
    };
    conflicting_bundle.validate()?;
    Ok((registration, bundle, conflicting_bundle))
}

fn exact(
    document_id: &str,
    bytes: &[u8],
) -> Result<ExactRegisteredDocumentV1, Wave5ReadinessError> {
    Ok(ExactRegisteredDocumentV1 {
        document_id: document_id.into(),
        exact_bytes: joshi_admission::operational::ExactByteClosureV1::new(bytes)?,
    })
}

fn store_bundle(bundle: &OwnedWave5RunRegistrationBundleV1) -> Wave5RunRegistrationByteBundle<'_> {
    Wave5RunRegistrationByteBundle {
        registration: &bundle.registration,
        build: &bundle.documents.build,
        source_tree: &bundle.documents.source_tree,
        configuration: &bundle.documents.configuration,
        budget: &bundle.documents.budget,
        privacy: &bundle.documents.privacy,
        daily_use_surface_profile: &bundle.documents.daily_use_surface_profile,
    }
}

fn digest(bytes: &[u8]) -> Sha256Digest {
    Sha256Digest::of_bytes(bytes)
}

fn config(root: &Path) -> Result<StoreConfig, Wave5ReadinessError> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-wave5-ignition-readiness")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

fn now() -> Result<joshi_domain::UtcTimestamp, Wave5ReadinessError> {
    let nanos = time::OffsetDateTime::now_utc().unix_timestamp_nanos();
    let micros = nanos.div_euclid(1_000) * 1_000;
    joshi_domain::UtcTimestamp::new(
        time::OffsetDateTime::from_unix_timestamp_nanos(micros)
            .map_err(|_| Wave5ReadinessError::Clock)?,
    )
    .map_err(|_| Wave5ReadinessError::Clock)
}

#[derive(Debug, Error)]
pub enum Wave5ReadinessError {
    #[error(transparent)]
    Admission(#[from] joshi_admission::AdmissionError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("system clock is unavailable")]
    Clock,
    #[error("Wave 5 fixture invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn semantic_run_registration_retries_and_reopens_without_live_claims() {
        let state = tempfile::tempdir().expect("temporary witness state");
        let report = run_wave5_ignition_readiness(state.path()).expect("Wave 5 fixture witness");
        assert_eq!(report.status, "useful_partial");
        assert_eq!(report.retry_status, IdempotencyStatus::Idempotent);
        assert!(report.changed_same_id_refused);
        assert_eq!(report.durable_progress_count, 1);
        assert!(report.restart_reverified);
        assert!(!report.provider_io);
        assert!(!report.publication_qualified);
        assert!(!report.live_qualified);
    }
}
