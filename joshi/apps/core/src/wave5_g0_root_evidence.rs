//! Consolidated, explicitly partial Wave 5 G0 root evidence.
//!
//! This joins the durable source/publication component to the ordinary-pairing HTTP open and
//! restart smoke over the same store state. It closes all eighteen baseline evidence roles, but
//! it does not execute or qualify the deterministic 37-scenario fault schedule.

use crate::{
    g0_inspector_smoke::{G0InspectorSmokeError, G0InspectorSmokeReport, run_g0_inspector_smoke},
    wave5_g0::{
        Wave5G0SourcePublicationError, Wave5G0SourcePublicationReport,
        offline_fixture_store_config, run_wave5_g0_source_publication, supervisor_config,
    },
};
use joshi_admission::Sha256Digest;
use joshi_domain::StableString;
use joshi_g0_harness::{EVIDENCE_CONTRACT, EvidenceBundle, EvidenceItem, EvidenceRole};
use joshi_store::{SqliteStore, StoreMode, VerifyDepth};
use joshi_supervisor::Supervisor;
use serde::Serialize;
use std::{
    fs::{self, File},
    path::{Path, PathBuf},
};
use thiserror::Error;

const CONTRACT: &str = "joshi.wave5.g0_root_evidence.v1";
const AUTHORITY: &str = "offline_fixture_evidence_no_fault_qualification";

const REQUIRED_ROLES: [EvidenceRole; 18] = [
    EvidenceRole::Reservation,
    EvidenceRole::OriginSegment,
    EvidenceRole::StoreReceipt,
    EvidenceRole::CatalogBinding,
    EvidenceRole::CatalogAck,
    EvidenceRole::SemanticFact,
    EvidenceRole::PublicationPrepare,
    EvidenceRole::PublicationHead,
    EvidenceRole::PairingExchange,
    EvidenceRole::GlassRead,
    EvidenceRole::MemoryAct,
    EvidenceRole::MemoryEpisode,
    EvidenceRole::ExportManifest,
    EvidenceRole::ImportReceipt,
    EvidenceRole::StatusReadback,
    EvidenceRole::BackupManifest,
    EvidenceRole::RestoreReadback,
    EvidenceRole::ReopenReadback,
];

/// Exact joined result. Nested reports retain the complete producer evidence rather than reducing
/// it to booleans or a detached digest.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave5G0RootEvidenceReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub component_report_digest: String,
    pub inspector_report_digest: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub publication_id: String,
    pub publication_digest: String,
    pub head_semantic_digest: String,
    pub head_bytes_digest: String,
    pub v10_export_snapshot_id: String,
    pub evidence_bundle: EvidenceBundle,
    pub final_recovery: G0FinalRecoveryReport,
    pub component: Wave5G0SourcePublicationReport,
    pub inspector: G0InspectorSmokeReport,
    pub partial_root_evidence_closed: bool,
    pub full_offline_fault_walk: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

/// Secret-free exact result of reopening store and origin state from distinct restored roots.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct G0FinalRecoveryReport {
    pub contract: &'static str,
    pub authority: &'static str,
    pub backup_id: String,
    pub backup_manifest_digest: String,
    pub backup_inventory_digest: String,
    pub restore_id: String,
    pub restore_readback_digest: String,
    pub supervisor_backup_manifest_digest: String,
    pub supervisor_file_count: u64,
    pub origin_segment_digest: String,
    pub final_readback_digest: String,
    pub original_paths_unavailable_during_reopen: bool,
    pub store_full_verification_closed: bool,
    pub supervisor_origin_reopened: bool,
    pub full_offline_fault_walk: bool,
}

/// Deterministic interruption points for the composite final backup/restore/reopen boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum G0FinalRecoveryFaultPoint {
    BeforeBackup,
    AfterBackup,
    BeforeRestore,
    AfterRestore,
    BeforeReopen,
    AfterReopen,
}

#[derive(Debug, Error)]
pub enum Wave5G0RootEvidenceError {
    #[error(transparent)]
    Component(#[from] Wave5G0SourcePublicationError),
    #[error(transparent)]
    Inspector(#[from] G0InspectorSmokeError),
    #[error(transparent)]
    Harness(#[from] joshi_g0_harness::HarnessError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Supervisor(#[from] joshi_supervisor::SupervisorError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error("injected Wave 5 G0 final recovery interruption at {0:?}")]
    Injected(G0FinalRecoveryFaultPoint),
    #[error("Wave 5 G0 root evidence invariant failed: {0}")]
    Invariant(&'static str),
}

/// Run and exact-join the existing offline component and paired route/restart smoke.
///
/// # Errors
///
/// Refuses any component failure, publication/run substitution, route-byte mismatch, missing or
/// duplicate evidence role, positive qualification, or malformed evidence digest.
pub async fn run_wave5_g0_root_evidence(
    state: &Path,
) -> Result<Wave5G0RootEvidenceReport, Wave5G0RootEvidenceError> {
    recover_interrupted_original_roots(state)?;
    let component = run_wave5_g0_source_publication(state)?;
    let inspector = run_g0_inspector_smoke(state).await?;
    let final_recovery = run_final_recovery(state, &component, &inspector)?;
    join_reports(component, inspector, final_recovery)
}

pub(crate) fn join_reports(
    component: Wave5G0SourcePublicationReport,
    inspector: G0InspectorSmokeReport,
    final_recovery: G0FinalRecoveryReport,
) -> Result<Wave5G0RootEvidenceReport, Wave5G0RootEvidenceError> {
    validate_report_pair(&component, &inspector)?;
    validate_final_recovery(&component, &final_recovery)?;
    let component_report_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&component)?).to_string();
    let inspector_report_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&inspector)?).to_string();

    let mut items = component.partial_fault_result.evidence_bundle.items.clone();
    items.extend([
        EvidenceItem {
            role: EvidenceRole::PairingExchange,
            evidence_id: inspector.pairing_occurrence_id.clone(),
            content_digest: inspector.pairing_occurrence_digest.clone(),
        },
        EvidenceItem {
            role: EvidenceRole::GlassRead,
            evidence_id: format!("glass-read:{}", inspector.session_id),
            content_digest: inspector.route_response_digest.clone(),
        },
        EvidenceItem {
            role: EvidenceRole::ReopenReadback,
            evidence_id: format!("reopen-readback:{}", component.run_registration_id),
            content_digest: final_recovery.final_readback_digest.clone(),
        },
    ]);
    items.sort_by(|left, right| {
        (left.role, left.evidence_id.as_str()).cmp(&(right.role, right.evidence_id.as_str()))
    });
    let mut evidence_bundle = EvidenceBundle {
        contract: EVIDENCE_CONTRACT.into(),
        items,
        digest: String::new(),
    };
    evidence_bundle.digest = evidence_bundle.recompute_digest()?;
    validate_complete_bundle(&component, &inspector, &final_recovery, &evidence_bundle)?;

    Ok(Wave5G0RootEvidenceReport {
        contract: CONTRACT,
        schema_version: 1,
        authority: AUTHORITY,
        status: "useful_partial",
        component_report_digest,
        inspector_report_digest,
        run_registration_id: component.run_registration_id.clone(),
        run_registration_digest: component.run_registration_digest.clone(),
        publication_id: component.publication_id.clone(),
        publication_digest: component.publication_digest.clone(),
        head_semantic_digest: inspector.head_digest.clone(),
        head_bytes_digest: component.head_digest.clone(),
        v10_export_snapshot_id: component.v10_export_snapshot_id.clone(),
        evidence_bundle,
        final_recovery,
        component,
        inspector,
        partial_root_evidence_closed: true,
        full_offline_fault_walk: false,
        browser_presented: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn validate_report_pair(
    component: &Wave5G0SourcePublicationReport,
    inspector: &G0InspectorSmokeReport,
) -> Result<(), Wave5G0RootEvidenceError> {
    component.partial_fault_result.validate()?;
    if component.partial_fault_result.evidence_bundle.items.len() != 15 {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "component must retain exactly its fifteen baseline evidence roles",
        ));
    }
    if component.run_registration_id != inspector.run_registration_id
        || component.run_registration_digest != inspector.run_registration_digest
        || component.source_occurrence_id != inspector.source_occurrence_id
        || component.publication_id != inspector.publication_id
        || component.publication_digest != inspector.publication_digest
        || component.head_digest != inspector.head_bytes_digest
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "component and inspector do not close the same run/source/publication/head",
        ));
    }
    if !component.restart_reverified
        || !inspector.paired_route_read_closed
        || !inspector.restart_old_capability_refused
        || !inspector.fresh_pairing_reopen_closed
        || inspector.route_response_digest != inspector.reopened_response_digest
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "component/restart/route readback evidence is incomplete",
        ));
    }
    if component.full_offline_fault_walk
        || component.provider_io
        || component.product_qualified
        || component.live_qualified
        || inspector.full_offline_fault_walk
        || inspector.browser_presented
        || inspector.product_qualified
        || inspector.live_qualified
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "partial root join cannot carry a positive fault/product/live claim",
        ));
    }
    Ok(())
}

fn validate_complete_bundle(
    component: &Wave5G0SourcePublicationReport,
    inspector: &G0InspectorSmokeReport,
    final_recovery: &G0FinalRecoveryReport,
    bundle: &EvidenceBundle,
) -> Result<(), Wave5G0RootEvidenceError> {
    bundle.validate()?;
    if bundle.items.len() != REQUIRED_ROLES.len() {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "root evidence bundle must contain exactly eighteen items",
        ));
    }
    for (item, role) in bundle.items.iter().zip(REQUIRED_ROLES) {
        if item.role != role {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "root evidence roles are missing, duplicated, or reordered",
            ));
        }
    }
    let expected_pairing = EvidenceItem {
        role: EvidenceRole::PairingExchange,
        evidence_id: inspector.pairing_occurrence_id.clone(),
        content_digest: inspector.pairing_occurrence_digest.clone(),
    };
    let expected_glass = EvidenceItem {
        role: EvidenceRole::GlassRead,
        evidence_id: format!("glass-read:{}", inspector.session_id),
        content_digest: inspector.route_response_digest.clone(),
    };
    let expected_reopen = EvidenceItem {
        role: EvidenceRole::ReopenReadback,
        evidence_id: format!("reopen-readback:{}", component.run_registration_id),
        content_digest: final_recovery.final_readback_digest.clone(),
    };
    let mut expected = component.partial_fault_result.evidence_bundle.items.clone();
    expected.extend([expected_pairing, expected_glass, expected_reopen]);
    expected.sort_by(|left, right| {
        (left.role, left.evidence_id.as_str()).cmp(&(right.role, right.evidence_id.as_str()))
    });
    if bundle.items != expected {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "root evidence differs from the exact component and inspector artifacts",
        ));
    }
    Ok(())
}

fn validate_final_recovery(
    component: &Wave5G0SourcePublicationReport,
    recovery: &G0FinalRecoveryReport,
) -> Result<(), Wave5G0RootEvidenceError> {
    if recovery.contract != "joshi.wave5.g0_final_recovery.v1"
        || recovery.authority != AUTHORITY
        || recovery.origin_segment_digest != component.origin_segment_digest
        || !recovery.original_paths_unavailable_during_reopen
        || !recovery.store_full_verification_closed
        || !recovery.supervisor_origin_reopened
        || recovery.full_offline_fault_walk
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "final recovery does not close exact restored store/origin state at the partial ceiling",
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct SupervisorBackupEntry {
    relative_path: String,
    byte_length: u64,
    content_digest: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_field_names)]
struct FinalReadbackMaterial<'a> {
    run_registration_digest: &'a str,
    source_descriptor_digest: &'a str,
    publication_digest: &'a str,
    publication_bytes_digest: &'a str,
    head_semantic_digest: &'a str,
    head_bytes_digest: &'a str,
    memory_terminal_digest: &'a str,
    export_binding_digest: &'a str,
    import_registration_digest: &'a str,
    status_record_digest: &'a str,
    pairing_occurrence_digest: &'a str,
    origin_segment_digest: &'a str,
    backup_manifest_digest: &'a str,
    restore_readback_digest: &'a str,
    supervisor_backup_manifest_digest: &'a str,
}

#[allow(clippy::too_many_lines)]
pub(crate) fn run_final_recovery(
    state: &Path,
    component: &Wave5G0SourcePublicationReport,
    inspector: &G0InspectorSmokeReport,
) -> Result<G0FinalRecoveryReport, Wave5G0RootEvidenceError> {
    run_final_recovery_with_fault(state, component, inspector, None)
}

#[allow(clippy::too_many_lines)]
pub(crate) fn run_final_recovery_with_fault(
    state: &Path,
    component: &Wave5G0SourcePublicationReport,
    inspector: &G0InspectorSmokeReport,
    fault: Option<G0FinalRecoveryFaultPoint>,
) -> Result<G0FinalRecoveryReport, Wave5G0RootEvidenceError> {
    let tag = inspector
        .pairing_occurrence_digest
        .strip_prefix("sha256:")
        .and_then(|value| value.get(..16))
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "pairing occurrence digest is not canonical",
        ))?;
    let root = state.join(format!("g0-root-recovery-{tag}"));
    let backup_id = StableString::new(format!("backup:g0-root-final-{tag}"))?;
    let restore_id = StableString::new(format!("restore:g0-root-final-{tag}"))?;
    let config = offline_fixture_store_config(state)?;
    let mut store = SqliteStore::open(config.clone(), StoreMode::SingleWriter)?;
    inject_final(fault, G0FinalRecoveryFaultPoint::BeforeBackup)?;
    let backup_context = store.begin_wave5_commit(
        StableString::new(format!("wave5:g0:root-final-backup:{tag}"))?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let backup = store.commit_wave5_g0_backup_v1(
        &backup_id,
        &StableString::new(component.run_registration_id.clone())?,
        &root.join("backup/catalog.sqlite"),
        &root.join("backup/artifacts"),
        &backup_context,
    )?;
    let supervisor_backup = root.join("backup/supervisor");
    let supervisor_entries = copy_exact_tree(&state.join("supervisor"), &supervisor_backup)?;
    if supervisor_entries.is_empty() {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "supervisor backup inventory is empty",
        ));
    }
    let supervisor_manifest_bytes = serde_json::to_vec(&supervisor_entries)?;
    let supervisor_manifest_digest = Sha256Digest::of_bytes(&supervisor_manifest_bytes).to_string();
    inject_final(fault, G0FinalRecoveryFaultPoint::AfterBackup)?;

    inject_final(fault, G0FinalRecoveryFaultPoint::BeforeRestore)?;
    let restore_context = store.begin_wave5_commit(
        StableString::new(format!("wave5:g0:root-final-restore:{tag}"))?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let restore = store.commit_wave5_g0_backup_restore_v1(
        &restore_id,
        &backup_id,
        &root.join("restored/catalog.sqlite"),
        &root.join("restored/artifacts"),
        &restore_context,
    )?;
    let supervisor_restore_state = next_supervisor_restore_state(&root)?;
    let supervisor_restore = supervisor_restore_state.join("supervisor");
    let restored_supervisor_entries = copy_exact_tree(&supervisor_backup, &supervisor_restore)?;
    if supervisor_entries != restored_supervisor_entries {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "restored supervisor inventory differs from its backup",
        ));
    }
    inject_final(fault, G0FinalRecoveryFaultPoint::AfterRestore)?;
    drop(store);

    let original_paths = [
        config.catalog_path.clone(),
        config.catalog_path.with_extension("sqlite-wal"),
        config.catalog_path.with_extension("sqlite-shm"),
        config.blob_root.clone(),
        config.export_root.clone(),
        state.join("supervisor"),
    ];
    let unavailable = root.join("original-paths-unavailable");
    let guard = OriginalRootsGuard::hide(&original_paths, &unavailable)?;
    if original_paths
        .iter()
        .any(|path| path.try_exists().unwrap_or(true))
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "an original root remained available during restored reopen",
        ));
    }
    inject_final(fault, G0FinalRecoveryFaultPoint::BeforeReopen)?;

    let mut restored_config = config;
    restored_config
        .catalog_path
        .clone_from(&restore.restored_catalog_path);
    restored_config.blob_root = restore.restored_artifact_root.join("blob");
    restored_config.export_root = restore.restored_artifact_root.join("export");
    let restored_store = SqliteStore::open(restored_config, StoreMode::ReadOnly)?;
    restored_store.verify(VerifyDepth::Full)?;
    let run_id = StableString::new(component.run_registration_id.clone())?;
    let run = restored_store
        .load_wave5_run_registration_v1(&run_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "registered run is absent from restored catalog",
        ))?;
    let source_id = StableString::new(component.source_occurrence_id.clone())?;
    let source = restored_store
        .load_wave5_source_occurrence_v1(&source_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "source occurrence is absent from restored catalog",
        ))?;
    let publication_id =
        joshi_publication::CockpitPublicationId::new(component.publication_id.clone())
            .map_err(|_| Wave5G0RootEvidenceError::Invariant("publication ID is invalid"))?;
    let publication = restored_store
        .load_cockpit_v2_publication_v1(&publication_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "publication is absent from restored catalog",
        ))?;
    let head = restored_store
        .load_cockpit_v2_head_v1(&publication_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "publication head is absent from restored catalog",
        ))?;
    let memory_id = StableString::new(component.memory_terminal_id.clone())?;
    let memory = restored_store
        .load_scientific_memory_occurrence_v1(&memory_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "memory terminal is absent from restored catalog",
        ))?;
    let export_id = StableString::new(component.v10_export_binding_id.clone())?;
    let export = restored_store
        .load_wave5_g0_export_occurrence_v1(&export_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "V10 export binding is absent from restored catalog",
        ))?;
    let import_id = StableString::new(component.baseline_import_id.clone())?;
    let import = restored_store
        .load_wave5_g0_import_occurrence_v1(&import_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "restricted import is absent from restored catalog",
        ))?;
    let status_id = StableString::new(component.status_record_id.clone())?;
    let status = restored_store
        .load_wave5_g0_status_occurrence_v1(&status_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "status occurrence is absent from restored catalog",
        ))?;
    let pairing_id = StableString::new(inspector.pairing_occurrence_id.clone())?;
    let pairing = restored_store
        .load_pairing_occurrence_v1(&pairing_id)?
        .ok_or(Wave5G0RootEvidenceError::Invariant(
            "pairing occurrence is absent from restored catalog",
        ))?;

    let restored_supervisor = Supervisor::open(supervisor_config(&supervisor_restore_state))?;
    let reservations = restored_supervisor
        .completed_no_gap_reservations_for_run(&component.run_registration_id)?;
    let [reservation] = reservations.as_slice() else {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "restored supervisor lacks exactly one completed reservation",
        ));
    };
    let local_receipt =
        restored_supervisor.local_spool_receipt_for_completed_reservation(reservation)?;
    let origin_segment_digest = local_receipt.exact_segment.digest.to_string();
    if origin_segment_digest != component.origin_segment_digest {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "restored supervisor origin segment differs from component evidence",
        ));
    }

    let backup_manifest_digest = Sha256Digest::of_bytes(&backup.manifest_bytes).to_string();
    let final_material = FinalReadbackMaterial {
        run_registration_digest: run.exact_digest.as_str(),
        source_descriptor_digest: source.descriptor_digest.as_str(),
        publication_digest: publication.publication.publication_digest.as_str(),
        publication_bytes_digest: publication.publication_bytes_digest.as_str(),
        head_semantic_digest: head.head.head_digest.as_str(),
        head_bytes_digest: head.head_digest.as_str(),
        memory_terminal_digest: memory.occurrence_digest.as_str(),
        export_binding_digest: export.binding_digest.as_str(),
        import_registration_digest: import.registration_digest.as_str(),
        status_record_digest: status.record_digest.as_str(),
        pairing_occurrence_digest: pairing.document_digest.as_str(),
        origin_segment_digest: &origin_segment_digest,
        backup_manifest_digest: &backup_manifest_digest,
        restore_readback_digest: restore.readback_digest.as_str(),
        supervisor_backup_manifest_digest: &supervisor_manifest_digest,
    };
    let final_readback_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&final_material)?).to_string();
    inject_final(fault, G0FinalRecoveryFaultPoint::AfterReopen)?;
    drop(restored_supervisor);
    drop(restored_store);
    guard.restore()?;

    Ok(G0FinalRecoveryReport {
        contract: "joshi.wave5.g0_final_recovery.v1",
        authority: AUTHORITY,
        backup_id: backup.backup_id.to_string(),
        backup_manifest_digest,
        backup_inventory_digest: backup.artifact_inventory_digest.to_string(),
        restore_id: restore.restore_id.to_string(),
        restore_readback_digest: restore.readback_digest.to_string(),
        supervisor_backup_manifest_digest: supervisor_manifest_digest,
        supervisor_file_count: u64::try_from(supervisor_entries.len()).map_err(|_| {
            Wave5G0RootEvidenceError::Invariant("supervisor backup file count overflow")
        })?,
        origin_segment_digest,
        final_readback_digest,
        original_paths_unavailable_during_reopen: true,
        store_full_verification_closed: true,
        supervisor_origin_reopened: true,
        full_offline_fault_walk: false,
    })
}

fn inject_final(
    requested: Option<G0FinalRecoveryFaultPoint>,
    current: G0FinalRecoveryFaultPoint,
) -> Result<(), Wave5G0RootEvidenceError> {
    if requested == Some(current) {
        crate::g0_process_fault::pause_if_process_kill_armed(
            "final_recovery",
            &format!("{current:?}"),
        );
        return Err(Wave5G0RootEvidenceError::Injected(current));
    }
    Ok(())
}

fn copy_exact_tree(
    source: &Path,
    destination: &Path,
) -> Result<Vec<SupervisorBackupEntry>, Wave5G0RootEvidenceError> {
    if destination.try_exists()? {
        let source_entries = exact_tree_inventory(source)?;
        let destination_entries = exact_tree_inventory(destination)?;
        if source_entries != destination_entries {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "existing supervisor backup/restore inventory differs",
            ));
        }
        return Ok(destination_entries);
    }
    let mut entries = Vec::new();
    copy_exact_tree_inner(source, source, destination, &mut entries)?;
    entries.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));
    Ok(entries)
}

fn next_supervisor_restore_state(root: &Path) -> Result<PathBuf, Wave5G0RootEvidenceError> {
    let attempts = root.join("supervisor-restore-attempts");
    fs::create_dir_all(&attempts)?;
    for ordinal in 1..=64_u8 {
        let candidate = attempts.join(format!("attempt-{ordinal:02}"));
        if !candidate.try_exists()? {
            return Ok(candidate);
        }
    }
    Err(Wave5G0RootEvidenceError::Invariant(
        "supervisor restore retry bound is exhausted",
    ))
}

fn exact_tree_inventory(
    root: &Path,
) -> Result<Vec<SupervisorBackupEntry>, Wave5G0RootEvidenceError> {
    let mut entries = Vec::new();
    exact_tree_inventory_inner(root, root, &mut entries)?;
    entries.sort_by(|left, right| left.relative_path.cmp(&right.relative_path));
    Ok(entries)
}

fn exact_tree_inventory_inner(
    root: &Path,
    current: &Path,
    entries: &mut Vec<SupervisorBackupEntry>,
) -> Result<(), Wave5G0RootEvidenceError> {
    let metadata = fs::symlink_metadata(current)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "supervisor inventory root contains a non-directory or symlink",
        ));
    }
    let mut children = fs::read_dir(current)?.collect::<Result<Vec<_>, _>>()?;
    children.sort_by_key(fs::DirEntry::file_name);
    for child in children {
        let path = child.path();
        let file_type = child.file_type()?;
        if file_type.is_symlink() {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "supervisor inventory contains a symlink",
            ));
        }
        let relative = path.strip_prefix(root).map_err(|_| {
            Wave5G0RootEvidenceError::Invariant("supervisor inventory path escaped")
        })?;
        if relative == Path::new("identity/supervisor.lock") {
            continue;
        }
        if file_type.is_dir() {
            exact_tree_inventory_inner(root, &path, entries)?;
        } else if file_type.is_file() {
            let bytes = fs::read(&path)?;
            entries.push(SupervisorBackupEntry {
                relative_path: relative.to_string_lossy().into_owned(),
                byte_length: u64::try_from(bytes.len()).map_err(|_| {
                    Wave5G0RootEvidenceError::Invariant("supervisor file length overflow")
                })?,
                content_digest: Sha256Digest::of_bytes(&bytes).to_string(),
            });
        } else {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "supervisor inventory contains a special file",
            ));
        }
    }
    Ok(())
}

fn copy_exact_tree_inner(
    root: &Path,
    source: &Path,
    destination_root: &Path,
    entries: &mut Vec<SupervisorBackupEntry>,
) -> Result<(), Wave5G0RootEvidenceError> {
    let metadata = fs::symlink_metadata(source)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "supervisor inventory root contains a non-directory or symlink",
        ));
    }
    let relative = source
        .strip_prefix(root)
        .map_err(|_| Wave5G0RootEvidenceError::Invariant("supervisor relative path escaped"))?;
    let destination = destination_root.join(relative);
    fs::create_dir_all(&destination)?;
    let mut children = fs::read_dir(source)?.collect::<Result<Vec<_>, _>>()?;
    children.sort_by_key(fs::DirEntry::file_name);
    for child in children {
        let child_path = child.path();
        let child_metadata = child.file_type()?;
        if child_metadata.is_symlink() {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "supervisor inventory contains a symlink",
            ));
        }
        let child_relative = child_path
            .strip_prefix(root)
            .map_err(|_| Wave5G0RootEvidenceError::Invariant("supervisor child path escaped"))?;
        if child_relative == Path::new("identity/supervisor.lock") {
            continue;
        }
        if child_metadata.is_dir() {
            copy_exact_tree_inner(root, &child_path, destination_root, entries)?;
        } else if child_metadata.is_file() {
            let bytes = fs::read(&child_path)?;
            let target = destination_root.join(child_relative);
            fs::copy(&child_path, &target)?;
            File::open(&target)?.sync_all()?;
            let readback = fs::read(&target)?;
            if readback != bytes {
                return Err(Wave5G0RootEvidenceError::Invariant(
                    "supervisor backup/restore changed file bytes",
                ));
            }
            entries.push(SupervisorBackupEntry {
                relative_path: child_relative.to_string_lossy().into_owned(),
                byte_length: u64::try_from(bytes.len()).map_err(|_| {
                    Wave5G0RootEvidenceError::Invariant("supervisor file length overflow")
                })?,
                content_digest: Sha256Digest::of_bytes(&bytes).to_string(),
            });
        } else {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "supervisor inventory contains a special file",
            ));
        }
    }
    File::open(destination)?.sync_all()?;
    Ok(())
}

struct OriginalRootsGuard {
    moved: Vec<(PathBuf, PathBuf)>,
}

impl OriginalRootsGuard {
    fn hide(paths: &[PathBuf], unavailable: &Path) -> Result<Self, Wave5G0RootEvidenceError> {
        if unavailable.try_exists()? {
            let metadata = fs::symlink_metadata(unavailable)?;
            if metadata.file_type().is_symlink()
                || !metadata.is_dir()
                || fs::read_dir(unavailable)?.next().is_some()
            {
                return Err(Wave5G0RootEvidenceError::Invariant(
                    "original-root quarantine exists and is not an empty real directory",
                ));
            }
        } else {
            fs::create_dir_all(unavailable)?;
        }
        let mut guard = Self { moved: Vec::new() };
        for (ordinal, path) in paths.iter().enumerate() {
            if !path.try_exists()? {
                continue;
            }
            let target = unavailable.join(format!("{ordinal:02}"));
            fs::rename(path, &target)?;
            guard.moved.push((path.clone(), target));
        }
        File::open(unavailable)?.sync_all()?;
        Ok(guard)
    }

    fn restore(mut self) -> Result<(), Wave5G0RootEvidenceError> {
        while let Some((original, hidden)) = self.moved.last().cloned() {
            fs::rename(&hidden, &original)?;
            if !original.try_exists()? || hidden.try_exists()? {
                return Err(Wave5G0RootEvidenceError::Invariant(
                    "an original root was not restored after verification",
                ));
            }
            self.moved.pop();
        }
        Ok(())
    }
}

impl Drop for OriginalRootsGuard {
    fn drop(&mut self) {
        for (original, hidden) in self.moved.iter().rev() {
            let _ = fs::rename(hidden, original);
        }
    }
}

pub(crate) fn recover_interrupted_original_roots(
    state: &Path,
) -> Result<bool, Wave5G0RootEvidenceError> {
    if !state.try_exists()? {
        return Ok(false);
    }
    let mut quarantines = Vec::new();
    for entry in fs::read_dir(state)? {
        let entry = entry?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        if !name.starts_with("g0-root-recovery-") {
            continue;
        }
        let metadata = fs::symlink_metadata(entry.path())?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "G0 recovery root is not a real directory",
            ));
        }
        let unavailable = entry.path().join("original-paths-unavailable");
        if !unavailable.try_exists()? {
            continue;
        }
        let metadata = fs::symlink_metadata(&unavailable)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "G0 original-root quarantine is not a real directory",
            ));
        }
        if fs::read_dir(&unavailable)?.next().transpose()?.is_some() {
            quarantines.push(unavailable);
        }
    }
    let [unavailable] = quarantines.as_slice() else {
        return if quarantines.is_empty() {
            Ok(false)
        } else {
            Err(Wave5G0RootEvidenceError::Invariant(
                "multiple interrupted G0 original-root quarantines exist",
            ))
        };
    };
    let config = offline_fixture_store_config(state)?;
    let originals = [
        config.catalog_path.clone(),
        config.catalog_path.with_extension("sqlite-wal"),
        config.catalog_path.with_extension("sqlite-shm"),
        config.blob_root,
        config.export_root,
        state.join("supervisor"),
    ];
    let mut moves = Vec::new();
    for entry in fs::read_dir(unavailable)? {
        let entry = entry?;
        let name = entry.file_name();
        let name = name.to_str().ok_or(Wave5G0RootEvidenceError::Invariant(
            "G0 quarantine entry name is not UTF-8",
        ))?;
        let ordinal = name
            .parse::<usize>()
            .ok()
            .filter(|ordinal| format!("{ordinal:02}") == name)
            .filter(|ordinal| *ordinal < originals.len())
            .ok_or(Wave5G0RootEvidenceError::Invariant(
                "G0 quarantine contains an unknown original-root ordinal",
            ))?;
        let hidden = entry.path();
        let metadata = fs::symlink_metadata(&hidden)?;
        if metadata.file_type().is_symlink() || (!metadata.is_file() && !metadata.is_dir()) {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "G0 quarantine contains a special file",
            ));
        }
        let original = originals[ordinal].clone();
        if original.try_exists()? {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "G0 original root conflicts with its interrupted quarantine",
            ));
        }
        moves.push((ordinal, hidden, original));
    }
    moves.sort_by_key(|(ordinal, _, _)| *ordinal);
    for (_, hidden, original) in moves {
        fs::rename(hidden, original)?;
    }
    File::open(unavailable)?.sync_all()?;
    File::open(state)?.sync_all()?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn joins_all_roles_and_refuses_cross_run_or_evidence_substitution() {
        let state = tempfile::tempdir().expect("temporary G0 root evidence state");
        let component = run_wave5_g0_source_publication(state.path()).expect("G0 component");
        let inspector = run_g0_inspector_smoke(state.path())
            .await
            .expect("G0 inspector");
        let recovery =
            run_final_recovery(state.path(), &component, &inspector).expect("final recovery");
        let report = join_reports(component.clone(), inspector.clone(), recovery.clone())
            .expect("root evidence");
        assert_eq!(report.evidence_bundle.items.len(), 18);
        assert_eq!(
            report
                .evidence_bundle
                .items
                .iter()
                .map(|item| item.role)
                .collect::<Vec<_>>(),
            REQUIRED_ROLES
        );
        assert!(report.partial_root_evidence_closed);
        assert!(
            report
                .final_recovery
                .original_paths_unavailable_during_reopen
        );
        assert!(report.final_recovery.store_full_verification_closed);
        assert!(report.final_recovery.supervisor_origin_reopened);
        assert!(!report.full_offline_fault_walk);
        assert!(!report.product_qualified);

        let mut wrong_run = inspector.clone();
        wrong_run.run_registration_id = "run:substituted".into();
        assert!(join_reports(component.clone(), wrong_run, recovery.clone()).is_err());

        let mut wrong_publication = inspector.clone();
        wrong_publication.publication_digest = format!("sha256:{}", "0".repeat(64));
        assert!(join_reports(component.clone(), wrong_publication, recovery.clone()).is_err());

        let mut wrong_route = inspector;
        wrong_route.reopened_response_digest = format!("sha256:{}", "1".repeat(64));
        assert!(join_reports(component, wrong_route, recovery.clone()).is_err());

        let mut wrong_recovery = recovery;
        wrong_recovery.origin_segment_digest = format!("sha256:{}", "2".repeat(64));
        assert!(validate_final_recovery(&report.component, &wrong_recovery).is_err());

        let mut missing = report.evidence_bundle.clone();
        missing.items.pop();
        missing.digest = missing
            .recompute_digest()
            .expect("recomputed partial digest");
        assert!(
            validate_complete_bundle(
                &report.component,
                &report.inspector,
                &report.final_recovery,
                &missing,
            )
            .is_err()
        );

        let mut duplicate = report.evidence_bundle.clone();
        duplicate.items.push(duplicate.items[0].clone());
        duplicate.items.sort_by(|left, right| {
            (left.role, left.evidence_id.as_str()).cmp(&(right.role, right.evidence_id.as_str()))
        });
        assert!(duplicate.recompute_digest().is_err());
    }

    #[tokio::test]
    async fn every_final_recovery_prefix_retries_to_exact_restored_truth() {
        for point in [
            G0FinalRecoveryFaultPoint::BeforeBackup,
            G0FinalRecoveryFaultPoint::AfterBackup,
            G0FinalRecoveryFaultPoint::BeforeRestore,
            G0FinalRecoveryFaultPoint::AfterRestore,
            G0FinalRecoveryFaultPoint::BeforeReopen,
            G0FinalRecoveryFaultPoint::AfterReopen,
        ] {
            let state = tempfile::tempdir().expect("temporary final recovery fault state");
            let component = run_wave5_g0_source_publication(state.path()).expect("G0 component");
            let inspector = run_g0_inspector_smoke(state.path())
                .await
                .expect("fresh pairing/open witness");
            assert!(matches!(
                run_final_recovery_with_fault(state.path(), &component, &inspector, Some(point)),
                Err(Wave5G0RootEvidenceError::Injected(actual)) if actual == point
            ));
            let recovered = run_final_recovery(state.path(), &component, &inspector)
                .unwrap_or_else(|error| {
                    panic!("exact final recovery retry after {point:?}: {error}")
                });
            validate_final_recovery(&component, &recovered).expect("valid final recovery");
            assert!(!recovered.full_offline_fault_walk);
        }
    }

    #[test]
    fn interrupted_original_root_quarantine_is_restored_before_component_replay() {
        let state = tempfile::tempdir().expect("temporary quarantine state");
        let root = state.path().join("g0-root-recovery-test");
        let unavailable = root.join("original-paths-unavailable");
        let catalog = state.path().join("catalog.sqlite");
        let blobs = state.path().join("blobs");
        let supervisor = state.path().join("supervisor");
        fs::create_dir_all(&blobs).expect("blob root");
        fs::create_dir_all(&supervisor).expect("supervisor root");
        fs::write(&catalog, b"catalog fixture").expect("catalog fixture");
        let guard = OriginalRootsGuard::hide(
            &[
                catalog.clone(),
                catalog.with_extension("sqlite-wal"),
                catalog.with_extension("sqlite-shm"),
                blobs.clone(),
                state.path().join("exports"),
                supervisor.clone(),
            ],
            &unavailable,
        )
        .expect("hide roots");
        std::mem::forget(guard);

        assert!(recover_interrupted_original_roots(state.path()).expect("recover roots"));
        assert_eq!(
            fs::read(&catalog).expect("catalog readback"),
            b"catalog fixture"
        );
        assert!(blobs.is_dir());
        assert!(supervisor.is_dir());
        assert!(
            fs::read_dir(&unavailable)
                .expect("empty quarantine")
                .next()
                .is_none()
        );
        assert!(!recover_interrupted_original_roots(state.path()).expect("idempotent retry"));
    }

    #[test]
    fn interrupted_original_root_quarantine_refuses_unknown_or_conflicting_entries() {
        let unknown = tempfile::tempdir().expect("unknown quarantine state");
        let unknown_quarantine = unknown
            .path()
            .join("g0-root-recovery-test/original-paths-unavailable");
        fs::create_dir_all(&unknown_quarantine).expect("unknown quarantine");
        fs::write(unknown_quarantine.join("99"), b"unknown").expect("unknown entry");
        assert!(recover_interrupted_original_roots(unknown.path()).is_err());

        let conflict = tempfile::tempdir().expect("conflicting quarantine state");
        let conflict_quarantine = conflict
            .path()
            .join("g0-root-recovery-test/original-paths-unavailable");
        fs::create_dir_all(&conflict_quarantine).expect("conflicting quarantine");
        fs::write(conflict_quarantine.join("00"), b"hidden catalog").expect("hidden catalog");
        fs::write(conflict.path().join("catalog.sqlite"), b"new catalog").expect("new catalog");
        assert!(recover_interrupted_original_roots(conflict.path()).is_err());
    }
}
